#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 PUDDY Inc. <legal@puddystudios.com>
"""SUNMAP cross-check - an independent second opinion on scripts/solar.py.

WHY THIS EXISTS
---------------
solar.py is Swiss Ephemeris on JPL DE441. It is the accurate engine and it is
the oracle for SUNMAP's numbers. What it cannot do is check itself: a wrong
timezone window, an inverted rise/set sign, an event attributed to the wrong
day, or a units slip would all come out of Swiss looking perfectly precise.
So this file computes the same Sun events a completely different way, from
scratch, and prints the difference in seconds.

WHAT IS INDEPENDENT HERE
------------------------
Everything. This module imports `math` and the standard library and nothing
else. It does not import swisseph, ephem, skyfield, astropy, or any other
astronomy package. It contains:

  1. The NOAA Solar Calculator algorithm, written out longhand: geometric mean
     longitude, mean anomaly, equation of centre, apparent longitude, obliquity
     with its nutation correction, declination, and the equation of time. Rise,
     set and twilight follow from the hour-angle equation; solar noon and solar
     midnight follow from the equation of time alone.

  2. A low-precision lunar theory (the abbreviated Meeus series, four terms of
     longitude and latitude plus a parallax series) with topocentric parallax
     applied, solved for the horizon crossing by bisection.

The only thing this file takes from solar.py is the ANSWER it is checking, plus
the location and date list. The day-window logic is re-derived here from the
IANA timezone alone, so a window bug in the engine cannot hide inside a shared
helper.

ONE CHECK IS DELIBERATELY NOT INDEPENDENT, and it is labelled as such:
`occurrence_reconciliation` counts the engine's emitted occurrences against
sign changes on the body's altitude curve. That reuses Swiss, so it proves
nothing about the ephemeris. It exists because the NOAA comparison is
STRUCTURALLY BLIND to one real failure: swe_rise_trans steps over events near
polar boundaries, and where the reference model's horizon is 2.55 arcmin
shallower it has no crossing there either, so the drop reads as agreement. A
sunset really was lost that way at Reykjavik on 2026-06-30 while every NOAA row
for the day passed.

WHAT THIS CAN AND CANNOT PROVE
------------------------------
NOAA is a truncated model. It carries no lunar perturbation of the Earth, a
fixed refraction of 34 arcmin, no observer altitude, and a Sun position good to
roughly 0.01 degrees. Swiss Ephemeris is better on every one of those counts.
So a delta of a few seconds means the two agree; it does NOT mean NOAA is right
and Swiss is wrong. This harness catches the failures that matter and that
precision cannot catch: sign inversions, day-attribution errors, timezone and
DST slips, missing events, and invented events.

Where the Sun grazes a threshold the crossing is nearly tangential, and a
0.01-degree model error turns into minutes of time error. That is a property of
the geometry, not a defect in either engine, and the tolerance table below
widens with latitude for exactly that reason.

THE MOON IS NOT CHECKED BY NOAA. NOAA models the Sun only; it has no lunar
theory of any kind and cannot say anything about moonrise. The Moon is checked
by the separate low-precision lunar theory in this file, at a much coarser
tolerance (15 minutes), which is the honest accuracy of a four-term lunar
series. That check will catch an inverted moonrise, a wrong day, or a moon
event off by an hour. It will not adjudicate the last minute, and it is not
asked to.

Usage:
  python3 verify_solar.py                 # the canonical seven sites, 4 dates each
  python3 verify_solar.py --sweep 60      # 60 consecutive days per site
  python3 verify_solar.py --site Tromso --date 2026-08-09 --verbose
"""
import argparse
import math
import sys
from datetime import date as _date, datetime, time as _time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import solar  # noqa: E402 - the engine under test, imported only for its output

RAD = math.pi / 180.0
DEG = 180.0 / math.pi


# ===========================================================================
# PART 1 - NOAA solar position, written from scratch
# ===========================================================================

def julian_day(y, m, d, hour_frac):
    """Gregorian calendar date + fractional hour UTC -> Julian Day."""
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return (math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1))
            + d + b - 1524.5 + hour_frac / 24.0)


def jd_from_datetime(dt):
    dt = dt.astimezone(timezone.utc)
    frac = dt.hour + dt.minute / 60.0 + (dt.second + dt.microsecond / 1e6) / 3600.0
    return julian_day(dt.year, dt.month, dt.day, frac)


def datetime_from_jd(jd):
    """Julian Day -> aware UTC datetime, to the millisecond."""
    jd += 0.5
    z = math.floor(jd)
    f = jd - z
    if z < 2299161:
        a = z
    else:
        alpha = math.floor((z - 1867216.25) / 36524.25)
        a = z + 1 + alpha - math.floor(alpha / 4)
    b = a + 1524
    c = math.floor((b - 122.1) / 365.25)
    d = math.floor(365.25 * c)
    e = math.floor((b - d) / 30.6001)
    day = b - d - math.floor(30.6001 * e)
    month = e - 1 if e < 14 else e - 13
    year = c - 4716 if month > 2 else c - 4715
    ms = round(f * 86400.0 * 1000.0)
    return (datetime(int(year), int(month), int(day), tzinfo=timezone.utc)
            + timedelta(milliseconds=ms))


def julian_century(jd):
    return (jd - 2451545.0) / 36525.0


def geom_mean_long_sun(t):
    return (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360.0


def geom_mean_anom_sun(t):
    return 357.52911 + t * (35999.05029 - 0.0001537 * t)


def eccent_earth_orbit(t):
    return 0.016708634 - t * (0.000042037 + 0.0000001267 * t)


def sun_eq_of_centre(t):
    m = geom_mean_anom_sun(t) * RAD
    return (math.sin(m) * (1.914602 - t * (0.004817 + 0.000014 * t))
            + math.sin(2 * m) * (0.019993 - 0.000101 * t)
            + math.sin(3 * m) * 0.000289)


def sun_apparent_long(t):
    true_long = geom_mean_long_sun(t) + sun_eq_of_centre(t)
    return true_long - 0.00569 - 0.00478 * math.sin((125.04 - 1934.136 * t) * RAD)


def mean_obliquity(t):
    seconds = 21.448 - t * (46.8150 + t * (0.00059 - t * 0.001813))
    return 23.0 + (26.0 + seconds / 60.0) / 60.0


def obliquity_corrected(t):
    return mean_obliquity(t) + 0.00256 * math.cos((125.04 - 1934.136 * t) * RAD)


def sun_declination(t):
    """Solar declination in degrees."""
    e = obliquity_corrected(t) * RAD
    lam = sun_apparent_long(t) * RAD
    return math.asin(math.sin(e) * math.sin(lam)) * DEG


def equation_of_time(t):
    """Apparent solar time minus mean solar time, in minutes."""
    eps = obliquity_corrected(t) * RAD
    l0 = geom_mean_long_sun(t) * RAD
    e = eccent_earth_orbit(t)
    m = geom_mean_anom_sun(t) * RAD
    y = math.tan(eps / 2.0) ** 2
    etime = (y * math.sin(2 * l0)
             - 2.0 * e * math.sin(m)
             + 4.0 * e * y * math.sin(m) * math.cos(2 * l0)
             - 0.5 * y * y * math.sin(4 * l0)
             - 1.25 * e * e * math.sin(2 * m))
    return etime * 4.0 * DEG


def hour_angle(lat_deg, dec_deg, zenith_deg):
    """Hour angle in DEGREES at which the Sun's centre reaches `zenith_deg`.

    Returns a POSITIVE value, or None when the Sun never reaches that zenith
    from this latitude on this day.

    Sign convention, stated explicitly because it is the classic place to go
    wrong: the returned angle is the angular distance of the event from local
    apparent noon. The MORNING event is at noon MINUS the hour angle, the
    EVENING event is at noon PLUS it. An implementation that swaps those two
    produces an output that looks entirely plausible and is reflected about
    midday.
    """
    lat, dec, z = lat_deg * RAD, dec_deg * RAD, zenith_deg * RAD
    denom = math.cos(lat) * math.cos(dec)
    if abs(denom) < 1e-12:
        return None
    cos_ha = (math.cos(z) / denom) - math.tan(lat) * math.tan(dec)
    if cos_ha > 1.0 or cos_ha < -1.0:
        return None
    return math.acos(cos_ha) * DEG


def solar_noon_jd(jd_guess, lon_east):
    """Julian Day of local apparent noon nearest `jd_guess`. Iterated to converge."""
    jd_midnight = math.floor(jd_guess - 0.5) + 0.5
    jd = jd_guess
    for _ in range(4):
        eq = equation_of_time(julian_century(jd))
        minutes = 720.0 - 4.0 * lon_east - eq
        jd = jd_midnight + minutes / 1440.0
    return jd


def noaa_event_jd(jd_midnight_utc, lat, lon_east, zenith, morning, seed=0.5):
    """Julian Day of one Sun threshold crossing on the UTC day starting at
    `jd_midnight_utc`. Returns None when the Sun never reaches `zenith`.

    Iterated: the declination and the equation of time are re-evaluated at the
    running estimate of the event time, not at midday, so the answer converges
    on itself rather than on an arbitrary reference instant.

    `seed` is the starting fraction of the UTC day. It matters near a polar
    threshold: a deep twilight event there happens within minutes of solar
    MIDNIGHT, and the declination twelve hours away at midday can be on the
    wrong side of the tangency, which makes the very first hour-angle
    evaluation report "no such event" and abandon a crossing that is really
    there. The caller tries several seeds and keeps whatever converges.
    """
    jd = jd_midnight_utc + seed
    minutes = None
    for _ in range(6):
        t = julian_century(jd)
        dec = sun_declination(t)
        eq = equation_of_time(t)
        ha = hour_angle(lat, dec, zenith)
        if ha is None:
            return None
        noon = 720.0 - 4.0 * lon_east - eq
        minutes = noon - 4.0 * ha if morning else noon + 4.0 * ha
        jd = jd_midnight_utc + minutes / 1440.0
    return jd_midnight_utc + minutes / 1440.0


def noaa_sun_altitude(jd, lat, lon_east):
    """Geometric altitude of the Sun's centre in degrees, NOAA model.

    Used for two things the closed form cannot do: finding a crossing that the
    hour-angle fixed point fails to converge on at a tangency, and measuring
    how far the Sun actually gets past a threshold so a disagreement about
    whether an event happened at all can be judged instead of just counted.
    """
    t = julian_century(jd)
    dec = sun_declination(t)
    eq = equation_of_time(t)
    jd_midnight = math.floor(jd - 0.5) + 0.5
    minutes = (jd - jd_midnight) * 1440.0
    true_solar_minutes = (minutes + eq + 4.0 * lon_east) % 1440.0
    ha = (true_solar_minutes / 4.0 - 180.0) * RAD
    lat_r, dec_r = lat * RAD, dec * RAD
    sin_alt = (math.sin(lat_r) * math.sin(dec_r)
               + math.cos(lat_r) * math.cos(dec_r) * math.cos(ha))
    return math.asin(max(-1.0, min(1.0, sin_alt))) * DEG


def bisect_crossing(fn, lo, hi):
    f_lo = fn(lo)
    while (hi - lo) > 0.05 / 86400.0:
        mid = 0.5 * (lo + hi)
        if (fn(mid) < 0.0) == (f_lo < 0.0):
            lo, f_lo = mid, fn(mid)
        else:
            hi = mid
    return 0.5 * (lo + hi)


def noaa_altitude_crossings(lat, lon, jd0, jd1, threshold, rising):
    """Every crossing of `threshold` by the NOAA Sun inside the window."""
    step = 2.0 / 1440.0
    n = max(1, int(math.ceil((jd1 - jd0) / step)))
    grid = [jd0 + i * step for i in range(n)] + [jd1]
    alt = [noaa_sun_altitude(j, lat, lon) for j in grid]
    vals = [a - threshold for a in alt]
    hits = []
    for i in range(1, len(grid)):
        up = vals[i - 1] < 0.0 <= vals[i]
        down = vals[i - 1] > 0.0 >= vals[i]
        if (up and rising) or (down and not rising):
            hits.append(bisect_crossing(
                lambda j: noaa_sun_altitude(j, lat, lon) - threshold,
                grid[i - 1], grid[i]))
    return hits


# The event ladder in NOAA terms. zenith = 90 + depression of the Sun's centre.
#   sunrise/sunset 90.833 is the classical 34 arcmin refraction plus a 16 arcmin
#   semidiameter. Note that Swiss does NOT use 34 arcmin: measured against its
#   own output it applies 36.739 arcmin, so the two definitions of "sunset"
#   differ by 2.5 arcmin of altitude. That is invisible on a normal day and
#   decisive on a day when the Sun grazes the horizon, which is what the
#   tangency test below exists to handle.
NOAA_SUN = {
    "astronomical_dawn":    (108.0, True),
    "nautical_dawn":        (102.0, True),
    "civil_dawn":           (96.0, True),
    "golden_hour_start_am": (94.0, True),
    "sunrise":              (90.833, True),
    "golden_hour_end_am":   (84.0, True),
    "golden_hour_start_pm": (84.0, False),
    "sunset":               (90.833, False),
    "golden_hour_end_pm":   (94.0, False),
    "civil_dusk":           (96.0, False),
    "nautical_dusk":        (102.0, False),
    "astronomical_dusk":    (108.0, False),
}


# ===========================================================================
# PART 2 - low-precision lunar theory, also from scratch
# ===========================================================================

def moon_ecliptic(t):
    """Geocentric ecliptic longitude, latitude (deg) and horizontal parallax (deg).

    The abbreviated Meeus series. Longitude is good to roughly 0.2 degrees and
    latitude to roughly 0.1 degrees, which is three orders of magnitude coarser
    than the ELP truncation Swiss Ephemeris carries. That is deliberate: this
    exists to catch a moonrise that is inverted, mis-dated or an hour out, not
    to argue about seconds.
    """
    d = 297.8501921 + 445267.1114034 * t - 0.0018819 * t * t
    m = 357.5291092 + 35999.0502909 * t - 0.0001536 * t * t
    mp = 134.9633964 + 477198.8675055 * t + 0.0087414 * t * t
    f = 93.2720950 + 483202.0175233 * t - 0.0036539 * t * t
    lp = 218.3164477 + 481267.88123421 * t - 0.0015786 * t * t

    d, m, mp, f = d * RAD, m * RAD, mp * RAD, f * RAD

    lon = (lp
           + 6.288774 * math.sin(mp)
           + 1.274027 * math.sin(2 * d - mp)
           + 0.658314 * math.sin(2 * d)
           + 0.213618 * math.sin(2 * mp)
           - 0.185116 * math.sin(m)
           - 0.114332 * math.sin(2 * f)
           + 0.058793 * math.sin(2 * d - 2 * mp)
           + 0.057066 * math.sin(2 * d - m - mp)
           + 0.053322 * math.sin(2 * d + mp)
           + 0.045758 * math.sin(2 * d - m))

    lat = (5.128122 * math.sin(f)
           + 0.280602 * math.sin(mp + f)
           + 0.277693 * math.sin(mp - f)
           + 0.173237 * math.sin(2 * d - f)
           + 0.055413 * math.sin(2 * d - mp + f)
           + 0.046271 * math.sin(2 * d - mp - f))

    parallax = (0.950725
                + 0.051818 * math.cos(mp)
                + 0.009531 * math.cos(2 * d - mp)
                + 0.007843 * math.cos(2 * d)
                + 0.002824 * math.cos(2 * mp))

    return lon % 360.0, lat, parallax


def ecliptic_to_equatorial(lon_deg, lat_deg, eps_deg):
    lon, lat, eps = lon_deg * RAD, lat_deg * RAD, eps_deg * RAD
    ra = math.atan2(math.sin(lon) * math.cos(eps) - math.tan(lat) * math.sin(eps),
                    math.cos(lon))
    dec = math.asin(math.sin(lat) * math.cos(eps)
                    + math.cos(lat) * math.sin(eps) * math.sin(lon))
    return (ra * DEG) % 360.0, dec * DEG


def gmst_deg(jd):
    """Greenwich mean sidereal time in degrees."""
    t = julian_century(jd)
    theta = (280.46061837 + 360.98564736629 * (jd - 2451545.0)
             + 0.000387933 * t * t - t * t * t / 38710000.0)
    return theta % 360.0


def moon_topocentric_altitude(jd, lat, lon_east):
    """(geometric topocentric altitude, threshold altitude) of the Moon, degrees.

    Parallax is applied in the plane of the observer's meridian, which is the
    standard first-order correction and is adequate at this precision. The
    threshold is the centre altitude at which the upper limb touches the
    refracted horizon: minus 34 arcmin of refraction, minus the semidiameter.
    """
    t = julian_century(jd)
    lon_ecl, lat_ecl, parallax = moon_ecliptic(t)
    ra, dec = ecliptic_to_equatorial(lon_ecl, lat_ecl, obliquity_corrected(t))

    ha = (gmst_deg(jd) + lon_east - ra) % 360.0
    ha_r, dec_r, lat_r = ha * RAD, dec * RAD, lat * RAD

    sin_alt = (math.sin(lat_r) * math.sin(dec_r)
               + math.cos(lat_r) * math.cos(dec_r) * math.cos(ha_r))
    alt_geocentric = math.asin(max(-1.0, min(1.0, sin_alt))) * DEG

    # Diurnal parallax lowers the Moon by up to one degree near the horizon.
    alt = alt_geocentric - parallax * math.cos(alt_geocentric * RAD)

    semidiameter = 0.2725 * parallax
    threshold = -(34.0 / 60.0 + semidiameter)
    return alt, threshold


def moon_transit_offset(jd, _lat, lon_east):
    """Signed hour angle of the Moon in degrees, wrapped to (-180, 180].

    Zero at upper transit, 180 at lower transit. Used to bisect for lunar noon
    and lunar midnight.
    """
    t = julian_century(jd)
    lon_ecl, lat_ecl, _ = moon_ecliptic(t)
    ra, _dec = ecliptic_to_equatorial(lon_ecl, lat_ecl, obliquity_corrected(t))
    ha = (gmst_deg(jd) + lon_east - ra) % 360.0
    return ha - 360.0 if ha > 180.0 else ha


def sun_ecliptic_longitude(t):
    return sun_apparent_long(t) % 360.0


def moon_illumination_pct(jd):
    """Illuminated fraction of the lunar disc, per cent, from the elongation."""
    t = julian_century(jd)
    lon_m, lat_m, _ = moon_ecliptic(t)
    lon_s = sun_ecliptic_longitude(t)
    # Angular separation on the celestial sphere, Sun taken as latitude zero.
    lm, bm, ls = lon_m * RAD, lat_m * RAD, lon_s * RAD
    cos_elong = math.cos(bm) * math.cos(lm - ls)
    elong = math.acos(max(-1.0, min(1.0, cos_elong)))
    # Phase angle: the Sun is 389 lunar distances away, so the Earth-Moon-Sun
    # angle is the supplement of the elongation to within a quarter of a degree.
    phase = math.pi - elong
    return (1.0 + math.cos(phase)) / 2.0 * 100.0


# ===========================================================================
# PART 3 - the day window, re-derived independently
# ===========================================================================

def local_day_bounds(day, tzname):
    """First instant of the local date, and of the next one.

    Deliberately NOT imported from solar.py. A window bug is one of the failure
    modes this harness exists to catch, and it cannot catch it with the same
    code on both sides. This walks minute by minute from a point that is
    certainly the previous local day, which is slow and obviously correct.
    """
    tz = ZoneInfo(tzname)
    cursor = datetime.combine(day, _time(0), tzinfo=timezone.utc) - timedelta(days=2)
    start = end = None
    while cursor < datetime.combine(day, _time(0), tzinfo=timezone.utc) + timedelta(days=4):
        local_date = cursor.astimezone(tz).date()
        if start is None and local_date == day:
            start = cursor
        if start is not None and local_date > day:
            end = cursor
            break
        cursor += timedelta(minutes=1)
    return start, end


# ===========================================================================
# PART 4 - the comparison
# ===========================================================================

SITES = {
    "LA":        (34.0522, -118.2437, "America/Los_Angeles"),
    "Tromso":    (69.6496, 18.9560, "Europe/Oslo"),
    "Svalbard":  (78.2232, 15.6469, "Arctic/Longyearbyen"),
    "Quito":     (-0.1807, -78.4678, "America/Guayaquil"),
    "Sydney":    (-33.8688, 151.2093, "Australia/Sydney"),
    "Reykjavik": (64.1466, -21.9426, "Atlantic/Reykjavik"),
    "Singapore": (1.3521, 103.8198, "Asia/Singapore"),
}

DEFAULT_DATES = ["2026-03-20", "2026-06-21", "2026-08-09", "2026-12-21"]


def sun_tolerance_s(lat):
    """Stated tolerance for a Sun event, in seconds, by latitude.

    NOAA's Sun is good to about 0.01 degrees. Near the horizon the Sun descends
    at 15 degrees per hour times the cosine of the latitude, so the same angular
    error buys more time error the further north or south you stand, and near a
    polar boundary the crossing goes tangential and the error is unbounded.
    These numbers are the model's honest resolution, not a passing grade chosen
    after the fact.
    """
    a = abs(lat)
    if a <= 55.0:
        return 60.0
    if a <= 66.0:
        return 240.0
    return 900.0


TRANSIT_TOLERANCE_S = 30.0     # solar noon and midnight, latitude independent
MOON_TOLERANCE_S = 900.0       # low-precision lunar theory, 15 minutes
MOON_LAT_LIMIT = 60.0          # above this the lunar series is not asked to judge
ILLUM_TOLERANCE_PP = 1.0       # percentage points

# How close the Sun has to come to a threshold before the two models can no
# longer be trusted to agree about whether it crossed at all.
#
# Rise and set: Swiss puts the horizon at 36.739 arcmin of refraction and NOAA
# at 34, a 2.55 arcmin gap in altitude, plus about 0.6 arcmin of NOAA position
# error. On a day when the Sun bottoms out inside that band, one model has a
# sunset and the other has polar day, and both are right about their own
# definition. Swiss is the oracle, so the engine wins and the row is recorded
# as not adjudicable rather than as a failure.
#
# Twilight and golden hour: both models use the identical centre altitude, so
# only NOAA's position error is in play and the band is much narrower.
TANGENCY_RISE_SET_DEG = 0.06
TANGENCY_THRESHOLD_DEG = 0.03
TANGENCY_MOON_DEG = 0.35       # the lunar series' own position error

NOAA_THRESHOLD_ALT = {k: 90.0 - z for k, (z, _m) in NOAA_SUN.items()}


def noaa_events_for_day(lat, lon, day, tzname):
    """Every Sun event this harness believes falls in the local day.

    Candidates are generated from three consecutive UTC days and then filtered
    by the independently derived local-day window, which is the same question
    the engine answers and the place the engine used to get it wrong.
    """
    start, end = local_day_bounds(day, tzname)
    jd_start, jd_end = jd_from_datetime(start), jd_from_datetime(end)
    base = math.floor(jd_from_datetime(start) - 0.5) + 0.5

    # Two occurrences of one key inside a single local day are always about 24
    # hours apart, so anything closer than a few hours is the same root reached
    # from a different seed.
    same_root = 0.1

    out = {}
    for key, (zenith, morning) in NOAA_SUN.items():
        hits = []
        for offset in (-1, 0, 1):
            for seed in (0.5, 0.0, 1.0):
                jd = noaa_event_jd(base + offset, lat, lon, zenith, morning, seed)
                if jd is None:
                    continue
                if jd_start <= jd < jd_end and all(abs(jd - h) > same_root for h in hits):
                    hits.append(jd)
        # The closed form is the canonical NOAA calculator and it is what pins
        # the sign convention, but its fixed-point iteration can fail to
        # converge where the crossing is tangential. Sweep the altitude curve
        # too and adopt anything it missed, so a real event is never scored as
        # the engine inventing one.
        swept = noaa_altitude_crossings(lat, lon, jd_start, jd_end,
                                        90.0 - zenith, morning)
        for jd in swept:
            if all(abs(jd - h) > same_root for h in hits):
                hits.append(jd)
        out[key] = sorted(hits)

    for key, half_turn in (("solar_noon", 0.0), ("solar_midnight", 0.5)):
        hits = []
        for offset in (-1, 0, 1):
            jd = solar_noon_jd(base + offset + 0.5, lon) + half_turn
            if jd_start <= jd < jd_end and all(abs(jd - h) > same_root for h in hits):
                hits.append(jd)
        out[key] = sorted(hits)

    return out, jd_start, jd_end


def noaa_moon_events_for_day(lat, lon, jd_start, jd_end):
    """Moonrise, moonset and the two lunar transits, from the lunar series."""
    step = 4.0 / 1440.0
    # The grid must END exactly on the window edge. An overshoot of even one
    # step lets a crossing that belongs to tomorrow be counted today, which
    # would have this harness accusing the engine of losing an event it
    # correctly placed on the next day.
    n = max(1, int(math.ceil((jd_end - jd_start) / step)))
    grid = [jd_start + i * step for i in range(n)] + [jd_end]

    def f_horizon(jd):
        alt, thr = moon_topocentric_altitude(jd, lat, lon)
        return alt - thr

    def bisect(fn, lo, hi):
        f_lo = fn(lo)
        while (hi - lo) > 0.05 / 86400.0:
            mid = 0.5 * (lo + hi)
            if (fn(mid) < 0.0) == (f_lo < 0.0):
                lo, f_lo = mid, fn(mid)
            else:
                hi = mid
        return 0.5 * (lo + hi)

    rises, sets = [], []
    vals = [f_horizon(j) for j in grid]
    for i in range(1, len(grid)):
        if vals[i - 1] < 0.0 <= vals[i]:
            rises.append(bisect(f_horizon, grid[i - 1], grid[i]))
        elif vals[i - 1] > 0.0 >= vals[i]:
            sets.append(bisect(f_horizon, grid[i - 1], grid[i]))

    # Transits: the hour angle sweeps through 0 (upper) and wraps at 180 (lower).
    ups, downs = [], []
    ha = [moon_transit_offset(j, lat, lon) for j in grid]
    for i in range(1, len(grid)):
        a, b = ha[i - 1], ha[i]
        if a < 0.0 <= b and abs(b - a) < 180.0:
            ups.append(bisect(lambda j: moon_transit_offset(j, lat, lon),
                              grid[i - 1], grid[i]))
        elif a > 0.0 > b:  # wrapped through +180 / -180
            downs.append(bisect(lambda j: abs(moon_transit_offset(j, lat, lon)) - 180.0,
                                grid[i - 1], grid[i]))
    return {"moonrise": rises, "moonset": sets,
            "lunar_noon": ups, "lunar_midnight": downs}


GRAZE_HALF_WIDTH_DAYS = 0.25   # six hours either side of the disputed instant


def local_graze(key, jd, lat, lon):
    """How close the body comes to this event's threshold near `jd`, in degrees.

    Returns (margin, limit), or (None, None) for events that have no threshold
    (the transits, which always happen and cannot be tangential).

    The margin is measured over a six-hour window centred on the disputed
    instant, because the turning point that decides whether the crossing
    happens at all is always within a few hours of it. Measuring over the whole
    day would be wrong: a single local day can hold a deep solar midnight at
    one end and a 0.1 arcmin graze at the other, and the deeper one would mask
    the shallow one that is actually in dispute.
    """
    lo_jd = jd - GRAZE_HALF_WIDTH_DAYS
    steps = int(2 * GRAZE_HALF_WIDTH_DAYS * 1440 / 2.0) + 1

    if key in NOAA_THRESHOLD_ALT:
        thr = NOAA_THRESHOLD_ALT[key]
        vals = [noaa_sun_altitude(lo_jd + i * 2.0 / 1440.0, lat, lon) - thr
                for i in range(steps)]
        limit = (TANGENCY_RISE_SET_DEG if key in ("sunrise", "sunset")
                 else TANGENCY_THRESHOLD_DEG)
        return min(abs(min(vals)), abs(max(vals))), limit

    if key in ("moonrise", "moonset"):
        vals = []
        for i in range(steps):
            j = lo_jd + i * 2.0 / 1440.0
            alt, thr = moon_topocentric_altitude(j, lat, lon)
            vals.append(alt - thr)
        return min(abs(min(vals)), abs(max(vals))), TANGENCY_MOON_DEG

    return None, None


def match_occurrences(engine_times, ref_times, tol_days):
    """Pair engine events with reference events by nearest instant.

    Returns (pairs, unmatched_engine, unmatched_reference). Counting alone is
    not enough: when an event sits within a second of local midnight the two
    models can legitimately file it on opposite sides of the boundary, and that
    has to be told apart from an event genuinely lost or invented.
    """
    used = set()
    pairs, extra_ref = [], []
    for r in ref_times:
        best = None
        for i, a in enumerate(engine_times):
            if i in used:
                continue
            if best is None or abs(a - r) < abs(engine_times[best] - r):
                best = i
        if best is not None and abs(engine_times[best] - r) <= tol_days:
            used.add(best)
            pairs.append((engine_times[best], r))
        else:
            extra_ref.append(r)
    extra_eng = [a for i, a in enumerate(engine_times) if i not in used]
    return pairs, extra_eng, extra_ref


def compare_day(site, lat, lon, tzname, day, verbose=False):
    """One site, one day. Returns (rows, counters)."""
    engine = solar.day_events(lat, lon, 0.0, day, tzname)
    eng = {}
    for e in engine["events"]:
        eng.setdefault(e["key"], {"times": [], "status": e["status"]})
        if e["utc"]:
            eng[e["key"]]["times"].append(
                jd_from_datetime(datetime.fromisoformat(e["utc"].replace("Z", "+00:00"))))

    noaa, jd_start, jd_end = noaa_events_for_day(lat, lon, day, tzname)
    moon = noaa_moon_events_for_day(lat, lon, jd_start, jd_end)

    rows = []
    counters = {"pass": 0, "fail": 0, "agree_absent": 0, "count_mismatch": 0,
                "boundary": 0, "tangent": 0, "skipped": 0,
                "max_delta": 0.0, "max_delta_key": "",
                "max_sun": 0.0, "max_sun_key": "",
                "max_moon": 0.0, "max_moon_key": ""}

    for key, _label, body, _dirn, _mode, _p, _thr in solar.LADDER:
        e = eng.get(key, {"times": [], "status": "missing_from_engine"})
        if key in noaa:
            ref, tol, source = noaa[key], sun_tolerance_s(lat), "NOAA"
            if key in ("solar_noon", "solar_midnight"):
                tol = TRANSIT_TOLERANCE_S
        elif key in moon:
            ref, tol, source = moon[key], MOON_TOLERANCE_S, "lunar-series"
            if abs(lat) > MOON_LAT_LIMIT:
                counters["skipped"] += 1
                rows.append((site, day.isoformat(), key, source, "SKIP",
                             None, "lat %.1f is past the lunar series' useful range"
                             % lat))
                continue
        else:
            continue

        if not e["times"] and not ref:
            counters["agree_absent"] += 1
            rows.append((site, day.isoformat(), key, source, "AGREE-ABSENT",
                         None, "engine: %s" % e["status"]))
            continue

        tol_days = tol / 86400.0
        pairs, extra_eng, extra_ref = match_occurrences(e["times"], ref, tol_days)

        for a, b in pairs:
            delta = (a - b) * 86400.0
            counters["pass"] += 1
            if abs(delta) > counters["max_delta"]:
                counters["max_delta"] = abs(delta)
                counters["max_delta_key"] = "%s/%s" % (site, key)
            slot = "moon" if body == "moon" else "sun"
            if abs(delta) > counters["max_" + slot]:
                counters["max_" + slot] = abs(delta)
                counters["max_%s_key" % slot] = "%s %s" % (key, day.isoformat())
            rows.append((site, day.isoformat(), key, source, "PASS", delta,
                         "tol %.0fs" % tol))

        for jd, side in ([(x, "engine") for x in extra_eng]
                         + [(x, "check") for x in extra_ref]):
            edge = min(abs(jd - jd_start), abs(jd - jd_end)) * 86400.0
            # How near the threshold did the body actually get, AROUND THIS
            # INSTANT? A disagreement about whether an event happened is only
            # meaningful when the body cleared the threshold by more than the
            # two models' combined uncertainty about where that threshold is.
            # The window has to be local: a day can hold a deep solar midnight
            # at one end and a 0.1 arcmin graze at the other, and the global
            # minimum would hide the graze that is actually in dispute.
            graze, graze_limit = local_graze(key, jd, lat, lon)
            if graze is not None and graze <= graze_limit:
                counters["tangent"] += 1
                rows.append((site, day.isoformat(), key, source, "TANGENT", None,
                             "%s-only; the body grazes the threshold by %.2f "
                             "arcmin (limit %.1f arcmin) - the two definitions "
                             "cannot agree here" % (side, graze * 60.0,
                                                    graze_limit * 60.0)))
            elif edge <= tol:
                # The event is closer to the day boundary than the reference
                # model's own resolution, so the reference cannot say which
                # local day owns it. The accurate engine decides.
                counters["boundary"] += 1
                rows.append((site, day.isoformat(), key, source, "BOUNDARY", None,
                             "%s-only occurrence, %.1fs from the day edge "
                             "(tol %.0fs) - not adjudicable" % (side, edge, tol)))
            else:
                counters["count_mismatch"] += 1
                rows.append((site, day.isoformat(), key, source, "COUNT", None,
                             "%s-only occurrence at %s, %.0fs from the day edge; "
                             "engine status '%s'"
                             % (side, datetime_from_jd(jd).isoformat(), edge,
                                e["status"])))

    # Illumination, from the elongation of the independent lunar series.
    mid = 0.5 * (jd_start + jd_end)
    ref_illum = moon_illumination_pct(mid)
    got_illum = engine["moon"]["illumination_pct"]
    d_illum = got_illum - ref_illum
    ok = abs(d_illum) <= ILLUM_TOLERANCE_PP
    counters["pass" if ok else "fail"] += 1
    rows.append((site, day.isoformat(), "moon.illumination_pct", "lunar-series",
                 "PASS" if ok else "FAIL", None,
                 "engine %.2f%% vs check %.2f%%, delta %+.2f pp (tol %.1f pp)"
                 % (got_illum, ref_illum, d_illum, ILLUM_TOLERANCE_PP)))

    if verbose:
        for r in rows:
            _print_row(r)
    return rows, counters, engine


def _print_row(r):
    site, day, key, source, verdict, delta, note = r
    d = "%+9.2fs" % delta if delta is not None else "         -"
    print(f"  {site:<10} {day}  {key:<22} {source:<13} {verdict:<13} {d}  {note}")


def occurrence_reconciliation(data, lat, lon, tzname, day):
    """Does the engine emit one time per crossing the sky actually made?

    HONEST SCOPE: this is not a second ephemeris. It is a second METHOD inside
    the same one. The engine's times come from swe_rise_trans, a root solver;
    this counts sign changes on a sampled altitude curve from swe_calc_ut. They
    share Swiss and they share DE441, so this cannot catch a wrong ephemeris.
    What it catches is swe_rise_trans stepping over an event, which is a real
    and measured failure of that function near polar boundaries and which the
    NOAA comparison above structurally CANNOT see: when the reference model's
    own horizon is 2.55 arcmin shallower, it simply has no crossing there to
    miss, so a dropped occurrence reads as agreement.

    That is not hypothetical. Before this check existed the engine dropped the
    sunset at Reykjavik on 2026-06-30, 0.8 s into the local day, and every
    NOAA row for that day passed.
    """
    faults = []
    counts = {}
    for e in data["events"]:
        if e["utc"]:
            counts[e["key"]] = counts.get(e["key"], 0) + 1
    start, end = solar.local_day_bounds(day, tzname)
    jd0, jd1 = solar.jd_utc(start), solar.jd_utc(end)
    tracks = {}
    for key, _label, body, direction, _mode, _p, thr in solar.LADDER:
        if direction in (solar.TRANSIT_UP, solar.TRANSIT_DOWN):
            continue
        if body not in tracks:
            tracks[body] = solar._AltitudeTrack(body, (lon, lat, 0.0), jd0, jd1)
        n_track = len(tracks[body].crossings(thr, direction))
        n_engine = counts.get(key, 0)
        if n_track != n_engine:
            faults.append("%s: engine emitted %d occurrence(s), the altitude "
                          "curve crosses the threshold %d time(s)"
                          % (key, n_engine, n_track))
    return faults


def structural_checks(data, lat, lon, tzname, day):
    """Contract checks that need no second ephemeris at all."""
    faults = []
    keys = [e["key"] for e in data["events"]]
    for k, *_ in solar.LADDER:
        if k not in keys:
            faults.append("key '%s' absent from events" % k)
    timed = [e["utc"] for e in data["events"] if e["utc"]]
    if timed != sorted(timed):
        faults.append("timed events are not in chronological order")
    first_null = next((i for i, e in enumerate(data["events"]) if not e["utc"]),
                      len(data["events"]))
    if any(e["utc"] for e in data["events"][first_null:]):
        faults.append("a timed event is sorted after an absent one")
    for e in data["events"]:
        if (e["utc"] is None) != (e["status"] != "ok"):
            faults.append("%s: status '%s' disagrees with utc %s"
                          % (e["key"], e["status"], e["utc"]))
        if e["utc"] and e["local"]:
            a = datetime.fromisoformat(e["utc"].replace("Z", "+00:00"))
            b = datetime.fromisoformat(e["local"])
            if a != b:
                faults.append("%s: utc and local are different instants" % e["key"])
    for field in ("date", "tz", "observer", "day_length_s", "moon", "events"):
        if field not in data:
            faults.append("contract field '%s' missing" % field)
    faults.extend(occurrence_reconciliation(data, lat, lon, tzname, day))
    return faults


def main():
    ap = argparse.ArgumentParser(
        description="Independent cross-check of the SUNMAP engine.")
    ap.add_argument("--site", action="append",
                    help="site name (repeatable); default is all seven")
    ap.add_argument("--date", action="append", help="YYYY-MM-DD (repeatable)")
    ap.add_argument("--sweep", type=int, default=0,
                    help="check N consecutive days from the first --date instead")
    ap.add_argument("--verbose", action="store_true", help="print every row")
    args = ap.parse_args()

    sites = args.site or list(SITES)
    if args.sweep:
        first = _date.fromisoformat(args.date[0]) if args.date else _date(2026, 1, 1)
        dates = [first + timedelta(days=i) for i in range(args.sweep)]
    else:
        dates = [_date.fromisoformat(s) for s in (args.date or DEFAULT_DATES)]

    print("SUNMAP ENGINE CROSS-CHECK")
    print("Engine under test : scripts/solar.py (Swiss Ephemeris %s, JPL DE441)"
          % solar.swe.version)
    print("Sun reference     : NOAA Solar Calculator algorithm, implemented in "
          "this file from stdlib math only")
    print("Moon reference    : abbreviated Meeus lunar series, implemented in "
          "this file from stdlib math only")
    print("                    NOAA has no lunar theory and cannot check the "
          "Moon at all - the Moon is judged")
    print("                    solely by that separate series, at a 15 minute "
          "tolerance, which is its honest accuracy")
    print("Tolerances        : Sun rise/set/twilight/golden %ds up to 55 deg, "
          "%ds to 66 deg, %ds beyond"
          % (sun_tolerance_s(0), sun_tolerance_s(60), sun_tolerance_s(80)))
    print("                    solar noon/midnight %ds  |  Moon events %ds "
          "(only up to %d deg)  |  illumination %.1f pp"
          % (TRANSIT_TOLERANCE_S, MOON_TOLERANCE_S, MOON_LAT_LIMIT,
             ILLUM_TOLERANCE_PP))
    print()
    if args.verbose:
        print(f"  {'site':<10} {'date':<10}  {'event':<22} {'source':<13} "
              f"{'verdict':<13} {'delta':>10}  note")

    total = {"pass": 0, "fail": 0, "agree_absent": 0, "count_mismatch": 0,
             "boundary": 0, "tangent": 0, "skipped": 0}
    worst = []
    fails = []
    struct_faults = []

    for name in sites:
        lat, lon, tzname = SITES[name]
        site_worst = (0.0, "")
        worst_sun = (0.0, "-")
        worst_moon = (0.0, "-")
        for day in dates:
            rows, c, data = compare_day(name, lat, lon, tzname, day,
                                        verbose=args.verbose)
            for k in total:
                total[k] += c[k]
            if c["max_delta"] > site_worst[0]:
                site_worst = (c["max_delta"], c["max_delta_key"])
            fails.extend(r for r in rows if r[4] in ("FAIL", "COUNT"))
            if c["max_sun"] > worst_sun[0]:
                worst_sun = (c["max_sun"], c["max_sun_key"])
            if c["max_moon"] > worst_moon[0]:
                worst_moon = (c["max_moon"], c["max_moon_key"])
            for f in structural_checks(data, lat, lon, tzname, day):
                struct_faults.append("%s %s: %s" % (name, day, f))
        worst.append((name, lat, worst_sun, worst_moon))

    print("PER-SITE WORST DELTA  (engine minus independent reference)")
    print(f"  {'site':<12} {'lat':>8}  {'worst SUN':>11}  {'at':<28} "
          f"{'worst MOON':>11}  at")
    for name, lat, ws, wm in worst:
        print(f"  {name:<12} {lat:>8.4f}  {ws[0]:>10.2f}s  {ws[1]:<28} "
              f"{wm[0]:>10.2f}s  {wm[1]}")
    print("  (a Moon column of 0.00s / '-' means the lunar series declined to "
          "judge this site at all - see the skipped count below)")

    print()
    print("STRUCTURAL CONTRACT CHECKS (no second ephemeris; the occurrence "
          "count is reconciled against\nthe altitude curve, a second method "
          "inside Swiss rather than a second source)")
    if struct_faults:
        for f in struct_faults:
            print("  FAULT", f)
    else:
        print("  %d site-days: every ladder key present, chronological order "
              "holds, status and time agree,\n  contract fields present, and "
              "every emitted occurrence matches a real crossing of the "
              "altitude curve" % (len(sites) * len(dates)))

    print()
    print("TOTALS")
    print("  compared and within tolerance : %d" % total["pass"])
    print("  outside tolerance             : %d" % total["fail"])
    print("  both agree the event is absent: %d" % total["agree_absent"])
    print("  occurrence-count disagreement : %d" % total["count_mismatch"])
    print("  day-boundary straddles        : %d  (event sits closer to local "
          "midnight than the reference model can resolve)" % total["boundary"])
    print("  threshold tangencies          : %d  (body grazes the threshold; "
          "the two definitions of the horizon differ by 2.55 arcmin)"
          % total["tangent"])
    print("  not judged (Moon above %d deg): %d" % (MOON_LAT_LIMIT, total["skipped"]))

    if fails and not args.verbose:
        print()
        print("ROWS NEEDING ATTENTION")
        for r in fails:
            _print_row(r)

    bad = total["fail"] + total["count_mismatch"] + len(struct_faults)
    print()
    print("VERDICT: %s" % ("PASS" if bad == 0 else "FAIL (%d rows)" % bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
