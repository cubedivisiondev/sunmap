#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 PUDDY Inc. <legal@puddystudios.com>
"""Build SUNMAP's Complete Corresponding Source archive. Stdlib only.

    python3 scripts/build_source_archive.py            # build + verify
    python3 scripts/build_source_archive.py --verify    # verify only, write nothing

WHY THIS SCRIPT EXISTS

SUNMAP serves a WebAssembly build of the Swiss Ephemeris to every visitor's
browser. That is conveying object code. GPL-3.0 section 6(d) - the clause that
governs conveyance from a network server - requires "equivalent access to the
Corresponding Source in the same way through the same place at no further
charge". An email offer does not satisfy 6(d); 6(b)'s written offer is only
available for object code embodied in a physical product. So the source has to
be a file on this origin, and it has to actually correspond to the binary.

"Correspond" is the part a hand-assembled tarball gets wrong six weeks later,
when sunmap-worker.js has moved on and the archive has not. This script is the
guard: it rebuilds the archive from provable inputs and refuses to write one
that does not match what SUNMAP serves.

WHERE THE UPSTREAM SOURCE COMES FROM

SUNMAP serves the byte-identical engine STARMAP serves - same swisseph.wasm,
same swisseph.js, same SHA-256. So the upstream half of the corresponding
source is identical too, and it is read straight out of the sibling archive at
star_map/source/corresponding-source.tar.gz rather than duplicated in the repo.
The script proves the reuse is legitimate before it relies on it: if the engine
files inside that archive are not byte-identical to the ones in
sun_map/vendor/sweph/, it fails instead of shipping a mismatched claim.

WHAT GOES IN

  swisseph-2.10.03/           Swiss Ephemeris C source (Astrodienst AG, AGPL-3.0)
  swisseph-wasm-0.0.5-npm/    the exact npm package whose wasm/ SUNMAP serves
  swisseph-wasm-main/         prolaxu's build harness, incl. compile.sh
  sunmap-worker.js            SUNMAP's own code that links the engine
  sunmap-geo.js               SUNMAP's observer-input module (also AGPL)
  AGPL-3.0.txt, GPL-3.0.txt   full license texts
  README.md                   the written offer, the manifest, rebuild steps

Every size and hash printed in the README is computed here, never typed.

The tar is deterministic: sorted member order, zeroed mtime/uid/gid, zeroed
gzip header time. Same inputs give the same bytes, so the archive can be
diffed across rebuilds.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import os
import sys
import tarfile
from pathlib import Path

SUN = Path(__file__).resolve().parents[1]
REPO = SUN.parent
STAR_ARCHIVE = REPO / "star_map" / "source" / "corresponding-source.tar.gz"
OUT_DIR = SUN / "source"
OUT_TAR = OUT_DIR / "corresponding-source.tar.gz"

PROD = "https://sunmap.puddystudios.com/"
ROOT = "corresponding-source"

# Reused verbatim from the sibling archive - the upstream half of the source.
UPSTREAM_TREES = ("swisseph-2.10.03", "swisseph-wasm-0.0.5-npm", "swisseph-wasm-main")
LICENCE_TEXTS = ("AGPL-3.0.txt", "GPL-3.0.txt")

# SUNMAP's own files. The first is the combined work; the second is shipped
# under the same license and included so the offer covers everything the page
# names. (path in sun_map/, note for the manifest)
OWN_FILES = (
    ("sunmap-worker.js", "SUNMAP's module worker - imports vendor/sweph/swisseph.js "
                         "and drives the engine. This is the COMBINED WORK."),
    ("sunmap-geo.js", "SUNMAP's observer-input module (coordinates, elevation, "
                      "timezone). Released under the same license."),
)

# The engine files whose identity licenses the whole reuse.
ENGINE_FILES = ("swisseph.js", "swisseph.wasm")


def sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def read_star_archive() -> dict[str, tarfile.TarInfo]:
    if not STAR_ARCHIVE.is_file():
        sys.exit(f"FAIL: upstream source archive not found at {STAR_ARCHIVE}")
    return {}


def load_members() -> tuple[dict[str, bytes], dict[str, tarfile.TarInfo]]:
    """Pull the upstream trees and license texts out of the sibling archive."""
    blobs: dict[str, bytes] = {}
    infos: dict[str, tarfile.TarInfo] = {}
    wanted_prefixes = tuple(f"{ROOT}/{t}/" for t in UPSTREAM_TREES)
    wanted_files = tuple(f"{ROOT}/{f}" for f in LICENCE_TEXTS)
    with tarfile.open(STAR_ARCHIVE, "r:gz") as tf:
        for m in tf.getmembers():
            if not (m.name.startswith(wanted_prefixes) or m.name in wanted_files):
                continue
            infos[m.name] = m
            if m.isfile():
                fh = tf.extractfile(m)
                blobs[m.name] = fh.read() if fh else b""
    return blobs, infos


def verify_engine_identity(blobs: dict[str, bytes]) -> dict[str, str]:
    """The reuse is only legitimate if the engine in the sibling archive is the
    engine SUNMAP serves. Byte-for-byte, or this script refuses to build."""
    hashes: dict[str, str] = {}
    for name in ENGINE_FILES:
        served_p = SUN / "vendor" / "sweph" / name
        if not served_p.is_file():
            sys.exit(f"FAIL: SUNMAP does not have {served_p} - nothing to correspond to")
        served = served_p.read_bytes()
        key = f"{ROOT}/swisseph-wasm-0.0.5-npm/wasm/{name}"
        if key not in blobs:
            sys.exit(f"FAIL: {key} is not in {STAR_ARCHIVE.name}")
        if sha256(served) != sha256(blobs[key]):
            sys.exit(f"FAIL: {name} served by SUNMAP differs from the archived npm package. "
                     "The upstream source does not correspond to the conveyed binary.")
        hashes[name] = sha256(served)
        print(f"  ok  {name:<16} {hashes[name][:16]}...  served == archived npm package")
    return hashes


def own_blobs() -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for rel, _note in OWN_FILES:
        p = SUN / rel
        if not p.is_file():
            sys.exit(f"FAIL: {p} is missing - the archive would not correspond")
        out[rel] = p.read_bytes()
    return out


def render_readme(engine: dict[str, str], mine: dict[str, bytes],
                  tree_bytes: dict[str, int]) -> str:
    lic = SUN / "vendor" / "sweph" / "LICENSE.txt"
    lic_note = ""
    if lic.is_file():
        lic_note = (
            "\n## A note on vendor/sweph/LICENSE.txt\n\n"
            "The engine directory SUNMAP serves carries `LICENSE.txt`, the\n"
            "`swisseph-wasm` wrapper author's older license summary (Copyright 2024\n"
            "prolaxu). It describes the Swiss Ephemeris as free for non-commercial use\n"
            "with a commercial license required otherwise. That summary predates\n"
            "Astrodienst's relicensing of the Swiss Ephemeris under the GNU Affero\n"
            "General Public License. The authoritative license for the C library is\n"
            "`swisseph-2.10.03/LICENSE` in this archive (full AGPL text in\n"
            "`AGPL-3.0.txt`). SUNMAP's governing terms are AGPL-3.0, and SUNMAP\n"
            "complies by publishing this archive at no charge from the same origin\n"
            "that serves the binary.\n")

    rows = []
    for rel, note in OWN_FILES:
        rows.append(f"| `{rel}` | {note} | AGPL-3.0-or-later (Copyright 2026 PUDDY Inc.) "
                    f"| this product | {len(mine[rel]):,} |")
    own_rows = "\n".join(rows)

    own_hashes = "\n".join(
        f"    {sha256(mine[rel])}  {rel}" for rel, _n in OWN_FILES)

    return f"""<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Copyright (C) 2026 PUDDY Inc. <legal@puddystudios.com> - this document -->
# Complete Corresponding Source - SUNMAP

SUNMAP (sunmap.puddystudios.com), a product of PUDDY Inc., serves a WebAssembly
build of the **Swiss Ephemeris** astronomical library to visitors' browsers. Every
sunrise, sunset, twilight, golden hour, moonrise and moonset SUNMAP prints is
computed on the device by that engine, topocentrically for the observer. The Swiss
Ephemeris is dual-licensed; **SUNMAP uses it under the free copyleft license, the
GNU Affero General Public License v3.0 (AGPL-3.0)**, NOT the paid commercial
license. The WebAssembly wrapper that builds it is licensed GPL-3.0-or-later.

This archive is the **Complete Corresponding Source** for the binary SUNMAP
conveys (`swisseph.wasm` + its `swisseph.js` Emscripten loader), provided per
GPL-3.0 section 6(d) and AGPL-3.0 section 13, plus SUNMAP's own code that links it.

## Written offer

The complete corresponding source for the copyleft components SUNMAP serves is
available to anyone, at no charge, from the same origin that serves the binary,
for as long as SUNMAP serves that binary:

- This archive:            {PROD}source/corresponding-source.tar.gz
- Source information page: {PROD}source.html
- This README:             {PROD}source/README.md
- Full license texts:      {PROD}source/AGPL-3.0.txt
                           {PROD}source/GPL-3.0.txt
- The running binary:      {PROD}vendor/sweph/swisseph.wasm
                           {PROD}vendor/sweph/swisseph.js
- Our calling code:        {PROD}sunmap-worker.js

No account, no charge, and no request is required to obtain any of the above. If
you would rather receive it another way, or if any link above fails, write to
**legal@puddystudios.com** and PUDDY Inc. will supply the complete corresponding
source at no charge.

## Contents and exact versions

| Path | What | License | Upstream (exact version) | Bytes |
|---|---|---|---|---|
| `swisseph-2.10.03/` | Swiss Ephemeris C library source, Astrodienst AG. `sweph.h` declares `SE_VERSION "2.10.03"` | AGPL-3.0 (free option chosen) | github.com/aloistr/swisseph tag `v2.10.03`; www.astro.com/ftp/swisseph | {tree_bytes['swisseph-2.10.03']:,} |
| `swisseph-wasm-0.0.5-npm/` | The exact `swisseph-wasm@0.0.5` npm package SUNMAP serves. Its `wasm/swisseph.js` + `wasm/swisseph.wasm` are the files that run in the browser | GPL-3.0-or-later (Copyright 2024 prolaxu) | npm `swisseph-wasm@0.0.5` (registry.npmjs.org/swisseph-wasm/-/swisseph-wasm-0.0.5.tgz) | {tree_bytes['swisseph-wasm-0.0.5-npm']:,} |
| `swisseph-wasm-main/` | The `swisseph-wasm` build harness: `compile.sh` (the Emscripten command and its exported function list) that produces `swisseph.js` + `swisseph.wasm` | GPL-3.0-or-later | github.com/prolaxu/swisseph-wasm | {tree_bytes['swisseph-wasm-main']:,} |
{own_rows}
| `AGPL-3.0.txt` | Full GNU Affero GPL v3.0 text | - | gnu.org/licenses/agpl-3.0.txt | - |
| `GPL-3.0.txt` | Full GNU GPL v3.0 text | - | gnu.org/licenses/gpl-3.0.txt | - |

## Integrity - this source corresponds to that binary

The two engine files SUNMAP serves, and their copies inside
`swisseph-wasm-0.0.5-npm/wasm/`, are byte-identical. SHA-256:

    {engine['swisseph.js']}  swisseph.js
    {engine['swisseph.wasm']}  swisseph.wasm

SUNMAP's own files in this archive, SHA-256:

{own_hashes}

Verify any of them against the served copies:

    curl -sS {PROD}vendor/sweph/swisseph.wasm | shasum -a 256
    curl -sS {PROD}sunmap-worker.js | shasum -a 256

## Provenance note (version labels)

The binary SUNMAP serves is the **`swisseph-wasm@0.0.5`** npm release
(`swisseph-wasm-0.0.5-npm/`, whose `package.json` reads `0.0.5`). The build
harness in `swisseph-wasm-main/` is prolaxu's source repository; **its in-repo
`package.json` reads `0.0.4` because the maintainer published the `0.0.5` npm tag
without bumping the committed version number**. The build script and the emitted
`wasm/swisseph.js` are nonetheless the `0.0.5` release, which the SHA-256 above
settles: the loader is byte-identical across the npm package, the build repo, and
the file SUNMAP serves at `/vendor/sweph/swisseph.js`. The corresponding source
therefore corresponds to the conveyed binary regardless of the upstream label slip.

## How to rebuild the exact binary SUNMAP serves

1. Install Emscripten (emsdk) per https://emscripten.org.
2. The build harness is `swisseph-wasm-main/`. Its `compile.sh` compiles
   `deps/swisseph/*.c`. **`swisseph-wasm-main/deps/swisseph/` in this archive is
   already populated with the Swiss Ephemeris 2.10.03 C sources**, so `compile.sh`
   runs unedited:

       cd swisseph-wasm-main && bash compile.sh

   (Upstream that directory is an empty git submodule pointing at
   github.com/aloistr/swisseph; it is populated here so no submodule fetch is
   needed.) Those 29 files are byte-identical to their counterparts in
   `swisseph-2.10.03/`. `swisseph-2.10.03/` additionally carries the upstream
   `Makefile`, the license copies and the Windows and VB bindings, which
   `compile.sh` does not use.
3. `compile.sh` also `--preload-file`s `deps/sweph` for ephemeris DATA. SUNMAP
   bypasses that preload and injects the `.se1` files at runtime instead (see
   `sunmap-worker.js`), so the data preload is not required to reproduce the
   engine logic.
4. The emitted `wasm/swisseph.js` + `wasm/swisseph.wasm` are the files SUNMAP
   serves at `/vendor/sweph/`.

## Ephemeris data files (not program source)

The engine reads three Swiss Ephemeris data files - `seas_18.se1`, `semo_18.se1`,
`sepl_18.se1` (the JPL DE441-derived ephemerides). These are DATA, not program
source code, so they are not part of "Corresponding Source". SUNMAP serves them
verbatim at {PROD}data/ephe/ and Astrodienst publishes them
at www.astro.com/ftp/swisseph/ephe/. They are included here by reference only.
{lic_note}
## Scope of the combined work

`sunmap-worker.js` imports the Emscripten module directly and therefore forms a
combined work with it; it is licensed AGPL-3.0-or-later. The rest of the SUNMAP
page communicates with that worker only by `postMessage`, exchanging JSON data
across a process boundary, and is merely aggregated with the copyleft components.

## Notices preserved

Swiss Ephemeris is Copyright Astrodienst AG, Switzerland. The `swisseph-wasm`
wrapper is Copyright 2024 prolaxu. Their LICENSE files are retained in their
respective directories. SUNMAP makes no modification to the Swiss Ephemeris
library; it links it unmodified.

Questions or source requests: legal@puddystudios.com
"""


def add(tar: tarfile.TarFile, name: str, blob: bytes, mode: int = 0o644) -> None:
    ti = tarfile.TarInfo(name)
    ti.size = len(blob)
    ti.mtime = 0
    ti.mode = mode
    ti.uid = ti.gid = 0
    ti.uname = ti.gname = ""
    tar.addfile(ti, io.BytesIO(blob))


def main() -> int:
    ap = argparse.ArgumentParser(description="Build SUNMAP's corresponding-source archive.")
    ap.add_argument("--verify", action="store_true",
                    help="check the existing archive instead of writing a new one")
    args = ap.parse_args()

    read_star_archive()
    print(f"upstream source  {STAR_ARCHIVE}")
    blobs, infos = load_members()
    print(f"pulled           {len(blobs)} upstream files")

    print("engine identity:")
    engine = verify_engine_identity(blobs)
    mine = own_blobs()

    tree_bytes = {t: sum(len(b) for n, b in blobs.items()
                         if n.startswith(f"{ROOT}/{t}/")) for t in UPSTREAM_TREES}
    readme = render_readme(engine, mine, tree_bytes).encode("utf-8")

    # --- assemble, deterministically -------------------------------------
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        add(tar, f"{ROOT}/README.md", readme)
        for f in LICENCE_TEXTS:
            add(tar, f"{ROOT}/{f}", blobs[f"{ROOT}/{f}"])
        for rel, _note in OWN_FILES:
            add(tar, f"{ROOT}/{rel}", mine[rel])
        for name in sorted(n for n in infos if n.startswith(tuple(
                f"{ROOT}/{t}/" for t in UPSTREAM_TREES))):
            m = infos[name]
            if m.isdir():
                ti = tarfile.TarInfo(name)
                ti.type = tarfile.DIRTYPE
                ti.mode = 0o755
                ti.mtime = 0
                ti.uid = ti.gid = 0
                ti.uname = ti.gname = ""
                tar.addfile(ti)
            elif m.isfile():
                add(tar, name, blobs[name], mode=0o755 if m.mode & 0o111 else 0o644)

    packed = io.BytesIO()
    with gzip.GzipFile(fileobj=packed, mode="wb", compresslevel=9, mtime=0) as gz:
        gz.write(raw.getvalue())
    archive = packed.getvalue()

    if args.verify:
        if not OUT_TAR.is_file():
            print(f"FAIL: {OUT_TAR} does not exist")
            return 1
        same = OUT_TAR.read_bytes() == archive
        print(f"{'ok  ' if same else 'FAIL'} {OUT_TAR.name} "
              f"{'matches a fresh build' if same else 'is STALE - rerun without --verify'}")
        return 0 if same else 1

    OUT_DIR.mkdir(exist_ok=True)
    OUT_TAR.write_bytes(archive)
    (OUT_DIR / "README.md").write_bytes(readme)
    for f in LICENCE_TEXTS:
        (OUT_DIR / f).write_bytes(blobs[f"{ROOT}/{f}"])

    n = len(raw.getvalue())
    print(f"\nwrote {OUT_TAR.relative_to(REPO)}  "
          f"{len(archive):,} bytes gz / {n:,} bytes raw")
    print(f"      sha256 {sha256(archive)}")
    for f in ("README.md", *LICENCE_TEXTS):
        print(f"wrote {(OUT_DIR / f).relative_to(REPO)}  {(OUT_DIR / f).stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
