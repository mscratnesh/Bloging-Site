// Run with: node --test tests/
// Each SIP, step-up SIP, lumpsum and retirement figure is checked against a plain
// month-by-month simulation (a separate way of getting the same number), to within ₹1
// as NFR-07 asks. Scoring and the horizon override are checked against the BRS tables.
const test = require('node:test');
const assert = require('node:assert/strict');
const config = require('../goal-sip-config.js');
const calc = require('../goal-sip-calc.js');

const assumptions = { returns: { ...config.returns }, postRetirementReturn: config.postRetirementReturn, stepUp: config.defaultStepUp };
const profileById = (id) => config.profiles.find((p) => p.id === id);
const TOLERANCE = 1;

// Invest `sip` at the start of every month for years*12 months, raising it by stepUp%
// at the start of each new year; return the balance at the end.
function simulateSip(sip, annualPct, years, stepUpPct) {
  const rm = Math.pow(1 + annualPct / 100, 1 / 12) - 1;
  let balance = 0;
  let amount = sip;
  for (let m = 0; m < years * 12; m++) {
    if (m > 0 && m % 12 === 0) amount *= 1 + stepUpPct / 100;
    balance = (balance + amount) * (1 + rm);
  }
  return balance;
}

// Draw `expense` at the start of every month, raised by inflation each year; return what is left.
function simulateDrawdown(corpus, expense, years, postPct, inflationPct) {
  const rm = Math.pow(1 + postPct / 100, 1 / 12) - 1;
  let balance = corpus;
  for (let y = 0; y < years; y++) {
    const monthly = expense * Math.pow(1 + inflationPct / 100, y);
    for (let m = 0; m < 12; m++) balance = (balance - monthly) * (1 + rm);
  }
  return balance;
}

const goalCases = [
  { profile: 'conservative', cost: 500000, years: 1, inflation: 5, saved: 0 },
  { profile: 'aggressive', cost: 800000, years: 2, inflation: 5, saved: 100000 },
  { profile: 'moderate', cost: 1500000, years: 3, inflation: 7, saved: 0 },
  { profile: 'aggressive', cost: 1500000, years: 4, inflation: 7, saved: 200000 },
  { profile: 'mod-conservative', cost: 2000000, years: 5, inflation: 6, saved: 0 },
  { profile: 'aggressive', cost: 2000000, years: 6, inflation: 6, saved: 0 },
  { profile: 'moderate', cost: 2500000, years: 7, inflation: 10, saved: 300000 },
  { profile: 'mod-aggressive', cost: 2500000, years: 10, inflation: 10, saved: 0 },
  { profile: 'aggressive', cost: 3000000, years: 15, inflation: 10, saved: 500000 },
  { profile: 'conservative', cost: 1000000, years: 12, inflation: 7, saved: 0 },
  { profile: 'mod-conservative', cost: 5000000, years: 20, inflation: 7, saved: 1000000 },
  { profile: 'moderate', cost: 750000, years: 8, inflation: 5, saved: 50000 },
  { profile: 'mod-aggressive', cost: 12000000, years: 25, inflation: 6, saved: 0 },
  { profile: 'aggressive', cost: 20000000, years: 30, inflation: 6, saved: 2500000 },
  { profile: 'conservative', cost: 300000, years: 40, inflation: 6, saved: 0 },
  { profile: 'moderate', cost: 4000000, years: 18, inflation: 10, saved: 0 },
  { profile: 'mod-aggressive', cost: 600000, years: 3, inflation: 5, saved: 0 },
  { profile: 'mod-conservative', cost: 900000, years: 6, inflation: 7, saved: 150000 },
  { profile: 'aggressive', cost: 100000, years: 5, inflation: 6, saved: 0 },
  { profile: 'moderate', cost: 10000000, years: 35, inflation: 7, saved: 0 },
  { profile: 'mod-aggressive', cost: 3500000, years: 9, inflation: 10, saved: 400000 },
  { profile: 'conservative', cost: 2500000, years: 14, inflation: 6, saved: 250000 },
];

for (const [i, c] of goalCases.entries()) {
  test(`goal case ${i + 1}: ${c.profile}, ₹${c.cost}, ${c.years} yrs`, () => {
    const plan = calc.planGoal({ type: 'custom', ...c }, profileById(c.profile), assumptions, config);
    const fv = c.cost * Math.pow(1 + c.inflation / 100, c.years);
    assert.ok(Math.abs(plan.futureCost - fv) < TOLERANCE);
    const target = fv - c.saved * Math.pow(1 + plan.rate / 100, c.years);
    assert.ok(Math.abs(plan.shortfall - target) < TOLERANCE);
    assert.ok(Math.abs(simulateSip(plan.sip, plan.rate, c.years, 0) - target) < TOLERANCE, 'flat SIP reaches the goal');
    assert.ok(Math.abs(simulateSip(plan.stepUpSip, plan.rate, c.years, 10) - target) < TOLERANCE, 'step-up SIP reaches the goal');
    assert.ok(Math.abs(plan.lumpsum * Math.pow(1 + plan.rate / 100, c.years) - target) < TOLERANCE, 'lumpsum reaches the goal');
    // FR-C5 written out literally.
    const rm = Math.pow(1 + plan.rate / 100, 1 / 12) - 1;
    const N = 12 * c.years;
    assert.ok(Math.abs(plan.sip - (target * rm) / ((Math.pow(1 + rm, N) - 1) * (1 + rm))) < TOLERANCE);
  });
}

test('worked example: ₹10,00,000 at 10% inflation for 10 years', () => {
  const plan = calc.planGoal({ type: 'custom', cost: 1000000, years: 10, inflation: 10, saved: 0 }, profileById('moderate'), assumptions, config);
  assert.equal(Math.round(plan.futureCost), 2593742);
  assert.deepEqual(plan.mix, { equity: 50, gold: 10, debt: 40 });
  assert.ok(Math.abs(plan.rate - 8.9) < 1e-9); // 0.5*11 + 0.4*6.5 + 0.1*8
});

test('goal already funded by savings (FR-C9)', () => {
  const plan = calc.planGoal({ type: 'custom', cost: 100000, years: 5, inflation: 6, saved: 200000 }, profileById('moderate'), assumptions, config);
  assert.equal(plan.funded, true);
  assert.equal(plan.sip, 0);
  assert.equal(plan.lumpsum, 0);
});

for (const [years, expense, inRetirement] of [[25, 50000, 25], [10, 80000, 20], [30, 40000, 30]]) {
  test(`retirement: ₹${expense}/month, ${years} yrs away, ${inRetirement} yrs in retirement`, () => {
    const goal = { type: 'retirement', monthlyExpense: expense, years, retirementYears: inRetirement, inflation: 6, saved: 0 };
    const plan = calc.planGoal(goal, profileById('mod-aggressive'), assumptions, config);
    const expenseAtRetirement = expense * Math.pow(1.06, years);
    assert.ok(Math.abs(simulateDrawdown(plan.futureCost, expenseAtRetirement, inRetirement, 7, 6)) < TOLERANCE, 'corpus lasts exactly the retirement period');
    assert.ok(Math.abs(simulateSip(plan.sip, plan.rate, years, 0) - plan.futureCost) < TOLERANCE);
  });
}

test('horizon override at 2, 4, 6 and 10 years (acceptance 4)', () => {
  const aggressive = profileById('aggressive');
  const conservative = profileById('conservative');
  assert.deepEqual(calc.goalMix(aggressive, 2, config), { equity: 0, gold: 0, debt: 100 });
  assert.deepEqual(calc.goalMix(aggressive, 4, config), { equity: 30, gold: 10, debt: 60 });
  assert.deepEqual(calc.goalMix(aggressive, 6, config), { equity: 50, gold: 10, debt: 40 });
  assert.deepEqual(calc.goalMix(aggressive, 10, config), { equity: 80, gold: 10, debt: 10 });
  assert.deepEqual(calc.goalMix(conservative, 4, config), { equity: 20, gold: 10, debt: 70 });
  assert.deepEqual(calc.goalMix(conservative, 6, config), { equity: 20, gold: 10, debt: 70 });
  assert.deepEqual(calc.goalMix(aggressive, 3, config), { equity: 30, gold: 10, debt: 60 });
  assert.deepEqual(calc.goalMix(aggressive, 7, config), { equity: 80, gold: 10, debt: 10 });
});

const ids = config.questions.map((q) => q.id);
// Build answers whose capacity (5-20) and willingness (5-19) sums are the given totals.
// Willingness tops out at 19 because Q10's best option scores 3, not 4.
function answersFor(capacity, willingness) {
  const answers = {};
  const fill = (qs, total) => {
    let left = total - qs.length;
    for (const q of qs) {
      const best = Math.max(...q.points);
      const want = 1 + Math.min(best - 1, left);
      left -= want - 1;
      answers[q.id] = q.points.findIndex((p, i) => p === want && i !== q.flagOption);
    }
    assert.equal(left, 0, `total ${total} is not reachable`);
  };
  fill(config.questions.filter((q) => q.part === 'capacity'), capacity);
  fill(config.questions.filter((q) => q.part === 'willingness'), willingness);
  return answers;
}

test('all five profiles are reachable at their score boundaries', () => {
  const expected = [[5, 'conservative'], [7, 'conservative'], [8, 'mod-conservative'], [10, 'mod-conservative'], [11, 'moderate'], [14, 'moderate'], [15, 'mod-aggressive'], [17, 'mod-aggressive'], [18, 'aggressive'], [19, 'aggressive']];
  for (const [score, id] of expected) {
    const r = calc.scoreProfile(answersFor(Math.min(20, score + 1), score), config);
    assert.equal(r.finalScore, score);
    assert.equal(r.profile.id, id);
  }
});

test('final score is the lower sub-score; mismatch note only at a gap of 6+ (FR-S2, FR-S3)', () => {
  let r = calc.scoreProfile(answersFor(18, 13), config);
  assert.equal(r.finalScore, 13);
  assert.equal(r.mismatch, null);
  r = calc.scoreProfile(answersFor(18, 12), config);
  assert.equal(r.mismatch, 'willingness');
  r = calc.scoreProfile(answersFor(8, 14), config);
  assert.equal(r.mismatch, 'capacity');
  assert.equal(r.profile.id, 'mod-conservative');
});

test('15%+ expectation scores 2 and raises the flag (FR-S4)', () => {
  const answers = answersFor(12, 12);
  const before = calc.scoreProfile(answers, config);
  assert.equal(before.expectFlag, false);
  const expectQ = config.questions.find((q) => q.id === 'expect');
  answers.expect = expectQ.points.indexOf(2); // the 8-11% option
  const plain = calc.scoreProfile(answers, config);
  answers.expect = expectQ.flagOption;
  const flagged = calc.scoreProfile(answers, config);
  assert.equal(flagged.expectFlag, true);
  assert.equal(flagged.willingness, plain.willingness);
});

test('a blank answer gives no result (FR-S5)', () => {
  const answers = answersFor(12, 12);
  delete answers[ids[3]];
  assert.equal(calc.scoreProfile(answers, config), null);
});

test('age bands: under 30 and 30-40 both score 4', () => {
  const age = config.questions.find((q) => q.id === 'age');
  assert.deepEqual(age.points, [4, 4, 3, 2, 1]);
});

test('surplus goes to goals in priority order, then entry order (FR-F2)', () => {
  const goals = [{ priority: 'low' }, { priority: 'high' }, { priority: 'medium' }, { priority: 'high' }];
  const plans = [{ sip: 4000 }, { sip: 5000 }, { sip: 3000 }, { sip: 2000 }];
  const { perGoal, totalSip } = calc.allocate(goals, plans, 9000);
  assert.equal(totalSip, 14000);
  assert.deepEqual(perGoal.map((g) => g.allocated), [0, 5000, 2000, 2000]);
  assert.deepEqual(perGoal.map((g) => g.gap), [4000, 0, 1000, 0]);
});

test('final score never reaches 20: willingness is capped at 19', () => {
  const best = calc.scoreProfile(Object.fromEntries(config.questions.map((q) => [q.id, q.points.indexOf(Math.max(...q.points))])), config);
  assert.equal(best.capacity, 20);
  assert.equal(best.willingness, 19);
  assert.equal(best.profile.id, 'aggressive');
});

test('more years does not help when goal inflation beats the blended return', () => {
  const profile = profileById('moderate'); // 8.9% blended at 7+ years
  const goal = { type: 'custom', cost: 2500000, years: 10, inflation: 10, saved: 0 };
  const plan = calc.planGoal(goal, profile, assumptions, config);
  assert.equal(calc.levers(goal, profile, assumptions, config, plan.sip * 0.6).years, null);
});

test('each lever, applied alone, closes the gap (FR-F3)', () => {
  const profile = profileById('moderate');
  const goal = { type: 'custom', cost: 2500000, years: 10, inflation: 6, saved: 0 };
  const plan = calc.planGoal(goal, profile, assumptions, config);
  const affordable = plan.sip * 0.6;
  const l = calc.levers(goal, profile, assumptions, config, affordable);
  assert.ok(calc.planGoal({ ...goal, years: l.years }, profile, assumptions, config).sip <= affordable);
  assert.ok(calc.planGoal({ ...goal, years: l.years - 1 }, profile, assumptions, config).sip > affordable);
  assert.ok(simulateSip(affordable, plan.rate, goal.years, l.stepUp) >= plan.shortfall - TOLERANCE);
  assert.ok(Math.abs(calc.planGoal({ ...goal, cost: l.targetToday }, profile, assumptions, config).sip - affordable) < TOLERANCE);
  assert.ok(Math.abs(calc.planGoal({ ...goal, saved: l.lumpsum }, profile, assumptions, config).sip - affordable) < TOLERANCE);
});
