// Scoring and SIP maths for the Goal SIP calculator. Pure functions, no DOM, so the
// same file runs in the browser and under `node tests/goal-sip.test.js`.
// Rates are passed as percentages (11 = 11% a year); amounts are rupees.
(function (root) {
  function scoreProfile(answers, config) {
    // answers: option index per question id. Returns null while any is blank (FR-S5).
    let capacity = 0;
    let willingness = 0;
    let expectFlag = false;
    for (const q of config.questions) {
      const pick = answers[q.id];
      if (pick === undefined || pick === null || q.points[pick] === undefined) return null;
      if (q.part === 'capacity') capacity += q.points[pick];
      else willingness += q.points[pick];
      if (q.flagOption === pick) expectFlag = true;
    }
    const finalScore = Math.min(capacity, willingness);
    const profile = config.profiles.find((p) => finalScore >= p.min && finalScore <= p.max);
    let mismatch = null;
    if (Math.abs(capacity - willingness) >= config.mismatchGap) {
      mismatch = capacity < willingness ? 'capacity' : 'willingness';
    }
    return { capacity, willingness, finalScore, profile, mismatch, expectFlag };
  }

  function goalMix(profile, years, config) {
    const row = config.horizon.find((h) => years < h.below);
    const equity = row.equityCap === null ? profile.equity : Math.min(profile.equity, row.equityCap);
    const gold = row.equityCap === null ? profile.gold : row.gold;
    return { equity, gold, debt: 100 - equity - gold };
  }

  function blendedReturn(mix, returns) {
    return (mix.equity * returns.equity + mix.debt * returns.debt + mix.gold * returns.gold) / 100;
  }

  function monthlyRate(annualPct) {
    return Math.pow(1 + annualPct / 100, 1 / 12) - 1;
  }

  // Value at the end of `years` of 1 rupee a month, paid at the start of each month,
  // with the monthly amount raised by stepUpPct at the start of each new year.
  function sipFactor(annualPct, years, stepUpPct) {
    const rm = monthlyRate(annualPct);
    const g = (stepUpPct || 0) / 100;
    const yearFactor = rm === 0 ? 12 : ((Math.pow(1 + rm, 12) - 1) / rm) * (1 + rm);
    // Year k's 12 instalments are worth yearFactor at the end of that year, then grow
    // for the remaining whole years; (1 + rm)^12 is exactly one year of growth.
    let total = 0;
    for (let k = 0; k < years; k++) {
      total += Math.pow(1 + g, k) * yearFactor * Math.pow(1 + annualPct / 100, years - 1 - k);
    }
    return total;
  }

  function futureCost(costToday, inflationPct, years) {
    return costToday * Math.pow(1 + inflationPct / 100, years);
  }

  // Corpus needed at retirement: present value (at retirement) of a monthly expense,
  // paid at the start of each month, held flat within a year and raised by inflation
  // each year, discounted at the post-retirement return (FR-C8).
  function retirementCorpus(monthlyExpenseAtRetirement, yearsInRetirement, postReturnPct, inflationPct) {
    const rm = monthlyRate(postReturnPct);
    let pv = 0;
    for (let y = 0; y < yearsInRetirement; y++) {
      const expense = monthlyExpenseAtRetirement * Math.pow(1 + inflationPct / 100, y);
      for (let m = 0; m < 12; m++) pv += expense / Math.pow(1 + rm, 12 * y + m);
    }
    return pv;
  }

  // One goal -> future cost, mix, shortfall, SIP, step-up SIP and lumpsum (FR-C2..C9).
  // goal: { type, cost, years, saved, inflation, monthlyExpense, retirementYears }
  function planGoal(goal, profile, assumptions, config) {
    const years = goal.years;
    const mix = goalMix(profile, years, config);
    const r = blendedReturn(mix, assumptions.returns);
    let fv;
    if (goal.type === 'retirement') {
      const expenseAtRetirement = futureCost(goal.monthlyExpense, goal.inflation, years);
      fv = retirementCorpus(expenseAtRetirement, goal.retirementYears, assumptions.postRetirementReturn, goal.inflation);
    } else {
      fv = futureCost(goal.cost, goal.inflation, years);
    }
    const savedGrown = (goal.saved || 0) * Math.pow(1 + r / 100, years);
    const shortfall = fv - savedGrown;
    const funded = shortfall <= 0;
    const sip = funded ? 0 : shortfall / sipFactor(r, years, 0);
    const stepUpSip = funded ? 0 : shortfall / sipFactor(r, years, assumptions.stepUp);
    const lumpsum = funded ? 0 : shortfall / Math.pow(1 + r / 100, years);
    return { years, mix, rate: r, futureCost: fv, savedGrown, shortfall, funded, sip, stepUpSip, lumpsum };
  }

  const PRIORITY_ORDER = { high: 0, medium: 1, low: 2 };

  // Spread the monthly surplus over goals in priority order (FR-F1, FR-F2).
  // Returns allocated SIP and gap per goal, in the goals' original order.
  function allocate(goals, plans, surplus) {
    const order = goals.map((g, i) => i).sort((a, b) => (PRIORITY_ORDER[goals[a].priority] - PRIORITY_ORDER[goals[b].priority]) || a - b);
    let left = Math.max(0, surplus || 0);
    const result = plans.map(() => null);
    for (const i of order) {
      const need = plans[i] ? plans[i].sip : 0;
      const given = Math.min(need, left);
      left -= given;
      result[i] = { allocated: given, gap: need - given };
    }
    return { perGoal: result, totalSip: plans.reduce((s, p) => s + (p ? p.sip : 0), 0), unused: left };
  }

  // What-if levers for a goal that is short at a given affordable SIP (FR-F3).
  function levers(goal, profile, assumptions, config, affordableSip) {
    const base = planGoal(goal, profile, assumptions, config);
    const out = {};

    // More years: the smallest horizon (up to 40) where the affordable SIP is enough.
    // Not offered for retirement, whose horizon is the retirement date itself.
    if (goal.type !== 'retirement') {
      out.years = null;
      for (let n = goal.years + 1; n <= 40; n++) {
        if (affordableSip > 0 && planGoal({ ...goal, years: n }, profile, assumptions, config).sip <= affordableSip) { out.years = n; break; }
      }
    }

    // Step-up: the yearly raise (0-50%) that makes the affordable SIP enough.
    out.stepUp = null;
    if (affordableSip > 0) {
      const fvAt = (g) => affordableSip * sipFactor(base.rate, goal.years, g);
      if (fvAt(50) >= base.shortfall) {
        let lo = 0;
        let hi = 50;
        for (let i = 0; i < 60; i++) {
          const mid = (lo + hi) / 2;
          if (fvAt(mid) >= base.shortfall) hi = mid; else lo = mid;
        }
        out.stepUp = Math.ceil(hi * 10) / 10;
      }
    }

    // Lower target: the goal size (today's money) that the affordable SIP plus savings reach.
    const reachable = affordableSip * sipFactor(base.rate, goal.years, 0) + base.savedGrown;
    out.targetToday = goal.type === 'retirement'
      ? goal.monthlyExpense * reachable / base.futureCost // as a monthly expense in today's money
      : reachable / Math.pow(1 + goal.inflation / 100, goal.years);

    // Extra lumpsum today that closes the remaining gap.
    out.lumpsum = Math.max(0, base.shortfall - affordableSip * sipFactor(base.rate, goal.years, 0)) / Math.pow(1 + base.rate / 100, goal.years);
    return out;
  }

  const api = { scoreProfile, goalMix, blendedReturn, monthlyRate, sipFactor, futureCost, retirementCorpus, planGoal, allocate, levers };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.GoalSipCalc = api;
})(this);
