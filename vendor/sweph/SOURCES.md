# vendor/sweph - Swiss Ephemeris WebAssembly runtime

Minimal browser dist staged for Puddy Starmap "Personal Sky" (client-side
topocentric recompute). Selected + validated 2026-06-10; full numbers in
`star_map/.wasm-eval/RESULTS.md`.

## Package

- **Package**: `swisseph-wasm@0.0.5` (npm)
- **Upstream**: https://github.com/prolaxu/swisseph-wasm
- **npm**: https://www.npmjs.com/package/swisseph-wasm
- **Tarball**: https://registry.npmjs.org/swisseph-wasm/-/swisseph-wasm-0.0.5.tgz
- **Embedded C library**: Swiss Ephemeris 2.10.03 (Astrodienst AG,
  https://www.astro.com/swisseph/) - identical version to the pyswisseph
  2.10.03 used by our Python engine.

## Files staged (verbatim from the npm package)

| File | From | Bytes |
|---|---|---|
| `swisseph.js` | `swisseph-wasm/wasm/swisseph.js` (Emscripten ESM glue, `export default Swisseph` factory) | 72,420 |
| `swisseph.wasm` | `swisseph-wasm/wasm/swisseph.wasm` | 543,953 |
| `LICENSE` | `swisseph-wasm/LICENSE` (GPL-3.0-or-later + Swiss Ephemeris terms) | 1,498 |

Deliberately NOT staged: `wasm/swisseph.data` (12.1MB Emscripten preload - its
own copies of seas/semo/sepl_18.se1 + a 9.9MB asteroid-name file). We bypass it
with `getPreloadedPackage: (_n, size) => new ArrayBuffer(size)` and inject OUR
canonical files from `star_map/data/ephe/` (seas_18.se1, semo_18.se1,
sepl_18.se1 - 2,011,836 bytes total) into MEMFS at runtime, so browser results
are byte-faithful to the Python engine. Also not staged: `src/swisseph.js`
high-level wrapper (it cannot pass module config, so it would force the 12MB
preload download in a browser).

## Licensing (DECISION LOCKED 2026-06-12: free AGPL-3.0 path, no payment)

STARMAP ships the Swiss Ephemeris UNMODIFIED under its free **AGPL-3.0** option (not the paid commercial license). Full compliance is implemented: complete corresponding source is self-hosted at `/source/corresponding-source.tar.gz`, the offer + license texts are at `/source.html`, our calling files (`personal-sky.js`, `personal-sky-worker.js`) carry AGPL-3.0-or-later headers and are included in the archive, and a visible Source link appears in the moonnote + footer. Serve `LICENSE.txt` (the extensionless `LICENSE` 404s via the index-rewrite function). See PUD-150 + the AGPL briefing.

## Licensing (original notes)

- Wrapper package: **GPL-3.0-or-later** (Copyright 2024 prolaxu).
- Swiss Ephemeris C library compiled inside the .wasm: **dual-licensed** by
  Astrodienst AG - AGPL-3.0 (their public/free option; older releases used the
  "Swiss Ephemeris Public License", GPL-equivalent) OR a paid commercial
  license (swisseph@astro.com).
- Serving this on a free public web page under the free option requires:
  keep the LICENSE file, attribute Astrodienst's Swiss Ephemeris, and make the
  complete corresponding source available (links to
  https://github.com/prolaxu/swisseph-wasm and https://www.astro.com/swisseph/
  suffice while files are unmodified - this SOURCES.md serves that purpose).
  Any product-level decision (e.g. whether Starmap's overall posture is
  "commercial use" needing the Astrodienst paid license, and AGPL implications
  for the rest of the page's JS) is Colton's call - see RESULTS.md.
