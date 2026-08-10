#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 PUDDY Inc. <legal@puddystudios.com>
"""SUNMAP engine - the daily solar and lunar cycle, solved to the second.

Every event here is TOPOCENTRIC by nature: a sunrise is a statement about one
observer on one patch of ground. That is the difference from STARMAP, whose
events are mostly geocentric instants true for the whole planet.

Engine: Swiss Ephemeris (pyswisseph) `swe_rise_trans` on the JPL DE441
ephemerides, the same engine and the same data files STARMAP ships.

Cross-check: scripts/verify_solar.py runs an independent NOAA-algorithm
implementation over the same inputs and reports per-event deltas.

Usage:
  python3 solar.py --lat 34.0522 --lon -118.2437 --date 2026-08-09 --tz America/Los_Angeles


THE DAY MODEL
-------------
A day result covers ONE LOCAL CALENDAR DAY: the half-open interval from the
first instant of that local date to the first instant of the next, in the
observer's own timezone. The bounds are solved by bisection on real UTC
instants, so a DST spring-forward day is 23 hours, a fall-back day is 25, and
a zone whose clocks jump AT midnight (Santiago, Beirut, Havana) still gets its
true first instant rather than a local time that does not exist.

Every event key in LADDER appears in `events` on every day, always. An event
that does not occur carries `utc: null`, `local: null` and a status that says
why. An event that occurs twice inside one local day appears twice - which
happens on a 25-hour fall-back day, and also near a polar boundary where the
event drifts across midnight. Nothing is ever silently dropped, and no time is
ever invented.

Holding that true takes more than asking Swiss. swe_rise_trans steps over an
event that sits a few seconds past its search start, so every threshold event's
occurrence LIST is reconciled against the body's measured altitude, on every
day, not only on the days Swiss comes back empty. See _solve_window.


STATUS VOCABULARY
-----------------
  ok             The event occurred at the reported instant.
  always_above   The body stayed ABOVE this event's altitude threshold for the
                 whole local day, so the crossing never happened. On
                 sunrise/sunset this is polar day (midnight sun). On a twilight
                 event it means the night never deepened that far. On
                 moonrise/moonset it is the classical "circumpolar" Moon.
  always_below   The body stayed BELOW this event's threshold all day. On
                 sunrise/sunset this is polar night. On moonrise/moonset the
                 Moon never rose.
  none_today     The crossing exists in the ongoing cycle but none of them fell
                 inside this local day. Routine for the Moon (its day is 24h50m,
                 so roughly once a month a local day contains no moonrise), and
                 for Sun events on the days that bracket a polar-day or
                 polar-night transition.
  error: <msg>   The solver failed. Surfaced, never swallowed.

`always_above` / `always_below` are decided by measuring the body's actual
altitude across the day, not by trusting a solver return code.
"""
import argparse
import json
from datetime import datetime, time as _time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import swisseph as swe

EPHE = str((Path(__file__).resolve().parents[1] / "data" / "ephe"))
swe.set_ephe_path(EPHE)

FLAGS = swe.FLG_SWIEPH

# Geometric altitude of the body's CENTRE at the moment of each event, in
# degrees. Used to classify a non-event honestly (always above vs always below)
# and as the root function for the fallback solver.
#
# The twilight and golden-hour thresholds are exact: swe_rise_trans lands on
# them to better than 0.1 arcsec, measured.
#
# Rise and set are not a constant. The threshold is minus the sum of the
# body's semidiameter and the refraction at the horizon, the semidiameter
# moves with distance, and the refraction swe_rise_trans applies depends on
# the observer's altitude through an internal pressure model that the public
# refraction API does not expose. So RISE_SET is a sentinel: the threshold is
# calibrated from Swiss itself per site. See _AltitudeTrack._refraction.
RISE_SET = None
ALT_CIVIL = -6.0
ALT_NAUTICAL = -12.0
ALT_ASTRO = -18.0
GOLDEN_LOW = -4.0
GOLDEN_HIGH = 6.0

# The refraction swe_rise_trans uses at sea level, measured from the engine
# itself: 36.739 arcmin, constant to 0.002 arcmin across latitude, season and
# body. Only used when calibration cannot run, which is deep inside a polar
# day or night where the nearest rise or set is weeks away and the body is
# degrees clear of the horizon anyway.
DEFAULT_HORIZON_REFRACTION = 36.739 / 60.0

RISE, SET, TRANSIT_UP, TRANSIT_DOWN = "rise", "set", "transit_up", "transit_down"

# The full event ladder in chronological intent. This ordering is the canonical
# one: it is how events with no time are ordered in the output, and it is the
# contract the UI reads.
#   key, label, body, direction, mode, rsmi, threshold_alt_deg
LADDER = [
    ("astronomical_dawn",    "Astronomical dawn",  "sun",  RISE,          "rsmi", swe.CALC_RISE | swe.BIT_ASTRO_TWILIGHT,  ALT_ASTRO),
    ("nautical_dawn",        "Nautical dawn",      "sun",  RISE,          "rsmi", swe.CALC_RISE | swe.BIT_NAUTIC_TWILIGHT, ALT_NAUTICAL),
    ("civil_dawn",           "Civil dawn",         "sun",  RISE,          "rsmi", swe.CALC_RISE | swe.BIT_CIVIL_TWILIGHT,  ALT_CIVIL),
    ("golden_hour_start_am", "Golden hour begins", "sun",  RISE,          "alt",  GOLDEN_LOW,                              GOLDEN_LOW),
    ("sunrise",              "Sunrise",            "sun",  RISE,          "rsmi", swe.CALC_RISE,                           RISE_SET),
    ("golden_hour_end_am",   "Golden hour ends",   "sun",  RISE,          "alt",  GOLDEN_HIGH,                             GOLDEN_HIGH),
    ("solar_noon",           "Solar noon",         "sun",  TRANSIT_UP,    "rsmi", swe.CALC_MTRANSIT,                       None),
    ("golden_hour_start_pm", "Golden hour begins", "sun",  SET,           "alt",  GOLDEN_HIGH,                             GOLDEN_HIGH),
    ("sunset",               "Sunset",             "sun",  SET,           "rsmi", swe.CALC_SET,                            RISE_SET),
    ("golden_hour_end_pm",   "Golden hour ends",   "sun",  SET,           "alt",  GOLDEN_LOW,                              GOLDEN_LOW),
    ("civil_dusk",           "Civil dusk",         "sun",  SET,           "rsmi", swe.CALC_SET | swe.BIT_CIVIL_TWILIGHT,   ALT_CIVIL),
    ("nautical_dusk",        "Nautical dusk",      "sun",  SET,           "rsmi", swe.CALC_SET | swe.BIT_NAUTIC_TWILIGHT,  ALT_NAUTICAL),
    ("astronomical_dusk",    "Astronomical dusk",  "sun",  SET,           "rsmi", swe.CALC_SET | swe.BIT_ASTRO_TWILIGHT,   ALT_ASTRO),
    ("solar_midnight",       "Solar midnight",     "sun",  TRANSIT_DOWN,  "rsmi", swe.CALC_ITRANSIT,                       None),
    ("moonrise",             "Moonrise",           "moon", RISE,          "rsmi", swe.CALC_RISE,                           None),
    ("lunar_noon",           "Lunar noon",         "moon", TRANSIT_UP,    "rsmi", swe.CALC_MTRANSIT,                       None),
    ("moonset",              "Moonset",            "moon", SET,           "rsmi", swe.CALC_SET,                            None),
    ("lunar_midnight",       "Lunar midnight",     "moon", TRANSIT_DOWN,  "rsmi", swe.CALC_ITRANSIT,                       None),
]

LADDER_INDEX = {row[0]: i for i, row in enumerate(LADDER)}

BODY_ID = {"sun": swe.SUN, "moon": swe.MOON}

# One second in Julian days, and the nudge used to step past a solved event so
# the next search does not re-find the same one.
_SEC = 1.0 / 86400.0
_NUDGE = 2.0 * _SEC

# Two occurrences of the same event inside one local day are always close to 24
# hours apart - the tightest pair measured over a year at seven sites is 23h45m.
# So two times closer together than this are the same crossing reached two
# different ways, never two events.
_SAME_EVENT_S = 600.0

# How far back swe_rise_trans has to be re-seeded before it will return an event
# it stepped over. Measured at Reykjavik on 2026-06-30: the sunset was 1.8 s
# past the search start, and seeding 5 s, 30 s, 120 s or 600 s earlier all
# skipped it and returned the following day's. Seeding 30 minutes earlier found
# it. The ladder runs out to six hours for margin.
_RESEED_BACKOFF_S = (1800.0, 5400.0, 10800.0, 21600.0)


# ---------------------------------------------------------------------------
# Time plumbing
# ---------------------------------------------------------------------------

def jd_utc(dt):
    """datetime (aware) -> Julian Day UT."""
    dt = dt.astimezone(timezone.utc)
    return swe.julday(dt.year, dt.month, dt.day,
                      dt.hour + dt.minute / 60 + (dt.second + dt.microsecond / 1e6) / 3600,
                      swe.GREG_CAL)


def jd_to_dt(jd):
    """Julian Day UT -> aware UTC datetime, rounded to the millisecond."""
    y, m, d, h = swe.revjul(jd, swe.GREG_CAL)
    total_ms = round(h * 3600 * 1000)
    base = datetime(int(y), int(m), int(d), tzinfo=timezone.utc)
    return base + timedelta(milliseconds=total_ms)


def local_day_bounds(day, tzname):
    """First instant of local date `day`, and first instant of the next date.

    Solved by bisection on UTC seconds against the predicate "the local date at
    this instant is >= day". That is monotonic for every real timezone, so it
    is correct across DST gaps (a zone whose clocks skip 00:00 has no local
    midnight at all, and this returns 01:00 local, the day's true first
    instant), across DST overlaps, and across historical offset changes.
    """
    tz = ZoneInfo(tzname)

    def first_instant_of(target):
        # A window guaranteed to straddle the boundary: naive midnight is never
        # more than 30 hours away from the true first instant in any real zone.
        lo = datetime.combine(target, _time(0), tzinfo=timezone.utc) - timedelta(days=2)
        hi = lo + timedelta(days=4)
        assert lo.astimezone(tz).date() < target <= hi.astimezone(tz).date()
        lo_s, hi_s = int(lo.timestamp()), int(hi.timestamp())
        while hi_s - lo_s > 1:
            mid = (lo_s + hi_s) // 2
            m = datetime.fromtimestamp(mid, timezone.utc)
            if m.astimezone(tz).date() >= target:
                hi_s = mid
            else:
                lo_s = mid
        return datetime.fromtimestamp(hi_s, timezone.utc)

    return first_instant_of(day), first_instant_of(day + timedelta(days=1))


# ---------------------------------------------------------------------------
# Altitude sampling - the independent arbiter
# ---------------------------------------------------------------------------

class _AltitudeTrack:
    """Geometric topocentric altitude of one body, sampled over one local day.

    This is what decides `always_above` / `always_below`, and what backstops the
    Swiss solver: if Swiss reports no event but the altitude track crosses the
    threshold, the crossing is found here by bisection rather than lost.
    """

    STEP_MIN = 2.0      # altitude sampling step in minutes
    SD_STEP_MIN = 30.0  # semidiameter sampling step in minutes

    def __init__(self, body, geo, jd0, jd1):
        self.body = body
        self.ipl = BODY_ID[body]
        self.geo = geo
        self.jd0 = jd0
        self.jd1 = jd1
        n = max(2, int(round((jd1 - jd0) * 1440.0 / self.STEP_MIN)) + 1)
        self.grid = [jd0 + (jd1 - jd0) * i / (n - 1) for i in range(n)]
        self.alt = [self.altitude(j) for j in self.grid]
        self._grid_cache = {}
        self._refr = None
        self._sd_step = self.SD_STEP_MIN / 1440.0
        self._sd_n = max(2, int((jd1 - jd0) / self._sd_step) + 2)
        self._sd_grid = [None] * self._sd_n

    def altitude(self, jd):
        """Geometric (unrefracted) topocentric altitude of the body's centre."""
        lon, lat, alt_m = self.geo
        swe.set_topo(lon, lat, alt_m)
        xx, _ = swe.calc_ut(jd, self.ipl,
                            FLAGS | swe.FLG_EQUATORIAL | swe.FLG_TOPOCTR)
        xaz = swe.azalt(jd, swe.EQU2HOR, self.geo, 0.0, 0.0, (xx[0], xx[1], xx[2]))
        return xaz[1]

    def semidiameter(self, jd):
        """Topocentric apparent semidiameter of the body, in degrees."""
        lon, lat, alt_m = self.geo
        swe.set_topo(lon, lat, alt_m)
        return swe.pheno_ut(jd, self.ipl, FLAGS | swe.FLG_TOPOCTR)[3] / 2.0

    def _sd(self, jd):
        """Semidiameter by interpolation on a half-hourly grid.

        The apparent size of the disc is the slowest-moving quantity in the
        whole calculation, and asking Swiss for it at all 721 altitude samples
        cost more than every other ephemeris call in the engine combined.
        Sampled every 30 minutes and interpolated linearly it is good to about
        0.06 arcsec for the Moon and a thousandth of that for the Sun, against
        a horizon whose two competing definitions differ by 153 arcsec.

        Outside the sampled span it falls through to the exact call: the
        refraction calibration reaches up to 24 days away from the window.
        """
        i = int((jd - self.jd0) / self._sd_step)
        if i < 0 or i + 1 >= self._sd_n:
            return self.semidiameter(jd)
        for k in (i, i + 1):
            if self._sd_grid[k] is None:
                self._sd_grid[k] = self.semidiameter(self.jd0 + k * self._sd_step)
        frac = (jd - self.jd0) / self._sd_step - i
        return self._sd_grid[i] + frac * (self._sd_grid[i + 1] - self._sd_grid[i])

    def _refraction(self):
        """The refraction component of Swiss's OWN rise/set threshold, here.

        Calibrated rather than assumed. swe_rise_trans places rise and set at a
        centre altitude of minus (refraction plus semidiameter); the
        semidiameter is knowable, but the refraction depends on the observer's
        altitude through an internal pressure model that the public refraction
        API does not reproduce. So ask Swiss for a rise or set it CAN solve
        near this day, measure the geometric centre altitude it chose, and
        subtract the semidiameter. What is left is the refraction Swiss is
        using at this site.

        This is what keeps the fallback solver definitionally identical to the
        primary one. Without it the two disagree by 10 to 30 seconds, and a
        rescued sunset would sit visibly out of line with the sunsets on the
        days either side of it.
        """
        if self._refr is not None:
            return self._refr
        mid = 0.5 * (self.jd0 + self.jd1) - 0.5
        offsets = [0.0] + [s * k for k in range(1, 25) for s in (-1.0, 1.0)]
        for offset in offsets:
            for flag in (swe.CALC_RISE, swe.CALC_SET):
                try:
                    res, tret = swe.rise_trans(mid + offset, self.ipl, flag,
                                               self.geo, 0.0, 0.0, FLAGS)
                except Exception:  # noqa: BLE001
                    continue
                if res != 0:
                    continue
                # Measured with the same semidiameter function the threshold
                # uses, so calibration and use cannot drift apart.
                self._refr = -self.altitude(tret[0]) - self._sd(tret[0])
                return self._refr
        # Deep polar day or night: no rise or set within 24 days to calibrate
        # against. The body is degrees clear of the horizon, so the sea-level
        # constant is far more precision than the classification needs.
        self._refr = DEFAULT_HORIZON_REFRACTION
        return self._refr

    def threshold(self, jd, thr):
        """Threshold altitude at `jd`. Fixed for twilight, live for rise/set."""
        if thr is not None:
            return thr
        return -(self._refraction() + self._sd(jd))

    def f(self, jd, thr):
        return self.altitude(jd) - self.threshold(jd, thr)

    def _grid_f(self, thr):
        """altitude-minus-threshold on the sample grid, computed once per thr."""
        if thr not in self._grid_cache:
            self._grid_cache[thr] = [a - self.threshold(j, thr)
                                     for j, a in zip(self.grid, self.alt)]
        return self._grid_cache[thr]

    def extrema(self, thr):
        """(min, max) of altitude-minus-threshold across the day."""
        vals = self._grid_f(thr)
        return min(vals), max(vals)

    def crossings(self, thr, direction):
        """Every threshold crossing in the window, in the requested direction.

        Returns a list of Julian Days, refined by bisection to under 0.05 s.
        """
        want_up = direction == RISE
        vals = self._grid_f(thr)
        found = []
        for i in range(1, len(self.grid)):
            prev_v, v = vals[i - 1], vals[i]
            crossed_up = prev_v < 0.0 <= v
            crossed_down = prev_v > 0.0 >= v
            if (crossed_up and want_up) or (crossed_down and not want_up):
                found.append(self._bisect(self.grid[i - 1], self.grid[i], thr))
        return found

    def _bisect(self, lo, hi, thr):
        f_lo = self.f(lo, thr)
        while (hi - lo) > 0.05 * _SEC:
            mid = 0.5 * (lo + hi)
            f_mid = self.f(mid, thr)
            if (f_mid < 0.0) == (f_lo < 0.0):
                lo, f_lo = mid, f_mid
            else:
                hi = mid
        return 0.5 * (lo + hi)


# ---------------------------------------------------------------------------
# Swiss solves
# ---------------------------------------------------------------------------

def _solve_one(jd_start, ipl, mode, rsmi_or_alt, direction, geo):
    """One Swiss rise/set/transit solve. Returns (jd|None, ret_code, err)."""
    try:
        if mode == "rsmi":
            res, tret = swe.rise_trans(jd_start, ipl, rsmi_or_alt, geo, 0.0, 0.0, FLAGS)
        else:
            rsmi = ((swe.CALC_RISE if direction == RISE else swe.CALC_SET)
                    | swe.BIT_DISC_CENTER | swe.BIT_NO_REFRACTION)
            res, tret = swe.rise_trans_true_hor(jd_start, ipl, rsmi, geo, 0.0, 0.0,
                                                float(rsmi_or_alt), FLAGS)
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller, never swallowed
        return None, None, str(exc)
    if res != 0:
        return None, res, None
    return tret[0], 0, None


def _reseed(target, ipl, mode, rsmi_or_alt, direction, geo, jd0, jd1):
    """Ask Swiss again for an event it stepped over, seeding further back.

    Returns Swiss's own instant for the crossing at `target`, or None if no
    backoff produces it. Swiss is the oracle, so where it CAN be made to answer
    its answer is preferred to the altitude track's; the track is only there to
    prove the event exists and to say roughly when.
    """
    for back in _RESEED_BACKOFF_S:
        jd, _ret, err = _solve_one(target - back * _SEC, ipl, mode,
                                   rsmi_or_alt, direction, geo)
        if err is not None or jd is None:
            continue
        if abs(jd - target) * 86400.0 <= _SAME_EVENT_S and jd0 <= jd < jd1:
            return jd
    return None


def _solve_window(spec, jd0, jd1, geo, track_for):
    """All occurrences of one event inside [jd0, jd1). Returns (jds, status).

    The old engine asked Swiss for "the next event after local midnight" and
    kept it only if it happened to land inside the day. That answered a
    different question than the one the day model asks, and it lost events
    three ways: a second occurrence inside a 25-hour fall-back day was never
    looked for, an event that fell outside the window vanished from the output
    entirely instead of being reported as absent, and Swiss's own return code
    -2 was reported as "circumpolar" even when the Sun plainly rose and set
    that day and it was only a twilight threshold that went unreached.

    This walks the whole window instead, RECONCILES what Swiss returned against
    the measured altitude of the body, and only then decides what to say about
    an empty result.

    The reconciliation is unconditional, and that is the point. swe_rise_trans
    steps over an event that sits a few seconds past its search start: at
    Reykjavik on 2026-06-30 it skipped a sunset 1.8 s ahead of the cursor and
    returned the day's OTHER sunset instead. Consulting the altitude track only
    when Swiss came back empty misses exactly that case, because Swiss did not
    come back empty - it came back one short, which looks identical to a normal
    day from the outside.
    """
    key, _label, body, direction, mode, rsmi_or_alt, thr = spec
    ipl = BODY_ID[body]

    jds = []
    # A hair early, so an event exactly at the boundary instant is not
    # stepped over.
    cursor = jd0 - _SEC
    err = None
    for _ in range(8):           # a 25-hour day holds at most two of anything
        jd, _ret, err = _solve_one(cursor, ipl, mode, rsmi_or_alt, direction, geo)
        if err is not None or jd is None:
            break
        if jd >= jd1:
            break
        if jd >= jd0:
            jds.append(jd)
        cursor = jd + _NUDGE
        if cursor >= jd1:
            break

    if err is not None:
        return [], "error: %s" % err

    if direction in (TRANSIT_UP, TRANSIT_DOWN):
        # A transit has no threshold, so there is nothing to measure against
        # and nothing for Swiss to graze past. It always exists; the only
        # honest empty answer is that none of them landed in this local day.
        return (jds, "ok") if jds else ([], "none_today")

    # Measure the sky, every time, and adopt any crossing Swiss did not report.
    track = track_for(body)
    for crossing in track.crossings(thr, direction):
        if any(abs(crossing - j) * 86400.0 <= _SAME_EVENT_S for j in jds):
            continue
        recovered = _reseed(crossing, ipl, mode, rsmi_or_alt, direction, geo,
                            jd0, jd1)
        jds.append(recovered if recovered is not None else crossing)
    jds.sort()

    if jds:
        return jds, "ok"

    lo, hi = track.extrema(thr)
    if lo > 0.0:
        return [], "always_above"
    if hi < 0.0:
        return [], "always_below"
    # The threshold is crossed inside the window, but not in this event's
    # direction: the matching crossing sits on the other side of midnight.
    return [], "none_today"


# ---------------------------------------------------------------------------
# The day
# ---------------------------------------------------------------------------

def day_events(lat, lon, alt_m, date_local, tzname):
    """Every solar and lunar event for one LOCAL calendar day at one location."""
    tz = ZoneInfo(tzname)
    geo = (lon, lat, alt_m)
    start_utc, end_utc = local_day_bounds(date_local, tzname)
    jd0, jd1 = jd_utc(start_utc), jd_utc(end_utc)

    tracks = {}

    def track_for(body):
        if body not in tracks:
            tracks[body] = _AltitudeTrack(body, geo, jd0, jd1)
        return tracks[body]

    events = []
    statuses = {}
    times = {}
    for spec in LADDER:
        key, label, body, _direction, _mode, _p, _thr = spec
        jds, status = _solve_window(spec, jd0, jd1, geo, track_for)
        statuses[key] = status
        times[key] = jds
        if not jds:
            events.append({"key": key, "label": label, "body": body,
                           "utc": None, "local": None, "status": status})
            continue
        for jd in jds:
            dt = jd_to_dt(jd)
            events.append({
                "key": key, "label": label, "body": body,
                "utc": dt.isoformat().replace("+00:00", "Z"),
                "local": dt.astimezone(tz).isoformat(),
                "status": status,
            })

    events.sort(key=lambda e: (e["utc"] is None,
                               e["utc"] or "",
                               LADDER_INDEX[e["key"]]))

    return {
        "date": date_local.isoformat(),
        "tz": tzname,
        "observer": {"lat": lat, "lon": lon, "alt_m": alt_m},
        "engine": "Swiss Ephemeris %s (JPL DE441), swe_rise_trans, topocentric"
                  % swe.version,
        "day_length_s": _day_length(times, statuses, geo, jd0, jd1),
        "moon": _moon_block(geo, jd0, jd1),
        "events": events,
    }


def _day_length(times, statuses, geo, jd0, jd1):
    """Seconds from the day's sunrise to the sunset that follows it.

    The pair is not required to sit inside the same local day: at Tromso in
    mid-May the Sun rises at 01:29 and does not set until 00:06 the next
    morning, and 22h37m is the honest answer for how long that day was.

    Polar day returns the full length of the local day, polar night returns 0.
    Both are measured facts, not placeholders.
    """
    window_s = round((jd1 - jd0) * 86400.0)
    if statuses.get("sunrise") == "always_above":
        return window_s
    if statuses.get("sunrise") == "always_below":
        return 0

    rises, sets = times.get("sunrise") or [], times.get("sunset") or []
    if rises:
        sr = rises[0]
        ss, _ret, _err = _solve_one(sr + _NUDGE, swe.SUN, "rsmi", swe.CALC_SET,
                                    SET, geo)
        if ss is not None:
            return round((ss - sr) * 86400.0)
        return None
    if sets:
        ss = sets[0]
        # Walk forward from 36 hours back and keep the last sunrise before it.
        cursor, best = ss - 1.5, None
        for _ in range(4):
            sr, _ret, _err = _solve_one(cursor, swe.SUN, "rsmi", swe.CALC_RISE,
                                        RISE, geo)
            if sr is None or sr >= ss:
                break
            best, cursor = sr, sr + _NUDGE
        if best is not None:
            return round((ss - best) * 86400.0)
    return None


def _moon_block(geo, jd0, jd1):
    """Moon illumination, phase angle and apparent size, TOPOCENTRIC.

    Sampled at the midpoint of the local day, which is a stable daily instant
    that survives DST shifts. Topocentric because the contract carries an
    observer: the Moon overhead is about 1.7 percent wider than the Moon on the
    geocentric books, and `apparent_diameter_arcsec` should mean what the
    observer would measure.
    """
    lon, lat, alt_m = geo
    swe.set_topo(lon, lat, alt_m)
    mid = 0.5 * (jd0 + jd1)
    attr = swe.pheno_ut(mid, swe.MOON, FLAGS | swe.FLG_TOPOCTR)
    return {
        "illumination_pct": round(attr[1] * 100, 2),
        "phase_angle_deg": round(attr[0], 3),
        "apparent_diameter_arcsec": round(attr[3] * 3600, 2),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

# Plain language for the CLI table. The JSON keeps the uniform vocabulary.
_HUMAN = {
    ("sun", "sunrise", "always_above"): "polar day - the Sun never sets",
    ("sun", "sunset", "always_above"): "polar day - the Sun never sets",
    ("sun", "sunrise", "always_below"): "polar night - the Sun never rises",
    ("sun", "sunset", "always_below"): "polar night - the Sun never rises",
    ("moon", "moonrise", "always_above"): "circumpolar - the Moon never sets",
    ("moon", "moonset", "always_above"): "circumpolar - the Moon never sets",
    ("moon", "moonrise", "always_below"): "the Moon never rises today",
    ("moon", "moonset", "always_below"): "the Moon never rises today",
}


def _explain(event):
    key, body, status = event["key"], event["body"], event["status"]
    hit = _HUMAN.get((body, key, status))
    if hit:
        return hit
    who = "the Sun" if body == "sun" else "the Moon"
    if status == "always_above":
        return "never reached - %s stays above this altitude all day" % who
    if status == "always_below":
        return "never reached - %s stays below this altitude all day" % who
    if status == "none_today":
        return "does not fall inside this local day"
    return status


def main():
    ap = argparse.ArgumentParser(description="SUNMAP - daily solar and lunar cycle to the second.")
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True, help="east positive")
    ap.add_argument("--alt", type=float, default=0.0, help="metres above sea level")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (local); defaults to today in --tz")
    ap.add_argument("--tz", default="America/Los_Angeles")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    args = ap.parse_args()

    tz = ZoneInfo(args.tz)
    d = (datetime.strptime(args.date, "%Y-%m-%d").date() if args.date
         else datetime.now(tz).date())

    data = day_events(args.lat, args.lon, args.alt, d, args.tz)

    if args.json:
        print(json.dumps(data, indent=2))
        return

    print(f"SUNMAP  {data['date']}  {args.lat:.4f}, {args.lon:.4f}  {args.tz}")
    print(f"engine: {data['engine']}")
    print()
    for e in data["events"]:
        if e["local"]:
            # Round to the nearest second for display; the JSON keeps the
            # millisecond-resolution instant.
            exact = datetime.fromisoformat(e["local"])
            t = (exact + timedelta(milliseconds=500)).replace(microsecond=0).strftime("%H:%M:%S")
            mark = "sun " if e["body"] == "sun" else "moon"
            print(f"  {mark}  {e['label']:22s} {t}")
        else:
            print(f"        {e['label']:22s} -  {_explain(e)}")
    if data["day_length_s"] is not None:
        h, rem = divmod(data["day_length_s"], 3600)
        m, s = divmod(rem, 60)
        print(f"\n  Day length: {h}h {m}m {s}s")
    else:
        print("\n  Day length: undetermined")
    print(f"  Moon: {data['moon']['illumination_pct']}% illuminated, "
          f"{data['moon']['apparent_diameter_arcsec']}\" across")


if __name__ == "__main__":
    main()
