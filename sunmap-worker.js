/*!
 * SPDX-License-Identifier: AGPL-3.0-or-later
 * Copyright (C) 2026 PUDDY Inc.
 *
 * SUNMAP compute worker. This file dynamically links the Swiss Ephemeris
 * (Copyright Astrodienst AG), compiled to WebAssembly by swisseph-wasm
 * (GPL-3.0-or-later, Copyright 2024 prolaxu), and therefore forms a COMBINED
 * WORK with it. Free software under the GNU AGPL v3.0 or later, NO WARRANTY.
 * https://www.gnu.org/licenses/agpl-3.0.html
 *
 * The Swiss Ephemeris is used UNMODIFIED under its free AGPL-3.0 option.
 * Complete Corresponding Source: https://sunmap.puddystudios.com/source.html
 */

/* Every event SUNMAP shows is topocentric: a sunrise is a statement about one
 * observer on one patch of ground. So the engine runs here, on the device, and
 * no coordinate is ever sent anywhere.
 *
 * In:  { base, coords:{lat,lon,alt}, date:"YYYY-MM-DD", tz:"IANA/Zone", moon:bool }
 * Out: { ok:true, result:<day result>, ms } | { ok:false, error }
 * The day result is shape-identical to scripts/solar.py's JSON.
 */
'use strict';

const SUN = 0, MOON = 1;
const FLG_SWIEPH = 2;

const CALC_RISE = 1, CALC_SET = 2, CALC_MTRANSIT = 4, CALC_ITRANSIT = 8;
const BIT_DISC_CENTER = 256, BIT_NO_REFRACTION = 512;
const BIT_CIVIL = 1024, BIT_NAUTIC = 2048, BIT_ASTRO = 4096;

// The ladder, mirroring scripts/solar.py exactly.
const SUN_EVENTS = [
  ['astronomical_dawn', 'Astronomical dawn', CALC_RISE | BIT_ASTRO],
  ['nautical_dawn',     'Nautical dawn',     CALC_RISE | BIT_NAUTIC],
  ['civil_dawn',        'Civil dawn',        CALC_RISE | BIT_CIVIL],
  ['sunrise',           'Sunrise',           CALC_RISE],
  ['solar_noon',        'Solar noon',        CALC_MTRANSIT],
  ['sunset',            'Sunset',            CALC_SET],
  ['civil_dusk',        'Civil dusk',        CALC_SET | BIT_CIVIL],
  ['nautical_dusk',     'Nautical dusk',     CALC_SET | BIT_NAUTIC],
  ['astronomical_dusk', 'Astronomical dusk', CALC_SET | BIT_ASTRO],
  ['solar_midnight',    'Solar midnight',    CALC_ITRANSIT],
];

const MOON_EVENTS = [
  ['moonrise',        'Moonrise',        CALC_RISE],
  ['lunar_noon',      'Lunar noon',      CALC_MTRANSIT],
  ['moonset',         'Moonset',         CALC_SET],
  ['lunar_midnight',  'Lunar midnight',  CALC_ITRANSIT],
];

// Golden hour is an altitude band, not a Swiss bit flag: the sun's centre
// between -4 and +6 degrees geometric altitude.
const BANDS = [
  ['golden_hour_start_am', 'Golden hour begins', -4.0, true],
  ['golden_hour_end_am',   'Golden hour ends',    6.0, true],
  ['golden_hour_start_pm', 'Golden hour begins',  6.0, false],
  ['golden_hour_end_pm',   'Golden hour ends',   -4.0, false],
];

let enginePromise = null;

function initEngine(base) {
  if (enginePromise) return enginePromise;
  enginePromise = (async () => {
    const factory = (await import(base + 'vendor/sweph/swisseph.js')).default;
    const M = await factory({
      // Bypass the package's 12MB .data preload; we inject our own ephemeris.
      getPreloadedPackage: (_name, size) => new ArrayBuffer(size),
      locateFile: (f) => base + 'vendor/sweph/' + f,
    });
    M.FS.mkdir('/ephe');
    for (const f of ['seas_18.se1', 'semo_18.se1', 'sepl_18.se1']) {
      const buf = await (await fetch(base + 'data/ephe/' + f)).arrayBuffer();
      M.FS.writeFile('/ephe/' + f, new Uint8Array(buf));
    }
    M.ccall('swe_set_ephe_path', null, ['string'], ['/ephe']);

    // Allocate once. Emscripten heap views are re-read on every access below
    // because a growing heap detaches the old typed-array view.
    const geoPtr  = M._malloc(3 * 8);
    const tretPtr = M._malloc(10 * 8);
    const attrPtr = M._malloc(20 * 8);
    const serrPtr = M._malloc(256);
    return { M, geoPtr, tretPtr, attrPtr, serrPtr };
  })();
  enginePromise = enginePromise.catch((err) => { enginePromise = null; throw err; });
  return enginePromise;
}

/* ---- time helpers ---- */

const UNIX_EPOCH_JD = 2440587.5;
const msToJd = (ms) => ms / 86400000 + UNIX_EPOCH_JD;
const jdToMs = (jd) => (jd - UNIX_EPOCH_JD) * 86400000;

/** Offset of an IANA zone from UTC, in ms, at a given instant. */
function tzOffsetMs(instantMs, tz) {
  const d = new Date(instantMs);
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: tz, hour12: false,
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  }).formatToParts(d).reduce((a, p) => (a[p.type] = p.value, a), {});
  // Interpret the wall-clock reading as if it were UTC, then difference.
  const asUTC = Date.UTC(+parts.year, +parts.month - 1, +parts.day,
    +parts.hour % 24, +parts.minute, +parts.second);
  return asUTC - (Math.floor(instantMs / 1000) * 1000);
}

/** UTC ms for local midnight of `dateStr` in `tz`. Handles DST by iterating. */
function localMidnightMs(dateStr, tz) {
  const [y, m, d] = dateStr.split('-').map(Number);
  let guess = Date.UTC(y, m - 1, d, 0, 0, 0);
  for (let i = 0; i < 3; i++) {
    const off = tzOffsetMs(guess, tz);
    const corrected = Date.UTC(y, m - 1, d, 0, 0, 0) - off;
    if (Math.abs(corrected - guess) < 1000) { guess = corrected; break; }
    guess = corrected;
  }
  return guess;
}

function isoZ(ms) {
  return new Date(Math.round(ms)).toISOString().replace(/\.(\d{3})\d*Z$/, '.$1Z');
}

/** Local ISO string (with offset) for an instant in a zone. */
function isoLocal(ms, tz) {
  const off = tzOffsetMs(ms, tz);
  const shifted = new Date(ms + off);
  const sign = off >= 0 ? '+' : '-';
  const a = Math.abs(off) / 60000;
  const hh = String(Math.floor(a / 60)).padStart(2, '0');
  const mm = String(Math.round(a % 60)).padStart(2, '0');
  return shifted.toISOString().slice(0, 23) + sign + hh + ':' + mm;
}

/* ---- the Swiss calls ---- */

function setGeo(eng, lon, lat, alt) {
  const { M, geoPtr } = eng;
  const h = M.HEAPF64;            // re-read: heap growth detaches old views
  h[geoPtr / 8] = lon;
  h[geoPtr / 8 + 1] = lat;
  h[geoPtr / 8 + 2] = alt;
}

/**
 * swe_rise_trans(double tjd_ut, int32 ipl, char *starname, int32 epheflag,
 *                int32 rsmi, double *geopos, double atpress, double attemp,
 *                double *tret, char *serr)
 */
function riseTrans(eng, jd, body, rsmi) {
  const { M, geoPtr, tretPtr, serrPtr } = eng;
  const ret = M.ccall('swe_rise_trans', 'number',
    ['number', 'number', 'number', 'number', 'number',
     'number', 'number', 'number', 'number', 'number'],
    [jd, body, 0, FLG_SWIEPH, rsmi, geoPtr, 0.0, 0.0, tretPtr, serrPtr]);
  if (ret === -2) return { status: 'circumpolar', jd: null };
  if (ret < 0) return { status: 'error: ' + M.UTF8ToString(serrPtr), jd: null };
  return { status: 'ok', jd: M.HEAPF64[tretPtr / 8] };
}

/**
 * swe_rise_trans_true_hor(..., double horhgt, double *tret, char *serr)
 * One extra double before tret.
 */
function riseTransAlt(eng, jd, body, rising, altDeg) {
  const { M, geoPtr, tretPtr, serrPtr } = eng;
  const rsmi = (rising ? CALC_RISE : CALC_SET) | BIT_DISC_CENTER | BIT_NO_REFRACTION;
  const ret = M.ccall('swe_rise_trans_true_hor', 'number',
    ['number', 'number', 'number', 'number', 'number',
     'number', 'number', 'number', 'number', 'number', 'number'],
    [jd, body, 0, FLG_SWIEPH, rsmi, geoPtr, 0.0, 0.0, altDeg, tretPtr, serrPtr]);
  if (ret === -2) return { status: 'circumpolar', jd: null };
  if (ret < 0) return { status: 'error: ' + M.UTF8ToString(serrPtr), jd: null };
  return { status: 'ok', jd: M.HEAPF64[tretPtr / 8] };
}

/** swe_pheno_ut(double tjd_ut, int32 ipl, int32 iflag, double *attr, char *serr) */
function phenoUt(eng, jd, body) {
  const { M, attrPtr, serrPtr } = eng;
  const ret = M.ccall('swe_pheno_ut', 'number',
    ['number', 'number', 'number', 'number', 'number'],
    [jd, body, FLG_SWIEPH, attrPtr, serrPtr]);
  if (ret < 0) return null;
  const h = M.HEAPF64, i = attrPtr / 8;
  return { phaseAngle: h[i], illum: h[i + 1], diamArcsec: h[i + 3] * 3600 };
}

/* ---- the day solve ---- */

function solveDay(eng, coords, dateStr, tz, wantMoon) {
  setGeo(eng, coords.lon, coords.lat, coords.alt || 0);

  const startMs = localMidnightMs(dateStr, tz);
  const endMs = startMs + 24 * 3600 * 1000 + tzOffsetMs(startMs, tz) - tzOffsetMs(startMs + 86400000, tz);
  const jd0 = msToJd(startMs);

  const events = [];
  const push = (key, label, body, res) => {
    if (res.jd === null) {
      events.push({ key, label, body, utc: null, local: null, status: res.status });
      return;
    }
    const ms = jdToMs(res.jd);
    if (ms < startMs || ms >= endMs) return;   // not in this local day
    events.push({
      key, label, body,
      utc: isoZ(ms), local: isoLocal(ms, tz), status: 'ok',
    });
  };

  for (const [key, label, rsmi] of SUN_EVENTS) {
    // Search from just before local midnight so an event at 00:0x is not missed,
    // then window-filter. A second probe a day back catches transits that the
    // first call resolves past the window (the high-latitude case).
    let r = riseTrans(eng, jd0 - 0.05, SUN, rsmi);
    if (r.jd !== null && jdToMs(r.jd) >= endMs) {
      const back = riseTrans(eng, jd0 - 1.05, SUN, rsmi);
      if (back.jd !== null && jdToMs(back.jd) >= startMs && jdToMs(back.jd) < endMs) r = back;
    }
    push(key, label, 'sun', r);
  }

  for (const [key, label, altDeg, rising] of BANDS) {
    push(key, label, 'sun', riseTransAlt(eng, jd0 - 0.05, SUN, rising, altDeg));
  }

  if (wantMoon) {
    for (const [key, label, rsmi] of MOON_EVENTS) {
      let r = riseTrans(eng, jd0 - 0.05, MOON, rsmi);
      if (r.jd !== null && jdToMs(r.jd) >= endMs) {
        const back = riseTrans(eng, jd0 - 1.05, MOON, rsmi);
        if (back.jd !== null && jdToMs(back.jd) >= startMs && jdToMs(back.jd) < endMs) r = back;
      }
      push(key, label, 'moon', r);
    }
  }

  events.sort((a, b) => {
    if (a.utc === null && b.utc === null) return 0;
    if (a.utc === null) return 1;
    if (b.utc === null) return -1;
    return a.utc < b.utc ? -1 : a.utc > b.utc ? 1 : 0;
  });

  const byKey = Object.fromEntries(events.map((e) => [e.key, e]));
  let dayLen = null;
  if (byKey.sunrise && byKey.sunrise.utc && byKey.sunset && byKey.sunset.utc) {
    dayLen = Math.round((Date.parse(byKey.sunset.utc) - Date.parse(byKey.sunrise.utc)) / 1000);
  }

  const ph = phenoUt(eng, msToJd(startMs + 12 * 3600 * 1000), MOON);

  return {
    date: dateStr,
    tz,
    observer: { lat: coords.lat, lon: coords.lon, alt_m: coords.alt || 0 },
    engine: 'Swiss Ephemeris 2.10.03 (JPL DE441), swe_rise_trans, topocentric, on-device',
    day_length_s: dayLen,
    moon: ph ? {
      illumination_pct: Math.round(ph.illum * 10000) / 100,
      phase_angle_deg: Math.round(ph.phaseAngle * 1000) / 1000,
      apparent_diameter_arcsec: Math.round(ph.diamArcsec * 100) / 100,
    } : null,
    events,
  };
}

self.onmessage = async (ev) => {
  const t0 = Date.now();
  const { base, coords, date, tz, moon } = ev.data || {};
  try {
    const eng = await initEngine(base || '/');
    const result = solveDay(eng, coords, date, tz, moon !== false);
    self.postMessage({ ok: true, result, ms: Date.now() - t0 });
  } catch (e) {
    self.postMessage({ ok: false, error: String((e && e.message) || e) });
  }
};
