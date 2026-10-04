// Settings and wording for the Goal SIP calculator (goal-sip-calculator.html).
// Thresholds, allocations, default rates and every question live here, not in the
// page or the maths, so they can be changed (and re-reviewed by compliance, CR-09)
// in one place. Text sits under strings.en so a Hindi block can be added later.
(function (root) {
  const config = {
    // Compliance details shown in the footer and on every printed page (CR-06).
    // If arn is ever blank the page shows a visible placeholder instead.
    arn: 'ARN-132137', // the author's own ARN (individual), not Nirmal Bang's
    distributorName: 'Ratnesh Kumar Singh',
    distributorLine: 'AMFI-registered Mutual Fund Distributor',
    associatedWith: 'associated with Nirmal Bang',

    // Illustrative return assumptions, % per year (FR-C1, CR-03). Owner to confirm.
    returns: { equity: 11, debt: 6.5, gold: 8 },
    postRetirementReturn: 7,
    defaultStepUp: 10,
    defaultRetirementYears: 25,
    maxGoals: 6,

    // Final score -> profile and asset mix (section 4.4).
    profiles: [
      { id: 'conservative', min: 5, max: 7, equity: 20, debt: 70, gold: 10 },
      { id: 'mod-conservative', min: 8, max: 10, equity: 35, debt: 55, gold: 10 },
      { id: 'moderate', min: 11, max: 14, equity: 50, debt: 40, gold: 10 },
      { id: 'mod-aggressive', min: 15, max: 17, equity: 65, debt: 25, gold: 10 },
      { id: 'aggressive', min: 18, max: 20, equity: 80, debt: 10, gold: 10 },
    ],
    mismatchGap: 6, // FR-S3

    // Horizon override (section 5.2). Rows are checked in order; first match wins.
    // equityCap null means the profile's own equity applies.
    horizon: [
      { below: 3, equityCap: 0, gold: 0 },
      { below: 5, equityCap: 30, gold: 10 },
      { below: 7, equityCap: 50, gold: 10 },
      { below: Infinity, equityCap: null, gold: 10 },
    ],

    // Goal types and default inflation, % per year (FR-G3). Owner to confirm.
    goalTypes: [
      { id: 'education', inflation: 10 },
      { id: 'marriage', inflation: 7 },
      { id: 'house', inflation: 7 },
      { id: 'car', inflation: 5 },
      { id: 'retirement', inflation: 6 },
      { id: 'custom', inflation: 6 },
    ],

    // Risk questions (section 4.2). points[i] is the score of option i.
    // part: 'capacity' (Q1-Q5) or 'willingness' (Q6-Q10).
    questions: [
      { id: 'age', part: 'capacity', points: [4, 4, 3, 2, 1] },
      { id: 'income', part: 'capacity', points: [1, 2, 3, 4] },
      { id: 'dependents', part: 'capacity', points: [4, 3, 2, 1] },
      { id: 'emergency', part: 'capacity', points: [1, 2, 3, 4] },
      { id: 'need', part: 'capacity', points: [1, 2, 3, 4] },
      { id: 'fall', part: 'willingness', points: [1, 2, 3, 4] },
      { id: 'experience', part: 'willingness', points: [1, 2, 3, 4] },
      { id: 'objective', part: 'willingness', points: [1, 2, 3, 4] },
      { id: 'range', part: 'willingness', points: [1, 2, 3, 4] },
      { id: 'expect', part: 'willingness', points: [1, 2, 3, 2], flagOption: 3 },
    ],

    strings: {
      en: {
        questions: {
          age: { q: 'Your age band', options: ['Under 30', '30–40', '40–50', '50–60', '60 or above'] },
          income: { q: 'How steady is your income?', options: ['No regular income, or retired', 'Variable (business, commission)', 'Salaried, private sector', 'Highly secure, or several sources'] },
          dependents: { q: 'How many people depend on your income?', options: ['None', '1', '2', '3 or more'] },
          emergency: { q: 'How many months of expenses do you keep as an emergency fund?', options: ['None', 'Less than 3 months', '3 to 6 months', '6 months or more'] },
          need: { q: 'When might you need a large part of this money?', options: ['Within 2 years', 'In 2 to 5 years', 'In 5 to 8 years', 'After 8 years or more'] },
          fall: { q: 'Your investments fall 25% in 3 months. What do you do?', options: ['Sell everything', 'Sell some', 'Hold and wait', 'Invest more'] },
          experience: { q: 'Your investing experience so far', options: ['Only FDs, PPF and similar', 'Some mutual funds', 'Mutual funds and stocks for 3+ years', 'Held stocks through a major market crash'] },
          objective: { q: 'What is the main aim for this money?', options: ['Protect what I have', 'Earn a regular income', 'Balanced growth', 'Maximum long-term growth'] },
          range: { q: 'Which one-year range of outcomes would you accept?', options: ['−2% to +8%', '−8% to +15%', '−15% to +25%', '−30% to +40%'] },
          expect: { q: 'What yearly return do you expect over the long term?', options: ['6–8%', '8–11%', '11–14%', '15% or more'] },
        },
        profiles: {
          conservative: { name: 'Conservative', text: 'Keeping your capital steady matters more to you than growth, or your situation leaves little room for losses. Most of the money sits in debt, with a small share in equity for long-term goals. Expect slower growth and smaller swings.' },
          'mod-conservative': { name: 'Moderately Conservative', text: 'You can accept some ups and downs, but stability still comes first. Debt forms the larger share, and equity adds growth for goals that are several years away. Expect modest swings in value.' },
          moderate: { name: 'Moderate', text: 'You want a balance of growth and stability. Equity and debt carry roughly equal weight for long-term goals. Expect noticeable falls in bad years, which you are prepared to sit through.' },
          'mod-aggressive': { name: 'Moderately Aggressive', text: 'You are aiming for growth and can handle sharp falls along the way. Equity forms the larger share for long-term goals, with debt as a cushion. Expect large swings in value in some years.' },
          aggressive: { name: 'Aggressive', text: 'You have both the room and the temperament to take high risk for long-term growth. Equity dominates the mix for long-term goals. Expect deep temporary falls, sometimes lasting years.' },
        },
        goalTypes: { education: 'Child education', marriage: 'Child marriage', house: 'House down payment', car: 'Car', retirement: 'Retirement', custom: 'Custom goal' },
        priorities: { high: 'High', medium: 'Medium', low: 'Low' },
        notes: {
          mismatchCapacity: 'Your willingness to take risk ({w}/20) is well above your capacity to take it ({c}/20). Your situation (age, income, dependents, emergency fund or time frame) is what limits your profile here.',
          mismatchWillingness: 'Your capacity to take risk ({c}/20) is well above your willingness to take it ({w}/20). Your comfort with ups and downs is what limits your profile here.',
          expectation: 'You expect 15% a year or more over the long term. Returns are never assured, and a target that depends on a high return can easily fall short. The SIPs below use the lower illustrative rates shown under Assumptions; you can change them, but be cautious about raising them.',
          holdingsShort: 'Savings earmarked for goals ({e}) are more than the existing holdings you entered ({h}).',
          funded: 'Already funded on these assumptions.',
          retirementNeedsYears: 'Set years to retirement (in your profile) to at least 1 to calculate this goal.',
        },
        levers: {
          years: 'Push the goal out to {n} years',
          stepUp: 'Raise the SIP by {p} every year',
          moreSurplus: 'Invest {v} more each month',
          target: 'Lower the target to {v} in today’s money',
          targetRetirement: 'Lower the monthly retirement expense to {v} in today’s money',
          lumpsum: 'Add a lumpsum of {v} today',
        },
      },
    },
    lang: 'en',
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = config;
  else root.GOAL_SIP_CONFIG = config;
})(this);
