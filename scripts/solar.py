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
why. An event that occurs twice inside a 25-hour fall-back day appears twice.
Nothing is ever silently dropped, and no time is ever invented.


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
from datetime import date as _date, datetime, time as _time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import swisseph as swe

EPHE = str((Path(__file__).resolve().parents[1] / "data" / "ephe"))
swe.set_ephe_path(EPHE)

FLAGS = swe.FLG_SWIEPH

# Geometric altitude of the body's CENTRE at the moment of each event, in
# degrees. Used to classify a non-event honestly (always above vs always below)
# and as the root function for the independent fallback solver.
#   Sunrise/sunset: upper limb touching the horizon through standard refraction
#   is a centre altitude of -50 arcmin.
#   Twilights: the Swiss twilight bits are defined on the centre, unrefracted.
#   Golden hour: an explicit centre altitude band, -4 deg to +6 deg.
ALT_SUNRISE = -50.0 / 60.0        # -0.833333 deg
ALT_CIVIL = -6.0
ALT_NAUTICAL = -12.0
ALT_ASTRO = -18.0
GOLDEN_LOW = -4.0
GOLDEN_HIGH = 6.0

REFRACTION_AT_HORIZON = 34.0 / 60.0   # 0.566667 deg, for the Moon's threshold

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
    ("sunrise",              "Sunrise",            "sun",  RISE,          "rsmi", swe.CALC_RISE,                           ALT_SUNRISE),
    ("golden_hour_end_am",   "Golden hour ends",   "sun",  RISE,          "alt",  GOLDEN_HIGH,                             GOLDEN_HIGH),
    ("solar_noon",           "Solar noon",         "sun",  TRANSIT_UP,    "rsmi", swe.CALC_MTRANSIT,                       None),
    ("golden_hour_start_pm", "Golden hour begins", "sun",  SET,           "alt",  GOLDEN_HIGH,                             GOLDEN_HIGH),
    ("sunset",               "Sunset",             "sun",  SET,           "rsmi", swe.CALC_SET,                            ALT_SUNRISE),
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

    STEP_MIN = 2.0   # sampling step in minutes

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

    def altitude(self, jd):
        """Geometric (unrefracted) topocentric altitude of the body's centre."""
        lon, lat, alt_m = self.geo
        swe.set_topo(lon, lat, alt_m)
        xx, _ = swe.calc_ut(jd, self.ipl,
                            FLAGS | swe.FLG_EQUATORIAL | swe.FLG_TOPOCTR)
        xaz = swe.azalt(jd, swe.EQU2HOR, self.geo, 0.0, 0.0, (xx[0], xx[1], xx[2]))
        return xaz[1]

    def threshold(self, jd, thr):
        """Threshold altitude at `jd`. Constant for the Sun, live for the Moon.

        The Moon's rise/set threshold moves with its topocentric semidiameter
        (its distance varies by 10 percent over a month), so it is recomputed
        per sample instead of frozen at a mean value.
        """
        if thr is not None:
            return thr
        lon, lat, alt_m = self.geo
        swe.set_topo(lon, lat, alt_m)
        attr = swe.pheno_ut(jd, self.ipl, FLAGS | swe.FLG_TOPOCTR)
        semidiameter = attr[3] / 2.0
        return -(REFRACTION_AT_HORIZON + semidiameter)

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

    This walks the whole window instead, then decides an empty result by
    measuring the sky rather than by trusting a return code.
    """
    key, _label, body, direction, mode, rsmi_or_alt, thr = spec
    ipl = BODY_ID[body]

    jds = []
    cursor = jd0 - _SEC          # a hair early, so an event exactly at the
    swiss_ret = None             # boundary instant is not stepped over
    err = None
    for _ in range(8):           # a 25-hour day holds at most two of anything
        jd, ret, err = _solve_one(cursor, ipl, mode, rsmi_or_alt, direction, geo)
        swiss_ret = ret
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
    if jds:
        return jds, "ok"

    # Nothing from Swiss. Measure the day before saying anything about it.
    if direction in (TRANSIT_UP, TRANSIT_DOWN):
        # A transit always exists; the only honest empty answer is that none
        # of them landed in this local day.
        return [], "none_today"

    track = track_for(body)
    fallback = track.crossings(thr, direction)
    if fallback:
        # Swiss found nothing but the sky says otherwise. Trust the measurement.
        return fallback, "ok"

    lo, hi = track.extrema(thr)
    if lo > 0.0:
        return [], "always_above"
    if hi < 0.0:
        return [], "always_below"
    # The threshold is crossed inside the window, but not in this event's
    # direction: the matching crossing sits on the other side of midnight.
    del swiss_ret
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
        ss, ret, err = _solve_one(sr + _NUDGE, swe.SUN, "rsmi", swe.CALC_SET, SET, geo)
        if ss is not None:
            return round((ss - sr) * 86400.0)
        del ret, err
        return None
    if sets:
        ss = sets[0]
        # Walk forward from 36 hours back and keep the last sunrise before it.
        cursor, best = ss - 1.5, None
        for _ in range(4):
            sr, ret, err = _solve_one(cursor, swe.SUN, "rsmi", swe.CALC_RISE, RISE, geo)
            del ret, err
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
    if status == "always_above":
        return "never reached - the Sun stays above this altitude all day"
    if status == "always_below":
        return "never reached - the Sun stays below this altitude all day"
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
