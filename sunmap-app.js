// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 PUDDY Inc. <legal@puddystudios.com>
/**
 * SUNMAP - the page controller.
 *
 * Mirrors STARMAP's controller shape: a crest, a next-event card with a live
 * countdown, a category filter, a location box, and a three-column event row.
 * The only structural difference is that STARMAP steps through years and
 * SUNMAP steps through days.
 *
 * Rows are built with createElement and textContent. Event labels come from the
 * engine and place names come from a third-party geocoder, so nothing here is
 * ever interpolated into innerHTML.
 */
'use strict';

import * as geo from './sunmap-geo.js';

const $ = (id) => document.getElementById(id);
const BASE = new URL('.', import.meta.url).pathname;

/* ---- the ladder, grouped the way the filter presents it ---- */
const CATS = [
  { id: 'sun',     label: 'Sun',        keys: ['sunrise', 'sunset', 'solar_noon', 'solar_midnight'] },
  { id: 'twi',     label: 'Twilight',   keys: ['astronomical_dawn', 'nautical_dawn', 'civil_dawn',
                                               'civil_dusk', 'nautical_dusk', 'astronomical_dusk'] },
  { id: 'golden',  label: 'Golden hour', keys: ['golden_hour_start_am', 'golden_hour_end_am',
                                                'golden_hour_start_pm', 'golden_hour_end_pm'] },
  { id: 'moon',    label: 'Moon',       keys: ['moonrise', 'moonset', 'lunar_noon', 'lunar_midnight'] },
];
const CAT_OF = {};
CATS.forEach((c) => c.keys.forEach((k) => { CAT_OF[k] = c.id; }));

/* Plain-language gloss for each row. The engine gives an instant; this says what
   the instant means, the way STARMAP's sub-line names the sign. */
const GLOSS = {
  astronomical_dawn: 'Sun centre 18 deg below the horizon. The first light.',
  nautical_dawn:     'Sun centre 12 deg below. The sea horizon becomes visible.',
  civil_dawn:        'Sun centre 6 deg below. Outdoor work needs no lamp.',
  golden_hour_start_am: 'Sun centre 4 deg below. Warm, low, long-shadowed light.',
  sunrise:           'The upper limb clears the horizon, refraction included.',
  golden_hour_end_am: 'Sun centre passes 6 deg above, climbing.',
  solar_noon:        'Upper transit. The sun is due south or north, and highest.',
  golden_hour_start_pm: 'Sun centre drops back through 6 deg above.',
  sunset:            'The upper limb touches the horizon, refraction included.',
  golden_hour_end_pm: 'Sun centre 4 deg below. The warm light is gone.',
  civil_dusk:        'Sun centre 6 deg below. Lamps come on.',
  nautical_dusk:     'Sun centre 12 deg below. The sea horizon is lost.',
  astronomical_dusk: 'Sun centre 18 deg below. Full astronomical night.',
  solar_midnight:    'Lower transit. The sun is at its lowest, below the horizon.',
  moonrise:          'The upper limb of the moon clears the horizon.',
  lunar_noon:        'Upper transit. The moon is highest in your sky.',
  moonset:           'The upper limb of the moon touches the horizon.',
  lunar_midnight:    'Lower transit. The moon is at its lowest.',
};

const STATUS_TEXT = {
  always_above: 'None - the body stays above this altitude all day',
  always_below: 'None - the body stays below this altitude all day',
  none_today:   'None - no crossing falls inside this local day',
};

const LS_CATS = 'sunmap.cats';
const SUN_GLYPH = '☉';   // text sigil, not an image emoji
const MOON_GLYPH = '☽';

let state = {
  loc: null,
  date: null,
  result: null,
  cats: new Set(JSON.parse(localStorage.getItem(LS_CATS) || '["sun","twi","golden"]')),
};

/* ------------------------------------------------------------------ worker -- */
const worker = new Worker(BASE + 'sunmap-worker.js', { type: 'module' });
let pending = null;

worker.onmessage = (ev) => {
  const d = ev.data;
  if (!d || !d.ok) { fail((d && d.error) || 'the engine did not answer'); return; }
  state.result = d.result;
  render();
};
worker.onerror = (e) => fail('the engine failed to load: ' + (e.message || 'unknown'));

function fail(msg) {
  const box = $('err');
  box.textContent = 'Could not solve this day: ' + msg;
}

function compute() {
  if (!state.loc || !state.date) return;
  $('err').textContent = '';
  clearTimeout(pending);
  pending = setTimeout(() => {
    worker.postMessage({
      base: BASE,
      coords: { lat: state.loc.lat, lon: state.loc.lon, alt: state.loc.alt || 0 },
      date: state.date, tz: state.loc.tz, moon: true,
    });
  }, 10);
}

/* -------------------------------------------------------------------- time -- */
const pad = (n) => String(n).padStart(2, '0');
const dayIn = (tz) => new Intl.DateTimeFormat('en-CA',
  { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());

function shiftDay(iso, n) {
  const [y, m, d] = iso.split('-').map(Number);
  const t = new Date(Date.UTC(y, m - 1, d));
  t.setUTCDate(t.getUTCDate() + n);
  return `${t.getUTCFullYear()}-${pad(t.getUTCMonth() + 1)}-${pad(t.getUTCDate())}`;
}

const fmtTime = (iso) => {
  const d = new Date(iso);
  return new Intl.DateTimeFormat('en-US', {
    hour: 'numeric', minute: '2-digit', second: '2-digit',
    hour12: true, timeZone: state.loc.tz,
  }).format(d);
};

const zoneAbbr = (iso) => {
  const parts = new Intl.DateTimeFormat('en-US',
    { timeZone: state.loc.tz, timeZoneName: 'short' }).formatToParts(new Date(iso));
  const p = parts.find((x) => x.type === 'timeZoneName');
  return p ? p.value : state.loc.tz.split('/').pop().replace(/_/g, ' ');
};

function longDate(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return new Intl.DateTimeFormat('en-US', {
    weekday: 'long', month: 'long', day: 'numeric', year: 'numeric', timeZone: 'UTC',
  }).format(new Date(Date.UTC(y, m - 1, d)));
}

/* ------------------------------------------------------------------ render -- */
function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function row(e) {
  const isMoon = e.body === 'moon';
  const has = !!e.local;
  const r = el('div', 'ev ' + (has ? (isMoon ? 'is-moon' : 'is-sun') : 'is-none'));

  const left = el('div');
  left.append(el('div', 'd', has ? fmtTime(e.utc) : 'None'));
  left.append(el('div', 't', has ? zoneAbbr(e.utc) : ''));

  const mid = el('div');
  const title = el('div', 'title');
  const g = el('span', 'gl', isMoon ? MOON_GLYPH : SUN_GLYPH);
  title.append(g, document.createTextNode(' ' + e.label));
  mid.append(title);
  mid.append(el('div', 'sub', has ? (GLOSS[e.key] || '')
                                  : (STATUS_TEXT[e.status] || e.status || '')));

  const meta = el('div', 'meta');
  meta.append(el('span', 'badge', isMoon ? 'MOON' : 'SUN'));

  r.append(left, mid, meta);
  return r;
}

function render() {
  const res = state.result;
  if (!res) return;

  $('day-now').textContent = longDate(state.date).replace(/,? \d{4}$/, '');
  $('day-pick').value = state.date;
  $('loc-active').textContent = state.loc.label;

  const shown = res.events.filter((e) => state.cats.has(CAT_OF[e.key]));
  const list = $('list');
  list.textContent = '';
  list.append(el('div', 'month', `${longDate(state.date)} - ${state.loc.label}`));
  if (!shown.length) {
    list.append(el('p', 'sub', 'No event types selected. Tap a category above.'));
  } else {
    shown.forEach((e) => list.append(row(e)));
  }

  // the note bar, mirroring STARMAP's moonnote
  const note = $('moonnote');
  note.textContent = '';
  const dl = res.day_length_s;
  const bits = [];
  if (dl != null) bits.push(`Day length ${Math.floor(dl / 3600)}h ${pad(Math.floor(dl % 3600 / 60))}m`);
  if (res.moon) bits.push(`Moon ${res.moon.illumination_pct.toFixed(1)}% illuminated`);
  bits.push(`Solved on your device for ${state.loc.lat.toFixed(4)}, ${state.loc.lon.toFixed(4)}`);
  note.textContent = bits.join('  -  ');

  nextEvent(res);
}

/* ---- the next-event card + live countdown (STARMAP's, retimed to a day) ---- */
let tick = null;
function nextEvent(res) {
  clearInterval(tick);
  const now = Date.now();
  const upcoming = res.events
    .filter((e) => e.utc && state.cats.has(CAT_OF[e.key]) && Date.parse(e.utc) > now)
    .sort((a, b) => Date.parse(a.utc) - Date.parse(b.utc))[0];

  if (!upcoming) {
    $('next-name').textContent = 'Nothing further today';
    $('next-when').textContent = 'Step to the next day to keep going';
    $('count').textContent = '--:--:--';
    const s = el('small', null, 'until next'); s.id = 'count-lbl';
    $('count').append(s);
    return;
  }
  $('next-name').textContent =
    (upcoming.body === 'moon' ? MOON_GLYPH : SUN_GLYPH) + ' ' + upcoming.label;
  $('next-when').textContent = `${longDate(state.date)} - ${fmtTime(upcoming.utc)}`;

  const target = Date.parse(upcoming.utc);
  const paint = () => {
    let s = Math.max(0, Math.round((target - Date.now()) / 1000));
    const h = Math.floor(s / 3600); s -= h * 3600;
    const m = Math.floor(s / 60); s -= m * 60;
    $('count').textContent = `${pad(h)}:${pad(m)}:${pad(s)}`;
    const lbl = el('small', null, 'until next'); lbl.id = 'count-lbl';
    $('count').append(lbl);
  };
  paint();
  tick = setInterval(paint, 1000);
}

/* -------------------------------------------------------------------- chips -- */
function buildCats() {
  const seg = $('cats');
  seg.textContent = '';
  CATS.forEach((c) => {
    const b = el('button', 'chip' + (state.cats.has(c.id) ? ' on' : ''), c.label);
    b.type = 'button';
    b.setAttribute('aria-pressed', String(state.cats.has(c.id)));
    b.onclick = () => {
      if (state.cats.has(c.id)) state.cats.delete(c.id); else state.cats.add(c.id);
      localStorage.setItem(LS_CATS, JSON.stringify([...state.cats]));
      buildCats();
      render();
    };
    seg.append(b);
  });
}

/* ----------------------------------------------------------------- location -- */
let debounce;
function wireLocation() {
  const input = $('loc-search');
  const box = $('loc-suggest');

  input.addEventListener('input', () => {
    const q = input.value.trim();
    clearTimeout(debounce);
    if (q.length < 3) { box.textContent = ''; box.style.display = 'none'; return; }
    debounce = setTimeout(async () => {
      let res = [];
      try { res = await geo.suggest(q); } catch { res = []; }
      box.textContent = '';
      if (!res.length) { box.style.display = 'none'; return; }
      box.style.display = 'block';
      res.slice(0, 6).forEach((r) => {
        const li = el('li', null, r.label);   // untrusted geocoder text
        li.setAttribute('role', 'option');
        li.tabIndex = 0;
        const pick = async () => {
          const loc = await geo.chooseLocation(r);
          setLocation(loc);
          box.textContent = ''; box.style.display = 'none'; input.value = '';
        };
        li.onclick = pick;
        li.onkeydown = (ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); pick(); } };
        box.append(li);
      });
    }, 250);
  });

  $('loc-here').onclick = async () => {
    $('loc-active').textContent = 'Locating...';
    try { setLocation(await geo.useDeviceLocation()); }
    catch {
      try { setLocation(await geo.useIPLocation()); }
      catch { fail('could not determine your location - search for a place above'); }
    }
  };
}

function setLocation(loc) {
  if (!loc || !isFinite(loc.lat) || !isFinite(loc.lon)) return;
  state.loc = loc;
  state.date = dayIn(loc.tz);
  compute();
}

/* -------------------------------------------------------------------- boot -- */
function wireDays() {
  $('day-prev').onclick = () => { state.date = shiftDay(state.date, -1); compute(); };
  $('day-next').onclick = () => { state.date = shiftDay(state.date, 1); compute(); };
  $('day-today').onclick = () => { state.date = dayIn(state.loc.tz); compute(); };
  $('day-pick').onchange = (e) => { if (e.target.value) { state.date = e.target.value; compute(); } };
}

(async function boot() {
  buildCats();
  wireDays();
  wireLocation();
  let loc;
  try { loc = await geo.initLocation(); } catch { loc = null; }
  setLocation(loc || {
    lat: 34.0522, lon: -118.2437, alt: 0, tz: 'America/Los_Angeles',
    label: 'Los Angeles, California, United States', source: 'default',
  });
})();
