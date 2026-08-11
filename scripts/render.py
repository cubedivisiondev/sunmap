#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 PUDDY Inc. <legal@puddystudios.com>
"""Render the Sunmap shell (one page) + PWA files.

A LITERAL FORK of star_map/scripts/render.py. The page skeleton, the entire
<style> block, the three-column event row, the controls panel, the crest, the
countdown card, the FAQ, the JSON-LD, the PWA emission and the --base/--site
flag handling are STARMAP's, unchanged. Only the VALUES differ: STARMAP lists a
year of geocentric ingresses, SUNMAP lists one day of topocentric solar and
lunar events for the observer standing there.

Computed parts injected per page: __SIGIL_BODY__ (21-node radiant sun),
__PRERENDER_LIST__ (crawlable day ladder), __FAQ_HTML__, __JSONLD__, day nav,
and the engine-derived ladder tables the page script reads.

Mount point is baked at render time via --base ('/' for the sunmap subdomains).
--site sets the canonical/OG origin (always the PROD home; dev stays noindex
via the CloudFront header).

Also emits manifest.json, sw.js, sitemap.xml, robots.txt, 404.html and
source.html (the AGPL-3.0 corresponding-source offer the worker header points
at - serving the page without it is a licence violation, not a nicety).

WHERE THE DATA COMES FROM
  build time  scripts/solar.py  -> the prerendered crawlable ladder + the FAQ,
              computed for the DEFAULT observer (New York City, the tzdata
              principal point sunmap-geo.js also defaults to) on --date.
  run time    sunmap-worker.js  -> the same JSON shape, recomputed on the
              device for the visitor's own coordinates, elevation and day.
  The two are interchangeable by contract, so the JS list hydrates straight
  over the prerendered one.

CORRECTNESS
  An event that does not occur carries no time. It renders an honest
  "None - ..." with the reason. No time is ever invented, at build time or in
  the browser.

ONE DELIBERATE DEPARTURE FROM THE PARENT
  STARMAP assembles its list, chips and note bar with innerHTML. SUNMAP builds
  the IDENTICAL markup with createElement + textContent, because its data layer
  carries third-party text: sunmap-geo.js states in its own contract that place
  names originate in OpenStreetMap, are user-editable, and must be rendered with
  textContent. Same classes, same nesting, same rendered DOM - safer
  construction.

CANONICAL IS ALWAYS PROD
  Every canonical, og:url and JSON-LD @id points at sunmap.puddystudios.com no
  matter which host the build is served from, and any build whose --site is not
  prod also gets <meta name="robots" content="noindex,nofollow"> and a
  Disallow-all robots.txt. The demo host must never compete with prod in the
  index, and must never self-canonicalize. Only --og-site follows the build host,
  so a dev link preview still resolves while prod is dark.

Usage:
  python3 render.py --date 2026-12-21                  # a specific day
  # PROD:
  python3 render.py --base / --site https://sunmap.puddystudios.com/
  # DEV (noindex meta + Disallow robots.txt + dev-resolving OG):
  python3 render.py --base / --site https://sunmap.puddy.dev/ --og-site https://sunmap.puddy.dev/
"""
import argparse
import math
import sys
from pathlib import Path

SUN = Path(__file__).resolve().parents[1]

_ap = argparse.ArgumentParser()
_ap.add_argument('--base', default='/', help="URL mount: '/' (the sunmap subdomains - canonical) or a subpath")
_ap.add_argument('--site', default='https://sunmap.puddystudios.com/', help='canonical origin+base for SEO tags')
_ap.add_argument('--og-site', default=None, help='host for OG/social images + JSON-LD image (defaults to --site); point at the dev host so dev link previews resolve while prod is dark')
_ap.add_argument('--years', default='1900-2099', help='inclusive year range the day picker offers')
_ap.add_argument('--date', default=None, help='the local day to prerender (YYYY-MM-DD); defaults to today at the default observer')
_args = _ap.parse_args()

BASE = _args.base if _args.base.endswith('/') else _args.base + '/'
SITE = _args.site if _args.site.endswith('/') else _args.site + '/'
OG_SITE = (_args.og_site or _args.site)
OG_SITE = OG_SITE if OG_SITE.endswith('/') else OG_SITE + '/'

# Kept from SUNMAP's own prior generator, deliberately, because dropping it in a
# fork would be a live SEO regression: EVERY canonical and identity URL points at
# PROD no matter which host this build is served from, and any non-prod build
# also carries a noindex meta. The demo host must never compete with prod in the
# index, and it must never self-canonicalize if someone passes --site by hand.
PROD = 'https://sunmap.puddystudios.com/'
INDEXABLE = (SITE == PROD)
ROBOTS = ('' if INDEXABLE else
          '\n<meta name="robots" content="noindex,nofollow">'
          '<!-- demo build: prod is the only indexable host -->')
_y0, _y1 = (int(p) for p in _args.years.split('-'))
YEARS = list(range(_y0, _y1 + 1))

HTML = r"""<!DOCTYPE html>
<!-- SPDX-License-Identifier: AGPL-3.0-or-later
     Copyright (C) 2026 PUDDY Inc. <legal@puddystudios.com>
     Generated by scripts/render.py - do not hand-edit. Corresponding source: /source.html -->
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<script>(function(){var u=new URL(window.location.href);['_gl','_ga','_gac','gclid','gclsrc'].forEach(function(p){u.searchParams.delete(p);});if(u.href!==window.location.href)window.history.replaceState(null,'',u.pathname+(u.search||'')+(u.hash||''));})();</script>
<title>__TITLE__</title>
<meta name="description" content="__DESC__">
<meta name="keywords" content="__KEYWORDS__">
<meta name="author" content="Colton Dempsey 𓅇">
<link rel="canonical" href="__CANONICAL__">__ROBOTS__
<meta property="og:type" content="website">
<meta property="og:site_name" content="Puddy Studios">
<meta property="og:title" content="__OGTITLE__">
<meta property="og:description" content="__OGDESC__">
<meta property="og:url" content="__PAGEURL__">
<meta property="og:image" content="__OGIMG__">
<meta property="og:image:width" content="2400">
<meta property="og:image:height" content="1260">
<meta property="og:image:alt" content="__OGALT__">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:site" content="@cubedivision">
<meta name="twitter:title" content="__TWTITLE__">
<meta name="twitter:description" content="__OGDESC__">
<meta name="twitter:image" content="__OGIMG__">
<meta name="twitter:image:alt" content="__OGALT__">
__PREVNEXT_LINKS__
<link rel="manifest" href="__B__manifest.json">
<meta name="theme-color" content="#000000">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black">
<meta name="apple-mobile-web-app-title" content="Sunmap">
<link rel="apple-touch-icon" href="__B__icons/icon-180.png">
<link rel="icon" type="image/svg+xml" sizes="any" href="__B__favicon.svg">
<link rel="icon" type="image/png" sizes="32x32" href="__B__icons/icon-32.png">
<link rel="icon" type="image/png" sizes="16x16" href="__B__icons/icon-16.png">
<link rel="icon" type="image/x-icon" href="__B__favicon.ico">
<link rel="icon" type="image/png" sizes="192x192" href="__B__icons/icon-192.png">
__JSONLD__
<link rel="dns-prefetch" href="https://photon.komoot.io">
<link rel="dns-prefetch" href="https://nominatim.openstreetmap.org">
<link rel="dns-prefetch" href="https://get.geojs.io">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<link href="https://api.fontshare.com/v2/css?f[]=satoshi@400,500,700,900&display=swap" rel="stylesheet">
<script src="/puddy-tools.js?v=15" data-nav="studios" defer></script>
<style>
  :root{
    --bg:#000;--fg:#fff;--dim:rgba(255,255,255,.55);--faint:rgba(255,255,255,.32);
    --line:rgba(255,255,255,.16);--panel:rgba(255,255,255,.03);
    --sans:'Satoshi',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
    --mono:'Space Mono',ui-monospace,Menlo,monospace;
    --sym:'Apple Symbols','Segoe UI Symbol','Noto Sans Symbols2',var(--sans);
  }
  *{box-sizing:border-box;margin:0;padding:0}
  html{scroll-behavior:smooth}
  body{background:var(--bg);color:var(--fg);font-family:var(--sans);-webkit-font-smoothing:antialiased;line-height:1.5;overflow-x:hidden}
  .wrap{max-width:1080px;margin:0 auto;padding:0 clamp(20px,5vw,44px)}
  .gl{font-family:var(--sym);font-weight:400}

  header{position:relative;padding:60px 0 38px;border-bottom:1px solid var(--line);overflow:hidden}
  #stars{position:fixed;inset:0;width:100vw;height:100vh;opacity:.9;pointer-events:none;z-index:-1}
  .crest{text-align:center;padding:6px 0 12px}
  h1{font-weight:900;font-size:clamp(30px,8.5vw,90px);line-height:1.0;letter-spacing:-.01em;margin:0;text-transform:uppercase;white-space:nowrap}
  .crest h1 .wm{color:inherit;text-decoration:none;cursor:pointer}
  .crest h1 .h1yr{display:block;font-family:var(--mono);font-size:clamp(13px,3vw,26px);font-weight:700;letter-spacing:.22em;opacity:.6;margin-top:.32em;white-space:nowrap}
  .sigil{display:block;margin:26px auto 20px;width:clamp(150px,21vw,228px);height:auto}
  .subtitle{font-family:var(--sans);font-weight:500;font-size:clamp(15px,2.5vw,25px);line-height:1.22;letter-spacing:.005em;color:var(--fg)}
  .subtitle span{display:block}
  .tag{margin-top:22px;max-width:660px;color:var(--dim);font-size:15.5px}
  .tag b{color:var(--fg);font-weight:500}
  .tag+.tag{margin-top:12px}

  .yearnav{font-family:var(--mono);font-size:13px;letter-spacing:.14em;margin-top:16px;color:var(--faint)}
  .yearnav a{color:var(--dim);text-decoration:none;padding:4px 10px;border:1px solid var(--line);border-radius:3px;transition:.12s}
  .yearnav a:hover{color:var(--fg);border-color:var(--faint)}
  .yearnav .ynow{color:var(--fg);border:1px solid var(--faint);border-radius:3px;padding:4px 12px;margin:0 6px}
  .yearnav .yn-select{margin-bottom:10px}
  .yearnav .yn-select button{font-family:var(--mono);font-size:12px;letter-spacing:.18em;text-transform:uppercase;color:var(--dim);background:rgba(0,0,0,.3);border:1px solid var(--line);border-radius:3px;padding:7px 16px;cursor:pointer;transition:.12s}
  .yearnav .yn-select button:hover{color:var(--fg);border-color:var(--faint)}
  .yearnav .yn-day{margin-top:10px;position:relative;display:inline-block}
  .day-box{font-family:var(--mono);font-size:12px;letter-spacing:.18em;text-transform:uppercase;text-align:center;color:var(--dim);background:rgba(0,0,0,.3);border:1px solid var(--line);border-radius:3px;padding:7px 18px;cursor:pointer;transition:.12s;width:200px;appearance:none;-webkit-appearance:none}
  .day-box:hover{color:var(--fg);border-color:var(--faint)}
  .day-box:focus{outline:none;color:var(--fg);border-color:var(--faint)}
  .day-box.empty{color:var(--dim)}
  #day-cal{position:fixed;transform:translateX(-50%);z-index:9999;width:300px;background:#000;border:1px solid var(--faint);border-radius:6px;padding:14px;box-shadow:0 16px 50px rgba(0,0,0,.72)}
  #day-cal[hidden]{display:none}
  .dc-wheels{position:relative;display:flex;gap:6px;height:180px;overflow:hidden;margin-bottom:12px}
  .dc-col{flex:1;overflow-y:scroll;scroll-snap-type:y mandatory;scrollbar-width:none;-ms-overflow-style:none;text-align:center;position:relative;z-index:2;overscroll-behavior:contain}
  .dc-col::-webkit-scrollbar{display:none}
  .dc-col#dc-mon{flex:1.35}
  .dc-col#dc-day{flex:.7}
  .dc-opt{height:36px;line-height:36px;scroll-snap-align:center;font-family:var(--mono);font-size:12.5px;letter-spacing:.03em;color:var(--faint);cursor:pointer;transition:color .12s}
  .dc-opt.on{color:var(--fg);font-weight:700}
  .dc-pad{height:72px}
  .dc-band{position:absolute;left:0;right:0;top:72px;height:36px;border-top:1px solid var(--faint);border-bottom:1px solid var(--faint);background:rgba(255,255,255,.05);pointer-events:none;z-index:1}
  #dc-go{font-family:var(--mono);font-size:12px;letter-spacing:.18em;text-transform:uppercase;color:var(--dim);background:rgba(0,0,0,.3);border:1px solid var(--line);border-radius:3px;padding:9px 0;cursor:pointer;width:100%;transition:.12s}
  #dc-go:hover{color:var(--fg);border-color:var(--faint)}
  #foot{text-align:center;padding:24px 16px}
  #foot .foot-nav{display:flex;flex-wrap:wrap;justify-content:center;gap:6px 16px;margin-bottom:6px}
  #foot .foot-nav a{font-family:var(--mono);font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--dim);text-decoration:none}
  #foot .foot-nav a:hover{color:var(--fg)}
  #foot .foot-c{font-family:var(--mono);font-size:10px;letter-spacing:.1em;color:var(--faint);margin:0}
  body:has(.pt-sfoot) #foot{display:none}  /* the JS studios chrome replaces this no-JS fallback */
  .ev{scroll-margin-top:84px}  /* clears the fixed studios nav when a searched day jumps to the top */
  .ev.daymark{outline:1px solid var(--fg);background:rgba(255,255,255,.08)}  /* stays lit until a new day is searched */
  #yn-menu{position:fixed;inset:0;z-index:50;background:rgba(0,0,0,.96);backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);overflow-y:auto;display:none}
  #yn-menu .ym-wrap{max-width:1080px;margin:0 auto;padding:30px clamp(20px,5vw,44px) 80px}
  #yn-menu .ym-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
  #yn-menu h2{font-family:var(--mono);font-size:14px;letter-spacing:.24em;text-transform:uppercase;font-weight:400;color:var(--dim)}
  #yn-menu .ym-close,#yn-menu .ym-this{font-family:var(--mono);font-size:13px;color:var(--dim);background:none;border:1px solid var(--line);border-radius:3px;padding:6px 12px;cursor:pointer;text-decoration:none}
  #yn-menu .ym-close:hover,#yn-menu .ym-this:hover{color:var(--fg);border-color:var(--faint)}
  #yn-menu .ym-decade{font-family:var(--mono);font-size:11px;letter-spacing:.22em;color:var(--faint);margin:18px 0 8px;text-align:center}
  #yn-menu .ym-grid{display:flex;flex-wrap:wrap;gap:6px;justify-content:center}
  #yn-menu .ym-grid a{font-family:var(--mono);font-size:13px;color:var(--dim);text-decoration:none;border:1px solid var(--line);padding:7px 11px;border-radius:3px;transition:.12s}
  #yn-menu .ym-grid a:hover{color:var(--fg);border-color:var(--faint)}
  #yn-menu .ym-grid a.ym-cur{background:var(--fg);color:#000;border-color:var(--fg)}
  .yeardir{padding:34px clamp(20px,5vw,44px) 20px;border-top:1px solid var(--line);background:rgba(0,0,0,.4);backdrop-filter:blur(3px);-webkit-backdrop-filter:blur(3px)}
  .yeardir h2{font-weight:800;font-size:clamp(20px,3vw,27px);letter-spacing:-.01em;margin:0 0 6px;text-align:center}
  .yeardir .lead{color:var(--dim);font-size:14.5px;line-height:1.7;max-width:840px;margin:0 auto 16px;text-align:center}
  .yeardir .decade{font-family:var(--mono);font-size:11px;letter-spacing:.22em;color:var(--faint);margin:18px 0 8px;text-align:center}
  .yeardir .ygrid{display:flex;flex-wrap:wrap;gap:6px;justify-content:center}
  .yeardir .ygrid a{font-family:var(--mono);font-size:12px;color:var(--dim);text-decoration:none;border:1px solid var(--line);padding:5px 9px;border-radius:3px;transition:.12s}
  .yeardir .ygrid a:hover{color:var(--fg);border-color:var(--faint)}
  .yeardir .ygrid a[aria-current="page"]{background:var(--fg);color:#000;border-color:var(--fg)}

  .next{margin:30px 0 0;border:1px solid var(--line);background:rgba(0,0,0,.3);backdrop-filter:blur(3px);-webkit-backdrop-filter:blur(3px);padding:20px 22px;display:flex;flex-wrap:wrap;gap:16px 24px;align-items:center;justify-content:space-between}
  .next>div{min-width:0}
  .next .lbl{font-family:var(--mono);font-size:11px;letter-spacing:.26em;color:var(--faint);text-transform:uppercase}
  .next .name{font-weight:700;font-size:19px;margin-top:6px}
  .next .when{font-family:var(--mono);font-size:13px;color:var(--dim);margin-top:4px}
  .count{font-family:var(--mono);font-weight:700;font-size:clamp(24px,5vw,40px);letter-spacing:.02em;text-align:right;white-space:nowrap}
  .count small{display:block;font-weight:400;font-size:11px;letter-spacing:.2em;color:var(--faint);text-align:right;margin-top:4px}

  .moonnote{border-bottom:1px solid var(--line);background:rgba(0,0,0,.4);backdrop-filter:blur(3px);-webkit-backdrop-filter:blur(3px)}
  .moonnote .wrap{padding:18px clamp(20px,5vw,44px);font-family:var(--mono);font-size:12px;color:var(--dim);line-height:1.85}
  .moonnote p+p{margin-top:8px}
  .moonnote b{color:var(--fg);font-weight:400}
  .moonnote .beta{display:inline-block;font-size:9.5px;letter-spacing:.18em;padding:2px 6px;border:1px solid var(--line);border-radius:3px;margin:0 2px 0 4px;color:var(--faint)}
  .moonnote .srcnote{color:var(--faint);font-size:11px}
  .moonnote .srcnote a{color:var(--dim);text-decoration:underline}
  .moonnote .srcnote a:hover{color:var(--fg)}

  /* Controls panel: one coherent section, three internal rows. NOT sticky -
     once you scroll, you scroll (Colton 2026-06-10). */
  .controls{position:relative;z-index:20;background:rgba(0,0,0,.94);backdrop-filter:blur(8px);border-bottom:1px solid var(--line)}
  .panel{padding:18px clamp(20px,5vw,44px)}
  .section + .section{border-top:1px solid var(--line);padding-top:14px;margin-top:14px}
  .slabel{font-family:var(--mono);font-size:10px;letter-spacing:.22em;color:var(--faint);text-transform:uppercase;margin-bottom:8px}
  .seg{display:flex;gap:7px;flex-wrap:wrap}
  .chip{font-family:var(--mono);font-size:12px;letter-spacing:.05em;text-transform:uppercase;border:1px solid var(--line);background:rgba(0,0,0,.3);backdrop-filter:blur(3px);-webkit-backdrop-filter:blur(3px);color:var(--dim);padding:7px 11px;border-radius:3px;cursor:pointer;transition:.12s;user-select:none}
  .chip:hover{color:var(--fg);border-color:var(--faint)}
  .chip[aria-pressed="true"]{background:var(--fg);color:#000;border-color:var(--fg)}
  .chip .x{opacity:.55;margin-left:6px}
  /* Range / Frame / Engine: evenly spaced columns across the panel */
  .triad{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px}
  .col{min-width:0}
  .note{font-family:var(--mono);font-size:10.5px;color:var(--faint);margin-top:8px;max-width:380px;line-height:1.6}
  /* Location section: all caps, centered - one box sets the timezone AND the
     topocentric observer, with live autocomplete. Only a picked suggestion applies. */
  .loc-section{text-align:center}
  .locwrap{position:relative;width:min(380px,92%);margin:0 auto}
  .locrow{display:flex;gap:8px;align-items:stretch}
  input#tz-search{flex:1;min-width:0;background:transparent;border:1px solid var(--line);color:var(--fg);font-family:var(--mono);font-size:16px;padding:9px 12px;border-radius:3px;letter-spacing:.06em;text-align:center;text-transform:uppercase;box-sizing:border-box}
  #loc-here{flex:0 0 auto;width:44px;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.3);border:1px solid var(--line);border-radius:3px;color:var(--dim);cursor:pointer;transition:.12s;-webkit-appearance:none;appearance:none}
  #loc-here:hover{color:var(--fg);border-color:var(--faint)}
  #loc-here svg{display:block}
  input#tz-search::placeholder{color:var(--faint);letter-spacing:.18em}
  #loc-suggest{display:none;position:absolute;top:calc(100% + 4px);left:0;right:0;z-index:30;background:rgba(0,0,0,.97);border:1px solid var(--faint);border-radius:3px;max-height:380px;overflow-y:auto;text-align:left}
  #loc-suggest .ls-item{padding:9px 12px;cursor:pointer;border-bottom:1px solid var(--line)}
  #loc-suggest .ls-item:last-child{border-bottom:none}
  #loc-suggest .ls-n{font-family:var(--mono);font-size:12px;color:var(--fg);letter-spacing:.04em}
  #loc-suggest .ls-s{font-family:var(--mono);font-size:10px;color:var(--faint);margin-top:2px;letter-spacing:.06em}
  #loc-suggest .ls-item:hover,#loc-suggest .ls-item.ls-hot{background:rgba(255,255,255,.1)}
  #loc-suggest .ls-cred{font-family:var(--mono);font-size:9px;color:var(--faint);padding:6px 12px;letter-spacing:.1em;text-transform:uppercase;cursor:default}
  .tzactive{font-family:var(--mono);font-size:11px;color:var(--faint);text-align:center;margin-top:9px}
  .tzactive b{color:var(--dim);font-weight:400}
  .locstatus{font-family:var(--mono);font-size:10.5px;color:var(--faint);text-align:center;margin-top:5px;min-height:13px}

  #yn-menu .ym-head h2{flex:1;text-align:center}

  main{padding:8px 0 60px;min-height:40vh;background:rgba(0,0,0,.4);backdrop-filter:blur(3px);-webkit-backdrop-filter:blur(3px)}
  .status{font-family:var(--mono);font-size:12px;color:var(--faint);padding:18px 0 4px}
  .month{font-family:var(--mono);font-size:13px;letter-spacing:.24em;text-transform:uppercase;color:var(--faint);padding:30px 0 10px;border-bottom:1px solid var(--line)}
  .ev{display:grid;grid-template-columns:168px 1fr auto;gap:20px;align-items:baseline;padding:15px 0;border-bottom:1px solid var(--line)}
  .ev .d{font-weight:600;font-size:15px;white-space:nowrap}
  .ev .t{font-family:var(--mono);font-size:12px;color:var(--dim);margin-top:4px;white-space:nowrap}
  .ev .t .sec{color:var(--fg)}.ev .t .ms{color:var(--dim)}.ev .t .mer{color:var(--faint)}
  .ev .title{font-weight:500;font-size:16px}
  .ev .title .gl{color:var(--fg)}
  .ev .sub{color:var(--dim);font-size:12.5px;margin-top:4px;font-family:var(--mono)}
  .ev .meta{text-align:right;white-space:nowrap}
  .badge{display:inline-block;font-family:var(--mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;border:1px solid var(--line);color:var(--dim);padding:3px 6px;border-radius:3px}
  .badge.nasa{border-color:rgba(255,255,255,.6);color:var(--fg)}
  .prec{font-family:var(--mono);font-size:10.5px;color:var(--faint);margin-top:5px}
  .flag{display:inline-block;font-family:var(--mono);font-size:10px;font-weight:700;letter-spacing:.14em;background:#fff;color:#000;padding:2px 8px;border-radius:3px;margin-left:10px;vertical-align:middle;white-space:nowrap}
  .ev.flagged{background:rgba(255,255,255,.05)}
  /* Prerendered (crawlable) content - briefly visible before the JS list hydrates */
  .seo-pre .seo-lead{color:var(--dim);font-size:14px;line-height:1.7;max-width:780px;margin:6px 0 14px}
  .seo-pre h2{font-family:var(--mono);font-size:13px;letter-spacing:.2em;text-transform:uppercase;color:var(--faint);padding:24px 0 8px;border-bottom:1px solid var(--line)}
  .seo-pre ul{list-style:none}
  .seo-pre li{padding:11px 0;border-bottom:1px solid var(--line);font-size:14.5px}
  .seo-pre time{font-family:var(--mono);font-size:12.5px;color:var(--dim);margin-right:8px}
  /* FAQ */
  .faq{padding:34px clamp(20px,5vw,44px) 52px;border-top:1px solid var(--line);background:rgba(0,0,0,.4);backdrop-filter:blur(3px);-webkit-backdrop-filter:blur(3px)}
  .faq h2{font-weight:800;font-size:clamp(22px,3.2vw,30px);letter-spacing:-.01em;margin:0 0 14px}
  .faq .lead{color:var(--dim);font-size:15px;line-height:1.75;max-width:840px;margin-bottom:10px}
  .faq .lead b{color:var(--fg);font-weight:500}
  .faq .qa{border-top:1px solid var(--line);padding:16px 0}
  .faq .qa h3{font-size:16.5px;font-weight:600;margin-bottom:7px}
  .faq .qa p{color:var(--dim);font-size:14.5px;line-height:1.7;max-width:840px}
  .faq .qa b{color:var(--fg);font-weight:500}

  footer{border-top:1px solid var(--line);padding:38px 0 80px;color:var(--faint);font-size:12px;font-family:var(--mono);line-height:1.85;background:rgba(0,0,0,.4);backdrop-filter:blur(3px);-webkit-backdrop-filter:blur(3px)}
  footer b{color:var(--dim);font-weight:400}
  /* One footer only. puddy-tools.js (studios mode) injects the shared canonical
     footer (.pt-sfoot); when it does, hide this page's static fallback #foot so
     there is exactly one. A no-JS crawler never gets .pt-sfoot, so it still sees
     #foot (which also carries the AGPL Source link). */
  body:has(.pt-sfoot) #foot{display:none}
  @media(max-width:680px){
    .ev{grid-template-columns:146px 1fr;gap:14px}
    .ev .t{white-space:normal}  /* long GMT-offset zones (e.g. GMT+5:30) wrap inside the lane instead of crowding the alignment column */
    .ev .meta{grid-column:1/-1;text-align:left;margin-top:6px}
    .count,.count small{text-align:left}
    .triad{grid-template-columns:1fr;gap:22px}
  }
  /* Centered layout pass (Colton 2026-06-10), revised same day: the CONTROLS,
     year nav, year directory, FAQ and footer sit on the centered axis; the
     credit tags, countdown card, moonnote and the EVENT LIST stay left-anchored
     (Colton: the events do not look good centered). */
  .slabel{text-align:center}
  .seg{justify-content:center}
  .triad .col{text-align:center}
  .yearnav{text-align:center}
  .yn-spread,.yn-select{justify-content:center}
  #years{text-align:center}
  .faq{text-align:center}
  .faq .qa p{margin-left:auto;margin-right:auto}
  footer{text-align:center}
</style>
</head>
<body>
<header>
  <canvas id="stars" aria-hidden="true"></canvas>
  <div class="wrap">
    <div class="crest">
      <h1><a class="wm" href="__B__" aria-label="SUNMAP home - Today's solar and lunar cycle">Sunmap</a>__H1YR__</h1>
      <svg class="sigil" viewBox="0 0 200 200" preserveAspectRatio="xMidYMid meet" aria-hidden="true">
        <defs>
          <symbol id="puddy-face" viewBox="0 0 38.4 38.4">
            <circle fill="#fff" cx="19.2" cy="19.2" r="19.2"/>
            <path d="M23.48,27.37c-1.11,1.09-3.21,1.98-4.75,1.76-1.41-.2-2.7-.8-3.73-1.76-.69-.64-1.23-1.37-1.64-2.23v-4.04s11.76,0,11.76,0v4.04c-.41.86-.95,1.58-1.64,2.23Z"/>
            <polygon points="12.14 19.12 10.17 19.12 8.3 17.96 8.29 10.62 10.37 9.23 11.93 9.23 14.01 10.62 14 17.96 12.14 19.12"/>
            <rect fill="#fff" x="10.18" y="10.36" width="1.94" height="2.8" transform="translate(-.02 .02) rotate(-.12)"/>
            <polygon points="28.25 19.12 26.28 19.12 24.4 17.96 24.4 10.62 26.48 9.23 28.03 9.23 30.11 10.62 30.11 17.96 28.25 19.12"/>
            <rect fill="#fff" x="26.29" y="10.36" width="1.94" height="2.8" transform="translate(-.02 .06) rotate(-.12)"/>
          </symbol>
        </defs>
        __SIGIL_BODY__
      </svg>
      <h2 class="subtitle"><span>Every Sunrise and Sunset</span> <span>Solved Where You Stand</span></h2>
      <nav class="yearnav" aria-label="Browse days">__YEARNAV__</nav>
    </div>
    <div class="next" id="next">
      <div><div class="lbl">Next event</div><div class="name" id="next-name">-</div><div class="when" id="next-when">-</div></div>
      <div class="count" id="count">--:--:--<small id="count-lbl">until next</small></div>
    </div>
    <p class="tag"><b>Swiss Ephemeris (DE441)</b> resolves every sunrise and moonrise to the second.</p>
    <p class="tag">Engine cross-checked against an independent <b>NOAA</b> implementation - Event by event.</p>
    <p class="tag">Every other almanac rounds to the minute. We get it <b>EXACT</b>.</p>
  </div>
</header>

<div class="moonnote"><div class="wrap" id="moonnote">Loading the sky...</div></div>

<nav class="controls"><div class="panel wrap">
  <div class="section"><div class="slabel">Show events (tap to add or remove)</div><div class="seg" id="cats"></div></div>
  <div class="section"><div class="triad">
    <div class="col"><div class="slabel">Range</div><div class="seg" id="range"></div></div>
    <div class="col"><div class="slabel">Elevation</div><div class="seg" id="frame"></div><div class="note" id="frame-note"></div></div>
    <div class="col"><div class="slabel">Clock</div><div class="seg" id="engine"></div></div>
  </div></div>
  <div class="section loc-section">
    <div class="slabel">Where you are standing</div>
    <div class="locwrap">
      <div class="locrow">
        <input id="tz-search" placeholder="CHOOSE YOUR LOCATION" autocomplete="off" role="combobox" aria-expanded="false" aria-label="Choose your location - City, address, or zip">
        <button type="button" id="loc-here" aria-label="Use my device location" title="Use my device location"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="12" r="6"/><line x1="12" y1="1.5" x2="12" y2="5"/><line x1="12" y1="19" x2="12" y2="22.5"/><line x1="1.5" y1="12" x2="5" y2="12"/><line x1="19" y1="12" x2="22.5" y2="12"/></svg></button>
      </div>
      <div id="loc-suggest" role="listbox" aria-label="Location suggestions"></div>
    </div>
    <div class="tzactive">Showing times for <b id="tz-active">New York City</b></div>
    <div class="locstatus" id="loc-status"></div>
  </div>
</div></nav>

<main class="wrap"><div class="status" id="status">Loading...</div><div id="list">__PRERENDER_LIST__</div></main>
<section class="wrap yeardir" aria-label="Browse every day of the month">__YEARS_DIR__</section>
<section class="wrap faq" aria-label="__YEAR__ sunrise and sunset - Frequently asked questions">__FAQ_HTML__</section>
<footer class="wrap" id="foot"><nav class="foot-nav" aria-label="Puddy Studios"><a href="https://puddystudios.com/about">About</a><a href="https://puddystudios.com/contact">Contact</a><a href="https://puddystudios.com/privacy">Privacy</a><a href="https://puddystudios.com/terms">Terms</a><a href="https://starmap.puddystudios.com/">Starmap</a><a href="__B__source.html">Source</a></nav><p class="foot-c">&copy; 2026 PUDDY INC. - ALL RIGHTS RESERVED</p></footer>

<script type="module">
import * as GEO from '__B__sunmap-geo.js';

const LS='sunmap.v1';
const B='__B__', Y0=__Y0__, Y1=__Y1__;
const DAY0='__DAY0__';  /* the day this page was prerendered for */
const BODYG={sun:'☉',moon:'☽'};
const LADDER=__LADDER__;      /* [[key,label,body],...] - the engine's canonical order */
const GLOSS=__GLOSS__;        /* key -> what the instant means */
const PREC=__PREC__;          /* key -> the geometric definition, derived from the engine ladder */
const NONE=__NONE__;          /* key -> status -> the honest sentence for a non-event */
const CATS=__CATS__;          /* [{key,label,keys,def}] */
CATS.forEach(c=>{const s=new Set(c.keys);c.test=e=>s.has(e.key);});
const KEY_ORDER={}; LADDER.forEach((r,i)=>{KEY_ORDER[r[0]]=i;});

let DATA=null, sel=new Set(), frame='sea', engine='h12', range='all', day=DAY0, tz='__TZ0__', loc=null;

/* Everything below builds DOM with createElement + textContent. Place names come
   from OpenStreetMap and are user-editable; sunmap-geo.js's contract requires
   they never touch innerHTML. Same markup as STARMAP, safer construction. */
const $=id=>document.getElementById(id);
function el(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n;}
function clear(n){while(n.firstChild)n.removeChild(n.firstChild);return n;}
function txt(s){return document.createTextNode(s);}

function load(){try{const s=JSON.parse(localStorage.getItem(LS));if(s){sel=new Set(s.cats||[]);frame=s.frame||'sea';engine=s.engine||'h12';range=s.range||'all';if(sel.size===0)sel=new Set(CATS.filter(c=>c.def).map(c=>c.key));}else{sel=new Set(CATS.filter(c=>c.def).map(c=>c.key));}}catch(e){sel=new Set(CATS.filter(c=>c.def).map(c=>c.key));}}
function save(){try{localStorage.setItem(LS,JSON.stringify({cats:[...sel],frame,engine,range}));}catch(e){}}

/* ---- the engine. Same JSON contract as scripts/solar.py, solved on the device
   so no coordinate ever leaves it. ---- */
const worker=new Worker(B+'sunmap-worker.js',{type:'module'});
worker.onmessage=ev=>{const d=ev.data||{};
  if(!d.ok){$('status').textContent='Could not solve this day: '+(d.error||'the engine did not answer');return;}
  DATA=d.result;chrome();render();};
worker.onerror=e=>{$('status').textContent='The engine failed to load: '+((e&&e.message)||'unknown');};
function compute(){
  if(!loc)return;
  $('status').textContent='Solving '+dayLabel()+'...';
  worker.postMessage({base:B,coords:{lat:loc.lat,lon:loc.lon,alt:(frame==='ground'?(loc.alt||0):0)},
    date:day,tz:tz,moon:true});
}

/* ---- time. Rounded to the SECOND, the way the engine's own CLI rounds it:
   sub-second sunrise is arithmetic the atmosphere does not support. ---- */
function tzCity(t){return ((t||'').split('/').pop()||'').replace(/_/g,' ');}
function toSec(iso){return new Date(Math.round(Date.parse(iso)/1000)*1000);}
function clockOpts(){const h12=(engine==='h12');
  const o={timeZone:tz,hour:h12?'numeric':'2-digit',minute:'2-digit',second:'2-digit',timeZoneName:'short'};
  /* hour12:false yields a 24:xx midnight in en-US; hourCycle h23 is the correct dial */
  if(h12)o.hour12=true; else o.hourCycle='h23';
  return o;}
function fmtDate(iso){return toSec(iso).toLocaleString('en-US',{timeZone:tz,month:'short',day:'2-digit',year:'numeric'});}
function fmtClock(iso){return toSec(iso).toLocaleString('en-US',clockOpts());}
/* the .t lane: H:MM<span class="sec">:SS</span> <span class="mer">AM ZONE</span> */
function fillTime(host,iso){
  const h12=(engine==='h12'), base=fmtClock(iso);
  const m=h12?base.match(/^(\d+):(\d{2}):(\d{2})\s*(AM|PM)\s*(.*)$/i)
             :base.match(/^(\d+):(\d{2}):(\d{2})\s*(.*)$/);
  if(!m){host.textContent=base;return;}
  const mer=h12?m[4]:'', zone=(h12?m[5]:m[4])||tzCity(tz);
  host.append(txt(m[1]+':'+m[2]),el('span','sec',':'+m[3]),txt(' '),el('span','mer',(mer?mer+' ':'')+zone));
}
function ymd(iso){const p=iso.split('-');return new Date(Date.UTC(+p[0],+p[1]-1,+p[2]));}
function dayLabel(){return ymd(day).toLocaleDateString('en-US',{timeZone:'UTC',weekday:'long',month:'long',day:'numeric',year:'numeric'});}
function navLabel(){return ymd(day).toLocaleDateString('en-US',{timeZone:'UTC',weekday:'long',month:'long',day:'numeric'});}
function shiftDay(iso,n){const t=ymd(iso);t.setUTCDate(t.getUTCDate()+n);
  const p=x=>String(x).padStart(2,'0');
  return `${t.getUTCFullYear()}-${p(t.getUTCMonth()+1)}-${p(t.getUTCDate())}`;}
function todayIn(z){try{return new Intl.DateTimeFormat('en-CA',{timeZone:z,year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());}catch(e){return DAY0;}}

/* ---- the row. Honest about a non-event: no time, and the reason in the sub. ---- */
function reason(e){const byKey=NONE[e.key]||{};return byKey[e.status]||('None - The solver reported: '+e.status);}
let DUP=new Set();
function flagFor(e){
  if(e.key==='sunrise'||e.key==='sunset'){
    if(e.status==='always_above')return 'MIDNIGHT SUN';
    if(e.status==='always_below')return 'POLAR NIGHT';}
  if((e.key==='moonrise'||e.key==='moonset')&&e.status==='always_above')return 'CIRCUMPOLAR';
  if(e.utc&&DUP.has(e.key))return 'TWICE TODAY';
  return '';}

function row(e){
  const has=!!e.utc, fl=flagFor(e);
  const r=el('div','ev'+(fl?' flagged':''));
  r.setAttribute('data-k',e.key);
  const left=el('div');
  left.append(el('div','d',has?fmtDate(e.utc):'None'));
  const t=el('div','t'); if(has)fillTime(t,e.utc); left.append(t);
  const mid=el('div');
  const title=el('div','title');
  title.append(el('span','gl',BODYG[e.body]||''),txt(' '+e.label));
  if(fl)title.append(txt(' '),el('span','flag',fl));
  mid.append(title,el('div','sub',has?(GLOSS[e.key]||''):reason(e)));
  const meta=el('div','meta');
  meta.append(el('span','badge',e.body==='moon'?'MOON':'SUN'),el('div','prec',PREC[e.key]||''));
  r.append(left,mid,meta);
  return r;
}

function shown(){let arr=(DATA?DATA.events:[]).filter(e=>{for(const k of sel){const c=CATS.find(x=>x.key===k);if(c&&c.test(e))return true;}return false;});
  if(range==='now'){const now=Date.now();arr=arr.filter(e=>e.utc&&Date.parse(e.utc)>=now);}return arr;}
function shownSorted(){const ev=shown();ev.sort((a,b)=>{const an=!a.utc,bn=!b.utc;if(an!==bn)return an?1:-1;
  const x=a.utc||'',y=b.utc||'';if(x<y)return -1;if(x>y)return 1;return KEY_ORDER[a.key]-KEY_ORDER[b.key];});return ev;}

function render(){
  if(!DATA)return; /* controls are clickable before the engine answers */
  const list=clear($('list')), ev=shownSorted();
  const seen={};DUP=new Set();
  for(const e of DATA.events){if(!e.utc)continue;if(seen[e.key])DUP.add(e.key);seen[e.key]=1;}
  const ctx=range==='now'?` still ahead on ${dayLabel()}`:` on ${dayLabel()}`;
  $('status').textContent=`${ev.length} event${ev.length===1?'':'s'}${ctx}`;
  list.append(el('div','month',dayLabel()+' - '+locLabel()));
  ev.forEach(e=>list.append(row(e)));
  tick();
}

/* ---- the day nav. One page, so a day is a fragment, not a new URL. ---- */
function gotoDay(d){
  if(!/^\d{4}-\d{2}-\d{2}$/.test(d))return;
  const y=+d.slice(0,4); if(y<Y0||y>Y1)return;
  day=d; syncDayNav(); if(window.__dayBox)window.__dayBox(d);
  try{history.replaceState(null,'','#d='+d);}catch(e){}
  compute();
}
function syncDayNav(){
  const now=$('day-now'); if(now)now.textContent=navLabel();
  const p=$('day-prev'), n=$('day-next');
  if(p)p.href='#d='+shiftDay(day,-1);
  if(n)n.href='#d='+shiftDay(day,1);
  const dd=$('day-dir'); if(dd)buildDayDir(dd);
}
function dayHash(){
  if(location.hash.indexOf('#d=')!==0)return;
  const d=location.hash.slice(3);
  if(/^\d{4}-\d{2}-\d{2}$/.test(d))gotoDay(d);
}
(function(){
  const p=$('day-prev'), n=$('day-next');
  if(p)p.addEventListener('click',e=>{e.preventDefault();gotoDay(shiftDay(day,-1));});
  if(n)n.addEventListener('click',e=>{e.preventDefault();gotoDay(shiftDay(day,1));});
  window.addEventListener('hashchange',dayHash);
})();

/* PICK A DATE - the same iOS-style scroll wheels STARMAP uses (month / day /
   year), no typing needed, no third-party calls. The centred row under the band
   is the selection; "Go to day" applies it. */
(function(){
  const inp=$('day-input'),cal=$('day-cal'),
        colM=$('dc-mon'),colD=$('dc-day'),colY=$('dc-yr'),go=$('dc-go');
  if(!inp||!colM)return;
  const MON=['January','February','March','April','May','June','July','August','September','October','November','December'];
  const ITEM=36, pad=n=>(n<10?'0':'')+n;
  let sm=+DAY0.slice(5,7)-1, sd=+DAY0.slice(8,10), sy=Math.min(Y1,Math.max(Y0,+DAY0.slice(0,4)));
  const daysIn=(m,y)=>new Date(y,m+1,0).getDate();
  const nOpts=col=>col.querySelectorAll('.dc-opt').length;
  const curISO=()=>sy+'-'+pad(sm+1)+'-'+pad(sd);
  function fill(col,labels,selIdx){clear(col);                          /* DOM-built, no innerHTML */
    col.appendChild(el('div','dc-pad'));
    labels.forEach((lab,i)=>{const o=el('div','dc-opt'+(i===selIdx?' on':''),lab);o.dataset.i=i;col.appendChild(o);});
    col.appendChild(el('div','dc-pad'));}
  function mark(col,i){const o=col.querySelectorAll('.dc-opt');for(let k=0;k<o.length;k++)o[k].classList.toggle('on',k===i);}
  function setCol(col,i){col._last=i;mark(col,i);
    /* mandatory scroll-snap silently resets a programmatic scrollTop; disable snap
       while we position, then restore it next frame so the row lands under the band. */
    col.style.scrollSnapType='none';col.scrollTop=i*ITEM;
    requestAnimationFrame(()=>{col.style.scrollSnapType='y mandatory';});}
  function fillDays(){const n=daysIn(sm,sy);if(sd>n)sd=n;fill(colD,Array.from({length:n},(_,i)=>String(i+1)),sd-1);}
  /* rebuild the day column when month/year changes - colD._busy suppresses ONLY
     the day column's own reflow-induced scroll events, so the month + year
     wheels stay fully responsive (no global lock). */
  function buildDays(){colD._busy=true;fillDays();requestAnimationFrame(()=>{setCol(colD,sd-1);setTimeout(()=>{colD._busy=false;},120);});}
  function setBox(v){inp.textContent=v||'PICK A DATE';inp.classList.toggle('empty',!v);}
  function pick(unit,i){
    if(unit==='mon'){sm=i;buildDays();}
    else if(unit==='day'){sd=i+1;}
    else{sy=Y0+i;buildDays();}
    setBox(curISO());
  }
  function onScroll(col,unit){if(col._busy)return;clearTimeout(col._t);col._t=setTimeout(()=>{if(col._busy)return;
    let i=Math.round(col.scrollTop/ITEM);i=Math.max(0,Math.min(i,nOpts(col)-1));
    if(i===col._last)return;col._last=i;mark(col,i);pick(unit,i);},80);}
  colM.addEventListener('scroll',()=>onScroll(colM,'mon'));
  colD.addEventListener('scroll',()=>onScroll(colD,'day'));
  colY.addEventListener('scroll',()=>onScroll(colY,'yr'));
  function tap(col,unit){col.addEventListener('click',e=>{const o=e.target.closest('.dc-opt');if(!o)return;
    const i=+o.dataset.i;setCol(col,i);pick(unit,i);});}
  tap(colM,'mon');tap(colD,'day');tap(colY,'yr');
  /* fixed picker: open under the box, but clamp into the viewport (nudge up if it
     would run off the bottom) - NO page scroll. */
  function placeCal(){const b=inp.getBoundingClientRect();var h=cal.offsetHeight||300,top=b.bottom+8,max=innerHeight-h-8;if(top>max)top=Math.max(8,max);cal.style.left=Math.round(b.left+b.width/2)+'px';cal.style.top=Math.round(top)+'px';}
  function openCal(){cal.hidden=false;inp.setAttribute('aria-expanded','true');colD._busy=true;
    fill(colM,MON,sm);fillDays();fill(colY,Array.from({length:Y1-Y0+1},(_,i)=>String(Y0+i)),sy-Y0);
    colM._last=sm;colD._last=sd-1;colY._last=sy-Y0;
    placeCal();
    /* a freshly-displayed element loses an immediate scrollTop set; wait for layout to settle. */
    setTimeout(()=>{placeCal();setCol(colM,sm);setCol(colD,sd-1);setCol(colY,sy-Y0);setTimeout(()=>{colD._busy=false;},140);},60);}
  function closeCal(){cal.hidden=true;inp.setAttribute('aria-expanded','false');}
  inp.addEventListener('focus',openCal);
  inp.addEventListener('click',openCal);
  inp.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();closeCal();gotoDay(curISO());}else if(e.key==='Escape')closeCal();}); /* button: no text keyboard */
  go.addEventListener('click',()=>{closeCal();gotoDay(curISO());});
  document.addEventListener('click',e=>{if(!cal.hidden&&e.target!==inp&&!cal.contains(e.target))closeCal();});
  /* persistence: after a jump, show the chosen day in the box */
  window.__dayBox=function(d){setBox(d);sy=+d.slice(0,4);sm=+d.slice(5,7)-1;sd=+d.slice(8,10);};
})();

function buildControls(){
  const cats=clear($('cats'));
  CATS.forEach(cat=>{const on=sel.has(cat.key);const b=el('button','chip',null);b.type='button';
    b.setAttribute('aria-pressed',on);b.append(txt(cat.label));if(on)b.append(el('span','x','×'));
    b.onclick=()=>{on?sel.delete(cat.key):sel.add(cat.key);save();buildControls();render();};cats.appendChild(b);});
  const seg=(id,opts,cur,set)=>{const host=clear($(id));
    opts.forEach(([k,l])=>{const b=el('button','chip',l);b.type='button';
      b.setAttribute('aria-pressed',k===cur);b.onclick=()=>{set(k);save();buildControls();render();chrome();};host.appendChild(b);});};
  seg('range',[['now','From now'],['all','All day']],range,k=>range=k);
  seg('frame',[['sea','Sea level'],['ground','Your elevation']],frame,k=>{frame=k;compute();});
  seg('engine',[['h12','12-hour'],['h24','24-hour']],engine,k=>engine=k);
  /* MEASURED, not assumed. Swiss swe_rise_trans takes the observer's altitude
     into its internal PRESSURE model, so thinner air refracts less and sunrise
     lands slightly LATER, sunset slightly EARLIER. It does NOT model the
     geometric dip of the horizon you get from standing high up. At 1000 m the
     measured shift is +23 s on sunrise; true dip would be minutes, the other
     way. Say what the engine does, and name what it does not. */
  const fn=$('frame-note');
  if(fn)fn.textContent=(loc&&loc.alt)
    ?('Elevation '+Math.round(loc.alt)+' m - Thinner air refracts less, so sunrise lands a little '
      +'later and sunset a little earlier. The geometric dip of a high horizon is not modelled.')
    :'No elevation known for this point, so both settings agree.';
  $('tz-active').textContent=locLabelTZ();
  initLocationBox();
}

/* ---- THE LOCATION BOX. One input sets the observer AND the timezone. The
   network stack, the on-device city table, the 7-day cache, the Photon ->
   Nominatim fallback and the GPS -> IP chain all live in sunmap-geo.js, which
   is STARMAP's own location stack ported and verified. This is only the UI. ---- */
function locLabel(){return (loc&&loc.label)||'New York City';}
function tzName(){try{var ps=new Intl.DateTimeFormat('en-US',{timeZone:tz,timeZoneName:'longGeneric'}).formatToParts(new Date());
  var p=ps.find(function(x){return x.type==='timeZoneName';});return p?p.value:'';}catch(e){return '';}}
function locLabelTZ(){var n=tzName();return locLabel()+(n?' ('+n+')':'');}
function locStatus(m){var s=$('loc-status');if(s)s.textContent=m||'';}

function initLocationBox(){
  var inp=$('tz-search'), box=$('loc-suggest');
  if(!inp||!box||inp._init)return;
  inp._init=1;
  var items=[],hot=-1;

  function closeBox(){box.style.display='none';clear(box);items=[];hot=-1;inp.setAttribute('aria-expanded','false');}
  function pick(it){
    closeBox();inp.value='';
    locStatus('Locating "'+String(it.label||'').split(',')[0]+'"...');
    try{GEO.chooseLocation(it);locStatus('');}catch(e){locStatus('Lookup failed - Try again');}
  }
  function renderBox(){
    clear(box);
    if(!items.length){closeBox();return;}
    items.forEach(function(it,i){
      var d=el('div','ls-item'+(i===hot?' ls-hot':''));d.setAttribute('role','option');
      d.append(el('div','ls-n',it.label));                 /* untrusted geocoder text */
      if(it.sub)d.append(el('div','ls-s',it.sub));
      d.addEventListener('mousedown',function(ev){ev.preventDefault();pick(it);});
      box.appendChild(d);
    });
    box.appendChild(el('div','ls-cred',GEO.ATTRIBUTION));
    box.style.display='block';
    inp.setAttribute('aria-expanded','true');
  }
  inp.addEventListener('input',function(){
    var q=(inp.value||'').trim();
    if(q.length<3){GEO.cancelSuggest();closeBox();return;}
    /* sunmap-geo.js owns the 250 ms debounce and marks a superseded call stale */
    GEO.suggest(q).then(function(res){
      if(!res||res.stale)return;
      items=res.slice(0,10);hot=items.length?0:-1;renderBox();
    }).catch(function(){});
  });
  inp.addEventListener('keydown',function(ev){
    if(ev.key==='ArrowDown'&&items.length){hot=(hot+1)%items.length;renderBox();ev.preventDefault();}
    else if(ev.key==='ArrowUp'&&items.length){hot=(hot-1+items.length)%items.length;renderBox();ev.preventDefault();}
    else if(ev.key==='Enter'){
      ev.preventDefault();
      if(items.length){pick(items[hot>=0?hot:0]);}
      else if((inp.value||'').trim()){locStatus('Pick a suggested location - Type a city, address, or zip');}
    }
    else if(ev.key==='Escape'){closeBox();}
  });
  inp.addEventListener('blur',function(){setTimeout(closeBox,150);});
  /* Dedicated device-location button. Precise device GPS first; on ANY failure
     (denied, unavailable, timeout, or no API) sunmap-geo.js falls back to IP so
     it ALWAYS resolves. */
  var hereBtn=$('loc-here');
  if(hereBtn)hereBtn.addEventListener('click',function(){
    locStatus('Locating you...');
    GEO.useDeviceLocation().then(function(l){
      locStatus(l&&l.source==='gps'?'Using your device location - It never leaves this device'
                                   :'Using your approximate location (by network) - Type an address above for an exact sky');
    }).catch(function(){locStatus('Could not detect your location - Type a city, address, or zip above');});
  });
}

function tick(){
  if(!DATA)return;const now=Date.now();
  const up=shownSorted().filter(e=>e.utc&&Date.parse(e.utc)>now)[0];
  const ct=$('count');
  document.querySelectorAll('#list .ev.daymark').forEach(r=>r.classList.remove('daymark'));
  $('next').querySelector('.lbl').textContent='Next event';
  if(!up){
    $('next-name').textContent='Nothing further on this day';
    $('next-when').textContent='Step to the next day to keep going';
    ct.firstChild.textContent='--:--:--';
    $('count-lbl').textContent='until next';
    return;}
  const r=document.querySelector('#list .ev[data-k="'+up.key+'"]');if(r)r.classList.add('daymark');
  const nm=clear($('next-name'));
  nm.append(el('span','gl',BODYG[up.body]||''),txt(' '+up.label));
  $('next-when').textContent=fmtDate(up.utc)+' · '+fmtClock(up.utc);
  let diff=Math.max(0,Math.floor((Date.parse(up.utc)-now)/1000));
  const d=Math.floor(diff/86400);diff-=d*86400;const h=Math.floor(diff/3600);diff-=h*3600;
  const m=Math.floor(diff/60),s=diff-m*60,pad=n=>String(n).padStart(2,'0');
  ct.firstChild.textContent=(d>0?d+'d ':'')+`${pad(h)}:${pad(m)}:${pad(s)}`;
  $('count-lbl').textContent='until next';
}

/* SELECT DAY overlay menu (the day directory below stays for crawlers) */
(function(){
  var btn=$('yn-open'); if(!btn)return;
  var menu=null;
  function monthGrid(wrap,y,m,cur){
    wrap.appendChild(el('div','ym-decade',
      new Date(Date.UTC(y,m,1)).toLocaleDateString('en-US',{timeZone:'UTC',month:'long',year:'numeric'})));
    var g=el('div','ym-grid');
    var n=new Date(y,m+1,0).getDate(), p=x=>String(x).padStart(2,'0');
    for(var i=1;i<=n;i++){
      var iso=y+'-'+p(m+1)+'-'+p(i);
      var a=el('a',null,String(i)); a.href='#d='+iso;
      if(iso===cur){a.className='ym-cur'; a.setAttribute('aria-current','page');}
      a.addEventListener('click',(function(v){return function(e){e.preventDefault();close();gotoDay(v);};})(iso));
      g.appendChild(a);
    }
    wrap.appendChild(g);
  }
  function build(){
    menu=el('div'); menu.id='yn-menu'; menu.setAttribute('role','dialog');
    menu.setAttribute('aria-modal','true'); menu.setAttribute('aria-label','Select a day');
    menu.appendChild(el('div','ym-wrap'));
    menu.addEventListener('click',function(e){if(e.target===menu)close();});
    document.body.appendChild(menu);
  }
  function fill(){
    var wrap=clear(menu.querySelector('.ym-wrap'));
    var head=el('div','ym-head');
    var x=el('button','ym-close','× Close'); x.type='button'; x.onclick=close;
    var ty=el('a','ym-this','Today'); ty.href='#d='+todayIn(tz);
    ty.onclick=function(e){e.preventDefault();close();gotoDay(todayIn(tz));};
    head.append(x,el('h2',null,'Select day'),ty); wrap.appendChild(head);
    var y=+day.slice(0,4), m=+day.slice(5,7)-1;
    for(var k=-1;k<=1;k++){var t=new Date(Date.UTC(y,m+k,1));monthGrid(wrap,t.getUTCFullYear(),t.getUTCMonth(),day);}
  }
  function open(){ if(!menu)build(); fill(); menu.style.display='block'; document.body.style.overflow='hidden';
    var cur=menu.querySelector('.ym-cur'); if(cur)cur.scrollIntoView({block:'center'}); }
  function close(){ if(menu){menu.style.display='none';} document.body.style.overflow=''; }
  btn.addEventListener('click',open);
  window.addEventListener('keydown',function(e){if(e.key==='Escape')close();});
})();

/* the crawlable day directory below the list, rebuilt for the active month */
function buildDayDir(host){
  var y=+day.slice(0,4), m=+day.slice(5,7)-1, p=x=>String(x).padStart(2,'0');
  var n=new Date(y,m+1,0).getDate();
  /* the heading and the month label move with the grid, or the page shows one
     month's days under another month's title */
  var ml=new Date(Date.UTC(y,m,1)).toLocaleDateString('en-US',{timeZone:'UTC',month:'long',year:'numeric'});
  var hh=$('day-dir-h'); if(hh)hh.textContent='Browse Every Day of '+ml;
  var mm=$('day-dir-m'); if(mm)mm.textContent=ml;
  clear(host);
  for(var i=1;i<=n;i++){
    var iso=y+'-'+p(m+1)+'-'+p(i);
    var a=el('a',null,String(i)); a.href='#d='+iso;
    if(iso===day)a.setAttribute('aria-current','page');
    a.addEventListener('click',(function(v){return function(e){e.preventDefault();gotoDay(v);};})(iso));
    host.appendChild(a);
  }
}

/* the note bar + the footer, rebuilt whenever the day, place or dial changes */
function para(parts){const p=el('p');
  parts.forEach(x=>p.append(typeof x==='string'?txt(x):x));return p;}
function b(t){return el('b',null,t);}
function chrome(){
  var d=DATA||{}, mn=d.moon||{}, ob=d.observer||{}, dl=d.day_length_s;
  var note=clear($('moonnote'));
  note.append(para(['Times shown for ',b(locLabelTZ()),', to the second.']));
  note.append(para([b('SWISS'),' (DE441) solves every event of this day on your device. An independent ',
    b('NOAA'),' implementation verifies the ladder event by event.']));
  var lenBits;
  if(dl==null)lenBits=['Day length could not be determined for this day. '];
  else if(dl===0)lenBits=['Day length ',b('0h 0m'),' - The Sun does not rise. '];
  else lenBits=['Day length ',b(Math.floor(dl/3600)+'h '+Math.floor(dl%3600/60)+'m '+(dl%60)+'s'),
    ', sunrise to the sunset that follows it. '];
  note.append(para(lenBits.concat(['The Moon is ',b((mn.illumination_pct!=null?mn.illumination_pct:0).toFixed(1)+'%'),
    ' illuminated, ',b((mn.apparent_diameter_arcsec!=null?mn.apparent_diameter_arcsec:0).toFixed(1)+'"'),' across.'])));
  note.append(para([b('Topocentric'),' = the sky from where you stand. Your latitude, longitude and elevation '+
    'move every time on this page - Computed on your device, never sent anywhere.']));
  var src=el('p','srcnote');
  src.append(txt('SUNMAP runs the '),b('Swiss Ephemeris'),txt(' (© Astrodienst AG) on your device under the '),
    b('AGPL-3.0'),txt(' free license. '));
  var sa=el('a',null,'Source & licenses'); sa.href=B+'source.html'; src.append(sa,txt('.'));
  note.append(src);

  var latAbs=Math.abs(+ob.lat||0);
  var rows=[
    [b('Engine:'),' '+(d.engine||'Swiss Ephemeris (JPL DE441), swe_rise_trans, topocentric')],
    [b('Observer:'),' '+(+ob.lat||0).toFixed(4)+', '+(+ob.lon||0).toFixed(4)+', '+Math.round(+ob.alt_m||0)+' m - Nothing leaves this device.'],
    [b('Precision:'),' Every instant lands on the second. Almanacs stop at the minute.'],
  ];
  if(latAbs>=66.5)rows.push([b('Latitude note:'),' Above the polar circle whole events stop happening for weeks at a time - Those rows say so rather than showing a time.']);
  else if(latAbs>=60)rows.push([b('Latitude note:'),' This far north the twilight ladder can run out before it finishes - Missing rows are real, not errors.']);
  rows.push([b('Geosearch:'),' OpenStreetMap (Photon / Nominatim). Locations stay on your device.']);
  rows.push([b('Verification:'),' scripts/verify_solar.py, an independent NOAA-algorithm implementation.']);
  var foot=clear($('foot'));
  rows.forEach(function(r,i){foot.append(r[0],txt(r[1]));if(i<rows.length-1)foot.append(el('br'));});
  localizeTimes();
}
/* Re-render every baked instant in the FAQ in the viewer's timezone */
function localizeTimes(){
  var zs=document.querySelectorAll('.faq time[datetime]');
  for(var i=0;i<zs.length;i++){
    var t=zs[i], iso=t.getAttribute('datetime');
    try{
      t.textContent = t.hasAttribute('data-d')
        ? new Date(iso).toLocaleDateString('en-US',{timeZone:tz,month:'long',day:'numeric',year:'numeric'})
        : toSec(iso).toLocaleString('en-US',Object.assign({month:'long',day:'numeric',year:'numeric'},clockOpts()));
    }catch(e){}
  }
}

// Hieroglyph glyph-scramble (ported from the main site's GlitchText): click the sigil to scramble
// the title + subtitle through sacred glyphs, revealing left-to-right over ~900ms.
var GLITCH = [0x0030,0x0031,0x1F701,0x1F702,0x1F703,0x1F704,0x1F70A,0x1F74E,0x13080,0x1309D,0x1317F,0x131A3,0x131B3,0x131B8,0x131B9,0x131C5,0x131CB,0x131F3,0x131FA,0x131FC,0x13216,0x13250,0x13283,0x13296,0x132A2,0x132A4,0x132A8,0x132B5,0x132BD,0x132D4,0x132DD,0x132DE,0x132F9,0x132FF,0x13300,0x1336F,0x133C1,0x133CF,0x133F4,0x2297,0x260A,0x260B,0x2643,0x2644,0x2645,0x2646,0x2647,0x26B8,0x16A0,0x16A2,0x16A6,0x16A8,0x16B1,0x16B2,0x16B7,0x16B9,0x16BA,0x16BE,0x16C1,0x16C3,0x16C5,0x16C7,0x16C8,0x16C9,0x16CB,0x16CF,0x16D2,0x16D6,0x16D7,0x16DA,0x16DC,0x16DE,0x16DF,0x16E2].map(function(c){return String.fromCodePoint(c);});
function scramble(sEl){
  if(!sEl) return;
  var text = sEl.getAttribute('data-text') || sEl.textContent;
  sEl.setAttribute('data-text', text);
  var dur=900, start=Date.now();
  if(sEl._iv) clearInterval(sEl._iv);
  sEl._iv = setInterval(function(){
    var e = Date.now()-start;
    if(e>=dur){ clearInterval(sEl._iv); sEl._iv=null; sEl.textContent=text; return; }
    var rev = Math.floor(e/dur*text.length), out='';
    for(var i=0;i<text.length;i++){ out += (i<rev) ? text[i] : (text[i]===' ' ? ' ' : GLITCH[Math.floor(Math.random()*GLITCH.length)]); }
    sEl.textContent = out;
  }, 50);
}
(function(){
  var sig = document.querySelector('.sigil');
  if(!sig) return;
  sig.style.cursor = 'pointer';
  sig.addEventListener('click', function(e){
    if(window.__puddyBurst) window.__puddyBurst(e.clientX, e.clientY);
    scramble(document.querySelector('.crest h1 .wm'));
    var spans = document.querySelectorAll('.subtitle span');
    for(var i=0;i<spans.length;i++) scramble(spans[i]);
  });
})();

/* ---- boot ---- */
load();buildControls();syncDayNav();
GEO.onChange(function(l){
  if(!l||!isFinite(l.lat)||!isFinite(l.lon))return;
  var first=!loc;
  loc=l;
  try{new Intl.DateTimeFormat('en-US',{timeZone:l.tz});tz=l.tz;}catch(e){}
  if(first)day=todayIn(tz);
  syncDayNav();buildControls();compute();
});
GEO.initLocation().catch(function(){});
setInterval(tick,1000);
dayHash();
</script>
<script>
(function(){
  // Beams of light, the SUNMAP field. Structurally the STARMAP particle-mesh
  // background (same canvas, same count/DPR/resize/mouse/burst plumbing); the
  // drawing routine is the only difference. Each beam is a long, thin, low-alpha
  // shaft that drifts across the page and fades in and out on a life cycle, and
  // the whole field is deliberately near-invisible, exactly as STARMAP's is.
  var c=document.getElementById('stars'); if(!c||!c.getContext) return;
  var ctx=c.getContext('2d'), DPR=Math.min(window.devicePixelRatio||1,2);
  var W=0, H=0, MOBILE=false, parts=[], mouse={x:0,y:0,active:false}, INTENSITY=0.8;
  var ANG=-Math.PI/3.2;  // the shared shaft direction: light falling from the upper left
  // PLUTO sand-300 #ceba9d - the locked PUDDY gold, and the ONLY colour in the field.
  // Held as a channel triplet because every alpha here is computed per frame.
  var BEAM='206,186,157';
  function count(){var area=W*H;
    if(MOBILE) return Math.max(8, Math.min(Math.floor(area/60000)*INTENSITY, 16));
    return Math.max(14, Math.min(Math.floor(area/34000)*INTENSITY, 46));}
  function build(){
    var w=document.documentElement.clientWidth||window.innerWidth;
    var h=window.innerHeight||document.documentElement.clientHeight;
    if(w<2||h<2||(w===W&&h===H)) return;
    W=w; H=h; MOBILE=W<768; DPR=MOBILE?1:Math.min(window.devicePixelRatio||1,2);
    c.width=Math.round(W*DPR); c.height=Math.round(H*DPR);
    ctx.setTransform(DPR,0,0,DPR,0,0);
    var n=count(); parts=[];
    for(var i=0;i<n;i++){parts.push({x:Math.random()*W, y:Math.random()*H,
      vx:(Math.random()-0.5)*0.3, vy:(Math.random()-0.5)*0.3,
      life:Math.random()*100, maxLife:150+Math.random()*100,
      len:120+Math.random()*260, size:Math.random()*1.4+0.6});}
  }
  function paint(){
    ctx.clearRect(0,0,W,H);
    var dx=Math.cos(ANG), dy=Math.sin(ANG);
    for(var k=0;k<parts.length;k++){var p=parts[k];
      if(mouse.active){var ax=mouse.x-p.x, ay=mouse.y-p.y, ad=Math.sqrt(ax*ax+ay*ay);
        if(ad<120){var f=(120-ad)/120; p.vx-=(ax/ad)*f*0.3; p.vy-=(ay/ad)*f*0.3;}}
      p.x+=p.vx; p.y+=p.vy; p.life++; p.vx*=0.99; p.vy*=0.99;
      if(p.x<0)p.x=W; if(p.x>W)p.x=0; if(p.y<0)p.y=H; if(p.y>H)p.y=H;
      var op=Math.sin((p.life/p.maxLife)*Math.PI)*0.30;
      var x2=p.x+dx*p.len, y2=p.y+dy*p.len;
      var g=ctx.createLinearGradient(p.x,p.y,x2,y2);
      // Gold at the source, dissolving to nothing along the shaft. A linear ramp from
      // op to 0 integrates to the same 0.5*op mean as the centre-peaked ramp it
      // replaces, so the field carries the SAME total light as before - it just falls
      // off in one direction instead of two. It stays as near-invisible as STARMAP's.
      g.addColorStop(0,'rgba('+BEAM+','+op+')');
      g.addColorStop(1,'rgba('+BEAM+',0)');
      ctx.beginPath(); ctx.strokeStyle=g; ctx.lineWidth=p.size; ctx.lineCap='round';
      ctx.moveTo(p.x,p.y); ctx.lineTo(x2,y2); ctx.stroke();
      // The mote riding the shaft - the dust that makes a beam visible at all. It used
      // to sit at the midpoint because that was the shaft's brightest point; with the
      // peak moved to the source it rides at t=0.25 instead, and its alpha is the same
      // 0.8 fraction of the shaft's LOCAL value there (0.8 * op * (1-0.25) = 0.6*op),
      // so it never becomes a bright dot floating on a dim shaft.
      ctx.beginPath(); ctx.fillStyle='rgba('+BEAM+','+(op*0.6)+')';
      ctx.arc(p.x+dx*p.len*0.25, p.y+dy*p.len*0.25, p.size*0.7, 0, 6.2832); ctx.fill();
      if(p.life>p.maxLife){p.life=0; p.x=Math.random()*W; p.y=Math.random()*H;}
    }
  }
  function frame(){ paint(); requestAnimationFrame(frame); }
  var rt;
  function schedule(){clearTimeout(rt); rt=setTimeout(build,150);}
  if(window.ResizeObserver){try{new ResizeObserver(schedule).observe(document.documentElement);}catch(e){}}
  window.addEventListener('resize', schedule);
  window.addEventListener('mousemove', function(e){mouse.x=e.clientX; mouse.y=e.clientY; mouse.active=true;});
  window.addEventListener('mouseout', function(){mouse.active=false;});
  window.__puddyBurst = function(cx, cy){
    for(var i=0;i<parts.length;i++){ var p=parts[i];
      var dx=p.x-cx, dy=p.y-cy, d=Math.sqrt(dx*dx+dy*dy)||1;
      var f=Math.min(80, 600/(d*0.1+1));
      p.vx += (dx/d)*f*0.15; p.vy += (dy/d)*f*0.15; }
  };
  build(); paint(); requestAnimationFrame(frame);
})();
if('serviceWorker' in navigator){
  window.addEventListener('load', function(){
    navigator.serviceWorker.register('__B__sw.js').catch(function(){});
  });
}
</script>
</body>
</html>"""

# Puddy radiant-sun sigil (per puddy-sigil-methodology-reference.md), built the same way
# STARMAP's cosmographic mandala is: 21 nodes (Sun at centre + corona ring of 10 + ray-tip
# ring of 10), every node = the #puddy-face symbol, 3 concentric spheres at the same radii.
# Sacred-geometry weight in the edges: a decagram {10/3} across the corona, 20 straight
# radial rays (centre -> corona -> tip), and 10 interleaved short rays on the half-step
# angles. Min chord 27.2u (corona ring) >= 22 floor.
# Hate-symbol audit (RULE 15.8): 10-fold, in the sanctioned 5-fold family. NOT 12-fold
# (no sonnenrad / black sun), NOT 4-fold, no rotation between rings, every arm perfectly
# straight and radial - no bent, hooked or pinwheel arms - and no outer rim polygon, so
# the form reads as a radiant sun and never as a spoked wheel. No hexagram.
#
# COLOUR. The faces are white on black, exactly as STARMAP's are - the #puddy-face
# symbol is copied verbatim and is never recoloured. The only other colour in the
# crest is PLUTO sand-300, the locked PUDDY gold (brand/PLUTO_PALETTE.md), and it
# is an ACCENT, never a wash: it marks the SOLAR CORE only - the r=30 limb and the
# ten short rays leaving it. That is 11 hairline strokes out of 51; everything
# further out (the r=64 and r=92 spheres, the 20 radial rays, the corona decagram)
# stays #fff, so the crest keeps STARMAP's near-monochrome restraint. Gold at the
# source is the same rule the beam field follows.
_GOLD = '#ceba9d'                            # PLUTO sand-300 - LOCKED, never derived
_CX = _CY = 100.0
_N = 10


def _ring(r, n, off=-math.pi / 2):
    return [(_CX + r * math.cos(off + _i * 2 * math.pi / n),
             _CY + r * math.sin(off + _i * 2 * math.pi / n)) for _i in range(n)]


_corona = _ring(44.0, _N)
_tips = _ring(86.0, _N)
_nodes = [(_CX, _CY)] + _corona + _tips      # 0 = centre, 1-10 = corona, 11-20 = tips


def _C(i): return 1 + (i % _N)


def _T(i): return 1 + _N + (i % _N)


_edges = []
_edges += [(0, _C(i)) for i in range(_N)]              # centre -> corona (the inner ray)
_edges += [(_C(i), _T(i)) for i in range(_N)]          # corona -> tip (the outer ray)
_edges += [(_C(i), _C(i + 3)) for i in range(_N)]      # corona decagram {10/3}
_p = []
for _r in (92.0, 64.0, 30.0):
    # r=30 is the solar limb, the edge of the disc itself - the one sphere that takes
    # the gold. The two outer spheres are structure, and structure stays white.
    _s = _GOLD if _r == 30.0 else '#fff'
    _p.append(f'<circle cx="100" cy="100" r="{_r:.0f}" fill="none" stroke="{_s}" stroke-width="1" opacity="0.4"/>')
# the 10 interleaved short rays, on the half-step angles, r=30 -> r=64. These leave the
# limb, so they carry the gold with them and stop at the middle sphere - the accent is
# contained inside the inner third of the crest and never reaches the rim.
for _i in range(_N):
    _a = -math.pi / 2 + (_i + 0.5) * 2 * math.pi / _N
    _p.append('<line x1="{:.2f}" y1="{:.2f}" x2="{:.2f}" y2="{:.2f}" stroke="{}" stroke-width="1.5" opacity="0.55"/>'.format(
        _CX + 30.0 * math.cos(_a), _CY + 30.0 * math.sin(_a),
        _CX + 64.0 * math.cos(_a), _CY + 64.0 * math.sin(_a), _GOLD))
for _a, _b in _edges:
    _x1, _y1 = _nodes[_a]
    _x2, _y2 = _nodes[_b]
    _p.append(f'<line x1="{_x1:.2f}" y1="{_y1:.2f}" x2="{_x2:.2f}" y2="{_y2:.2f}" stroke="#fff" stroke-width="1.5" opacity="0.8"/>')
_GEOM = ''.join(_p)                          # the structure alone - spheres, rays, decagram
for _cx, _cy in _nodes:
    _p.append(f'<use href="#puddy-face" x="{_cx-7:.2f}" y="{_cy-7:.2f}" width="14" height="14"/>')
_SIGIL = ''.join(_p)

# THE FAVICON is the SAME crest, generated from the SAME geometry, so the two can never
# drift apart. It is emitted by this script rather than hand-kept, because a hand-kept
# favicon is exactly how an off-canon colour got onto the page: the file this replaces
# was a drawn amber sun on an invented yellow that appears nowhere in the PLUTO ramp.
# The hex is deliberately not repeated here, so a colour sweep of this tree stays clean.
# At 16px a 14px puddy-face is illegible, so the nodes render as plain discs - the same
# substitution STARMAP makes in its own favicon (r=5.2, #fff). Transparent ground and
# the 200x200 viewBox match STARMAP's ("favicon all white, always", d8ef9a2); the only
# departure is SUNMAP's own accent, the gold solar core, unchanged from the crest.
_FAVICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">'
            + _GEOM
            + ''.join(f'<circle cx="{_cx:.2f}" cy="{_cy:.2f}" r="5.2" fill="#fff"/>'
                      for _cx, _cy in _nodes)
            + '</svg>\n')

# ---------------- per-page build engine (SEO prerender + FAQ + JSON-LD + PWA) ----------------
import json as _json
import html as _html
import hashlib as _hashlib
from datetime import datetime as _dt, timedelta as _td
from zoneinfo import ZoneInfo as _ZoneInfo

# The engine. First-party sibling module; it is the SAME solver the browser runs
# (sunmap-worker.js is a port of it), so the prerendered ladder and the hydrated
# one cannot disagree. STARMAP's render.py read pre-generated JSON and needed no
# engine; a SUNMAP day is per-observer, so there is nothing to pre-generate and
# the engine has to run here.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import solar as _solar
except ImportError as _e:  # pragma: no cover - a build without the engine is a wrong build
    raise SystemExit(
        'render.py needs the SUNMAP engine: %s\n'
        'Install pyswisseph (pip install pyswisseph) and rebuild. Emitting a page '
        'without a prerendered ladder would ship an empty crawlable surface.' % _e)

# The default observer. The tzdata principal point for America/New_York - the
# same real, sourced coordinates sunmap-geo.js defaults to, so the prerendered
# page and a first-visit-before-geolocation page agree.
OBS_LAT, OBS_LON, OBS_ALT = 40.7142, -74.0064, 0.0
OBS_TZ = 'America/New_York'
OBS_LABEL = 'New York City'

_PT = _ZoneInfo(OBS_TZ)
_MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
           'August', 'September', 'October', 'November', 'December']

DAY = (_dt.strptime(_args.date, '%Y-%m-%d').date() if _args.date
       else _dt.now(_PT).date())

# ---- ladder tables, derived from the engine so they cannot drift ----
_LADDER_JS = [[k, lab, body] for (k, lab, body, _d, _m, _p2, _t) in _solar.LADDER]

GLOSS = {
    'astronomical_dawn': 'Sun centre 18 deg below the horizon. The first light.',
    'nautical_dawn': 'Sun centre 12 deg below. The sea horizon becomes visible.',
    'civil_dawn': 'Sun centre 6 deg below. Outdoor work needs no lamp.',
    'golden_hour_start_am': 'Sun centre 4 deg below. Warm, low, long-shadowed light.',
    'sunrise': 'The upper limb clears the horizon, refraction included.',
    'golden_hour_end_am': 'Sun centre passes 6 deg above, climbing.',
    'solar_noon': 'Upper transit. The Sun is due south or north, and highest.',
    'golden_hour_start_pm': 'Sun centre drops back through 6 deg above.',
    'sunset': 'The upper limb touches the horizon, refraction included.',
    'golden_hour_end_pm': 'Sun centre 4 deg below. The warm light is gone.',
    'civil_dusk': 'Sun centre 6 deg below. Lamps come on.',
    'nautical_dusk': 'Sun centre 12 deg below. The sea horizon is lost.',
    'astronomical_dusk': 'Sun centre 18 deg below. Full astronomical night.',
    'solar_midnight': 'Lower transit. The Sun is at its lowest, below the horizon.',
    'moonrise': 'The upper limb of the Moon clears the horizon.',
    'lunar_noon': 'Upper transit. The Moon is highest in your sky.',
    'moonset': 'The upper limb of the Moon touches the horizon.',
    'lunar_midnight': 'Lower transit. The Moon is at its lowest.',
}
_missing = [k for (k, *_r) in _LADDER_JS if k not in GLOSS]
if _missing:
    raise SystemExit('GLOSS is missing engine ladder keys: %s' % ', '.join(_missing))


def _prec_of(spec):
    """The geometric definition of one ladder row, read off the engine's own spec."""
    _k, _lab, _body, direction, _mode, _rsmi, thr = spec
    if thr is not None:
        return 'Centre %+.2f deg' % thr
    if direction == _solar.TRANSIT_UP:
        return 'Upper transit'
    if direction == _solar.TRANSIT_DOWN:
        return 'Lower transit'
    return 'Upper limb, refracted'


PREC = {spec[0]: _prec_of(spec) for spec in _solar.LADDER}

# The honest sentence for every non-event, keyed the way the engine keys its
# statuses. Built from the ladder so a new row cannot slip through untranslated.
_WHO = {'sun': 'The Sun', 'moon': 'The Moon'}
NONE_TEXT = {}
for _spec in _solar.LADDER:
    _k, _lab, _body = _spec[0], _spec[1], _spec[2]
    _who = _WHO[_body]
    # A rise and a set are the same fact seen twice: if the body never crosses
    # the horizon it neither rises NOR sets, so both rows say so. Naming only
    # one half ("the Moon never sets") on the moonRISE row reads as a mistake.
    if _k in ('sunrise', 'sunset'):
        _above = 'None - Polar day. The Sun is above the horizon all day, so it neither rises nor sets.'
        _below = 'None - Polar night. The Sun is below the horizon all day, so it neither rises nor sets.'
    elif _k in ('moonrise', 'moonset'):
        _above = 'None - Circumpolar. The Moon is above the horizon all day, so it neither rises nor sets.'
        _below = 'None - The Moon is below the horizon all day, so it neither rises nor sets.'
    else:
        _above = 'None - %s stays above this altitude all day.' % _who
        _below = 'None - %s stays below this altitude all day.' % _who
    NONE_TEXT[_k] = {
        'always_above': _above,
        'always_below': _below,
        'none_today': 'None - No crossing of this threshold falls inside this local day.',
    }

CATS = [
    {'key': 'sun', 'label': 'Sun', 'def': True,
     'keys': ['sunrise', 'sunset', 'solar_noon', 'solar_midnight']},
    {'key': 'twilight', 'label': 'Twilight', 'def': True,
     'keys': ['astronomical_dawn', 'nautical_dawn', 'civil_dawn',
              'civil_dusk', 'nautical_dusk', 'astronomical_dusk']},
    {'key': 'golden', 'label': 'Golden hour', 'def': True,
     'keys': ['golden_hour_start_am', 'golden_hour_end_am',
              'golden_hour_start_pm', 'golden_hour_end_pm']},
    {'key': 'moon', 'label': 'Moon', 'def': True,
     'keys': ['moonrise', 'lunar_noon', 'moonset', 'lunar_midnight']},
]
_covered = {k for c in CATS for k in c['keys']}
_uncovered = [k for (k, *_r) in _LADDER_JS if k not in _covered]
if _uncovered:
    raise SystemExit('No chip covers engine ladder keys: %s' % ', '.join(_uncovered))


# ---------------- day helpers (build-time formatting of the engine's output) ----------------

def _first(day_data, key):
    """The first occurrence of one ladder key, or None when it did not happen."""
    for e in day_data['events']:
        if e['key'] == key and e['local']:
            return e
    return None


def _status(day_data, key):
    for e in day_data['events']:
        if e['key'] == key:
            return e['status']
    return 'none_today'


def _lt(e):
    """The local instant, rounded to the second the way the engine's CLI rounds it.

    astimezone(_PT) is load-bearing: fromisoformat() returns a FIXED-OFFSET
    tzinfo built from the '-04:00' in the string, and strftime('%Z') on that
    prints "UTC-04:00". Re-attaching the real ZoneInfo prints "EDT".
    """
    return ((_dt.fromisoformat(e['local']).astimezone(_PT) + _td(milliseconds=500))
            .replace(microsecond=0))


def _clock(e):
    return _lt(e).strftime('%-I:%M:%S %p %Z').strip()


def _hm(e):
    return _lt(e).strftime('%-I:%M %p').strip()


def _fmt(e):
    return _lt(e).strftime('%B %-d, %Y at %-I:%M:%S %p %Z').strip()


def _fmt_t(e):
    """Visible-FAQ variant: a <time> element the page re-renders in the viewer's timezone."""
    return f'<time datetime="{_html.escape(e["utc"])}">{_html.escape(_fmt(e))}</time>'


def _dur(secs):
    if secs is None:
        return None
    h, rem = divmod(int(secs), 3600)
    m, s = divmod(rem, 60)
    return f'{h} hours {m} minutes {s} seconds'


def _long(d):
    return d.strftime('%A, %B %-d, %Y')


def _day_summary(day_data, d):
    """A unique, data-derived prose paragraph - different on every day."""
    s = []
    sr, ss = _first(day_data, 'sunrise'), _first(day_data, 'sunset')
    st = _status(day_data, 'sunrise')
    if sr and ss:
        s.append(f'On {_long(d)} the Sun rises over {OBS_LABEL} at {_clock(sr)} '
                 f'and sets at {_clock(ss)}.')
    elif st == 'always_above':
        s.append(f'On {_long(d)} the Sun never sets over {OBS_LABEL} - It is polar day.')
    elif st == 'always_below':
        s.append(f'On {_long(d)} the Sun never rises over {OBS_LABEL} - It is polar night.')
    else:
        s.append(f'On {_long(d)} neither a sunrise nor a sunset falls inside the '
                 f'local day at {OBS_LABEL}.')
    # The day-length sentence only makes sense once a rise and a set were named.
    # Polar day returns the full local-day window, which is a true number but
    # "a day 24 hours 0 minutes 0 seconds long" is not what it means.
    if sr and ss and day_data.get('day_length_s'):
        s.append(f'That is a day {_dur(day_data["day_length_s"])} long.')
    elif st == 'always_above':
        s.append('The Sun stays above the horizon for the entire local day.')
    ga, gb = _first(day_data, 'golden_hour_start_am'), _first(day_data, 'golden_hour_end_am')
    gc, gd = _first(day_data, 'golden_hour_start_pm'), _first(day_data, 'golden_hour_end_pm')
    if ga and gb and gc and gd:
        s.append(f'Golden hour runs {_hm(ga)} to {_hm(gb)} in the morning and '
                 f'{_hm(gc)} to {_hm(gd)} in the evening.')
    ad = _first(day_data, 'astronomical_dusk')
    if ad:
        s.append(f'Full astronomical night begins at {_clock(ad)}.')
    elif _status(day_data, 'astronomical_dusk') == 'always_above':
        s.append('Full astronomical night never arrives - The sky does not darken that far.')
    mr, ms = _first(day_data, 'moonrise'), _first(day_data, 'moonset')
    ill = day_data['moon']['illumination_pct']
    if mr and ms:
        s.append(f'The Moon rises at {_clock(mr)} and sets at {_clock(ms)}, {ill:.1f} percent illuminated.')
    elif mr:
        s.append(f'The Moon rises at {_clock(mr)} and does not set inside this day, '
                 f'{ill:.1f} percent illuminated.')
    elif ms:
        s.append(f'The Moon sets at {_clock(ms)} and does not rise again inside this day, '
                 f'{ill:.1f} percent illuminated.')
    else:
        s.append(f'The Moon is {ill:.1f} percent illuminated, with neither a rise nor a set '
                 'inside this local day.')
    return ' '.join(s)


def _build_page(d):
    """Render the page for one local day at the default observer."""
    day_data = _solar.day_events(OBS_LAT, OBS_LON, OBS_ALT, d, OBS_TZ)
    evs = day_data['events']
    sr, ss = _first(day_data, 'sunrise'), _first(day_data, 'sunset')
    dl_s = day_data.get('day_length_s')
    ill = day_data['moon']['illumination_pct']
    dia = day_data['moon']['apparent_diameter_arcsec']

    # --- prerendered crawlable list (the JS list hydrates over it) ---
    pre = [f'<p class="seo-lead">{_html.escape(_day_summary(day_data, d))} '
           'Every twilight, golden hour, transit, moonrise and moonset below is solved to the '
           f'second with the Swiss Ephemeris (DE441) for {_html.escape(OBS_LABEL)} - Choose your '
           'own location on the page and the whole ladder recomputes on your device, for your '
           'latitude, longitude, elevation and day.</p>',
           f'<h2>{_html.escape(_long(d))} - {_html.escape(OBS_LABEL)}</h2><ul>']
    for e in evs:
        glyph = '☉' if e['body'] == 'sun' else '☽'
        if e['local']:
            pre.append(f'<li><time datetime="{_html.escape(e["utc"])}">{_html.escape(_clock(e))}</time> '
                       f'{glyph} {_html.escape(e["label"])}</li>')
        else:
            txt = NONE_TEXT.get(e['key'], {}).get(e['status'], 'None - ' + e['status'])
            pre.append(f'<li>{glyph} {_html.escape(e["label"])} - {_html.escape(txt)}</li>')
    pre.append('</ul>')
    prerender = ''.join(pre)

    # --- day directory (crawlable, and the in-page month jumper) ---
    _last = (d.replace(day=28) + _td(days=4)).replace(day=1) - _td(days=1)
    # The heading and the month label carry ids because buildDayDir() rewrites the
    # grid on every day change - without them the page would show December's days
    # under an "August 2026" heading.
    ydir = [f'<h2 id="years"><span id="day-dir-h">Browse Every Day of {_MONTHS[d.month-1]} {d.year}</span></h2>',
            '<p class="lead">Every day is solved live on your device, for wherever you are '
            'standing - Sunrise, sunset, all three twilights, both golden hours, solar noon and '
            'midnight, and the Moon. Pick a day, or step with the arrows above.</p>',
            f'<div class="decade" id="day-dir-m">{_MONTHS[d.month-1]} {d.year}</div>',
            '<div class="ygrid" id="day-dir">']
    for _dd in range(1, _last.day + 1):
        iso = f'{d.year:04d}-{d.month:02d}-{_dd:02d}'
        cur = ' aria-current="page"' if _dd == d.day else ''
        ydir.append(f'<a href="#d={iso}"{cur}>{_dd}</a>')
    ydir.append('</div>')
    years_dir = ''.join(ydir)

    # --- FAQ (computed from the data) ---
    # Each entry carries (question, plain_answer, html_answer): plain goes to the
    # FAQPage JSON-LD; html carries <time> elements the page re-renders in the
    # viewer's timezone the moment they choose a location.
    dstr = d.strftime('%B %-d, %Y')
    faq = []

    q1 = f'What time is sunrise and sunset in {OBS_LABEL} on {dstr}?'
    if sr and ss:
        tail1 = f' That is a day {_dur(dl_s)} long.' if dl_s else ''
        # "on <full datetime>", never "at <full datetime>" - _fmt already carries
        # its own "at", and the page swaps these <time> nodes for full datetimes
        # in the viewer's zone, so the sentence has to read right at full length.
        faq.append((q1,
                    f'Sunrise falls on {_fmt(sr)} and sunset on {_fmt(ss)}.' + tail1,
                    f'Sunrise falls on {_fmt_t(sr)} and sunset on {_fmt_t(ss)}.' + _html.escape(tail1)))
    else:
        a1 = (f'Neither a sunrise nor a sunset falls inside {dstr} at {OBS_LABEL}: '
              + NONE_TEXT['sunrise'].get(_status(day_data, 'sunrise'), 'the crossing did not occur')
                .replace('None - ', '').rstrip('.') + '.')
        faq.append((q1, a1, _html.escape(a1)))

    ga, gb = _first(day_data, 'golden_hour_start_am'), _first(day_data, 'golden_hour_end_am')
    gc, gd = _first(day_data, 'golden_hour_start_pm'), _first(day_data, 'golden_hour_end_pm')
    q2 = f'When is golden hour on {dstr}?'
    if ga and gb and gc and gd:
        tail2 = (' Golden hour is bounded by the Sun centre passing 4 degrees below and 6 degrees '
                 'above the horizon, so it moves with your latitude and the season, not by a fixed hour.')
        faq.append((q2,
                    f'Morning golden hour runs from {_fmt(ga)} to {_fmt(gb)}. Evening golden hour '
                    f'runs from {_fmt(gc)} to {_fmt(gd)}.' + tail2,
                    f'Morning golden hour runs from {_fmt_t(ga)} to {_fmt_t(gb)}. Evening golden hour '
                    f'runs from {_fmt_t(gc)} to {_fmt_t(gd)}.' + _html.escape(tail2)))
    else:
        a2 = (f'Golden hour does not complete on {dstr} at {OBS_LABEL} - The Sun does not cross '
              'both of its bounding altitudes inside this local day, so no window is reported '
              'rather than a made-up one.')
        faq.append((q2, a2, _html.escape(a2)))

    ad, aw = _first(day_data, 'astronomical_dusk'), _first(day_data, 'astronomical_dawn')
    q3 = f'When does it get fully dark on {dstr}?'
    if ad and aw:
        # Dusk and dawn are stated as two separate instants, never as one
        # interval: both belong to this local day, but the dawn closes the
        # PREVIOUS night, so "begins 4:56 PM and ends 6:28 AM" reads backwards.
        tail3 = (' Full astronomical night is the Sun centre 18 degrees below the horizon, the '
                 'point at which sunlight stops contributing to the sky at all. The dusk closes '
                 'this day and the dawn opened it.')
        faq.append((q3,
                    f'Astronomical dusk falls on {_fmt(ad)}, and astronomical dawn on {_fmt(aw)}.' + tail3,
                    f'Astronomical dusk falls on {_fmt_t(ad)}, and astronomical dawn on {_fmt_t(aw)}.' + _html.escape(tail3)))
    else:
        a3 = (f'It does not get fully dark on {dstr} at {OBS_LABEL}. The Sun centre never reaches '
              '18 degrees below the horizon inside this local day, so there is no astronomical '
              'night to report.')
        faq.append((q3, a3, _html.escape(a3)))

    mr, ms = _first(day_data, 'moonrise'), _first(day_data, 'moonset')
    q4 = f'What is the Moon doing on {dstr}?'
    lead4 = f'The Moon is {ill:.1f} percent illuminated and {dia:.1f} arcseconds across. '
    if mr and ms:
        faq.append((q4, lead4 + f'It rises on {_fmt(mr)} and sets on {_fmt(ms)}.',
                    _html.escape(lead4) + f'It rises on {_fmt_t(mr)} and sets on {_fmt_t(ms)}.'))
    elif mr:
        faq.append((q4, lead4 + f'It rises on {_fmt(mr)} and does not set inside this local day.',
                    _html.escape(lead4) + f'It rises on {_fmt_t(mr)} and does not set inside this local day.'))
    elif ms:
        faq.append((q4, lead4 + f'It sets on {_fmt(ms)} and does not rise again inside this local day.',
                    _html.escape(lead4) + f'It sets on {_fmt_t(ms)} and does not rise again inside this local day.'))
    else:
        # WHY there is no moonrise decides the sentence. Three different facts
        # collapse into "no rise and no set", and only ONE of them is the lunar
        # day drifting past the calendar day: a circumpolar Moon is up the whole
        # time, and a Moon below the horizon never comes up at all. The ladder
        # rows already name which, from the same NONE_TEXT table, so the FAQ has
        # to read the status too or it contradicts the page it sits on.
        _mst = _status(day_data, 'moonrise')
        if _mst == 'none_today':
            a4 = (lead4 + 'Neither a moonrise nor a moonset falls inside this local day - The lunar '
                  'day runs 24 hours 50 minutes, so roughly once a month a calendar day contains neither.')
        else:
            a4 = (lead4 + f'Neither a moonrise nor a moonset falls inside {dstr} at {OBS_LABEL}: '
                  + NONE_TEXT['moonrise'].get(_mst, 'the crossing did not occur')
                    .replace('None - ', '').rstrip('.') + '.')
        faq.append((q4, a4, _html.escape(a4)))

    acc = ('Every instant is computed with the Swiss Ephemeris (DE441) on the JPL DE441 ephemerides '
           'and resolved to the second, topocentrically, for a specific latitude, longitude and '
           'elevation. An independent NOAA-algorithm implementation verifies the ladder event by '
           'event. The remaining uncertainty is not in the arithmetic, it is in the air: standard '
           'refraction at the horizon is 34 arcminutes and real atmosphere departs from it, so an '
           'observed sunrise against a real horizon can differ from any computed one by a few tens '
           'of seconds. Two limits are worth naming plainly. These times assume a level horizon at '
           'your own altitude, so the geometric dip you gain standing on a mountain, and the delay '
           'from a ridge or a building in the way, are not modelled. And your elevation is used for '
           'the air pressure at your altitude, which makes sunrise marginally later rather than '
           'earlier. Every other almanac rounds to the minute and hides all of it. SUNMAP prints '
           'the second and names the limit.')
    faq.append(('How accurate are these sunrise and sunset times?', acc, _html.escape(acc)))

    fh = [f'<h2>{_html.escape(_long(d))} - Frequently Asked Questions</h2>',
          '<p class="lead">SUNMAP is the most precise sunrise and sunset calculator on the web - '
          'The whole solar and lunar day to the second, in your own timezone and from where you '
          'actually stand. The answers below come straight from the data.</p>']
    # html answers are assembled from generator-controlled strings + escaped <time> attrs
    for q, _a_plain, a_html in faq:
        fh.append(f'<div class="qa"><h3>{_html.escape(q)}</h3><p>{a_html}</p></div>')
    faq_html = ''.join(fh)
    faq = [(q, a) for q, a, _h2 in faq]  # JSON-LD consumes the plain pairs

    # --- URLs + meta ---
    # Identity is PROD, always. OG_SITE is the only thing that follows the build
    # host, so a dev link preview resolves while prod is dark.
    page_url = PROD
    canonical = PROD
    og_img = f'{OG_SITE}og/sunmap-og.png'
    # Unique, data-driven description (real numbers from this day's data).
    _bits = []
    if sr:
        _bits.append(f'sunrise {_hm(sr)}')
    if ss:
        _bits.append(f'sunset {_hm(ss)}')
    if dl_s:
        _bits.append(f'{dl_s // 3600}h {(dl_s % 3600) // 60}m of daylight')
    _facts = ', '.join(_bits) if _bits else f'the full solar ladder for {OBS_LABEL}'
    title = 'SUNMAP | Sunrise, Sunset and Twilight - Timed to the Second'
    # Google truncates past about 160 characters, so this stays inside the
    # 50-170 window scripts/seo_check.py enforces. The long-form pitch lives in
    # og_desc below, where social cards give it room.
    desc = (f'Sunrise, sunset, twilight, golden hour and the Moon, solved to the second '
            f'for where you stand. {dstr} at {OBS_LABEL}: {_facts}.')
    if len(desc) > 170:
        desc = (f'Sunrise, sunset, twilight, golden hour and the Moon, solved to the '
                f'second for where you stand. {dstr} at {OBS_LABEL}.')
    # House style capitalizes the first word after a " - " separator, and _facts
    # is a lowercase fact list ("sunrise 6:01 AM, ...") built for mid-sentence use
    # in `desc`, so it gets an initial cap here and only here.
    og_desc = (f'The whole solar and lunar day to the second, topocentric to where you stand - '
               f'{_facts[:1].upper()}{_facts[1:]}')
    keywords = ('sunrise time, sunset time, golden hour calculator, blue hour, civil twilight, '
                'nautical twilight, astronomical twilight, moonrise time, moonset time, solar noon, '
                'day length calculator, sunrise sunset by location')
    og_title = title
    og_alt = 'SUNMAP: Sunrise, Sunset and Twilight to the Second - Puddy Studios social card'
    tw_title = title

    # --- JSON-LD ---
    crumbs = [{'@type': 'ListItem', 'position': 1, 'name': 'Puddy Studios', 'item': 'https://puddystudios.com/'},
              {'@type': 'ListItem', 'position': 2, 'name': 'Sunmap', 'item': PROD}]
    ld = {'@context': 'https://schema.org', '@graph': [
        {'@type': 'WebSite', '@id': 'https://puddystudios.com/#website', 'url': 'https://puddystudios.com/',
         'name': 'Puddy Studios', 'publisher': {'@id': 'https://puddystudios.com/#org'}},
        {'@type': 'Organization', '@id': 'https://puddystudios.com/#org', 'name': 'Puddy Studios',
         'url': 'https://puddystudios.com/', 'logo': 'https://puddystudios.com/puddy-logo.svg'},
        {'@type': 'ImageObject', '@id': f'{page_url}#primaryimage', 'url': og_img, 'contentUrl': og_img,
         'width': 2400, 'height': 1260,
         'caption': 'SUNMAP: Sunrise, Sunset and Twilight to the Second - Puddy Studios'},
        {'@type': ['WebPage', 'CollectionPage'], '@id': f'{page_url}#webpage', 'url': page_url,
         'name': title,
         'isPartOf': {'@id': 'https://puddystudios.com/#website'},
         'primaryImageOfPage': {'@id': f'{page_url}#primaryimage'},
         'image': {'@id': f'{page_url}#primaryimage'},
         'dateModified': d.isoformat(),
         'description': ('The whole solar and lunar day timed to the second on the Swiss Ephemeris '
                         'engine, topocentric to the observer.'),
         'about': ['Sunrise', 'Sunset', 'Twilight', 'Golden hour', 'Moonrise', 'Solar noon', 'Day length'],
         'breadcrumb': {'@id': f'{page_url}#breadcrumb'}},
        {'@type': 'BreadcrumbList', '@id': f'{page_url}#breadcrumb', 'itemListElement': crumbs},
        {'@type': 'Dataset', '@id': f'{page_url}#dataset',
         'name': 'The Solar and Lunar Day - Second Precision',
         'description': ('Sunrise, sunset, astronomical, nautical and civil twilight, both golden '
                         'hours, solar noon and solar midnight, moonrise, moonset, lunar noon and '
                         'lunar midnight - Solved to the second from the Swiss Ephemeris (DE441), '
                         'topocentrically for the observer, and cross-checked against an '
                         'independent NOAA-algorithm implementation.'),
         'url': page_url, 'image': og_img,
         'keywords': ['sunrise', 'sunset', 'twilight', 'golden hour', 'moonrise', 'moonset',
                      'solar noon', 'day length'],
         'temporalCoverage': f'{d.isoformat()}/{d.isoformat()}',
         'spatialCoverage': {'@type': 'Place', 'name': OBS_LABEL,
                             'geo': {'@type': 'GeoCoordinates', 'latitude': OBS_LAT, 'longitude': OBS_LON}},
         'creator': {'@id': 'https://puddystudios.com/#org'},
         'measurementTechnique': ('Swiss Ephemeris DE441 swe_rise_trans, topocentric; independent '
                                  'NOAA-algorithm cross-check'),
         'license': 'https://puddystudios.com/terms',
         'variableMeasured': 'Topocentric altitude threshold crossing times of the Sun and Moon'},
        {'@type': 'WebApplication', '@id': f'{PROD}#app', 'name': 'SUNMAP',
         'url': PROD, 'image': og_img, 'applicationCategory': 'UtilitiesApplication',
         'operatingSystem': 'Any', 'browserRequirements': 'Requires JavaScript',
         'description': ('The whole solar and lunar day - Sunrise, sunset, twilight, golden hour '
                         'and the Moon - Solved to the second on your own device for exactly where '
                         'you stand. Installable and offline-capable.'),
         'offers': {'@type': 'Offer', 'price': '0', 'priceCurrency': 'USD'}},
        {'@type': 'FAQPage', '@id': f'{page_url}#faq', 'mainEntity': [
            {'@type': 'Question', 'name': q, 'acceptedAnswer': {'@type': 'Answer', 'text': a}} for q, a in faq]},
    ]}
    jsonld = '<script type="application/ld+json">' + _json.dumps(ld, ensure_ascii=False) + '</script>'

    # --- day nav (the year nav's shape, stepping a day instead of a year) ---
    prev_iso, next_iso = (d - _td(days=1)).isoformat(), (d + _td(days=1)).isoformat()
    daynav = ('<div class="yn-select"><button id="yn-open" type="button" aria-haspopup="dialog">Select day</button></div>'
              '<div class="yn-spread">'
              f'<a href="#d={prev_iso}" id="day-prev" rel="prev">&laquo; Prev</a>'
              f'<span class="ynow" id="day-now">{_html.escape(d.strftime("%A, %B %-d"))}</span>'
              f'<a href="#d={next_iso}" id="day-next" rel="next">Next &raquo;</a>'
              '</div>'
              '<div class="yn-day">'
              f'<button type="button" id="day-input" class="day-box empty" aria-haspopup="dialog" aria-expanded="false" aria-label="Pick a date from {YEARS[0]} to {YEARS[-1]} - Scroll the month, day and year wheels">PICK A DATE</button>'
              '<div id="day-cal" hidden role="dialog" aria-label="Pick a day">'
              '<div class="dc-wheels">'
              '<div class="dc-col" id="dc-mon" role="listbox" aria-label="Month"></div>'
              '<div class="dc-col" id="dc-day" role="listbox" aria-label="Day"></div>'
              '<div class="dc-col" id="dc-yr" role="listbox" aria-label="Year"></div>'
              '<div class="dc-band" aria-hidden="true"></div>'
              '</div><button type="button" id="dc-go">Go to day</button></div>'
              '</div>')

    # --- apply (longest placeholder keys first so __DAY0__ never clobbers a longer key) ---
    repl = {
        '__PREVNEXT_LINKS__': '',
        '__ROBOTS__': ROBOTS,
        '__PRERENDER_LIST__': prerender,
        '__SIGIL_BODY__': _SIGIL,
        '__YEARS_DIR__': years_dir,
        '__CANONICAL__': canonical,
        '__KEYWORDS__': keywords,
        '__FAQ_HTML__': faq_html,
        '__YEARNAV__': daynav,
        '__H1YR__': '',
        '__LADDER__': _json.dumps(_LADDER_JS, ensure_ascii=False, separators=(',', ':')),
        '__GLOSS__': _json.dumps(GLOSS, ensure_ascii=False, separators=(',', ':')),
        '__PREC__': _json.dumps(PREC, ensure_ascii=False, separators=(',', ':')),
        '__NONE__': _json.dumps(NONE_TEXT, ensure_ascii=False, separators=(',', ':')),
        '__CATS__': _json.dumps(CATS, ensure_ascii=False, separators=(',', ':')),
        '__OGTITLE__': og_title,
        '__TWTITLE__': tw_title,
        '__PAGEURL__': page_url,
        '__JSONLD__': jsonld,
        '__OGDESC__': og_desc,
        '__OGALT__': og_alt,
        '__OGIMG__': og_img,
        '__TITLE__': title,
        '__DAY0__': d.isoformat(),
        '__TZ0__': OBS_TZ,
        '__DESC__': desc,
        '__YEAR__': _long(d),
        '__Y0__': str(YEARS[0]),
        '__Y1__': str(YEARS[-1]),
        '__B__': BASE,
    }
    out = HTML
    for k in sorted(repl, key=len, reverse=True):
        out = out.replace(k, repl[k])
    return out


# ---------------- build ----------------
_hub_html = _build_page(DAY)
(SUN / 'index.html').write_text(_hub_html)
print(f'built the sunmap page for {DAY.isoformat()} at {OBS_LABEL}  base={BASE} site={SITE} '
      f'canonical={PROD} indexable={INDEXABLE}')

# ---------------- sitemap.xml + robots.txt + 404.html + source.html ----------------
from datetime import date as _date
_today = _date.today().isoformat()
_sm = ['<?xml version="1.0" encoding="UTF-8"?>',
       '<!-- SPDX-License-Identifier: AGPL-3.0-or-later',
       '     Copyright (C) 2026 PUDDY Inc. <legal@puddystudios.com> -->',
       '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
       'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">',
       f'<url><loc>{PROD}</loc><lastmod>{_today}</lastmod><changefreq>daily</changefreq><priority>1.0</priority>'
       f'<image:image><image:loc>{OG_SITE}og/sunmap-og.png</image:loc>'
       f'<image:title>SUNMAP - Sunrise, Sunset and Twilight, Timed to the Second</image:title></image:image></url>',
       '</urlset>']
(SUN / 'sitemap.xml').write_text('\n'.join(_sm) + '\n')
(SUN / 'favicon.svg').write_text(_FAVICON)
_ROBOTS_HDR = ('# SPDX-License-Identifier: AGPL-3.0-or-later\n'
               '# Copyright (C) 2026 PUDDY Inc. <legal@puddystudios.com>\n')
(SUN / 'robots.txt').write_text(
    _ROBOTS_HDR + (('User-agent: *\nAllow: /\n\nSitemap: %ssitemap.xml\n' % PROD) if INDEXABLE
                   else 'User-agent: *\nDisallow: /\n'))  # the demo host asks not to be crawled at all

_nf = ('<!DOCTYPE html>'
       '<!-- SPDX-License-Identifier: AGPL-3.0-or-later'
       ' | Copyright (C) 2026 PUDDY Inc. <legal@puddystudios.com> -->'
       '<html lang="en"><head><meta charset="utf-8">'
       '<meta name="viewport" content="width=device-width, initial-scale=1">'
       '<meta name="robots" content="noindex">'
       '<title>SUNMAP | 404 - Below the Horizon</title>'
       '<meta name="description" content="This page is below the horizon - Go back to SUNMAP for '
       'sunrise, sunset, twilight and the Moon, timed to the second.">'
       '<link rel="icon" type="image/svg+xml" sizes="any" href="' + BASE + 'favicon.svg">'
       '<link rel="icon" type="image/x-icon" href="' + BASE + 'favicon.ico">'
       '<style>'
       'body{background:#000;color:#fff;font-family:ui-monospace,Menlo,monospace;display:flex;'
       'align-items:center;justify-content:center;min-height:100vh;margin:0;text-align:center}'
       'a{color:#fff} .x{letter-spacing:.2em} h1{font-size:42px;margin:0 0 10px}'
       'p{color:rgba(255,255,255,.55);line-height:1.8}</style></head><body><div>'
       '<h1 class="x">404</h1><p>This page is below the horizon.<br>'
       f'<a href="{BASE}">Back to the Sunmap</a> - Any day, anywhere you stand.</p>'
       '</div></body></html>')
(SUN / '404.html').write_text(_nf)

# ---- source.html: GPL-3.0 sec 6(d) / AGPL-3.0 sec 13 corresponding-source offer ----
_src = ('<!DOCTYPE html>'
        '<!-- SPDX-License-Identifier: AGPL-3.0-or-later'
        ' | Copyright (C) 2026 PUDDY Inc. <legal@puddystudios.com> -->'
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>SUNMAP | Source and Open-Source Licenses</title>'
        '<meta name="description" content="Complete Corresponding Source and license information '
        'for the open-source components SUNMAP serves (Swiss Ephemeris, AGPL-3.0).">'
        '<link rel="canonical" href="' + PROD + 'source.html">'
        '<link rel="icon" type="image/svg+xml" sizes="any" href="' + BASE + 'favicon.svg">'
        '<link rel="icon" type="image/x-icon" href="' + BASE + 'favicon.ico">'
        '<style>'
        'body{background:#000;color:#fff;font-family:ui-monospace,Menlo,monospace;line-height:1.75;'
        'margin:0;padding:48px clamp(20px,6vw,80px);max-width:860px}'
        'a{color:#fff}h1{font-size:26px;letter-spacing:.04em;margin:0 0 6px}'
        'h2{font-size:14px;letter-spacing:.14em;text-transform:uppercase;color:rgba(255,255,255,.6);'
        'margin:34px 0 10px;border-top:1px solid rgba(255,255,255,.15);padding-top:20px}'
        'p,li{color:rgba(255,255,255,.72);font-size:13px}ul{padding-left:18px}'
        'code{color:#fff;background:rgba(255,255,255,.08);padding:1px 5px;border-radius:3px;font-size:12px}'
        '.lead{color:rgba(255,255,255,.55);font-size:13px;margin-bottom:8px}'
        '.dl{color:#fff;text-decoration:underline}</style></head><body>'
        '<h1>Source &amp; Open-Source Licenses</h1>'
        '<p class="lead">SUNMAP is a product of PUDDY Inc. It runs open-source software on your '
        'device; this page provides the corresponding source and licenses, as those licenses '
        'require.</p>'
        '<h2>What runs on your device</h2>'
        '<p>SUNMAP computes your whole solar and lunar day in your browser using the '
        '<b>Swiss Ephemeris</b> astronomical library (&copy; Astrodienst AG), compiled to '
        'WebAssembly by the <code>swisseph-wasm</code> package (&copy; 2024 prolaxu). SUNMAP uses '
        'the Swiss Ephemeris <b>unmodified</b>, under its free <b>GNU Affero General Public License '
        'v3.0 (AGPL-3.0)</b> option - not the paid commercial license. The <code>swisseph-wasm</code> '
        'wrapper is licensed <b>GPL-3.0-or-later</b>. SUNMAP\'s own code that drives the engine '
        '(<code>sunmap-worker.js</code>) forms a combined work with it and is likewise licensed '
        '<b>AGPL-3.0-or-later</b> (&copy; 2026 PUDDY Inc.)</p>'
        '<h2>Complete Corresponding Source</h2>'
        '<p>In accordance with GPL-3.0 section 6(d) and AGPL-3.0 section 13, the corresponding '
        'source is available here at no charge. The running binary and our calling code are served '
        'directly from this site:</p><ul>'
        '<li>The running binary: <a href="' + BASE + 'vendor/sweph/swisseph.wasm">swisseph.wasm</a>, '
        '<a href="' + BASE + 'vendor/sweph/swisseph.js">swisseph.js</a>, '
        '<a href="' + BASE + 'vendor/sweph/LICENSE.txt">upstream LICENSE</a>, '
        '<a href="' + BASE + 'vendor/sweph/SOURCES.md">SOURCES.md</a> (versions and rebuild steps)</li>'
        '<li>Our code: <a href="' + BASE + 'sunmap-worker.js">sunmap-worker.js</a> (the AGPL combined '
        'work), <a href="' + BASE + 'sunmap-geo.js">sunmap-geo.js</a></li></ul>'
        '<p>The Swiss Ephemeris 2.10.03 C source and the <code>swisseph-wasm</code> package source '
        'with its Emscripten build script are available on written request at no charge: '
        '<b>legal@puddystudios.com</b>. They are also published upstream at the links below.</p>'
        '<p class="lead" style="color:rgba(255,255,255,.6)">A note on the bundled '
        '<a href="' + BASE + 'vendor/sweph/LICENSE.txt">vendor/sweph/LICENSE.txt</a>: that file is '
        'the <code>swisseph-wasm</code> wrapper author\'s older license summary (&copy; 2024 prolaxu). '
        'It describes the Swiss Ephemeris as free for non-commercial use with a commercial license '
        'required otherwise. That summary predates Astrodienst\'s relicensing of the Swiss Ephemeris '
        'under the GNU Affero General Public License. SUNMAP\'s governing terms are <b>AGPL-3.0</b>, '
        'and SUNMAP complies by providing the corresponding source above and on request.</p>'
        '<h2>Upstream provenance</h2><ul>'
        '<li>Swiss Ephemeris 2.10.03 - Astrodienst AG: '
        '<a href="https://www.astro.com/swisseph/">astro.com/swisseph</a>, '
        '<a href="https://github.com/aloistr/swisseph">github.com/aloistr/swisseph</a> (tag v2.10.03)</li>'
        '<li><code>swisseph-wasm</code> 0.0.5: '
        '<a href="https://github.com/prolaxu/swisseph-wasm">github.com/prolaxu/swisseph-wasm</a>, '
        '<a href="https://www.npmjs.com/package/swisseph-wasm">npm</a></li>'
        '<li>Full license texts: '
        '<a href="https://www.gnu.org/licenses/agpl-3.0.txt">AGPL-3.0</a>, '
        '<a href="https://www.gnu.org/licenses/gpl-3.0.txt">GPL-3.0</a></li></ul>'
        '<h2>Ephemeris data</h2>'
        '<p>The engine reads Swiss Ephemeris data files (<code>seas_18.se1</code>, '
        '<code>semo_18.se1</code>, <code>sepl_18.se1</code>). These are astronomical data, not '
        'program source; SUNMAP serves them at <a href="' + BASE + 'data/ephe/seas_18.se1">/data/ephe/</a> '
        'and Astrodienst publishes them at '
        '<a href="https://www.astro.com/ftp/swisseph/ephe/">astro.com/ftp/swisseph/ephe</a>.</p>'
        '<h2>The rest of SUNMAP</h2>'
        '<p>The remainder of this website (the page, design, and other tooling) is proprietary '
        'and is merely aggregated with the open-source components above; it does not link into them. '
        'All engine interaction is isolated behind the AGPL-licensed worker.</p>'
        '<p style="margin-top:30px"><a href="' + BASE + '">Back to SUNMAP</a> &middot; '
        'Source requests: legal@puddystudios.com</p>'
        '</body></html>')
(SUN / 'source.html').write_text(_src)
print('wrote sitemap.xml (1 URL, image extension) + robots.txt + favicon.svg + 404.html + source.html')

# ---------------- PWA: manifest.json + sw.js ----------------
_manifest = {
    'name': 'SUNMAP',
    'short_name': 'SUNMAP',
    'description': ('Sunrise, sunset, twilight, golden hour and the Moon - Timed to the second on '
                    'the Swiss Ephemeris engine, solved on your device for exactly where you '
                    'stand. A Puddy Studios tool.'),
    'id': BASE,
    'start_url': BASE,
    'scope': BASE,
    'display': 'standalone',
    'orientation': 'any',
    'background_color': '#000000',
    'theme_color': '#000000',
    'lang': 'en',
    'categories': ['utilities', 'lifestyle', 'education'],
    'icons': [
        {'src': f'{BASE}icons/icon-192.png', 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any'},
        {'src': f'{BASE}icons/icon-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any'},
        {'src': f'{BASE}icons/icon-maskable-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'},
    ],
    'screenshots': [
        {'src': f'{BASE}og/sunmap-og.png', 'sizes': '2400x1260', 'type': 'image/png', 'form_factor': 'wide',
         'label': 'SUNMAP - Sunrise, Sunset and Twilight to the Second'},
    ],
}
_manifest_text = _json.dumps(_manifest, ensure_ascii=False, indent=2) + '\n'
(SUN / 'manifest.json').write_text(_manifest_text)

_h = _hashlib.sha1()
_h.update(_hub_html.encode('utf-8'))
_h.update(_manifest_text.encode('utf-8'))
for _dep in ('sunmap-worker.js', 'sunmap-geo.js'):
    _dp = SUN / _dep
    if _dp.exists():
        _h.update(_dp.read_bytes())
_ver = _h.hexdigest()[:10]

_SW = r"""/* SPDX-License-Identifier: AGPL-3.0-or-later
   Copyright (C) 2026 PUDDY Inc. <legal@puddystudios.com>
   SUNMAP service worker - generated by scripts/render.py, do not hand-edit. */
'use strict';
var VERSION = '__VER__';
var CACHE = 'sunmap-' + VERSION;
var EXT = 'sunmap-ext';
var CORE = [
  '__BB__',
  '__BB__index.html',
  '__BB__manifest.json',
  '__BB__sunmap-worker.js',
  '__BB__sunmap-geo.js',
  '__BB__favicon.svg'
];
/* Everything the on-device engine needs to run with no network, plus the root
   chrome, the OG card and the icons. Cached TOLERANTLY: any one of these
   missing must not fail the install, because the OG card comes from
   scripts/generate-og.mjs and the icons from scripts/make-icons.sh, and either
   may not have been run yet. Once they are cached, SUNMAP solves any day
   fully offline. */
var EXTRAS = [
  '/puddy-tools.js?v=15', '/puddy-logo.svg', '__BB__og/sunmap-og.png',
  '__BB__vendor/sweph/swisseph.js', '__BB__vendor/sweph/swisseph.wasm',
  '__BB__data/ephe/seas_18.se1', '__BB__data/ephe/semo_18.se1', '__BB__data/ephe/sepl_18.se1',
  '__BB__icons/icon-192.png', '__BB__icons/icon-512.png',
  '__BB__icons/icon-maskable-512.png', '__BB__icons/icon-180.png',
  '__BB__icons/icon-32.png', '__BB__icons/icon-16.png', '__BB__favicon.ico'
];

self.addEventListener('install', function (e) {
  e.waitUntil(
    caches.open(CACHE).then(function (c) {
      /* cache:'reload' bypasses the browser HTTP cache so installs always
         snapshot fresh-from-edge, never a stale disk-cached copy. */
      return c.addAll(CORE.map(function (u) { return new Request(u, { cache: 'reload' }); })).then(function () {
        return Promise.allSettled(EXTRAS.map(function (u) { return c.add(new Request(u, { cache: 'reload' })); }));
      });
    }).then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (e) {
  e.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.filter(function (k) {
        return k.indexOf('sunmap-') === 0 && k !== CACHE && k !== EXT;
      }).map(function (k) { return caches.delete(k); }));
    }).then(function () { return self.clients.claim(); })
  );
});

function swr(req, cacheName) {
  return caches.open(cacheName).then(function (c) {
    return c.match(req).then(function (hit) {
      /* no-cache = revalidate against the edge (conditional GET), so the
         background refresh can never re-absorb a stale browser-cache copy. */
      var refresh = fetch(req, { cache: 'no-cache' }).then(function (res) {
        if (res && res.ok) c.put(req, res.clone());
        return res;
      }).catch(function () { return hit; });
      return hit || refresh;
    });
  });
}

self.addEventListener('fetch', function (e) {
  var req = e.request;
  if (req.method !== 'GET') return;
  var url = new URL(req.url);

  /* Page navigations: network-first so new builds land immediately; cached page offline. */
  if (req.mode === 'navigate') {
    e.respondWith(
      fetch(req, { cache: 'no-cache' }).then(function (res) {
        if (res && res.ok) {
          var copy = res.clone();
          caches.open(CACHE).then(function (c) { c.put(req, copy); });
        }
        return res;
      }).catch(function () {
        return caches.match(req).then(function (hit) {
          return hit || caches.match('__BB__').then(function (hub) {
            return hub || caches.match('__BB__index.html');
          });
        });
      })
    );
    return;
  }

  /* Same-origin assets (the engine, the ephemerides, icons, OG, chrome): stale-while-revalidate. */
  if (url.origin === self.location.origin) {
    e.respondWith(swr(req, CACHE));
    return;
  }

  /* Webfonts (Google Fonts / Fontshare): cache so the installed app keeps its type offline. */
  if (/fonts\.googleapis\.com|fonts\.gstatic\.com|api\.fontshare\.com|cdn\.fontshare\.com/.test(url.host)) {
    e.respondWith(swr(req, EXT));
  }
});
"""
(SUN / 'sw.js').write_text(_SW.replace('__VER__', _ver).replace('__BB__', BASE))
print(f'wrote manifest.json + sw.js (cache sunmap-{_ver})')
