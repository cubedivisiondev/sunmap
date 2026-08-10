# SUNMAP - Production Cutover Runbook

> Domain: CUBE BUSINESS
> Type: RUNBOOK
> Status: STAGED - prod is provisioned and DARK, awaiting founder approval
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
| DNS | Cloudflare CNAME, live | NONE - this is what keeps prod dark |
| Enabled | true | **false** |

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

```bash
cd sun_map
python3 scripts/render_page.py --base / --site https://sunmap.puddystudios.com/ --out index.html
aws s3 sync . s3://sunmap-puddystudios/ --exclude "scripts/*" --exclude "__pycache__/*" \
  --exclude "*.pyc" --exclude ".gitignore" --exclude "package.json" --delete
aws s3 cp s3://sunmap-puddystudios/vendor/sweph/swisseph.wasm \
  s3://sunmap-puddystudios/vendor/sweph/swisseph.wasm \
  --content-type "application/wasm" --metadata-directive REPLACE
```

**2. Enable the distribution.**

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
for p in sunmap-worker.js sunmap-geo.js vendor/sweph/swisseph.wasm data/ephe/semo_18.se1; do
  curl -s -o /dev/null -w "$p %{http_code} %{content_type}\n" "https://sunmap.puddystudios.com/$p"
done
```

The engine must return `application/wasm` or streaming compilation silently
degrades. Open the page in a real browser and confirm sunrise, sunset and the
twilight ladder render, then change the location and confirm they change.

## Rollback

Set `Enabled: false` on `E33LDSQF7SNDJW`, or delete the DNS record. Either alone
takes prod dark. The dev surface is unaffected by both.

## Before prod goes public, decide these

- **OG cards.** None exist yet. Link previews will be bare until they do.
- **Service worker.** SUNMAP has no offline cache. STARMAP ships one; this does not.
- **AGPL source offer.** The worker header points at
  `https://sunmap.puddystudios.com/source.html`, which does not exist yet.
  SUNMAP serves the same Swiss Ephemeris WebAssembly build STARMAP does, under the
  same free AGPL-3.0 option, so the same obligation applies: the complete
  corresponding source and a written offer must be reachable at that URL **before**
  the page is served publicly. Staging it is a copy of STARMAP's `source/` tree
  plus a `source.html`. This is a compliance blocker, not a nicety.
- **Sitemap and robots.txt.** Neither is generated yet.
