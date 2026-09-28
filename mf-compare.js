// Mutual fund rolling-return comparison. NAVs come from /api/mf/nav/<code> (a cached proxy for mfapi.in);
// every return is worked out here in the browser.

const MAX_FUNDS = 6;
const COLORS = ['#2f6b46', '#ef795d', '#3b6fb6', '#b8872b', '#8a5cb8', '#17201b'];
const BENCHMARK_CODE = '120716'; // UTI Nifty 50 Index Fund - Direct Plan - Growth (a search for it lists Nifty Next 50 first)
const PRESETS = [
  ['Flexi cap funds vs Nifty 50', ['122639', '118955', BENCHMARK_CODE]], // Parag Parikh Flexi Cap, HDFC Flexi Cap
  ['Three small cap funds', ['118778', '125354', '125497']], // Nippon India, Axis, SBI Small Cap
];
const DAY_MS = 86400000;
const BUCKETS = [[-Infinity, 0, 'Below 0%'], [0, 0.05, '0–5%'], [0.05, 0.1, '5–10%'], [0.1, 0.15, '10–15%'], [0.15, 0.2, '15–20%'], [0.2, Infinity, '20% and above']];

const state = { funds: [], years: 3, period: 'common', directOnly: true };
const $ = (selector) => document.querySelector(selector);

const esc = (text) => String(text).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const toDay = (iso) => Date.UTC(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10)) / DAY_MS;
const fmtDate = (day) => new Date(day * DAY_MS).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'UTC' });
const pct = (value, digits = 1) => (value == null || !Number.isFinite(value) ? '—' : `${value < 0 ? '−' : ''}${Math.abs(value * 100).toFixed(digits)}%`);
const rupees = (value) => `₹${Math.round(value).toLocaleString('en-IN')}`;

function yearsBefore(day, years) {
  const date = new Date(day * DAY_MS);
  return Date.UTC(date.getUTCFullYear() - years, date.getUTCMonth(), date.getUTCDate()) / DAY_MS;
}

function lowerBound(arr, x) {
  let lo = 0, hi = arr.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (arr[mid] < x) lo = mid + 1; else hi = mid; }
  return lo;
}

// Index of the last entry on or before x (-1 if none).
const atOrBefore = (arr, x) => lowerBound(arr, x + 1e-9) - 1;

function shortName(name) {
  let short = name.split(/\s+-\s+/)[0].trim();
  if (/regular/i.test(name)) short += ' · Regular';
  if (/idcw|dividend/i.test(name)) short += ' · IDCW';
  return short;
}

const isDirectGrowth = (name) => /direct/i.test(name) && /growth/i.test(name) && !/idcw|dividend|bonus/i.test(name);

function setStatus(message, isError = false) {
  const el = $('#mf-status');
  el.textContent = message;
  el.classList.toggle('error', isError);
}

// ---------- data ----------

async function getJson(url) {
  const response = await fetch(url);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || 'Request failed.');
  return data;
}

async function searchFunds(query) {
  const data = await getJson(`/api/mf/search?q=${encodeURIComponent(query)}`);
  return data.results || [];
}

async function addFund(code, { quiet = false } = {}) {
  if (state.funds.some((fund) => fund.code === code)) return;
  if (state.funds.length >= MAX_FUNDS) { setStatus(`You can compare up to ${MAX_FUNDS} funds. Remove one first.`, true); return; }
  if (!quiet) setStatus('Loading NAV history…');
  try {
    const data = await getJson(`/api/mf/nav/${code}`);
    if (state.funds.some((fund) => fund.code === data.code) || state.funds.length >= MAX_FUNDS) return;
    const usedColors = new Set(state.funds.map((fund) => fund.color));
    state.funds.push({
      code: data.code,
      name: data.name,
      short: shortName(data.name),
      category: data.category,
      stale: data.stale,
      t: Float64Array.from(data.points, (point) => toDay(point[0])),
      nav: Float64Array.from(data.points, (point) => point[1]),
      color: COLORS.find((color) => !usedColors.has(color)),
    });
    if (!quiet) setStatus(data.stale ? 'Showing the last saved NAVs: the data source could not be reached.' : '');
  } catch (error) {
    setStatus(`Could not load scheme ${code}: ${error.message}`, true);
  }
  render();
}

function removeFund(code) {
  state.funds = state.funds.filter((fund) => fund.code !== code);
  setStatus('');
  render();
}

// ---------- maths ----------

// The slice of a fund's NAVs to use: all of it, or only the dates every chosen fund has.
function slicePeriod(fund, range) {
  if (!range) return { t: fund.t, nav: fund.nav };
  const a = lowerBound(fund.t, range[0]);
  const b = atOrBefore(fund.t, range[1]) + 1;
  return { t: fund.t.subarray(a, b), nav: fund.nav.subarray(a, b) };
}

function commonRange(funds) {
  const start = Math.max(...funds.map((fund) => fund.t[0]));
  const end = Math.min(...funds.map((fund) => fund.t[fund.t.length - 1]));
  return start < end ? [start, end] : null;
}

// Yearly return (CAGR) over `years`, ending on every NAV date that has a NAV `years` earlier (within a week).
function rolling(series, years) {
  const t = [], v = [];
  let j = 0;
  for (let i = 0; i < series.t.length; i++) {
    const target = yearsBefore(series.t[i], years);
    if (target < series.t[0]) continue;
    while (j + 1 < series.t.length && series.t[j + 1] <= target) j++;
    if (target - series.t[j] > 7) continue;
    t.push(series.t[i]);
    v.push(Math.pow(series.nav[i] / series.nav[j], 1 / years) - 1);
  }
  return { t, v };
}

function summarise(values) {
  const n = values.length;
  if (!n) return null;
  const sorted = Float64Array.from(values).sort();
  const mean = values.reduce((sum, x) => sum + x, 0) / n;
  const sd = Math.sqrt(values.reduce((sum, x) => sum + (x - mean) ** 2, 0) / n);
  const median = n % 2 ? sorted[(n - 1) / 2] : (sorted[n / 2 - 1] + sorted[n / 2]) / 2;
  const share = (test) => values.reduce((count, x) => count + (test(x) ? 1 : 0), 0) / n;
  return {
    n, mean, median, sd, min: sorted[0], max: sorted[n - 1],
    negative: share((x) => x < 0), above10: share((x) => x >= 0.1), above15: share((x) => x >= 0.15),
    buckets: BUCKETS.map(([lo, hi]) => share((x) => x >= lo && x < hi)),
  };
}

function periodStats(series) {
  const n = series.t.length;
  if (n < 2) return null;
  const years = (series.t[n - 1] - series.t[0]) / 365.25;
  let peak = series.nav[0], worst = 0, sum = 0, sumSq = 0;
  for (let i = 0; i < n; i++) {
    peak = Math.max(peak, series.nav[i]);
    worst = Math.min(worst, series.nav[i] / peak - 1);
    if (i) { const r = Math.log(series.nav[i] / series.nav[i - 1]); sum += r; sumSq += r * r; }
  }
  const mean = sum / (n - 1);
  const perYear = (n - 1) / Math.max(years, 1 / 365);
  return {
    start: series.t[0], end: series.t[n - 1],
    cagr: years > 0 ? Math.pow(series.nav[n - 1] / series.nav[0], 1 / years) - 1 : null,
    grown: 10000 * series.nav[n - 1] / series.nav[0],
    vol: Math.sqrt(Math.max(0, sumSq / (n - 1) - mean * mean) * perYear),
    worst,
  };
}

// Point-to-point returns as of the fund's latest NAV (CAGR for periods over a year).
function trailing(fund) {
  const last = fund.t.length - 1;
  const out = {};
  for (const years of [1, 3, 5, 10]) {
    const target = yearsBefore(fund.t[last], years);
    const j = atOrBefore(fund.t, target);
    out[years] = target < fund.t[0] || j < 0 || target - fund.t[j] > 7 ? null : Math.pow(fund.nav[last] / fund.nav[j], 1 / years) - 1;
  }
  const span = (fund.t[last] - fund.t[0]) / 365.25;
  out.launch = span >= 1 ? Math.pow(fund.nav[last] / fund.nav[0], 1 / span) - 1 : null;
  return out;
}

// On dates every fund has a rolling return: how often each fund was best, and how often row beat column.
function headToHead(rolls) {
  const maps = rolls.map((roll) => new Map(roll.t.map((day, i) => [day, roll.v[i]])));
  const best = rolls.map(() => 0);
  const beat = rolls.map(() => rolls.map(() => 0));
  let n = 0;
  for (const day of rolls[0].t) {
    const values = maps.map((map) => map.get(day));
    if (values.some((value) => value === undefined)) continue;
    n++;
    best[values.indexOf(Math.max(...values))]++;
    values.forEach((a, i) => values.forEach((b, k) => { if (a > b) beat[i][k]++; }));
  }
  return { n, best: best.map((count) => count / (n || 1)), beat: beat.map((row) => row.map((count) => count / (n || 1))) };
}

// ---------- charts ----------

function niceTicks(lo, hi, count) {
  if (lo === hi) { lo -= Math.abs(lo) * 0.1 || 0.01; hi += Math.abs(hi) * 0.1 || 0.01; }
  const raw = (hi - lo) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((k) => k * mag).find((s) => s >= raw);
  const ticks = [];
  for (let v = Math.floor(lo / step) * step; v <= Math.ceil(hi / step) * step + step / 2; v += step) ticks.push(+v.toPrecision(12));
  return ticks;
}

function thin(t, v, max = 700) {
  if (t.length <= max) return { t, v };
  const step = Math.ceil(t.length / max);
  const out = { t: [], v: [] };
  for (let i = 0; i < t.length; i += step) { out.t.push(t[i]); out.v.push(v[i]); }
  if (out.t[out.t.length - 1] !== t[t.length - 1]) { out.t.push(t[t.length - 1]); out.v.push(v[v.length - 1]); }
  return out;
}

function lineChart(el, series, { height = 320, fmtY, zero = false }) {
  series = series.filter((s) => s.t.length);
  if (!series.length) { el.innerHTML = '<p class="mf-note">Not enough history for this holding period.</p>'; return; }
  const W = Math.max(320, el.clientWidth), H = height;
  const m = { l: 58, r: 14, t: 10, b: 28 };
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  for (const s of series) {
    x0 = Math.min(x0, s.t[0]); x1 = Math.max(x1, s.t[s.t.length - 1]);
    for (const value of s.v) { y0 = Math.min(y0, value); y1 = Math.max(y1, value); }
  }
  if (zero) { y0 = Math.min(y0, 0); y1 = Math.max(y1, 0); }
  const yTicks = niceTicks(y0, y1, 5);
  y0 = yTicks[0]; y1 = yTicks[yTicks.length - 1];
  const X = (t) => m.l + ((t - x0) / (x1 - x0 || 1)) * (W - m.l - m.r);
  const Y = (v) => H - m.b - ((v - y0) / (y1 - y0 || 1)) * (H - m.t - m.b);

  const firstYear = new Date(x0 * DAY_MS).getUTCFullYear() + 1, lastYear = new Date(x1 * DAY_MS).getUTCFullYear();
  const yearStep = Math.max(1, Math.ceil((lastYear - firstYear + 1) / Math.max(2, Math.floor((W - m.l) / 70))));
  let svg = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img">`;
  for (const tick of yTicks) {
    svg += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(tick)}" y2="${Y(tick)}" stroke="${zero && tick === 0 ? '#17201b' : '#d9ddd5'}" stroke-width="1"/>`;
    svg += `<text x="${m.l - 8}" y="${Y(tick) + 4}" text-anchor="end">${fmtY(tick)}</text>`;
  }
  for (let year = firstYear; year <= lastYear; year += yearStep) {
    const x = X(Date.UTC(year, 0, 1) / DAY_MS);
    svg += `<line x1="${x}" x2="${x}" y1="${H - m.b}" y2="${H - m.b + 4}" stroke="#667069"/><text x="${x}" y="${H - 8}" text-anchor="middle">${year}</text>`;
  }
  for (const s of series) {
    const p = thin(s.t, s.v);
    const d = p.t.map((t, i) => `${i ? 'L' : 'M'}${X(t).toFixed(1)},${Y(p.v[i]).toFixed(1)}`).join('');
    svg += `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="1.6" stroke-linejoin="round"/>`;
  }
  svg += `<line class="mf-cursor" y1="${m.t}" y2="${H - m.b}" stroke="#17201b" stroke-dasharray="3 3" visibility="hidden"/>`;
  svg += series.map((s) => `<circle class="mf-dot" r="3.5" fill="${s.color}" visibility="hidden"/>`).join('');
  svg += `<rect x="${m.l}" y="${m.t}" width="${W - m.l - m.r}" height="${H - m.t - m.b}" fill="transparent"/></svg><div class="mf-tip"></div>`;
  el.innerHTML = svg;

  const svgEl = el.querySelector('svg'), tip = el.querySelector('.mf-tip'), cursor = el.querySelector('.mf-cursor');
  const dots = [...el.querySelectorAll('.mf-dot')];
  const hide = () => { tip.style.display = 'none'; cursor.setAttribute('visibility', 'hidden'); dots.forEach((dot) => dot.setAttribute('visibility', 'hidden')); };
  const move = (event) => {
    const box = svgEl.getBoundingClientRect();
    const px = ((event.clientX - box.left) / box.width) * W;
    if (px < m.l || px > W - m.r) { hide(); return; }
    const day = x0 + ((px - m.l) / (W - m.l - m.r)) * (x1 - x0);
    let rows = '';
    series.forEach((s, k) => {
      const i = atOrBefore(s.t, day);
      if (i < 0 || day - s.t[i] > 10) { dots[k].setAttribute('visibility', 'hidden'); return; }
      dots[k].setAttribute('cx', X(s.t[i])); dots[k].setAttribute('cy', Y(s.v[i])); dots[k].setAttribute('visibility', 'visible');
      rows += `<div><span><i style="background:${s.color}"></i>${esc(s.name)}</span><strong>${fmtY(s.v[i], true)}</strong></div>`;
    });
    if (!rows) { hide(); return; }
    cursor.setAttribute('x1', px); cursor.setAttribute('x2', px); cursor.setAttribute('visibility', 'visible');
    tip.innerHTML = `<b>${fmtDate(day)}</b>${rows}`;
    tip.style.display = 'block';
    const left = (px / W) * box.width;
    tip.style.left = `${Math.max(0, Math.min(left + 14, box.width - tip.offsetWidth))}px`;
    tip.style.top = `${Math.max(0, event.clientY - box.top - tip.offsetHeight - 12) + 12}px`;
  };
  svgEl.addEventListener('mousemove', move);
  svgEl.addEventListener('touchmove', (event) => move(event.touches[0]), { passive: true });
  svgEl.addEventListener('mouseleave', hide);
}

// ---------- rendering ----------

const fundCell = (fund) => `<td><i style="background:${fund.color}"></i>${esc(fund.short)}</td>`;

// Cells for one column, with the best value (highest, or lowest when lowerIsBetter) highlighted.
function cells(values, format, { lowerIsBetter = false, markNegative = true, highlight = true } = {}) {
  const valid = values.filter((value) => value != null && Number.isFinite(value));
  const best = highlight && valid.length > 1 ? (lowerIsBetter ? Math.min(...valid) : Math.max(...valid)) : null;
  return values.map((value) => {
    const classes = [value === best ? 'best' : '', markNegative && value < 0 ? 'neg' : ''].filter(Boolean).join(' ');
    return `<td${classes ? ` class="${classes}"` : ''}>${format(value)}</td>`;
  });
}

function table(head, rows) {
  return `<div class="mf-tablewrap"><table class="mf-table"><thead><tr>${head.map((h) => `<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.map((row) => `<tr>${row.join('')}</tr>`).join('')}</tbody></table></div>`;
}

// Build a table with one row per fund from per-column value arrays.
function fundTable(funds, columns) {
  const columnCells = columns.map((col) => cells(col.values, col.format || pct, col));
  return table(['Fund', ...columns.map((col) => col.label)], funds.map((fund, i) => [fundCell(fund), ...columnCells.map((col) => col[i])]));
}

function renderChips() {
  $('#mf-chips').innerHTML = state.funds.map((fund) => `<div class="mf-chip" title="${esc(fund.name)}"><i style="background:${fund.color}"></i><span>${esc(fund.short)}</span><small>${esc(fund.category.replace(/^.*?Scheme\s*-\s*/i, ''))}</small><button type="button" data-remove="${esc(fund.code)}" aria-label="Remove ${esc(fund.short)}">×</button></div>`).join('');
}

function renderEmpty() {
  $('#mf-out').innerHTML = `<div class="mf-empty">Search for a fund above to begin, or try a ready-made comparison:<br>
    ${PRESETS.map(([label, codes]) => `<button class="mf-btn" type="button" data-preset="${codes.join(',')}">${label}</button>`).join('')}</div>`;
}

function render() {
  renderChips();
  syncUrl();
  const funds = state.funds;
  if (!funds.length) { renderEmpty(); return; }

  const years = state.years;
  const range = state.period === 'common' && funds.length > 1 ? commonRange(funds) : null;
  if (state.period === 'common' && funds.length > 1 && !range) {
    $('#mf-out').innerHTML = '<p class="mf-empty">These funds have no dates in common. Switch "Dates compared" to each fund\'s full history.</p>';
    return;
  }
  const series = funds.map((fund) => slicePeriod(fund, range));
  const rolls = series.map((s) => rolling(s, years));
  const stats = rolls.map((roll) => summarise(roll.v));
  const label = `${years}-year`;
  const rangeNote = range ? `Common period ${fmtDate(range[0])} to ${fmtDate(range[1])}` : 'Each fund over its full history';
  const withRolls = funds.map((fund, i) => ({ fund, stat: stats[i] })).filter((row) => row.stat);
  const statFunds = withRolls.map((row) => row.fund);
  const col = (pick) => withRolls.map((row) => pick(row.stat));

  let html = '';
  html += `<div class="mf-block"><h2>${label} rolling returns</h2><p>Each point is the yearly return (CAGR) of someone who bought ${years} year${years > 1 ? 's' : ''} before that date and held until it. ${rangeNote}.</p><div class="mf-chart" id="mf-roll-chart"></div></div>`;

  if (withRolls.length) {
    html += `<div class="mf-block"><h2>The range of outcomes</h2><p>Across every ${label} period. Green marks the best value in each column.</p>${fundTable(statFunds, [
      { label: 'Average', values: col((s) => s.mean) },
      { label: 'Median', values: col((s) => s.median) },
      { label: 'Worst', values: col((s) => s.min) },
      { label: 'Best', values: col((s) => s.max) },
      { label: 'Spread (SD)', values: col((s) => s.sd), lowerIsBetter: true, markNegative: false },
      { label: 'Lost money', values: col((s) => s.negative), lowerIsBetter: true, markNegative: false, format: (v) => pct(v, 0) },
      { label: '10%+ a year', values: col((s) => s.above10), format: (v) => pct(v, 0) },
      { label: '15%+ a year', values: col((s) => s.above15), format: (v) => pct(v, 0) },
      { label: 'Periods', values: col((s) => s.n), markNegative: false, highlight: false, format: (v) => v.toLocaleString('en-IN') },
    ])}<p class="mf-note">"Lost money", "10%+" and "15%+" are the share of ${label} periods in which the yearly return was below zero, at least 10% or at least 15%. Spread is the standard deviation of the rolling returns: lower means more consistent.</p></div>`;

    html += `<div class="mf-block"><h2>How the returns were spread</h2><p>Share of ${label} periods that landed in each band of yearly return.</p>${table(['Fund', ...BUCKETS.map((b) => b[2])], withRolls.map(({ fund, stat }) => [fundCell(fund), ...stat.buckets.map((share) => `<td>${pct(share, 0)}</td>`)]))}</div>`;
  } else {
    html += `<p class="mf-empty">None of these funds has ${years} years of history${range ? ' in the common period' : ''}. Pick a shorter holding period${range ? ' or compare each fund\'s full history' : ''}.</p>`;
  }

  if (withRolls.length > 1) {
    const idx = funds.map((fund, i) => i).filter((i) => stats[i]);
    const h2h = headToHead(idx.map((i) => rolls[i]));
    if (h2h.n) {
      html += `<div class="mf-block"><h2>Who came out ahead</h2><p>On the ${h2h.n.toLocaleString('en-IN')} dates where every fund has a ${label} return: how often each fund was the best of the group, and how often the fund in the row beat the fund in the column.</p>${table(
        ['Fund', 'Best of the group', ...statFunds.map((fund) => `vs <span style="color:${fund.color}">●</span> ${esc(fund.short)}`)],
        statFunds.map((fund, r) => [fundCell(fund), `<td${h2h.best[r] === Math.max(...h2h.best) ? ' class="best"' : ''}>${pct(h2h.best[r], 0)}</td>`, ...statFunds.map((other, c) => `<td>${r === c ? '—' : pct(h2h.beat[r][c], 0)}</td>`)]),
      )}</div>`;
    }
  }

  const periods = series.map(periodStats);
  const withPeriod = funds.map((fund, i) => ({ fund, p: periods[i] })).filter((row) => row.p);
  html += `<div class="mf-block"><h2>Over the whole period</h2><p>${rangeNote}. Growth of ₹10,000 invested at the start, with no further investments.</p><div class="mf-chart" id="mf-growth-chart"></div>${fundTable(withPeriod.map((row) => row.fund), [
    { label: 'From', values: withPeriod.map((row) => row.p.start), markNegative: false, highlight: false, format: fmtDate },
    { label: 'Yearly return', values: withPeriod.map((row) => row.p.cagr) },
    { label: '₹10,000 became', values: withPeriod.map((row) => row.p.grown), format: rupees },
    { label: 'Volatility', values: withPeriod.map((row) => row.p.vol), lowerIsBetter: true, markNegative: false },
    { label: 'Worst fall', values: withPeriod.map((row) => row.p.worst) },
  ])}<p class="mf-note">Volatility is the annualised standard deviation of daily NAV changes. Worst fall is the biggest drop from a previous high NAV to a later low.${range ? '' : ' With full histories the funds cover different years, so these numbers are not directly comparable.'}</p></div>`;

  const trail = funds.map(trailing);
  html += `<div class="mf-block"><h2>Trailing returns</h2><p>Point-to-point returns up to each fund's latest NAV, always over its full history. These are the numbers fund factsheets quote; they depend heavily on today's date.</p>${fundTable(funds, [
    { label: 'Latest NAV', values: funds.map((fund) => fund.t[fund.t.length - 1]), markNegative: false, highlight: false, format: fmtDate },
    { label: '1 year', values: trail.map((t) => t[1]) },
    { label: '3 years', values: trail.map((t) => t[3]) },
    { label: '5 years', values: trail.map((t) => t[5]) },
    { label: '10 years', values: trail.map((t) => t[10]) },
    { label: 'Since launch', values: trail.map((t) => t.launch) },
  ])}<p class="mf-note">Returns over 1 year are yearly (CAGR). "Since launch" starts at the first NAV the data source has, which can be later than the fund's real launch.</p></div>`;

  $('#mf-out').innerHTML = html;
  drawCharts(funds, rolls, series);
}

let lastCharts = null;
function drawCharts(funds, rolls, series) {
  lastCharts = [funds, rolls, series];
  const rollEl = $('#mf-roll-chart'), growthEl = $('#mf-growth-chart');
  if (rollEl) lineChart(rollEl, funds.map((fund, i) => ({ name: fund.short, color: fund.color, t: rolls[i].t, v: rolls[i].v })), { fmtY: (v, exact) => pct(v, exact ? 1 : 0), zero: true });
  if (growthEl) {
    lineChart(growthEl, funds.map((fund, i) => {
      const s = series[i];
      return { name: fund.short, color: fund.color, t: Array.from(s.t), v: Array.from(s.nav, (nav) => (10000 * nav) / s.nav[0]) };
    }), { height: 280, fmtY: (v, exact) => (exact ? rupees(v) : v >= 100000 ? `₹${(v / 100000).toFixed(v % 100000 ? 1 : 0)}L` : `₹${Math.round(v / 1000)}k`) });
  }
}

let resizeTimer;
addEventListener('resize', () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => lastCharts && drawCharts(...lastCharts), 150); });

// ---------- URL state (so a comparison can be shared) ----------

function syncUrl() {
  const params = new URLSearchParams();
  if (state.funds.length) params.set('funds', state.funds.map((fund) => fund.code).join(','));
  params.set('years', state.years);
  if (state.period !== 'common') params.set('period', state.period);
  history.replaceState(null, '', `${location.pathname}?${params}`);
}

async function loadFromUrl() {
  const params = new URLSearchParams(location.search);
  const years = +params.get('years');
  if ([1, 2, 3, 5, 7, 10].includes(years)) { state.years = years; $('#mf-years').value = String(years); }
  if (params.get('period') === 'full') { state.period = 'full'; $('#mf-period').value = 'full'; }
  const codes = (params.get('funds') || '').split(',').filter((code) => /^\d{1,8}$/.test(code)).slice(0, MAX_FUNDS);
  if (!codes.length) { render(); return; }
  setStatus('Loading NAV history…');
  for (const code of codes) await addFund(code, { quiet: true });
  if (!$('#mf-status').classList.contains('error')) setStatus('');
}

// ---------- search box ----------

const queryEl = $('#mf-query'), resultsEl = $('#mf-results');
let searchTimer, searchSeq = 0, activeIndex = -1;

function closeResults() { resultsEl.classList.remove('open'); activeIndex = -1; }

async function runSearch() {
  const query = queryEl.value.trim();
  if (query.length < 3) { closeResults(); return; }
  const seq = ++searchSeq;
  resultsEl.innerHTML = '<p>Searching…</p>';
  resultsEl.classList.add('open');
  try {
    let rows = await searchFunds(query);
    if (seq !== searchSeq) return;
    const total = rows.length;
    if (state.directOnly) rows = rows.filter((row) => isDirectGrowth(row.name));
    resultsEl.innerHTML = rows.length
      ? rows.slice(0, 25).map((row) => `<button type="button" role="option" data-code="${esc(row.code)}">${esc(row.name)}<small>Scheme code ${esc(row.code)}</small></button>`).join('')
      : `<p>${total ? 'No Direct Growth plans match. Untick "Direct Growth plans only" to see all plans.' : 'No funds match that search.'}</p>`;
    activeIndex = -1;
  } catch (error) {
    if (seq === searchSeq) resultsEl.innerHTML = `<p>${esc(error.message)}</p>`;
  }
}

queryEl.addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(runSearch, 300); });
queryEl.addEventListener('focus', () => { if (resultsEl.innerHTML && queryEl.value.trim().length >= 3) resultsEl.classList.add('open'); });
queryEl.addEventListener('keydown', (event) => {
  const options = [...resultsEl.querySelectorAll('button')];
  if (event.key === 'Escape') { closeResults(); return; }
  if (!options.length || !resultsEl.classList.contains('open')) return;
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault();
    activeIndex = (activeIndex + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length;
    options.forEach((option, i) => option.classList.toggle('active', i === activeIndex));
    options[activeIndex].scrollIntoView({ block: 'nearest' });
  } else if (event.key === 'Enter') {
    event.preventDefault();
    options[Math.max(0, activeIndex)].click();
  }
});
resultsEl.addEventListener('click', (event) => {
  const option = event.target.closest('button[data-code]');
  if (!option) return;
  closeResults();
  queryEl.value = '';
  addFund(option.dataset.code);
});
document.addEventListener('click', (event) => { if (!event.target.closest('.mf-search')) closeResults(); });

// ---------- controls ----------

$('#mf-years').addEventListener('change', (event) => { state.years = +event.target.value; render(); });
$('#mf-period').addEventListener('change', (event) => { state.period = event.target.value; render(); });
$('#mf-direct').addEventListener('change', (event) => { state.directOnly = event.target.checked; runSearch(); });
$('#mf-bench').addEventListener('click', () => addFund(BENCHMARK_CODE));
$('#mf-chips').addEventListener('click', (event) => { const button = event.target.closest('[data-remove]'); if (button) removeFund(button.dataset.remove); });
$('#mf-out').addEventListener('click', async (event) => {
  const button = event.target.closest('[data-preset]');
  if (!button) return;
  setStatus('Loading NAV history…');
  for (const code of button.dataset.preset.split(',')) await addFund(code, { quiet: true });
  if (!$('#mf-status').classList.contains('error')) setStatus('');
});

loadFromUrl();
