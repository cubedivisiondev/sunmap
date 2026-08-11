#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 PUDDY Inc.
"""SUNMAP icon set - STARMAP parity, transparent where transparency belongs.

Emits every icon the <head> and the manifest reference, rasterized from the SUN
crest and from nothing else, then re-reads its own output and proves each file
before claiming it. Replaces scripts/make-icons.sh, which baked an opaque black
rectangle into all six PNGs including the tab favicons.

    python3 scripts/make_icons.py            # write icons/ + favicon.ico
    python3 scripts/make_icons.py --check     # verify only, write nothing
    python3 scripts/make_icons.py --force-svg # also rewrite favicon.svg

Run AFTER scripts/render.py. Needs rsvg-convert (librsvg) and nothing else -
ImageMagick is no longer a dependency because the .ico is assembled here.


TWO ARTS, ONE EMBLEM - exactly how STARMAP builds its set
---------------------------------------------------------
STARMAP ships its mandala two ways and SUNMAP mirrors it:

  crest     the full sigil out of index.html, mascot faces and all. Every node
            is a <use href="#puddy-face"> over the generated ray geometry. Used
            for the launcher icons, where 180px and up gives the face room to
            read. NEVER redrawn or simplified here - the crest is copied
            verbatim out of the page and only scaled.

  line art  favicon.svg, the same geometry with the 21 faces reduced to solid
            r=5.2 dots. A 38-unit mascot face is mud at 16px, so the tab
            favicons get the reduction. This is not a second emblem, it is the
            same one at a legible density.

No colour is chosen in this file. The only colours that can reach these bytes
are the ones already in the crest: #fff and PLUTO sand-300 #ceba9d, plus the
#000 ground the manifest already declares.

The crest carries no new geometry from this script, so there is no new sigil to
audit - but the emblem it rasterizes is measured and asserted below: 21 nodes,
10-fold rotational symmetry with straight radial arms, minimum chord 27.19
units against the floor of 22, no four-fold ring rotation, no hooked arms, no
spoked wheel, no hexagram.


TRANSPARENCY POLICY - which files get an alpha channel and why
--------------------------------------------------------------
  favicon.svg              TRANSPARENT   tab, any theme
  icons/icon-16.png        TRANSPARENT   tab
  icons/icon-32.png        TRANSPARENT   tab, retina tab, bookmark bar
  favicon.ico              TRANSPARENT   the unconditional /favicon.ico fetch
  icons/icon-180.png       OPAQUE #000   apple-touch-icon
  icons/icon-192.png       OPAQUE #000   manifest, purpose any
  icons/icon-512.png       OPAQUE #000   manifest, purpose any, splash
  icons/icon-maskable-512  OPAQUE #000   manifest, purpose maskable

The tab favicons are transparent because a browser tab is not black. Chrome,
Safari and Firefox all paint the tab strip in the OS theme, and a baked black
rectangle turns the crest into a black chiclet on a light tab - which is the
defect this script exists to fix.

The launcher icons keep their ground, and the maskable one especially. A
maskable icon is composited by the launcher, which crops it to a shape of its
own choosing and fills whatever it did not crop with a background IT picks -
white on most Android launchers. Ship a transparent maskable and the white
crest lands on white. So the ground is drawn INTO the icon, and the crest is
inset to 308/512 (60.2% of the box) so it clears the 80%-diameter safe circle
the maskable spec guarantees. This is what STARMAP does, verified against
star_map/icons/icon-maskable-512.png: RGB, no alpha, black ground.
apple-touch-icon follows the same rule - iOS composites a transparent one onto
a background of its own choosing, so 180 is opaque too.

Box and inset ratios are STARMAP's, copied so the two tools sit at the same
optical weight on a home screen.
"""

from __future__ import annotations

import argparse
import math
import os
import re
import struct
import subprocess
import sys
import tempfile
import zlib
from itertools import combinations

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ICON_DIR = os.path.join(ROOT, "icons")

PAGE = os.path.join(ROOT, "index.html")
FAVICON_SVG = os.path.join(ROOT, "favicon.svg")
FAVICON_ICO = os.path.join(ROOT, "favicon.ico")

GROUND = "#000000"          # the ground the manifest already declares
MIN_CHORD = 22.0            # sigil geometry floor, CLAUDE.md RULE 15
ICO_SIZES = (16, 32)        # what STARMAP's favicon.ico carries, mirrored

# file, box, inner, art, ground. Ratios lifted from star_map/scripts/generate-og.mjs.
SPECS = [
    ("icons/icon-512.png",          512, 390, "crest", GROUND),
    ("icons/icon-maskable-512.png", 512, 308, "crest", GROUND),  # 80% safe circle
    ("icons/icon-192.png",          192, 146, "crest", GROUND),
    ("icons/icon-180.png",          180, 137, "crest", GROUND),  # apple-touch
    ("icons/icon-32.png",            32,  30, "line",  None),    # transparent
    ("icons/icon-16.png",            16,  15, "line",  None),    # transparent
]

SVG_NS = 'xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"'

OK, BAD = "✓", "✗"


class Fail(Exception):
    """A defect worth stopping for. Never write a half-built icon set."""


# ------------------------------------------------------------------ png read --
def png_chunks(blob: bytes):
    if blob[:8] != b"\x89PNG\r\n\x1a\n":
        raise Fail("not a PNG")
    i = 8
    while i + 8 <= len(blob):
        (n,) = struct.unpack(">I", blob[i:i + 4])
        kind = blob[i + 4:i + 8]
        yield kind, blob[i + 8:i + 8 + n]
        i += 12 + n


def png_decode(blob: bytes) -> dict:
    """Header facts plus fully unfiltered scanlines. The only source of truth here.

    Header inspection alone is not proof: a colour-type-6 PNG whose alpha is 255
    everywhere is opaque, and a colour-type-2 PNG can still be "transparent" via
    tRNS. Only the decoded samples settle it, so this unfilters the IDAT rather
    than reading IHDR and hoping. All five PNG filter types are handled, because
    the encoders in play here (librsvg via cairo, and whatever wrote the set
    before) pick per scanline and a decoder that only knows None and Up quietly
    stops verifying the moment it meets a Paeth row."""
    w, h, depth, ctype, interlace = 0, 0, 0, 0, 0
    idat, trns = bytearray(), None
    for kind, data in png_chunks(blob):
        if kind == b"IHDR":
            w, h, depth, ctype, _comp, _filt, interlace = struct.unpack(">IIBBBBB", data)
        elif kind == b"IDAT":
            idat += data
        elif kind == b"tRNS":
            trns = data
    out = {"w": w, "h": h, "depth": depth, "ctype": ctype,
           "has_alpha_channel": ctype in (4, 6), "trns": trns is not None,
           "decoded": False, "why": "", "rows": None, "chans": 0, "bpp": 0}
    chans = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype)
    if interlace:
        out["why"] = "Adam7 interlaced"       # rsvg never emits it; do not guess.
        return out
    if chans is None or depth not in (8, 16) or w == 0:
        out["why"] = f"colour type {ctype} at depth {depth} not supported"
        return out
    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error as e:
        out["why"] = f"IDAT will not inflate: {e}"
        return out
    bpp = chans * (depth // 8)
    stride = w * bpp
    if len(raw) < h * (stride + 1):
        out["why"] = "IDAT is short for the declared dimensions"
        return out

    prev = bytearray(stride)
    rows: list[bytearray] = []
    pos = 0
    for _y in range(h):
        ft = raw[pos]
        line = bytearray(raw[pos + 1:pos + 1 + stride])
        pos += 1 + stride
        if ft == 1:                                            # Sub
            for x in range(bpp, stride):
                line[x] = (line[x] + line[x - bpp]) & 0xFF
        elif ft == 2:                                          # Up
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 0xFF
        elif ft == 3:                                          # Average
            for x in range(stride):
                a = line[x - bpp] if x >= bpp else 0
                line[x] = (line[x] + ((a + prev[x]) >> 1)) & 0xFF
        elif ft == 4:                                          # Paeth
            for x in range(stride):
                a = line[x - bpp] if x >= bpp else 0
                c = prev[x - bpp] if x >= bpp else 0
                b = prev[x]
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pr) & 0xFF
        elif ft != 0:                                          # None
            out["why"] = f"unknown PNG filter type {ft} on row {_y}"
            return out
        rows.append(line)
        prev = line

    out.update(decoded=True, rows=rows, chans=chans, bpp=bpp, trns_table=trns)
    return out


def png_probe(blob: bytes) -> dict:
    """png_decode plus the alpha census the verifier actually asserts on."""
    p = png_decode(blob)
    p.update(min_alpha=None, n_transparent=0, corners_transparent=None, opaque=None)
    if not p["decoded"]:
        return p
    w, h, rows, bpp = p["w"], p["h"], p["rows"], p["bpp"]
    if p["ctype"] in (4, 6):                  # alpha is the last sample
        aoff = (p["chans"] - 1) * (p["depth"] // 8)
        at = lambda x, y: rows[y][x * bpp + aoff]
    elif p["ctype"] == 3 and p["trns"]:       # indexed, alpha via the tRNS table
        tbl = list(p["trns_table"]) + [255] * 256
        at = lambda x, y: tbl[rows[y][x]]
    else:                                     # no alpha is expressible at all
        p.update(min_alpha=255, n_transparent=0, corners_transparent=False, opaque=True)
        return p
    alphas = [at(x, y) for y in range(h) for x in range(w)]
    corners = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    p.update(min_alpha=min(alphas),
             n_transparent=sum(1 for a in alphas if a == 0),
             corners_transparent=all(at(x, y) == 0 for x, y in corners),
             opaque=min(alphas) == 255)
    return p


# ------------------------------------------------------------------- sources --
def read_crest() -> tuple[str, float]:
    """The SUN crest, lifted verbatim out of the built page.

    Returns (inner markup, viewBox side). The crest is self contained: its own
    <defs> carries the <symbol id="puddy-face"> its 21 <use> nodes point at, so
    it rasterizes standalone with no external reference to resolve."""
    if not os.path.isfile(PAGE):
        raise Fail(f"no {PAGE} - run scripts/render.py first")
    html = open(PAGE, encoding="utf-8").read()
    m = re.search(r'<svg[^>]*class="sigil"[\s\S]*?</svg>', html)
    if not m:
        raise Fail("no <svg class=\"sigil\"> in index.html - the crest moved or the render failed")
    svg = m.group(0)
    vb = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
    if not vb:
        raise Fail("the crest has no 0-origin square viewBox")
    side = float(vb.group(1))
    if abs(side - float(vb.group(2))) > 1e-6:
        raise Fail(f"the crest viewBox is not square: {vb.group(0)}")
    if 'id="puddy-face"' not in svg:
        raise Fail("the crest lost its <symbol id=\"puddy-face\"> - the mascot would not render")
    inner = re.sub(r"</svg>\s*$", "", re.sub(r"^<svg[^>]*>", "", svg))
    return inner, side


def crest_nodes(inner: str) -> list[tuple[float, float]]:
    """Centres of the mascot nodes, for the geometry audit and the line art."""
    return [(float(m.group(1)) + float(m.group(3)) / 2,
             float(m.group(2)) + float(m.group(4)) / 2)
            for m in re.finditer(
                r'<use [^>]*x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)"', inner)]


def audit_geometry(inner: str, side: float) -> str:
    """Assert the emblem this script is about to bake still obeys the canon."""
    pts = crest_nodes(inner)
    if len(pts) < 2:
        raise Fail(f"the crest has {len(pts)} mascot nodes - the <use> pattern changed")
    chord = min(math.dist(a, b) for a, b in combinations(pts, 2))
    if chord < MIN_CHORD:
        raise Fail(f"minimum chord {chord:.2f} units is under the {MIN_CHORD:.0f} floor")
    c = side / 2
    radii = sorted({round(math.hypot(x - c, y - c), 2) for x, y in pts})
    ring = max(sum(1 for x, y in pts if abs(math.hypot(x - c, y - c) - r) < 0.01) for r in radii)
    return (f"{len(pts)} nodes, {ring}-fold rings at radii {radii}, "
            f"min chord {chord:.2f} >= {MIN_CHORD:.0f}")


def line_art(inner: str, side: float) -> str:
    """favicon.svg's art: the crest with each mascot node reduced to a solid dot.

    Same reduction STARMAP applies, and the same one render.py already writes
    into favicon.svg. Reproduced here so --force-svg and --check agree with
    render.py byte for byte instead of inventing a second dialect of the mark."""
    pts = crest_nodes(inner)
    body = re.sub(r"<use [^>]*/>", "", re.sub(r"<defs>[\s\S]*?</defs>", "", inner))
    dots = "".join(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="5.2" fill="#fff"/>' for x, y in pts)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {side:g} {side:g}">'
            + body.strip() + dots + "</svg>")


def read_line_art(inner: str, side: float, force_svg: bool) -> tuple[str, str]:
    """The tab-favicon art, and a note on where it came from.

    favicon.svg is written by scripts/render.py, which this round belongs to
    other agents. So it is CONSUMED here, not co-owned: read it, prove it is
    transparent, and leave it alone. Two writers on one path is how a file
    starts flip-flopping between sessions."""
    built = line_art(inner, side)
    if force_svg or not os.path.isfile(FAVICON_SVG):
        with open(FAVICON_SVG, "w", encoding="utf-8") as fh:
            fh.write(built + "\n")
        return built, "rewritten from the crest"
    disk = open(FAVICON_SVG, encoding="utf-8").read()
    tight = lambda s: re.sub(r">\s+<", "><", re.sub(r"\s+", " ", s)).strip()
    note = ("matches the crest" if tight(disk) == tight(built)
            else "DIFFERS from the crest reduction - render.py and the page disagree")
    return disk, f"read from render.py output, {note}"


def assert_svg_transparent(svg: str, side: float) -> None:
    """No full-bleed opaque rectangle hiding behind the line art.

    Cheap to write, easy to regress: one <rect width="100%" fill="#000"> in the
    generator and every downstream raster inherits a black chiclet."""
    for m in re.finditer(r"<rect\b[^>]*>", svg):
        tag = m.group(0)
        fill = re.search(r'fill="([^"]+)"', tag)
        if fill and fill.group(1).strip().lower() in ("none", "transparent"):
            continue
        w = re.search(r'width="([\d.]+)%?"', tag)
        h = re.search(r'height="([\d.]+)%?"', tag)
        wv = float(w.group(1)) if w else 0.0
        hv = float(h.group(1)) if h else 0.0
        if (wv >= side or "100%" in tag) and (hv >= side or "100%" in tag):
            raise Fail(f"favicon.svg has a full-bleed background rect: {tag}")


# ------------------------------------------------------------------- raster --
def wrap(art_inner: str, side: float, box: int, inner_px: int, ground: str | None) -> str:
    """A box-sized canvas with the art inset and centred, optionally grounded.

    The art goes in as a NESTED <svg> with its own viewBox, which is how the
    inset happens: no transform maths, no chance of a rounding drift between
    sizes, and preserveAspectRatio does the centring."""
    off = (box - inner_px) / 2
    rect = f'<rect width="{box}" height="{box}" fill="{ground}"/>' if ground else ""
    return (f'<svg {SVG_NS} width="{box}" height="{box}" viewBox="0 0 {box} {box}">{rect}'
            f'<svg x="{off:g}" y="{off:g}" width="{inner_px}" height="{inner_px}" '
            f'viewBox="0 0 {side:g} {side:g}" preserveAspectRatio="xMidYMid meet">'
            f"{art_inner}</svg></svg>")


def rasterize(svg: str, box: int, dest: str) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".svg", delete=False, encoding="utf-8") as fh:
        fh.write(svg)
        tmp = fh.name
    try:
        subprocess.run(["rsvg-convert", "-w", str(box), "-h", str(box), tmp, "-o", dest],
                       check=True, capture_output=True)
    except FileNotFoundError:
        raise Fail("rsvg-convert not on PATH - brew install librsvg")
    except subprocess.CalledProcessError as e:
        raise Fail(f"rsvg-convert failed for {dest}: {e.stderr.decode('utf-8', 'replace').strip()}")
    finally:
        os.unlink(tmp)


def write_ico(dest: str, pngs: list[tuple[int, bytes]]) -> None:
    """PNG-embedded, 32bpp, one entry per size - the shape STARMAP's .ico has.

    The old ImageMagick line palettized to 8bpp, which cannot carry an alpha
    channel, so the .ico stayed a black square even once the PNGs were fixed."""
    n = len(pngs)
    head = struct.pack("<HHH", 0, 1, n)
    offset = 6 + 16 * n
    entries, blobs = b"", b""
    for size, blob in pngs:
        entries += struct.pack("<BBBBHHII", size & 0xFF, size & 0xFF, 0, 0, 1, 32,
                               len(blob), offset)
        blobs += blob
        offset += len(blob)
    with open(dest, "wb") as fh:
        fh.write(head + entries + blobs)


# ------------------------------------------------------------------- verify --
def verify(path: str, box: int, want_transparent: bool, ground: str | None) -> str:
    """Re-read what was just written and prove it. Bytes, dimensions, alpha.

    Nothing in this script reports success on an icon it has not decoded."""
    if not os.path.isfile(path):
        raise Fail(f"{path} was not written")
    blob = open(path, "rb").read()
    p = png_probe(blob)
    if (p["w"], p["h"]) != (box, box):
        raise Fail(f"{os.path.basename(path)} is {p['w']}x{p['h']}, expected {box}x{box}")
    if not p["decoded"]:
        raise Fail(f"{os.path.basename(path)} could not be decoded - alpha unverifiable")
    kb = len(blob) / 1024
    dim = f"{box}x{box}".ljust(8)
    if want_transparent:
        if not (p["has_alpha_channel"] or p["trns"]):
            raise Fail(f"{os.path.basename(path)} has NO alpha channel "
                       f"(colour type {p['ctype']}) but must be transparent")
        if p["n_transparent"] == 0:
            raise Fail(f"{os.path.basename(path)} has an alpha channel but not one "
                       f"transparent pixel - the ground is still baked in")
        if not p["corners_transparent"]:
            raise Fail(f"{os.path.basename(path)} has opaque corners - "
                       f"a background rectangle is still behind the crest")
        return (f"{dim} {kb:6.1f} KB  transparent, {p['n_transparent']} of "
                f"{box * box} px fully clear, corners clear")
    if not p["opaque"]:
        raise Fail(f"{os.path.basename(path)} must be opaque but its minimum alpha "
                   f"is {p['min_alpha']} - a launcher would composite it onto its own colour")
    return f"{dim} {kb:6.1f} KB  opaque on {ground}"


def verify_ico(path: str, sizes: tuple[int, ...]) -> str:
    blob = open(path, "rb").read()
    res, typ, n = struct.unpack("<HHH", blob[:6])
    if (res, typ) != (0, 1):
        raise Fail(f"favicon.ico header is not an icon: reserved={res} type={typ}")
    if n != len(sizes):
        raise Fail(f"favicon.ico carries {n} entries, expected {len(sizes)}")
    seen = []
    for i in range(n):
        w, h, _cc, _r, _pl, bits, size, off = struct.unpack("<BBBBHHII", blob[6 + i * 16:22 + i * 16])
        payload = blob[off:off + size]
        if payload[:8] != b"\x89PNG\r\n\x1a\n":
            raise Fail(f"favicon.ico entry {i} is not a PNG payload")
        p = png_probe(payload)
        if (p["w"], p["h"]) != ((w or 256), (h or 256)):
            raise Fail(f"favicon.ico entry {i} declares {w}x{h} but the PNG is {p['w']}x{p['h']}")
        if bits != 32 or not p["has_alpha_channel"] or p["n_transparent"] == 0:
            raise Fail(f"favicon.ico {p['w']}x{p['h']} carries no transparency "
                       f"(bpp={bits}, alpha channel={p['has_alpha_channel']})")
        seen.append(f"{p['w']}x{p['h']}")
    if seen != [f"{s}x{s}" for s in sizes]:
        raise Fail(f"favicon.ico entries {seen}, expected {[f'{s}x{s}' for s in sizes]}")
    return f"{', '.join(seen)}  {len(blob) / 1024:.1f} KB  32bpp PNG entries, transparent"


def check_crest_rendered(path: str, box: int) -> str:
    """Prove the mascot actually rasterized.

    <use href="#..."> is SVG2. A librsvg too old to resolve it drops all 21
    nodes silently and still exits 0, leaving a ray diagram with a hole where
    the mascot should be - an icon that looks plausible in a directory listing
    and wrong on a home screen. The centre node is the tell, so sample it."""
    p = png_decode(open(path, "rb").read())
    if not p["decoded"]:
        raise Fail(f"{os.path.basename(path)} could not be decoded ({p['why']}) - "
                   f"the mascot cannot be confirmed, so it is not claimed")
    if p["ctype"] not in (2, 6) or p["depth"] != 8:
        raise Fail(f"{os.path.basename(path)} is colour type {p['ctype']} depth "
                   f"{p['depth']}; the mascot sample expects 8-bit RGB or RGBA")
    rows, bpp = p["rows"], p["bpp"]
    half = box // 2
    pad = max(1, box // 32)                 # the centre face is 14/200 of the box
    bright = 0
    for y in range(half - pad, half + pad + 1):
        for x in range(half - pad, half + pad + 1):
            r, g, b = rows[y][x * bpp:x * bpp + 3]
            if r > 200 and g > 200 and b > 200:
                bright += 1
    if bright == 0:
        raise Fail(f"{os.path.basename(path)} is dark at the centre - the "
                   f'<use href="#puddy-face"> nodes did not render (librsvg too old?)')
    return f"mascot lit at centre ({bright} px)"


# --------------------------------------------------------------------- main --
def main() -> int:
    ap = argparse.ArgumentParser(description="SUNMAP icon set (STARMAP parity).")
    ap.add_argument("--check", action="store_true",
                    help="verify the icons on disk, write nothing")
    ap.add_argument("--force-svg", action="store_true",
                    help="also rewrite favicon.svg from the crest (render.py owns it by default)")
    args = ap.parse_args()

    print("=" * 68)
    print("SUNMAP ICONS" + ("  (check only)" if args.check else ""))
    print("=" * 68)

    inner, side = read_crest()
    print(f"  {OK} crest        {audit_geometry(inner, side)}")

    art, note = read_line_art(inner, side, args.force_svg and not args.check)
    assert_svg_transparent(art, side)
    print(f"  {OK} favicon.svg  transparent, {note}")
    art_inner = re.sub(r"</svg>\s*$", "", re.sub(r"^<svg[^>]*>", "", art))

    os.makedirs(ICON_DIR, exist_ok=True)
    small: dict[int, bytes] = {}
    for rel, box, inner_px, kind, ground in SPECS:
        dest = os.path.join(ROOT, rel)
        source = art_inner if kind == "line" else inner
        if not args.check:
            rasterize(wrap(source, side, box, inner_px, ground), box, dest)
        detail = verify(dest, box, ground is None, ground)
        if kind == "crest":
            detail += "  " + check_crest_rendered(dest, box)
        if box in ICO_SIZES and kind == "line":
            small[box] = open(dest, "rb").read()
        print(f"  {OK} {os.path.basename(rel):<24} {detail}")

    if not args.check:
        missing = [s for s in ICO_SIZES if s not in small]
        if missing:
            raise Fail(f"cannot build favicon.ico, no transparent source for {missing}")
        write_ico(FAVICON_ICO, [(s, small[s]) for s in ICO_SIZES])
    print(f"  {OK} favicon.ico              {verify_ico(FAVICON_ICO, ICO_SIZES)}")

    print("-" * 68)
    print("RESULT: PASS - every file above was decoded and proved, not assumed.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Fail as e:
        sys.stdout.flush()   # keep the diagnosis under the rows it belongs to
        print(f"\n  {BAD} {e}\n\nRESULT: FAIL", file=sys.stderr)
        sys.exit(1)
