// Loan EMI and prepayment calculator (loan-prepayment.html). Everything is worked out here in the browser.

const $ = (selector) => document.querySelector(selector);
const esc = (text) => String(text).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const rupees = (value) => `₹${Math.round(value).toLocaleString('en-IN')}`;
const rupeesShort = (value) => (value >= 1e7 ? `₹${+(value / 1e7).toFixed(2)}Cr` : value >= 1e5 ? `₹${+(value / 1e5).toFixed(1)}L` : value >= 1000 ? `₹${Math.round(value / 1000)}k` : `₹${Math.round(value)}`);
const pct = (value, digits = 1) => (value == null || !Number.isFinite(value) ? '—' : `${(value * 100).toFixed(digits)}%`);
const MAX_MONTHS = 600;

const FIELDS = {
  principal: { id: 'loan-amount', def: 5000000, min: 10000, max: 1e10 },
  rate: { id: 'loan-rate', def: 8.5, min: 0.1, max: 30 },
  years: { id: 'loan-years', def: 20, min: 1, max: 40 },
  start: { id: 'loan-start', def: new Date().toISOString().slice(0, 7) },
  monthly: { id: 'pre-monthly', def: 0, min: 0, max: 1e9 },
  yearly: { id: 'pre-yearly', def: 100000, min: 0, max: 1e10 },
  lump: { id: 'pre-lump', def: 0, min: 0, max: 1e10 },
  lumpMonth: { id: 'pre-lump-month', def: 12, min: 1, max: MAX_MONTHS },
  stepup: { id: 'pre-stepup', def: 0, min: 0, max: 20 },
  mode: { id: 'pre-mode', def: 'tenure' },
  invest: { id: 'inv-rate', def: 10, min: 0, max: 30 },
};

// Monthly EMI that repays `principal` over `months` at monthly rate `r`.
const emiFor = (principal, r, months) => (r ? (principal * r * (1 + r) ** months) / ((1 + r) ** months - 1) : principal / months);

// The prepayments planned for month m (1-based): extra every month, a yearly amount every 12th month, a one-off.
const planned = (p, m) => p.monthly + (m % 12 === 0 ? p.yearly : 0) + (m === p.lumpMonth ? p.lump : 0);

// Month-by-month schedule. Prepayments go straight to principal after that month's EMI. In 'tenure' mode
// the EMI stays the same (rising by the step-up every 12 months) and the loan ends early; in 'emi' mode the
// EMI is recalculated over the remaining original tenure after every prepayment.
function amortise(p, withPrepay) {
  const r = p.rate / 1200, n = p.years * 12;
  const baseEmi = emiFor(p.principal, r, n);
  let emi = baseEmi, balance = p.principal;
  const rows = [];
  for (let m = 1; m <= MAX_MONTHS && balance > 0.005; m++) {
    if (withPrepay && p.mode === 'tenure' && m > 1 && (m - 1) % 12 === 0) emi *= 1 + p.stepup;
    const interest = balance * r;
    const pay = Math.min(emi, balance + interest);
    balance -= pay - interest;
    const prepay = withPrepay ? Math.min(balance, planned(p, m)) : 0;
    balance -= prepay;
    if (balance < 0.005) balance = 0;
    rows.push({ m, emi: pay, interest, principal: pay - interest, prepay, balance });
    if (withPrepay && p.mode === 'emi' && prepay > 0 && balance > 0) emi = emiFor(balance, r, n - m);
  }
  const interest = rows.reduce((sum, row) => sum + row.interest, 0);
  const prepaid = rows.reduce((sum, row) => sum + row.prepay, 0);
  return { rows, baseEmi, months: rows.length, interest, prepaid, paid: p.principal + interest };
}

// Both plans spend the same each month until the original loan would end: the original EMI plus the planned
// prepayments (and step-up). "Invest" pays the original loan and invests the prepayments; "prepay" pays them
// into the loan and invests whatever is left of that budget once the EMI falls or the loan closes.
// Returns the wealth each has built by the original end date, at `yearly` return.
function prepayVsInvest(p, base, pre, yearly) {
  const ri = (1 + yearly) ** (1 / 12) - 1, n = base.months;
  let invest = 0, prepay = 0;
  for (let m = 1; m <= n; m++) {
    const stepExtra = p.mode === 'tenure' ? base.baseEmi * ((1 + p.stepup) ** Math.floor((m - 1) / 12) - 1) : 0;
    const extra = planned(p, m) + stepExtra;
    const budget = base.rows[m - 1].emi + extra;
    const row = pre.rows[m - 1];
    const spent = row ? row.emi + row.prepay : 0;
    const grow = (1 + ri) ** (n - m);
    invest += extra * grow;
    prepay += Math.max(0, budget - spent) * grow;
  }
  return { invest, prepay };
}

// The yearly investment return at which both plans end with the same wealth.
function breakEven(p, base, pre) {
  let lo = 0, hi = 0.5;
  const gap = (rate) => { const w = prepayVsInvest(p, base, pre, rate); return w.invest - w.prepay; };
  if (gap(lo) > 0 || gap(hi) < 0) return null;
  for (let k = 0; k < 50; k++) { const mid = (lo + hi) / 2; if (gap(mid) < 0) lo = mid; else hi = mid; }
  return (lo + hi) / 2;
}

// ---------- dates ----------

function monthDate(start, m) {
  const [y, mo] = start.split('-').map(Number);
  return new Date(Date.UTC(y, mo - 2 + m, 1));
}
const monthLabel = (start, m) => monthDate(start, m).toLocaleDateString('en-IN', { month: 'short', year: 'numeric', timeZone: 'UTC' });
const duration = (months) => {
  const y = Math.floor(months / 12), mo = months % 12;
  return [y ? `${y} yr${y > 1 ? 's' : ''}` : '', mo ? `${mo} mo` : ''].filter(Boolean).join(' ') || '0 mo';
};

// ---------- chart ----------

function niceTicks(lo, hi, count) {
  if (lo === hi) hi = lo + 1;
  const raw = (hi - lo) / count, mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((k) => k * mag).find((s) => s >= raw);
  const ticks = [];
  for (let v = Math.floor(lo / step) * step; v <= Math.ceil(hi / step) * step + step / 2; v += step) ticks.push(+v.toPrecision(12));
  return ticks;
}

// Outstanding balance by month for each series ({ name, color, v: balances after month 1..n }), starting at the loan amount.
function balanceChart(el, series, principal, start) {
  const W = Math.max(320, el.clientWidth), H = 280, m = { l: 58, r: 14, t: 10, b: 28 };
  const n = Math.max(...series.map((s) => s.v.length));
  const ticks = niceTicks(0, principal, 5), y1 = ticks[ticks.length - 1];
  const X = (i) => m.l + (i / n) * (W - m.l - m.r);
  const Y = (v) => H - m.b - (v / y1) * (H - m.t - m.b);
  const years = n / 12, yearStep = Math.max(1, Math.ceil(years / Math.max(2, Math.floor((W - m.l) / 60))));
  let svg = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Outstanding loan balance over time">`;
  for (const tick of ticks) svg += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(tick)}" y2="${Y(tick)}" stroke="${tick === 0 ? '#17201b' : '#d9ddd5'}"/><text x="${m.l - 8}" y="${Y(tick) + 4}" text-anchor="end">${rupeesShort(tick)}</text>`;
  for (let y = 0; y <= years; y += yearStep) svg += `<line x1="${X(y * 12)}" x2="${X(y * 12)}" y1="${H - m.b}" y2="${H - m.b + 4}" stroke="#667069"/><text x="${X(y * 12)}" y="${H - 8}" text-anchor="middle">${y ? `Yr ${y}` : 'Start'}</text>`;
  for (const s of series) {
    const d = [principal, ...s.v].map((v, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join('');
    svg += `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="1.8" stroke-linejoin="round"/>`;
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
    const i = Math.round(((px - m.l) / (W - m.l - m.r)) * n);
    const rows = series.map((s, k) => {
      const v = i === 0 ? principal : i > s.v.length ? 0 : s.v[i - 1];
      dots[k].setAttribute('cx', X(i)); dots[k].setAttribute('cy', Y(v)); dots[k].setAttribute('visibility', 'visible');
      return `<div><span><i style="background:${s.color}"></i>${esc(s.name)}</span><strong>${rupees(v)}</strong></div>`;
    }).join('');
    cursor.setAttribute('x1', X(i)); cursor.setAttribute('x2', X(i)); cursor.setAttribute('visibility', 'visible');
    tip.innerHTML = `<b>${i ? `After ${duration(i)} · ${monthLabel(start, i)}` : 'Start'}</b>${rows}`;
    tip.style.display = 'block';
    tip.style.left = `${Math.max(0, Math.min((X(i) / W) * box.width + 14, box.width - tip.offsetWidth))}px`;
    tip.style.top = `${Math.max(0, event.clientY - box.top - tip.offsetHeight - 12) + 12}px`;
  };
  svgEl.addEventListener('mousemove', move);
  svgEl.addEventListener('touchmove', (event) => move(event.touches[0]), { passive: true });
  svgEl.addEventListener('mouseleave', hide);
}

// ---------- rendering ----------

function readInputs() {
  const p = {};
  for (const [key, field] of Object.entries(FIELDS)) {
    const value = $(`#${field.id}`).value;
    p[key] = key === 'start' || key === 'mode' ? value : +value;
  }
  p.stepup /= 100;
  p.invest /= 100;
  return p;
}

function invalid(p) {
  for (const [key, field] of Object.entries(FIELDS)) {
    if (field.min == null) continue;
    const value = key === 'stepup' || key === 'invest' ? p[key] * 100 : p[key];
    if (!(value >= field.min && value <= field.max)) {
      return `Check "${$(`label[for="${field.id}"]`).textContent}".`;
    }
  }
  if (!/^\d{4}-\d{2}$/.test(p.start)) return 'Pick the month of the first EMI.';
  return '';
}

function yearTable(p, plan) {
  const years = [];
  plan.rows.forEach((row) => {
    const y = Math.floor((row.m - 1) / 12);
    years[y] ||= { interest: 0, principal: 0, prepay: 0, emi: 0, balance: 0, from: row.m, to: row.m };
    const acc = years[y];
    acc.interest += row.interest; acc.principal += row.principal; acc.prepay += row.prepay; acc.emi += row.emi; acc.balance = row.balance; acc.to = row.m;
  });
  const body = years.map((y, i) => `<tr><td>Year ${i + 1} <small>${monthLabel(p.start, y.from)}–${monthLabel(p.start, y.to)}</small></td><td>${rupees(y.emi)}</td><td>${rupees(y.principal)}</td><td>${rupees(y.interest)}</td><td>${y.prepay ? rupees(y.prepay) : '—'}</td><td>${rupees(y.balance)}</td></tr>`).join('');
  return `<div class="mf-tablewrap"><table class="mf-table"><thead><tr><th>Year</th><th>EMIs paid</th><th>Principal</th><th>Interest</th><th>Prepaid</th><th>Balance left</th></tr></thead><tbody>${body}</tbody></table></div>`;
}

function render() {
  const p = readInputs();
  $('#pre-stepup').disabled = p.mode === 'emi';
  $('#pre-stepup-note').textContent = p.mode === 'emi' ? 'Only with "Shorter tenure"' : '';
  if (p.mode === 'emi') p.stepup = 0;
  syncUrl(p);
  const problem = invalid(p);
  if (problem) { $('#loan-out').innerHTML = `<p class="mf-empty">${esc(problem)}</p>`; return; }

  const base = amortise(p, false), pre = amortise(p, true);
  const anyPrepay = pre.prepaid > 0 || p.stepup > 0;
  const saved = base.interest - pre.interest;
  const cmp = (label, a, b, fmt, better = 'lower') => {
    const cls = a === b ? '' : (better === 'lower' ? b < a : b > a) ? ' class="best"' : '';
    return `<tr><td>${label}</td><td>${fmt(a)}</td><td${cls}>${fmt(b)}</td></tr>`;
  };
  const endLabel = (plan) => `${duration(plan.months)} <small>(last EMI ${monthLabel(p.start, plan.months)})</small>`;
  // In 'emi' mode the EMI falls after each prepayment; show where it ends (the very last EMI is often part of one).
  const emiLabel = p.mode === 'emi' && anyPrepay ? `${rupees(base.baseEmi)} at first, falling to ${rupees(pre.rows[Math.max(0, pre.months - 2)].emi)}` : p.stepup ? `${rupees(base.baseEmi)}, +${pct(p.stepup, 0)} a year` : rupees(base.baseEmi);

  let html = `<div class="loan-kpis">
      <div><span>Monthly EMI</span><strong>${rupees(base.baseEmi)}</strong></div>
      <div><span>Interest without prepaying</span><strong>${rupees(base.interest)}</strong></div>
      <div><span>Interest saved</span><strong class="${saved > 0 ? 'ok' : ''}">${anyPrepay ? rupees(saved) : '—'}</strong></div>
      <div><span>${p.mode === 'emi' ? 'Tenure' : 'Loan closes'}</span><strong>${anyPrepay && p.mode === 'tenure' ? `${duration(base.months - pre.months)} early` : duration(pre.months)}</strong></div>
    </div>`;

  html += `<div class="mf-block"><h2>With and without prepaying</h2><p>Loan of ${rupees(p.principal)} at ${p.rate}% for ${duration(p.years * 12)}, first EMI in ${monthLabel(p.start, 1)}.</p>
    <div class="mf-tablewrap"><table class="mf-table loan-cmp"><thead><tr><th></th><th>No prepayment</th><th>With prepayment</th></tr></thead><tbody>
      <tr><td>EMI</td><td>${rupees(base.baseEmi)}</td><td>${emiLabel}</td></tr>
      <tr><td>Loan runs for</td><td>${endLabel(base)}</td><td${pre.months < base.months ? ' class="best"' : ''}>${endLabel(pre)}</td></tr>
      ${cmp('Total interest', base.interest, pre.interest, rupees)}
      <tr><td>Prepaid in all</td><td>—</td><td>${rupees(pre.prepaid)}</td></tr>
      ${cmp('Total paid (principal + interest)', base.paid, pre.paid, rupees)}
      ${cmp('Interest as a share of the loan', base.interest / p.principal, pre.interest / p.principal, (v) => pct(v, 0))}
    </tbody></table></div>
    <div class="mf-chart" id="loan-chart"></div>
    <p class="mf-note">Grey is the loan without prepaying, green with. Prepayments are applied to principal right after that month's EMI. Most banks charge no prepayment penalty on floating-rate home loans taken by individuals; check your loan terms for fixed-rate and other loans.</p></div>`;

  if (anyPrepay) {
    const wealth = prepayVsInvest(p, base, pre, p.invest);
    const even = breakEven(p, base, pre);
    const winner = wealth.prepay >= wealth.invest ? 'Prepaying' : 'Investing';
    html += `<div class="mf-block"><h2>Prepay or invest the money?</h2><p>Both plans spend exactly the same each month until ${monthLabel(p.start, base.months)}, when the original loan would end. One puts the extra money into the loan and, once the loan closes${p.mode === 'emi' ? ' or the EMI falls' : ''}, invests what it no longer has to pay. The other keeps the original loan and invests the extra money at ${pct(p.invest, 1)} a year after tax.</p>
      <div class="loan-kpis">
        <div><span>Prepay, then invest</span><strong>${rupees(wealth.prepay)}</strong></div>
        <div><span>Keep the loan, invest</span><strong>${rupees(wealth.invest)}</strong></div>
        <div><span>${winner} ends ahead by</span><strong class="ok">${rupees(Math.abs(wealth.prepay - wealth.invest))}</strong></div>
        <div><span>Break-even return</span><strong>${even == null ? '—' : pct(even, 2)}</strong></div>
      </div>
      <p class="mf-note">Wealth is the value, in ${monthLabel(p.start, base.months)}, of everything invested along the way; both plans are debt-free by then. Investing comes out ahead only if it earns more than the break-even return after tax, which is close to the loan rate. A prepayment's return is certain; an investment's is not. Tax breaks on home loans (interest under Section 24(b) and principal under Section 80C, old regime only) lower the loan's real cost and tilt the answer toward investing; they are not included here.</p></div>`;
  }

  html += `<div class="mf-block"><h2>Year-by-year schedule</h2><p>${anyPrepay ? 'With prepayment.' : 'Without prepayment.'} Year 1 is the first 12 EMIs.</p>${yearTable(p, pre)}</div>`;
  $('#loan-out').innerHTML = html;
  balanceChart($('#loan-chart'), [
    { name: 'No prepayment', color: '#9aa39c', v: base.rows.map((row) => row.balance) },
    ...(anyPrepay ? [{ name: 'With prepayment', color: '#2f6b46', v: pre.rows.map((row) => row.balance) }] : []),
  ], p.principal, p.start);
}

// ---------- URL state ----------

const URL_KEYS = { principal: 'amount', rate: 'rate', years: 'years', start: 'start', monthly: 'monthly', yearly: 'yearly', lump: 'lump', lumpMonth: 'lumpmonth', stepup: 'stepup', mode: 'mode', invest: 'invest' };

function syncUrl(p) {
  const params = new URLSearchParams();
  for (const [key, name] of Object.entries(URL_KEYS)) {
    let value = p[key];
    if (key === 'stepup' || key === 'invest') value = +(value * 100).toFixed(2);
    if (key === 'start' ? value !== FIELDS.start.def : value !== FIELDS[key].def) params.set(name, value);
  }
  history.replaceState(null, '', `${location.pathname}${params.size ? `?${params}` : ''}`);
}

function loadFromUrl() {
  const params = new URLSearchParams(location.search);
  for (const [key, field] of Object.entries(FIELDS)) {
    const el = $(`#${field.id}`);
    const raw = params.get(URL_KEYS[key]);
    let value = field.def;
    if (raw != null) {
      if (key === 'mode') value = raw === 'emi' ? 'emi' : 'tenure';
      else if (key === 'start') value = /^\d{4}-\d{2}$/.test(raw) ? raw : field.def;
      else if (+raw >= field.min && +raw <= field.max) value = +raw;
    }
    el.value = value;
  }
}

loadFromUrl();
render();
document.querySelector('#loan-form').addEventListener('input', render);
document.querySelector('#loan-form').addEventListener('submit', (event) => event.preventDefault());
let resizeTimer;
addEventListener('resize', () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(render, 150); });
