<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
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

- This archive:            https://sunmap.puddystudios.com/source/corresponding-source.tar.gz
- Source information page: https://sunmap.puddystudios.com/source.html
- This README:             https://sunmap.puddystudios.com/source/README.md
- Full license texts:      https://sunmap.puddystudios.com/source/AGPL-3.0.txt
                           https://sunmap.puddystudios.com/source/GPL-3.0.txt
- The running binary:      https://sunmap.puddystudios.com/vendor/sweph/swisseph.wasm
                           https://sunmap.puddystudios.com/vendor/sweph/swisseph.js
- Our calling code:        https://sunmap.puddystudios.com/sunmap-worker.js

No account, no charge, and no request is required to obtain any of the above. If
you would rather receive it another way, or if any link above fails, write to
**legal@puddystudios.com** and PUDDY Inc. will supply the complete corresponding
source at no charge.

## Contents and exact versions

| Path | What | License | Upstream (exact version) | Bytes |
|---|---|---|---|---|
| `swisseph-2.10.03/` | Swiss Ephemeris C library source, Astrodienst AG. `sweph.h` declares `SE_VERSION "2.10.03"` | AGPL-3.0 (free option chosen) | github.com/aloistr/swisseph tag `v2.10.03`; www.astro.com/ftp/swisseph | 2,171,590 |
| `swisseph-wasm-0.0.5-npm/` | The exact `swisseph-wasm@0.0.5` npm package SUNMAP serves. Its `wasm/swisseph.js` + `wasm/swisseph.wasm` are the files that run in the browser | GPL-3.0-or-later (Copyright 2024 prolaxu) | npm `swisseph-wasm@0.0.5` (registry.npmjs.org/swisseph-wasm/-/swisseph-wasm-0.0.5.tgz) | 914,222 |
| `swisseph-wasm-main/` | The `swisseph-wasm` build harness: `compile.sh` (the Emscripten command and its exported function list) that produces `swisseph.js` + `swisseph.wasm` | GPL-3.0-or-later | github.com/prolaxu/swisseph-wasm | 12,652,931 |
| `sunmap-worker.js` | SUNMAP's module worker - imports vendor/sweph/swisseph.js and drives the engine. This is the COMBINED WORK. | AGPL-3.0-or-later (Copyright 2026 PUDDY Inc.) | this product | 40,327 |
| `sunmap-geo.js` | SUNMAP's observer-input module (coordinates, elevation, timezone). Released under the same license. | AGPL-3.0-or-later (Copyright 2026 PUDDY Inc.) | this product | 71,034 |
| `AGPL-3.0.txt` | Full GNU Affero GPL v3.0 text | - | gnu.org/licenses/agpl-3.0.txt | - |
| `GPL-3.0.txt` | Full GNU GPL v3.0 text | - | gnu.org/licenses/gpl-3.0.txt | - |

## Integrity - this source corresponds to that binary

The two engine files SUNMAP serves, and their copies inside
`swisseph-wasm-0.0.5-npm/wasm/`, are byte-identical. SHA-256:

    deacf15677279d8fba5c321e235c1e62840f91e94478bc629bc5d1a98d3131d2  swisseph.js
    2c39039161dc443850c93e23744d3f34dc1873b1417c5b59f41a70f5378db073  swisseph.wasm

SUNMAP's own files in this archive, SHA-256:

    5040a21278b0209b2bd1192ffd5c70456f98783b59d4be224d030d3245e0a1ff  sunmap-worker.js
    fe5d586350715175c893b5f21a8c499e2a89dd411df19aca383a1ccdc4a5c607  sunmap-geo.js

Verify any of them against the served copies:

    curl -sS https://sunmap.puddystudios.com/vendor/sweph/swisseph.wasm | shasum -a 256
    curl -sS https://sunmap.puddystudios.com/sunmap-worker.js | shasum -a 256

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
verbatim at https://sunmap.puddystudios.com/data/ephe/ and Astrodienst publishes them
at www.astro.com/ftp/swisseph/ephe/. They are included here by reference only.

## A note on vendor/sweph/LICENSE.txt

The engine directory SUNMAP serves carries `LICENSE.txt`, the
`swisseph-wasm` wrapper author's older license summary (Copyright 2024
prolaxu). It describes the Swiss Ephemeris as free for non-commercial use
with a commercial license required otherwise. That summary predates
Astrodienst's relicensing of the Swiss Ephemeris under the GNU Affero
General Public License. The authoritative license for the C library is
`swisseph-2.10.03/LICENSE` in this archive (full AGPL text in
`AGPL-3.0.txt`). SUNMAP's governing terms are AGPL-3.0, and SUNMAP
complies by publishing this archive at no charge from the same origin
that serves the binary.

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
