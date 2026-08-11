# vendor/sweph - Swiss Ephemeris WebAssembly runtime

Minimal browser dist staged for SUNMAP, which solves the whole solar and lunar
day on the device: sunrise, sunset, the three twilights, both golden hours,
solar noon and midnight, moonrise, moonset, lunar noon and midnight, all
topocentric to the observer standing there.

This is the same engine, byte for byte, that STARMAP serves for its "Personal
Sky" recompute - same `swisseph.js`, same `swisseph.wasm`, same SHA-256. It was
selected and validated 2026-06-10; the numbers are in `star_map/.wasm-eval/RESULTS.md`.

## Package

- **Package**: `swisseph-wasm@0.0.5` (npm)
- **Upstream**: https://github.com/prolaxu/swisseph-wasm
- **npm**: https://www.npmjs.com/package/swisseph-wasm
- **Tarball**: https://registry.npmjs.org/swisseph-wasm/-/swisseph-wasm-0.0.5.tgz
- **Embedded C library**: Swiss Ephemeris 2.10.03 (Astrodienst AG,
  https://www.astro.com/swisseph/) - identical version to the pyswisseph
  2.10.03 used by `scripts/solar.py`, the build-time engine `sunmap-worker.js`
  is a port of. That is what lets the prerendered ladder and the hydrated one
  agree to the second.

## Files staged (verbatim from the npm package)

| File | From | Bytes |
|---|---|---|
| `swisseph.js` | `swisseph-wasm/wasm/swisseph.js` (Emscripten ESM glue, `export default Swisseph` factory) | 72,420 |
| `swisseph.wasm` | `swisseph-wasm/wasm/swisseph.wasm` | 543,953 |
| `LICENSE.txt` | `swisseph-wasm/LICENSE` (GPL-3.0-or-later + Swiss Ephemeris terms) | 1,498 |

Deliberately NOT staged: `wasm/swisseph.data` (12.1MB Emscripten preload - its
own copies of seas/semo/sepl_18.se1 plus a 9.9MB asteroid-name file). We bypass
it with `getPreloadedPackage: (_n, size) => new ArrayBuffer(size)` and inject OUR
canonical files from `sun_map/data/ephe/` (seas_18.se1, semo_18.se1,
sepl_18.se1) into MEMFS at runtime, so browser results are byte-faithful to the
Python engine. Also not staged: `src/swisseph.js` high-level wrapper (it cannot
pass module config, so it would force the 12MB preload download in a browser).

Serve `LICENSE.txt`, not an extensionless `LICENSE` - the index-rewrite
CloudFront function 404s the latter.

## Licensing (free AGPL-3.0 path, no payment)

SUNMAP ships the Swiss Ephemeris UNMODIFIED under its free **AGPL-3.0** option,
not the paid commercial license. Compliance is implemented, and it is a ship
gate rather than a nicety:

- Complete Corresponding Source is self-hosted at
  `/source/corresponding-source.tar.gz` - the Swiss Ephemeris 2.10.03 C source,
  the `swisseph-wasm@0.0.5` package, prolaxu's build harness with its
  `compile.sh`, and SUNMAP's own calling code.
- The written offer, the manifest of contents and the full AGPL and GPL texts
  are at `/source.html` and `/source/README.md`.
- `sunmap-worker.js` (the file that imports the engine, and therefore the
  combined work) carries an AGPL-3.0-or-later header and is included in the
  archive byte-identical to the served copy.
- A visible Source link sits in the page footer.

Rebuild the archive with `python3 scripts/build_source_archive.py`; it refuses
to write one whose engine files do not match the binary in this directory.
`python3 scripts/seo_check.py` asserts the whole surface resolves.

## Licensing (original upstream notes)

- Wrapper package: **GPL-3.0-or-later** (Copyright 2024 prolaxu).
- Swiss Ephemeris C library compiled inside the .wasm: **dual-licensed** by
  Astrodienst AG - AGPL-3.0 (their public/free option; older releases used the
  "Swiss Ephemeris Public License", GPL-equivalent) OR a paid commercial
  license (swisseph@astro.com).
- The bundled `LICENSE.txt` is the wrapper author's older summary and predates
  Astrodienst's AGPL relicensing. The authoritative text for the C library is
  `swisseph-2.10.03/LICENSE` inside the corresponding-source archive.
