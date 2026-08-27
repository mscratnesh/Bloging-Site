function money(value) {
  return '₹' + value.toLocaleString('en-IN', { maximumFractionDigits: 0 });
}

function row(label, value) {
  return `<div class="calc-result-row"><span>${label}</span><b>${value}</b></div>`;
}

function setupSIPCalculator() {
  const form = document.getElementById('sip-form');
  const resultDiv = document.getElementById('sip-result');
  if (!form) return;
  form.onsubmit = (event) => {
    event.preventDefault();
    const amount = parseFloat(document.getElementById('sip-amount').value);
    const rate = parseFloat(document.getElementById('sip-rate').value);
    const years = parseInt(document.getElementById('sip-years').value, 10);
    if (!(amount > 0 && rate > 0 && years > 0)) { resultDiv.textContent = 'Please enter valid values.'; return; }
    const months = years * 12;
    const monthlyRate = rate / 12 / 100;
    const fv = amount * (((Math.pow(1 + monthlyRate, months) - 1) / monthlyRate) * (1 + monthlyRate));
    const invested = amount * months;
    resultDiv.innerHTML = row('Total invested', money(invested)) + row('Estimated value', money(fv)) + row('Estimated gain', money(fv - invested));
  };
}

function setupLumpCalculator() {
  const form = document.getElementById('lump-form');
  const resultDiv = document.getElementById('lump-result');
  if (!form) return;
  form.onsubmit = (event) => {
    event.preventDefault();
    const amount = parseFloat(document.getElementById('lump-amount').value);
    const rate = parseFloat(document.getElementById('lump-rate').value);
    const years = parseInt(document.getElementById('lump-years').value, 10);
    if (!(amount > 0 && rate > 0 && years > 0)) { resultDiv.textContent = 'Please enter valid values.'; return; }
    const fv = amount * Math.pow(1 + rate / 100, years);
    resultDiv.innerHTML = row('Invested amount', money(amount)) + row('Estimated value', money(fv)) + row('Estimated gain', money(fv - amount));
  };
}

function setupLumpSIPCalculator() {
  const form = document.getElementById('lumpsip-form');
  const resultDiv = document.getElementById('lumpsip-result');
  if (!form) return;
  form.onsubmit = (event) => {
    event.preventDefault();
    const lump = parseFloat(document.getElementById('lumpsip-lump').value);
    const sip = parseFloat(document.getElementById('lumpsip-sip').value);
    const rate = parseFloat(document.getElementById('lumpsip-rate').value);
    const years = parseInt(document.getElementById('lumpsip-years').value, 10);
    if (!(lump >= 0 && sip >= 0 && rate > 0 && years > 0)) { resultDiv.textContent = 'Please enter valid values.'; return; }
    const lumpFV = lump * Math.pow(1 + rate / 100, years);
    const months = years * 12;
    const monthlyRate = rate / 12 / 100;
    const sipFV = sip * (((Math.pow(1 + monthlyRate, months) - 1) / monthlyRate) * (1 + monthlyRate));
    const invested = lump + sip * months;
    const totalFV = lumpFV + sipFV;
    resultDiv.innerHTML = row('Total invested', money(invested)) + row('Estimated value', money(totalFV)) + row('Estimated gain', money(totalFV - invested));
  };
}

function setupEMICalculator() {
  const form = document.getElementById('emi-form');
  const resultDiv = document.getElementById('emi-result');
  if (!form) return;
  form.onsubmit = (event) => {
    event.preventDefault();
    const principal = parseFloat(document.getElementById('emi-principal').value);
    const rate = parseFloat(document.getElementById('emi-rate').value);
    const years = parseInt(document.getElementById('emi-years').value, 10);
    if (!(principal > 0 && rate > 0 && years > 0)) { resultDiv.textContent = 'Please enter valid values.'; return; }
    const n = years * 12;
    const r = rate / 12 / 100;
    const emi = principal * r * Math.pow(1 + r, n) / (Math.pow(1 + r, n) - 1);
    const total = emi * n;
    resultDiv.innerHTML = row('Monthly EMI', money(emi)) + row('Total payment', money(total)) + row('Total interest', money(total - principal));
  };
}

function setupEMIAddCalculator() {
  const form = document.getElementById('emiadd-form');
  const resultDiv = document.getElementById('emiadd-result');
  if (!form) return;
  form.onsubmit = (event) => {
    event.preventDefault();
    const principal = parseFloat(document.getElementById('emiadd-principal').value);
    const rate = parseFloat(document.getElementById('emiadd-rate').value);
    const years = parseInt(document.getElementById('emiadd-years').value, 10);
    const extra = parseFloat(document.getElementById('emiadd-extra').value);
    if (!(principal > 0 && rate > 0 && years > 0 && extra >= 0)) { resultDiv.textContent = 'Please enter valid values.'; return; }
    const n = years * 12;
    const r = rate / 12 / 100;
    const emi = principal * r * Math.pow(1 + r, n) / (Math.pow(1 + r, n) - 1);
    let balance = principal, totalInterest = 0, month = 0;
    while (balance > 0.1 && month < 1000) {
      month++;
      const interest = balance * r;
      balance -= (emi - interest);
      if (month % 12 === 0 && extra > 0) balance -= extra;
      totalInterest += interest;
      if (balance < 0) balance = 0;
    }
    const totalPaid = emi * month + extra * Math.floor(month / 12);
    resultDiv.innerHTML = row('Monthly EMI', money(emi)) + row('Total payment', money(totalPaid)) + row('Total interest', money(totalInterest)) + row('Loan paid off in', `${Math.floor(month / 12)} years ${month % 12} months`);
  };
}

function setupTaxCalculator() {
  const form = document.getElementById('tax-form');
  const resultDiv = document.getElementById('tax-result');
  if (!form) return;
  form.onsubmit = (event) => {
    event.preventDefault();
    const income = parseFloat(document.getElementById('tax-income').value);
    const deduction80C = parseFloat(document.getElementById('tax-deduction').value);
    const medical = parseFloat(document.getElementById('tax-medical').value);
    const hra = parseFloat(document.getElementById('tax-hra').value);
    const rent = parseFloat(document.getElementById('tax-rent').value);
    const pf = parseFloat(document.getElementById('tax-pf').value);
    const age = document.getElementById('tax-age').value;
    let hraExempt = 0;
    if (hra > 0 && rent > 0) hraExempt = Math.max(0, Math.min(hra, rent - 0.1 * income));
    const ded80C = Math.min(deduction80C, 150000);
    const max80D = (age === 'senior' || age === 'super') ? 50000 : 25000;
    const ded80D = Math.min(medical, max80D);
    const totalDed = ded80C + ded80D + pf + hraExempt;
    if (!(income >= 0 && deduction80C >= 0 && medical >= 0 && hra >= 0 && rent >= 0 && pf >= 0) || totalDed > income) {
      resultDiv.textContent = 'Please enter valid values.'; return;
    }

    const taxableOld = Math.max(0, income - totalDed);
    let slabsOld;
    if (age === 'normal' || age === 'huf') slabsOld = [{ upto: 250000, rate: 0 }, { upto: 500000, rate: 0.05 }, { upto: 1000000, rate: 0.2 }, { upto: Infinity, rate: 0.3 }];
    else if (age === 'senior') slabsOld = [{ upto: 300000, rate: 0 }, { upto: 500000, rate: 0.05 }, { upto: 1000000, rate: 0.2 }, { upto: Infinity, rate: 0.3 }];
    else slabsOld = [{ upto: 500000, rate: 0 }, { upto: 1000000, rate: 0.2 }, { upto: Infinity, rate: 0.3 }];
    let taxOld = 0, prevOld = 0;
    for (const slab of slabsOld) {
      if (taxableOld > slab.upto) { taxOld += (slab.upto - prevOld) * slab.rate; prevOld = slab.upto; }
      else { taxOld += (taxableOld - prevOld) * slab.rate; break; }
    }
    if (taxableOld <= 500000) taxOld = 0;
    const cessOld = taxOld * 0.04;
    const totalOld = taxOld + cessOld;

    const taxableNew = Math.max(0, income - 50000);
    const slabsNew = [{ upto: 300000, rate: 0 }, { upto: 600000, rate: 0.05 }, { upto: 900000, rate: 0.1 }, { upto: 1200000, rate: 0.15 }, { upto: 1500000, rate: 0.2 }, { upto: Infinity, rate: 0.3 }];
    let taxNew = 0, prevNew = 0;
    for (const slab of slabsNew) {
      if (taxableNew > slab.upto) { taxNew += (slab.upto - prevNew) * slab.rate; prevNew = slab.upto; }
      else { taxNew += (taxableNew - prevNew) * slab.rate; break; }
    }
    if (taxableNew <= 700000) taxNew = 0;
    const cessNew = taxNew * 0.04;
    const totalNew = taxNew + cessNew;

    resultDiv.innerHTML = `<div class="calc-result-cards">
      <div class="calc-result-card"><h3>Old regime</h3>${row('Taxable income', money(taxableOld))}${row('Income tax', money(taxOld))}${row('Cess (4%)', money(cessOld))}${row('Total payable', money(totalOld))}<p class="calc-result-note">Deductions claimed: ${money(totalDed)}</p></div>
      <div class="calc-result-card"><h3>New regime</h3>${row('Taxable income', money(taxableNew))}${row('Income tax', money(taxNew))}${row('Cess (4%)', money(cessNew))}${row('Total payable', money(totalNew))}<p class="calc-result-note">Standard deduction ₹50,000. Other deductions not allowed.</p></div>
    </div>`;
  };
}

function setupCGTCalculator() {
  const form = document.getElementById('cgt-form');
  const resultDiv = document.getElementById('cgt-result');
  if (!form) return;
  form.onsubmit = (event) => {
    event.preventDefault();
    const type = document.getElementById('cgt-type').value;
    const buy = parseFloat(document.getElementById('cgt-buy').value);
    const sell = parseFloat(document.getElementById('cgt-sell').value);
    const years = parseFloat(document.getElementById('cgt-years').value);
    const exp = parseFloat(document.getElementById('cgt-exp').value);
    if (!(buy >= 0 && sell >= 0 && years >= 0 && exp >= 0) || sell < buy) { resultDiv.textContent = 'Please enter valid values.'; return; }
    const gain = sell - buy - exp;
    if (gain <= 0) { resultDiv.innerHTML = '<p>No capital gain.</p>'; return; }
    let tax = 0, slab = '', details = '';
    if (type === 'stock' || type === 'equity-mf') {
      if (years >= 1) { slab = 'Long term'; tax = Math.max(0, gain - 100000) * 0.10; details = 'LTCG above ₹1L taxed at 10%'; }
      else { slab = 'Short term'; tax = gain * 0.15; details = 'STCG taxed at 15%'; }
    } else if (type === 'debt-mf') {
      slab = years >= 3 ? 'Long term' : 'Short term';
      tax = gain * 0.30;
      details = 'Taxed at slab rate (assumed 30% for illustration)';
    } else {
      if (years >= 2) { slab = 'Long term'; tax = gain * 0.20; details = 'LTCG taxed at 20% (indexation not included)'; }
      else { slab = 'Short term'; tax = gain * 0.30; details = 'STCG taxed at slab rate (assumed 30% for illustration)'; }
    }
    resultDiv.innerHTML = row('Capital gain type', slab) + row('Net capital gain', money(gain)) + row('Tax payable', money(tax)) + `<p class="calc-result-note">${details}</p>`;
  };
}

function setupRetireCalculator() {
  const form = document.getElementById('retire-form');
  const resultDiv = document.getElementById('retire-result');
  if (!form) return;
  form.onsubmit = (event) => {
    event.preventDefault();
    const age = parseInt(document.getElementById('retire-age').value, 10);
    const retireAge = parseInt(document.getElementById('retire-retire').value, 10);
    const life = parseInt(document.getElementById('retire-life').value, 10);
    const exp = parseFloat(document.getElementById('retire-exp').value);
    const infl = parseFloat(document.getElementById('retire-infl').value);
    const rate = parseFloat(document.getElementById('retire-rate').value);
    if (!(age >= 18 && retireAge > age && life > retireAge && exp > 0 && infl > 0 && rate > 0)) { resultDiv.textContent = 'Please enter valid values.'; return; }
    const yearsRetired = life - retireAge;
    const expAtRetire = exp * Math.pow(1 + infl / 100, retireAge - age);
    const annualExp = expAtRetire * 12;
    const r = rate / 100;
    const corpus = annualExp * ((1 - Math.pow(1 + r, -yearsRetired)) / r) * (1 + r);
    resultDiv.innerHTML = row('Monthly expenses at retirement', money(expAtRetire)) + row('Years in retirement', yearsRetired) + row('Required retirement corpus', money(corpus));
  };
}

function setupGoalCalculator() {
  const form = document.getElementById('goal-form');
  const resultDiv = document.getElementById('goal-result');
  if (!form) return;
  form.onsubmit = (event) => {
    event.preventDefault();
    const amount = parseFloat(document.getElementById('goal-amount').value);
    const years = parseInt(document.getElementById('goal-years').value, 10);
    const rate = parseFloat(document.getElementById('goal-rate').value);
    const type = document.getElementById('goal-type').value;
    if (!(amount > 0 && years > 0 && rate > 0)) { resultDiv.textContent = 'Please enter valid values.'; return; }
    let extra;
    if (type === 'sip') {
      const months = years * 12;
      const monthlyRate = rate / 12 / 100;
      const factor = ((Math.pow(1 + monthlyRate, months) - 1) / monthlyRate) * (1 + monthlyRate);
      extra = row('Required monthly SIP', money(amount / factor));
    } else {
      extra = row('Required lump sum investment', money(amount / Math.pow(1 + rate / 100, years)));
    }
    resultDiv.innerHTML = row('Goal amount', money(amount)) + row('Years to goal', years) + row('Expected return', `${rate}% p.a.`) + extra;
  };
}

function setupSWPCalculator() {
  const form = document.getElementById('swp-form');
  const resultDiv = document.getElementById('swp-result');
  if (!form) return;
  form.onsubmit = (event) => {
    event.preventDefault();
    const corpus = parseFloat(document.getElementById('swp-corpus').value);
    const withdraw = parseFloat(document.getElementById('swp-withdraw').value);
    const rate = parseFloat(document.getElementById('swp-rate').value);
    const years = parseInt(document.getElementById('swp-years').value, 10);
    if (!(corpus > 0 && withdraw > 0 && rate > 0 && years > 0)) { resultDiv.textContent = 'Please enter valid values.'; return; }
    let balance = corpus;
    const months = years * 12;
    const monthlyRate = rate / 12 / 100;
    let depletedMonth = null;
    for (let m = 1; m <= months; m++) {
      balance = balance * (1 + monthlyRate) - withdraw;
      if (balance < 0) { depletedMonth = m; break; }
    }
    let outcome;
    if (depletedMonth) {
      const y = Math.floor((depletedMonth - 1) / 12);
      const mo = (depletedMonth - 1) % 12;
      outcome = `<p class="calc-result-warn">Corpus will be depleted in ${y} years ${mo} months.</p>`;
    } else {
      outcome = `<p class="calc-result-ok">Corpus will last for ${years} years.</p>` + row('Estimated final balance', money(balance));
    }
    resultDiv.innerHTML = row('Initial corpus', money(corpus)) + row('Monthly withdrawal', money(withdraw)) + row('Expected return', `${rate}% p.a.`) + row('Planned period', `${years} years`) + outcome;
  };
}

function setupCalculatorCollapse() {
  document.querySelectorAll('.collapse-btn[data-target]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const content = document.getElementById(btn.dataset.target);
      const isOpen = btn.classList.contains('active');
      document.querySelectorAll('.collapse-btn[data-target]').forEach((b) => { b.classList.remove('active'); b.querySelector('b').textContent = '+'; });
      document.querySelectorAll('.collapse-content').forEach((c) => c.classList.remove('active'));
      if (!isOpen) {
        btn.classList.add('active');
        btn.querySelector('b').textContent = '–';
        content.classList.add('active');
      }
    });
  });
}

setupCalculatorCollapse();
setupSIPCalculator();
setupLumpCalculator();
setupLumpSIPCalculator();
setupEMICalculator();
setupEMIAddCalculator();
setupTaxCalculator();
setupCGTCalculator();
setupRetireCalculator();
setupGoalCalculator();
setupSWPCalculator();
