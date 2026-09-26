/**
 * Multi Year Breakout - auto trade tracker (v2 rules, Sep 2026)
 * Weekly (Sat): logs new BREAKOUTs from MasterData (signal already applies market filter,
 * liquidity, base depth, median-10 volume, close position and the 10% risk cap) and C&H
 * breakouts that pass the same market / liquidity / risk gates. Open trades use two-stage exits:
 *   Stage 1 (peak close < +20%): FAILED-BO = weekly close < R with Wk Vol Ratio >= 1.0
 *                                SL        = weekly close < Initial SL  (MAX(R x 0.97, breakout-week low); C&H = handle low)
 *   Stage 2 (after any weekly close >= Entry x 1.20):
 *                                BREAKEVEN = weekly close < MAX(Initial SL, Entry)
 *                                TRAIL-10W = weekly close < 10-week SMA
 */
const MASTER = 'MasterData';
const TRACKER = 'Tracker';
const SETTINGS = 'Settings';
const HEADERS = ['Symbol', 'Entry Date', 'Entry Price', 'Resistance (R)', 'Weekly Close',
  '10W MA (Trail)', 'Status', 'Exit Date', 'Exit Price', 'Exit Reason', 'P&L %', 'Base (yrs)', 'Setup',
  'Active SL', 'SL Dist %', 'Initial SL', 'Peak Close', 'Stage', 'Qty', 'Wk Vol Ratio'];

function onOpen() {
  SpreadsheetApp.getUi().createMenu('Breakout Tracker')
    .addItem('Update now', 'updateTracker')
    .addItem('Set weekly auto-update (Sat 9 AM)', 'createWeeklyTrigger')
    .addItem('Build Cup & Handle scanner', 'setupCupHandle')
    .addSeparator()
    .addItem('Upgrade to v2 rules (one-time)', 'upgradeToV2')
    .addToUi();
}

function getTracker_(ss) {
  let sh = ss.getSheetByName(TRACKER);
  if (!sh) {
    sh = ss.insertSheet(TRACKER);
    sh.setFrozenRows(1);
    sh.getRange('B:B').setNumberFormat('dd-mmm-yyyy');
    sh.getRange('H:H').setNumberFormat('dd-mmm-yyyy');
    sh.getRange('C:F').setNumberFormat('0.00');
    sh.getRange('I:I').setNumberFormat('0.00');
    sh.getRange('K:K').setNumberFormat('0.00%');
  }
  ensureSlColumns_(sh);
  return sh;
}

function getSetting_(ss, a1, dflt) {
  const s = ss.getSheetByName(SETTINGS);
  if (!s) return dflt;
  const v = s.getRange(a1).getValue();
  return (v === '' || v === null) ? dflt : v;
}

function ma30Formula_(r) {
  return '=IFERROR(AVERAGE(QUERY(GOOGLEFINANCE("NSE:"&A' + r + ',"close",TODAY()-250,TODAY(),"WEEKLY"),"select Col2 order by Col1 desc limit 30",1)),"")';
}
// (v1, unused in v2) lowest weekly LOW of the 2 completed weeks before the latest week
function trail2wFormula_(r) {
  return '=IFERROR(LET(d,GOOGLEFINANCE("NSE:"&A' + r + ',"low",TODAY()-42,TODAY(),"WEEKLY"),n,ROWS(d),MIN(INDEX(d,n-2,2),INDEX(d,n-1,2))),"")';
}
// v2 trail: 10-week SMA of weekly closes (latest week included)
// v2 volume: latest week volume / median of previous 10 weeks
// Qty = Capital x Risk per trade / (Entry - Initial SL)
function qtyFormula_(r) {
  return '=IFERROR(FLOOR(Settings!$B$6*Settings!$B$8/(C' + r + '-P' + r + ')),"")';
}
// Active SL = Initial SL in Stage 1, MAX(Initial SL, Entry) in Stage 2; SL Dist % = cushion of weekly close above it
function setSlFormulas_(sh, r) {
  sh.getRange(r, 14, 1, 2).setFormulas([[
    '=IF(A' + r + '="","",IF(R' + r + '=2,MAX(P' + r + ',C' + r + '),IF(P' + r + '="",D' + r + ',P' + r + ')))',
    '=IF(OR(G' + r + '="EXIT",E' + r + '="",N' + r + '=""),"",E' + r + '/N' + r + '-1)'
  ]]);
}
function ensureSlColumns_(sh) {
  sh.getRange(1, 1, 1, HEADERS.length).setValues([HEADERS])
    .setFontWeight('bold').setBackground('#0b3a53').setFontColor('#ffffff');
  sh.getRange('N:N').setNumberFormat('0.00');
  sh.getRange('O:O').setNumberFormat('0.00%');
  sh.getRange('P:Q').setNumberFormat('0.00');
  sh.getRange('R:S').setNumberFormat('0');
  sh.getRange('T:T').setNumberFormat('0.00');
}
function pnlFormula_(r) {
  return '=IF(I' + r + '<>"",I' + r + '/C' + r + '-1,IF(E' + r + '="","",E' + r + '/C' + r + '-1))';
}

function updateTracker() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const master = ss.getSheetByName(MASTER);
  if (master.getMaxColumns() < 17 || master.getRange(1, 17).getValue() !== '10W MA') {
    throw new Error('Run Breakout Tracker > Upgrade to v2 rules first.');
  }
  const sh = getTracker_(ss);
  const today = new Date();
  const mktOK = getSetting_(ss, 'B5', true) === true;
  const minLiq = Number(getSetting_(ss, 'B7', 5));
  const maxPos = Number(getSetting_(ss, 'B9', 10));
  const W = HEADERS.length;

  // 1) Manage open trades
  const last = sh.getLastRow();
  const open = {};
  let openCount = 0;
  if (last > 1) {
    const rows = sh.getRange(2, 1, last - 1, W).getValues();
    rows.forEach(function (row, i) {
      const r = i + 2;
      const sym = String(row[0]).trim();
      if (!sym) return;
      let setup = String(row[12]).trim();
      if (!setup) { setup = 'MYB'; sh.getRange(r, 13).setValue(setup); }
      const key = sym + '|' + setup;
      if (row[6] === 'EXIT') return;
      const entryP = Number(row[2]), R = Number(row[3]), wc = Number(row[4]), ma10 = Number(row[5]);
      const vr = Number(row[19]);
      let initSL = Number(row[15]);
      if (!(initSL > 0)) initSL = setup === 'C&H' ? R : Math.round(R * 0.97 * 100) / 100;
      const peak = Math.max(Number(row[16]) || 0, wc > 0 ? wc : 0, entryP);
      const stage = (Number(row[17]) === 2 || peak >= entryP * 1.2) ? 2 : 1;
      sh.getRange(r, 16, 1, 3).setValues([[initSL, peak, stage]]);
      // Entered less than 6 days ago: no completed week since entry yet
      const entry = row[1] instanceof Date ? row[1] : null;
      if (entry && (today - entry) < 6 * 24 * 3600 * 1000) { open[key] = true; openCount++; return; }
      let reason = '';
      if (wc > 0) {
        if (stage === 1) {
          if (R > 0 && wc < R && vr >= 1) reason = 'FAILED-BO: weekly close below R on above-avg volume';
          else if (wc < initSL) reason = 'SL: weekly close below initial SL';
        } else {
          const be = Math.max(initSL, entryP);
          if (wc < be) reason = 'BREAKEVEN: weekly close below breakeven stop';
          else if (ma10 > 0 && wc < ma10) reason = 'TRAIL-10W: weekly close below 10-week MA';
        }
      }
      if (reason) {
        // freeze values at exit
        sh.getRange(r, 5, 1, 2).setValues([[wc, ma10]]);
        sh.getRange(r, 7, 1, 4).setValues([['EXIT', today, wc, reason]]);
        sh.getRange(r, 11).setValue(wc / entryP - 1);
        sh.getRange(r, 20).setValue(vr);
      } else {
        sh.getRange(r, 7).setValue('HOLDING');
        open[key] = true; openCount++;
      }
    });
  }

  const skipped = [];
  const addTrade_ = function (sym, price, R, base, setup, initSL) {
    if (openCount >= maxPos) { skipped.push(sym + ' (' + setup + ')'); return; }
    const r = sh.getLastRow() + 1;
    sh.getRange(r, 1, 1, 4).setValues([[sym, today, price, R]]);
    sh.getRange(r, 5).setFormula(weeklyCloseFormula_(r));
    sh.getRange(r, 6).setFormula(ma10Formula_(r));
    sh.getRange(r, 7).setValue('BREAKOUT');
    sh.getRange(r, 11).setFormula(pnlFormula_(r));
    sh.getRange(r, 12).setValue(base);
    sh.getRange(r, 13).setValue(setup);
    setSlFormulas_(sh, r);
    sh.getRange(r, 16, 1, 3).setValues([[initSL, price, 1]]);
    sh.getRange(r, 19).setFormula(qtyFormula_(r));
    sh.getRange(r, 20).setFormula(wkVolFormula_(r));
    open[sym + '|' + setup] = true; openCount++;
  };

  // 2) New Multi Year BREAKOUTs (MasterData signal already applies every v2 entry gate)
  const m = master.getRange(2, 1, master.getLastRow() - 1, 17).getValues();
  const liq = {};
  m.forEach(function (row) {
    const sym = String(row[0]).trim();
    if (!sym) return;
    liq[sym] = Number(row[13]);
    if (row[8] !== 'BREAKOUT' || !mktOK || open[sym + '|MYB']) return;
    const R = Number(row[2]);
    const initSL = Number(row[14]) > 0 ? Math.round(Number(row[14]) * 100) / 100 : Math.round(R * 0.97 * 100) / 100;
    addTrade_(sym, Number(row[1]), R, Number(row[4]), 'MYB', initSL);
  });

  // 3) New C&H BREAKOUTs: same market, liquidity and 10% risk gates; R = pivot, Initial SL = handle low
  const ch = ss.getSheetByName(CH_SHEET);
  if (ch && ch.getLastRow() > 1) {
    const c = ch.getRange(2, 1, ch.getLastRow() - 1, 9).getValues();
    c.forEach(function (row) {
      const sym = String(row[0]).trim();
      if (!sym || row[2] !== 'BREAKOUT' || !mktOK || open[sym + '|C&H']) return;
      const cmp = Number(row[1]), pivot = Number(row[3]), hdep = Number(row[8]);
      const hl = Math.round(pivot * (1 - hdep) * 100) / 100;
      if (!(liq[sym] >= minLiq) || !(cmp > 0) || (cmp - hl) / cmp > 0.10) return;
      addTrade_(sym, cmp, pivot, '', 'C&H', hl);
    });
  }

  if (skipped.length) ss.toast('Max open positions (' + maxPos + ') reached. Not logged: ' + skipped.join(', '), 'Breakout Tracker', 15);
  colorStatus_(sh);
  upgradeFinalList_();
  formatFinalList();
}

// Adds a Setup column (G) to Final List and includes Cup & Handle signals
function upgradeFinalList_() {
  const fl = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Final List');
  if (fl.getRange('G2').getValue() !== '' && String(fl.getRange('G2').getFormula()).indexOf('C&H') < 0) {
    fl.insertColumnBefore(7); // shifts the rules block right
  }
  const core = 'LET(ts,IFERROR(INDIRECT("Tracker!A2:A"),""),st,IFERROR(INDIRECT("Tracker!G2:G"),""),' +
    'ed,IFERROR(INDIRECT("Tracker!H2:H"),""),sraw,IFERROR(INDIRECT("Tracker!M2:M"),""),su,IF(sraw="","MYB",sraw),' +
    't,IFERROR(FILTER(HSTACK(ts,st,su),ts<>"",(st<>"EXIT")+ISNUMBER(ed)*(ed>=TODAY()-30)),{"","",""}),' +
    'os,IFERROR(FILTER(ts&"|"&su,ts<>"",st<>"EXIT"),"~"),' +
    'ms,MasterData!A2:A,sg,MasterData!I2:I,' +
    'mybn,IFERROR(FILTER(HSTACK(ms,sg,IF(ROW(ms),"MYB")),(sg="BREAKOUT")+(sg="NEAR")+(sg="BLOCKED")+(sg="SKIP-RISK"),ISNA(MATCH(ms&"|MYB",os,0))),{"","",""}),' +
    'cs,IFERROR(INDIRECT("CupHandle!A2:A"),""),cg,IFERROR(INDIRECT("CupHandle!C2:C"),""),' +
    'chn,IFERROR(FILTER(HSTACK(cs,cg,IF(LEN(cs)>=0,"C&H")),(cg="BREAKOUT")+(cg="READY")+(cg="BO LOW VOL"),ISNA(MATCH(cs&"|C&H",os,0))),{"","",""}),' +
    'v,VSTACK(t,mybn,chn),a,FILTER(v,CHOOSECOLS(v,1)<>""),' +
    'r,MAP(CHOOSECOLS(a,2),LAMBDA(x,XMATCH(x,{"BREAKOUT";"HOLDING";"EXIT";"NEAR";"READY";"BO LOW VOL";"BLOCKED";"SKIP-RISK"}))),' +
    'CHOOSECOLS(SORT(HSTACK(a,r),4,TRUE,3,FALSE),';
  fl.getRange('A2').setFormula('=' + core + '1))');
  fl.getRange('E2').setFormula('=' + core + '2))');
  fl.getRange('G2').setFormula('=' + core + '3))');
  fl.getRange('G1').setValue('SETUP');
  fl.getRange('F1').copyFormatToRange(fl, 7, 7, 1, 1);
  fl.getRange('F2').setFormula('=ARRAYFORMULA(IF(A2:A="","",IF(G2:G="C&H","",IFNA(XLOOKUP(A2:A,MasterData!A2:A,MasterData!J2:J),""))))');
  // make sure per-row price / chart / 52W formulas cover enough rows
  const need = 150;
  fl.getRange('B2:D2').copyTo(fl.getRange(3, 2, need - 2, 3));
  // v2: rules text lives on the Rules sheet (Final List column H is the SL column)
}

// Colours the Status column (E) on Final List
function formatFinalList() {
  const fl = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Final List');
  const range = fl.getRange('E2:E');
  const keep = fl.getConditionalFormatRules().filter(function (r) {
    return !r.getRanges().some(function (g) { return g.getA1Notation() === range.getA1Notation(); });
  });
  [['BREAKOUT', '#b7e1cd'], ['HOLDING', '#fff2cc'], ['EXIT', '#f4c7c3'], ['NEAR', '#cfe2f3'], ['READY', '#d9ead3'], ['BO LOW VOL', '#fce5cd'], ['BLOCKED', '#d9d9d9'], ['SKIP-RISK', '#ead1dc']].forEach(function (x) {
    keep.push(SpreadsheetApp.newConditionalFormatRule().whenTextEqualTo(x[0])
      .setBackground(x[1]).setBold(true).setRanges([range]).build());
  });
  fl.setConditionalFormatRules(keep);
}

function colorStatus_(sh) {
  const range = sh.getRange('A2:T');
  const rules = [
    ['=$G2="BREAKOUT"', '#b7e1cd'],
    ['=$G2="HOLDING"', '#fff2cc'],
    ['=$G2="EXIT"', '#f4c7c3']
  ].map(function (x) {
    return SpreadsheetApp.newConditionalFormatRule()
      .whenFormulaSatisfied(x[0]).setBackground(x[1]).setRanges([range]).build();
  });
  sh.setConditionalFormatRules(rules);
}

function createWeeklyTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'updateTracker') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('updateTracker').timeBased()
    .onWeekDay(ScriptApp.WeekDay.SATURDAY).atHour(9).inTimezone('Asia/Kolkata').create();
}


/* ================= CUP & HANDLE SCANNER (weekly, O'Neil-style, v2) =================
 * Universe = MasterData symbols. Completed weeks come from the weekly GOOGLEFINANCE series (3 yrs);
 * the current week is rebuilt from daily bars, as in MasterData v2 (the weekly series leaves out the
 * latest week), so the breakout week and its volume are this week's, not last week's.
 * Pattern, on completed weeks:
 *   Right rim = highest weekly high of the last 10 completed weeks (latest one if tied); Pivot = its high.
 *   Handle = right rim week to last week: 1-8 weeks, <= 15% below the pivot, low in the upper half of the cup.
 *   Left rim = highest weekly high of the 65 weeks before the right rim. Cup = left rim to right rim:
 *   7-65 weeks, 12-40% deep, right rim 90-103% of left rim, >= 3 weeks down and >= 3 weeks up (U, not V).
 *   Prior uptrend: left rim >= 25% above the lowest low of the 52 weeks before it (at least 13 weeks of data).
 * Signals: BREAKOUT (0-5% above pivot, this week's vol >= 1.4x average of the previous 10 weeks, above
 *   30W MA), BO LOW VOL, READY (within 5% below pivot), HANDLE (deeper), EXTENDED (> 5% above).
 * Backtest (Nifty 500, Oct 2021 - Sep 2026, with the v2 market, liquidity and 10% risk gates and the
 * two-stage exits): these settings beat the stricter O'Neil ones; the volume rule mattered most.
 */
const CH_SHEET = 'CupHandle';
const CH_LIST = 'C&H List';
const CH_HEADERS = ['Symbol', 'CMP', 'C&H Signal', 'Pivot', 'Dist %', 'Cup Wks', 'Cup Depth %',
  'Handle Wks', 'Handle Depth %', 'Left Rim Date', 'Left Rim', 'Cup Low', 'Prior Up %', 'Vol Ratio', '30W MA'];

function chFormula_(r) {
  const s = '"NSE:"&$A' + r;
  return '=IF($A' + r + '="","",IFERROR(LET(' +
    // completed weeks (weekly series) + this week (daily bars since Monday)
    'raw,GOOGLEFINANCE(' + s + ',"all",TODAY()-1100,TODAY(),"WEEKLY"),w,CHOOSEROWS(raw,SEQUENCE(ROWS(raw)-1,1,2)),' +
    'draw,GOOGLEFINANCE(' + s + ',"all",TODAY()-14,TODAY(),"DAILY"),dd,CHOOSEROWS(draw,SEQUENCE(ROWS(draw)-1,1,2)),' +
    'ddt,INDEX(dd,0,1),ld,MAX(ddt),ws,INT(ld)-WEEKDAY(ld,3),cmk,ARRAYFORMULA(ddt>=ws),' +
    'wkC,INDEX(dd,ROWS(dd),5),wkV,SUM(FILTER(INDEX(dd,0,6),cmk)),' +
    'wdt,INDEX(w,0,1),n,SUM(ARRAYFORMULA(--(wdt<ws))),' +
    'dt,CHOOSEROWS(wdt,SEQUENCE(n)),hi,CHOOSEROWS(INDEX(w,0,3),SEQUENCE(n)),lo,CHOOSEROWS(INDEX(w,0,4),SEQUENCE(n)),' +
    'cl,CHOOSEROWS(INDEX(w,0,5),SEQUENCE(n)),vo,CHOOSEROWS(INDEX(w,0,6),SEQUENCE(n)),' +
    // right rim = highest high of the last 10 completed weeks; handle = right rim to last week
    't10,CHOOSEROWS(hi,SEQUENCE(10,1,n-9)),piv,MAX(t10),ir,n-10+XMATCH(piv,t10,0,-1),hw,n-ir+1,' +
    'hlow,MIN(CHOOSEROWS(lo,SEQUENCE(hw,1,ir))),' +
    // left rim = highest high of the 65 weeks before the right rim; cup low between the rims
    'lwin,CHOOSEROWS(hi,SEQUENCE(65,1,ir-65)),lrim,MAX(lwin),il,ir-66+XMATCH(lrim,lwin),' +
    'cwin,CHOOSEROWS(lo,SEQUENCE(ir-il+1,1,il)),cuplow,MIN(cwin),ib,il-1+XMATCH(cuplow,cwin),' +
    // prior uptrend: left rim vs the lowest low of the 52 weeks before it
    'pst,MAX(1,il-52),pup,IF(il-pst>=13,lrim/MIN(CHOOSEROWS(lo,SEQUENCE(il-pst,1,pst)))-1,0),' +
    'cmp,IF(ISNUMBER($B' + r + '),$B' + r + ',wkC),' +
    'cw,ir-il,dep,1-cuplow/lrim,rimr,piv/lrim,hdep,1-hlow/piv,dist,cmp/piv-1,' +
    'vr,wkV/AVERAGE(CHOOSEROWS(vo,SEQUENCE(10,1,n-9))),' +
    'mavg,(SUM(CHOOSEROWS(cl,SEQUENCE(29,1,n-28)))+wkC)/30,' +
    'okay,AND(cw>=7,cw<=65,dep>=0.12,dep<=0.4,rimr>=0.9,rimr<=1.03,ib-il>=3,ir-ib>=3,pup>=0.25,hw<=8,hdep<=0.15,hlow>=(lrim+cuplow)/2),' +
    'sig,IF(NOT(okay),"",IF(dist>0.05,"EXTENDED",IF(dist>0,IF(AND(vr>=1.4,cmp>mavg),"BREAKOUT","BO LOW VOL"),IF(dist>=-0.05,"READY","HANDLE")))),' +
    'HSTACK(sig,piv,dist,cw,dep,hw,hdep,INDEX(dt,il),lrim,cuplow,pup,vr,mavg)),""))';
}

function setupCupHandle() {
  const ss = SpreadsheetApp.getActive();
  const master = ss.getSheetByName(MASTER);
  const last = master.getLastRow();
  let sh = ss.getSheetByName(CH_SHEET) || ss.insertSheet(CH_SHEET);
  sh.clear();
  sh.clearConditionalFormatRules();
  if (sh.getMaxRows() < last) sh.insertRowsAfter(sh.getMaxRows(), last - sh.getMaxRows());
  sh.getRange(1, 1, 1, CH_HEADERS.length).setValues([CH_HEADERS])
    .setFontWeight('bold').setBackground('#0b3a53').setFontColor('#ffffff').setWrap(true);
  sh.setFrozenRows(1);
  const f = [];
  for (let r = 2; r <= last; r++) {
    f.push(["='" + MASTER + "'!A" + r, "='" + MASTER + "'!B" + r, chFormula_(r)]);
  }
  sh.getRange(2, 1, f.length, 3).setFormulas(f);
  const n = f.length;
  sh.getRange(2, 2, n, 1).setNumberFormat('0.00');
  sh.getRange(2, 4, n, 1).setNumberFormat('0.00');
  sh.getRange(2, 5, n, 1).setNumberFormat('0.0%');
  sh.getRange(2, 6, n, 1).setNumberFormat('0');
  sh.getRange(2, 7, n, 1).setNumberFormat('0.0%');
  sh.getRange(2, 8, n, 1).setNumberFormat('0');
  sh.getRange(2, 9, n, 1).setNumberFormat('0.0%');
  sh.getRange(2, 10, n, 1).setNumberFormat('dd-mmm-yyyy');
  sh.getRange(2, 11, n, 2).setNumberFormat('0.00');
  sh.getRange(2, 13, n, 1).setNumberFormat('0.0%');
  sh.getRange(2, 14, n, 2).setNumberFormat('0.00');
  sh.setConditionalFormatRules(chColorRules_(sh.getRange(2, 3, n, 1)));

  // Filtered, ranked list
  let ls = ss.getSheetByName(CH_LIST) || ss.insertSheet(CH_LIST);
  ls.clear();
  ls.clearConditionalFormatRules();
  ls.getRange(1, 1, 1, CH_HEADERS.length).setValues([CH_HEADERS])
    .setFontWeight('bold').setBackground('#0b3a53').setFontColor('#ffffff').setWrap(true);
  ls.setFrozenRows(1);
  ls.getRange('A2').setFormula(
    "=IFERROR(LET(f,FILTER('" + CH_SHEET + "'!A2:O,'" + CH_SHEET + "'!C2:C<>\"\")," +
    "SORT(f,XMATCH(INDEX(f,0,3),{\"BREAKOUT\";\"READY\";\"BO LOW VOL\";\"HANDLE\";\"EXTENDED\"}),TRUE,INDEX(f,0,5),FALSE)),\"No setups yet\")");
  ls.getRange('B2:B').setNumberFormat('0.00');
  ls.getRange('D2:D').setNumberFormat('0.00');
  ls.getRange('E2:E').setNumberFormat('0.0%');
  ls.getRange('G2:G').setNumberFormat('0.0%');
  ls.getRange('I2:I').setNumberFormat('0.0%');
  ls.getRange('J2:J').setNumberFormat('dd-mmm-yyyy');
  ls.getRange('K2:L').setNumberFormat('0.00');
  ls.getRange('M2:M').setNumberFormat('0.0%');
  ls.getRange('N2:O').setNumberFormat('0.00');
  ls.setConditionalFormatRules(chColorRules_(ls.getRange('C2:C')));
  ls.getRange('Q1').setValue('CUP & HANDLE RULES').setFontWeight('bold');
  ls.getRange('Q2:Q10').setValues([
    ['Weekly close basis. Completed weeks from the weekly series; this week rebuilt from daily bars'],
    ['Prior uptrend: left rim >= 25% above the lowest low of the 52 weeks before it'],
    ['Cup: 7-65 weeks from left rim to right rim, 12-40% deep, >= 3 weeks down and >= 3 weeks up (U, not V)'],
    ['Right rim = highest weekly high of the last 10 weeks, 90-103% of the left rim (highest high of the 65 weeks before it)'],
    ['Handle: right rim to last week, 1-8 weeks, <= 15% deep, low stays in the upper half of the cup'],
    ['Pivot (buy point) = right-rim high'],
    ['BREAKOUT: 0-5% above pivot, this week vol >= 1.4x avg of previous 10 weeks, above 30W MA'],
    ['READY: within 5% below pivot | HANDLE: deeper in handle | EXTENDED: > 5% above pivot'],
    ['Tracker: logged if market OK, liquidity OK, risk to handle low <= 10%. Exits: two-stage (R = pivot, Initial SL = handle low)']]);
  writeRulesV2_(ss); // Rules sheet C&H text, without re-running the v2 upgrade (which resets Settings)
  SpreadsheetApp.getActive().toast('Cup & Handle scanner built for ' + n + ' symbols. Let GOOGLEFINANCE load.', 'C&H', 8);
}

function chColorRules_(rng) {
  const mk = (t, bg, fc) => SpreadsheetApp.newConditionalFormatRule().whenTextEqualTo(t)
    .setBackground(bg).setFontColor(fc).setBold(true).setRanges([rng]).build();
  return [mk('BREAKOUT', '#1e8e3e', '#ffffff'), mk('BO LOW VOL', '#f9ab00', '#000000'),
    mk('READY', '#b7e1cd', '#0b5d1e'), mk('HANDLE', '#fce8b2', '#7a5c00'),
    mk('EXTENDED', '#e0e0e0', '#555555')];
}


// One-time: switch open trades + rules text from 30W MA trail to 2-week-low trail
function switchTo2WeekLowTrail() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sh = ss.getSheetByName(TRACKER);
  sh.getRange(1, 6).setValue('2W Low (Trail)');
  const last = sh.getLastRow();
  for (let r = 2; r <= last; r++) {
    if (!sh.getRange(r, 1).getValue() || sh.getRange(r, 7).getValue() === 'EXIT') continue;
    sh.getRange(r, 6).setFormula(trail2wFormula_(r));
  }
  const fl = ss.getSheetByName('Final List');
  const lastCol = fl.getLastColumn();
  const rng = fl.getRange(1, 1, 60, lastCol);
  const vals = rng.getValues();
  vals.forEach(function (row, i) {
    row.forEach(function (v, j) {
      if (typeof v === 'string' && /trailing/i.test(v) && /30/.test(v)) {
        fl.getRange(i + 1, j + 1).setValue('Trailing exit: weekly close below lowest low of prior 2 weeks');
      }
    });
  });
}

// One-time: add Active SL / SL Dist % to every existing Tracker row
function setupSlColumns() {
  const sh = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(TRACKER);
  ensureSlColumns_(sh);
  for (let r = 2; r <= sh.getLastRow(); r++) {
    if (sh.getRange(r, 1).getValue()) setSlFormulas_(sh, r);
  }
  colorStatus_(sh);
}


/* ================= v2 UPGRADE (one-time) ================= */

// MasterData C:Q from ONE weekly GOOGLEFINANCE call per row (5 yrs of weekly OHLCV)

// Latest daily close (on the weekend = Friday close = the week's close)
function weeklyCloseFormula_(r) {
  return '=IFERROR(LET(d,GOOGLEFINANCE("NSE:"&A' + r + ',"close",TODAY()-10,TODAY(),"DAILY"),INDEX(d,ROWS(d),2)),"")';
}
// v2 trail: 10-week SMA = 9 completed weekly closes + latest daily close (weekly series lags a week)
function ma10Formula_(r) {
  const s = '"NSE:"&A' + r;
  return '=IFERROR(LET(w,GOOGLEFINANCE(' + s + ',"close",TODAY()-120,TODAY(),"WEEKLY"),d,GOOGLEFINANCE(' + s + ',"close",TODAY()-10,TODAY(),"DAILY"),' +
    'ld,INDEX(d,ROWS(d),1),ws,INT(ld)-WEEKDAY(ld,3),wd,CHOOSEROWS(w,SEQUENCE(ROWS(w)-1,1,2)),n,SUM(ARRAYFORMULA(--(INDEX(wd,0,1)<ws))),' +
    '(SUM(CHOOSEROWS(INDEX(wd,0,2),SEQUENCE(9,1,n-8)))+INDEX(d,ROWS(d),2))/10),"")';
}
// v2 volume: this week's volume (sum of daily bars since Monday) / median of previous 10 completed weeks
function wkVolFormula_(r) {
  const s = '"NSE:"&A' + r;
  return '=IFERROR(LET(w,GOOGLEFINANCE(' + s + ',"volume",TODAY()-120,TODAY(),"WEEKLY"),d,GOOGLEFINANCE(' + s + ',"volume",TODAY()-10,TODAY(),"DAILY"),' +
    'dd,CHOOSEROWS(d,SEQUENCE(ROWS(d)-1,1,2)),ld,MAX(INDEX(dd,0,1)),ws,INT(ld)-WEEKDAY(ld,3),wd,CHOOSEROWS(w,SEQUENCE(ROWS(w)-1,1,2)),' +
    'n,SUM(ARRAYFORMULA(--(INDEX(wd,0,1)<ws))),' +
    'SUM(FILTER(INDEX(dd,0,2),ARRAYFORMULA(INDEX(dd,0,1)>=ws)))/MEDIAN(CHOOSEROWS(INDEX(wd,0,2),SEQUENCE(10,1,n-9)))),"")';
}
// MasterData C:Q. Weekly bars = completed-week history; the current week is rebuilt from daily bars
// (GOOGLEFINANCE's weekly series omits the latest week until the following week).
function masterFormulaV2_(r) {
  const s = '"NSE:"&$A' + r;
  return '=IF($A' + r + '="","",IFERROR(LET(raw,GOOGLEFINANCE(' + s + ',"all",TODAY()-5*365,TODAY(),"WEEKLY"),' +
    'w,CHOOSEROWS(raw,SEQUENCE(ROWS(raw)-1,1,2)),draw,GOOGLEFINANCE(' + s + ',"all",TODAY()-14,TODAY(),"DAILY"),' +
    'dd,CHOOSEROWS(draw,SEQUENCE(ROWS(draw)-1,1,2)),ddt,INDEX(dd,0,1),ld,MAX(ddt),ws,INT(ld)-WEEKDAY(ld,3),cmk,ARRAYFORMULA(ddt>=ws),' +
    'wkH,MAX(FILTER(INDEX(dd,0,3),cmk)),wkL,MIN(FILTER(INDEX(dd,0,4),cmk)),wkC,INDEX(dd,ROWS(dd),5),wkV,SUM(FILTER(INDEX(dd,0,6),cmk)),' +
    'wdt,INDEX(w,0,1),n,SUM(ARRAYFORMULA(--(wdt<ws))),' +
    'dt,CHOOSEROWS(wdt,SEQUENCE(n)),hi,CHOOSEROWS(INDEX(w,0,3),SEQUENCE(n)),lo,CHOOSEROWS(INDEX(w,0,4),SEQUENCE(n)),' +
    'cl,CHOOSEROWS(INDEX(w,0,5),SEQUENCE(n)),vo,CHOOSEROWS(INDEX(w,0,6),SEQUENCE(n)),' +
    'm,ARRAYFORMULA(dt<=TODAY()-28),hm,FILTER(hi,m),k,ROWS(hm),res,MAX(hm),ri,XMATCH(res,hm),rd,INT(INDEX(dt,ri)),age,ROUND((TODAY()-rd)/365,1),' +
    'blow,IF(k>ri,MIN(CHOOSEROWS(lo,SEQUENCE(k-ri,1,ri+1))),res),depth,1-blow/res,' +
    'cmp,IF(ISNUMBER($B' + r + '),$B' + r + ',wkC),bo,cmp/res-1,' +
    'vr,wkV/MEDIAN(CHOOSEROWS(vo,SEQUENCE(10,1,n-9))),' +
    'ma_l,(SUM(CHOOSEROWS(cl,SEQUENCE(29,1,n-28)))+wkC)/30,ma_s,(SUM(CHOOSEROWS(cl,SEQUENCE(9,1,n-8)))+wkC)/10,' +
    'cpos,IF(wkH>wkL,(wkC-wkL)/(wkH-wkL),1),' +
    'liq,SUMPRODUCT(CHOOSEROWS(cl,SEQUENCE(4,1,n-3)),CHOOSEROWS(vo,SEQUENCE(4,1,n-3)))/20/10^7,' +
    'sl,MAX(res*0.97,wkL),risk,(cmp-sl)/cmp,mkt,Settings!$B$5=TRUE,' +
    'base,AND(age>=2,depth<=0.6,liq>=Settings!$B$7),core,AND(base,bo>=0,bo<=0.1,vr>=1.5,cpos>=0.67),' +
    'sig,IF(NOT(base),"",IF(bo>0.1,"EXTENDED",IF(core,IF(risk>0.1,"SKIP-RISK",IF(mkt,"BREAKOUT","BLOCKED")),IF(AND(bo>=-0.05,bo<0),"NEAR","")))),' +
    'bkt,IF(age<2,"<2Y",IF(age>=5,"5Y+",IF(age>=4,"4Y",IF(age>=3,"3Y","2Y")))),' +
    'HSTACK(res,rd,age,bo,vr,ma_l,sig,bkt,blow,depth,cpos,liq,sl,risk,ma_s)),HSTACK("","","","","","","CHECK")))';
}

function setupSettings_(ss) {
  let s = ss.getSheetByName(SETTINGS);
  if (!s) s = ss.insertSheet(SETTINGS);
  s.clear();
  const nifty = function (sym, label) {
    return 'LET(w,GOOGLEFINANCE("' + sym + '","close",TODAY()-400,TODAY(),"WEEKLY"),d,GOOGLEFINANCE("' + sym + '","close",TODAY()-10,TODAY(),"DAILY"),' +
      'ld,INDEX(d,ROWS(d),1),ws,INT(ld)-WEEKDAY(ld,3),wd,CHOOSEROWS(w,SEQUENCE(ROWS(w)-1,1,2)),n,SUM(ARRAYFORMULA(--(INDEX(wd,0,1)<ws))),lc,INDEX(d,ROWS(d),2),' +
      'VSTACK(lc,(SUM(CHOOSEROWS(INDEX(wd,0,2),SEQUENCE(39,1,n-38)))+lc)/40,"' + label + '"))';
  };
  s.getRange('A1:C1').setValues([['Setting', 'Value', 'Note']])
    .setFontWeight('bold').setBackground('#0b3a53').setFontColor('#ffffff');
  s.getRange('A2:A10').setValues([['Nifty weekly close'], ['Nifty 40-week SMA'], ['Market data source'],
    ['MARKET OK (new entries allowed)'], ['Capital (Rs)'], ['Min liquidity (Rs Cr/day)'],
    ['Risk per trade'], ['Max open positions'], ['Max per sector (manual check)']]);
  s.getRange('B2').setFormula('=IFERROR(' + nifty('INDEXNSE:NIFTY_50', 'INDEXNSE:NIFTY_50') + ',' +
    nifty('NSE:NIFTYBEES', 'NSE:NIFTYBEES (proxy)') + ')');
  s.getRange('B5').setFormula('=AND(ISNUMBER(B2),ISNUMBER(B3),B2>B3)');
  s.getRange('B6:B10').setValues([[1000000], [5], [0.01], [10], [3]]);
  s.getRange('C2:C10').setValues([['Latest weekly close'], ['No new entries when close is below this'],
    ['Falls back to NIFTYBEES if index history is unavailable'], ['TRUE = BREAKOUT allowed; FALSE = BLOCKED'],
    ['EDIT: your trading capital (used for Qty)'], ['4-week avg daily traded value floor'],
    ['Fraction of capital risked per trade'], ['New breakouts beyond this are not logged'],
    ['No sector data in sheet: check before entry']]);
  s.getRange('B2:B3').setNumberFormat('0.00');
  s.getRange('B6').setNumberFormat('#,##0');
  s.getRange('B8').setNumberFormat('0.0%');
  s.getRange('A5:B5').setFontWeight('bold');
  s.setColumnWidth(1, 240); s.setColumnWidth(2, 160); s.setColumnWidth(3, 340);
  s.setConditionalFormatRules([
    SpreadsheetApp.newConditionalFormatRule().whenFormulaSatisfied('=$B$5=TRUE').setBackground('#b7e1cd').setRanges([s.getRange('B5')]).build(),
    SpreadsheetApp.newConditionalFormatRule().whenFormulaSatisfied('=$B$5=FALSE').setBackground('#f4c7c3').setRanges([s.getRange('B5')]).build()
  ]);
}

function writeRulesV2_(ss) {
  const sh = ss.getSheetByName('Rules') || ss.insertSheet('Rules');
  sh.getRange('A1:I80').clearContent();
  const L = [
    ['MULTI YEAR BREAKOUT - RULES v2 (weekly close basis)'],
    ['FILTERS'],
    ['Market: Nifty 50 weekly close above 40-week SMA (Settings!B5). Otherwise BREAKOUT shows as BLOCKED and is not logged'],
    ['Liquidity: 4-week avg daily traded value >= Settings!B7 (default Rs 5 Cr)'],
    ['Base: Resistance (highest weekly high, 5 yrs ago to 4 wks ago) at least 2 years old'],
    ['Base depth: (R - lowest low since R) / R <= 60%'],
    ['SIGNALS'],
    ['BREAKOUT = filters + CMP 0% to +10% above R + Vol Ratio (this week / median of prev 10 wks) >= 1.5 + close in top 1/3 of week range + risk <= 10% + market OK'],
    ['BLOCKED = BREAKOUT except market filter | SKIP-RISK = BREAKOUT except risk > 10% | EXTENDED = more than 10% above R'],
    ['NEAR = filters + CMP within 5% below R | CHECK = data error, fix symbol'],
    ['ENTRY & SIZE'],
    ['Enter at weekly close of the signal week. Initial SL = MAX(R x 0.97, breakout-week low). Risk % = (Entry - SL) / Entry <= 10%'],
    ['Qty = Capital x 1% / (Entry - Initial SL). Max 10 open positions, max 3 per sector. Check monthly chart before entry'],
    ['EXITS (Tracker, weekly close)'],
    ['Stage 1 (peak < +20%): FAILED-BO = close below R on Vol Ratio >= 1.0 | SL = close below Initial SL'],
    ['Stage 2 (after any close >= +20%): BREAKEVEN = close below MAX(Initial SL, Entry) | TRAIL-10W = close below 10-week SMA'],
    ['CUP & HANDLE (Setup = C&H)'],
    ['Pattern: right rim = highest weekly high of the last 10 weeks (pivot); handle 1-8 wks, <= 15% deep, upper half of cup; left rim = highest high of the 65 wks before; cup 7-65 wks, 12-40% deep, U 3+ wks each side; right rim 90-103% of left; left rim >= 25% above the 52-wk low before it'],
    ['BREAKOUT = 0-5% above pivot, this week vol >= 1.4x avg of previous 10 wks, above 30W MA; logged only if market OK, liquidity OK and risk to handle low <= 10%'],
    ['READY = within 5% below pivot | BO LOW VOL = above pivot, volume weak | HANDLE = deeper in the handle | EXTENDED = more than 5% above pivot'],
    ['Exits: same two-stage rules; R = pivot, Initial SL = handle low']
  ];
  sh.getRange(1, 1, L.length, 1).setValues(L);
  sh.getRange('A1:A80').setFontWeight('normal');
  [1, 2, 7, 11, 14, 17].forEach(function (i) { sh.getRange(i, 1).setFontWeight('bold'); });
}

function upgradeToV2() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  setupSettings_(ss);

  // 1) Backup Tracker as plain values
  const tr = ss.getSheetByName(TRACKER);
  if (tr && !ss.getSheetByName('Tracker_v1_backup')) {
    const v = tr.getDataRange().getValues();
    const b = ss.insertSheet('Tracker_v1_backup');
    b.getRange(1, 1, v.length, v[0].length).setValues(v);
  }

  // 2) MasterData: one GOOGLEFINANCE call per row, spilling C:Q
  const md = ss.getSheetByName(MASTER);
  const last = md.getLastRow();
  if (md.getMaxColumns() < 17) md.insertColumnsAfter(md.getMaxColumns(), 17 - md.getMaxColumns());
  md.getRange(1, 3, md.getMaxRows(), 15).clearContent();
  md.getRange(1, 3, 1, 15).setValues([['Resistance', 'Resistance Date', 'Base (yrs)', 'Breakout %', 'Vol Ratio (med10)',
    '30W MA', 'Signal', 'Base Bucket', 'Base Low', 'Base Depth %', 'Close Pos', 'Liquidity (Cr/day)', 'Initial SL', 'Risk %', '10W MA']]);
  md.getRange('C1').copyFormatToRange(md, 11, 17, 1, 1);
  const f = [];
  for (let r = 2; r <= last; r++) f.push([masterFormulaV2_(r)]);
  md.getRange(2, 3, f.length, 1).setFormulas(f);
  const n = f.length;
  md.getRange(2, 4, n, 1).setNumberFormat('dd-mmm-yyyy');
  md.getRange(2, 5, n, 1).setNumberFormat('0.0');
  md.getRange(2, 6, n, 1).setNumberFormat('0.0%');
  md.getRange(2, 7, n, 2).setNumberFormat('0.00');
  md.getRange(2, 11, n, 1).setNumberFormat('0.00');
  md.getRange(2, 12, n, 1).setNumberFormat('0.0%');
  md.getRange(2, 13, n, 1).setNumberFormat('0.00');
  md.getRange(2, 14, n, 1).setNumberFormat('0.0');
  md.getRange(2, 15, n, 1).setNumberFormat('0.00');
  md.getRange(2, 16, n, 1).setNumberFormat('0.0%');
  md.getRange(2, 17, n, 1).setNumberFormat('0.00');
  const sig = md.getRange(2, 9, n, 1);
  const keep = md.getConditionalFormatRules().filter(function (x) {
    return !x.getRanges().some(function (g) { return g.getColumn() === 9; });
  });
  [['BREAKOUT', '#b7e1cd'], ['NEAR', '#cfe2f3'], ['BLOCKED', '#d9d9d9'], ['SKIP-RISK', '#ead1dc'], ['EXTENDED', '#fff2cc'], ['CHECK', '#ea9999']].forEach(function (x) {
    keep.push(SpreadsheetApp.newConditionalFormatRule().whenTextEqualTo(x[0]).setBackground(x[1]).setBold(true).setRanges([sig]).build());
  });
  md.setConditionalFormatRules(keep);

  // 3) Migrate open Tracker rows to v2 columns
  const sh = getTracker_(ss);
  const lr = sh.getLastRow();
  if (lr > 1) {
    const rows = sh.getRange(2, 1, lr - 1, HEADERS.length).getValues();
    rows.forEach(function (row, i) {
      const r = i + 2;
      if (!String(row[0]).trim() || row[6] === 'EXIT') return;
      const setup = String(row[12]).trim() || 'MYB';
      const entryP = Number(row[2]), R = Number(row[3]), wc = Number(row[4]);
      const initSL = Number(row[15]) > 0 ? Number(row[15]) : (setup === 'C&H' ? R : Math.round(R * 0.97 * 100) / 100);
      const peak = Math.max(entryP, wc > 0 ? wc : 0);
      sh.getRange(r, 5).setFormula(weeklyCloseFormula_(r));
      sh.getRange(r, 6).setFormula(ma10Formula_(r));
      sh.getRange(r, 16, 1, 3).setValues([[initSL, peak, peak >= entryP * 1.2 ? 2 : 1]]);
      sh.getRange(r, 19).setFormula(qtyFormula_(r));
      sh.getRange(r, 20).setFormula(wkVolFormula_(r));
      setSlFormulas_(sh, r);
    });
  }
  colorStatus_(sh);

  // 4) Rules text + Final List
  writeRulesV2_(ss);
  upgradeFinalList_();
  formatFinalList();
  ss.toast('v2 installed. Edit Settings!B6 (capital). Let GOOGLEFINANCE load, then run Update now.', 'Breakout Tracker', 12);
}
