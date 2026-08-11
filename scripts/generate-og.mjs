// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 PUDDY Inc.
//
// PUDDY house-style social cards for SUNMAP.
//
// Matches STARMAP's card system (star_map/scripts/generate-og.mjs) in layout,
// band math, DPI and gallery emission, with two deliberate departures:
//
//   1. NO COMMERCIAL FONT. STARMAP base64-embeds FuturaCyrillicBold.woff out of
//      the sibling puddy-studios checkout. SUNMAP references an open/system
//      geometric-sans stack BY NAME and embeds no font binary at all, so this
//      directory carries no licensed-font dependency and nothing to redistribute.
//   2. REAL TEXT MEASUREMENT. STARMAP estimates glyph widths with a hardcoded
//      constant (FUTURA_BOLD_CAPS_WIDTH = 0.72) that is only valid for the one
//      font it embeds. Because our face is resolved at render time, we binary
//      search the type size against the browser's own measurement instead. The
//      fit is correct for whichever family actually wins the stack.
//
// Formats - the exact five STARMAP ships:
//   landscape 1200x630   sunmap-og.png          -> og:image / twitter:image
//   youtube   1280x720   sunmap-og-youtube.png
//   square    1080x1080  sunmap-og-square.png
//   pinterest 1000x1500  sunmap-og-pin.png
//   story     1080x1920  sunmap-og-story.png
//
// All render at deviceScaleFactor 2, so the landscape PNG is 2400x1260 actual
// pixels - which is what index.html declares in og:image:width/height.
//
//   node sun_map/scripts/generate-og.mjs                 # 5 cards + og/_gallery.html
//   node sun_map/scripts/generate-og.mjs --gallery-only  # rewrite the gallery only
//
// Run AFTER render.py: the centerpiece is lifted verbatim out of the built
// index.html, so the card always carries whatever corona render.py emitted.

import { readFileSync, mkdirSync, writeFileSync, statSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, '..');   // sun_map/
const REPO = resolve(ROOT, '..');        // Puddy Studios/
const outDir = resolve(ROOT, 'og');

// ---------------------------------------------------------------- palette --
// PLUTO canon (brand/PLUTO_PALETTE.md). Gold is an ACCENT, never a wash - the
// card is black and white, and #ceba9d touches exactly one element.
const GOLD = '#ceba9d';

// ------------------------------------------------------------------ fonts --
// Referenced by NAME only. No @font-face, no base64, no file read: nothing
// licensed is embedded or redistributed. Ordered geometric-sans first so the
// card keeps PUDDY's Futura-adjacent character wherever it renders, with an
// open/metric-safe tail (DejaVu/Liberation/Nimbus ship with most Linux boxes).
const FONT_STACK = [
  "'Avenir Next'", "'Futura'", "'Century Gothic'", "'URW Gothic'",
  "'Questrial'", "'Jost'", "'Nimbus Sans'", "'Helvetica Neue'",
  'Helvetica', "'Liberation Sans'", "'DejaVu Sans'", 'Arial', 'sans-serif',
].join(', ');
// Probed in-page after load and printed in the run report, so the operator
// always knows which face actually drew the cards on this machine.
const FONT_PROBE = ['Avenir Next', 'Futura', 'Century Gothic', 'URW Gothic',
  'Questrial', 'Jost', 'Nimbus Sans', 'Helvetica Neue', 'Helvetica',
  'Liberation Sans', 'DejaVu Sans', 'Arial'];

// --------------------------------------------------------------- centerpiece
const indexPath = resolve(ROOT, 'index.html');
let html;
try {
  html = readFileSync(indexPath, 'utf8');
} catch {
  console.error(`FATAL: cannot read ${indexPath} - run scripts/render.py first.`);
  process.exit(1);
}
const sigilMatch = html.match(/<svg class="sigil"[\s\S]*?<\/svg>/);
if (!sigilMatch) {
  console.error('FATAL: <svg class="sigil"> not found in index.html - run scripts/render.py first.');
  process.exit(1);
}
const SIGIL = sigilMatch[0];
const nodeCount = (SIGIL.match(/<use /g) || []).length;

// ------------------------------------------------------------------- copy --
// "SUNMAP" is all-caps standalone per house style. Hyphens only, no dashes.
const CARD = {
  eyebrow: 'Timed to the Second',
  lines: ['SUNMAP:', 'Sunrise, Sunset', 'and Twilight'],
  hook: 'SUNMAP: Sunrise, Sunset and Twilight',
  brand: 'Puddy Studios',
  url: 'sunmap.puddystudios.com',
};

const FORMATS = [
  { suffix: '', width: 1200, height: 630, layout: 'landscape', label: 'Landscape 1200x630' },
  { suffix: '-youtube', width: 1280, height: 720, layout: 'landscape', label: 'YouTube 1280x720' },
  { suffix: '-square', width: 1080, height: 1080, layout: 'stack', label: 'Square 1080x1080' },
  { suffix: '-pin', width: 1000, height: 1500, layout: 'stack', label: 'Pin 1000x1500' },
  { suffix: '-story', width: 1080, height: 1920, layout: 'stack', label: 'Story 1080x1920' },
];

const DPI = 2;
const escapeHtml = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

// ------------------------------------------------------------ band geometry
// Same proportions STARMAP uses, so the two tools' cards sit side by side as
// one family. Only the type sizing method differs (measured, not estimated).
function logoFractionFor(fmt) {
  if (fmt.layout === 'landscape') return 0;
  if (fmt.height >= 1800) return 0.50;
  if (fmt.width === fmt.height) return 0.34;
  return 0.42;
}

function bands(fmt) {
  if (fmt.layout === 'landscape') {
    const padX = Math.round(fmt.width * 0.06);
    const padY = Math.round(fmt.height * 0.095);
    const gap = Math.round(fmt.width * 0.05);
    const logoSize = Math.round(Math.min(fmt.width, fmt.height) * 0.57);
    return {
      padX, padY, gap, logoSize,
      eyebrowSize: Math.round(fmt.width * 0.015),
      brandSize: Math.round(fmt.width * 0.0166),
      urlSize: Math.round(fmt.width * 0.015),
      hookWidth: fmt.width - 2 * padX - gap - logoSize,
      hookHeight: Math.round(fmt.height * 0.46),
      fontMax: 130,
    };
  }
  const padX = Math.round(fmt.width * 0.07);
  const padY = Math.round(fmt.height * 0.07);
  const logoSize = Math.round(fmt.width * logoFractionFor(fmt));
  const eyebrowSize = Math.round(fmt.width * 0.018);
  const brandSize = Math.round(fmt.width * 0.020);
  const urlSize = Math.round(fmt.width * 0.018);
  const brandHeight = Math.round(fmt.width * 0.06);
  return {
    padX, padY, logoSize, eyebrowSize, brandSize, urlSize,
    centerpieceGap: Math.round(fmt.height * 0.05),
    hookWidth: fmt.width - 2 * padX,
    hookHeight: Math.max(
      120,
      fmt.height - 2 * padY - logoSize - eyebrowSize - brandHeight - Math.round(fmt.height * 0.11),
    ),
    fontMax: 220,
  };
}

// ------------------------------------------------------------------ markup --
function htmlForCard(fmt) {
  const b = bands(fmt);
  const hookHtml = CARD.lines
    .map((l) => `<div class="hook-line">${escapeHtml(l)}</div>`)
    .join('\n      ');
  const base = `
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { width: ${fmt.width}px; height: ${fmt.height}px; background: #000; }
body {
  font-family: ${FONT_STACK};
  color: #fff;
  -webkit-font-smoothing: antialiased;
  overflow: hidden;
}
.logo svg { width: 100%; height: 100%; display: block; }
.eyebrow { font-weight: 700; text-transform: uppercase; letter-spacing: 0.35em; color: ${GOLD}; }
.hook-frame { overflow: hidden; display: flex; flex-direction: column; }
.hook-line { font-weight: 700; line-height: 1.02; letter-spacing: 0.005em;
  text-transform: uppercase; color: #fff; white-space: nowrap; }
.hook-line + .hook-line { margin-top: 0.05em; }
`;

  if (fmt.layout === 'landscape') {
    return `<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><style>${base}
body { display: flex; align-items: center; padding: ${b.padY}px ${b.padX}px; gap: ${b.gap}px; }
.logo { width: ${b.logoSize}px; height: ${b.logoSize}px; flex-shrink: 0; }
.text { flex: 1; min-width: 0; display: flex; flex-direction: column;
  justify-content: center; gap: ${Math.round(b.eyebrowSize * 1.4)}px; }
.eyebrow { font-size: ${b.eyebrowSize}px; }
.hook-frame { width: ${b.hookWidth}px; max-height: ${b.hookHeight}px;
  align-items: flex-start; justify-content: center; }
.brand-mark { position: absolute; top: ${Math.round(b.padY * 0.83)}px; right: ${b.padX}px;
  font-size: ${b.brandSize}px; font-weight: 700; letter-spacing: 0.25em;
  text-transform: uppercase; color: rgba(255,255,255,0.7); }
.url-strip { position: absolute; bottom: ${Math.round(b.padY * 0.83)}px; left: ${b.padX}px;
  right: ${b.padX}px; text-align: center; font-size: ${b.urlSize}px; font-weight: 700;
  letter-spacing: 0.15em; color: rgba(255,255,255,0.45); }
</style></head>
<body>
  <div class="brand-mark">${escapeHtml(CARD.brand)}</div>
  <div class="logo">${SIGIL}</div>
  <div class="text">
    <div class="eyebrow">${escapeHtml(CARD.eyebrow)}</div>
    <div class="hook-frame">
      ${hookHtml}
    </div>
  </div>
  <div class="url-strip">${escapeHtml(CARD.url)}</div>
</body></html>`;
  }

  return `<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><style>${base}
body { display: flex; flex-direction: column; align-items: center;
  justify-content: space-between; padding: ${b.padY}px ${b.padX}px; text-align: center; }
.eyebrow { font-size: ${b.eyebrowSize}px; }
.centerpiece { display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: ${b.centerpieceGap}px; width: 100%; }
.logo { width: ${b.logoSize}px; height: ${b.logoSize}px; flex-shrink: 0; }
.hook-frame { width: ${b.hookWidth}px; max-height: ${b.hookHeight}px;
  align-items: center; justify-content: center; }
.hook-line { text-align: center; }
.brand { display: flex; flex-direction: column; align-items: center;
  gap: ${Math.round(b.eyebrowSize * 0.8)}px; }
.brand .name { font-size: ${b.brandSize}px; font-weight: 700; letter-spacing: 0.25em;
  text-transform: uppercase; color: rgba(255,255,255,0.7); }
.brand .url { font-size: ${b.urlSize}px; font-weight: 700; letter-spacing: 0.15em;
  color: rgba(255,255,255,0.45); }
</style></head>
<body>
  <div class="eyebrow">${escapeHtml(CARD.eyebrow)}</div>
  <div class="centerpiece">
    <div class="logo">${SIGIL}</div>
    <div class="hook-frame">
      ${hookHtml}
    </div>
  </div>
  <div class="brand">
    <span class="name">${escapeHtml(CARD.brand)}</span>
    <span class="url">${escapeHtml(CARD.url)}</span>
  </div>
</body></html>`;
}

// --------------------------------------------------------------- gallery ----
function writeGallery(rows) {
  const entries = rows.map((r) => {
    const grid = FORMATS.map((f) => `<div class="card">
      <div class="image-wrap"><img src="${r.filePrefix}${f.suffix}.png" loading="lazy"
        alt="SUNMAP social card, ${f.label}"></div>
      <div class="label">${f.label}</div>
    </div>`).join('\n    ');
    return `<div class="entry" id="${r.slug}">
  <h3>${r.slug}<span class="hook">${escapeHtml(r.hook)}</span></h3>
  <div class="grid">
    ${grid}
  </div>
</div>`;
  }).join('\n');
  const out = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>SUNMAP OG Gallery</title>
<style>
body { margin: 0; padding: 40px; background: #111; color: #fff; font-family: 'Trebuchet MS', Arial, sans-serif; }
h1 { font-size: 28px; font-weight: 700; letter-spacing: 0.05em; margin: 0 0 8px; }
.sub { color: #aaa; font-size: 13px; margin-bottom: 24px; }
.entry { margin-bottom: 48px; }
.entry h3 { font-size: 14px; letter-spacing: 0.25em; text-transform: uppercase; color: rgba(255,255,255,0.7); margin: 32px 0 6px; padding-top: 24px; border-top: 1px solid #333; }
.entry h3 .hook { display: block; margin-top: 6px; font-size: 10px; letter-spacing: 0.15em; color: rgba(255,255,255,0.45); font-weight: 400; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; align-items: start; }
.image-wrap { background: #000; line-height: 0; border-radius: 4px; overflow: hidden; }
.image-wrap img { display: block; width: 100%; height: auto; }
.card .label { margin-top: 8px; background: #1a1a1a; border: 1px solid #2a2a2a; border-left: 3px solid ${GOLD};
  font-size: 10px; letter-spacing: 0.18em; text-transform: uppercase; color: #c0c0c0; padding: 7px 12px; border-radius: 3px; }
</style></head><body>
<h1>SUNMAP - OG Card Gallery</h1>
<div class="sub">${rows.length} entry x ${FORMATS.length} formats. Auto-generated by scripts/generate-og.mjs. Review here before approving prod.</div>
${entries}
</body></html>`;
  writeFileSync(resolve(outDir, '_gallery.html'), out);
  console.log('  og/_gallery.html');
}

// ------------------------------------------------------------------- main ---
mkdirSync(outDir, { recursive: true });

if (process.argv.includes('--gallery-only')) {
  writeGallery([{ slug: 'hub', hook: CARD.hook, filePrefix: 'sunmap-og' }]);
  process.exit(0);
}

// Playwright: prefer a local install, fall back to the monorepo's. Unlike the
// font, this is a build-time-only tool dependency and ships in no artifact.
let chromium;
for (const base of [resolve(ROOT, 'package.json'), resolve(REPO, 'puddy-studios/package.json')]) {
  try { ({ chromium } = createRequire(base)('playwright')); break; } catch { /* next */ }
}
if (!chromium) {
  console.error('FATAL: playwright not resolvable from sun_map/ or puddy-studios/.');
  console.error('       Install with: npm i -D playwright && npx playwright install chromium');
  process.exit(1);
}

console.log(`SUNMAP OG cards - centerpiece: ${nodeCount} puddy-face nodes lifted from index.html`);

const browser = await chromium.launch();
const results = [];
let resolvedFont = null;

for (const fmt of FORMATS) {
  const context = await browser.newContext({
    viewport: { width: fmt.width, height: fmt.height },
    deviceScaleFactor: DPI,
  });
  const tab = await context.newPage();
  await tab.setContent(htmlForCard(fmt), { waitUntil: 'load' });
  await tab.evaluateHandle('document.fonts.ready');

  if (!resolvedFont) {
    resolvedFont = await tab.evaluate((probe) => {
      for (const f of probe) if (document.fonts.check(`700 100px "${f}"`)) return f;
      return 'generic sans-serif';
    }, FONT_PROBE);
  }

  // Largest type size at which every line fits the frame, measured by the
  // browser. Font-agnostic: no per-face width constant anywhere.
  // The frame hugs its text (max-height, not height), so the leftover space is
  // distributed by the flex parent instead of pooling into one dead band.
  const fontSize = await tab.evaluate(({ fontMax, budget }) => {
    const frame = document.querySelector('.hook-frame');
    const lines = [...frame.querySelectorAll('.hook-line')];
    const fits = (px) => {
      lines.forEach((l) => { l.style.fontSize = px + 'px'; });
      return lines.every((l) => l.scrollWidth <= frame.clientWidth)
        && frame.scrollHeight <= budget;
    };
    let lo = 12, hi = fontMax;
    if (fits(hi)) return hi;
    for (let i = 0; i < 30; i++) {
      const mid = (lo + hi) / 2;
      if (fits(mid)) lo = mid; else hi = mid;
    }
    const final = Math.floor(lo);
    fits(final);
    return final;
  }, { fontMax: bands(fmt).fontMax, budget: bands(fmt).hookHeight });

  const file = `sunmap-og${fmt.suffix}.png`;
  await tab.screenshot({
    path: resolve(outDir, file), type: 'png',
    clip: { x: 0, y: 0, width: fmt.width, height: fmt.height },
  });
  await tab.close();
  await context.close();

  const bytes = statSync(resolve(outDir, file)).size;
  results.push({ file, fmt, fontSize, bytes });
  console.log(`  og/${file.padEnd(24)} ${fmt.width}x${fmt.height} css `
    + `-> ${fmt.width * DPI}x${fmt.height * DPI} px  hook ${fontSize}px  ${(bytes / 1024).toFixed(0)} KB`);
}

await browser.close();
writeGallery([{ slug: 'hub', hook: CARD.hook, filePrefix: 'sunmap-og' }]);
console.log(`font resolved: ${resolvedFont} (referenced by name, no binary embedded)`);
console.log(`wrote ${results.length} cards to og/`);
