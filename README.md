# SUNMAP

Sunrise, sunset, twilight, golden hour and the Moon - solved to the second for exactly where you stand, on any day from 1900 to 2099. Computed on your device.

**Live: [sunmap.puddystudios.com](https://sunmap.puddystudios.com)** - installable as a PWA, works offline, free.

## What it computes

The whole solar and lunar day, topocentrically, for a specific latitude and longitude: astronomical, nautical and civil dawn and dusk; both golden hours; sunrise and sunset at the refracted upper limb; solar noon and solar midnight; moonrise, moonset, lunar noon and lunar midnight, with the Moon's illumination and apparent diameter. Eighteen events, each printed to the second.

## How, and how accurately

Every instant is computed by a Swiss Ephemeris (DE441) engine compiled to WebAssembly and run on the device - nothing is fetched from a server. A second implementation that shares no code with the engine verifies the ladder event by event: the solar events against the NOAA Solar Calculator algorithm, the lunar events against an independent Meeus lunar series.

The remaining uncertainty is not in the arithmetic; it is in the air. The engine models 36.7 arcminutes of horizon refraction where the classic almanac convention is 34, and a real atmosphere departs from both, so an observed sunrise against a real horizon can differ from any computed one by a few tens of seconds. Every rise and set is solved against a clear sea-level horizon, the same reference every published almanac uses: from a summit the Sun clears the real horizon earlier than the printed time, and a ridge to your east delays sunrise by an amount no ephemeris can know. Other almanacs round to the minute and hide all of this. SUNMAP prints the second and names the limits.

## Provenance

SUNMAP debuted at sunmap.puddystudios.com on 2026-08-12, its DNS record created and verified in the second of the total solar eclipse's totality, 09:12:57 PDT. This repository carries the tool's development record from its first commit; production ships are documented as releases.

## License

AGPL-3.0-or-later. The compute engine is the Swiss Ephemeris, used under its AGPL license; the served application publishes its corresponding source, and this repository is that correspondence.

Built by [Puddy Studios](https://puddystudios.com). PUDDY ✵ DECENTRALIZED AI.
