// Mutual fund rolling-return comparison (mf-compare.html), fund SIP calculator (mf-sip.html, <body data-mf-page="sip">)
// and fund SWP calculator (mf-swp.html, <body data-mf-page="swp">).
// NAVs come from /api/mf/nav/<code> (a cached proxy for mfapi.in); every return is worked out here in the browser.

const SIP_PAGE = document.body.dataset.mfPage === 'sip';
const SWP_PAGE = document.body.dataset.mfPage === 'swp';

const MAX_FUNDS = 6;
const COLORS = ['#2f6b46', '#ef795d', '#3b6fb6', '#b8872b', '#8a5cb8', '#17201b'];
const BENCHMARK_CODE = '120716'; // UTI Nifty 50 Index Fund - Direct Plan - Growth
const PRESETS = [
  ['Flexi cap funds vs Nifty 50', ['122639', '118955', BENCHMARK_CODE]], // Parag Parikh Flexi Cap, HDFC Flexi Cap
  ['Three small cap funds', ['118778', '125354', '125497']], // Nippon India, Axis, SBI Small Cap
];
const DAY_MS = 86400000;
const BUCKETS = [[-Infinity, 0, 'Below 0%'], [0, 0.05, '0–5%'], [0.05, 0.1, '5–10%'], [0.1, 0.15, '10–15%'], [0.15, 0.2, '15–20%'], [0.2, Infinity, '20% and above']];

const SIP_DEFAULT = { amount: 10000, from: null, day: 5, stepup: 0 }; // from: 'YYYY-MM', or null for 5 years back
// from: 'YYYY-MM', or null for 10 years back; horizon: years each start month is tested over
const SWP_DEFAULT = { corpus: 1000000, withdraw: 6000, from: null, day: 5, stepup: 0, horizon: 10 };
const state = { funds: [], years: 3, period: 'common', directOnly: true, sip: { ...SIP_DEFAULT }, swp: { ...SWP_DEFAULT } };
const $ = (selector) => document.querySelector(selector);

const esc = (text) => String(text).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const toDay = (iso) => Date.UTC(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10)) / DAY_MS;
const fmtDate = (day) => new Date(day * DAY_MS).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'UTC' });
const pct = (value, digits = 1) => (value == null || !Number.isFinite(value) ? '—' : `${value < 0 ? '−' : ''}${Math.abs(value * 100).toFixed(digits)}%`);
const rupees = (value) => `₹${Math.round(value).toLocaleString('en-IN')}`;
const rupeesShort = (value) => (value >= 1e7 ? `₹${+(value / 1e7).toFixed(2)}Cr` : value >= 1e5 ? `₹${+(value / 1e5).toFixed(1)}L` : value >= 1000 ? `₹${Math.round(value / 1000)}k` : `₹${Math.round(value)}`);
const toMonth = (day) => new Date(day * DAY_MS).toISOString().slice(0, 7);

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

// ---------- SIP ----------

// Every fund is valued on the same date: the earliest of their latest NAVs.
const sipEnd = (funds) => Math.min(...funds.map((fund) => fund.t[fund.t.length - 1]));

// Five years before the end, or the month after the youngest fund's first NAV if that is later.
function sipFrom(funds) {
  if (state.sip.from) return state.sip.from;
  const end = sipEnd(funds);
  const youngest = Math.max(...funds.map((fund) => fund.t[0]));
  return toMonth(Math.min(end, Math.max(yearsBefore(end, 5), youngest + 31)));
}

// A monthly SIP on `day` of each month from `from` to `end`. Each instalment buys units at the first NAV
// on or after its date; months before the fund's first NAV are skipped. The step-up raises the
// instalment every 12 months from the start month.
function simulateSip(fund, { amount, day, stepup }, from, end) {
  const [year, month] = from.split('-').map(Number);
  const buys = [];
  let instalment = amount;
  for (let k = 0; ; k++) {
    const date = Date.UTC(year, month - 1 + k, day) / DAY_MS;
    if (date > end) break;
    if (k && k % 12 === 0) instalment *= 1 + stepup;
    if (date < fund.t[0]) continue;
    const i = lowerBound(fund.t, date);
    if (i >= fund.t.length || fund.t[i] > end) break;
    buys.push({ i, day: fund.t[i], amount: instalment, units: instalment / fund.nav[i] });
  }
  if (!buys.length) return null;
  const last = atOrBefore(fund.t, end);
  const t = [], value = [], invested = [];
  let units = 0, paid = 0, b = 0;
  for (let p = buys[0].i; p <= last; p++) {
    while (b < buys.length && buys[b].i <= p) { units += buys[b].units; paid += buys[b].amount; b++; }
    t.push(fund.t[p]); value.push(units * fund.nav[p]); invested.push(paid);
  }
  const finalValue = value[value.length - 1], totalPaid = invested[invested.length - 1];
  return {
    first: buys[0].day, count: buys.length, invested: totalPaid, value: finalValue, gain: finalValue - totalPaid,
    xirr: xirr([...buys.map((buy) => [buy.day, -buy.amount]), [fund.t[last], finalValue]]),
    t, v: value, paid: invested,
  };
}

// Yearly rate that makes the cash flows ([day, amount], money in negative) add up to zero, by bisection.
function xirr(flows) {
  const d0 = flows[0][0];
  const npv = (rate) => flows.reduce((sum, [day, amount]) => sum + amount / Math.pow(1 + rate, (day - d0) / 365), 0);
  let lo = -0.99, hi = 10;
  const sign = Math.sign(npv(lo));
  if (sign === Math.sign(npv(hi))) return null;
  for (let k = 0; k < 100; k++) {
    const mid = (lo + hi) / 2;
    if (Math.sign(npv(mid)) === sign) lo = mid; else hi = mid;
  }
  return (lo + hi) / 2;
}

function sipBlock(funds) {
  const end = sipEnd(funds), from = sipFrom(funds), sip = state.sip;
  const minMonth = toMonth(Math.min(...funds.map((fund) => fund.t[0])));
  const dayOptions = Array.from({ length: 28 }, (_, i) => `<option value="${i + 1}"${i + 1 === sip.day ? ' selected' : ''}>${i + 1}</option>`).join('');
  const stepOptions = [0, 5, 10, 15, 20].map((p) => `<option value="${p}"${p / 100 === sip.stepup ? ' selected' : ''}>${p ? `${p}% a year` : 'None'}</option>`).join('');
  return `<div class="mf-block" id="mf-sip"><h2>What the SIP became</h2><p>What a monthly SIP in each fund would have become, worked out on the fund's actual NAVs. Each instalment buys units at the first NAV on or after the SIP date, and every fund is valued on ${fmtDate(end)}.</p>
    <div class="mf-options mf-sip-options">
      <div class="mf-field"><label for="mf-sip-amount">Monthly SIP (₹)</label><input id="mf-sip-amount" type="number" min="100" max="10000000" step="500" value="${sip.amount}" inputmode="numeric"></div>
      <div class="mf-field"><label for="mf-sip-from">Start month</label><input id="mf-sip-from" type="month" min="${minMonth}" max="${toMonth(end)}" value="${from}"></div>
      <div class="mf-field"><label for="mf-sip-day">SIP date</label><select id="mf-sip-day">${dayOptions}</select></div>
      <div class="mf-field"><label for="mf-sip-stepup">Yearly step-up</label><select id="mf-sip-stepup">${stepOptions}</select></div>
    </div><div id="mf-sip-out"></div></div>`;
}

function renderSip() {
  const out = $('#mf-sip-out');
  if (!out) return;
  const funds = state.funds, sip = state.sip;
  const end = sipEnd(funds), from = sipFrom(funds);
  if (!(sip.amount >= 100 && sip.amount <= 10000000)) { out.innerHTML = '<p class="mf-empty">Enter a monthly SIP between ₹100 and ₹1,00,00,000.</p>'; return; }
  if (!/^\d{4}-\d{2}$/.test(from) || from > toMonth(end)) { out.innerHTML = `<p class="mf-empty">Pick a start month on or before ${fmtDate(end)}.</p>`; return; }
  const rows = funds.map((fund) => ({ fund, r: simulateSip(fund, sip, from, end) })).filter((row) => row.r);
  if (!rows.length) { out.innerHTML = '<p class="mf-empty">No SIP instalments fall between the start month and the latest NAV.</p>'; return; }
  const late = rows.filter((row) => toMonth(row.r.first) > from);
  const longest = rows.reduce((a, b) => (b.r.count > a.r.count ? b : a));
  out.innerHTML = `<div class="mf-chart" id="mf-sip-chart"></div>${fundTable(rows.map((row) => row.fund), [
    { label: 'First SIP', values: rows.map((row) => row.r.first), markNegative: false, highlight: false, format: fmtDate },
    { label: 'Instalments', values: rows.map((row) => row.r.count), markNegative: false, highlight: false, format: (v) => v.toLocaleString('en-IN') },
    { label: 'Invested', values: rows.map((row) => row.r.invested), markNegative: false, highlight: false, format: rupees },
    { label: 'Value', values: rows.map((row) => row.r.value), format: rupees },
    { label: 'Gain', values: rows.map((row) => row.r.gain), format: (v) => `${v < 0 ? '−' : ''}${rupees(Math.abs(v))}` },
    { label: 'XIRR', values: rows.map((row) => row.r.xirr) },
  ])}<p class="mf-note">XIRR is the yearly return on the SIP, allowing for each instalment being invested for a different length of time. The grey line is the amount invested${rows.length > 1 && late.length ? ` in ${esc(longest.fund.short)}` : ''}. Exit loads, stamp duty and taxes are ignored.${late.length ? ` ${late.map((row) => esc(row.fund.short)).join(', ')} ${late.length > 1 ? 'have' : 'has'} no NAVs for the start month, so ${late.length > 1 ? 'their SIPs start' : 'its SIP starts'} later and ${late.length > 1 ? 'are' : 'is'} not directly comparable.` : ''}</p>`;
  lineChart($('#mf-sip-chart'), [
    { name: 'Invested', color: '#9aa39c', t: longest.r.t, v: longest.r.paid },
    ...rows.map(({ fund, r }) => ({ name: fund.short, color: fund.color, t: r.t, v: r.v })),
  ], { height: 280, fmtY: (v, exact) => (exact ? rupees(v) : rupeesShort(v)) });
}

// ---------- SWP ----------

// Ten years before the end, or the month after the youngest fund's first NAV if that is later.
function swpFrom(funds) {
  if (state.swp.from) return state.swp.from;
  const end = sipEnd(funds);
  const youngest = Math.max(...funds.map((fund) => fund.t[0]));
  return toMonth(Math.min(end, Math.max(yearsBefore(end, 10), youngest + 31)));
}

// The corpus buys units at the first NAV on or after `day` of the start month. From the next month a
// withdrawal on `day` sells units at the first NAV on or after that date, until `end` or until the units
// run out (the last withdrawal is then whatever was left). The step-up raises the withdrawal every
// 12 withdrawals. With `full`, also returns the day-by-day value and cumulative withdrawals for a chart.
function simulateSwp(fund, { corpus, withdraw, day, stepup }, from, end, full = true) {
  const [year, month] = from.split('-').map(Number);
  const i0 = lowerBound(fund.t, Date.UTC(year, month - 1, day) / DAY_MS);
  if (i0 >= fund.t.length || fund.t[i0] > end) return null;
  let units = corpus / fund.nav[i0], amount = withdraw, ranOut = null;
  const sells = [];
  for (let k = 1; ; k++) {
    const date = Date.UTC(year, month - 1 + k, day) / DAY_MS;
    if (date > end) break;
    if (k > 1 && (k - 1) % 12 === 0) amount *= 1 + stepup;
    const i = lowerBound(fund.t, date);
    if (i >= fund.t.length || fund.t[i] > end) break;
    const sold = Math.min(units, amount / fund.nav[i]);
    units -= sold;
    sells.push({ i, day: fund.t[i], units: sold, amount: sold * fund.nav[i] });
    if (units <= 1e-9) { units = 0; ranOut = fund.t[i]; break; }
  }
  const last = ranOut != null ? sells[sells.length - 1].i : atOrBefore(fund.t, end);
  const finalValue = units * fund.nav[last];
  const withdrawn = sells.reduce((sum, sell) => sum + sell.amount, 0);
  const result = {
    start: fund.t[i0], count: sells.length, withdrawn, value: finalValue, ranOut,
    xirr: xirr([[fund.t[i0], -corpus], ...sells.map((sell) => [sell.day, sell.amount]), [fund.t[last], finalValue]]),
  };
  if (!full) return result;
  const t = [], value = [], out = [];
  let held = corpus / fund.nav[i0], paid = 0, s = 0, low = corpus;
  for (let p = i0; p <= last; p++) {
    while (s < sells.length && sells[s].i <= p) { held -= sells[s].units; paid += sells[s].amount; s++; }
    const v = Math.max(0, held) * fund.nav[p];
    low = Math.min(low, v);
    t.push(fund.t[p]); value.push(v); out.push(paid);
  }
  return { ...result, low: ranOut != null ? 0 : low, t, v: value, out };
}

// The largest monthly withdrawal (with the same step-up) that would not have run out before `end`.
function maxSafeWithdrawal(fund, swp, from, end) {
  let lo = 0, hi = swp.corpus;
  for (let k = 0; k < 40; k++) {
    const mid = (lo + hi) / 2;
    const r = simulateSwp(fund, { ...swp, withdraw: mid }, from, end, false);
    if (r && r.ranOut == null) lo = mid; else hi = mid;
  }
  return lo;
}

// The same SWP started in every month where all chosen funds have `horizon` years of NAVs afterwards.
function swpEveryStart(funds, swp) {
  const first = Math.max(...funds.map((fund) => fund.t[0])) + 31, end = sipEnd(funds);
  const starts = [];
  for (let month = toMonth(first); ; ) {
    const [y, m] = month.split('-').map(Number);
    const stop = Date.UTC(y + swp.horizon, m - 1, swp.day) / DAY_MS;
    if (stop > end) break;
    starts.push([month, stop]);
    month = toMonth(Date.UTC(y, m, 1) / DAY_MS);
  }
  return funds.map((fund) => {
    const runs = starts.map(([month, stop]) => ({ month, r: simulateSwp(fund, swp, month, stop, false) })).filter((run) => run.r);
    if (!runs.length) return null;
    const ends = runs.map((run) => run.r.value / swp.corpus).sort((a, b) => a - b);
    // Lowest value left; among runs that ran out, the one that ran out soonest after starting.
    const daysLasted = (run) => (run.r.ranOut == null ? Infinity : run.r.ranOut - toDay(`${run.month}-01`));
    const worst = runs.reduce((a, b) => (b.r.value < a.r.value || (b.r.value === a.r.value && daysLasted(b) < daysLasted(a)) ? b : a));
    return {
      n: runs.length,
      lasted: runs.filter((run) => run.r.ranOut == null).length / runs.length,
      median: ends[Math.floor((ends.length - 1) / 2)],
      worst: ends[0],
      best: ends[ends.length - 1],
      worstMonth: worst.month,
      worstRanOut: worst.r.ranOut,
    };
  });
}

function swpBlock(funds) {
  const end = sipEnd(funds), from = swpFrom(funds), swp = state.swp;
  const minMonth = toMonth(Math.min(...funds.map((fund) => fund.t[0])));
  const dayOptions = Array.from({ length: 28 }, (_, i) => `<option value="${i + 1}"${i + 1 === swp.day ? ' selected' : ''}>${i + 1}</option>`).join('');
  const stepOptions = [0, 3, 5, 6, 8, 10].map((p) => `<option value="${p}"${p / 100 === swp.stepup ? ' selected' : ''}>${p ? `${p}% a year` : 'None'}</option>`).join('');
  const horizonOptions = [5, 10, 15, 20].map((y) => `<option value="${y}"${y === swp.horizon ? ' selected' : ''}>${y} years</option>`).join('');
  return `<div class="mf-block" id="mf-swp"><h2>How the withdrawals played out</h2><p>A lump sum invested at the start, then a fixed monthly withdrawal sold at the fund's actual NAV. Every fund runs up to ${fmtDate(end)} unless the money runs out first.</p>
    <div class="mf-options mf-sip-options">
      <div class="mf-field"><label for="mf-swp-corpus">Amount invested (₹)</label><input id="mf-swp-corpus" type="number" min="10000" max="1000000000" step="10000" value="${swp.corpus}" inputmode="numeric"></div>
      <div class="mf-field"><label for="mf-swp-withdraw">Monthly withdrawal (₹)</label><input id="mf-swp-withdraw" type="number" min="100" max="100000000" step="500" value="${swp.withdraw}" inputmode="numeric"></div>
      <div class="mf-field"><label for="mf-swp-from">Start month</label><input id="mf-swp-from" type="month" min="${minMonth}" max="${toMonth(end)}" value="${from}"></div>
      <div class="mf-field"><label for="mf-swp-day">Withdrawal date</label><select id="mf-swp-day">${dayOptions}</select></div>
      <div class="mf-field"><label for="mf-swp-stepup">Yearly increase</label><select id="mf-swp-stepup">${stepOptions}</select></div>
    </div><div id="mf-swp-out"></div></div>
    <div class="mf-block"><h2>Would it have lasted from any start month?</h2><p>The same SWP started in every month the chosen funds have data for, each run for a fixed number of years. A bad few years right after you start hurt far more than the same years later on; this shows how much the start date mattered.</p>
    <div class="mf-options mf-sip-options"><div class="mf-field"><label for="mf-swp-horizon">Run each SWP for</label><select id="mf-swp-horizon">${horizonOptions}</select></div></div>
    <div id="mf-swp-every"></div></div>`;
}

function swpInvalid(swp) {
  if (!(swp.corpus >= 10000 && swp.corpus <= 1e9)) return 'Enter an amount invested between ₹10,000 and ₹1,00,00,00,000.';
  if (!(swp.withdraw >= 100 && swp.withdraw <= swp.corpus)) return 'Enter a monthly withdrawal of at least ₹100 and no more than the amount invested.';
  return '';
}

function renderSwp() {
  const out = $('#mf-swp-out');
  if (!out) return;
  const funds = state.funds, swp = state.swp;
  const end = sipEnd(funds), from = swpFrom(funds);
  const invalid = swpInvalid(swp);
  if (invalid) { out.innerHTML = `<p class="mf-empty">${invalid}</p>`; $('#mf-swp-every').innerHTML = ''; return; }
  if (!/^\d{4}-\d{2}$/.test(from) || from >= toMonth(end)) { out.innerHTML = `<p class="mf-empty">Pick a start month before ${fmtDate(end)}.</p>`; renderSwpEvery(); return; }
  const rows = funds.map((fund) => ({ fund, r: simulateSwp(fund, swp, from, end) })).filter((row) => row.r);
  if (!rows.length) { out.innerHTML = '<p class="mf-empty">None of these funds has NAVs between the start month and the latest date.</p>'; renderSwpEvery(); return; }
  rows.forEach((row) => { row.safe = maxSafeWithdrawal(row.fund, swp, from, end); });
  const late = rows.filter((row) => toMonth(row.r.start) > from);
  const yearlyRate = (swp.withdraw * 12) / swp.corpus;
  out.innerHTML = `<div class="mf-chart" id="mf-swp-chart"></div>${fundTable(rows.map((row) => row.fund), [
    { label: 'Invested on', values: rows.map((row) => row.r.start), markNegative: false, highlight: false, format: fmtDate },
    { label: 'Withdrawals', values: rows.map((row) => row.r.count), markNegative: false, highlight: false, format: (v) => v.toLocaleString('en-IN') },
    { label: 'Total withdrawn', values: rows.map((row) => row.r.withdrawn), format: rupees },
    { label: 'Value left', values: rows.map((row) => row.r.value), format: rupees },
    { label: 'Ran out', values: rows.map((row) => row.r.ranOut), markNegative: false, highlight: false, format: (v) => (v == null ? 'No' : fmtDate(v)) },
    { label: 'Lowest value', values: rows.map((row) => row.r.low), format: rupees },
    { label: 'XIRR', values: rows.map((row) => row.r.xirr) },
    { label: 'Most it could pay', values: rows.map((row) => row.safe), format: (v) => `${rupees(v)}/mo` },
  ])}<p class="mf-note">You are withdrawing ${pct(yearlyRate, 1)} of the amount invested each year${swp.stepup ? `, rising ${pct(swp.stepup, 0)} a year` : ''}. "Most it could pay" is the largest starting monthly withdrawal${swp.stepup ? ' (with the same yearly increase)' : ''} that would not have run out before ${fmtDate(end)}. XIRR counts the money invested, every withdrawal and the value left. Exit loads, stamp duty and taxes on each redemption are ignored.${late.length ? ` ${late.map((row) => esc(row.fund.short)).join(', ')} ${late.length > 1 ? 'have' : 'has'} no NAVs for the start month, so ${late.length > 1 ? 'they start' : 'it starts'} later and ${late.length > 1 ? 'are' : 'is'} not directly comparable.` : ''}</p>`;
  const longest = rows.reduce((a, b) => (b.r.t.length > a.r.t.length ? b : a));
  lineChart($('#mf-swp-chart'), [
    { name: 'Withdrawn so far', color: '#9aa39c', t: longest.r.t, v: longest.r.out },
    ...rows.map(({ fund, r }) => ({ name: fund.short, color: fund.color, t: r.t, v: r.v })),
  ], { height: 280, fmtY: (v, exact) => (exact ? rupees(v) : rupeesShort(v)), zero: true });
  renderSwpEvery();
}

function renderSwpEvery() {
  const el = $('#mf-swp-every');
  if (!el) return;
  const funds = state.funds, swp = state.swp;
  if (swpInvalid(swp)) { el.innerHTML = ''; return; }
  const stats = swpEveryStart(funds, swp);
  const rows = funds.map((fund, i) => ({ fund, s: stats[i] })).filter((row) => row.s);
  if (!rows.length) { el.innerHTML = `<p class="mf-empty">These funds do not have ${swp.horizon} years of NAVs in common. Pick a shorter period.</p>`; return; }
  const multiple = (v) => `${rupeesShort(v * swp.corpus)} <small>(${v.toFixed(2)}×)</small>`;
  el.innerHTML = `${fundTable(rows.map((row) => row.fund), [
    { label: 'Start months', values: rows.map((row) => row.s.n), markNegative: false, highlight: false, format: (v) => v.toLocaleString('en-IN') },
    { label: 'Lasted', values: rows.map((row) => row.s.lasted), format: (v) => pct(v, 0) },
    { label: 'Median left', values: rows.map((row) => row.s.median), format: multiple },
    { label: 'Worst left', values: rows.map((row) => row.s.worst), format: multiple },
    { label: 'Best left', values: rows.map((row) => row.s.best), format: multiple },
    { label: 'Worst start', values: rows.map((row) => row.s.worstMonth), markNegative: false, highlight: false, format: (m) => new Date(`${m}-01T00:00:00Z`).toLocaleDateString('en-IN', { month: 'short', year: 'numeric', timeZone: 'UTC' }) },
  ])}<p class="mf-note">Each start month runs the SWP above (same amount, withdrawal and yearly increase) for ${swp.horizon} years. "Lasted" is the share of start months where the money did not run out. "Left" is the value remaining after ${swp.horizon} years, also shown as a multiple of the amount invested.${rows.some((row) => row.s.worstRanOut != null) ? ' Where the worst start ran out, "Worst left" is zero.' : ''}</p>`;
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
  if (SIP_PAGE) {
    $('#mf-out').innerHTML = sipBlock(funds);
    renderSip();
    return;
  }
  if (SWP_PAGE) {
    $('#mf-out').innerHTML = swpBlock(funds);
    renderSwp();
    return;
  }

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

  const codes = funds.map((fund) => fund.code).join(',');
  html += `<div class="mf-block"><h2>SIP and SWP calculators</h2><p>See what a monthly SIP in these funds would have become, or how long a lump sum would have lasted with a fixed monthly withdrawal, on their actual NAVs.</p><a class="text-link" href="mf-sip.html?funds=${codes}">Open the SIP calculator <b>↗</b></a> &nbsp; <a class="text-link" href="mf-swp.html?funds=${codes}">Open the SWP calculator <b>↗</b></a></div>`;

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
addEventListener('resize', () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => (SIP_PAGE ? renderSip() : SWP_PAGE ? renderSwp() : lastCharts && drawCharts(...lastCharts)), 150); });

// ---------- URL state (so a comparison can be shared) ----------

function syncUrl() {
  const params = new URLSearchParams();
  if (state.funds.length) params.set('funds', state.funds.map((fund) => fund.code).join(','));
  if (SWP_PAGE) {
    const swp = state.swp;
    if (swp.corpus !== SWP_DEFAULT.corpus) params.set('amount', swp.corpus);
    if (swp.withdraw !== SWP_DEFAULT.withdraw) params.set('swp', swp.withdraw);
    if (swp.from) params.set('swpfrom', swp.from);
    if (swp.day !== SWP_DEFAULT.day) params.set('swpday', swp.day);
    if (swp.stepup) params.set('stepup', Math.round(swp.stepup * 100));
    if (swp.horizon !== SWP_DEFAULT.horizon) params.set('horizon', swp.horizon);
    history.replaceState(null, '', `${location.pathname}?${params}`);
    return;
  }
  if (!SIP_PAGE) {
    params.set('years', state.years);
    if (state.period !== 'common') params.set('period', state.period);
    history.replaceState(null, '', `${location.pathname}?${params}`);
    return;
  }
  const sip = state.sip;
  if (sip.amount !== SIP_DEFAULT.amount) params.set('sip', sip.amount);
  if (sip.from) params.set('sipfrom', sip.from);
  if (sip.day !== SIP_DEFAULT.day) params.set('sipday', sip.day);
  if (sip.stepup) params.set('stepup', Math.round(sip.stepup * 100));
  history.replaceState(null, '', `${location.pathname}?${params}`);
}

async function loadFromUrl() {
  const params = new URLSearchParams(location.search);
  const years = +params.get('years');
  const COMPARE_PAGE = !SIP_PAGE && !SWP_PAGE;
  if (COMPARE_PAGE && [1, 2, 3, 5, 7, 10].includes(years)) { state.years = years; $('#mf-years').value = String(years); }
  if (COMPARE_PAGE && params.get('period') === 'full') { state.period = 'full'; $('#mf-period').value = 'full'; }
  const stepup = +params.get('stepup');
  if (SIP_PAGE) {
    const sipAmount = +params.get('sip'), sipDay = +params.get('sipday');
    if (sipAmount >= 100 && sipAmount <= 10000000) state.sip.amount = sipAmount;
    if (/^\d{4}-\d{2}$/.test(params.get('sipfrom') || '')) state.sip.from = params.get('sipfrom');
    if (Number.isInteger(sipDay) && sipDay >= 1 && sipDay <= 28) state.sip.day = sipDay;
    if ([5, 10, 15, 20].includes(stepup)) state.sip.stepup = stepup / 100;
  }
  if (SWP_PAGE) {
    const swp = state.swp, corpus = +params.get('amount'), withdraw = +params.get('swp'), day = +params.get('swpday'), horizon = +params.get('horizon');
    if (corpus >= 10000 && corpus <= 1e9) swp.corpus = corpus;
    if (withdraw >= 100 && withdraw <= swp.corpus) swp.withdraw = withdraw;
    if (/^\d{4}-\d{2}$/.test(params.get('swpfrom') || '')) swp.from = params.get('swpfrom');
    if (Number.isInteger(day) && day >= 1 && day <= 28) swp.day = day;
    if ([3, 5, 6, 8, 10].includes(stepup)) swp.stepup = stepup / 100;
    if ([5, 10, 15, 20].includes(horizon)) swp.horizon = horizon;
  }
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

$('#mf-years')?.addEventListener('change', (event) => { state.years = +event.target.value; render(); });
$('#mf-period')?.addEventListener('change', (event) => { state.period = event.target.value; render(); });
$('#mf-direct').addEventListener('change', (event) => { state.directOnly = event.target.checked; runSearch(); });
$('#mf-bench').addEventListener('click', () => addFund(BENCHMARK_CODE));
$('#mf-chips').addEventListener('click', (event) => { const button = event.target.closest('[data-remove]'); if (button) removeFund(button.dataset.remove); });
// SIP inputs live inside #mf-out; changing one redraws only the SIP results, so the input keeps focus.
$('#mf-out').addEventListener('input', (event) => {
  const value = event.target.value;
  if (SWP_PAGE) {
    const swp = state.swp;
    if (event.target.id === 'mf-swp-corpus') swp.corpus = +value;
    else if (event.target.id === 'mf-swp-withdraw') swp.withdraw = +value;
    else if (event.target.id === 'mf-swp-from') swp.from = /^\d{4}-\d{2}$/.test(value) ? value : null;
    else if (event.target.id === 'mf-swp-day') swp.day = +value;
    else if (event.target.id === 'mf-swp-stepup') swp.stepup = +value / 100;
    else if (event.target.id === 'mf-swp-horizon') { swp.horizon = +value; renderSwpEvery(); syncUrl(); return; }
    else return;
    renderSwp();
    syncUrl();
    return;
  }
  const sip = state.sip;
  if (event.target.id === 'mf-sip-amount') sip.amount = +value;
  else if (event.target.id === 'mf-sip-from') sip.from = /^\d{4}-\d{2}$/.test(value) ? value : null;
  else if (event.target.id === 'mf-sip-day') sip.day = +value;
  else if (event.target.id === 'mf-sip-stepup') sip.stepup = +value / 100;
  else return;
  renderSip();
  syncUrl();
});
$('#mf-out').addEventListener('click', async (event) => {
  const button = event.target.closest('[data-preset]');
  if (!button) return;
  setStatus('Loading NAV history…');
  for (const code of button.dataset.preset.split(',')) await addFund(code, { quiet: true });
  if (!$('#mf-status').classList.contains('error')) setStatus('');
});

loadFromUrl();
