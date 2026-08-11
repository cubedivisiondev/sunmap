#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 PUDDY Inc.
"""SUNMAP SEO auditor - stdlib only, no third-party imports.

Audits the BUILT page (local files, or a live URL) and asserts the things that
actually break rich results and rankings. Prints a report and exits non-zero if
any check fails.

    python3 scripts/seo_check.py                      # local build, dev rules
    python3 scripts/seo_check.py --env prod           # local build, prod rules
    python3 scripts/seo_check.py --url https://sunmap.puddy.dev/
    python3 scripts/seo_check.py --strict             # warnings count as failures

Checks, per page:
  lang set, viewport set, exactly one h1, heading order sane (no skipped level),
  title present / length / unique across the site, meta description present /
  length / unique, canonical present + absolute + on the PROD host, Open Graph
  complete, Twitter Card complete, every referenced social image RESOLVABLE with
  its real pixel dimensions checked against the declared width/height, JSON-LD
  parseable with sane @context/@type, every <img> carrying alt text, inline SVG
  labelled or explicitly hidden, robots directive correct for the environment.

Site level:
  robots.txt present and consistent with the environment, sitemap.xml present,
  well formed, every <loc> on the prod host, resolving to a real page, with a
  valid non-future lastmod, and every indexable page present in the sitemap.

AGPL surface (a ship gate, not an SEO nicety):
  SUNMAP serves a Swiss Ephemeris WebAssembly build to every visitor, so it
  conveys object code under GPL-3.0 / AGPL-3.0 and owes the Corresponding
  Source from the same place. This asserts source.html exists and links the
  archive, the archive exists, is a readable gzip tar over the size floor, and
  contains everything the page claims - and, the check that matters, that the
  sunmap-worker.js inside it is byte-identical to the one being served. A stale
  archive is not Corresponding Source.

House style: ASCII hyphens only, text sigils only (no image emojis).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import io
import json
import os
import re
import struct
import sys
import tarfile
import urllib.error
import urllib.request
import zlib
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

PROD_HOST = "sunmap.puddystudios.com"
DEV_HOST = "sunmap.puddy.dev"
PROD_ORIGIN = f"https://{PROD_HOST}"

# Length budgets. Hard bounds fail; soft bounds warn.
TITLE_MIN, TITLE_SOFT_MAX, TITLE_MAX = 10, 60, 70
DESC_MIN, DESC_SOFT_MAX, DESC_MAX = 50, 160, 170

OG_REQUIRED = ["og:type", "og:site_name", "og:title", "og:description", "og:url", "og:image"]
OG_RECOMMENDED = ["og:image:width", "og:image:height", "og:image:alt"]
TW_REQUIRED = ["twitter:card", "twitter:title", "twitter:description", "twitter:image"]
TW_RECOMMENDED = ["twitter:site", "twitter:image:alt"]

# summary_large_image: Twitter wants >=300x157; Facebook wants >=1200x630.
MIN_OG_W, MIN_OG_H = 1200, 630
MAX_IMAGE_BYTES = 5 * 1024 * 1024

# --- icon policy ------------------------------------------------------------
# Transparency is asserted by ROLE, not by filename, so a renamed icon cannot
# slip past the check:
#
#   <link rel="icon">        a tab strip painted in the OS theme  -> TRANSPARENT
#   <link rel="apple-touch-icon">  iOS composites it itself       -> OPAQUE
#   manifest purpose=maskable      the launcher crops and fills   -> OPAQUE
#   manifest purpose=any           either is legitimate           -> unasserted
#
# The transparent rule exists because the set shipped opaque once: every PNG
# was rasterized with a baked #000 ground, which reads as a black chiclet on a
# light tab. Same policy STARMAP ships, verified against star_map/icons/.
APPLE_TOUCH_MIN = 180                 # iOS @3x home screen
MANIFEST_REQUIRED = ("name", "short_name", "start_url", "scope", "display")
DISPLAY_MODES = ("fullscreen", "standalone", "minimal-ui", "browser")
SHORT_NAME_MAX = 12                   # Android truncates a longer home-screen label
INSTALL_ICON_MIN = 192                # an installable PWA needs 192 and 512, purpose any
COLOR_RE = re.compile(r"^(#[0-9a-fA-F]{3,8}|rgba?\([^)]*\)|hsla?\([^)]*\)|[a-zA-Z]+)$")

# Dev surfaces sit behind a shared password gate; a 401/403 means "not audited",
# not "broken", and must not be reported as a content defect.
GATED = (401, 403)

# --- AGPL surface -------------------------------------------------------------
# SUNMAP serves a WebAssembly build of the Swiss Ephemeris to every visitor's
# browser. That is conveying object code, and GPL-3.0 section 6(d) - the clause
# that governs conveyance from a network server - wants the Corresponding Source
# reachable "in the same way through the same place" as the binary. An email
# address does not satisfy it. So these are not SEO checks that happen to live
# here; they are the ship gate. A SUNMAP that serves the engine without the
# archive is not a page with a broken link, it is a license violation.
#
# The check that actually earns its place is CORRESPONDS: the sunmap-worker.js
# INSIDE the archive must be byte-identical to the one the site serves. Every
# other file can be present and correct while the archive quietly describes a
# worker that shipped six weeks ago.
ENGINE_BINARY = "/vendor/sweph/swisseph.wasm"
SOURCE_PAGE = "/source.html"
SOURCE_ARCHIVE = "/source/corresponding-source.tar.gz"
SOURCE_README = "/source/README.md"
ARCHIVE_ROOT = "corresponding-source/"
LICENSE_TEXTS = {
    "/source/AGPL-3.0.txt": "GNU AFFERO GENERAL PUBLIC LICENSE",
    "/source/GPL-3.0.txt": "GNU GENERAL PUBLIC LICENSE",
}
# Not a guess at the right size: the archive has to carry a 2.1 MB C library, so
# anything under a megabyte is a truncated upload or an LFS pointer, not source.
ARCHIVE_MIN_BYTES = 1_000_000
LICENSE_TEXT_MIN_BYTES = 20_000        # the real GNU texts are ~34 KB
README_MIN_BYTES = 1_000
# Paths the archive must contain, relative to ARCHIVE_ROOT. A directory entry is
# matched by prefix, a file by exact name.
ARCHIVE_REQUIRED = (
    "README.md",
    "AGPL-3.0.txt",
    "GPL-3.0.txt",
    "sunmap-worker.js",
    "swisseph-2.10.03/",
    "swisseph-wasm-0.0.5-npm/wasm/swisseph.wasm",
    "swisseph-wasm-0.0.5-npm/wasm/swisseph.js",
    "swisseph-wasm-main/compile.sh",
)
# Served files that link the engine. Each must be in the archive, byte-identical.
CORRESPONDS = ("sunmap-worker.js",)
OFFER_CONTACT = "legal@puddystudios.com"

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
SIGIL = {PASS: "✓", WARN: "⚠", FAIL: "✗"}  # check / warning / cross

HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")


# --------------------------------------------------------------------- parse --
class PageParser(HTMLParser):
    """Collects only what the audit needs. Content inside <svg> is ignored for
    heading/title purposes so mascot geometry cannot spoof document structure."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lang: str | None = None
        self.title: str | None = None
        self.metas: list[dict] = []
        self.links: list[dict] = []
        self.headings: list[tuple[int, str]] = []
        self.imgs: list[dict] = []
        self.svgs: list[dict] = []
        self.ldjson: list[str] = []
        self._svg_depth = 0
        self._cap: str | None = None
        self._buf: list[str] = []

    # void + self-closing tags route through the same handler
    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag in ("svg",):
            self._svg_depth = max(0, self._svg_depth - 1)

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "svg":
            self._svg_depth += 1
            self.svgs.append(a)
            return
        if self._svg_depth:
            return
        if tag == "html":
            self.lang = a.get("lang")
        elif tag == "meta":
            self.metas.append(a)
        elif tag == "link":
            self.links.append(a)
        elif tag == "img":
            self.imgs.append(a)
        elif tag == "title" and self.title is None:
            self._cap, self._buf = "title", []
        elif tag in HEADING_TAGS:
            # A previous heading left unclosed would otherwise swallow this one.
            self._flush_heading()
            self._cap, self._buf = tag, []
        elif tag == "script" and a.get("type", "").strip().lower() == "application/ld+json":
            self._cap, self._buf = "ld", []

    def _flush_heading(self) -> None:
        """Record a pending heading capture, taking the level from the START tag.

        Deliberately tolerant of malformed markup. An exact start/end match would
        silently DROP a heading written as <h1>x</h2>, and a dropped heading is a
        false PASS: the auditor would report "exactly one h1" on a page browsers
        and Googlebot parse as having two, because the HTML5 tree builder recovers
        from mismatched tags. Caught by mutation test C."""
        if self._cap in HEADING_TAGS:
            self.headings.append(
                (int(self._cap[1]), re.sub(r"\s+", " ", "".join(self._buf).strip())))
            self._cap, self._buf = None, []

    def close(self):
        super().close()
        self._flush_heading()   # a heading never closed at all still counts

    def handle_endtag(self, tag):
        if tag == "svg":
            self._svg_depth = max(0, self._svg_depth - 1)
            return
        if self._svg_depth or self._cap is None:
            return
        text = "".join(self._buf).strip()
        if self._cap == "title" and tag == "title":
            self.title = re.sub(r"\s+", " ", text)
        elif self._cap == "ld" and tag == "script":
            self.ldjson.append(text)
        elif self._cap in HEADING_TAGS and tag in HEADING_TAGS:
            # Level from the start tag, not this end tag - see _flush_heading.
            self.headings.append((int(self._cap[1]), re.sub(r"\s+", " ", text)))
        else:
            return
        self._cap, self._buf = None, []

    def handle_data(self, data):
        if self._cap is not None:
            self._buf.append(data)

    # helpers -----------------------------------------------------------------
    def meta(self, key: str) -> str | None:
        key = key.lower()
        for m in self.metas:
            if m.get("property", "").lower() == key or m.get("name", "").lower() == key:
                return (m.get("content") or "").strip()
        return None

    def link(self, rel: str) -> str | None:
        for ln in self.links:
            if rel in ln.get("rel", "").lower().split():
                return (ln.get("href") or "").strip()
        return None


# ------------------------------------------------------------------- sources --
class Source:
    """Reads pages and binary assets from local disk or over HTTP."""

    def __init__(self, root: str | None, base_url: str | None):
        self.root = root
        self.base_url = base_url.rstrip("/") + "/" if base_url else None
        self.remote = base_url is not None
        self._cache: dict[str, tuple[int, bytes, str]] = {}

    def _local_path(self, path: str) -> str:
        p = urlparse(path).path if "://" in path else path
        p = p.split("?")[0].split("#")[0]
        if p.endswith("/") or p == "":
            p += "index.html"
        return os.path.join(self.root, p.lstrip("/"))

    def get(self, path: str) -> tuple[int, bytes, str]:
        """Returns (status, body, note). status 200 means found."""
        if path in self._cache:
            return self._cache[path]
        if self.remote:
            url = path if "://" in path else urljoin(self.base_url, path.lstrip("/"))
            req = urllib.request.Request(url, headers={"User-Agent": "PUDDY-seo-check/1.0"})
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    out = (r.status, r.read(), url)
            except urllib.error.HTTPError as e:
                out = (e.code, b"", url)
            except Exception as e:  # DNS, TLS, timeout
                out = (0, b"", f"{url} ({type(e).__name__}: {e})")
        else:
            fp = self._local_path(path)
            if os.path.isfile(fp):
                with open(fp, "rb") as fh:
                    out = (200, fh.read(), fp)
            else:
                out = (404, b"", fp)
        self._cache[path] = out
        return out


def image_size(blob: bytes) -> tuple[int, int] | None:
    """Real pixel dimensions from the file header. PNG, JPEG, GIF, WebP."""
    if blob[:8] == b"\x89PNG\r\n\x1a\n" and blob[12:16] == b"IHDR":
        return struct.unpack(">II", blob[16:24])
    if blob[:3] == b"\xff\xd8\xff":
        i = 2
        while i + 9 < len(blob):
            if blob[i] != 0xFF:
                i += 1
                continue
            marker, seglen = blob[i + 1], struct.unpack(">H", blob[i + 2:i + 4])[0]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB):
                h, w = struct.unpack(">HH", blob[i + 5:i + 9])
                return w, h
            i += 2 + seglen
        return None
    if blob[:6] in (b"GIF87a", b"GIF89a"):
        return struct.unpack("<HH", blob[6:10])
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP" and blob[12:16] == b"VP8 ":
        return struct.unpack("<HH", blob[26:30])
    return None


# ---------------------------------------------------------------- icon probes --
# An icon audit that stops at the header is not an audit. A colour-type-6 PNG
# whose alpha is 255 everywhere is opaque; a colour-type-3 PNG can be
# transparent through tRNS. Only the decoded samples settle it, so the alpha
# census below inflates the IDAT and unfilters it.
#
# The same decoder lives in scripts/make_icons.py, deliberately. This file is
# the shipped auditor: it has to run against a live URL from any checkout with
# nothing beside it, so it stays one self-contained stdlib script. Fix a bug in
# one of the two and fix it in the other.

def png_alpha(blob: bytes) -> dict | None:
    """Dimensions plus a real alpha census. None if the bytes are not a PNG."""
    if blob[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    w = h = depth = ctype = interlace = 0
    idat, trns = bytearray(), None
    i = 8
    while i + 8 <= len(blob):
        (n,) = struct.unpack(">I", blob[i:i + 4])
        kind, data = blob[i + 4:i + 8], blob[i + 8:i + 8 + n]
        if kind == b"IHDR":
            w, h, depth, ctype, _c, _f, interlace = struct.unpack(">IIBBBBB", data)
        elif kind == b"IDAT":
            idat += data
        elif kind == b"tRNS":
            trns = data
        i += 12 + n

    out = {"w": w, "h": h, "ctype": ctype, "alpha_channel": ctype in (4, 6),
           "trns": trns is not None, "decoded": False, "why": "",
           "min_alpha": None, "n_transparent": 0, "corners_transparent": None}
    chans = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype)
    if interlace:
        out["why"] = "Adam7 interlaced"
        return out
    if chans is None or depth not in (8, 16) or w == 0:
        out["why"] = f"colour type {ctype} at depth {depth}"
        return out
    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error as e:
        out["why"] = f"IDAT will not inflate ({e})"
        return out
    bpp, = (chans * (depth // 8),)
    stride = w * bpp
    if len(raw) < h * (stride + 1):
        out["why"] = "IDAT short for the declared dimensions"
        return out

    prev, rows, pos = bytearray(stride), [], 0
    for y in range(h):
        ft = raw[pos]
        line = bytearray(raw[pos + 1:pos + 1 + stride])
        pos += 1 + stride
        if ft == 1:                                     # Sub
            for x in range(bpp, stride):
                line[x] = (line[x] + line[x - bpp]) & 0xFF
        elif ft == 2:                                   # Up
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 0xFF
        elif ft == 3:                                   # Average
            for x in range(stride):
                a = line[x - bpp] if x >= bpp else 0
                line[x] = (line[x] + ((a + prev[x]) >> 1)) & 0xFF
        elif ft == 4:                                   # Paeth
            for x in range(stride):
                a = line[x - bpp] if x >= bpp else 0
                c = prev[x - bpp] if x >= bpp else 0
                b = prev[x]
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pr) & 0xFF
        elif ft != 0:                                   # None
            out["why"] = f"unknown PNG filter {ft} on row {y}"
            return out
        rows.append(line)
        prev = line

    if ctype in (4, 6):
        aoff = (chans - 1) * (depth // 8)
        at = lambda x, y: rows[y][x * bpp + aoff]
    elif ctype == 3 and trns is not None:
        tbl = list(trns) + [255] * 256
        at = lambda x, y: tbl[rows[y][x]]
    else:
        out.update(decoded=True, min_alpha=255, n_transparent=0, corners_transparent=False)
        return out
    alphas = [at(x, y) for y in range(h) for x in range(w)]
    corners = ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))
    out.update(decoded=True, min_alpha=min(alphas),
               n_transparent=sum(1 for a in alphas if a == 0),
               corners_transparent=all(at(x, y) == 0 for x, y in corners))
    return out


def ico_probe(blob: bytes) -> list[dict] | None:
    """Every image in a .ico, with the alpha census of each PNG payload."""
    if len(blob) < 6:
        return None
    reserved, kind, n = struct.unpack("<HHH", blob[:6])
    if reserved != 0 or kind != 1 or n == 0 or len(blob) < 6 + 16 * n:
        return None
    out = []
    for i in range(n):
        w, h, _cc, _r, _pl, bits, size, off = struct.unpack(
            "<BBBBHHII", blob[6 + i * 16:22 + i * 16])
        payload = blob[off:off + size]
        entry = {"w": w or 256, "h": h or 256, "bits": bits,
                 "png": payload[:8] == b"\x89PNG\r\n\x1a\n", "alpha": None}
        if entry["png"]:
            entry["alpha"] = png_alpha(payload)
        out.append(entry)
    return out


_SVG_LEN = re.compile(r'(width|height)="([\d.]+)(%?)"')


def svg_opaque_ground(text: str) -> str | None:
    """The full-bleed <rect> that turns a transparent mark into a chiclet.

    Returns the offending tag, or None. Cheap to reintroduce (one line in a
    generator) and invisible in a directory listing, so it gets its own check."""
    vb = re.search(r'viewBox="[\d.\-]+ [\d.\-]+ ([\d.]+) ([\d.]+)"', text)
    side_w = float(vb.group(1)) if vb else 0.0
    side_h = float(vb.group(2)) if vb else 0.0
    for m in re.finditer(r"<rect\b[^>]*>", text):
        tag = m.group(0)
        fill = re.search(r'fill="([^"]+)"', tag)
        if fill and fill.group(1).strip().lower() in ("none", "transparent"):
            continue
        if fill is None and "fill:" not in tag:
            continue        # no fill at all paints black, but only if it has size
        dims = {k: (float(v), pct) for k, v, pct in _SVG_LEN.findall(tag)}
        wv, wp = dims.get("width", (0.0, ""))
        hv, hp = dims.get("height", (0.0, ""))
        if (wp == "%" and wv >= 100) or (side_w and wv >= side_w):
            if (hp == "%" and hv >= 100) or (side_h and hv >= side_h):
                return tag
    return None


# -------------------------------------------------------------------- report --
class Report:
    def __init__(self, strict: bool) -> None:
        self.rows: list[tuple[str, str, str, str]] = []
        self.strict = strict

    def add(self, section: str, status: str, name: str, detail: str) -> None:
        self.rows.append((section, status, name, detail))

    def ok(self, s, n, d=""):
        self.add(s, PASS, n, d)

    def warn(self, s, n, d=""):
        self.add(s, WARN, n, d)

    def fail(self, s, n, d=""):
        self.add(s, FAIL, n, d)

    def check(self, s, cond, n, ok_detail="", bad_detail="", soft=False):
        if cond:
            self.ok(s, n, ok_detail)
        elif soft:
            self.warn(s, n, bad_detail)
        else:
            self.fail(s, n, bad_detail)
        return cond

    @property
    def failures(self):
        return [r for r in self.rows if r[1] == FAIL]

    @property
    def warnings(self):
        return [r for r in self.rows if r[1] == WARN]

    def render(self) -> int:
        width = max((len(r[2]) for r in self.rows), default=10)
        current = None
        for section, status, name, detail in self.rows:
            if section != current:
                print(f"\n{section}")
                print("-" * max(len(section), 60))
                current = section
            line = f"  {SIGIL[status]} {name.ljust(width)}"
            print(f"{line}  {detail}" if detail else line)
        n_pass = len(self.rows) - len(self.failures) - len(self.warnings)
        print("\n" + "=" * 60)
        print(f"SUMMARY  {n_pass} passed  {len(self.warnings)} warnings  {len(self.failures)} failed")
        if self.failures:
            print("\nFAILURES")
            for section, _s, name, detail in self.failures:
                print(f"  {SIGIL[FAIL]} [{section}] {name} - {detail}")
        if self.warnings:
            print("\nWARNINGS")
            for section, _s, name, detail in self.warnings:
                print(f"  {SIGIL[WARN]} [{section}] {name} - {detail}")
        bad = len(self.failures) + (len(self.warnings) if self.strict else 0)
        print("\n" + ("RESULT: FAIL" if bad else "RESULT: PASS"))
        return 1 if bad else 0


# --------------------------------------------------------------------- checks --
def audit_image(rep: Report, sec: str, label: str, url: str, src: Source,
                declared: tuple[str | None, str | None], env: str,
                canonical_host: str | None, min_w=0, min_h=0) -> None:
    """Resolvability is the point: a social tag pointing at a 404 is worse than
    no social tag, because the platform caches the miss."""
    if not url:
        rep.fail(sec, f"{label} url", "missing")
        return
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        rep.fail(sec, f"{label} url", f"not absolute: {url} (crawlers require an absolute URL)")
        return

    if canonical_host and parsed.netloc != canonical_host:
        detail = f"image host {parsed.netloc} != canonical host {canonical_host} ({url})"
        # On prod this is a real defect: the indexable page advertises an image
        # served from a different (gated) host.
        (rep.fail if env == "prod" else rep.warn)(sec, f"{label} host", detail)
    else:
        rep.ok(sec, f"{label} host", parsed.netloc)

    status, blob, note = src.get(parsed.path if not src.remote else url)
    if status != 200 or not blob:
        rep.fail(sec, f"{label} resolves", f"HTTP/FS {status} for {note}")
        return

    size = image_size(blob)
    kb = len(blob) / 1024
    if size is None:
        rep.warn(sec, f"{label} resolves", f"{note} found ({kb:.0f} KB) but format not recognised")
        return
    w, h = size
    rep.ok(sec, f"{label} resolves", f"{w}x{h}, {kb:.0f} KB")

    if len(blob) > MAX_IMAGE_BYTES:
        rep.fail(sec, f"{label} bytes", f"{kb/1024:.1f} MB exceeds the 5 MB card limit")
    if min_w and (w < min_w or h < min_h):
        rep.fail(sec, f"{label} pixels", f"{w}x{h} is under the {min_w}x{min_h} minimum")
    elif min_w:
        rep.ok(sec, f"{label} pixels", f"{w}x{h} >= {min_w}x{min_h}")

    dw, dh = declared
    if dw and dh:
        if (str(w), str(h)) == (dw, dh):
            rep.ok(sec, f"{label} declared size", f"{dw}x{dh} matches the file")
        else:
            rep.fail(sec, f"{label} declared size",
                     f"tags say {dw}x{dh} but the file is {w}x{h}")


def audit_page(rep: Report, page_path: str, body: bytes, src: Source, env: str,
               all_titles: dict, all_descs: dict, role: str, robots_blocks_all: bool) -> None:
    """role: 'primary'   - an indexable content page, full social + schema stack
             'secondary' - a real page nobody shares (licenses, colophon)
             'utility'   - 404 and friends, structural checks only

    The role model exists so the audit does not cry wolf: STARMAP, the house
    standard, ships no canonical and no Open Graph on its 404 or source pages,
    so demanding them here would be inventing a rule the house does not keep."""
    sec = f"PAGE {page_path} [{role}]"
    p = PageParser()
    try:
        p.feed(body.decode("utf-8", "replace"))
        p.close()   # flush any heading left open at EOF
    except Exception as e:
        rep.fail(sec, "parse", f"HTML parse error: {e}")
        return

    # --- document basics ----------------------------------------------------
    rep.check(sec, bool(p.lang), "lang", f'html lang="{p.lang}"', "no lang attribute on <html>")
    vp = p.meta("viewport")
    rep.check(sec, bool(vp) and "width=device-width" in (vp or ""), "viewport",
              vp or "", f"viewport missing or lacks width=device-width: {vp!r}")
    charset = any("charset" in m for m in p.metas)
    rep.check(sec, charset, "charset", "declared", "no <meta charset>")

    # --- title --------------------------------------------------------------
    t = p.title or ""
    if not t:
        rep.fail(sec, "title", "missing <title>")
    else:
        n = len(t)
        if n < TITLE_MIN or n > TITLE_MAX:
            rep.fail(sec, "title length", f"{n} chars, outside {TITLE_MIN}-{TITLE_MAX}: {t!r}")
        elif n > TITLE_SOFT_MAX:
            rep.warn(sec, "title length", f"{n} chars, over the {TITLE_SOFT_MAX} soft cap - SERP truncation likely")
        else:
            rep.ok(sec, "title length", f"{n} chars")
        first = all_titles.setdefault(t.lower(), page_path)
        rep.check(sec, first == page_path, "title unique",
                  "unique across the site", f"duplicate of {first}: {t!r}")

    # --- description --------------------------------------------------------
    d = p.meta("description") or ""
    if not d:
        if role == "utility":
            rep.ok(sec, "description", "not required on a utility page")
        else:
            rep.fail(sec, "description", "missing meta description")
    else:
        n = len(d)
        if n < DESC_MIN or n > DESC_MAX:
            rep.fail(sec, "description length",
                     f"{n} chars, outside {DESC_MIN}-{DESC_MAX} - Google rewrites or truncates")
        elif n > DESC_SOFT_MAX:
            rep.warn(sec, "description length", f"{n} chars, over the {DESC_SOFT_MAX} soft cap")
        else:
            rep.ok(sec, "description length", f"{n} chars")
        first = all_descs.setdefault(d.lower(), page_path)
        rep.check(sec, first == page_path, "description unique",
                  "unique across the site", f"duplicate of {first}")

    # --- canonical ----------------------------------------------------------
    canon = p.link("canonical")
    canonical_host = None
    if not canon:
        if role == "utility":
            rep.ok(sec, "canonical", "not required on a utility page")
        else:
            rep.fail(sec, "canonical", "no <link rel=canonical>")
    else:
        cp = urlparse(canon)
        canonical_host = cp.netloc
        rep.check(sec, cp.scheme == "https", "canonical scheme", "https",
                  f"canonical is not https: {canon}")
        rep.check(sec, cp.netloc == PROD_HOST, "canonical host", PROD_HOST,
                  f"canonical points at {cp.netloc or '(relative)'}, expected the prod host {PROD_HOST}")
        expect = "/" + page_path.lstrip("/")
        expect = "/" if expect == "/index.html" else expect
        rep.check(sec, cp.path in (expect, expect.rstrip(".html")), "canonical path",
                  cp.path, f"canonical path {cp.path} does not match the page location {expect}")

    # --- robots per environment --------------------------------------------
    robots = (p.meta("robots") or "").lower()
    noindex = "noindex" in robots
    if env == "prod":
        if role == "utility":
            rep.check(sec, noindex, "robots meta", robots,
                      "a 404 page should carry noindex", soft=True)
        else:
            rep.check(sec, not noindex, "robots meta",
                      robots or "(absent, indexable)",
                      f"prod page carries noindex: {robots!r} - it will never rank")
    else:
        # robots.txt Disallow already stops the crawl, so a missing meta here is
        # a consistency gap rather than an exposure. Report it either way, but
        # only fail the run when nothing else is holding the door shut.
        rep.check(sec, noindex, "robots meta", robots,
                  "dev page is missing noindex"
                  + (" (robots.txt Disallow still blocks it, so this is a consistency gap"
                     " not an exposure)" if robots_blocks_all
                     else " and robots.txt does NOT block the site - it can be indexed"),
                  soft=robots_blocks_all)

    # --- headings -----------------------------------------------------------
    h1s = [h for h in p.headings if h[0] == 1]
    rep.check(sec, len(h1s) == 1, "h1 count",
              f'exactly one: "{h1s[0][1][:48]}"' if len(h1s) == 1 else "",
              f"{len(h1s)} h1 elements (need exactly 1)")
    skips = []
    prev = 0
    for lvl, txt in p.headings:
        if prev and lvl > prev + 1:
            skips.append(f"h{prev} -> h{lvl} ({txt[:32]})")
        prev = lvl
    rep.check(sec, not skips, "heading order",
              f"{len(p.headings)} headings, no skipped levels",
              "skipped heading levels: " + "; ".join(skips))

    # --- images and inline svg ---------------------------------------------
    missing_alt = [i.get("src", "(no src)") for i in p.imgs if not i.get("alt", "").strip()]
    if p.imgs:
        rep.check(sec, not missing_alt, "img alt",
                  f"all {len(p.imgs)} <img> have alt text",
                  f"{len(missing_alt)} <img> without alt: {missing_alt[:3]}")
    else:
        rep.ok(sec, "img alt", "no <img> elements on the page")
    unlabelled = [s for s in p.svgs
                  if not (s.get("aria-hidden") or s.get("aria-label") or s.get("role") == "img")]
    rep.check(sec, not unlabelled, "svg labelled",
              f"all {len(p.svgs)} inline <svg> hidden or labelled",
              f"{len(unlabelled)} of {len(p.svgs)} inline <svg> neither aria-hidden nor labelled"
              + (f" (first: viewBox={unlabelled[0].get('viewbox', '?')})" if unlabelled else ""),
              soft=True)

    # --- social stack -------------------------------------------------------
    # Utility pages are exempt outright. Secondary pages get warnings, not
    # failures: the house standard does not card them.
    has_any_og = any(p.meta(k) for k in OG_REQUIRED)
    has_any_tw = any(p.meta(k) for k in TW_REQUIRED)
    if role == "utility":
        rep.ok(sec, "social tags", "not required on a utility page")
    elif not has_any_og and not has_any_tw:
        (rep.warn if role == "secondary" else rep.fail)(
            sec, "social tags",
            "no Open Graph or Twitter tags - the page shares as a bare link")
    else:
        soft = role == "secondary"
        missing = [k for k in OG_REQUIRED if not p.meta(k)]
        rep.check(sec, not missing, "og complete",
                  f"all {len(OG_REQUIRED)} required og tags present",
                  f"missing og tags: {missing}", soft=soft)
        soft_missing = [k for k in OG_RECOMMENDED if not p.meta(k)]
        rep.check(sec, not soft_missing, "og recommended",
                  "width, height and alt all present",
                  f"missing recommended og tags: {soft_missing}", soft=True)
        og_url = p.meta("og:url")
        if og_url and canon:
            rep.check(sec, og_url.rstrip("/") == canon.rstrip("/"), "og:url matches canonical",
                      og_url, f"og:url {og_url} != canonical {canon}", soft=soft)

        tmissing = [k for k in TW_REQUIRED if not p.meta(k)]
        rep.check(sec, not tmissing, "twitter complete",
                  f"all {len(TW_REQUIRED)} required twitter tags present",
                  f"missing twitter tags: {tmissing}", soft=soft)
        tsoft = [k for k in TW_RECOMMENDED if not p.meta(k)]
        rep.check(sec, not tsoft, "twitter recommended", "site and image:alt present",
                  f"missing recommended twitter tags: {tsoft}", soft=True)
        card = p.meta("twitter:card")
        rep.check(sec, card in ("summary", "summary_large_image", "app", "player"),
                  "twitter:card valid", card or "", f"invalid twitter:card: {card!r}", soft=soft)

        audit_image(rep, sec, "og:image", p.meta("og:image") or "", src,
                    (p.meta("og:image:width"), p.meta("og:image:height")),
                    env, canonical_host, MIN_OG_W, MIN_OG_H)
        tw_img = p.meta("twitter:image") or ""
        if tw_img and tw_img == (p.meta("og:image") or ""):
            rep.ok(sec, "twitter:image", "same asset as og:image, already verified")
        else:
            audit_image(rep, sec, "twitter:image", tw_img, src, (None, None),
                        env, canonical_host, 300, 157)

    # --- json-ld ------------------------------------------------------------
    if not p.ldjson:
        if role == "primary":
            rep.warn(sec, "json-ld", "no JSON-LD block - rich results unavailable")
        else:
            rep.ok(sec, "json-ld", f"not required on a {role} page")
    for i, raw in enumerate(p.ldjson):
        tag = f"json-ld[{i}]"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            rep.fail(sec, tag, f"invalid JSON at line {e.lineno} col {e.colno}: {e.msg}")
            continue
        nodes = data.get("@graph") if isinstance(data, dict) and "@graph" in data else data
        nodes = nodes if isinstance(nodes, list) else [nodes]
        if not (isinstance(data, dict) and data.get("@context")):
            rep.fail(sec, f"{tag} @context", "missing @context")
            continue
        types, untyped = [], 0
        for node in nodes:
            if not isinstance(node, dict):
                untyped += 1
                continue
            ty = node.get("@type")
            if not ty:
                untyped += 1
            else:
                types.extend(ty if isinstance(ty, list) else [ty])
        if untyped:
            rep.fail(sec, f"{tag} @type", f"{untyped} node(s) without @type")
        else:
            # A node may carry an array @type (["WebPage","CollectionPage"]), so
            # there can be more type NAMES than nodes. Any truncation is marked -
            # an unmarked cut silently hid FAQPage, the node driving rich results.
            shown = ", ".join(types[:12]) + (f", +{len(types) - 12} more" if len(types) > 12 else "")
            rep.ok(sec, tag, f"valid, {len(nodes)} node(s): {shown}")


UTILITY_PAGES = {"404.html", "500.html", "50x.html", "offline.html"}


def read_sitemap_paths(src: Source) -> set[str]:
    """Best-effort path set, read before the page audits so roles can be assigned.
    Detailed sitemap validation still happens in audit_site()."""
    status, blob, _note = src.get("/sitemap.xml")
    if status != 200:
        return set()
    try:
        root = ElementTree.fromstring(blob)
    except ElementTree.ParseError:
        return set()
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    out: set[str] = set()
    for u in (root.findall("s:url", ns) or root.findall("url")):
        el = u.find("s:loc", ns)
        el = el if el is not None else u.find("loc")
        if el is not None and el.text:
            out.add(urlparse(el.text.strip()).path or "/")
    return out


def page_role(page: str, sitemap_paths: set[str]) -> str:
    base = os.path.basename(page)
    if base in UTILITY_PAGES:
        return "utility"
    want = "/" if base == "index.html" else "/" + page.lstrip("/")
    if base == "index.html" or want in sitemap_paths:
        return "primary"
    return "secondary"


def audit_site(rep: Report, src: Source, env: str, pages: list[str],
               sitemap_paths: set[str]) -> None:
    sec = "SITE"

    # --- robots.txt ---------------------------------------------------------
    status, blob, note = src.get("/robots.txt")
    if status in GATED:
        # The dev surfaces sit behind a shared password gate. Reporting the gate
        # once beats emitting a cascade of derived failures about a file we were
        # never allowed to read.
        rep.warn(sec, "robots.txt", f"HTTP {status} - behind the auth gate, cannot audit ({note})")
        rep.warn(sec, "sitemap.xml", f"HTTP {status} - behind the auth gate, cannot audit")
        return
    if status != 200:
        rep.fail(sec, "robots.txt", f"not found ({note})")
        txt = ""
    else:
        txt = blob.decode("utf-8", "replace")
        rep.ok(sec, "robots.txt", f"present, {len(txt.splitlines())} lines")
    lower = txt.lower()
    disallow_all = bool(re.search(r"^\s*disallow:\s*/\s*$", txt, re.M | re.I))
    sitemap_line = re.search(r"^\s*sitemap:\s*(\S+)", txt, re.M | re.I)
    if env == "prod":
        rep.check(sec, not disallow_all, "robots.txt crawlable",
                  "no blanket Disallow", "robots.txt has 'Disallow: /' - prod would be delisted")
        rep.check(sec, "allow:" in lower or not disallow_all, "robots.txt allow",
                  "crawlers permitted", "no Allow directive and crawling is blocked")
        if rep.check(sec, bool(sitemap_line), "robots.txt sitemap",
                     "advertised", "no 'Sitemap:' line - prod robots.txt must advertise the sitemap"):
            declared = sitemap_line.group(1)
            expected = f"{PROD_ORIGIN}/sitemap.xml"
            rep.check(sec, declared == expected, "robots.txt sitemap url", declared,
                      f"sitemap line is {declared}, expected {expected}")
    else:
        rep.check(sec, disallow_all, "robots.txt blocks dev", "Disallow: /",
                  "dev robots.txt does not block crawling - the gated build could get indexed")

    # --- sitemap.xml --------------------------------------------------------
    status, blob, note = src.get("/sitemap.xml")
    if status != 200:
        rep.fail(sec, "sitemap.xml", f"not found ({note})")
        return
    try:
        root = ElementTree.fromstring(blob)
    except ElementTree.ParseError as e:
        rep.fail(sec, "sitemap.xml", f"malformed XML: {e}")
        return
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = root.findall("s:url", ns) or root.findall("url")
    rep.ok(sec, "sitemap.xml", f"well formed, {len(urls)} <url> entries")

    today = _dt.date.today()
    listed: list[str] = []
    for u in urls:
        loc_el = u.find("s:loc", ns)
        loc_el = loc_el if loc_el is not None else u.find("loc")
        loc = (loc_el.text or "").strip() if loc_el is not None else ""
        listed.append(loc)
        parsed = urlparse(loc)
        rep.check(sec, parsed.netloc == PROD_HOST, f"sitemap host {loc[:52]}",
                  PROD_HOST, f"sitemap entry is on {parsed.netloc}, expected {PROD_HOST}")
        st, _b, n = src.get(parsed.path or "/")
        rep.check(sec, st == 200, f"sitemap target {parsed.path or '/'}",
                  "resolves to a real page", f"sitemap lists {loc} but {n} is missing (HTTP/FS {st})")
        lm_el = u.find("s:lastmod", ns)
        lm_el = lm_el if lm_el is not None else u.find("lastmod")
        if lm_el is None:
            rep.warn(sec, f"sitemap lastmod {parsed.path or '/'}", "no <lastmod>")
        else:
            raw = (lm_el.text or "").strip()
            try:
                when = _dt.date.fromisoformat(raw[:10])
                rep.check(sec, when <= today, f"sitemap lastmod {parsed.path or '/'}", raw,
                          f"lastmod {raw} is in the future (today is {today.isoformat()})")
            except ValueError:
                rep.fail(sec, f"sitemap lastmod {parsed.path or '/'}", f"unparseable date: {raw!r}")

    # Every indexable page should be listed. Utility pages are excluded by
    # design; secondary pages warn rather than fail, since the house standard
    # deliberately keeps colophon pages out of the sitemap.
    listed_paths = {urlparse(u).path or "/" for u in listed}
    for page in pages:
        role = page_role(page, sitemap_paths)
        if role == "utility":
            continue
        want = "/" if os.path.basename(page) == "index.html" else "/" + page.lstrip("/")
        if want in listed_paths or want.rstrip(".html") in listed_paths:
            rep.ok(sec, f"sitemap covers {want}", "listed")
        elif role == "primary":
            rep.fail(sec, f"sitemap covers {want}",
                     f"{want} is a primary page but is absent from sitemap.xml")
        else:
            rep.warn(sec, f"sitemap covers {want}",
                     f"{want} exists but is not in sitemap.xml (secondary page)")


# --------------------------------------------------------------- agpl surface --
def audit_agpl(rep: Report, src: Source) -> None:
    """Assert the corresponding-source offer exists, resolves, and corresponds.

    Runs in both environments. The obligation attaches to serving the binary, so
    it applies on the dev host exactly as it does on prod - the only difference
    is that a gated dev surface cannot be read, which is reported as unaudited
    rather than as compliance."""
    sec = "AGPL"

    st, engine, note = src.get(ENGINE_BINARY)
    if st in GATED:
        rep.warn(sec, "engine served", f"HTTP {st} - behind the auth gate, AGPL surface not audited")
        return
    rep.check(sec, st == 200, "engine served",
              f"{len(engine):,} bytes at {ENGINE_BINARY}",
              f"{ENGINE_BINARY} did not resolve (HTTP/FS {st}, {note}) - SUNMAP cannot compute "
              "anything without it, and if it moved the source offer now points at nothing")

    # --- the offer page -----------------------------------------------------
    st, blob, note = src.get(SOURCE_PAGE)
    page = blob.decode("utf-8", "replace") if st == 200 else ""
    if not rep.check(sec, st == 200, "source.html",
                     f"present, {len(blob):,} bytes",
                     f"{SOURCE_PAGE} is MISSING (HTTP/FS {st}, {note}) - the binary is conveyed "
                     "with no corresponding-source offer"):
        return
    rep.check(sec, SOURCE_ARCHIVE.lstrip("/") in page, "source.html links archive",
              "links the corresponding-source archive",
              f"{SOURCE_PAGE} does not link {SOURCE_ARCHIVE} - the offer names no source")
    rep.check(sec, SOURCE_README.lstrip("/") in page, "source.html links README",
              "links the manifest of contents",
              f"{SOURCE_PAGE} does not link {SOURCE_README}")
    for path in LICENSE_TEXTS:
        rep.check(sec, path.lstrip("/") in page, f"source.html links {os.path.basename(path)}",
                  "linked", f"{SOURCE_PAGE} does not link {path}")
    rep.check(sec, OFFER_CONTACT in page, "written offer", OFFER_CONTACT,
              f"{SOURCE_PAGE} carries no contact for source requests")
    rep.check(sec, "AGPL-3.0" in page, "license named", "AGPL-3.0 named on the page",
              f"{SOURCE_PAGE} never names the license it is complying with")
    for name in CORRESPONDS:
        rep.check(sec, name in page, f"source.html names {name}",
                  "named", f"{SOURCE_PAGE} does not name {name}, which links the engine")

    # --- the offer is reachable from the product ----------------------------
    st, blob, _n = src.get("/")
    if st == 200:
        home = blob.decode("utf-8", "replace")
        rep.check(sec, "source.html" in home, "home links source.html",
                  "the offer is reachable from the page that serves the engine",
                  "index.html does not link source.html - AGPL-3.0 section 13 wants the offer "
                  "prominent, not merely present at a guessable URL")

    # --- license texts ------------------------------------------------------
    for path, title in LICENSE_TEXTS.items():
        st, blob, note = src.get(path)
        label = os.path.basename(path)
        if not rep.check(sec, st == 200, label, f"{len(blob):,} bytes",
                         f"{path} is MISSING (HTTP/FS {st}, {note})"):
            continue
        text = blob.decode("utf-8", "replace")
        rep.check(sec, len(blob) >= LICENSE_TEXT_MIN_BYTES and title in text.upper(),
                  f"{label} genuine", f"carries the {title} text",
                  f"{path} is {len(blob):,} bytes and does not contain '{title}' - "
                  "that is a stub, not the license")

    # --- the README ---------------------------------------------------------
    st, blob, note = src.get(SOURCE_README)
    if rep.check(sec, st == 200 and len(blob) >= README_MIN_BYTES, "source/README.md",
                 f"present, {len(blob):,} bytes",
                 f"{SOURCE_README} missing or trivial (HTTP/FS {st}, {len(blob):,} bytes)"):
        readme = blob.decode("utf-8", "replace")
        rep.check(sec, f"{PROD_ORIGIN}{SOURCE_ARCHIVE}" in readme, "README written offer",
                  "states where the source lives, on the prod origin",
                  f"{SOURCE_README} does not state the prod archive URL "
                  f"{PROD_ORIGIN}{SOURCE_ARCHIVE} - a written offer has to say where")

    # --- the archive itself -------------------------------------------------
    st, blob, note = src.get(SOURCE_ARCHIVE)
    if not rep.check(sec, st == 200, "archive present",
                     f"{len(blob):,} bytes", f"{SOURCE_ARCHIVE} is MISSING (HTTP/FS {st}, {note}) - "
                     "the page offers a source archive that does not exist"):
        return
    if not rep.check(sec, len(blob) >= ARCHIVE_MIN_BYTES, "archive size",
                     f"{len(blob):,} bytes", f"{SOURCE_ARCHIVE} is only {len(blob):,} bytes, under "
                     f"the {ARCHIVE_MIN_BYTES:,} floor - it cannot hold the Swiss Ephemeris source"):
        return
    try:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
            names = tf.getnames()
            rep.ok(sec, "archive readable", f"valid gzip tar, {len(names)} members")
            present = set(names)
            for want in ARCHIVE_REQUIRED:
                full = ARCHIVE_ROOT + want
                hit = (any(n.startswith(full) for n in present) if want.endswith("/")
                       else full in present)
                rep.check(sec, hit, f"archive has {want}", "present",
                          f"{SOURCE_ARCHIVE} is missing {full} - the page claims it contains this")
            # The one that matters: does the archived source correspond to the
            # binary and the code actually being served right now?
            for name in CORRESPONDS:
                member = ARCHIVE_ROOT + name
                st_live, live, _n = src.get("/" + name)
                if st_live != 200:
                    rep.fail(sec, f"{name} corresponds",
                             f"/{name} did not resolve (HTTP/FS {st_live}) but SUNMAP's page "
                             "loads it as a worker")
                    continue
                if member not in present:
                    continue        # already reported by the manifest loop
                fh = tf.extractfile(member)
                archived = fh.read() if fh else b""
                same = hashlib.sha256(archived).digest() == hashlib.sha256(live).digest()
                rep.check(sec, same, f"{name} corresponds",
                          f"archived copy is byte-identical to the served copy "
                          f"({hashlib.sha256(live).hexdigest()[:16]}...)",
                          f"the {name} inside {SOURCE_ARCHIVE} is NOT the {name} being served - "
                          "the archive is stale, so it is not Corresponding Source. Rerun "
                          "scripts/build_source_archive.py")
            # Same trap, one level out: the README on disk and the README in the
            # archive drift apart the moment one is regenerated without the other.
            st_r, live_readme, _n = src.get(SOURCE_README)
            member = ARCHIVE_ROOT + "README.md"
            if st_r == 200 and member in present:
                fh = tf.extractfile(member)
                rep.check(sec, (fh.read() if fh else b"") == live_readme, "README corresponds",
                          "the served README is the one inside the archive",
                          f"{SOURCE_README} differs from {member} - one of them was regenerated "
                          "alone. Rerun scripts/build_source_archive.py")
    except tarfile.TarError as e:
        rep.fail(sec, "archive readable",
                 f"{SOURCE_ARCHIVE} is not a readable gzip tar: {e}")


# ----------------------------------------------------------------------- main --
def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="SUNMAP SEO auditor (stdlib only).")
    ap.add_argument("--root", default=os.path.dirname(here),
                    help="directory of the built site (default: sun_map/)")
    ap.add_argument("--url", default=None, help="audit a live URL instead of local files")
    ap.add_argument("--env", choices=("dev", "prod"), default=None,
                    help="ruleset: dev expects noindex, prod expects indexable (default: infer)")
    ap.add_argument("--pages", nargs="*", default=None,
                    help="page paths to audit (default: every .html at the site root)")
    ap.add_argument("--strict", action="store_true", help="treat warnings as failures")
    args = ap.parse_args()

    if args.env:
        env = args.env
    elif args.url:
        env = "prod" if PROD_HOST in args.url else "dev"
    else:
        env = "dev"

    src = Source(None if args.url else args.root, args.url)

    if args.pages:
        pages = args.pages
    elif args.url:
        pages = ["index.html"]
    else:
        pages = sorted(f for f in os.listdir(args.root)
                       if f.endswith(".html") and not f.startswith("_"))

    # Two site-level facts are needed BEFORE the page audits: which paths the
    # sitemap claims (that decides a page's role) and whether robots.txt already
    # blocks the whole site (that decides how hard a missing noindex bites).
    sitemap_paths = read_sitemap_paths(src)
    _st, _robots_blob, _n = src.get("/robots.txt")
    robots_blocks_all = bool(re.search(r"^\s*disallow:\s*/\s*$",
                                       _robots_blob.decode("utf-8", "replace"), re.M | re.I))

    origin = args.url if args.url else args.root
    print("=" * 60)
    print("SUNMAP SEO AUDIT")
    print("=" * 60)
    print(f"source     {origin}")
    print(f"ruleset    {env} (prod host {PROD_HOST}, dev host {DEV_HOST})")
    print(f"pages      {', '.join(pages)}")
    print(f"strict     {'yes - warnings fail the run' if args.strict else 'no'}")

    rep = Report(args.strict)
    all_titles: dict[str, str] = {}
    all_descs: dict[str, str] = {}
    for page in pages:
        status, body, note = src.get(page if args.url is None else urljoin(src.base_url, page))
        if status in GATED:
            rep.warn(f"PAGE {page}", "fetch",
                     f"HTTP {status} - behind the dev password gate, page not audited ({note})")
            continue
        if status != 200:
            rep.fail(f"PAGE {page}", "fetch", f"HTTP/FS {status} for {note}")
            continue
        audit_page(rep, page, body, src, env, all_titles, all_descs,
                   page_role(page, sitemap_paths), robots_blocks_all)

    audit_site(rep, src, env, pages, sitemap_paths)
    audit_agpl(rep, src)
    return rep.render()


if __name__ == "__main__":
    sys.exit(main())
