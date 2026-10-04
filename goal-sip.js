// Page logic for goal-sip-calculator.html: the step-by-step questionnaire, the goals
// editor and the live report. Everything stays in this page's memory; nothing is
// stored or sent (NFR-02). Maths lives in goal-sip-calc.js, settings in goal-sip-config.js.
(function () {
  const C = window.GOAL_SIP_CONFIG;
  const K = window.GoalSipCalc;
  const T = C.strings[C.lang];
  const Q = C.questions;
  const STEP_NUMBERS = Q.length;
  const STEP_GOALS = Q.length + 1;
  const STEP_RESULTS = Q.length + 2;
  const stage = document.getElementById('gs-stage');

  const state = {
    step: 0,
    answers: {},
    numbers: { retireYears: '', surplus: '', mf: '', equity: '', debt: '', gold: '' },
    goals: [newGoal('education')],
    assumptions: { equity: C.returns.equity, debt: C.returns.debt, gold: C.returns.gold, post: C.postRetirementReturn, stepUp: C.defaultStepUp },
    tracked: {},
  };

  function newGoal(type) {
    const t = C.goalTypes.find((g) => g.id === type);
    return { type, cost: '', years: '', priority: 'high', saved: '', inflation: t.inflation, monthlyExpense: '', retirementYears: C.defaultRetirementYears };
  }

  // ---------- small helpers ----------
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmt = (s, vars) => s.replace(/\{(\w+)\}/g, (m, k) => vars[k]);
  const inr = (v) => '₹' + Math.round(v).toLocaleString('en-IN');
  const pct = (v) => (Math.round(v * 100) / 100).toLocaleString('en-IN') + '%';
  const num = (v) => (v === '' || v === null || v === undefined ? NaN : Number(v));
  const isInt = (v, lo, hi) => Number.isInteger(num(v)) && num(v) >= lo && num(v) <= hi;
  const inRange = (v, lo, hi) => Number.isFinite(num(v)) && num(v) >= lo && num(v) <= hi;
  const blankOrMin0 = (v) => v === '' || inRange(v, 0, 1e12);

  // Page events only, never answer values (AN-01). Uses the site's analytics if present.
  function track(name) {
    if (state.tracked[name] && name !== 'cta_clicked') return;
    state.tracked[name] = true;
    try {
      if (typeof window.gtag === 'function') window.gtag('event', 'goal_sip_' + name);
      else if (Array.isArray(window.dataLayer)) window.dataLayer.push({ event: 'goal_sip_' + name });
    } catch (e) { /* analytics must never break the tool */ }
  }

  function complianceText() {
    const arn = C.arn ? C.arn : '[ARN to be added]';
    return `The author of Let Money Earn, ${C.distributorName}, is an ${C.distributorLine} (${arn}), ${C.associatedWith}. This is not investment advice. The risk profile and SIP figures are indicative, use illustrative assumptions and do not name or recommend any scheme; please review them with a SEBI-registered Investment Adviser for personalised advice. Mutual Fund investments are subject to market risks, read all scheme related documents carefully.`;
  }

  // ---------- validation ----------
  function numbersError(n) {
    if (!isInt(n.retireYears, 0, 45)) return 'Enter years to retirement as a whole number from 0 to 45.';
    if (!inRange(n.surplus, 0, 1e10)) return 'Enter the amount you can invest each month (0 or more).';
    if (![n.mf, n.equity, n.debt, n.gold].every(blankOrMin0)) return 'Existing holdings must be 0 or more, or left blank.';
    return null;
  }

  function goalError(g) {
    if (g.type === 'retirement') {
      if (!isInt(state.numbers.retireYears, 1, 45)) return T.notes.retirementNeedsYears;
      if (!inRange(g.monthlyExpense, 1, 1e9)) return 'Enter your monthly expenses in today’s money.';
      if (!isInt(g.retirementYears, 1, 50)) return 'Years in retirement must be a whole number from 1 to 50.';
    } else {
      if (!inRange(g.cost, 1, 1e12)) return 'Enter what this goal costs in today’s money.';
      if (!isInt(g.years, 1, 40)) return 'Years away must be a whole number from 1 to 40.';
    }
    if (!blankOrMin0(g.saved)) return 'Amount already saved must be 0 or more.';
    if (!inRange(g.inflation, 0, 20)) return 'Inflation must be between 0% and 20%.';
    return null;
  }

  // ---------- step rendering ----------
  function setProgress() {
    const total = STEP_RESULTS;
    const shown = Math.min(state.step + 1, total);
    document.getElementById('gs-progress').hidden = state.step === STEP_RESULTS;
    document.getElementById('gs-progress-text').textContent = `Step ${shown} of ${total}`;
    const bar = document.getElementById('gs-progress-bar');
    bar.style.width = (100 * state.step / total) + '%';
    bar.parentElement.setAttribute('aria-valuenow', String(Math.round(100 * state.step / total)));
  }

  function navButtons(nextLabel, nextDisabled) {
    return `<div class="gs-nav">${state.step > 0 ? '<button type="button" class="gs-btn ghost" data-act="back">Back</button>' : ''}<button type="submit" class="gs-btn" ${nextDisabled ? 'disabled' : ''}>${nextLabel}</button></div>`;
  }

  function questionStep(i) {
    const q = Q[i];
    const text = T.questions[q.id];
    const part = q.part === 'capacity' ? 'Your situation' : 'Your attitude to risk';
    const options = text.options.map((label, idx) => `<label class="gs-option"><input type="radio" name="answer" value="${idx}" ${state.answers[q.id] === idx ? 'checked' : ''}>${esc(label)}</label>`).join('');
    return `<form class="gs-step" id="gs-form" novalidate><fieldset><span class="gs-part">Question ${i + 1} of ${Q.length} · ${part}</span><legend tabindex="-1">${esc(text.q)}</legend><div class="gs-options">${options}</div></fieldset>${navButtons('Next', state.answers[q.id] === undefined)}</form>`;
  }

  function field(id, label, value, attrs, hint) {
    return `<div class="gs-field"><label for="${id}">${label}</label><input id="${id}" inputmode="decimal" value="${esc(value)}" ${attrs}>${hint ? `<p class="gs-hint">${hint}</p>` : ''}</div>`;
  }

  function numbersFields(prefix) {
    const n = state.numbers;
    const at = (key) => `type="number" min="0" data-num="${key}"`;
    return `<div class="gs-fields">${field(prefix + 'retire', 'Years to planned retirement', n.retireYears, at('retireYears') + ' max="45" step="1" required')}${field(prefix + 'surplus', 'Monthly amount you can invest (₹)', n.surplus, at('surplus') + ' required')}</div>
      <p class="gs-sub">Existing investments <span class="gs-hint">(optional)</span></p>
      <div class="gs-fields">${field(prefix + 'mf', 'Mutual funds (₹)', n.mf, at('mf'))}${field(prefix + 'eq', 'Stocks (₹)', n.equity, at('equity'))}${field(prefix + 'debt', 'FDs, bonds, PPF and other debt (₹)', n.debt, at('debt'))}${field(prefix + 'gold', 'Gold (₹)', n.gold, at('gold'))}</div>`;
  }

  function numbersStep() {
    return `<form class="gs-step" id="gs-form" novalidate><h2 tabindex="-1">Your numbers</h2><p class="gs-hint" style="margin:-10px 0 18px">These set your retirement date, check whether your goals fit your budget, and let you set aside existing savings for goals.</p>${numbersFields('n-')}<p class="gs-error" id="gs-err" role="alert"></p>${navButtons('Next', false)}</form>`;
  }

  function goalEditor(g, i) {
    const p = `g${i}-`;
    const types = C.goalTypes.map((t) => `<option value="${t.id}" ${g.type === t.id ? 'selected' : ''}>${esc(T.goalTypes[t.id])}</option>`).join('');
    const prios = Object.keys(T.priorities).map((k) => `<option value="${k}" ${g.priority === k ? 'selected' : ''}>${T.priorities[k]}</option>`).join('');
    const at = (key, extra) => `type="number" min="0" data-goal="${i}" data-key="${key}" ${extra || ''}`;
    const main = g.type === 'retirement'
      ? field(p + 'exp', 'Monthly expenses in today’s ₹', g.monthlyExpense, at('monthlyExpense')) + field(p + 'ry', 'Years in retirement', g.retirementYears, at('retirementYears', 'max="50" step="1"')) + `<div class="gs-field"><span class="gs-label">Years to retirement</span><p style="margin:10px 0 0">${isInt(state.numbers.retireYears, 0, 45) ? esc(state.numbers.retireYears) : '–'} <span class="gs-hint">(from your numbers)</span></p></div>`
      : field(p + 'cost', 'Cost in today’s ₹', g.cost, at('cost')) + field(p + 'yrs', 'Years away', g.years, at('years', 'max="40" step="1"'));
    return `<div class="gs-goal"><div class="gs-goal-head"><span>Goal ${i + 1}</span>${state.goals.length > 1 ? `<button type="button" class="gs-link" data-act="remove" data-goal="${i}">Remove</button>` : ''}</div>
      <div class="gs-fields"><div class="gs-field"><label for="${p}type">Goal type</label><select id="${p}type" data-goal="${i}" data-key="type">${types}</select></div>${main}
      <div class="gs-field"><label for="${p}prio">Priority</label><select id="${p}prio" data-goal="${i}" data-key="priority">${prios}</select></div>
      ${field(p + 'saved', 'Already saved for it (₹)', g.saved, at('saved'), 'Optional')}${field(p + 'infl', 'Inflation for this goal (% a year)', g.inflation, at('inflation', 'max="20" step="0.1"'))}</div></div>`;
  }

  function goalsEditor() {
    return state.goals.map(goalEditor).join('') + (state.goals.length < C.maxGoals ? '<button type="button" class="gs-btn ghost" data-act="add">+ Add a goal</button>' : `<p class="gs-hint">You can add up to ${C.maxGoals} goals.</p>`);
  }

  function goalsStep() {
    return `<form class="gs-step" id="gs-form" novalidate><h2 tabindex="-1">Your goals</h2><p class="gs-hint" style="margin:-10px 0 18px">Add 1 to ${C.maxGoals} goals. Enter costs in today’s money; the calculator adds inflation.</p><div id="gs-goals">${goalsEditor()}</div><p class="gs-error" id="gs-err" role="alert"></p>${navButtons('See my results', false)}</form>`;
  }

  function resultsStep() {
    const a = state.assumptions;
    const at = (key, extra) => `type="number" step="0.1" min="0" max="30" data-asm="${key}" ${extra || ''}`;
    const answers = Q.map((q, i) => `<div class="gs-field"><label for="a-${q.id}">${i + 1}. ${esc(T.questions[q.id].q)}</label><select id="a-${q.id}" data-answer="${q.id}">${T.questions[q.id].options.map((o, idx) => `<option value="${idx}" ${state.answers[q.id] === idx ? 'selected' : ''}>${esc(o)}</option>`).join('')}</select></div>`).join('');
    return `<div class="gs-results"><div id="gs-report" tabindex="-1"></div>
      <aside class="gs-edit" aria-label="Change your inputs"><p class="gs-label">Change anything; the results update as you type</p>
        <details open><summary>Assumptions</summary><p class="gs-hint">Illustrative rates only. They are not expected or promised returns.</p><div class="gs-fields">
          ${field('as-eq', 'Equity, illustrative (% a year)', a.equity, at('equity'))}${field('as-db', 'Debt, illustrative (% a year)', a.debt, at('debt'))}${field('as-gd', 'Gold, illustrative (% a year)', a.gold, at('gold'))}
          ${field('as-post', 'After retirement, illustrative (% a year)', a.post, at('post'))}${field('as-step', 'Yearly step-up for step-up SIP (%)', a.stepUp, at('stepUp', 'max="50"'))}</div></details>
        <details><summary>Your goals</summary><div id="gs-goals">${goalsEditor()}</div></details>
        <details><summary>Your numbers</summary>${numbersFields('e-')}</details>
        <details><summary>Your answers</summary><div class="gs-fields">${answers}</div></details>
        <div class="gs-nav"><button type="button" class="gs-btn ghost" data-act="restart">Start again</button></div>
      </aside></div>`;
  }

  function render(focus) {
    setProgress();
    if (state.step < Q.length) stage.innerHTML = questionStep(state.step);
    else if (state.step === STEP_NUMBERS) stage.innerHTML = numbersStep();
    else if (state.step === STEP_GOALS) stage.innerHTML = goalsStep();
    else { stage.innerHTML = resultsStep(); renderReport(); track('completed'); }
    if (focus) {
      const target = stage.querySelector('legend, h2[tabindex], #gs-report');
      if (target) target.focus({ preventScroll: true });
      document.getElementById('gs-tool').scrollIntoView({ block: 'start', behavior: 'smooth' });
    }
  }

  // ---------- report ----------
  function assumptionsForCalc() {
    const a = state.assumptions;
    return { returns: { equity: num(a.equity), debt: num(a.debt), gold: num(a.gold) }, postRetirementReturn: num(a.post), stepUp: num(a.stepUp) };
  }

  function assumptionsError() {
    const a = state.assumptions;
    if (![a.equity, a.debt, a.gold, a.post].every((v) => inRange(v, 0, 30))) return 'Illustrative rates must be between 0% and 30%.';
    if (!inRange(a.stepUp, 0, 50)) return 'Step-up must be between 0% and 50%.';
    return null;
  }

  function goalName(g, i) {
    return `Goal ${i + 1} · ${T.goalTypes[g.type]}`;
  }

  function mixBar(mix) {
    return `<div class="gs-mix" role="img" aria-label="Equity ${mix.equity}%, debt ${mix.debt}%, gold ${mix.gold}%">${mix.equity ? `<span class="eq" style="width:${mix.equity}%"></span>` : ''}${mix.debt ? `<span class="db" style="width:${mix.debt}%"></span>` : ''}${mix.gold ? `<span class="gd" style="width:${mix.gold}%"></span>` : ''}</div>
      <div class="gs-mix-key"><span><i style="background:var(--ink)"></i>Equity ${mix.equity}%</span><span><i style="background:#8fa197"></i>Debt ${mix.debt}%</span><span><i style="background:#c9a43b"></i>Gold ${mix.gold}%</span></div>`;
  }

  // Required SIP per goal against the monthly surplus (FR-R3). Plain HTML bars so the
  // labels stay readable at 360px; the funded part is solid, the unfunded part hatched,
  // and each row also states its status in words.
  function chart(rows, surplus, total) {
    const max = Math.max(total, surplus, 1) * 1.04;
    const w = (v) => (100 * v / max).toFixed(2) + '%';
    const line = `<span style="position:absolute;top:-4px;bottom:-4px;left:${w(surplus)};border-left:2px dashed var(--coral-text)" aria-hidden="true"></span>`;
    const bar = (label, need, given, bold) => {
      const gap = Math.max(0, need - given);
      const status = need === 0 ? 'already funded' : gap > 0.5 ? `short ${inr(gap)}/month` : 'fits';
      return `<div style="margin:10px 0" role="img" aria-label="${esc(label)}: needs ${inr(need)} a month, ${status}">
        <div style="display:flex;justify-content:space-between;gap:10px;font-size:13px;${bold ? 'font-weight:700' : ''}"><span>${esc(label)}</span><span>${inr(need)} <span style="color:var(--muted);font-weight:400">· ${status}</span></span></div>
        <div style="position:relative;height:14px;background:var(--line);margin-top:4px;border-radius:2px;display:flex;gap:2px">
          ${given > 0 ? `<span style="width:${w(given)};background:var(--ink);border-radius:2px 0 0 2px"></span>` : ''}
          ${gap > 0.5 ? `<span style="width:${w(gap)};background:repeating-linear-gradient(135deg,var(--coral-text) 0 3px,transparent 3px 6px);border:1px solid var(--coral-text)"></span>` : ''}
          ${line}</div></div>`;
    };
    return `<div class="gs-chart"><p class="gs-hint">Dashed line: the ${inr(surplus)} a month you can invest. Solid: covered by it. Hatched: not covered.</p>
      ${rows.map((r) => bar(r.label, r.need, r.given)).join('')}${rows.length > 1 ? bar('All goals', total, Math.min(total, surplus), true) : ''}</div>`;
  }

  function renderReport() {
    const report = document.getElementById('gs-report');
    if (!report) return;
    const score = K.scoreProfile(state.answers, C);
    const p = score.profile;
    const pText = T.profiles[p.id];
    const problems = [numbersError(state.numbers), assumptionsError()].filter(Boolean);

    let html = `<div class="gs-profile"><p class="eyebrow">Your indicative risk profile</p><h2>${esc(pText.name)}</h2>
      <div class="gs-scores"><span>Risk capacity <b>${score.capacity}/20</b></span><span>Risk willingness <b>${score.willingness}/20</b></span><span>Profile score (lower of the two) <b>${score.finalScore}</b></span></div>
      <p>${esc(pText.text)}</p>`;
    if (score.mismatch) html += `<div class="gs-note">${esc(fmt(score.mismatch === 'capacity' ? T.notes.mismatchCapacity : T.notes.mismatchWillingness, { c: score.capacity, w: score.willingness }))}</div>`;
    if (score.expectFlag) html += `<div class="gs-note">${esc(T.notes.expectation)}</div>`;
    html += `<p class="gs-label" style="margin-top:16px">Asset mix for goals 7+ years away</p>${mixBar({ equity: p.equity, debt: p.debt, gold: p.gold })}<p class="gs-hint">Goals sooner than 7 years get less equity; see each goal below.</p></div>`;

    if (problems.length) {
      html += `<div class="gs-section"><div class="gs-note">${problems.map(esc).join('<br>')}</div></div>`;
      report.innerHTML = html + complianceBox();
      return;
    }

    const A = assumptionsForCalc();
    const surplus = num(state.numbers.surplus);
    const valid = [];
    const cards = [];
    state.goals.forEach((g, i) => {
      const err = goalError(g);
      if (err) { cards.push(`<div class="gs-card"><h3>${esc(goalName(g, i))}</h3><p class="gs-error">${esc(err)}</p></div>`); return; }
      const calcGoal = { type: g.type, cost: num(g.cost), years: g.type === 'retirement' ? num(state.numbers.retireYears) : num(g.years), saved: g.saved === '' ? 0 : num(g.saved), inflation: num(g.inflation), monthlyExpense: num(g.monthlyExpense), retirementYears: num(g.retirementYears) };
      valid.push({ g, i, calcGoal, plan: K.planGoal(calcGoal, p, A, C), card: cards.length });
      cards.push('');
    });

    const alloc = K.allocate(valid.map((v) => v.g), valid.map((v) => v.plan), surplus);
    const rows = [];
    valid.forEach((v, k) => {
      const { plan, g, i, calcGoal } = v;
      const a = alloc.perGoal[k];
      rows.push({ label: goalName(g, i), need: plan.sip, given: a.allocated });
      let body = `<div class="gs-row"><span>Future cost in ${plan.years} yrs${g.type === 'retirement' ? ' (corpus)' : ''}</span><b>${inr(plan.futureCost)}</b></div>`;
      if (calcGoal.saved > 0) body += `<div class="gs-row"><span>Savings grow to</span><b>${inr(plan.savedGrown)}</b></div>`;
      body += `<div style="margin:10px 0 4px">${mixBar(plan.mix)}</div><div class="gs-row"><span>Blended illustrative rate</span><b>${pct(plan.rate)}</b></div>`;
      let status;
      if (plan.funded) {
        status = `<span class="gs-status ok">✓ ${esc(T.notes.funded)}</span>`;
      } else {
        body += `<div class="gs-row"><span>Monthly SIP</span><b>${inr(plan.sip)}</b></div><div class="gs-row"><span>Step-up SIP (start, +${pct(A.stepUp)}/yr)</span><b>${inr(plan.stepUpSip)}</b></div><div class="gs-row"><span>Or lumpsum today</span><b>${inr(plan.lumpsum)}</b></div>`;
        if (a.gap < 0.5) {
          status = '<span class="gs-status ok">✓ On track: fits your monthly surplus</span>';
        } else {
          const l = K.levers(calcGoal, p, A, C, a.allocated);
          const items = [fmt(T.levers.moreSurplus, { v: inr(a.gap) })];
          // Time, step-up and a lower target only make sense when some SIP is going in.
          if (a.allocated > 0) {
            // More time doesn't help when goal inflation outpaces the blended rate; such levers are left out.
            if (g.type !== 'retirement' && l.years) items.push(fmt(T.levers.years, { n: l.years }));
            if (l.stepUp !== null) items.push(fmt(T.levers.stepUp, { p: pct(l.stepUp) }));
            items.push(fmt(g.type === 'retirement' ? T.levers.targetRetirement : T.levers.target, { v: inr(l.targetToday) }));
          }
          items.push(fmt(T.levers.lumpsum, { v: inr(l.lumpsum) }));
          status = `<span class="gs-status short">! Short by ${inr(a.gap)} a month</span><p class="gs-hint" style="margin-top:8px">${a.allocated > 0 ? `Your surplus covers ${inr(a.allocated)} a month of this goal.` : 'Your surplus is used up by higher-priority goals.'} Any one of these would close the gap on these assumptions:</p><ul class="gs-levers">${items.map((t) => `<li>${esc(t)}</li>`).join('')}</ul>`;
        }
      }
      cards[v.card] = `<div class="gs-card"><h3>${esc(goalName(g, i))}</h3><span class="meta">${T.priorities[g.priority]} priority · ${pct(calcGoal.inflation)} inflation</span>${body}${status}</div>`;
    });

    const total = alloc.totalSip;
    html += `<div class="gs-section"><h2>Can your surplus cover your goals?</h2><div class="gs-sum"><div>Total monthly SIP needed<b>${inr(total)}</b></div><div>You can invest<b>${inr(surplus)}</b></div><div>${total > surplus ? 'Shortfall' : 'Left over'}<b>${inr(Math.abs(surplus - total))}</b></div></div>`;
    if (rows.length) html += chart(rows, surplus, total);
    if (total > surplus) html += '<p class="gs-hint">Your surplus is given to high-priority goals first, then medium, then low. This uses the flat monthly SIP for each goal.</p>';
    const holdings = ['mf', 'equity', 'debt', 'gold'].reduce((s, k) => s + (state.numbers[k] === '' ? 0 : num(state.numbers[k])), 0);
    const earmarked = valid.reduce((s, v) => s + v.calcGoal.saved, 0);
    if (holdings > 0 && earmarked > holdings) html += `<div class="gs-note">${esc(fmt(T.notes.holdingsShort, { e: inr(earmarked), h: inr(holdings) }))}</div>`;
    html += `</div><div class="gs-section"><h2>Goal by goal</h2><div class="gs-cards">${cards.join('')}</div></div>`;
    html += `<div class="gs-section"><h2>Assumptions used</h2><p class="gs-hint">Illustrative rates, not expected or promised returns: equity ${pct(A.returns.equity)}, debt ${pct(A.returns.debt)}, gold ${pct(A.returns.gold)} a year; ${pct(A.postRetirementReturn)} a year after retirement; step-up ${pct(A.stepUp)} a year. SIPs are invested at the start of each month. Actual returns will differ and can be negative.</p></div>`;
    html += `<div class="gs-section gs-noprint"><h2>Next steps</h2><div class="gs-cta"><button type="button" class="gs-btn" data-act="print">Save as PDF</button><a class="gs-btn ghost" href="https://t.me/+nxbISOilZJoxOTFl" target="_blank" rel="noopener" data-cta>Join our Telegram</a><a class="gs-btn ghost" href="https://wa.me/919967355038?text=Hi%2C%20I%20used%20the%20goal%20SIP%20calculator%20and%20would%20like%20to%20talk%20about%20mutual%20funds." target="_blank" rel="noopener" data-cta>Talk to us about mutual funds</a></div></div>`;
    report.innerHTML = html + complianceBox();
  }

  function complianceBox() {
    return `<div class="gs-compliance"><p><strong>Please read.</strong> ${esc(complianceText())}</p><p>This tool only scores a risk profile and does SIP arithmetic for mutual fund goals. It is not a recommendation to buy any product.</p></div>`;
  }

  // ---------- printing (FR-R5) ----------
  function preparePrint() {
    const report = document.getElementById('gs-report');
    document.getElementById('gs-print-date').textContent = new Date().toLocaleDateString('en-IN', { day: 'numeric', month: 'long', year: 'numeric' });
    document.getElementById('gs-print-body').innerHTML = report ? report.innerHTML : '<p>Complete the questions to see your report.</p>';
  }
  window.addEventListener('beforeprint', preparePrint);

  // ---------- events ----------
  function goTo(step) {
    state.step = step;
    render(true);
  }

  stage.addEventListener('submit', (e) => {
    e.preventDefault();
    const err = document.getElementById('gs-err');
    if (state.step < Q.length) {
      if (state.answers[Q[state.step].id] === undefined) return; // FR-S5
      goTo(state.step + 1);
    } else if (state.step === STEP_NUMBERS) {
      const msg = numbersError(state.numbers);
      if (msg) { err.textContent = msg; return; }
      goTo(STEP_GOALS);
    } else if (state.step === STEP_GOALS) {
      const bad = state.goals.map(goalError).findIndex(Boolean);
      if (bad >= 0) { err.textContent = `Goal ${bad + 1}: ${goalError(state.goals[bad])}`; return; }
      goTo(STEP_RESULTS);
    }
  });

  stage.addEventListener('change', (e) => {
    const t = e.target;
    if (t.name === 'answer') {
      state.answers[Q[state.step].id] = Number(t.value);
      track('started');
      stage.querySelector('button[type=submit]').disabled = false;
    } else if (t.dataset.answer) {
      state.answers[t.dataset.answer] = Number(t.value);
      renderReport();
    } else if (t.dataset.key === 'type') {
      const i = Number(t.dataset.goal);
      const fresh = newGoal(t.value);
      state.goals[i] = { ...fresh, priority: state.goals[i].priority, saved: state.goals[i].saved };
      redrawGoals();
    } else if (t.dataset.key === 'priority') {
      state.goals[Number(t.dataset.goal)].priority = t.value;
      renderReport();
    }
  });

  stage.addEventListener('input', (e) => {
    const t = e.target;
    if (t.dataset.num) {
      state.numbers[t.dataset.num] = t.value;
      if (t.dataset.num === 'retireYears') redrawRetirementYears();
    } else if (t.dataset.goal !== undefined && t.dataset.key && t.tagName === 'INPUT') {
      state.goals[Number(t.dataset.goal)][t.dataset.key] = t.value;
    } else if (t.dataset.asm) {
      state.assumptions[t.dataset.asm] = t.value;
    } else return;
    const err = document.getElementById('gs-err');
    if (err) err.textContent = '';
    renderReport();
  });

  stage.addEventListener('click', (e) => {
    const t = e.target.closest('[data-act], [data-cta]');
    if (!t) return;
    if (t.hasAttribute('data-cta')) { track('cta_clicked'); return; }
    const act = t.dataset.act;
    if (act === 'back') goTo(state.step - 1);
    else if (act === 'add' && state.goals.length < C.maxGoals) { state.goals.push(newGoal('custom')); redrawGoals(); }
    else if (act === 'remove') { state.goals.splice(Number(t.dataset.goal), 1); redrawGoals(); }
    else if (act === 'print') { track('pdf_saved'); preparePrint(); window.print(); }
    else if (act === 'restart') {
      state.answers = {};
      state.numbers = { retireYears: '', surplus: '', mf: '', equity: '', debt: '', gold: '' };
      state.goals = [newGoal('education')];
      goTo(0);
    }
  });

  function redrawGoals() {
    const box = document.getElementById('gs-goals');
    if (box) box.innerHTML = goalsEditor();
    renderReport();
  }

  // The retirement goal shows years to retirement from the numbers; keep it in sync
  // without redrawing the field being typed in.
  function redrawRetirementYears() {
    if (state.step === STEP_RESULTS && state.goals.some((g) => g.type === 'retirement')) {
      const box = document.getElementById('gs-goals');
      if (box && !box.contains(document.activeElement)) box.innerHTML = goalsEditor();
    }
  }

  // ---------- static parts of the page ----------
  document.querySelectorAll('[data-compliance]').forEach((el) => { el.textContent = complianceText(); });
  const mixTable = document.getElementById('gs-mix-table');
  if (mixTable) mixTable.innerHTML = C.profiles.map((p) => `<tr><td>${p.min}–${p.max}</td><td>${esc(T.profiles[p.id].name)}</td><td>${p.equity}%</td><td>${p.debt}%</td><td>${p.gold}%</td></tr>`).join('');

  render(false);
})();
