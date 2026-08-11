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

/* SUNMAP - the solar and lunar day, solved on the device.
 *
 * Every event here is topocentric: a sunrise is a statement about one observer
 * on one patch of ground. So the engine runs in the browser and no coordinate
 * is ever sent anywhere.
 *
 * This is a port of scripts/solar.py onto the Swiss Ephemeris WASM build in
 * vendor/sweph/ - same 2.10.03 core, same JPL DE441 .se1 files, same call
 * sequence, same day model. The JSON it emits is interchangeable with the JSON
 * solar.py emits, so the page can consume either.
 *
 * In:  { base, coords:{lat,lon,alt}, date:"YYYY-MM-DD", tz:"IANA/Zone", moon:bool }
 * Out: { ok:true, result:<day result>, ms } | { ok:false, error }
 *
 * THE DAY MODEL, and why each piece is shaped the way it is:
 *
 *   - A day is the half-open interval from the first instant of the local date
 *     to the first instant of the next, found by BISECTION on the predicate
 *     "the local date at this instant is at or past the target". That is
 *     monotonic in every real zone, so it survives DST gaps (a zone that skips
 *     00:00 - Santiago, Havana - has no local midnight at all, and this returns
 *     01:00, the day's true first instant), DST overlaps, and historical offset
 *     changes. A spring-forward day is 23 hours and a fall-back day is 25.
 *     The zone is read from Intl, never from the host's own clock.
 *
 *   - Every key in LADDER appears in `events` on every day. An event that does
 *     not occur carries null times and a status saying why. An event that
 *     occurs TWICE inside a 25-hour fall-back day appears twice. Nothing is
 *     silently dropped and no time is ever invented.
 *
 *   - always_above / always_below are decided by MEASURING the body's altitude
 *     across the day on a two-minute grid, not by trusting a Swiss return code.
 *     The same track backstops the solver: if Swiss reports nothing but the sky
 *     crossed the threshold, the crossing is bisected out of the track instead
 *     of being lost. The track is built lazily, so an ordinary mid-latitude day
 *     never pays for it.
 *
 *   - The rise/set threshold is CALIBRATED FROM SWISS, not assumed. Swiss puts
 *     rise and set at a centre altitude of minus (refraction + semidiameter);
 *     the semidiameter is knowable and moves with distance, but the refraction
 *     depends on the observer's altitude through an internal pressure model the
 *     public API does not expose. So the track asks Swiss for a rise or set it
 *     CAN solve near this day and reads the refraction back out of the answer.
 *     Without this the fallback and the primary solver disagree by 10 to 60
 *     seconds and a rescued sunset sits out of line with the days either side.
 *
 *   - THE HORIZON DROPS AWAY BENEATH AN ELEVATED OBSERVER, so the Sun clears it
 *     EARLIER on a mountain than at the shore. Swiss does not model that. The
 *     observer altitude in geopos feeds an internal air PRESSURE model - thinner
 *     air, less refraction - and nothing else, an effect that is both tiny and
 *     BACKWARDS: measured at 33.9772 N, 118.4489 W for the 2026-08-12 sunrise,
 *     altitude alone moves it +2.4 s at 101 m, +23.0 s at 1000 m, +62.6 s at
 *     3000 m. Later as you climb. So the dip of the horizon is supplied
 *     explicitly as horhgt = -dip through swe_rise_trans_true_hor, which moves
 *     the same sunrise -103.2 s, -321.5 s and -547.3 s, and Swiss's pressure
 *     effect rides on top untouched. It applies to the four HORIZON_EVENTS
 *     only - never to a transit, which has no horizon in its definition, and
 *     never to the twilight or golden-hour bands, which are angles of the Sun's
 *     CENTRE measured from level.
 *
 *   - The moon block is TOPOCENTRIC: the Moon overhead is about 1.7 percent
 *     wider than the Moon on the geocentric books, and apparent_diameter_arcsec
 *     should mean what the observer would actually measure.
 *
 *   - Timestamps round to the millisecond and render the way Python's
 *     datetime.isoformat() renders them: six fractional digits when the
 *     microsecond field is non-zero, none at all when it is zero.
 *
 * `moon:false` skips the four lunar LADDER rows for speed. The moon
 * illumination block is always present - it is one cheap call and the data
 * contract requires the field.
 */
'use strict';

/* ------------------------------------------------------------- Swiss consts */

const SUN = 0, MOON = 1;
const FLG_SWIEPH = 2;
const FLG_EQUATORIAL = 2048;
const FLG_TOPOCTR = 32768;
const EQU2HOR = 1;
const GREG_CAL = 1;

const CALC_RISE = 1, CALC_SET = 2, CALC_MTRANSIT = 4, CALC_ITRANSIT = 8;
const BIT_DISC_CENTER = 256, BIT_NO_REFRACTION = 512;
const BIT_CIVIL = 1024, BIT_NAUTIC = 2048, BIT_ASTRO = 4096;

const EPHE_FILES = ['seas_18.se1', 'semo_18.se1', 'sepl_18.se1'];

/* Geometric altitude of the body's CENTRE at each event, in degrees. Used to
 * classify a non-event honestly and as the root function for the fallback
 * solver.
 *
 * The twilight and golden-hour thresholds are exact: swe_rise_trans lands on
 * them to better than 0.1 arcsec, measured.
 *
 * Rise and set are not a constant. The threshold is minus the sum of the body's
 * semidiameter and the depression of the horizon, the semidiameter moves with
 * distance, and the depression is two things at once: the refraction
 * swe_rise_trans applies, which depends on the observer's altitude through an
 * internal pressure model the public refraction API does not expose, plus the
 * dip this observer's elevation buys them. So RISE_SET is a sentinel: the
 * threshold is calibrated from Swiss itself per site, through the same call the
 * primary solver makes. See horizonDepression() in makeTrack. */
const RISE_SET = null;
const ALT_CIVIL = -6.0;
const ALT_NAUTICAL = -12.0;
const ALT_ASTRO = -18.0;
const GOLDEN_LOW = -4.0;
const GOLDEN_HIGH = 6.0;

/* The refraction swe_rise_trans uses at sea level, measured from the engine
 * itself: 36.739 arcmin, constant to 0.002 arcmin across latitude, season and
 * body. Only used when calibration cannot run, which is deep inside a polar
 * day or night where the nearest rise or set is weeks away and the body is
 * degrees clear of the horizon anyway. */
const DEFAULT_HORIZON_REFRACTION = 36.739 / 60.0;

/* The dip of the horizon, in arcminutes per square root of a metre of observer
 * height. 1.76 is the standard nautical value: it already carries the standard
 * terrestrial refraction along the long, low sight-line to the sea horizon,
 * which bends it back up a little. The purely geometric drop, ignoring air, is
 * 1.93 arcmin - arccos(R / (R + h)) with R the Earth's radius.
 *
 * Corroborated against Swiss's own dip, which it computes but does not apply to
 * rise and set: swe_refrac_extended returns -0.3224, -1.0145 and -1.7570 deg at
 * 101, 1000 and 3000 m, against -0.2948, -0.9276 and -1.6067 here. Same sign,
 * same size, differing only in the atmospheric model. */
const DIP_ARCMIN_PER_SQRT_METRE = 1.76;

/**
 * Degrees the visible horizon drops below level, for an observer altM up.
 *
 * Zero at and below sea level. A negative geodetic altitude is not a pit with a
 * raised horizon - Death Valley and the Dead Sea shore both see a horizon at
 * their own level - so the dip floors at zero rather than going NaN.
 */
function horizonDipDeg(altM) {
  const h = Number(altM);
  return DIP_ARCMIN_PER_SQRT_METRE * Math.sqrt(Number.isFinite(h) && h > 0 ? h : 0) / 60.0;
}

const RISE = 'rise', SET = 'set', TRANSIT_UP = 'transit_up', TRANSIT_DOWN = 'transit_down';

/* The full event ladder in chronological intent. This ordering is canonical:
 * it is how events with no time are ordered in the output, and it breaks ties
 * between two events that share an instant.
 *   key, label, body, direction, mode, rsmi_or_alt, threshold_alt_deg          */
const LADDER = [
  ['astronomical_dawn',    'Astronomical dawn',  'sun',  RISE,         'rsmi', CALC_RISE | BIT_ASTRO,  ALT_ASTRO],
  ['nautical_dawn',        'Nautical dawn',      'sun',  RISE,         'rsmi', CALC_RISE | BIT_NAUTIC, ALT_NAUTICAL],
  ['civil_dawn',           'Civil dawn',         'sun',  RISE,         'rsmi', CALC_RISE | BIT_CIVIL,  ALT_CIVIL],
  ['golden_hour_start_am', 'Golden hour begins', 'sun',  RISE,         'alt',  GOLDEN_LOW,             GOLDEN_LOW],
  ['sunrise',              'Sunrise',            'sun',  RISE,         'rsmi', CALC_RISE,              RISE_SET],
  ['golden_hour_end_am',   'Golden hour ends',   'sun',  RISE,         'alt',  GOLDEN_HIGH,            GOLDEN_HIGH],
  ['solar_noon',           'Solar noon',         'sun',  TRANSIT_UP,   'rsmi', CALC_MTRANSIT,          null],
  ['golden_hour_start_pm', 'Golden hour begins', 'sun',  SET,          'alt',  GOLDEN_HIGH,            GOLDEN_HIGH],
  ['sunset',               'Sunset',             'sun',  SET,          'rsmi', CALC_SET,               RISE_SET],
  ['golden_hour_end_pm',   'Golden hour ends',   'sun',  SET,          'alt',  GOLDEN_LOW,             GOLDEN_LOW],
  ['civil_dusk',           'Civil dusk',         'sun',  SET,          'rsmi', CALC_SET | BIT_CIVIL,   ALT_CIVIL],
  ['nautical_dusk',        'Nautical dusk',      'sun',  SET,          'rsmi', CALC_SET | BIT_NAUTIC,  ALT_NAUTICAL],
  ['astronomical_dusk',    'Astronomical dusk',  'sun',  SET,          'rsmi', CALC_SET | BIT_ASTRO,   ALT_ASTRO],
  ['solar_midnight',       'Solar midnight',     'sun',  TRANSIT_DOWN, 'rsmi', CALC_ITRANSIT,          null],
  ['moonrise',             'Moonrise',           'moon', RISE,         'rsmi', CALC_RISE,              null],
  ['lunar_noon',           'Lunar noon',         'moon', TRANSIT_UP,   'rsmi', CALC_MTRANSIT,          null],
  ['moonset',              'Moonset',            'moon', SET,          'rsmi', CALC_SET,               null],
  ['lunar_midnight',       'Lunar midnight',     'moon', TRANSIT_DOWN, 'rsmi', CALC_ITRANSIT,          null],
];

const LADDER_INDEX = Object.create(null);
LADDER.forEach((row, i) => { LADDER_INDEX[row[0]] = i; });

/* The four events defined by the VISIBLE horizon, and the only ones the dip
 * touches. Everything else in the ladder is defined against LEVEL: a transit has
 * no horizon in it at all, and the twilight and golden-hour bands are angles of
 * the Sun's centre below or above level, unchanged by how far the observer can
 * see. Named explicitly rather than inferred, so that adding a ladder row can
 * never silently opt it in or out - and cross-checked against the structure of
 * the ladder here, at load, because a mismatch would be a wrong TIME. */
const HORIZON_EVENTS = new Set(['sunrise', 'sunset', 'moonrise', 'moonset']);
{
  const structural = LADDER
    .filter((r) => r[4] === 'rsmi' && r[6] === null && (r[3] === RISE || r[3] === SET))
    .map((r) => r[0]);
  if (structural.length !== HORIZON_EVENTS.size || !structural.every((k) => HORIZON_EVENTS.has(k))) {
    throw new Error('HORIZON_EVENTS disagrees with LADDER: ' + structural.join(','));
  }
}

const BODY_ID = { sun: SUN, moon: MOON };

// One second in Julian days, and the nudge used to step past a solved event so
// the next search does not re-find the same one.
const SEC = 1.0 / 86400.0;
const NUDGE = 2.0 * SEC;

/* Two occurrences of the same event inside one local day are always close to 24
 * hours apart - the tightest pair measured over a year at seven sites is
 * 23h45m. So two times closer together than this are the same crossing reached
 * two different ways, never two events. */
const SAME_EVENT_S = 600.0;

/* How far back swe_rise_trans has to be re-seeded before it will return an event
 * it stepped over. Measured at Reykjavik on 2026-06-30: the sunset was 1.8 s
 * past the search start, and seeding 5 s, 30 s, 120 s or 600 s earlier all
 * skipped it and returned the following day's. Seeding 30 minutes earlier found
 * it. The ladder runs out to six hours for margin. */
const RESEED_BACKOFF_S = [1800.0, 5400.0, 10800.0, 21600.0];

/* ------------------------------------------------------------ time plumbing */

const MS_PER_DAY = 86400000;
const UNIX_EPOCH_JD = 2440587.5;

const msToJd = (ms) => ms / MS_PER_DAY + UNIX_EPOCH_JD;

/** Python's round(): half-to-even, unlike Math.round's half-up. */
function pyRound(x) {
  const f = Math.floor(x), diff = x - f;
  if (diff > 0.5) return f + 1;
  if (diff < 0.5) return f;
  return (f % 2 === 0) ? f : f + 1;
}

/**
 * Julian Day UT -> epoch ms, rounded to the millisecond.
 *
 * Goes through swe_revjul rather than a straight epoch subtraction so the
 * rounding happens on the SAME quantity solar.py rounds - the fractional hour
 * within the civil day. The two paths differ in the last ulp, and that is
 * enough to land on opposite sides of a half-millisecond boundary.
 */
function jdToMs(eng, jd) {
  const M = eng.M;
  // swe_revjul(double jd, int32 gregflag, int32 *jyear, int32 *jmon,
  //            int32 *jday, double *jut) - six arguments, six types.
  M.ccall('swe_revjul', null,
    ['number', 'number', 'number', 'number', 'number', 'number'],
    [jd, GREG_CAL, eng.revIPtr, eng.revIPtr + 4, eng.revIPtr + 8, eng.revDPtr]);
  const i32 = M.HEAP32, base = eng.revIPtr >> 2;
  const y = i32[base], mo = i32[base + 1], d = i32[base + 2];
  const h = M.HEAPF64[eng.revDPtr >> 3];
  let dayMs = Date.UTC(y, mo - 1, d);
  if (y >= 0 && y < 100) {           // Date.UTC maps 0-99 onto 1900-1999
    const t = new Date(dayMs);
    t.setUTCFullYear(y);
    dayMs = t.getTime();
  }
  return dayMs + pyRound(h * 3600 * 1000);
}

// Decimal rounding on the double's exact value, matching Python's round(v, n).
const round2 = (v) => Number(v.toFixed(2));
const round3 = (v) => Number(v.toFixed(3));

const pad = (n, w) => String(n).padStart(w, '0');

const formatters = new Map();
function zoneFormatter(tz) {
  let f = formatters.get(tz);
  if (!f) {
    f = new Intl.DateTimeFormat('en-US', {
      timeZone: tz, hourCycle: 'h23',
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    });
    formatters.set(tz, f);
  }
  return f;
}

function zoneParts(tz, utcMs) {
  const p = Object.create(null);
  for (const part of zoneFormatter(tz).formatToParts(utcMs)) p[part.type] = part.value;
  return p;
}

/** The local calendar date at an instant, as YYYY-MM-DD (sorts chronologically). */
function localDateAt(tz, utcMs) {
  const p = zoneParts(tz, utcMs);
  return pad(Number(p.year), 4) + '-' + p.month + '-' + p.day;
}

/** UTC offset of an IANA zone at an instant, in ms. */
function zoneOffsetMs(tz, utcMs) {
  const p = zoneParts(tz, utcMs);
  const hour = p.hour === '24' ? 0 : Number(p.hour);
  const wallAsUtc = Date.UTC(Number(p.year), Number(p.month) - 1, Number(p.day),
    hour, Number(p.minute), Number(p.second));
  // formatToParts truncates below the second; compare against a truncated
  // instant or the offset absorbs the sub-second remainder.
  return wallAsUtc - Math.floor(utcMs / 1000) * 1000;
}

/**
 * First instant of a local calendar date, by bisection on UTC seconds.
 *
 * The predicate "local date here is at or past the target" is monotonic in
 * every real zone, which is what makes this correct where naive midnight
 * arithmetic is not: in a zone whose clocks jump AT midnight there is no local
 * midnight to construct, and this still returns the day's true first instant.
 */
function firstInstantOf(tz, y, mo, d) {
  const target = pad(y, 4) + '-' + pad(mo, 2) + '-' + pad(d, 2);
  // Naive midnight is never more than 30 hours from the true first instant.
  const lo = Date.UTC(y, mo - 1, d) - 2 * MS_PER_DAY;
  let loS = Math.floor(lo / 1000);
  let hiS = loS + 4 * 86400;
  while (hiS - loS > 1) {
    const mid = Math.floor((loS + hiS) / 2);
    if (localDateAt(tz, mid * 1000) >= target) hiS = mid; else loS = mid;
  }
  return hiS * 1000;
}

/** Python datetime.isoformat() fractional-second rules, reproduced exactly. */
function frac(ms) {
  const rem = ((ms % 1000) + 1000) % 1000;
  return rem === 0 ? '' : '.' + pad(rem, 3) + '000';
}

function ymdhms(ms) {
  const t = new Date(ms);
  return pad(t.getUTCFullYear(), 4) + '-' + pad(t.getUTCMonth() + 1, 2) + '-' +
    pad(t.getUTCDate(), 2) + 'T' + pad(t.getUTCHours(), 2) + ':' +
    pad(t.getUTCMinutes(), 2) + ':' + pad(t.getUTCSeconds(), 2);
}

const isoZ = (ms) => ymdhms(ms) + frac(ms) + 'Z';

function isoLocal(ms, tz) {
  const off = zoneOffsetMs(tz, ms);
  const shifted = ms + off;
  const abs = Math.abs(off) / 1000;
  const oh = Math.floor(abs / 3600);
  const om = Math.floor(abs / 60) % 60;
  const os = Math.floor(abs) % 60;
  return ymdhms(shifted) + frac(shifted) + (off < 0 ? '-' : '+') +
    pad(oh, 2) + ':' + pad(om, 2) + (os ? ':' + pad(os, 2) : '');
}

/* ------------------------------------------------------------------- engine */

let enginePromise = null;

/**
 * Load the Swiss Ephemeris WASM and inject OUR .se1 files.
 *
 * The vendored package wants a 12MB Emscripten .data preload we do not ship;
 * getPreloadedPackage hands the loader an empty ArrayBuffer of the size it
 * asked for, which satisfies it with no download. The real ephemeris then goes
 * into MEMFS at /ephe and swe_set_ephe_path points the engine there. Same
 * pattern proven in STARMAP's personal-sky-worker.js.
 */
function initEngine(base) {
  if (enginePromise) return enginePromise;
  enginePromise = (async () => {
    const factory = (await import(base + 'vendor/sweph/swisseph.js')).default;
    const M = await factory({
      getPreloadedPackage: (_name, size) => new ArrayBuffer(size),
      locateFile: (f) => base + 'vendor/sweph/' + f,
    });
    try { M.FS.mkdir('/ephe'); } catch (_e) { /* already there */ }
    for (const f of EPHE_FILES) {
      const res = await fetch(base + 'data/ephe/' + f);
      if (!res.ok) throw new Error('ephemeris fetch failed: ' + f + ' (' + res.status + ')');
      M.FS.writeFile('/ephe/' + f, new Uint8Array(await res.arrayBuffer()));
    }
    M.ccall('swe_set_ephe_path', null, ['string'], ['/ephe']);

    // Allocated once for the life of the worker, never freed per call.
    //   geo  3 doubles in  (lon east-positive, lat, altitude metres)
    //   tret 10 doubles out (Swiss writes the event time into tret[0])
    //   attr 20 doubles out (swe_pheno_ut)
    //   xx   6 doubles out (swe_calc_ut)
    //   xin  3 doubles in  / xaz 3 doubles out (swe_azalt)
    //   serr 256 chars out
    const eng = {
      M,
      geoPtr:  M._malloc(3 * 8),
      tretPtr: M._malloc(10 * 8),
      attrPtr: M._malloc(20 * 8),
      xxPtr:   M._malloc(6 * 8),
      xinPtr:  M._malloc(3 * 8),
      xazPtr:  M._malloc(3 * 8),
      revIPtr: M._malloc(16),
      revDPtr: M._malloc(8),
      serrPtr: M._malloc(256),
    };
    M.ccall('swe_version', 'number', ['number'], [eng.serrPtr]);
    eng.version = M.UTF8ToString(eng.serrPtr) || '2.10.03';
    return eng;
  })();
  enginePromise = enginePromise.catch((err) => { enginePromise = null; throw err; });
  return enginePromise;
}

// swe_rise_trans(double tjd_ut, int32 ipl, char *starname, int32 epheflag,
//                int32 rsmi, double *geopos, double atpress, double attemp,
//                double *tret, char *serr)
const SIG_RT = ['number', 'number', 'number', 'number', 'number',
  'number', 'number', 'number', 'number', 'number'];
// swe_rise_trans_true_hor(..., double horhgt, double *tret, char *serr)
const SIG_RT_HOR = ['number', 'number', 'number', 'number', 'number',
  'number', 'number', 'number', 'number', 'number', 'number'];
// swe_azalt(double tjd_ut, int32 calc_flag, double *geopos, double atpress,
//           double attemp, double *xin, double *xaz)
const SIG_AZALT = ['number', 'number', 'number', 'number', 'number', 'number', 'number'];

/** Heap views are re-read on every access: a growing heap detaches the old ones. */
function setGeo(eng, lon, lat, alt) {
  const h = eng.M.HEAPF64, i = eng.geoPtr >> 3;
  h[i] = lon; h[i + 1] = lat; h[i + 2] = alt;
}

/** Null-terminate serr so a stale message from an earlier call cannot leak out. */
function clearErr(eng) {
  eng.M.HEAP32[eng.serrPtr >> 2] = 0;
}

/**
 * One Swiss rise/set/transit solve. Returns { jd, ret, err }.
 * Mirrors solar.py's _solve_one, including its error contract: a hard failure
 * (Swiss ERR) becomes an err string, while "no event" (-2) is a quiet null
 * that the altitude track is left to explain.
 *
 * `horhgt` is the height of the local horizon in degrees, negative when it is
 * depressed below level. It is the dip for the four HORIZON_EVENTS and zero for
 * everything else. At zero the call routes through swe_rise_trans, which is
 * what a sea-level observer got before the dip existed and is preserved
 * exactly: the two entry points agree to under 8 ms - solver convergence noise,
 * measured - and there is no reason to spend even that on a no-op.
 */
function solveOne(eng, jdStart, ipl, mode, rsmiOrAlt, direction, horhgt) {
  clearErr(eng);
  const hor = horhgt || 0.0;
  let ret;
  if (mode === 'rsmi') {
    ret = hor === 0.0
      ? eng.M.ccall('swe_rise_trans', 'number', SIG_RT,
        [jdStart, ipl, 0 /* starname NULL */, FLG_SWIEPH, rsmiOrAlt,
          eng.geoPtr, 0.0, 0.0, eng.tretPtr, eng.serrPtr])
      : eng.M.ccall('swe_rise_trans_true_hor', 'number', SIG_RT_HOR,
        [jdStart, ipl, 0, FLG_SWIEPH, rsmiOrAlt,
          eng.geoPtr, 0.0, 0.0, hor, eng.tretPtr, eng.serrPtr]);
  } else {
    const rsmi = (direction === RISE ? CALC_RISE : CALC_SET) | BIT_DISC_CENTER | BIT_NO_REFRACTION;
    ret = eng.M.ccall('swe_rise_trans_true_hor', 'number', SIG_RT_HOR,
      [jdStart, ipl, 0, FLG_SWIEPH, rsmi,
        eng.geoPtr, 0.0, 0.0, Number(rsmiOrAlt), eng.tretPtr, eng.serrPtr]);
  }
  if (ret === -1) {
    return { jd: null, ret: null, err: eng.M.UTF8ToString(eng.serrPtr) || 'swe_rise_trans failed' };
  }
  if (ret !== 0) return { jd: null, ret, err: null };
  return { jd: eng.M.HEAPF64[eng.tretPtr >> 3], ret: 0, err: null };
}

/** Topocentric moon phenomena. attr[0] phase angle, [1] phase, [3] diameter deg. */
function phenoTopo(eng, jd, ipl, lon, lat, altM) {
  eng.M.ccall('swe_set_topo', null, ['number', 'number', 'number'], [lon, lat, altM]);
  clearErr(eng);
  const ret = eng.M.ccall('swe_pheno_ut', 'number',
    ['number', 'number', 'number', 'number', 'number'],
    [jd, ipl, FLG_SWIEPH | FLG_TOPOCTR, eng.attrPtr, eng.serrPtr]);
  if (ret < 0) throw new Error(eng.M.UTF8ToString(eng.serrPtr) || 'swe_pheno_ut failed');
  const h = eng.M.HEAPF64, i = eng.attrPtr >> 3;
  return { phaseAngle: h[i], phase: h[i + 1], diamDeg: h[i + 3] };
}

/* ------------------------------------- the altitude track, the arbiter ----- */

/**
 * Geometric topocentric altitude of one body, sampled over one local day.
 *
 * This is what decides always_above / always_below, and what backstops the
 * Swiss solver: if Swiss reports no event but the altitude track crosses the
 * threshold, the crossing is found here by bisection rather than lost.
 */
function makeTrack(eng, body, geo, jd0, jd1) {
  const STEP_MIN = 2.0;      // altitude sampling step in minutes
  const SD_STEP_MIN = 30.0;  // semidiameter sampling step in minutes
  const ipl = BODY_ID[body];
  const [lon, lat, altM] = geo;
  const horhgt = -horizonDipDeg(altM);

  /** Geometric (unrefracted) topocentric altitude of the body's centre. */
  function altitude(jd) {
    const M = eng.M;
    M.ccall('swe_set_topo', null, ['number', 'number', 'number'], [lon, lat, altM]);
    clearErr(eng);
    const ret = M.ccall('swe_calc_ut', 'number',
      ['number', 'number', 'number', 'number', 'number'],
      [jd, ipl, FLG_SWIEPH | FLG_EQUATORIAL | FLG_TOPOCTR, eng.xxPtr, eng.serrPtr]);
    if (ret < 0) throw new Error(M.UTF8ToString(eng.serrPtr) || 'swe_calc_ut failed');
    const h = M.HEAPF64, xi = eng.xinPtr >> 3, xx = eng.xxPtr >> 3;
    h[xi] = h[xx]; h[xi + 1] = h[xx + 1]; h[xi + 2] = h[xx + 2];
    M.ccall('swe_azalt', null, SIG_AZALT,
      [jd, EQU2HOR, eng.geoPtr, 0.0, 0.0, eng.xinPtr, eng.xazPtr]);
    return M.HEAPF64[(eng.xazPtr >> 3) + 1];   // xaz[1] = true altitude
  }

  /** Topocentric apparent semidiameter of the body, in degrees. */
  function semidiameter(jd) {
    return phenoTopo(eng, jd, ipl, lon, lat, altM).diamDeg / 2.0;
  }

  /**
   * Semidiameter by interpolation on a half-hourly grid.
   *
   * The apparent size of the disc is the slowest-moving quantity in the whole
   * calculation, and asking Swiss for it at all 721 altitude samples costs more
   * than every other ephemeris call in the engine combined. Sampled every 30
   * minutes and interpolated linearly it is good to about 0.06 arcsec for the
   * Moon and a thousandth of that for the Sun, against a horizon whose two
   * competing definitions differ by 153 arcsec.
   *
   * Outside the sampled span it falls through to the exact call: the threshold
   * calibration reaches up to 24 days away from the window.
   */
  const sdStep = SD_STEP_MIN / 1440.0;
  const sdN = Math.max(2, Math.trunc((jd1 - jd0) / sdStep) + 2);
  const sdGrid = new Array(sdN).fill(null);
  function sd(jd) {
    const i = Math.trunc((jd - jd0) / sdStep);
    if (i < 0 || i + 1 >= sdN) return semidiameter(jd);
    for (const k of [i, i + 1]) {
      if (sdGrid[k] === null) sdGrid[k] = semidiameter(jd0 + k * sdStep);
    }
    const f = (jd - jd0) / sdStep - i;
    return sdGrid[i] + f * (sdGrid[i + 1] - sdGrid[i]);
  }

  let drop = null;

  /**
   * How far below level Swiss puts rise and set here, in degrees.
   *
   * Two effects in one number: the refraction Swiss applies, and the dip of the
   * visible horizon this observer's elevation buys them.
   *
   * Calibrated rather than assumed, and calibrated through THE SAME CALL the
   * primary solver makes - same horhgt, same flags. Swiss places rise and set at
   * a centre altitude of minus (depression plus semidiameter); the semidiameter
   * is knowable, so ask Swiss for a rise or set it CAN solve near this day,
   * measure the geometric centre altitude it chose, and subtract the
   * semidiameter. What is left is the depression Swiss is working to.
   *
   * Assembling it from parts instead would be wrong, not merely inelegant.
   * Refraction is not a constant the dip is added to: Swiss evaluates it at the
   * DEPRESSED altitude, where the sight-line runs further through the low air,
   * so it grows as the horizon falls. Measured at 33.9772 N, 118.4489 W: the
   * depression is 0.612 deg at sea level and 2.396 deg at 3000 m, where dip plus
   * the sea-level refraction would predict only 1.607 + 0.612 = 2.219. The
   * missing 0.18 deg is real refraction, worth some 40 seconds at the horizon's
   * rate of climb.
   *
   * This is what keeps the fallback solver definitionally identical to the
   * primary one. Without it the two disagree by 10 to 60 seconds, and a rescued
   * sunset sits visibly out of line with the days either side of it.
   */
  function horizonDepression() {
    if (drop !== null) return drop;
    const mid = 0.5 * (jd0 + jd1) - 0.5;
    const offsets = [0.0];
    for (let k = 1; k < 25; k++) { offsets.push(-k); offsets.push(k); }
    for (const offset of offsets) {
      for (const flag of [CALC_RISE, CALC_SET]) {
        setGeo(eng, lon, lat, altM);
        const r = solveOne(eng, mid + offset, ipl, 'rsmi', flag, null, horhgt);
        if (r.err !== null || r.jd === null) continue;
        drop = -altitude(r.jd) - sd(r.jd);
        return drop;
      }
    }
    // Deep polar day or night: no rise or set within 24 days to calibrate
    // against. The body is degrees clear of the horizon, so the sea-level
    // constant plus the dip is far more precision than the classification
    // needs. It is a floor on the true depression, never an overshoot.
    drop = DEFAULT_HORIZON_REFRACTION - horhgt;
    return drop;
  }

  /**
   * Threshold altitude at jd. Fixed for twilight, live for rise/set.
   *
   * `thr === null` reaches here only for the four HORIZON_EVENTS - the twilight
   * and golden-hour rows all carry a fixed angle, and transits never consult the
   * track - so the dip inside the depression is scoped to exactly the events
   * entitled to it.
   */
  function threshold(jd, thr) {
    if (thr !== null) return thr;
    return -(horizonDepression() + sd(jd));
  }

  const f = (jd, thr) => altitude(jd) - threshold(jd, thr);

  const n = Math.max(2, pyRound((jd1 - jd0) * 1440.0 / STEP_MIN) + 1);
  const grid = new Array(n);
  for (let i = 0; i < n; i++) grid[i] = jd0 + (jd1 - jd0) * i / (n - 1);
  const alt = grid.map(altitude);

  const gridCache = new Map();
  function gridF(thr) {
    if (!gridCache.has(thr)) {
      gridCache.set(thr, grid.map((j, i) => alt[i] - threshold(j, thr)));
    }
    return gridCache.get(thr);
  }

  function bisect(lo, hi, thr) {
    let fLo = f(lo, thr);
    while ((hi - lo) > 0.05 * SEC) {
      const mid = 0.5 * (lo + hi);
      const fMid = f(mid, thr);
      if ((fMid < 0.0) === (fLo < 0.0)) { lo = mid; fLo = fMid; } else { hi = mid; }
    }
    return 0.5 * (lo + hi);
  }

  return {
    /** (min, max) of altitude-minus-threshold across the day. */
    extrema(thr) {
      const vals = gridF(thr);
      let lo = Infinity, hi = -Infinity;
      for (const v of vals) { if (v < lo) lo = v; if (v > hi) hi = v; }
      return [lo, hi];
    },
    /** Every threshold crossing in the window, in the requested direction. */
    crossings(thr, direction) {
      const wantUp = direction === RISE;
      const vals = gridF(thr);
      const found = [];
      for (let i = 1; i < grid.length; i++) {
        const prevV = vals[i - 1], v = vals[i];
        const crossedUp = prevV < 0.0 && 0.0 <= v;
        const crossedDown = prevV > 0.0 && 0.0 >= v;
        if ((crossedUp && wantUp) || (crossedDown && !wantUp)) {
          found.push(bisect(grid[i - 1], grid[i], thr));
        }
      }
      return found;
    },
  };
}

/* ---------------------------------------------------------------- the solve */

/**
 * Ask Swiss again for an event it stepped over, seeding further back.
 *
 * Returns Swiss's own instant for the crossing at `target`, or null if no
 * backoff produces it. Swiss is the oracle, so where it CAN be made to answer
 * its answer is preferred to the altitude track's; the track is only there to
 * prove the event exists and to say roughly when.
 */
function reseed(eng, target, ipl, mode, rsmiOrAlt, direction, jd0, jd1, horhgt) {
  for (const back of RESEED_BACKOFF_S) {
    const r = solveOne(eng, target - back * SEC, ipl, mode, rsmiOrAlt, direction, horhgt);
    if (r.err !== null || r.jd === null) continue;
    if (Math.abs(r.jd - target) * 86400.0 <= SAME_EVENT_S && r.jd >= jd0 && r.jd < jd1) {
      return r.jd;
    }
  }
  return null;
}

/**
 * All occurrences of one event inside [jd0, jd1). Returns [jds, status].
 *
 * Walks the whole window rather than asking Swiss for "the next event after
 * midnight" and keeping it if it happens to land inside the day. That older
 * question lost events three ways: a second occurrence in a 25-hour fall-back
 * day was never looked for, an event outside the window vanished instead of
 * being reported absent, and a -2 return was called "circumpolar" even when the
 * Sun plainly rose and only a twilight threshold went unreached.
 *
 * Then it RECONCILES what Swiss returned against the measured altitude of the
 * body, UNCONDITIONALLY, and that is the point. swe_rise_trans steps over an
 * event that sits a few seconds past its search start: at Reykjavik on
 * 2026-06-30 the local day opens with a sunset 2.8 s after midnight, and Swiss
 * skips it and returns the day's OTHER sunset instead. Consulting the track only
 * when Swiss came back EMPTY misses exactly that case, because Swiss did not
 * come back empty - it came back one short, which looks identical to a normal
 * day from the outside. This engine used to make that mistake and drop the
 * sunset; solar.py did not, and the two disagreed by a whole event.
 */
function solveWindow(eng, spec, jd0, jd1, geo, trackFor) {
  const [key, , body, direction, mode, rsmiOrAlt, thr] = spec;
  const ipl = BODY_ID[body];
  const [lon, lat, altM] = geo;

  // The visible horizon drops away beneath an elevated observer. Only the four
  // HORIZON_EVENTS are defined against it; everything else is defined against
  // level and gets horhgt 0.
  const horhgt = HORIZON_EVENTS.has(key) ? -horizonDipDeg(altM) : 0.0;

  const jds = [];
  let cursor = jd0 - SEC;   // a hair early, so an event exactly at the boundary
  let err = null;           // instant is not stepped over
  for (let i = 0; i < 8; i++) {   // a 25-hour day holds at most two of anything
    const r = solveOne(eng, cursor, ipl, mode, rsmiOrAlt, direction, horhgt);
    err = r.err;
    if (err !== null || r.jd === null) break;
    if (r.jd >= jd1) break;
    if (r.jd >= jd0) jds.push(r.jd);
    cursor = r.jd + NUDGE;
    if (cursor >= jd1) break;
  }

  if (err !== null) return [[], 'error: ' + err];

  if (direction === TRANSIT_UP || direction === TRANSIT_DOWN) {
    // A transit has no threshold, so there is nothing to measure against and
    // nothing for Swiss to graze past. It always exists; the only honest empty
    // answer is that none of them landed in this local day.
    return jds.length ? [jds, 'ok'] : [[], 'none_today'];
  }

  // Measure the sky, every time, and adopt any crossing Swiss did not report.
  const track = trackFor(body);
  for (const crossing of track.crossings(thr, direction)) {
    if (jds.some((j) => Math.abs(crossing - j) * 86400.0 <= SAME_EVENT_S)) continue;
    setGeo(eng, lon, lat, altM);   // the track moved Swiss's topocentric observer
    const recovered = reseed(eng, crossing, ipl, mode, rsmiOrAlt, direction,
      jd0, jd1, horhgt);
    jds.push(recovered !== null ? recovered : crossing);
  }
  jds.sort((a, b) => a - b);

  if (jds.length) return [jds, 'ok'];

  const [lo, hi] = track.extrema(thr);
  if (lo > 0.0) return [[], 'always_above'];
  if (hi < 0.0) return [[], 'always_below'];
  // The threshold is crossed inside the window, but not in this event's
  // direction: the matching crossing sits on the other side of midnight.
  return [[], 'none_today'];
}

/**
 * Seconds from the day's sunrise to the sunset that follows it.
 *
 * The pair need not sit inside the same local day: at Tromso in mid-May the Sun
 * rises at 01:29 and does not set until 00:06 the next morning, and 22h37m is
 * the honest answer for how long that day was. Polar day returns the full
 * length of the local day, polar night returns 0. Both are measured facts.
 *
 * Sunrise and sunset are HORIZON_EVENTS, so the pair solved here carries the
 * same dip the ladder rows carry. Without that the printed day length would
 * contradict the printed sunrise and sunset by up to a quarter of an hour on a
 * mountain.
 */
function dayLength(eng, times, statuses, jd0, jd1, altM) {
  const windowS = pyRound((jd1 - jd0) * 86400.0);
  if (statuses.sunrise === 'always_above') return windowS;
  if (statuses.sunrise === 'always_below') return 0;

  const horhgt = -horizonDipDeg(altM);
  const rises = times.sunrise || [], sets = times.sunset || [];
  if (rises.length) {
    const sr = rises[0];
    const r = solveOne(eng, sr + NUDGE, SUN, 'rsmi', CALC_SET, SET, horhgt);
    if (r.jd !== null) return pyRound((r.jd - sr) * 86400.0);
    return null;
  }
  if (sets.length) {
    const ss = sets[0];
    // Walk forward from 36 hours back and keep the last sunrise before it.
    let cursor = ss - 1.5, best = null;
    for (let i = 0; i < 4; i++) {
      const r = solveOne(eng, cursor, SUN, 'rsmi', CALC_RISE, RISE, horhgt);
      if (r.jd === null || r.jd >= ss) break;
      best = r.jd;
      cursor = r.jd + NUDGE;
    }
    if (best !== null) return pyRound((ss - best) * 86400.0);
  }
  return null;
}

function parseDate(s) {
  const m = String(s == null ? '' : s).trim().match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) throw new Error('date must be YYYY-MM-DD, got: ' + s);
  return [Number(m[1]), Number(m[2]), Number(m[3])];
}

function todayIn(tz) {
  const p = zoneParts(tz, Date.now());
  return pad(Number(p.year), 4) + '-' + p.month + '-' + p.day;
}

/** Every solar and lunar event for one LOCAL calendar day at one location. */
function dayEvents(eng, lat, lon, altM, dateStr, tz, wantMoon) {
  const [y, mo, d] = parseDate(dateStr);
  const geo = [lon, lat, altM];
  setGeo(eng, lon, lat, altM);

  const startMs = firstInstantOf(tz, y, mo, d);
  const nx = new Date(Date.UTC(y, mo - 1, d + 1));
  const endMs = firstInstantOf(tz, nx.getUTCFullYear(), nx.getUTCMonth() + 1, nx.getUTCDate());
  const jd0 = msToJd(startMs), jd1 = msToJd(endMs);

  const tracks = Object.create(null);
  const trackFor = (body) => {
    if (!tracks[body]) tracks[body] = makeTrack(eng, body, geo, jd0, jd1);
    return tracks[body];
  };

  const events = [];
  const statuses = Object.create(null);
  const times = Object.create(null);

  for (const spec of LADDER) {
    const [key, label, body] = spec;
    if (!wantMoon && body === 'moon') continue;
    // Swiss's rise/set internals set the topocentric observer; re-assert ours
    // in case an altitude track moved it.
    setGeo(eng, lon, lat, altM);
    const [jds, status] = solveWindow(eng, spec, jd0, jd1, geo, trackFor);
    statuses[key] = status;
    times[key] = jds;
    if (!jds.length) {
      events.push({ key, label, body, utc: null, local: null, status });
      continue;
    }
    for (const jd of jds) {
      const ms = jdToMs(eng, jd);
      events.push({ key, label, body, utc: isoZ(ms), local: isoLocal(ms, tz), status });
    }
  }

  // solar.py's sort key: nulls last, then the raw UTC string, then ladder order.
  events.sort((a, b) => {
    const an = a.utc === null, bn = b.utc === null;
    if (an !== bn) return an ? 1 : -1;
    const au = a.utc || '', bu = b.utc || '';
    if (au < bu) return -1;
    if (au > bu) return 1;
    return LADDER_INDEX[a.key] - LADDER_INDEX[b.key];
  });

  setGeo(eng, lon, lat, altM);
  const dayLen = dayLength(eng, times, statuses, jd0, jd1, altM);

  // Sampled at the midpoint of the local day - a stable daily instant that
  // survives DST shifts - and topocentric, because the contract carries an
  // observer and apparent_diameter_arcsec should mean what they would measure.
  const ph = phenoTopo(eng, 0.5 * (jd0 + jd1), MOON, lon, lat, altM);

  return {
    date: pad(y, 4) + '-' + pad(mo, 2) + '-' + pad(d, 2),
    tz,
    observer: { lat, lon, alt_m: altM },
    engine: 'Swiss Ephemeris ' + eng.version + ' (JPL DE441), swe_rise_trans, topocentric',
    day_length_s: dayLen,
    moon: {
      illumination_pct: round2(ph.phase * 100),
      phase_angle_deg: round3(ph.phaseAngle),
      apparent_diameter_arcsec: round2(ph.diamDeg * 3600),
    },
    events,
  };
}

/* ------------------------------------------------------------------ message */

const DEFAULT_BASE = new URL('./', import.meta.url).href;

self.onmessage = async (ev) => {
  const t0 = Date.now();
  try {
    const msg = ev.data || {};
    const coords = msg.coords || {};
    const lat = Number(coords.lat), lon = Number(coords.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
      throw new Error('coords.lat and coords.lon are required numbers');
    }
    if (!msg.tz) throw new Error('tz is required (an IANA zone name)');
    const eng = await initEngine(msg.base || DEFAULT_BASE);
    const result = dayEvents(eng, lat, lon, Number(coords.alt) || 0,
      msg.date || todayIn(msg.tz), msg.tz, msg.moon !== false);
    self.postMessage({ ok: true, result, ms: Date.now() - t0 });
  } catch (e) {
    self.postMessage({ ok: false, error: String((e && e.message) || e) });
  }
};
