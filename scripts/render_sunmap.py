#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 PUDDY Inc. <legal@puddystudios.com>
"""SUPERSEDED - do not run. The SUNMAP generator is scripts/render.py.

This file is kept only as history. It is the last place in the tree that still
carries the invented sun-yellow the PUDDY canon rejects, and its own Usage block
below still calls itself the prod build - so running it would overwrite the page
with off-canon colour. The guard immediately after this docstring makes that
impossible. Recommend deleting the file outright; nothing imports it.

--- original header follows ---

SUNMAP page generator - a structural fork of STARMAP.

STARMAP maps the year. SUNMAP maps the day. They are the same product family,
so they are the same page: same chrome, same crest, same next-event card, same
control panel, same three-column event row, same type scale. The CSS in
style/base.css is STARMAP's, forked verbatim.

Two things change, and only two:
  1. The field behind the header is BEAMS, not stars.
  2. The crest emblem is a radiant sun, not the constellation mandala.

Everything else that differs is data: a day instead of a year, a solar ladder
instead of a zodiac, a next-event countdown that ticks toward sunset instead of
toward an ingress.

Usage:
  python3 render_sunmap.py                                        # prod build
  python3 render_sunmap.py --site https://sunmap.puddy.dev/       # demo build
"""
import sys

sys.exit(
    'render_sunmap.py is SUPERSEDED and will not run.\n'
    'It emits the pre-canon palette, including the invented sun-yellow.\n'
    'The SUNMAP generator is scripts/render.py - use:\n'
    '  python3 scripts/render.py\n'
)

import argparse
import json
import math
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
PROD = "https://sunmap.puddystudios.com/"

_ap = argparse.ArgumentParser()
_ap.add_argument("--base", default="/", help="URL mount")
_ap.add_argument("--site", default=PROD, help="origin this build is served from")
_ap.add_argument("--out", default=None, help="output path (default ../index.html)")
_args = _ap.parse_args()

BASE = _args.base if _args.base.endswith("/") else _args.base + "/"
SITE = _args.site if _args.site.endswith("/") else _args.site + "/"
INDEXABLE = SITE == PROD
OUT = Path(_args.out) if _args.out else (ROOT / "index.html")

DEFAULT = {"lat": 34.0522, "lon": -118.2437, "alt": 0.0,
           "tz": "America/Los_Angeles",
           "label": "Los Angeles, California, United States"}

# ---------------------------------------------------------------- the beams --
# Generated, not drawn. A fan of tapered wedges from a point above the frame,
# the same way STARMAP generates its mandala from ring geometry rather than
# hand-placing nodes.

def wedge(angle_deg, half_width_deg, length, ox, oy):
    r = math.radians
    a1, a2 = r(angle_deg - half_width_deg), r(angle_deg + half_width_deg)
    x1, y1 = ox + math.sin(a1) * length, oy + math.cos(a1) * length
    x2, y2 = ox + math.sin(a2) * length, oy + math.cos(a2) * length
    return f"M{ox:.0f},{oy:.0f} L{x1:.1f},{y1:.1f} L{x2:.1f},{y2:.1f} Z"


def beam_field():
    """The header field. One animated group, not N animated rays - a fixed
    full-viewport layer with dozens of independently animated children is what
    broke painting on 2026-08-10."""
    ox, oy, n = 500.0, -120.0, 17
    out = []
    for i in range(n):
        t = i / (n - 1)
        ang = -62 + t * 124 + math.sin(i * 2.399) * 3.2
        half = 2.4 + ((i * 37) % 11) * 0.55
        length = 1500 + ((i * 53) % 17) * 30
        op = 0.10 + 0.30 * (1 - abs(t - 0.5) * 2)
        out.append(f'<path d="{wedge(ang, half, length, ox, oy)}" '
                   f'fill="url(#sm-beam)" opacity="{op:.3f}"/>')
    return ("<svg id=\"beams\" aria-hidden=\"true\" viewBox=\"0 0 1000 1000\" "
            "preserveAspectRatio=\"xMidYMin slice\">"
            "<defs><linearGradient id=\"sm-beam\" x1=\"0\" y1=\"0\" x2=\"0\" y2=\"1\">"
            "<stop offset=\"0%\" stop-color=\"#f6c667\" stop-opacity=\".20\"/>"
            "<stop offset=\"48%\" stop-color=\"#c2801f\" stop-opacity=\".05\"/>"
            "<stop offset=\"100%\" stop-color=\"#000\" stop-opacity=\"0\"/>"
            "</linearGradient>"
            "<radialGradient id=\"sm-halo\" cx=\"50%\" cy=\"0%\" r=\"58%\">"
            "<stop offset=\"0%\" stop-color=\"#f6c667\" stop-opacity=\".13\"/>"
            "<stop offset=\"100%\" stop-color=\"#000\" stop-opacity=\"0\"/>"
            "</radialGradient></defs>"
            "<rect width=\"1000\" height=\"1000\" fill=\"url(#sm-halo)\"/>"
            f"<g class=\"sm-fan\">{''.join(out)}</g></svg>")


def crest_emblem():
    """The inline emblem under the wordmark - STARMAP has its mandala here, so
    SUNMAP has a sun: a disc, a corona of rays, and two orbit rings."""
    p = []
    for i in range(24):
        a = math.radians(i * 15)
        long_ray = (i % 2 == 0)
        r0, r1 = 47, (74 if long_ray else 62)
        x0, y0 = 90 + math.sin(a) * r0, 90 - math.cos(a) * r0
        x1, y1 = 90 + math.sin(a) * r1, 90 - math.cos(a) * r1
        p.append(f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y1:.1f}" '
                 f'stroke-width="{2.1 if long_ray else 1.2}"/>')
    return ('<svg class="emblem" viewBox="0 0 180 180" role="img" '
            'aria-label="SUNMAP emblem - a sun with a corona of rays">'
            '<g stroke="currentColor" fill="none" stroke-linecap="round">'
            f'{"".join(p)}'
            '<circle cx="90" cy="90" r="33" stroke-width="1.6"/>'
            '<circle cx="90" cy="90" r="24" stroke-width="1" opacity=".55"/>'
            '<circle cx="90" cy="90" r="82" stroke-width=".7" opacity=".28"/>'
            '</g><circle cx="90" cy="90" r="15" fill="currentColor"/></svg>')


# ------------------------------------------------------- prerendered content --
# A crawler and a no-JS reader must see a real day, not an empty shell. Computed
# by the same engine the browser runs.

def prerender():
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import solar  # noqa: E402
        day = datetime.now(ZoneInfo(DEFAULT["tz"])).date()
        data = solar.day_events(DEFAULT["lat"], DEFAULT["lon"], DEFAULT["alt"],
                                day, DEFAULT["tz"])
    except Exception as exc:  # noqa: BLE001 - surfaced, never silently skipped
        print(f"  WARNING: prerender failed ({exc}); shipping an empty shell",
              file=sys.stderr)
        return "", None
    rows = []
    for e in data["events"]:
        if e["body"] != "sun":
            continue
        if e["local"]:
            t = datetime.fromisoformat(e["local"])
            when = t.strftime("%-I:%M:%S %p")
        else:
            when = "None"
        rows.append(
            f'<div class="ev"><div><div class="d">{when}</div>'
            f'<div class="t">{data["tz"].split("/")[-1].replace("_", " ")}</div></div>'
            f'<div><div class="title">&#9737; {e["label"]}</div>'
            f'<div class="sub">{e["status"] if not e["local"] else ""}</div></div>'
            f'<div class="meta"><span class="badge">SUN</span></div></div>')
    head = (f'<div class="month">{day.strftime("%A, %B %-d, %Y")} '
            f'- {DEFAULT["label"]}</div>')
    return head + "".join(rows), data


PRERENDER, PRE_DATA = prerender()

CSS = (ROOT / "style" / "base.css").read_text()

SUNMAP_CSS = """
/* ---- SUNMAP deltas on the forked STARMAP sheet ---- */
:root{--sun:#f6c667;--moon:#b6c0ce}
html{background:var(--bg)}
.skip{position:absolute;left:-9999px;top:0;z-index:100;background:#fff;color:#000;
  font-family:var(--mono);font-size:12px;padding:10px 16px;text-decoration:none}
.skip:focus{left:8px;top:8px}
/* The field sits at 0 and content is lifted to 1. A fixed full-viewport layer
   at z-index -1 stops content above it repainting in Chrome - verified
   2026-08-10, the event ladder rendered one row and left the page black. */
#beams{position:absolute;inset:0;width:100%;height:100%;z-index:0;pointer-events:none;opacity:.34}
#beams .sm-fan{transform-box:view-box;transform-origin:500px -120px;
  animation:sm-sway 90s ease-in-out infinite alternate}
@keyframes sm-sway{from{transform:rotate(-1.4deg)}to{transform:rotate(1.4deg)}}
@media (prefers-reduced-motion:reduce){#beams .sm-fan{animation:none}}
header{position:relative;overflow:hidden;padding-bottom:34px}
header .wrap{position:relative;z-index:1}
main,.controls,.moonnote,footer{position:relative;z-index:1}
.emblem{width:clamp(128px,20vw,190px);height:auto;color:var(--sun);
  display:block;margin:14px auto 16px;opacity:.95}
.daynav{font-family:var(--mono);font-size:13px;letter-spacing:.14em;
  margin-top:16px;color:var(--faint)}
.dn-spread{display:flex;justify-content:center;align-items:center;gap:14px;margin-top:9px}
.dn-spread a,.dn-spread button{color:var(--dim);text-decoration:none;background:none;
  border:0;font:inherit;letter-spacing:inherit;cursor:pointer;padding:4px 6px}
.dn-spread a:hover,.dn-spread button:hover{color:var(--fg)}
.dn-spread .dnow{color:var(--fg);border:1px solid var(--line);padding:4px 12px;border-radius:3px}
.ev .d{font-family:var(--mono);font-weight:700;font-size:16px;letter-spacing:.02em;
  color:var(--fg);white-space:nowrap}
.ev .t{font-family:var(--mono);font-size:11px;letter-spacing:.16em;color:var(--faint);
  text-transform:uppercase;margin-top:3px}
.ev.is-sun .d{color:var(--sun)}
.ev.is-moon .d{color:var(--moon)}
.ev.is-none .d{color:var(--faint);font-weight:400;font-size:13px}
.ev .gl{color:var(--sun)}
.ev.is-moon .gl{color:var(--moon)}
#err{margin:14px 0;padding:12px 14px;border:1px solid rgba(255,90,90,.4);
  background:rgba(60,10,10,.5);color:#ff9a9a;font-size:13px;border-radius:4px}
#err:empty{display:none;margin:0;padding:0;border:0}
"""

ROBOTS = ("" if INDEXABLE else
          '\n<meta name="robots" content="noindex,nofollow">'
          '<!-- demo build: prod is the only indexable host -->')

TITLE = "SUNMAP | Sunrise, Sunset and Golden Hour - Solved to the Second"
DESC = ("Every solar and lunar moment of your day, solved to the second for your "
        "exact location on the Swiss Ephemeris. Sunrise, sunset, solar noon, the "
        "full twilight ladder, golden hour and the Moon, computed on your device.")

JSONLD = json.dumps({
    "@context": "https://schema.org", "@type": "WebApplication", "name": "SUNMAP",
    "url": PROD, "applicationCategory": "ReferenceApplication", "operatingSystem": "Any",
    "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
    "description": DESC,
    "publisher": {"@type": "Organization", "name": "PUDDY Inc.",
                  "url": "https://puddystudios.com/"},
}, separators=(",", ":"))

HTML = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{TITLE}</title>
<meta name="description" content="{DESC}">
<link rel="canonical" href="{PROD}">{ROBOTS}
<meta property="og:type" content="website">
<meta property="og:site_name" content="Puddy Studios">
<meta property="og:title" content="{TITLE}">
<meta property="og:description" content="{DESC}">
<meta property="og:url" content="{PROD}">
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#000000">
<link rel="icon" href="{BASE}favicon.svg" type="image/svg+xml">
<style>{CSS}{SUNMAP_CSS}</style>
</head>
<body>
<a class="skip" href="#day">Skip to the day</a>

<header>
{beam_field()}
  <div class="wrap">
    <div class="crest">
      <h1><a class="wm" href="{BASE}" aria-label="SUNMAP home - today">Sunmap</a></h1>
      {crest_emblem()}
      <h2 class="subtitle"><span>Every Sunrise and Sunset</span>
        <span>Solved to the Second</span></h2>
      <nav class="daynav" aria-label="Browse days">
        <div class="dn-spread">
          <button type="button" id="day-prev" aria-label="Previous day">&laquo; Prev</button>
          <span class="dnow" id="day-now">-</span>
          <button type="button" id="day-next" aria-label="Next day">Next &raquo;</button>
        </div>
        <div class="dn-spread">
          <button type="button" id="day-today">Back to today</button>
          <input type="date" id="day-pick" aria-label="Choose a date">
        </div>
      </nav>
    </div>

    <div class="next" id="next">
      <div>
        <div class="lbl">Next event</div>
        <div class="name" id="next-name">-</div>
        <div class="when" id="next-when">-</div>
      </div>
      <div class="count" id="count">--:--:--<small id="count-lbl">until next</small></div>
    </div>

    <p class="tag"><b>Swiss Ephemeris (DE441)</b> resolves every rise, set and twilight to the second.</p>
    <p class="tag">Every instant is <b>topocentric</b> - true for your coordinates and your altitude, not a city centre.</p>
    <p class="tag">Where the sun never rises or never sets, we <b>say so</b>. We never invent a time.</p>
  </div>
</header>

<div class="moonnote"><div class="wrap" id="moonnote">Solving your sky...</div></div>

<nav class="controls" aria-label="Display controls"><div class="panel wrap">
  <div class="section">
    <div class="slabel">Show events (tap to add or remove)</div>
    <div class="seg" id="cats"></div>
  </div>
  <div class="section loc-section">
    <div class="slabel">Your location</div>
    <div class="locwrap">
      <div class="locrow">
        <input id="loc-search" placeholder="CHOOSE YOUR LOCATION" autocomplete="off"
               role="combobox" aria-expanded="false" aria-label="Search for a place">
        <button type="button" id="loc-here" aria-label="Use my location">&#9678;</button>
      </div>
      <ul id="loc-suggest" role="listbox" aria-label="Places"></ul>
    </div>
    <div class="tzactive">Showing the day for <b id="loc-active">{DEFAULT["label"]}</b></div>
  </div>
</div></nav>

<main class="wrap" id="day">
  <div id="err" role="alert"></div>
  <div id="list">{PRERENDER}</div>
</main>

<footer><div class="wrap">
  <nav aria-label="Footer">
    <a href="https://puddystudios.com/about">ABOUT</a>
    <a href="https://puddystudios.com/contact">CONTACT</a>
    <a href="https://puddystudios.com/privacy">PRIVACY</a>
    <a href="https://puddystudios.com/terms">TERMS</a>
    <a href="https://starmap.puddystudios.com/">STARMAP</a>
  </nav>
  <p>&copy; 2026 PUDDY INC. - ALL RIGHTS RESERVED</p>
  <p class="eng">Engine: Swiss Ephemeris 2.10.03 on JPL DE441, unmodified, under its
     AGPL option. SUNMAP is free software under the GNU AGPL v3.0 or later.</p>
</div></footer>

<script type="application/ld+json">{JSONLD}</script>
<script src="{BASE}puddy-tools.js?v=15" defer></script>
<script type="module" src="{BASE}sunmap-app.js"></script>
</body>
</html>
"""

OUT.write_text(HTML)
n_pre = PRERENDER.count('class="ev"')
print(f"wrote {OUT}  {len(HTML):,} bytes")
print(f"  base={BASE}  site={SITE}  canonical={PROD}  indexable={INDEXABLE}")
print(f"  crest emblem + beam field generated; prerendered rows={n_pre}")
