#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 PUDDY Inc. <legal@puddystudios.com>
"""Render the SUNMAP shell - one self-contained index.html, zero dependencies.

Pure Python standard library, exactly like STARMAP's scripts/render.py. Nothing
is fetched, nothing is bundled, no third-party import appears anywhere in this
file. Run it and it writes ../index.html.

What it emits:
  - The PUDDY chrome (masthead + static footer fallback), the STARMAP type scale,
    pure black, the same controls-panel grammar. SUNMAP reads as a sibling.
  - THE BEAM FIELD: a procedurally generated inline SVG of crepuscular light rays,
    animated with CSS keyframes, frozen (never removed) under prefers-reduced-motion.
    Geometry is computed here in Python the way STARMAP computes its sigil geometry.
  - The full event ladder. Sun events always on, moon events behind a toggle that
    persists in localStorage (founder requirement).
  - Location control (delegates to sunmap-geo.js), date navigation, moon panel.
  - A crawlable prerendered block of the build day's events for Los Angeles, so a
    crawler never sees an empty page.
  - SEO: canonical (always the PROD host), description, Open Graph, Twitter,
    JSON-LD (WebSite, Organization, WebPage, BreadcrumbList, WebApplication, FAQPage).

The runtime seam, both halves owned by other agents:
  sunmap-worker.js - a MODULE worker. The page posts
      {type:'day', id, lat, lon, alt_m, date, tz}
    and accepts the DATA CONTRACT back in any of these envelopes:
      the bare contract object, {id, data:<contract>}, {id, result:<contract>},
      {id, ok:true, day:<contract>}. An {error} field is surfaced honestly.
  sunmap-geo.js - an ES module, imported dynamically so a missing or broken geo
    module degrades the page instead of killing it. The adapter probes for
      search/suggest/autocomplete/geocode  -> Promise<[{label, sub, lat, lon, tz?, alt_m?}]>
      here/locate/deviceLocation/ipLocate  -> Promise<{lat, lon, tz?, label?, alt_m?}>
      timezoneFor/tzFor/zoneFor/nearestZone -> string
    and falls back to navigator.geolocation, typed "lat, lon" coordinates, and the
    device timezone. Whatever the geo module actually exports, the page still works.

Prerender engine: this script shells out to the oracle (scripts/solar.py, Swiss
Ephemeris) when pyswisseph is installed on the build machine, so the static block
carries true Swiss values. If it is not installed the script falls back to its own
NOAA solar-position solver implemented here in stdlib math - measured within about
15 seconds of Swiss on the ladder - and says so in the page. The generator itself never gains a dependency.

Usage:
  python3 render_page.py                                             # prod build
  python3 render_page.py --base / --site https://sunmap.puddy.dev/   # demo build
"""
import argparse
import html as _html
import json
import math
import random
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SUN = Path(__file__).resolve().parents[1]

# The canonical production home. Canonical NEVER points anywhere else, even on a
# demo build - the demo host must not compete with prod in the index.
PROD = 'https://sunmap.puddystudios.com/'
DEMO = 'https://sunmap.puddy.dev/'

_ap = argparse.ArgumentParser(description='Render the SUNMAP page.')
_ap.add_argument('--base', default='/', help="URL mount: '/' for the sunmap subdomains, or a subpath")
_ap.add_argument('--site', default=PROD, help='origin+base this build is served from (canonical still points at prod)')
_ap.add_argument('--og-site', default=None, help='host for OG images (defaults to --site) so demo link previews resolve')
_ap.add_argument('--out', default=None, help='output path (defaults to ../index.html)')
_args = _ap.parse_args()

BASE = _args.base if _args.base.endswith('/') else _args.base + '/'
SITE = _args.site if _args.site.endswith('/') else _args.site + '/'
OG_SITE = (_args.og_site or SITE)
OG_SITE = OG_SITE if OG_SITE.endswith('/') else OG_SITE + '/'
OUT = Path(_args.out) if _args.out else (SUN / 'index.html')
IS_PROD = (SITE == PROD)

# --------------------------------------------------------------------------
# The event ladder. Chronological intent, not alphabetical. Mirrors solar.py.
# (key, label, body, plain-language note)
# --------------------------------------------------------------------------
LADDER = [
    ('astronomical_dawn',    'Astronomical dawn',  'sun',  'Sun centre reaches 18 deg below the horizon. The first light in the sky.'),
    ('nautical_dawn',        'Nautical dawn',      'sun',  'Sun centre at 12 deg below. The horizon becomes visible at sea.'),
    ('civil_dawn',           'Civil dawn',         'sun',  'Sun centre at 6 deg below. Bright enough to read outdoors.'),
    ('golden_hour_start_am', 'Golden hour begins', 'sun',  'Sun centre crosses 4 deg below the horizon, rising.'),
    ('sunrise',              'Sunrise',            'sun',  'The upper limb clears the horizon, refraction included.'),
    ('golden_hour_end_am',   'Golden hour ends',   'sun',  'Sun centre passes 6 deg above the horizon, rising.'),
    ('solar_noon',           'Solar noon',         'sun',  'Upper transit. The sun is due south or due north and at its highest.'),
    ('golden_hour_start_pm', 'Golden hour begins', 'sun',  'Sun centre drops back through 6 deg above the horizon.'),
    ('sunset',               'Sunset',             'sun',  'The upper limb touches the horizon, refraction included.'),
    ('golden_hour_end_pm',   'Golden hour ends',   'sun',  'Sun centre drops through 4 deg below the horizon.'),
    ('civil_dusk',           'Civil dusk',         'sun',  'Sun centre at 6 deg below. Outdoor detail is gone.'),
    ('nautical_dusk',        'Nautical dusk',      'sun',  'Sun centre at 12 deg below. The sea horizon is lost.'),
    ('astronomical_dusk',    'Astronomical dusk',  'sun',  'Sun centre at 18 deg below. Full astronomical night.'),
    ('solar_midnight',       'Solar midnight',     'sun',  'Lower transit. The sun is at its lowest, below the horizon.'),
    ('moonrise',             'Moonrise',           'moon', 'The upper limb of the moon clears the horizon.'),
    ('lunar_noon',           'Lunar noon',         'moon', 'Upper transit. The moon is at its highest for the day.'),
    ('moonset',              'Moonset',            'moon', 'The upper limb of the moon touches the horizon.'),
    ('lunar_midnight',       'Lunar midnight',     'moon', 'Lower transit. The moon is at its lowest, below the horizon.'),
]

DEFAULT_LOC = {'lat': 34.0522, 'lon': -118.2437, 'alt_m': 0.0,
               'tz': 'America/Los_Angeles', 'label': 'Los Angeles, California'}

# --------------------------------------------------------------------------
# THE BEAM FIELD - procedural geometry, generated here, emitted as inline SVG.
#
# A single radiant point sits above the top edge. Rays fan down across the whole
# canvas. Widths, angles and opacities come from a seeded deterministic PRNG so a
# rebuild is byte-identical. Length falloff is one shared user-space radial
# gradient (so 34 beams cost one gradient, not 34), and each beam carries its own
# base opacity, breathing period and phase offset as CSS custom properties. The
# whole field sways about the radiant point on a two-minute cycle.
#
# Restraint rules, deliberately: peak beam alpha stays under 0.11 on pure black,
# no bloom sprite, no chromatic tint, no starburst at the source. What reads is a
# shaft of light through air, not a lens flare.
# --------------------------------------------------------------------------
SRC_X, SRC_Y = 508.0, -168.0   # the radiant point, just off the top edge
FAN_AXIS = 90.0                # degrees, straight down the canvas
FAN_SPAN = 63.0                # half-width of the fan
RAY_LEN = 2050.0               # beyond the far corner at any aspect ratio
N_BEAMS = 34


def _beam_field():
    rng = random.Random(20260809)   # frozen seed: deterministic output
    defs = []

    # Shared falloff: bright at the source, gone before the far edge.
    defs.append(
        f'<radialGradient id="sm-fall" gradientUnits="userSpaceOnUse" '
        f'cx="{SRC_X:.1f}" cy="{SRC_Y:.1f}" r="{RAY_LEN * 0.86:.0f}">'
        '<stop offset="0" stop-color="#fff" stop-opacity="0.92"/>'
        '<stop offset="0.28" stop-color="#fff" stop-opacity="0.55"/>'
        '<stop offset="0.66" stop-color="#fff" stop-opacity="0.14"/>'
        '<stop offset="1" stop-color="#fff" stop-opacity="0"/>'
        '</radialGradient>')
    # The wash: one wide cone under everything, so the beams sit in air.
    defs.append(
        '<radialGradient id="sm-wash" gradientUnits="userSpaceOnUse" '
        f'cx="{SRC_X:.1f}" cy="{SRC_Y:.1f}" r="{RAY_LEN * 0.62:.0f}">'
        '<stop offset="0" stop-color="#fff" stop-opacity="0.10"/>'
        '<stop offset="0.45" stop-color="#fff" stop-opacity="0.030"/>'
        '<stop offset="1" stop-color="#fff" stop-opacity="0"/>'
        '</radialGradient>')

    body = []

    def wedge(a_deg, w_deg):
        """Path from the radiant point out to a chord of angular width w."""
        a0 = math.radians(a_deg - w_deg / 2.0)
        a1 = math.radians(a_deg + w_deg / 2.0)
        x0 = SRC_X + RAY_LEN * math.cos(a0)
        y0 = SRC_Y + RAY_LEN * math.sin(a0)
        x1 = SRC_X + RAY_LEN * math.cos(a1)
        y1 = SRC_Y + RAY_LEN * math.sin(a1)
        return (f'M{SRC_X:.1f} {SRC_Y:.1f}L{x0:.1f} {y0:.1f}'
                f'A{RAY_LEN:.0f} {RAY_LEN:.0f} 0 0 1 {x1:.1f} {y1:.1f}Z')

    # The wash cone.
    body.append(f'<path class="sm-wash" d="{wedge(FAN_AXIS, FAN_SPAN * 2.05)}" fill="url(#sm-wash)"/>')

    # Three hairline arcs centred on the source: sun-disc geometry, echoing the
    # concentric rings of the STARMAP sigil so the two products rhyme.
    for i, r in enumerate((430.0, 760.0, 1180.0)):
        op = 0.055 - i * 0.013
        body.append(f'<circle class="sm-arc" cx="{SRC_X:.1f}" cy="{SRC_Y:.1f}" r="{r:.0f}" '
                    f'fill="none" stroke="#fff" stroke-width="1" opacity="{op:.3f}"/>')

    # The beams themselves.
    for i in range(N_BEAMS):
        # Even spread plus a bounded jitter: ordered, never mechanical.
        t = (i + 0.5) / N_BEAMS                    # 0..1 across the fan
        off = (t * 2.0 - 1.0) * FAN_SPAN
        off += rng.uniform(-0.42, 0.42) * (FAN_SPAN / N_BEAMS) * 2.0
        ang = FAN_AXIS + off

        edge = abs(off) / FAN_SPAN                 # 0 at the axis, 1 at the rim
        # Cosine shoulder: bright core, clean fade to the rim. No hard cutoff.
        core = math.cos(min(1.0, edge) * math.pi / 2.0) ** 1.55
        width = (0.42 + 2.35 * (rng.random() ** 1.9)) * (0.55 + 0.45 * core)
        alpha = (0.022 + 0.082 * core) * (0.62 + 0.38 * rng.random())
        # Wide beams carry less alpha than narrow ones, or the fan turns to fog.
        alpha *= 1.0 - min(0.34, width * 0.11)

        dur = 13.0 + rng.random() * 21.0           # breathing period, seconds
        delay = -rng.random() * dur                # negative: already mid-cycle on load
        body.append(
            f'<path class="sm-ray" d="{wedge(ang, width)}" fill="url(#sm-fall)" '
            f'style="--o:{alpha:.4f};--d:{dur:.1f}s;--t:{delay:.1f}s"/>')

    return ''.join(defs), ''.join(body)


BEAM_DEFS, BEAM_BODY = _beam_field()

# --------------------------------------------------------------------------
# Prerender: the build day's events for the default location.
# Oracle first (Swiss, via solar.py), stdlib NOAA solver as the fallback.
# --------------------------------------------------------------------------
_SOLAR = SUN / 'scripts' / 'solar.py'
J2000 = 2451545.0


def _jd(dt):
    return dt.timestamp() / 86400.0 + 2440587.5


def _from_jd(jd):
    return datetime.fromtimestamp((jd - 2440587.5) * 86400.0, tz=timezone.utc)


def _sun_alt(jd, lat, lon):
    """Geometric solar altitude in degrees (USNO approximate, about 0.01 deg)."""
    n = jd - J2000
    L = math.radians((280.460 + 0.9856474 * n) % 360.0)
    g = math.radians((357.528 + 0.9856003 * n) % 360.0)
    lam = L + math.radians(1.915 * math.sin(g) + 0.020 * math.sin(2 * g))
    eps = math.radians(23.439 - 0.0000004 * n)
    ra = math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))
    dec = math.asin(math.sin(eps) * math.sin(lam))
    gmst = (18.697374558 + 24.06570982441908 * n) % 24.0
    ha = math.radians((gmst * 15.0 + lon) - math.degrees(ra))
    phi = math.radians(lat)
    return math.degrees(math.asin(
        math.sin(phi) * math.sin(dec) + math.cos(phi) * math.cos(dec) * math.cos(ha)))


def _noaa_day(lat, lon, alt_m, day, tzname):
    """Fallback day solve, stdlib only. Sun events; the moon is left to the engine."""
    tz = ZoneInfo(tzname)
    t0 = datetime.combine(day, datetime.min.time(), tzinfo=tz)
    t1 = t0 + timedelta(days=1)
    jd0, jd1 = _jd(t0), _jd(t1)
    step = 60.0 / 86400.0
    samples = []
    t = jd0
    while t <= jd1 + step:
        samples.append((t, _sun_alt(t, lat, lon)))
        t += step

    targets = {'astronomical_dawn': (-18.0, True), 'nautical_dawn': (-12.0, True),
               'civil_dawn': (-6.0, True), 'golden_hour_start_am': (-4.0, True),
               'sunrise': (-0.8333, True), 'golden_hour_end_am': (6.0, True),
               'golden_hour_start_pm': (6.0, False), 'sunset': (-0.8333, False),
               'golden_hour_end_pm': (-4.0, False), 'civil_dusk': (-6.0, False),
               'nautical_dusk': (-12.0, False), 'astronomical_dusk': (-18.0, False)}

    # ALL crossings, not the first: a 25-hour fall-back day really can carry a
    # crossing twice, and the contract says nothing is ever dropped.
    found = {}
    for key, (h, rising) in targets.items():
        hits = []
        for i in range(len(samples) - 1):
            a, b = samples[i], samples[i + 1]
            if (a[1] - h < 0) == (b[1] - h < 0):
                continue
            if (b[1] > a[1]) != rising:
                continue
            lo, hi = a[0], b[0]
            for _ in range(42):
                mid = (lo + hi) / 2.0
                if (_sun_alt(lo, lat, lon) - h < 0) == (_sun_alt(mid, lat, lon) - h < 0):
                    lo = mid
                else:
                    hi = mid
            hits.append((lo + hi) / 2.0)
        found[key] = hits

    # Transits: every local extremum of the sampled curve, refined by golden section.
    def _extrema(want_max):
        gr = (math.sqrt(5.0) - 1.0) / 2.0
        out = []
        for i in range(1, len(samples) - 1):
            p, c, n = samples[i - 1][1], samples[i][1], samples[i + 1][1]
            if (c >= p and c >= n) if want_max else (c <= p and c <= n):
                lo, hi = samples[i - 1][0], samples[i + 1][0]
                for _ in range(80):
                    x = hi - gr * (hi - lo)
                    y = lo + gr * (hi - lo)
                    fx, fy = _sun_alt(x, lat, lon), _sun_alt(y, lat, lon)
                    if (fx > fy) if want_max else (fx < fy):
                        hi = y
                    else:
                        lo = x
                t = (lo + hi) / 2.0
                if not out or (t - out[-1]) * 86400.0 > 120.0:
                    out.append(t)
        return out

    found['solar_noon'] = _extrema(True)
    found['solar_midnight'] = _extrema(False)

    # Every key appears every day, with a status that says why - same rule the
    # engine follows. A missing crossing is classified against the day's actual
    # altitude range, never guessed.
    lo_alt = min(s[1] for s in samples)
    hi_alt = max(s[1] for s in samples)
    events = []
    for key, label, body, _note in LADDER:
        if body != 'sun':
            # The build-time fallback has no lunar theory. Say that, do not imply
            # the moon event failed to happen.
            events.append({'key': key, 'label': label, 'body': body,
                           'utc': None, 'local': None, 'status': 'not_computed'})
            continue
        hit_any = False
        for jd in found.get(key) or []:
            dt = _from_jd(jd)
            loc = dt.astimezone(tz)
            if not (t0 <= loc < t1):
                continue
            events.append({'key': key, 'label': label, 'body': 'sun',
                           'utc': dt.isoformat().replace('+00:00', 'Z'),
                           'local': loc.isoformat(), 'status': 'ok'})
            hit_any = True
        if hit_any:
            continue
        h = targets.get(key, (None, None))[0]
        if h is None:
            status = 'none_today'
        elif lo_alt > h:
            status = 'always_above'
        elif hi_alt < h:
            status = 'always_below'
        else:
            status = 'none_today'
        events.append({'key': key, 'label': label, 'body': 'sun',
                       'utc': None, 'local': None, 'status': status})
    events.sort(key=lambda e: (e['utc'] is None, e['utc'] or ''))

    by = {e['key']: e for e in events}
    rise_e, set_e = by.get('sunrise'), by.get('sunset')
    day_len = None
    if rise_e and rise_e.get('utc') and set_e and set_e.get('utc'):
        sr = datetime.fromisoformat(rise_e['utc'].replace('Z', '+00:00'))
        ss = datetime.fromisoformat(set_e['utc'].replace('Z', '+00:00'))
        day_len = round((ss - sr).total_seconds())
    elif rise_e and rise_e.get('status') == 'always_above':
        day_len = round((t1 - t0).total_seconds())   # polar day: the whole local day
    elif rise_e and rise_e.get('status') == 'always_below':
        day_len = 0                                  # polar night

    return {'date': day.isoformat(), 'tz': tzname,
            'observer': {'lat': lat, 'lon': lon, 'alt_m': alt_m},
            'engine': 'NOAA solar position algorithm (build-time fallback)',
            'day_length_s': day_len, 'moon': None, 'events': events}


def _oracle_day(lat, lon, alt_m, day, tzname):
    """Ask scripts/solar.py. Returns None if pyswisseph is not on this machine."""
    if not _SOLAR.exists():
        return None
    try:
        p = subprocess.run(
            [sys.executable, str(_SOLAR), '--lat', repr(lat), '--lon', repr(lon),
             '--alt', repr(alt_m), '--date', day.isoformat(), '--tz', tzname, '--json'],
            capture_output=True, text=True, timeout=180)
    except Exception:
        return None
    if p.returncode != 0 or not p.stdout.strip():
        return None
    try:
        d = json.loads(p.stdout)
    except json.JSONDecodeError:
        return None
    return d if isinstance(d, dict) and d.get('events') else None


BUILD_DAY = datetime.now(ZoneInfo(DEFAULT_LOC['tz'])).date()
PRE = (_oracle_day(DEFAULT_LOC['lat'], DEFAULT_LOC['lon'], DEFAULT_LOC['alt_m'],
                   BUILD_DAY, DEFAULT_LOC['tz'])
       or _noaa_day(DEFAULT_LOC['lat'], DEFAULT_LOC['lon'], DEFAULT_LOC['alt_m'],
                    BUILD_DAY, DEFAULT_LOC['tz']))
PRE_SWISS = 'Swiss' in (PRE.get('engine') or '')

_MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
           'August', 'September', 'October', 'November', 'December']


def _long_date(d):
    return f'{_MONTHS[d.month - 1]} {d.day}, {d.year}'


def _clock(iso):
    """Local ISO with offset -> '6:07:12 AM'. No timezone abbreviation guessing."""
    t = datetime.fromisoformat(iso)
    h = t.hour % 12 or 12
    return f'{h}:{t.minute:02d}:{t.second:02d} {"AM" if t.hour < 12 else "PM"}'


def _dur(secs):
    if secs is None:
        return None
    h, rem = divmod(int(secs), 3600)
    m, s = divmod(rem, 60)
    return f'{h}h {m}m {s}s'


def _status_line(body, key, status):
    """The engine's status vocabulary in plain language. Mirrors noTime() in the runtime."""
    rs = key in ('sunrise', 'sunset', 'moonrise', 'moonset')
    moon = (body == 'moon')
    if status == 'always_above':
        if moon:
            return 'None - The moon is circumpolar today and never sets'
        return ('None - Polar day, the sun does not set' if rs
                else 'Never reached - The sun stays above this altitude all day')
    if status == 'always_below':
        if moon:
            return 'None - The moon stays below the horizon all day'
        return ('None - Polar night, the sun does not rise' if rs
                else 'Never reached - The sun stays below this altitude all day')
    if status == 'none_today':
        return 'None on this date'
    if status == 'not_computed':
        return 'Not computed at build time - The live engine fills this in'
    if status == 'circumpolar':
        return 'None - the body does not cross this altitude on this date'
    if str(status).startswith('error'):
        return f'Not solved - {status}'
    return f'No time - {status}'


def _pre_events(key):
    """Every occurrence of a key in the prerendered day, in time order."""
    hits = [e for e in PRE['events'] if e['key'] == key]
    hits.sort(key=lambda e: (e.get('utc') is None, e.get('utc') or ''))
    return hits


_PRE_BY = {e['key']: e for e in PRE['events']}
PRE_SUNRISE = _clock(_PRE_BY['sunrise']['local']) if _PRE_BY.get('sunrise', {}).get('local') else None
PRE_SUNSET = _clock(_PRE_BY['sunset']['local']) if _PRE_BY.get('sunset', {}).get('local') else None
PRE_DAYLEN = _dur(PRE.get('day_length_s'))


def _prerender_rows(body):
    rows = []
    glyph = '&#9737;' if body == 'sun' else '&#9789;'   # sun and moon text sigils
    for key, label, b, note in LADDER:
        if b != body:
            continue
        hits = _pre_events(key) or [None]
        total = len(hits)
        cls = ' class="key"' if key in ('sunrise', 'sunset', 'solar_noon') else ''
        for i, e in enumerate(hits, 1):
            if e and e.get('local'):
                when = f'<time datetime="{_html.escape(e["utc"])}">{_clock(e["local"])}</time>'
            elif e:
                when = ('<span class="none">'
                        + _html.escape(_status_line(body, key, e.get('status') or 'unavailable'))
                        + '</span>')
            else:
                when = '<span class="none">Not reported for this date</span>'
            n = note + (f' Occurrence {i} of {total} on this local day.' if total > 1 else '')
            rows.append(
                f'<tr{cls}><th scope="row"><span class="gl" aria-hidden="true">{glyph}</span>'
                f'{_html.escape(label)}</th>'
                f'<td class="t">{when}<span class="rn">{_html.escape(n)}</span></td></tr>')
    return ''.join(rows)


PRE_SUN_ROWS = _prerender_rows('sun')
PRE_MOON_ROWS = _prerender_rows('moon')

PRE_ENGINE_NOTE = (
    'Times below are the build-day values for Los Angeles, computed with the Swiss '
    'Ephemeris (DE441) engine. The page recomputes live, on your device, for your own '
    'location and any date you choose.'
    if PRE_SWISS else
    'Times below are the build-day values for Los Angeles, computed with the NOAA solar '
    'position algorithm - Within about 15 seconds of the Swiss Ephemeris engine that runs '
    'live in the page. The page recomputes on your device for your own location and any '
    'date you choose.')

# --------------------------------------------------------------------------
# Copy, SEO, FAQ
# --------------------------------------------------------------------------
TITLE = 'SUNMAP | Sunrise, Sunset and Golden Hour - Solved to the Second'
DESC = ('Every solar and lunar event of your day to the second - Sunrise, sunset, '
        'golden hour, all three twilights, solar noon and solar midnight, plus '
        'moonrise, moonset and illumination. Swiss Ephemeris on JPL DE441, computed '
        'on your device.')
OG_DESC = ('Sunrise, sunset, golden hour and every twilight of your day, to the second - '
           'Swiss Ephemeris on JPL DE441, computed on your device')
KEYWORDS = ('sunrise time, sunset time, golden hour calculator, blue hour, civil twilight, '
            'nautical twilight, astronomical twilight, solar noon, day length, moonrise, '
            'moonset, moon illumination, sun times today, photography light times')
OG_IMG = OG_SITE + 'og/sunmap-og.png'
OG_ALT = 'SUNMAP: the daily solar and lunar cycle - Puddy Studios'

FAQ = [
    ('What is golden hour and when does it happen?',
     'Golden hour is the stretch when the centre of the sun sits between 4 degrees below '
     'and 6 degrees above the horizon, so sunlight travels a long path through the '
     'atmosphere and turns warm and low-contrast. It happens twice a day, once climbing '
     'out of dawn and once falling into dusk. SUNMAP solves both edges of both windows '
     'for your exact coordinates, so the length of golden hour changes with your latitude '
     'and the season the way it actually does.'),
    ('Why do SUNMAP times differ from other almanacs by a minute?',
     'Most almanacs round to the minute and solve for a city centre or a whole timezone. '
     'SUNMAP solves topocentrically, for the latitude, longitude and altitude you give it, '
     'on the Swiss Ephemeris running against the JPL DE441 planetary ephemeris, and reports '
     'the result to the second. A sunrise is a statement about one observer standing on one '
     'patch of ground, and moving a few kilometres genuinely moves it.'),
    ('What happens above the Arctic Circle, when the sun never sets?',
     'SUNMAP says so plainly. On a polar day there is no sunrise and no sunset, so those '
     'rows read "None - Polar day, the sun does not set" instead of a time, and the same holds through '
     'polar night. The page never invents a time for an event that does not exist, and it '
     'never leaves the row blank and lets you guess.'),
    ('How accurate are these times?',
     'The engine is the Swiss Ephemeris 2.10.03 on JPL DE441, the same engine and the same '
     'ephemeris files that power STARMAP. Rise and set instants are solved with the Swiss '
     'rise and transit routines including refraction and the solar semidiameter. The '
     'limiting factor is not the ephemeris, it is your horizon: local terrain, buildings '
     'and unusual air pressure move a real-world sunrise by more than the engine error.'),
    ('Does SUNMAP send my location anywhere?',
     'No. The whole calculation runs in a worker on your device against ephemeris files '
     'served with the page. Choosing a place by name calls a geocoder to turn that name '
     'into coordinates, and using your device location asks the browser. Nothing about the '
     'day you compute leaves the browser.'),
    ('Can I turn the moon off?',
     'Yes, and it is off by default. Sun events are always shown. The moon toggle adds '
     'moonrise, lunar noon, moonset and lunar midnight to the ladder plus an illumination '
     'and phase panel, and the page remembers the choice on this device.'),
]


def _jsonld():
    graph = [
        {'@type': 'WebSite', '@id': 'https://puddystudios.com/#website',
         'url': 'https://puddystudios.com/', 'name': 'Puddy Studios',
         'publisher': {'@id': 'https://puddystudios.com/#org'}},
        {'@type': 'Organization', '@id': 'https://puddystudios.com/#org',
         'name': 'PUDDY Inc.', 'url': 'https://puddystudios.com/',
         'logo': 'https://puddystudios.com/puddy-logo.svg'},
        {'@type': 'ImageObject', '@id': PROD + '#primaryimage', 'url': OG_IMG,
         'contentUrl': OG_IMG, 'width': 2400, 'height': 1260, 'caption': OG_ALT},
        {'@type': 'WebPage', '@id': PROD + '#webpage', 'url': PROD, 'name': TITLE,
         'isPartOf': {'@id': 'https://puddystudios.com/#website'},
         'primaryImageOfPage': {'@id': PROD + '#primaryimage'},
         'image': {'@id': PROD + '#primaryimage'},
         'description': DESC,
         'about': ['Sunrise', 'Sunset', 'Golden hour', 'Twilight', 'Solar noon',
                   'Moonrise', 'Moon illumination'],
         'breadcrumb': {'@id': PROD + '#breadcrumb'}},
        {'@type': 'BreadcrumbList', '@id': PROD + '#breadcrumb', 'itemListElement': [
            {'@type': 'ListItem', 'position': 1, 'name': 'Puddy Studios',
             'item': 'https://puddystudios.com/'},
            {'@type': 'ListItem', 'position': 2, 'name': 'SUNMAP', 'item': PROD}]},
        {'@type': 'WebApplication', '@id': PROD + '#app', 'name': 'SUNMAP', 'url': PROD,
         'image': OG_IMG, 'applicationCategory': 'UtilitiesApplication',
         'operatingSystem': 'Any', 'browserRequirements': 'Requires JavaScript',
         'description': ('The daily solar and lunar cycle to the second - Sunrise, sunset, '
                         'golden hour, civil, nautical and astronomical twilight, solar noon '
                         'and solar midnight, moonrise, moonset and illumination, computed '
                         'on your device with the Swiss Ephemeris on JPL DE441.'),
         'featureList': [
             'Sunrise and sunset to the second',
             'Golden hour windows, morning and evening',
             'Civil, nautical and astronomical twilight',
             'Solar noon and solar midnight',
             'Day length',
             'Optional moonrise, moonset and lunar transits',
             'Moon illumination and phase',
             'Any date, any location on Earth',
             'Honest reporting of polar day and polar night'],
         'isAccessibleForFree': True,
         'offers': {'@type': 'Offer', 'price': '0', 'priceCurrency': 'USD'},
         'creator': {'@id': 'https://puddystudios.com/#org'}},
        {'@type': 'FAQPage', '@id': PROD + '#faq', 'mainEntity': [
            {'@type': 'Question', 'name': q,
             'acceptedAnswer': {'@type': 'Answer', 'text': a}} for q, a in FAQ]},
    ]
    return ('<script type="application/ld+json">'
            + json.dumps({'@context': 'https://schema.org', '@graph': graph},
                         ensure_ascii=False, separators=(',', ':'))
            + '</script>')


FAQ_HTML = ''.join(
    f'<div class="qa"><h3>{_html.escape(q)}</h3><p>{_html.escape(a)}</p></div>'
    for q, a in FAQ)

# --------------------------------------------------------------------------
# CSS
# --------------------------------------------------------------------------
CSS = r"""
:root{
  --bg:#000;--fg:#fff;
  --dim:rgba(255,255,255,.78);     /* body copy on black: about 13:1 */
  --soft:rgba(255,255,255,.62);    /* secondary copy: about 7.3:1 */
  --faint:rgba(255,255,255,.50);   /* small caps labels: about 5.3:1, still AA */
  --line:rgba(255,255,255,.16);
  --hair:rgba(255,255,255,.10);
  --panel:rgba(0,0,0,.55);
  --sans:'Satoshi',-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
  --mono:'Space Mono',ui-monospace,SFMono-Regular,Menlo,monospace;
  --sym:'Apple Symbols','Segoe UI Symbol','Noto Sans Symbols2',var(--sans);
}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth;-webkit-text-size-adjust:100%}
body{background:var(--bg);color:var(--fg);font-family:var(--sans);line-height:1.5;
  -webkit-font-smoothing:antialiased;overflow-x:hidden}
.wrap{max-width:1080px;margin:0 auto;padding:0 clamp(18px,5vw,44px)}
.gl{font-family:var(--sym);font-weight:400}
.vh{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;
  clip:rect(0 0 0 0);clip-path:inset(50%);white-space:nowrap;border:0}
a{color:inherit}
:focus-visible{outline:2px solid #fff;outline-offset:2px;border-radius:2px}
.skip{position:absolute;left:-9999px;top:0;z-index:100;background:#fff;color:#000;
  font-family:var(--mono);font-size:12px;padding:10px 16px;text-decoration:none}
.skip:focus{left:8px;top:8px}

/* ---- THE BEAM FIELD ---- */
#beams{position:fixed;inset:0;width:100vw;height:100vh;z-index:-1;pointer-events:none;opacity:.92}
#beams .sm-fan{transform-box:view-box;transform-origin:508px -168px;
  animation:sm-sway 124s ease-in-out infinite alternate}
#beams .sm-ray{opacity:var(--o);
  animation:sm-breathe var(--d) ease-in-out var(--t) infinite alternate}
@keyframes sm-breathe{from{opacity:calc(var(--o) * .38)}to{opacity:calc(var(--o) * 1.35)}}
@keyframes sm-sway{from{transform:rotate(-1.15deg)}to{transform:rotate(1.15deg)}}
@media (prefers-reduced-motion:reduce){
  /* Freeze the art. Never remove it. */
  #beams .sm-fan,#beams .sm-ray{animation:none}
}

/* ---- masthead ---- */
header{position:relative;padding:clamp(38px,7vw,64px) 0 30px;border-bottom:1px solid var(--line)}
.crest{text-align:center}
h1{font-weight:900;font-size:clamp(38px,10.5vw,104px);line-height:1;letter-spacing:-.015em;
  text-transform:uppercase;white-space:nowrap}
h1 a{text-decoration:none}
.subtitle{margin-top:.55em;font-weight:500;font-size:clamp(14px,2.4vw,23px);line-height:1.25}
.subtitle span{display:block}
.tag{margin:20px auto 0;max-width:680px;color:var(--soft);font-size:14.5px}
.tag b{color:var(--fg);font-weight:500}

/* ---- hero ---- */
.hero{margin:28px 0 4px;border:1px solid var(--line);background:var(--panel);
  backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);padding:20px clamp(16px,3.5vw,26px)}
.hero-head{display:flex;flex-wrap:wrap;gap:6px 18px;align-items:baseline;
  padding-bottom:16px;border-bottom:1px solid var(--hair)}
.hero-where{font-weight:700;font-size:clamp(17px,2.6vw,22px);letter-spacing:-.01em}
.hero-when{font-family:var(--mono);font-size:12.5px;letter-spacing:.14em;
  text-transform:uppercase;color:var(--soft)}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:16px}
.stat{min-width:0}
.stat .lbl{font-family:var(--mono);font-size:10px;letter-spacing:.24em;text-transform:uppercase;
  color:var(--faint)}
.stat .val{font-family:var(--mono);font-weight:700;font-size:clamp(18px,4.2vw,30px);
  letter-spacing:.01em;margin-top:7px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.stat .val.small{font-size:clamp(13px,2.6vw,17px);font-weight:400;white-space:normal;color:var(--dim)}
.stat .sub{font-family:var(--mono);font-size:10.5px;color:var(--faint);margin-top:5px;line-height:1.6}

/* ---- controls ---- */
.controls{position:relative;z-index:20;border-bottom:1px solid var(--line);
  background:rgba(0,0,0,.86);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px)}
.panel{padding:18px clamp(18px,5vw,44px)}
.grid3{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:20px 26px;
  align-items:start}
.slabel{display:block;font-family:var(--mono);font-size:10px;letter-spacing:.24em;
  text-transform:uppercase;color:var(--faint);margin-bottom:9px;text-align:center}
.field{position:relative}
.locrow{display:flex;gap:8px}
input[type=text],input[type=date]{flex:1;min-width:0;background:rgba(0,0,0,.35);
  border:1px solid var(--line);border-radius:3px;color:var(--fg);font-family:var(--mono);
  font-size:16px;padding:9px 12px;text-align:center;letter-spacing:.05em}
input[type=text]{text-transform:uppercase}
input[type=text]::placeholder{color:var(--faint);letter-spacing:.12em}
input[type=date]{text-transform:uppercase;color-scheme:dark}
.btn{font-family:var(--mono);font-size:12px;letter-spacing:.14em;text-transform:uppercase;
  color:var(--dim);background:rgba(0,0,0,.35);border:1px solid var(--line);border-radius:3px;
  padding:9px 14px;cursor:pointer;transition:color .12s,border-color .12s}
.btn:hover{color:var(--fg);border-color:var(--soft)}
.btn.icon{flex:0 0 auto;width:44px;display:flex;align-items:center;justify-content:center;padding:0}
.btn.icon svg{display:block}
.daterow{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:8px;align-items:stretch}
.daterow .btn{padding:9px 12px;white-space:nowrap}
.daterow #day-today{grid-column:1/-1}
.daterow input[type=date]{min-width:0;padding:9px 6px;font-size:15px}
#loc-suggest{display:none;position:absolute;top:calc(100% + 4px);left:0;right:0;z-index:30;
  background:rgba(0,0,0,.97);border:1px solid var(--soft);border-radius:3px;max-height:340px;
  overflow-y:auto;text-align:left}
#loc-suggest .ls-item{padding:9px 12px;cursor:pointer;border-bottom:1px solid var(--hair)}
#loc-suggest .ls-item:last-child{border-bottom:none}
#loc-suggest .ls-item:hover,#loc-suggest .ls-item.on{background:rgba(255,255,255,.1)}
#loc-suggest .ls-n{font-family:var(--mono);font-size:12.5px;letter-spacing:.03em}
#loc-suggest .ls-s{font-family:var(--mono);font-size:10.5px;color:var(--faint);margin-top:2px}
.hint{font-family:var(--mono);font-size:10.5px;color:var(--faint);text-align:center;
  margin-top:8px;min-height:14px;line-height:1.6}
/* the moon switch: a real checkbox, styled */
.switch{display:flex;align-items:center;justify-content:center;gap:11px;cursor:pointer;
  font-family:var(--mono);font-size:12px;letter-spacing:.1em;text-transform:uppercase;
  color:var(--dim);padding:9px 4px}
.switch input{position:absolute;opacity:0;width:1px;height:1px}
.track{width:46px;height:24px;border:1px solid var(--line);border-radius:13px;
  background:rgba(0,0,0,.4);position:relative;flex:0 0 auto;
  transition:border-color .14s,background .14s}
.track::after{content:"";position:absolute;top:3px;left:3px;width:16px;height:16px;
  border-radius:50%;background:var(--soft);transition:transform .16s ease,background .16s}
.switch input:checked+.track{background:rgba(255,255,255,.16);border-color:var(--fg)}
.switch input:checked+.track::after{transform:translateX(22px);background:#fff}
.switch input:focus-visible+.track{outline:2px solid #fff;outline-offset:2px}
.switch:hover{color:var(--fg)}
@media (prefers-reduced-motion:reduce){.track,.track::after,.btn{transition:none}}

/* ---- ladder ---- */
main{padding:6px 0 56px;background:rgba(0,0,0,.42);backdrop-filter:blur(3px);
  -webkit-backdrop-filter:blur(3px);min-height:46vh}
.status{font-family:var(--mono);font-size:12px;color:var(--faint);padding:18px 0 2px;
  letter-spacing:.05em;line-height:1.7}
.status.err{color:var(--fg)}
.seo-lead{color:var(--soft);font-size:14px;line-height:1.7;max-width:800px;margin:10px 0 4px}
h2.sec{font-family:var(--mono);font-size:12px;letter-spacing:.26em;text-transform:uppercase;
  color:var(--faint);font-weight:400;padding:28px 0 8px}
table.ladder{width:100%;border-collapse:collapse;table-layout:fixed}
table.ladder thead th{font-family:var(--mono);font-size:10px;letter-spacing:.24em;
  text-transform:uppercase;color:var(--faint);font-weight:400;text-align:left;
  padding:0 0 9px;border-bottom:1px solid var(--line)}
table.ladder thead th:last-child{text-align:right}
table.ladder tbody th{font-weight:500;font-size:15.5px;text-align:left;vertical-align:top;
  padding:14px 12px 14px 0;border-bottom:1px solid var(--hair);width:46%}
table.ladder tbody th .gl{margin-right:8px;color:var(--soft)}
table.ladder td.t{font-family:var(--mono);font-size:15px;text-align:right;vertical-align:top;
  padding:14px 0;border-bottom:1px solid var(--hair);width:54%}
table.ladder td.t .rn{display:block;font-family:var(--sans);font-size:12.5px;line-height:1.55;
  color:var(--soft);margin-top:5px;font-weight:400}
table.ladder td.t .none{color:var(--dim);font-size:13px;letter-spacing:.02em}
table.ladder tr.key th,table.ladder tr.key td.t{background:rgba(255,255,255,.05)}
table.ladder tbody tr:last-child th,table.ladder tbody tr:last-child td{border-bottom:none}

/* ---- moon panel ---- */
#moonpanel{margin-top:30px;border:1px solid var(--line);background:var(--panel);
  backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);padding:20px clamp(16px,3.5vw,26px)}
#moonpanel[hidden]{display:none}
.moonhead{display:flex;gap:18px;align-items:center;flex-wrap:wrap;
  padding-bottom:16px;border-bottom:1px solid var(--hair)}
#moon-disc{flex:0 0 auto;line-height:0}
.moonfacts .big{font-family:var(--mono);font-weight:700;font-size:clamp(19px,4vw,27px)}
.moonfacts .small{font-family:var(--mono);font-size:11.5px;color:var(--soft);margin-top:6px;
  line-height:1.75}

/* ---- FAQ + footer ---- */
.faq{padding:34px clamp(18px,5vw,44px) 52px;border-top:1px solid var(--line);
  background:rgba(0,0,0,.42);backdrop-filter:blur(3px);-webkit-backdrop-filter:blur(3px);
  text-align:center}
.faq h2{font-weight:800;font-size:clamp(20px,3.2vw,29px);letter-spacing:-.01em;margin-bottom:14px}
.faq .lead{color:var(--soft);font-size:14.5px;line-height:1.75;max-width:820px;margin:0 auto 8px}
.faq .qa{border-top:1px solid var(--line);padding:16px 0}
.faq .qa h3{font-size:16.5px;font-weight:600;margin-bottom:7px}
.faq .qa p{color:var(--soft);font-size:14.5px;line-height:1.7;max-width:820px;margin:0 auto}
#foot{text-align:center;padding:30px 16px 74px;border-top:1px solid var(--line);
  background:rgba(0,0,0,.42)}
#foot .foot-nav{display:flex;flex-wrap:wrap;justify-content:center;gap:8px 16px;margin-bottom:9px}
#foot .foot-nav a{font-family:var(--mono);font-size:11px;letter-spacing:.1em;
  text-transform:uppercase;color:var(--soft);text-decoration:none}
#foot .foot-nav a:hover{color:var(--fg)}
#foot .foot-c{font-family:var(--mono);font-size:10px;letter-spacing:.1em;color:var(--faint)}
#foot .foot-e{font-family:var(--mono);font-size:10px;letter-spacing:.05em;color:var(--faint);
  margin-top:8px;line-height:1.75}
body:has(.pt-sfoot) #foot .foot-nav{display:none}  /* the studios chrome owns the nav row */

/* ---- responsive ----
   Phone (<=560): stats stack to one column, the ladder keeps its two columns
     (the note lives under the time, so nothing is hidden and nothing duplicated).
   Foldable / small tablet (~884): the controls grid resolves to two columns at
     minmax(240px), the stats stay three across, the ladder keeps full type.
   Desktop (>=1080): the wrap caps at 1080 and everything breathes. */
@media (max-width:880px){
  .hero-head{gap:4px 14px}
  .stats{gap:12px}
}
@media (max-width:560px){
  .stats{grid-template-columns:1fr;gap:16px}
  .stat .val{font-size:26px}
  table.ladder tbody th{width:52%;font-size:14.5px;padding-right:10px}
  table.ladder td.t{width:48%;font-size:14px}
  table.ladder td.t .rn{font-size:11.5px}
  h1{font-size:clamp(34px,12vw,64px)}
}
@media (max-width:380px){
  table.ladder tbody th{width:50%}
}
"""

# --------------------------------------------------------------------------
# JS - the whole runtime. __B__ is replaced with the mount base at the end.
# Every node is built with real DOM calls. No markup string ever reaches the
# document, so no engine value or geocoder label can be injected as HTML.
# --------------------------------------------------------------------------
JS = r"""
/* SUNMAP page runtime. Owns: state, the worker seam, the geo seam, rendering.
   Owns no astronomy: every number on this page comes from sunmap-worker.js. */
(function () {
  'use strict';
  var B = '__B__', LS = 'sunmap.v1';
  var DEFAULT = {lat:34.0522, lon:-118.2437, alt_m:0, tz:'America/Los_Angeles', label:'Los Angeles, California'};
  /* What the server already rendered into the tables and the hero stats. While the
     request on screen still matches this, the prerendered Swiss values stay put. */
  var PRESET = __PRESET__;
  var LADDER = __LADDER__;
  var GLYPH = {sun:'☉', moon:'☽'};
  var SVGNS = 'http://www.w3.org/2000/svg';

  var state = {loc:null, date:null, moon:false};
  var day = null;      /* the DATA CONTRACT for state.date */
  var prevMoon = null; /* yesterday's moon block, used only to name waxing vs waning */
  var failed = false;  /* the engine has answered with an error, or not at all */
  var worker = null, workerDead = false, seq = 0, pending = {};

  /* ---------------- small DOM helpers ---------------- */
  function el(id) { return document.getElementById(id); }
  function clear(n) { while (n && n.firstChild) n.removeChild(n.firstChild); return n; }
  function mk(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }

  /* ---------------- storage ---------------- */
  function loadState() {
    var s = null;
    try { s = JSON.parse(localStorage.getItem(LS) || 'null'); } catch (e) { s = null; }
    s = s || {};
    state.moon = s.moon === true;
    var L = s.loc;
    state.loc = (L && isFinite(L.lat) && isFinite(L.lon)) ? {
      lat:+L.lat, lon:+L.lon, alt_m:+(L.alt_m || 0) || 0,
      tz:validTz(L.tz) || deviceTz(),
      label:String(L.label || coordLabel(+L.lat, +L.lon))
    } : {lat:DEFAULT.lat, lon:DEFAULT.lon, alt_m:0, tz:DEFAULT.tz, label:DEFAULT.label};
    state.date = todayIn(state.loc.tz);
    lastKey = locKey(state.loc);
  }
  function saveState() {
    try { localStorage.setItem(LS, JSON.stringify({moon:state.moon, loc:state.loc})); } catch (e) {}
  }
  function deviceTz() {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'; } catch (e) { return 'UTC'; }
  }
  function validTz(z) {
    if (!z || typeof z !== 'string') return null;
    try { new Intl.DateTimeFormat('en-US', {timeZone:z}); return z; } catch (e) { return null; }
  }
  function coordLabel(lat, lon) { return lat.toFixed(4) + ', ' + lon.toFixed(4); }

  /* ---------------- dates ---------------- */
  function todayIn(tz) {
    try { return new Date().toLocaleDateString('en-CA', {timeZone:tz}); }
    catch (e) { return new Date().toLocaleDateString('en-CA'); }
  }
  function shiftDate(d, n) {
    var p = d.split('-');
    return new Date(Date.UTC(+p[0], +p[1] - 1, +p[2]) + n * 86400000).toISOString().slice(0, 10);
  }
  function longDate(d) {
    var p = d.split('-');
    return new Date(Date.UTC(+p[0], +p[1] - 1, +p[2])).toLocaleDateString('en-US',
      {timeZone:'UTC', weekday:'long', month:'long', day:'numeric', year:'numeric'});
  }
  function clockOf(ev, tz, bare) {
    var iso = ev && (ev.local || ev.utc);
    if (!iso) return null;
    var t = new Date(iso);
    if (isNaN(t.getTime())) return null;
    var o = {hour:'numeric', minute:'2-digit', second:'2-digit', hour12:true};
    /* The hero tiles omit the zone abbreviation: the zone is already named on the
       line above them and in the status line, and at tile size it only forced an
       ellipsis through the seconds. The ladder keeps it. */
    if (!bare) o.timeZoneName = 'short';
    try { o.timeZone = tz; return t.toLocaleTimeString('en-US', o); }
    catch (e) { delete o.timeZone; return t.toLocaleTimeString('en-US', o); }
  }
  function durOf(s) {
    if (s === null || s === undefined || !isFinite(s)) return null;
    s = Math.round(s);
    return Math.floor(s / 3600) + 'h ' + Math.floor((s % 3600) / 60) + 'm ' + (s % 60) + 's';
  }

  /* Polar day or polar night, from the observer latitude and the solar declination
     of the date. Used ONLY to say WHICH honest thing is happening when the engine
     reports a circumpolar sun. It never produces a time. */
  function polarKind(lat, dstr) {
    var p = dstr.split('-');
    var n = (Date.UTC(+p[0], +p[1] - 1, +p[2]) - Date.UTC(+p[0], 0, 0)) / 86400000;
    var decl = 23.44 * Math.sin(2 * Math.PI * (n - 80.5) / 365.25);
    return ((lat >= 0) === (decl >= 0)) ? 'day' : 'night';
  }
  function obsLat() {
    if (day && day.observer && isFinite(day.observer.lat)) return +day.observer.lat;
    return state.loc.lat;
  }

  /* ---------------- honest empty states ----------------
     The engine's status vocabulary (scripts/solar.py): ok, always_above,
     always_below, none_today, error:<msg>. Each one gets its own sentence. No
     row is ever blank and no time is ever invented. "circumpolar" is the older
     spelling and is still accepted, resolved by declination. */
  var RISESET = {sunrise:1, sunset:1, moonrise:1, moonset:1};
  function noTime(item, ev) {
    var st = ev ? (ev.status || 'unavailable') : 'absent';
    var isMoon = (item.body === 'moon'), rs = !!RISESET[item.key];
    if (st === 'ok') return 'Time unavailable';
    if (st === 'always_above') {
      if (isMoon) return 'None - The moon is circumpolar today and never sets';
      if (rs) return 'None - Polar day, the sun does not set';
      return 'Never reached - The sun stays above this altitude all day';
    }
    if (st === 'always_below') {
      if (isMoon) return 'None - The moon stays below the horizon all day';
      if (rs) return 'None - Polar night, the sun does not rise';
      return 'Never reached - The sun stays below this altitude all day';
    }
    if (st === 'none_today') return 'None on this date';
    if (st === 'not_computed') return 'Not computed at build time - The live engine fills this in';
    if (st === 'circumpolar') {   /* legacy spelling: fall back to declination */
      var kind = polarKind(obsLat(), state.date);
      if (isMoon) return 'None - The moon does not cross the horizon on this date';
      if (rs) return 'None - Polar ' + kind;
      return kind === 'day'
        ? 'Never reached - The sun stays above this altitude all day'
        : 'Never reached - The sun never climbs this high today';
    }
    if (st === 'absent') return 'Not reported for this date';
    if (String(st).indexOf('error') === 0) return 'Not solved - ' + st;
    return 'No time - ' + st;
  }

  /* ---------------- the worker seam ---------------- */
  function bootWorker() {
    if (worker || workerDead) return worker;
    try {
      worker = new Worker(B + 'sunmap-worker.js', {type:'module'});
    } catch (e) {
      workerDead = true;
      fail('The compute engine could not start in this browser' +
        (e && e.message ? ' (' + e.message + ')' : '') +
        '. Nothing below has been recomputed - The times shown are the build-day values for Los Angeles.');
      return null;
    }
    worker.onmessage = function (m) { onEngine(m.data); };
    worker.onerror = function (e) {
      workerDead = true;
      fail('The compute engine failed to load' + (e && e.message ? ' (' + e.message + ')' : '') +
        '. Nothing below has been recomputed.');
    };
    worker.onmessageerror = function () { fail('The compute engine sent a message this page could not read.'); };
    return worker;
  }
  function ask(dateStr, tag) {
    var w = bootWorker();
    if (!w) return;
    var n = ++seq, id = tag + ':' + n;
    pending[id] = {tag:tag, date:dateStr, n:n, t:setTimeout(function () {
      if (!pending[id]) return;
      delete pending[id];
      if (tag === 'main') fail('The engine has not answered. Nothing below is a guess - Reload to try again.');
    }, 20000)};
    try {
      /* Both shapes in one message: the engine reads coords/tz/date, the id and
         the flat mirror cost nothing and keep a simpler worker satisfied. moon is
         always requested so the toggle is instant and never triggers a refetch. */
      w.postMessage({
        type:'day', id:id, date:dateStr, tz:state.loc.tz, moon:true,
        coords:{lat:state.loc.lat, lon:state.loc.lon, alt:state.loc.alt_m || 0},
        lat:state.loc.lat, lon:state.loc.lon, alt_m:state.loc.alt_m || 0
      });
    } catch (e) {
      clearTimeout(pending[id].t); delete pending[id];
      fail('The engine rejected the request: ' + (e && e.message ? e.message : e));
    }
  }
  /* The engine does not echo an id, so a reply is matched on the date it carries;
     an error reply carries neither, and settles the oldest request in flight. */
  function settle(msg, d) {
    var id, best = null, bestId = null;
    if (msg.id && pending[msg.id]) { bestId = msg.id; best = pending[msg.id]; }
    if (!best && d && d.date) {
      for (id in pending) if (pending[id].date === d.date) { bestId = id; best = pending[id]; break; }
    }
    if (!best) {
      for (id in pending) if (!best || pending[id].n < best.n) { bestId = id; best = pending[id]; }
    }
    if (best) { clearTimeout(best.t); delete pending[bestId]; }
    return best;
  }
  /* Accept the DATA CONTRACT in whichever envelope the worker uses. */
  function unwrap(msg) {
    if (!msg || typeof msg !== 'object') return null;
    if (Array.isArray(msg.events) && msg.date) return msg;
    var keys = ['data', 'result', 'day', 'payload'];
    for (var i = 0; i < keys.length; i++) {
      var v = msg[keys[i]];
      if (v && typeof v === 'object' && Array.isArray(v.events)) return v;
    }
    return null;
  }
  function onEngine(msg) {
    if (!msg || typeof msg !== 'object') return;
    var d = unwrap(msg), rec = settle(msg, d);
    var err = msg.error || (msg.ok === false ? (msg.reason || 'unknown engine error') : null);
    if (err) { if (!rec || rec.tag === 'main') fail('Engine error: ' + err); return; }
    if (!d) { if (!rec || rec.tag === 'main') fail('The engine returned a shape this page does not recognise.'); return; }
    var tag = (d.date === state.date) ? 'main' : (rec ? rec.tag : 'prev');
    if (tag === 'prev') { prevMoon = d.moon || null; renderMoon(); return; }
    if (d.date && d.date !== state.date) return;   /* a stale answer for an older request */
    day = d;
    render();
  }

  /* ---------------- the geo seam ---------------- */
  var geo = {search:null, here:null, zone:null, ready:false};
  function bindGeo(mod) {
    var src = mod || {}, d = src['default'], k;
    if (d && typeof d === 'object') {
      var merged = {};
      for (k in src) merged[k] = src[k];
      for (k in d) merged[k] = d[k];
      src = merged;
    }
    function grab(names) {
      for (var i = 0; i < names.length; i++) {
        if (typeof src[names[i]] === 'function') return src[names[i]].bind(src);
      }
      return null;
    }
    geo.search = grab(['search', 'suggest', 'autocomplete', 'geocode', 'lookup', 'query', 'find']);
    geo.searchNow = grab(['suggestNow', 'searchNow', 'geocodeNow']) || geo.search;
    geo.here = grab(['here', 'locate', 'device', 'deviceLocation', 'useDeviceLocation',
                     'currentLocation', 'myLocation', 'ipLocate', 'useIPLocation', 'detect']);
    geo.zone = grab(['timezoneFor', 'tzFor', 'zoneFor', 'nearestZone', 'nearestTimeZone', 'timezone', 'tz']);
    /* If the module can apply a pick itself it owns the harder parts - country
       constrained zone lookup, altitude refinement - so the pick is routed through
       it and the result comes back on the change subscription. */
    geo.pick = grab(['chooseLocation', 'choosePlace', 'choose', 'applyPlace']);
    geo.onChange = grab(['onChange', 'subscribe', 'onLocation']);
    geo.ready = !!(geo.search || geo.here);
    if (geo.onChange) {
      try { geo.onChange(function (loc) { var p = normPlace(loc, true); if (p) choose(p); }); } catch (e) {}
    }
  }
  /* applied=true means this object is a RESOLVED location the geo module emitted
     (from its pick, its device chain, or a later refinement). Its zone is final and
     is trusted as given. applied=false means a raw autocomplete suggestion, whose
     zone may be the module's own nearest-point guess; that one is re-derived with
     the country code in hand, which is the difference between Tromso resolving to
     Europe/Oslo and to Europe/Helsinki 1090 km away. */
  function normPlace(o, applied) {
    if (!o || typeof o !== 'object') return null;
    var lat = +(o.lat !== undefined ? o.lat : o.latitude);
    var lon = +(o.lon !== undefined ? o.lon : (o.lng !== undefined ? o.lng : o.longitude));
    if (!isFinite(lat) || !isFinite(lon)) return null;
    var alt = +(o.alt_m !== undefined ? o.alt_m : (o.alt !== undefined ? o.alt : o.elevation));
    var ownGuess = !applied && (o.tz_source === 'table' || o.source === 'offline');
    return {
      lat:lat, lon:lon, alt_m:isFinite(alt) ? alt : 0,
      tz:ownGuess ? null : validTz(o.tz || o.timezone || o.zone || o.tzid),
      cc:o.cc || o.country_code || null,
      raw:o,
      label:String(o.label || o.name || o.display_name || o.city || coordLabel(lat, lon)),
      sub:String(o.sub || o.detail || o.region || o.description || '')
    };
  }
  function parseCoords(q) {
    var m = String(q).trim().match(/^(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)$/);
    if (!m) return null;
    var lat = parseFloat(m[1]), lon = parseFloat(m[2]);
    if (!isFinite(lat) || !isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
    return {lat:lat, lon:lon, alt_m:0, tz:null, label:coordLabel(lat, lon), sub:'Coordinates'};
  }
  /* Resolves to an array, or to null meaning "a newer query superseded this one" -
     the caller must then leave the list alone rather than clear what is about to
     be filled. That STALE contract is the geo module's, and it is load-bearing. */
  function searchPlaces(q, now) {
    var coord = parseCoords(q);
    if (coord) return Promise.resolve([coord]);
    var fn = now ? geo.searchNow : geo.search;
    if (!fn) return Promise.resolve([]);
    try {
      return Promise.resolve(fn(q)).then(function (r) {
        if (r && r.stale === true) return null;
        var arr = Array.isArray(r) ? r : (r && Array.isArray(r.results) ? r.results : []);
        var out = [];
        for (var i = 0; i < arr.length && out.length < 8; i++) {
          var p = normPlace(arr[i]);
          if (p) out.push(p);
        }
        return out;
      }).catch(function () { return []; });
    } catch (e) { return Promise.resolve([]); }
  }
  function browserLocate() {
    return new Promise(function (res, rej) {
      if (!navigator.geolocation) { rej(new Error('this browser has no location service')); return; }
      navigator.geolocation.getCurrentPosition(function (p) {
        res({lat:p.coords.latitude, lon:p.coords.longitude,
          alt_m:isFinite(p.coords.altitude) ? p.coords.altitude : 0,
          tz:deviceTz(), label:coordLabel(p.coords.latitude, p.coords.longitude), sub:'Your device'});
      }, function (e) { rej(new Error(e && e.message ? e.message : 'location refused')); },
        {enableHighAccuracy:false, timeout:12000, maximumAge:600000});
    });
  }
  function locateHere() {
    if (!geo.here) return browserLocate();
    try {
      return Promise.resolve(geo.here())
        .then(function (r) { return normPlace(r, true) || browserLocate(); })
        .catch(function () { return browserLocate(); });
    } catch (e) { return browserLocate(); }
  }
  function zoneFor(p) {
    if (p.tz) return p.tz;
    if (geo.zone) { try { var z = validTz(geo.zone(p.lat, p.lon, p.cc)); if (z) return z; } catch (e) {} }
    return null;
  }

  /* ---------------- apply a place / a date ---------------- */
  /* One identity per observer. The geo module can emit the same location twice
     (once from the pick, once from the later altitude refinement), so an
     unchanged location must not trigger a second engine round trip. */
  var lastKey = null;
  function locKey(p) {
    return [(+p.lat).toFixed(5), (+p.lon).toFixed(5), Math.round(p.alt_m || 0),
            p.tz || '', p.label || ''].join('|');
  }
  function choose(p) {
    var z = zoneFor(p), guessed = false;
    if (!z) { z = deviceTz(); guessed = true; }
    var next = {lat:p.lat, lon:p.lon, alt_m:p.alt_m || 0, tz:z, label:p.label};
    var k = locKey(next);
    if (k === lastKey) return;
    lastKey = k;
    state.loc = next;
    saveState();
    failed = false;
    hint(guessed
      ? 'Times shown in your device timezone (' + z + ') - The geocoder did not name one for this place'
      : 'Showing ' + p.label + ' in ' + z.replace(/_/g, ' '));
    day = null; prevMoon = null;
    render();
    refresh();
  }
  function setDate(d) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(d)) return;
    state.date = d;
    failed = false;
    var inp = el('date-input');
    if (inp && inp.value !== d) inp.value = d;
    day = null; prevMoon = null;
    render();
    refresh();
  }
  function refresh() {
    ask(state.date, 'main');
    if (state.moon) ask(shiftDate(state.date, -1), 'prev');
  }

  /* ---------------- render ---------------- */
  function fail(msg) {
    var s = el('status');
    if (s) { s.textContent = msg; s.className = 'status err'; }
    failed = true;
    paintTables();   /* pending cells must not sit at "Computing..." forever */
  }
  /* Which state the tables and the hero stats are in.
       pre     - the server-rendered values still describe the request on screen
       live    - the engine has answered for this exact request
       pending - a request is out; show a placeholder, never a stale or invented time
       failed  - no answer; say so in every cell rather than leave a blank */
  function mode() {
    if (day) return 'live';
    if (failed) return 'failed';
    if (state.date === PRESET.date &&
        Math.abs(state.loc.lat - PRESET.lat) < 1e-9 &&
        Math.abs(state.loc.lon - PRESET.lon) < 1e-9) return 'pre';
    return 'pending';
  }
  var WAITING = {pending:'Computing...', failed:'Not computed'};
  function hint(msg) { var h = el('loc-hint'); if (h) h.textContent = msg || ''; }
  /* Every occurrence of a key, in time order. A 25-hour fall-back day can carry a
     twilight crossing twice, and the contract says nothing is ever dropped - so the
     page renders a row per occurrence rather than showing only the first. */
  function evsOf(key) {
    var out = [];
    if (!day || !Array.isArray(day.events)) return out;
    for (var i = 0; i < day.events.length; i++) if (day.events[i].key === key) out.push(day.events[i]);
    if (out.length > 1) {
      /* Nulls last, stated explicitly. The old form padded with a U+FFFF sentinel,
         which is a Unicode noncharacter: legal inside a JS string, but a
         noncharacter-in-input-stream parse error in the HTML byte stream and a hard
         failure for any strict XML or XHTML consumer. Never emit one. */
      out.sort(function (a, b) {
        if (!a.utc) return b.utc ? 1 : 0;
        if (!b.utc) return -1;
        return a.utc < b.utc ? -1 : (a.utc > b.utc ? 1 : 0);
      });
    }
    return out;
  }
  function evOf(key) { return evsOf(key)[0] || null; }
  function itemOf(key) {
    for (var i = 0; i < LADDER.length; i++) if (LADDER[i].key === key) return LADDER[i];
    return {key:key, label:key, body:'sun', note:''};
  }
  function ladderRow(it, ev, waiting, tz, ordinal, total) {
    var t = waiting ? null : clockOf(ev, tz);
    var tr = mk('tr', (it.key === 'sunrise' || it.key === 'sunset' || it.key === 'solar_noon') ? 'key' : '');
    var th = mk('th');
    th.setAttribute('scope', 'row');
    th.appendChild(mk('span', 'gl', GLYPH[it.body])).setAttribute('aria-hidden', 'true');
    th.appendChild(document.createTextNode(it.label));
    var td = mk('td', 't');
    if (t) {
      var tm = mk('time', '', t);
      if (ev && ev.utc) tm.setAttribute('datetime', ev.utc);
      td.appendChild(tm);
    } else {
      td.appendChild(mk('span', 'none', waiting ? WAITING[waiting] : noTime(it, ev)));
    }
    var note = it.note;
    if (total > 1) note += ' Occurrence ' + ordinal + ' of ' + total + ' on this local day.';
    td.appendChild(mk('span', 'rn', note));
    tr.appendChild(th);
    tr.appendChild(td);
    return tr;
  }
  function fillRows(tbodyId, body, waiting) {
    var tb = clear(el(tbodyId));
    var tz = (day && day.tz) || state.loc.tz;
    for (var i = 0; i < LADDER.length; i++) {
      var it = LADDER[i];
      if (it.body !== body) continue;
      var list = waiting ? [] : evsOf(it.key);
      if (list.length < 2) {
        tb.appendChild(ladderRow(it, list[0] || null, waiting, tz, 1, 1));
      } else {
        for (var j = 0; j < list.length; j++) {
          tb.appendChild(ladderRow(it, list[j], waiting, tz, j + 1, list.length));
        }
      }
    }
  }
  function setStat(id, val, small) {
    var n = el(id);
    n.textContent = val;
    n.className = 'val' + (small ? ' small' : '');
  }
  function statFor(key) {
    var it = itemOf(key), ev = evOf(key), t = clockOf(ev, (day && day.tz) || state.loc.tz, true);
    return t ? {val:t, small:false} : {val:noTime(it, ev), small:true};
  }

  function paintTables() {
    var m = mode();
    if (m === 'pre') return;                 /* the server values still stand */
    fillRows('sun-rows', 'sun', m === 'live' ? null : m);
    if (state.moon) fillRows('moon-rows', 'moon', m === 'live' ? null : m);
  }
  function render() {
    var tz = (day && day.tz) || state.loc.tz, m = mode();
    el('hero-where').textContent = state.loc.label;
    el('hero-when').textContent = longDate(state.date) + ' - ' + tz.replace(/_/g, ' ');
    var s = el('status');

    if (m === 'live') {
      var sr = statFor('sunrise'), ss = statFor('sunset');
      setStat('stat-sunrise', sr.val, sr.small);
      setStat('stat-sunset', ss.val, ss.small);
      var dl = durOf(day.day_length_s), rise = evOf('sunrise');
      var st = rise ? rise.status : null;
      if (dl !== null) {
        setStat('stat-daylen', dl, false);
        el('stat-daylen-sub').textContent =
          st === 'always_above' ? 'Polar day - The sun does not set' :
          st === 'always_below' ? 'Polar night - The sun does not rise' :
          'Sunrise to sunset';
      } else {
        var kind = (st === 'circumpolar') ? polarKind(obsLat(), state.date) : null;
        setStat('stat-daylen', kind ? (kind === 'day' ? 'Polar day' : 'Polar night') : 'Not reported', true);
        el('stat-daylen-sub').textContent = kind
          ? (kind === 'day' ? 'The sun does not set on this date' : 'The sun does not rise on this date')
          : 'The engine did not report a day length for this date';
      }
      el('seo-lead').textContent = 'Every solar event of ' + longDate(state.date) + ' at ' +
        state.loc.label + ', computed on your device with the Swiss Ephemeris on JPL DE441 ' +
        'and reported to the second.';
      s.className = 'status';
      s.textContent = 'Solved for ' + (+state.loc.lat).toFixed(4) + ', ' + (+state.loc.lon).toFixed(4) +
        (state.loc.alt_m ? ' at ' + Math.round(state.loc.alt_m) + ' m' : '') +
        ' - Times in ' + tz.replace(/_/g, ' ');
    } else if (m === 'pending') {
      setStat('stat-sunrise', 'Computing...', true);
      setStat('stat-sunset', 'Computing...', true);
      setStat('stat-daylen', 'Computing...', true);
      el('stat-daylen-sub').textContent = 'Sunrise to sunset';
      el('seo-lead').textContent = 'Solving ' + longDate(state.date) + ' at ' + state.loc.label +
        ' on your device. Nothing below is filled in until the engine answers.';
      s.className = 'status';
      s.textContent = 'Computing ' + longDate(state.date) + ' for ' + state.loc.label + '...';
    } else if (m === 'failed') {
      setStat('stat-sunrise', 'Not computed', true);
      setStat('stat-sunset', 'Not computed', true);
      setStat('stat-daylen', 'Not computed', true);
      el('stat-daylen-sub').textContent = 'The engine did not answer';
    }

    paintTables();
    renderMoon();
  }

  function phaseName(pct, waxing) {
    var n;
    if (pct < 1.5) n = 'New moon';
    else if (pct > 98.5) n = 'Full moon';
    else if (Math.abs(pct - 50) < 2.5) n = 'Quarter moon';
    else if (pct < 50) n = 'Crescent';
    else n = 'Gibbous';
    if (n === 'Quarter moon') {
      if (waxing === true) return 'First quarter';
      if (waxing === false) return 'Last quarter';
      return n;
    }
    if (n === 'Crescent' || n === 'Gibbous') {
      if (waxing === true) return 'Waxing ' + n.toLowerCase();
      if (waxing === false) return 'Waning ' + n.toLowerCase();
    }
    return n;
  }
  /* Terminator geometry from the illuminated fraction. Mirrored below the equator,
     because that is what a southern observer actually sees. */
  function moonDisc(k, waxing, south) {
    var R = 27, rx = R * Math.abs(1 - 2 * k);
    var right = (waxing === false) ? false : true;
    if (south) right = !right;
    var limb = right ? 1 : 0;
    var term = (k < 0.5) ? (right ? 1 : 0) : (right ? 0 : 1);
    var svg = document.createElementNS(SVGNS, 'svg');
    svg.setAttribute('width', '62');
    svg.setAttribute('height', '62');
    svg.setAttribute('viewBox', '-31 -31 62 62');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');
    var c = document.createElementNS(SVGNS, 'circle');
    c.setAttribute('r', String(R));
    c.setAttribute('fill', 'none');
    c.setAttribute('stroke', 'rgba(255,255,255,.28)');
    c.setAttribute('stroke-width', '1');
    svg.appendChild(c);
    if (k > 0.004) {
      var p = document.createElementNS(SVGNS, 'path');
      p.setAttribute('d', 'M0 ' + (-R) + ' A' + R + ' ' + R + ' 0 0 ' + limb + ' 0 ' + R +
        ' A' + rx.toFixed(2) + ' ' + R + ' 0 0 ' + term + ' 0 ' + (-R));
      p.setAttribute('fill', '#fff');
      p.setAttribute('opacity', '0.93');
      svg.appendChild(p);
    }
    return svg;
  }
  function renderMoon() {
    var panel = el('moonpanel');
    panel.hidden = !state.moon;
    if (!state.moon) return;
    /* Two distinct things, two distinct names. These were both called m, which
       "worked" only because var redeclaration is an assignment - one reorder and
       the row fill would have read a moon block as a render mode. */
    var md = mode();
    if (md !== 'pre') fillRows('moon-rows', 'moon', md === 'live' ? null : md);
    var facts = clear(el('moon-facts')), disc = clear(el('moon-disc'));
    var m = day && day.moon;
    if (!m || !isFinite(m.illumination_pct)) {
      facts.appendChild(mk('div', 'big', '--'));
      facts.appendChild(mk('div', 'small', day ? 'The engine returned no moon block for this day.' : 'Waiting on the engine.'));
      return;
    }
    var pct = +m.illumination_pct, k = Math.max(0, Math.min(1, pct / 100));
    var waxing = null;
    if (prevMoon && isFinite(prevMoon.illumination_pct)) {
      var delta = pct - prevMoon.illumination_pct;
      if (Math.abs(delta) > 0.05) waxing = delta > 0;
    }
    disc.appendChild(moonDisc(k, waxing, obsLat() < 0));
    facts.appendChild(mk('div', 'big', pct.toFixed(1) + '% illuminated'));
    var bits = ['Phase angle ' + (+m.phase_angle_deg).toFixed(1) + ' deg'];
    if (isFinite(m.apparent_diameter_arcsec)) {
      bits.push('Apparent diameter ' + (+m.apparent_diameter_arcsec).toFixed(0) + ' arcseconds');
    }
    if (waxing === null) bits.push('Waxing or waning is named once the previous day resolves');
    var small = mk('div', 'small', phaseName(pct, waxing));
    small.appendChild(document.createElement('br'));
    small.appendChild(document.createTextNode(bits.join(' - ')));
    facts.appendChild(small);
  }

  /* ---------------- controls ---------------- */
  function wireDate() {
    var inp = el('date-input');
    inp.value = state.date;
    inp.addEventListener('change', function () { if (inp.value) setDate(inp.value); });
    el('day-prev').addEventListener('click', function () { setDate(shiftDate(state.date, -1)); });
    el('day-next').addEventListener('click', function () { setDate(shiftDate(state.date, 1)); });
    el('day-today').addEventListener('click', function () { setDate(todayIn(state.loc.tz)); });
  }
  function wireMoon() {
    var cb = el('moon-toggle');
    cb.checked = state.moon;
    cb.addEventListener('change', function () {
      state.moon = cb.checked;
      saveState();
      renderMoon();
      if (state.moon && !prevMoon) ask(shiftDate(state.date, -1), 'prev');
    });
  }
  function wireLocation() {
    var inp = el('loc-input'), box = el('loc-suggest'), items = [], hot = -1, timer = null, run = 0;

    function close() {
      box.style.display = 'none';
      clear(box);
      items = []; hot = -1;
      inp.setAttribute('aria-expanded', 'false');
      inp.removeAttribute('aria-activedescendant');
    }
    function paint() {
      clear(box);
      if (!items.length) { close(); return; }
      items.forEach(function (it, i) {
        var d = mk('div', 'ls-item' + (i === hot ? ' on' : ''));
        d.id = 'ls-' + i;
        d.setAttribute('role', 'option');
        d.setAttribute('aria-selected', i === hot ? 'true' : 'false');
        d.appendChild(mk('div', 'ls-n', it.label));
        if (it.sub) d.appendChild(mk('div', 'ls-s', it.sub));
        d.addEventListener('mousedown', function (e) { e.preventDefault(); take(it); });
        box.appendChild(d);
      });
      box.style.display = 'block';
      inp.setAttribute('aria-expanded', 'true');
      if (hot >= 0) inp.setAttribute('aria-activedescendant', 'ls-' + hot);
    }
    function take(it) {
      close();
      inp.value = '';
      if (geo.pick) {
        /* chooseLocation() derives the zone with the country in hand and kicks off
           the altitude lookup; the result arrives on the change subscription. Its
           return value is applied too, in case no subscription was bound. */
        try {
          var applied = geo.pick(it.raw || it);
          if (applied) { var q = normPlace(applied, true); if (q) choose(q); }
          return;
        } catch (e) { /* fall through to the direct path */ }
      }
      choose(it);
    }
    function query(q, now) {
      var mine = ++run;
      searchPlaces(q, now).then(function (r) {
        if (mine !== run || r === null) return;   /* superseded: leave the list alone */
        items = r; hot = r.length ? 0 : -1;
        paint();
        if (!r.length) {
          hint(geo.search ? 'No match - Try a city, a postal code, or "lat, lon"'
                          : 'Place search is unavailable - Type coordinates as "34.05, -118.24"');
        }
      });
    }
    inp.addEventListener('input', function () {
      var q = inp.value.trim();
      clearTimeout(timer);
      if (q.length < 2) { close(); return; }
      timer = setTimeout(function () { query(q); }, 120);
    });
    inp.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { close(); return; }
      if (e.key === 'ArrowDown' && items.length) { e.preventDefault(); hot = (hot + 1) % items.length; paint(); return; }
      if (e.key === 'ArrowUp' && items.length) { e.preventDefault(); hot = (hot - 1 + items.length) % items.length; paint(); return; }
      if (e.key === 'Enter') {
        e.preventDefault();
        if (hot >= 0 && items[hot]) { take(items[hot]); return; }
        var c = parseCoords(inp.value);
        if (c) { take(c); return; }
        if (inp.value.trim().length >= 2) query(inp.value.trim(), true);
      }
    });
    inp.addEventListener('blur', function () { setTimeout(close, 140); });
    el('loc-here').addEventListener('click', function () {
      hint('Locating...');
      locateHere().then(function (p) {
        var q = normPlace(p, true);
        if (!q) { hint('Could not read a position'); return; }
        choose(q);
      }).catch(function (e) {
        hint('Location unavailable - ' + (e && e.message ? e.message : 'refused'));
      });
    });
  }

  /* ---------------- boot ---------------- */
  loadState();
  wireDate(); wireMoon(); wireLocation();
  render();
  refresh();
  import(B + 'sunmap-geo.js')
    .then(function (m) {
      bindGeo(m);
      if (!geo.search) hint('Type coordinates as "34.05, -118.24", or use the locate button');
    })
    .catch(function () {
      hint('Place search is offline - Type coordinates as "34.05, -118.24", or use the locate button');
    });
})();
"""

# --------------------------------------------------------------------------
# The page
# --------------------------------------------------------------------------
LADDER_JSON = json.dumps(
    [{'key': k, 'label': l, 'body': b, 'note': n} for k, l, b, n in LADDER],
    ensure_ascii=False, separators=(',', ':'))

PRESET_JSON = json.dumps({'date': BUILD_DAY.isoformat(),
                          'lat': DEFAULT_LOC['lat'], 'lon': DEFAULT_LOC['lon'],
                          'label': DEFAULT_LOC['label']},
                         ensure_ascii=False, separators=(',', ':'))

# The ladder and the prerender descriptor are baked into the runtime BEFORE the
# runtime is baked into the page: the single longest-key-first pass below cannot
# reach a placeholder that only appears inside a value substituted later. __B__ is
# shorter than __JS__ and so still resolves in the main pass.
JS = JS.replace('__LADDER__', LADDER_JSON).replace('__PRESET__', PRESET_JSON)

ROBOTS = ('' if IS_PROD else
          '\n<meta name="robots" content="noindex,nofollow">'
          '<!-- demo build: prod is the only indexable host -->')

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>__TITLE__</title>
<meta name="description" content="__DESC__">
<meta name="keywords" content="__KEYWORDS__">
<meta name="author" content="PUDDY Inc.">__ROBOTS__
<link rel="canonical" href="__CANONICAL__">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Puddy Studios">
<meta property="og:title" content="__TITLE__">
<meta property="og:description" content="__OGDESC__">
<meta property="og:url" content="__PAGEURL__">
<meta property="og:image" content="__OGIMG__">
<meta property="og:image:width" content="2400">
<meta property="og:image:height" content="1260">
<meta property="og:image:alt" content="__OGALT__">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:site" content="@cubedivision">
<meta name="twitter:title" content="__TITLE__">
<meta name="twitter:description" content="__OGDESC__">
<meta name="twitter:image" content="__OGIMG__">
<meta name="twitter:image:alt" content="__OGALT__">
<meta name="theme-color" content="#000000">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black">
<meta name="apple-mobile-web-app-title" content="SUNMAP">
<link rel="icon" type="image/svg+xml" sizes="any" href="__B__favicon.svg">
<link rel="icon" type="image/x-icon" href="__B__favicon.ico">
<link rel="apple-touch-icon" href="__B__icons/icon-180.png">
__JSONLD__
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<!-- Query separators are escaped and the brackets percent-encoded. A bare ampersand
     followed by letters and an equals sign is an ambiguous ampersand in an attribute:
     an HTML5 parse error and a W3C validator failure. Both URLs resolve identically
     (verified 200, byte-identical response, against both endpoints). -->
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&amp;display=swap" rel="stylesheet">
<link href="https://api.fontshare.com/v2/css?f%5B%5D=satoshi@400,500,700,900&amp;display=swap" rel="stylesheet">
<script src="__B__puddy-tools.js?v=15" data-nav="studios" defer></script>
<style>__CSS__</style>
</head>
<body>
<a class="skip" href="#ladder">Skip to the day's times</a>

<!-- THE BEAM FIELD. Geometry generated in scripts/render_page.py, animated in CSS,
     frozen (not removed) under prefers-reduced-motion. No external asset, no library. -->
<svg id="beams" viewBox="0 0 1000 1000" preserveAspectRatio="xMidYMid slice"
     aria-hidden="true" focusable="false" role="presentation">
  <defs>__BEAM_DEFS__</defs>
  <g class="sm-fan">__BEAM_BODY__</g>
</svg>

<header>
  <div class="wrap">
    <div class="crest">
      <h1><a href="__B__" aria-label="SUNMAP home">SUNMAP</a></h1>
      <p class="subtitle"><span>The Whole Day of Light</span> <span>Solved to the Second</span></p>
    </div>
    <div class="hero">
      <div class="hero-head">
        <h2 class="hero-where" id="hero-where">__PRE_PLACE__</h2>
        <p class="hero-when" id="hero-when">__PRE_WHEN__</p>
      </div>
      <div class="stats">
        <div class="stat"><div class="lbl">Sunrise</div>
          <div class="val" id="stat-sunrise">__PRE_SUNRISE__</div>
          <div class="sub">Upper limb clears the horizon</div></div>
        <div class="stat"><div class="lbl">Sunset</div>
          <div class="val" id="stat-sunset">__PRE_SUNSET__</div>
          <div class="sub">Upper limb touches the horizon</div></div>
        <div class="stat"><div class="lbl">Day length</div>
          <div class="val" id="stat-daylen">__PRE_DAYLEN__</div>
          <div class="sub" id="stat-daylen-sub">Sunrise to sunset</div></div>
      </div>
    </div>
    <p class="tag"><b>Swiss Ephemeris 2.10.03</b> on the JPL DE441 ephemeris, run on your device. Topocentric: your latitude, your longitude, your altitude.</p>
  </div>
</header>

<nav class="controls" aria-label="Location, date and display controls">
  <div class="panel wrap">
    <div class="grid3">
      <div>
        <label class="slabel" for="loc-input">Location</label>
        <div class="field">
          <div class="locrow">
            <input type="text" id="loc-input" placeholder="CITY, ZIP OR LAT, LON" autocomplete="off"
                   role="combobox" aria-expanded="false" aria-controls="loc-suggest" aria-autocomplete="list">
            <button type="button" class="btn icon" id="loc-here" aria-label="Use my device location" title="Use my device location">
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="6"/><line x1="12" y1="1.5" x2="12" y2="5"/><line x1="12" y1="19" x2="12" y2="22.5"/><line x1="1.5" y1="12" x2="5" y2="12"/><line x1="19" y1="12" x2="22.5" y2="12"/></svg>
            </button>
          </div>
          <div id="loc-suggest" role="listbox" aria-label="Location suggestions"></div>
        </div>
        <p class="hint" id="loc-hint"></p>
      </div>
      <div>
        <label class="slabel" for="date-input">Date</label>
        <div class="daterow">
          <button type="button" class="btn" id="day-prev" aria-label="Previous day">&#8592;</button>
          <input type="date" id="date-input" value="__PRE_DATE__" aria-label="Choose a date">
          <button type="button" class="btn" id="day-next" aria-label="Next day">&#8594;</button>
          <button type="button" class="btn" id="day-today">Back to today</button>
        </div>
        <p class="hint">Any date, any place on Earth.</p>
      </div>
      <div>
        <span class="slabel" id="moon-label">Moon events</span>
        <label class="switch" for="moon-toggle">
          <input type="checkbox" id="moon-toggle" aria-describedby="moon-hint">
          <span class="track" aria-hidden="true"></span>
          <span>Show the moon</span>
        </label>
        <p class="hint" id="moon-hint">Adds moonrise, moonset, the lunar transits and the phase panel.</p>
      </div>
    </div>
  </div>
</nav>

<main class="wrap">
  <p class="status" id="status" role="status" aria-live="polite">__PRE_STATUS__</p>
  <section id="ladder" aria-labelledby="sun-h">
    <h2 class="sec" id="sun-h">The sun</h2>
    <p class="seo-lead" id="seo-lead">__PRE_LEAD__</p>
    <table class="ladder">
      <caption class="vh">Solar events for the selected day, in order through the day</caption>
      <thead><tr><th scope="col">Event</th><th scope="col">Local time</th></tr></thead>
      <tbody id="sun-rows">__PRE_SUN_ROWS__</tbody>
    </table>
  </section>

  <section id="moonpanel" aria-labelledby="moon-h" hidden>
    <h2 class="sec" id="moon-h" style="padding-top:0">The moon</h2>
    <div class="moonhead">
      <div id="moon-disc"></div>
      <div class="moonfacts" id="moon-facts"><div class="big">--</div><div class="small">Waiting on the engine.</div></div>
    </div>
    <table class="ladder">
      <caption class="vh">Lunar events for the selected day</caption>
      <thead><tr><th scope="col">Event</th><th scope="col">Local time</th></tr></thead>
      <tbody id="moon-rows">__PRE_MOON_ROWS__</tbody>
    </table>
  </section>
</main>

<section class="faq" aria-labelledby="faq-h">
  <h2 id="faq-h">Sun times, golden hour and twilight - Frequently asked questions</h2>
  <p class="lead">SUNMAP is the daily half of the engine that runs STARMAP: the Swiss Ephemeris on JPL DE441, solved topocentrically for one observer on one patch of ground.</p>
  __FAQ_HTML__
</section>

<footer id="foot">
  <nav class="foot-nav" aria-label="Puddy Studios">
    <a href="https://puddystudios.com/about">About</a>
    <a href="https://puddystudios.com/contact">Contact</a>
    <a href="https://puddystudios.com/privacy">Privacy</a>
    <a href="https://puddystudios.com/terms">Terms</a>
    <a href="https://starmap.puddystudios.com/">Starmap</a>
  </nav>
  <p class="foot-c">&copy; 2026 PUDDY INC. - ALL RIGHTS RESERVED</p>
  <p class="foot-e">Engine: Swiss Ephemeris 2.10.03 on JPL DE441, unmodified, under its AGPL option. SUNMAP is free software under the GNU AGPL v3.0 or later.</p>
</footer>

<script>__JS__</script>
</body>
</html>
"""

REPL = {
    '__BEAM_DEFS__': BEAM_DEFS,
    '__BEAM_BODY__': BEAM_BODY,
    '__PRE_SUN_ROWS__': PRE_SUN_ROWS,
    '__PRE_MOON_ROWS__': PRE_MOON_ROWS,
    '__PRE_SUNRISE__': PRE_SUNRISE or 'No sunrise',
    '__PRE_SUNSET__': PRE_SUNSET or 'No sunset',
    '__PRE_DAYLEN__': PRE_DAYLEN or 'Not defined',
    '__PRE_STATUS__': _html.escape(PRE_ENGINE_NOTE),
    '__PRE_PLACE__': _html.escape(DEFAULT_LOC['label']),
    '__PRE_WHEN__': _html.escape(_long_date(BUILD_DAY) + ' - ' + DEFAULT_LOC['tz'].replace('_', ' ')),
    '__PRE_DATE__': BUILD_DAY.isoformat(),
    '__PRE_LEAD__': _html.escape(
        'Every solar event of ' + _long_date(BUILD_DAY) + ' at ' + DEFAULT_LOC['label'] +
        ', from astronomical dawn through solar midnight. Choose your own location and date '
        'above and the page recomputes on your device.'),
    '__CANONICAL__': PROD,      # canonical is the prod host, always
    '__PAGEURL__': SITE,
    '__KEYWORDS__': KEYWORDS,
    '__FAQ_HTML__': FAQ_HTML,
    '__JSONLD__': _jsonld(),
    '__ROBOTS__': ROBOTS,
    '__OGDESC__': OG_DESC,
    '__TITLE__': TITLE,
    '__OGIMG__': OG_IMG,
    '__OGALT__': OG_ALT,
    '__DESC__': DESC,
    '__CSS__': CSS,
    '__JS__': JS,
    '__B__': BASE,
}


def build():
    out = HTML
    for k in sorted(REPL, key=len, reverse=True):
        out = out.replace(k, REPL[k])
    left = [k for k in REPL if k in out]
    if left:
        raise SystemExit('unsubstituted placeholder(s): ' + ', '.join(sorted(left)))
    return out


if __name__ == '__main__':
    page = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page, encoding='utf-8')
    print(f'wrote {OUT}  {len(page.encode("utf-8")):,} bytes')
    print(f'  base={BASE}  site={SITE}  canonical={PROD}  indexable={IS_PROD}')
    print(f'  beams={N_BEAMS}  prerender={PRE["date"]} {DEFAULT_LOC["label"]} via '
          f'{"Swiss Ephemeris (solar.py)" if PRE_SWISS else "NOAA fallback"}  '
          f'events={len(PRE["events"])}')
