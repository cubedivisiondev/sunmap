# SUNMAP - Production Cutover Runbook

> Domain: CUBE BUSINESS
> Type: RUNBOOK
> Status: ARMED - prod is staged, ENABLED and DARK. Founder approved the ship for
>         2026-08-12 09:12:57 PDT (the topocentric New Moon at Mirabella). The only
>         remaining step is the DNS record.
> Owner: Claude Code (tools lane)
> Updated: 2026-08-10
> Links: sun_map/, star_map/PROD_RUNBOOK.md, CLAUDE.md RULE 9

Prod is built, staged, and deliberately unreachable. Nothing below runs without
explicit per-deploy founder approval (RULE 9). The cutover is four commands and
a verification pass.

## The two environments

| | DEV (live now) | PROD (staged dark) |
|---|---|---|
| Host | `sunmap.puddy.dev` | `sunmap.puddystudios.com` |
| Bucket | `sunmap-puddystudios-dev` | `sunmap-puddystudios` |
| Distribution | `E1NSIBF6WWQQ49` | `E33LDSQF7SNDJW` |
| CloudFront domain | `dj1992w0igv8a.cloudfront.net` | `d2pj6dhuyxhibu.cloudfront.net` |
| Certificate | `*.puddy.dev` | `*.puddystudios.com` |
| Password gate | `dev-starmap-auth` attached | NONE - prod is public |
| Indexable | No (`noindex,nofollow`) | Yes |
| Canonical | `sunmap.puddystudios.com` | `sunmap.puddystudios.com` |
| DNS | Cloudflare CNAME, live | **NONE - this is the ONLY thing keeping prod dark** |
| Enabled | true | true (enabled 2026-08-11 ahead of the timed ship) |

Canonical points at prod from both builds on purpose: the demo host must never
compete with prod in the index.

## What is already done

- Prod bucket created, public access fully blocked, OAC policy scoped to `E33LDSQF7SNDJW`.
- Prod distribution created with the `*.puddystudios.com` certificate, the dev
  password gate REMOVED, and `Enabled: false`.
- The indexable prod build is staged in the prod bucket (14 objects) with correct
  content types: `application/wasm` for the engine, `text/javascript` for the
  modules, `text/html` for the page.
- No DNS record exists for `sunmap.puddystudios.com`. That absence is the safety
  interlock - even if the distribution were enabled by accident, nothing resolves.

## The cutover (needs approval before ANY step)

**1. Rebuild prod from a clean source and re-stage.** Do not ship a stale artifact.

The archive rebuild comes FIRST and comes LAST: it must be built after
`sunmap-worker.js` is final, or the corresponding source does not correspond and
the offer is void. `seo_check.py` fails the run if they drift apart, so the gate
below is what actually enforces the order.

```bash
cd sun_map
python3 scripts/build_source_archive.py                                    # AGPL archive, after the worker is final
python3 scripts/render.py --base / --site https://sunmap.puddystudios.com/  # prod = indexable
python3 scripts/seo_check.py --env prod                                    # MUST exit 0 before any upload
aws s3 sync . s3://sunmap-puddystudios/ --exclude "scripts/*" --exclude "__pycache__/*" \
  --exclude "*.pyc" --exclude ".gitignore" --exclude "package.json" \
  --exclude "PROD_RUNBOOK.md" --exclude "og/_gallery.html" --exclude "sunmap-app.js" --delete
aws s3 cp s3://sunmap-puddystudios/vendor/sweph/swisseph.wasm \
  s3://sunmap-puddystudios/vendor/sweph/swisseph.wasm \
  --content-type "application/wasm" --metadata-directive REPLACE
```

The last three excludes are load-bearing, not tidiness. This sync is a denylist
over the whole directory, so anything not named here goes public on a host that
`robots.txt` opens with `Allow: /` and that is meant to be indexed:

- `PROD_RUNBOOK.md` - this file. It carries both bucket names, both distribution
  IDs, the CloudFront domains, the dev password-gate name and the rollback
  procedure. STARMAP prod returns 404 for `/PROD_RUNBOOK.md`; match that.
- `og/_gallery.html` - the internal OG review page. STARMAP's runbook excludes
  `_gallery.html` by name under the comment "NEVER ship the internal galleries
  or review mocks", and STARMAP prod returns 404 for it.
- `sunmap-app.js` - dead code. Nothing references it: `index.html` and `sw.js`
  both have zero mentions. It is a leftover of the `render_sunmap.py` era.

Verify after the sync, before announcing:

```bash
for p in PROD_RUNBOOK.md og/_gallery.html sunmap-app.js; do
  curl -s -o /dev/null -w "$p %{http_code} (expect 403 or 404)\n" "https://sunmap.puddystudios.com/$p"
done
```

**`--exclude` also disables `--delete` for that key.** `aws s3 sync --delete`
skips excluded keys on BOTH sides, so a denylisted file that reached the bucket
in an earlier run is never cleaned up by a later sync - it just sits there,
served, invisible to the sync output. `sunmap-app.js` did exactly this: staged
2026-08-10, still public on 2026-08-11 after several syncs that all "excluded"
it. Excluding a path is not the same as removing it. Delete stale denylisted
objects explicitly, once:

```bash
aws s3 rm s3://sunmap-puddystudios/sunmap-app.js
```

The `curl` loop above is what catches this - run it, do not assume the sync
flags did the work.

The sync must NOT exclude `source/` - that directory is the AGPL compliance
surface, not build scrap. Never pass `--content-encoding gzip` for the archive:
the client would transparently decompress it and `tar xzf` would then fail on a
file still named `.tar.gz`. STARMAP serves it as plain `application/x-tar` with
no content-encoding, which downloads intact; match that.

Optional, cosmetic only: `source/README.md` lands as `binary/octet-stream` and
downloads instead of displaying. Reachability is what the license requires, so
this is not a blocker, but one line fixes it:

```bash
aws s3 cp s3://sunmap-puddystudios/source/README.md s3://sunmap-puddystudios/source/README.md \
  --content-type "text/plain; charset=utf-8" --metadata-directive REPLACE
```

**2. Enable the distribution.** DONE 2026-08-11. It was enabled ~16 hours ahead of
the ship because a CloudFront enable takes 5-15 minutes to propagate, and the
ship is to a named SECOND - that latency cannot sit inside the moment. Prod
stayed dark throughout: with no DNS record nothing resolves to the distribution,
which is precisely the interlock this runbook relies on. Kept here for rollback.

```bash
aws cloudfront get-distribution-config --id E33LDSQF7SNDJW > /tmp/p.json
# set Enabled to true, keep the ETag, then:
aws cloudfront update-distribution --id E33LDSQF7SNDJW \
  --distribution-config file:///tmp/p-config.json --if-match <ETag>
```

**3. Create DNS last.** Resolvers negative-cache a miss for about 30 minutes, so
the name must not be looked up before it exists.

```bash
# Cloudflare, zone puddystudios.com - CNAME sunmap -> d2pj6dhuyxhibu.cloudfront.net
# Reference $CLOUDFLARE_DNS_TOKEN by name; never echo the value.
```

**4. Verify before announcing.**

```bash
curl -sI https://sunmap.puddystudios.com/ | head -3          # expect 200, no 401
curl -s https://sunmap.puddystudios.com/ | grep -c noindex   # expect 0
curl -s https://sunmap.puddystudios.com/robots.txt           # expect Allow: / + the Sitemap line
for p in sunmap-worker.js sunmap-geo.js vendor/sweph/swisseph.wasm data/ephe/semo_18.se1 \
         source.html source/corresponding-source.tar.gz source/README.md \
         source/AGPL-3.0.txt source/GPL-3.0.txt sitemap.xml; do
  curl -s -o /dev/null -w "$p %{http_code} %{content_type}\n" "https://sunmap.puddystudios.com/$p"
done

# The archive must survive the round trip as a real gzip, and the worker inside
# it must be the worker being served. This is the compliance proof, not a link check.
curl -sI https://sunmap.puddystudios.com/source/corresponding-source.tar.gz | grep -i content-encoding \
  && echo "STOP: content-encoding set - tar xzf will fail" || echo "ok: no content-encoding"
curl -s https://sunmap.puddystudios.com/source/corresponding-source.tar.gz -o /tmp/sunmap-cs.tgz
tar xzOf /tmp/sunmap-cs.tgz corresponding-source/sunmap-worker.js | shasum -a 256
curl -s https://sunmap.puddystudios.com/sunmap-worker.js | shasum -a 256   # must match the line above

python3 scripts/seo_check.py --url https://sunmap.puddystudios.com/         # must exit 0
```

The engine must return `application/wasm` or streaming compilation silently
degrades. Open the page in a real browser and confirm sunrise, sunset and the
twilight ladder render, then change the location and confirm they change.

## Rollback

Set `Enabled: false` on `E33LDSQF7SNDJW`, or delete the DNS record. Either alone
takes prod dark. The dev surface is unaffected by both.

## Before prod goes public, decide these

- **AGPL source offer. CLOSED 2026-08-11.** SUNMAP serves the byte-identical Swiss
  Ephemeris WebAssembly build STARMAP serves, under the same free AGPL-3.0 option,
  so it owes the Corresponding Source from the same place it serves the binary
  (GPL-3.0 section 6(d) - an email offer does not satisfy that clause). The surface
  now exists and mirrors STARMAP's: `source.html` carries the offer and the license
  summary; `source/corresponding-source.tar.gz` carries the Swiss Ephemeris 2.10.03
  C source, the `swisseph-wasm@0.0.5` npm package, prolaxu's build harness with
  `compile.sh`, both full license texts, and SUNMAP's own `sunmap-worker.js` and
  `sunmap-geo.js`; `source/README.md` is the written offer plus a SHA-256 manifest;
  `source/AGPL-3.0.txt` and `source/GPL-3.0.txt` are the full texts. Built by
  `scripts/build_source_archive.py`, which refuses to emit an archive whose engine
  files do not match the served binary. `scripts/seo_check.py` fails the run if any
  of it is missing or if the archived worker has drifted from the served one.
- **OG cards.** Five exist in `og/` (landscape, youtube, square, pin, story) and
  `og/sunmap-og.png` is what the page and sitemap reference.
- **Service worker.** `sw.js` is emitted by `scripts/render.py` with a
  content-hashed cache key.
- **Sitemap and robots.txt.** Both are emitted by `scripts/render.py`. The prod
  build gets `Allow: /` plus a `Sitemap:` line; any non-prod `--site` gets a
  Disallow-all robots.txt and a `noindex,nofollow` meta on every page. Confirmed by
  building both and diffing: the only differences are the noindex meta and the
  OG/JSON-LD image host. Canonical is the prod host in both.
