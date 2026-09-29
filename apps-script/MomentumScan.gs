// ===================== MOMENTUM SHARPE SCAN =====================
/**
 * MOMENTUM SCAN — Google Apps Script (live scan + rebalance plan)
 *
 * Same rules as the whole-NSE Momentum Study (study/momentum_nse_study.py). Pick one of its two
 * tested set-ups with PLAN below:
 *   MA50    monthly, top 20, keep while ranked 1-40. Market: no new buys while the Nifty500
 *           Momentum 50 (MOMENTUM50 ETF) closes below its 50-day SMA; sells go on as usual and the
 *           money waits in a liquid fund; on the first close back above, fill the empty slots that
 *           day. Never sells everything. (Higher return, deeper falls.)
 *   SWITCH  weekly, top 30, keep while ranked 1-60. Market: 3 closes in a row with the Nifty 500
 *           below its 200-day SMA = sell everything that day, 100% liquid fund; buy back at the first
 *           weekly rebalance above the SMA. (Smaller falls.)
 *  Universe   whatever symbols you list in MasterData (maintained manually). Stocks in NSE's BE/BZ
 *             (trade-to-trade) series are ranked like any other, as in the study.
 *   Filters    a stock is ranked only if ALL three pass:
 *                1. within 25% of its all-time high      (ATH - close) / ATH < 25%
 *                2. average daily turnover > Rs 1 crore  mean(close x volume) over 252 sessions
 *                3. close above its 233-day SMA
 *   Score      Av Sharpe = average over 252/184/126/63 sessions of
 *              (plain % return over the window) / (STDEV.S of daily returns x sqrt 252).
 *              No risk-free rate. Each window needs 90% price data.
 *   Prices     Yahoo close (split-adjusted, NOT dividend-adjusted), aligned to the Nifty 500
 *              calendar, gaps up to 5 sessions carried forward, one-day moves > 60% ignored.
 *   Portfolio  top N; keep a holding while it ranks 1-KEEP_RANK (failing a filter = not ranked = sell);
 *              refill with sale money split equally; rebalance on the last trading day of the
 *              month (MA50) or week (SWITCH).
 *
 * TABS CREATED:  Rules & How to Use, Momentum Rank, Portfolio, Rebalance Plan, _ScanWork (hidden)
 */

// ------------------------------- SETTINGS ---------------------------------
var PLAN = 'MA50';                  // 'MA50' or 'SWITCH' (see above)
var PLANS = {
  MA50:   { REBALANCE: 'month', TOP_N: 20, KEEP_RANK: 40, MARKET_RULE: 'pause' },
  SWITCH: { REBALANCE: 'week',  TOP_N: 30, KEEP_RANK: 60, MARKET_RULE: 'switch' }
};
var CFG = {
  INDEX_TICKER: '^CRSLDX',          // Nifty 500 on Yahoo (trading calendar; market series for SWITCH)
  MARKET_TICKER: 'NSE:MOMENTUM50',  // MA50 market series: Motilal Oswal Nifty 500 Momentum 50 ETF, via GOOGLEFINANCE
  MARKET_DAYS: 400,                 // calendar days of MOMENTUM50 history to load
  LOOKBACKS: [252, 184, 126, 63],
  MIN_PRESENT: 0.90,                // share of each window that must have data
  BAD_RET: 0.60,
  FFILL_LIMIT: 5,
  PAUSE_SMA: 50,                    // MA50: no new buys while MOMENTUM50 is below this SMA
  SWITCH_SMA: 200,                  // SWITCH: Nifty 500 SMA
  CONFIRM_DAYS: 3,                  // SWITCH: exit after this many closes in a row below the SMA
  STOCK_SMA: 233,                   // trend filter
  TURNOVER_DAYS: 252,
  MIN_TURNOVER: 1e7,                // Rs 1 crore
  MAX_FALL: 0.25,                   // within 25% of all-time high
  COST: 0.0025,
  DAILY_DAYS: 420,                  // calendar days of daily bars per stock (covers the 252-session windows)
  ATH_REFRESH_DAYS: 90,             // re-download a stock's full history for its all-time high this often
  BATCH: 30,                        // stocks per batch (1 Yahoo request each, 2 when the all-time high is refreshed)
  TIME_BUDGET_MS: 4.5 * 60 * 1000,  // stop and resume before the 6-min limit
  TZ: 'Asia/Kolkata'
};
Object.keys(PLANS[PLAN]).forEach(function (k) { CFG[k] = PLANS[PLAN][k]; });
var PAUSE = CFG.MARKET_RULE === 'pause';
var PERIOD = CFG.REBALANCE === 'week' ? 'week' : 'month';

var SH_RULES = 'Rules & How to Use', SH_RANK = 'Momentum Rank', SH_PORT = 'Portfolio', SH_PLAN = 'Rebalance Plan', SH_WORK = '_ScanWork', SH_MKT = 'MarketData';
var SH_ATH = '_AthCache';           // Symbol | all-time high | date it was downloaded (hidden)
var WORK_COLS = 13;                 // results in A:M
var STORE_COL = 21;                 // universe in U:V, index calendar in W:X
var RANK_HDR = 9;                   // Momentum Rank: summary in A1:B7, table header on row 9

function onOpen() {
  SpreadsheetApp.getUi().createMenu('Momentum')
    .addItem('Show rules', 'writeRules')
    .addItem('Run scan now', 'startScan')
    .addItem('Build rebalance plan', 'buildRebalancePlan')
    .addSeparator()
    .addItem('Auto-run scan every weekday 4:30 pm', 'installDailyTrigger')
    .addItem('Stop auto-run', 'removeDailyTrigger')
    .addToUi();
}

// ------------------------------- DATA -------------------------------------

function fetchUniverse_() {
  // Universe source: MasterData (header row has "Symbol"/"Nifty500"/"Nifty750" + "Industry"),
  // You maintain MasterData manually; nothing is hard-coded in the script.
  var ss = SpreadsheetApp.getActive();
  var names = ['MasterData'];
  for (var n = 0; n < names.length; n++) {
    var tab = ss.getSheetByName(names[n]);
    if (!tab || tab.getLastRow() < 2) continue;
    var rows = tab.getDataRange().getValues();
    for (var h = 0; h < Math.min(5, rows.length); h++) {
      var hdr = rows[h].map(function (x) { return String(x).trim().toLowerCase(); });
      var iSym = hdr.indexOf('symbol');
      if (iSym < 0) iSym = hdr.indexOf('nifty500');
      if (iSym < 0) iSym = hdr.indexOf('nifty750');
      var iInd = hdr.indexOf('industry');
      if (iSym < 0) continue;
      var out = [];
      for (var r = h + 1; r < rows.length; r++) {
        var s = String(rows[r][iSym] || '').trim();
        if (!s || s.toUpperCase().indexOf('DUMMY') === 0) continue;
        out.push([s, iInd >= 0 ? rows[r][iInd] : '']);
      }
      if (out.length) return out;
    }
  }
  throw new Error('MasterData is empty: add stock symbols in MasterData column A (from row 3), then run the scan again.');
}


function yahooUrl_(ticker, range, interval) {
  return 'https://query1.finance.yahoo.com/v8/finance/chart/' + encodeURIComponent(ticker) +
         '?range=' + range + '&interval=' + interval;
}

function yahooRequest_(ticker, range, interval) {
  return { url: yahooUrl_(ticker, range, interval), muteHttpExceptions: true, headers: { 'User-Agent': 'Mozilla/5.0' } };
}

/** Recent daily bars with split/bonus events, from DAILY_DAYS ago to now. */
function dailyRequest_(ticker) {
  var now = Math.floor(Date.now() / 1000), from = now - CFG.DAILY_DAYS * 86400;
  return { url: 'https://query1.finance.yahoo.com/v8/finance/chart/' + encodeURIComponent(ticker) +
                '?period1=' + from + '&period2=' + now + '&interval=1d&events=split',
           muteHttpExceptions: true, headers: { 'User-Agent': 'Mozilla/5.0' } };
}

function dateKey_(ts) {
  return Utilities.formatDate(new Date(ts * 1000), CFG.TZ, 'yyyy-MM-dd');
}

function today_() { return Utilities.formatDate(new Date(), CFG.TZ, 'yyyy-MM-dd'); }
function daysBetween_(a, b) { return (new Date(b) - new Date(a)) / 864e5; }

/** Daily chart -> {bars: {dateStr: {c, h, v}}, splits: [{d, ratio}]}. Close/high are split-adjusted,
 *  not dividend-adjusted. ratio = numerator / denominator (a 1:5 face-value split is 5). */
function parseChart_(text) {
  var j = JSON.parse(text), res = j.chart && j.chart.result && j.chart.result[0];
  if (!res || !res.timestamp) return null;
  var q = res.indicators.quote[0], map = {}, splits = [];
  for (var k = 0; k < res.timestamp.length; k++) {
    var c = q.close[k];
    if (c === null || c === undefined || isNaN(c) || !c) continue;
    var h = q.high && q.high[k], v = q.volume && q.volume[k];
    map[dateKey_(res.timestamp[k])] = { c: c, h: h || c, v: v || 0 };
  }
  var ev = res.events && res.events.splits;
  if (ev) Object.keys(ev).forEach(function (key) {
    var s = ev[key];
    if (s.numerator > 0 && s.denominator > 0) splits.push({ d: dateKey_(s.date), ratio: s.numerator / s.denominator });
  });
  return { bars: map, splits: splits };
}

function parseDaily_(text) { var p = parseChart_(text); return p ? p.bars : null; }

/** All-time highs are cached in a hidden tab so each stock's full history is downloaded only every
 *  ATH_REFRESH_DAYS; in between, the cached high (adjusted for later splits) is combined with the recent
 *  daily highs. Returns {symbol: {ath, on}}. */
function loadAthCache_() {
  var sh = SpreadsheetApp.getActive().getSheetByName(SH_ATH), m = {};
  if (!sh || sh.getLastRow() < 2) return m;
  sh.getRange(2, 1, sh.getLastRow() - 1, 3).getValues().forEach(function (r) {
    if (r[0] && Number(r[1]) > 0) m[String(r[0])] = { ath: Number(r[1]), on: String(r[2]) };
  });
  return m;
}

function saveAthCache_(m) {
  var ss = SpreadsheetApp.getActive(), sh = ss.getSheetByName(SH_ATH);
  if (!sh) { sh = ss.insertSheet(SH_ATH); sh.hideSheet(); }
  var rows = Object.keys(m).sort().map(function (k) { return [k, m[k].ath, m[k].on]; });
  sh.clear();
  sh.getRange(1, 1, 1, 3).setValues([['Symbol', 'AllTimeHigh', 'DownloadedOn']]);
  if (rows.length) {
    sh.getRange(2, 1, rows.length, 3).setNumberFormats(rows.map(function () { return ['@', '0.00', '@']; }));
    sh.getRange(2, 1, rows.length, 3).setValues(rows);
  }
}

/** Monthly bars over the full history -> highest high (the all-time high). */
function parseAllTimeHigh_(text) {
  var j = JSON.parse(text), res = j.chart && j.chart.result && j.chart.result[0];
  if (!res || !res.timestamp) return 0;
  var highs = res.indicators.quote[0].high || [], best = 0;
  for (var k = 0; k < highs.length; k++) if (highs[k] && highs[k] > best) best = highs[k];
  return best;
}

function fetchIndex_() {
  var r = UrlFetchApp.fetch(yahooUrl_(CFG.INDEX_TICKER, '2y', '1d'), { muteHttpExceptions: true, headers: { 'User-Agent': 'Mozilla/5.0' } });
  if (r.getResponseCode() !== 200) throw new Error('Nifty 500 download failed: HTTP ' + r.getResponseCode());
  var map = parseDaily_(r.getContentText());
  var dates = Object.keys(map).sort();
  return { dates: dates, closes: dates.map(function (d) { return map[d].c; }) };
}

/** Closes of the market-filter series (Nifty500 Momentum 50 via its ETF), oldest first.
 *  Source: GOOGLEFINANCE on the 'MarketData' tab (created automatically if missing). */
function fetchMarketCloses_() {
  var ss = SpreadsheetApp.getActive();
  var sh = ss.getSheetByName(SH_MKT);
  if (!sh) { sh = ss.insertSheet(SH_MKT); }
  var f = '=GOOGLEFINANCE("' + CFG.MARKET_TICKER + '","close",TODAY()-' + CFG.MARKET_DAYS + ',TODAY())';
  if (sh.getRange('A1').getFormula() !== f) {
    sh.getRange('A:B').clearContent();
    sh.getRange('A1').setFormula(f);
    sh.getRange('D1').setValue('Market filter data for the Momentum scan (' + CFG.MARKET_TICKER + ' daily closes via GOOGLEFINANCE). Written by the script; do not edit.');
  }
  var vals = [];
  for (var t = 0; t < 15; t++) {             // GOOGLEFINANCE can take a few seconds to load
    SpreadsheetApp.flush();
    vals = sh.getRange(2, 1, Math.max(sh.getLastRow() - 1, 1), 2).getValues();
    if (vals.length > CFG.PAUSE_SMA && vals[0][0] instanceof Date) break;
    Utilities.sleep(2000);
  }
  var out = [];
  vals.forEach(function (r) { if (r[0] instanceof Date && typeof r[1] === 'number' && r[1] > 0) out.push(r[1]); });
  if (!out.length) throw new Error('No GOOGLEFINANCE data for ' + CFG.MARKET_TICKER + ' (check the ' + SH_MKT + ' tab)');
  if (out.length < CFG.PAUSE_SMA + 5) throw new Error('Not enough history for the ' + CFG.PAUSE_SMA + '-day SMA on ' + CFG.MARKET_TICKER);
  return out;                                // GOOGLEFINANCE returns oldest first
}

// ------------------------------- SCORING ---------------------------------
/** Aligns a stock to the index calendar and computes its filters and Av Sharpe at the last date.
 *  Mirrors Scanner._features in the site's momentum.py. Returns null if there is no recent price. */
function scoreStock_(bars, cal, athHistory) {
  var n = cal.length, px = new Array(n), real = new Array(n), last = null, gap = 0, ath = athHistory || 0;
  for (var i = 0; i < n; i++) {
    var b = bars[cal[i]];
    if (b) { last = b.c; gap = 0; real[i] = b; ath = Math.max(ath, b.h, b.c); }
    else if (last !== null && gap < CFG.FFILL_LIMIT) gap++;
    else last = null;
    px[i] = last === null ? NaN : last;
  }
  var t = n - 1, cmp = px[t];
  if (isNaN(cmp)) return null;

  var ret = new Array(n); ret[0] = NaN;
  for (i = 1; i < n; i++) {
    var r = px[i] / px[i - 1] - 1;
    ret[i] = (isFinite(r) && Math.abs(r) <= CFG.BAD_RET) ? r : NaN;   // bad data ignored
  }

  // Av Sharpe: plain % return over the window / annualised volatility of daily returns
  var sharpes = [];
  for (var L = 0; L < CFG.LOOKBACKS.length; L++) {
    var N = CFG.LOOKBACKS[L], s = null;
    var past = t - N >= 0 ? px[t - N] : NaN;
    var w = [];
    for (i = Math.max(1, t - N + 1); i <= t; i++) if (!isNaN(ret[i])) w.push(ret[i]);
    if (!isNaN(past) && w.length >= Math.max(2, CFG.MIN_PRESENT * N)) {
      var mean = w.reduce(function (a, x) { return a + x; }, 0) / w.length, ss = 0;
      for (i = 0; i < w.length; i++) ss += (w[i] - mean) * (w[i] - mean);
      var vol = Math.sqrt(ss / (w.length - 1)) * Math.sqrt(252);        // STDEV.S * sqrt(252)
      if (vol > 0) s = (cmp / past - 1) / vol;
    }
    sharpes.push(s);
  }
  var complete = sharpes.every(function (x) { return x !== null && isFinite(x); });
  var av = complete ? sharpes.reduce(function (a, x) { return a + x; }, 0) / sharpes.length : null;

  // Filter 3: SMA of the (carried-forward) closes
  var sma = null;
  if (t - CFG.STOCK_SMA + 1 >= 0) {
    var sum = 0, k = 0;
    for (i = t - CFG.STOCK_SMA + 1; i <= t; i++) if (!isNaN(px[i])) { sum += px[i]; k++; }
    if (k >= CFG.STOCK_SMA * CFG.MIN_PRESENT) sma = sum / k;
  }
  // Filter 2: average daily turnover (close x volume) over days that actually traded
  var turnover = null;
  if (t - CFG.TURNOVER_DAYS + 1 >= 0) {
    var tsum = 0, tk = 0;
    for (i = t - CFG.TURNOVER_DAYS + 1; i <= t; i++) if (real[i]) { tsum += real[i].c * real[i].v; tk++; }
    if (tk >= CFG.TURNOVER_DAYS * CFG.MIN_PRESENT) turnover = tsum / tk;
  }
  // Filter 1: distance from the all-time high
  var fall = ath ? (ath - cmp) / ath : null;

  var failed = [];
  if (!(fall !== null && fall < CFG.MAX_FALL)) failed.push('ATH');
  if (!(turnover !== null && turnover > CFG.MIN_TURNOVER)) failed.push('Turnover');
  if (!(sma !== null && cmp > sma)) failed.push('SMA' + CFG.STOCK_SMA);
  return { close: cmp, s: sharpes, av: av, fall: fall, turnover: turnover, sma: sma, failed: failed };
}

// ------------------------------- SCAN (resumable) -------------------------
function startScan() {
  var ss = SpreadsheetApp.getActive(), props = PropertiesService.getDocumentProperties();
  var uni = fetchUniverse_(), idx = fetchIndex_();
  var work = ss.getSheetByName(SH_WORK) || ss.insertSheet(SH_WORK);
  work.clear(); work.hideSheet();
  work.getRange(1, 1, 1, WORK_COLS).setValues([['Symbol', 'Industry', 'Close', 'S252', 'S184', 'S126', 'S63', 'AvSharpe',
                                                 'FallFromATH', 'TurnoverCr', 'SMA' + CFG.STOCK_SMA, 'Filters', 'Status']]);
  // universe (U:V) and index calendar (W:X) are stored in the work tab (too big for script properties)
  work.getRange(1, STORE_COL, uni.length + idx.dates.length, 3).setNumberFormat('@');
  work.getRange(1, STORE_COL, uni.length, 2).setValues(uni);
  work.getRange(1, STORE_COL + 2, idx.dates.length, 2).setValues(idx.dates.map(function (d, i) { return [d, idx.closes[i]]; }));
  props.setProperties({ pos: '0', outRow: '2', retry: '[]', nUni: String(uni.length), nCal: String(idx.dates.length) });
  setStatus_('Scanning 0 / ' + uni.length + ' …');
  continueScan();
}

function loadState_(work, props) {
  var nU = Number(props.getProperty('nUni')), nC = Number(props.getProperty('nCal'));
  var uni = work.getRange(1, STORE_COL, nU, 2).getValues();
  var calRows = work.getRange(1, STORE_COL + 2, nC, 2).getValues();
  return { uni: uni, cal: calRows.map(function (r) { return String(r[0]); }),
           closes: calRows.map(function (r) { return Number(r[1]); }) };
}

function continueScan() {
  clearTriggers_('continueScan');
  var t0 = Date.now(), props = PropertiesService.getDocumentProperties();
  var work = SpreadsheetApp.getActive().getSheetByName(SH_WORK);
  var st = loadState_(work, props), uni = st.uni, cal = st.cal;
  var pos = Number(props.getProperty('pos')), retry = JSON.parse(props.getProperty('retry') || '[]');
  var cache = loadAthCache_();

  while (pos < uni.length) {
    if (Date.now() - t0 > CFG.TIME_BUDGET_MS) {
      saveAthCache_(cache);
      props.setProperties({ pos: String(pos), retry: JSON.stringify(retry) });
      setStatus_('Scanning ' + pos + ' / ' + uni.length + ' … continuing automatically');
      ScriptApp.newTrigger('continueScan').timeBased().after(60 * 1000).create();
      return;
    }
    var batch = uni.slice(pos, pos + CFG.BATCH);
    processBatch_(batch, cal, work, retry, true, cache);
    pos += batch.length;
  }
  if (retry.length) { Utilities.sleep(5000); processBatch_(retry, cal, work, [], false, cache); }  // one retry for 429s
  saveAthCache_(cache);
  props.setProperties({ pos: String(pos), retry: '[]' });
  finalizeScan_();
}

function processBatch_(batch, cal, work, retry, allowRetry, cache) {
  // One request per stock for recent daily bars; a second (monthly bars over the full history) only when
  // its cached all-time high is missing or older than ATH_REFRESH_DAYS.
  var today = today_(), reqs = [], slot = [];
  batch.forEach(function (b) {
    var c = cache[b[0]], refresh = !c || !(daysBetween_(c.on, today) <= CFG.ATH_REFRESH_DAYS);
    slot.push({ daily: reqs.length, hist: refresh ? reqs.length + 1 : -1 });
    reqs.push(dailyRequest_(b[0] + '.NS'));
    if (refresh) reqs.push(yahooRequest_(b[0] + '.NS', 'max', '1mo'));
  });
  var resps = UrlFetchApp.fetchAll(reqs), rows = [];
  for (var k = 0; k < batch.length; k++) {
    var daily = resps[slot[k].daily], hist = slot[k].hist >= 0 ? resps[slot[k].hist] : null, sym = batch[k][0], ind = batch[k][1];
    var code = daily.getResponseCode(), wcode = hist ? hist.getResponseCode() : 200;
    if ((code === 429 || wcode === 429) && allowRetry) { retry.push(batch[k]); continue; }
    var sc = null, status = 'OK', lastPx = '';
    if (code === 200 && wcode === 200) {
      try {
        var ch = parseChart_(daily.getContentText()), m = ch && ch.bars, ath;
        if (hist) {
          ath = parseAllTimeHigh_(hist.getContentText());
          if (ath > 0) cache[sym] = { ath: ath, on: today };
        } else {
          var since = cache[sym].on;                         // high is on the share basis of this day
          ath = cache[sym].ath;
          (ch ? ch.splits : []).forEach(function (s) {
            if (s.d > since) { ath /= s.ratio; cache[sym].on = ''; }   // split since then: rescale, refresh next run
          });
        }
        sc = m ? scoreStock_(m, cal, ath) : null;
        if (m) { var ks = Object.keys(m).sort(); if (ks.length) lastPx = m[ks[ks.length - 1]].c; }
      }
      catch (e) { status = 'Parse error'; }
      if (!sc && status === 'OK') status = 'No recent price';
      else if (sc && sc.av === null) status = 'Not scored (history/90% rule)';
      else if (sc && sc.failed.length) status = 'Filtered out';
    } else status = 'HTTP ' + code + '/' + wcode;
    rows.push(sc ? [sym, ind, sc.close].concat(sc.s.map(blank_)).concat([
                     blank_(sc.av), blank_(sc.fall), sc.turnover === null ? '' : sc.turnover / 1e7, blank_(sc.sma),
                     sc.failed.length ? 'Fails: ' + sc.failed.join(', ') : 'PASS', status])
                 : [sym, ind, lastPx, '', '', '', '', '', '', '', '', '', status]);   // keep last price so unranked holdings can be valued
  }
  if (rows.length) {
    // results go in A:M; U:X hold the universe/calendar, so getLastRow() can't be used here
    var props = PropertiesService.getDocumentProperties(), next = Number(props.getProperty('outRow') || 2);
    work.getRange(next, 1, rows.length, WORK_COLS).setValues(rows);
    props.setProperty('outRow', String(next + rows.length));
  }
}

function blank_(v) { return v === null || v === undefined || !isFinite(v) ? '' : v; }

function finalizeScan_() {
  var ss = SpreadsheetApp.getActive(), props = PropertiesService.getDocumentProperties();
  var work = ss.getSheetByName(SH_WORK);
  var data = work.getRange(2, 1, Math.max(Number(props.getProperty('outRow')) - 2, 1), WORK_COLS).getValues()
                 .filter(function (r) { return r[0] !== ''; });
  var scored = data.filter(function (r) { return r[7] !== '' && isFinite(r[7]); });
  var ranked = scored.filter(function (r) { return r[11] === 'PASS'; })
                     .sort(function (a, b) { return b[7] - a[7]; });
  var st = loadState_(work, props), cal = st.cal;
  var mk = marketFilter_(PAUSE ? fetchMarketCloses_() : st.closes), asOf = cal[cal.length - 1];
  var series = PAUSE ? 'Nifty500 Momentum 50 (MOMENTUM50)' : 'Nifty 500';

  var sh = ss.getSheetByName(SH_RANK) || ss.insertSheet(SH_RANK);
  sh.clear();
  sh.getRange('A1:B7').setValues([
    ['As of (last close) · plan ' + PLAN, asOf],
    [series + ' close', mk.close],
    [series + ' ' + mk.len + '-day SMA', mk.sma],
    ['Closes in a row below the SMA', mk.streak],
    ['Market filter', mk.label],
    ['Status', 'Done ' + Utilities.formatDate(new Date(), CFG.TZ, 'dd-MMM-yyyy HH:mm')],
    ['Ranked (pass all filters) / scored / universe', ranked.length + ' / ' + scored.length + ' / ' + data.length]
  ]);
  var colour = { 'RISK-ON': '#c8e6c9', 'BUY-OK': '#c8e6c9', FILL: '#a5d6a7', WATCH: '#fff2cc', PAUSE: '#ffe0b2', 'RISK-OFF': '#ffcdd2' };
  sh.getRange('B5').setBackground(colour[mk.state]).setFontWeight('bold');
  // universe size check removed: scan runs on whatever list is in MasterData
  var hdr = [['Rank', 'Symbol', 'Close', 'Av Sharpe', 'Sharpe 252', 'Sharpe 184', 'Sharpe 126', 'Sharpe 63',
              'Below ATH', 'Turnover ₹ Cr', 'SMA' + CFG.STOCK_SMA, 'Industry']];
  var top = RANK_HDR + 1;
  sh.getRange(RANK_HDR, 1, 1, hdr[0].length).setValues(hdr).setFontWeight('bold').setBackground('#00ffff');
  var out = ranked.map(function (r, i) { return [i + 1, r[0], r[2], r[7], r[3], r[4], r[5], r[6], r[8], r[9], r[10], r[1]]; });
  if (out.length) {
    sh.getRange(top, 1, out.length, hdr[0].length).setValues(out);
    sh.getRange(top, 3, out.length, 6).setNumberFormat('0.00');
    sh.getRange(top, 9, out.length, 1).setNumberFormat('0.0%');
    sh.getRange(top, 10, out.length, 2).setNumberFormat('0.00');
    sh.getRange(top, 1, Math.min(CFG.TOP_N, out.length), hdr[0].length).setBackground('#d9ead3');
    if (out.length > CFG.TOP_N)
      sh.getRange(top + CFG.TOP_N, 1, Math.min(CFG.KEEP_RANK, out.length) - CFG.TOP_N, hdr[0].length).setBackground('#fff2cc');
  }
  sh.setFrozenRows(RANK_HDR);
  sh.getRange(RANK_HDR - 1, 4).setValue('Green = top ' + CFG.TOP_N + ' (buy zone)   Yellow = rank ' + (CFG.TOP_N + 1) + '-' + CFG.KEEP_RANK +
    ' (hold zone)   Stocks failing a filter are not ranked (see _ScanWork)');
  writeRules();                     // keep the Rules tab in step with CFG
}

/** Mirrors the backtest's market rule for the chosen plan.
 *  MA50 (buy_gate_ma=50, buy_gate_fill) on MOMENTUM50:
 *    PAUSE     close below the 50-day SMA: no new buys; sells go on as usual, money waits in the liquid fund.
 *    FILL      today is the first close back above the SMA: fill the empty slots today.
 *    BUY-OK    close at or above the SMA.
 *  SWITCH (market_ma=200, market_check="daily", confirm_days=3) on the Nifty 500:
 *    RISK-OFF  CONFIRM_DAYS+ closes in a row below the SMA: sell everything today / stay in the liquid fund.
 *    WATCH     below the SMA for fewer days: keep holdings; if in the liquid fund, don't buy back yet.
 *    RISK-ON   close at or above the SMA. */
function marketFilter_(closes) {
  var n = closes.length, L = PAUSE ? CFG.PAUSE_SMA : CFG.SWITCH_SMA, cum = [0];
  if (n < L + 2) throw new Error('Not enough history for the ' + L + '-day SMA');
  for (var i = 0; i < n; i++) cum.push(cum[i] + closes[i]);
  var smaAt = function (k) { return k >= L - 1 ? (cum[k + 1] - cum[k + 1 - L]) / L : NaN; };
  var streak = 0;
  for (i = n - 1; i >= L - 1 && closes[i] < smaAt(i); i--) streak++;
  var state, label;
  if (PAUSE) {
    var crossed = streak === 0 && closes[n - 2] < smaAt(n - 2);
    state = streak > 0 ? 'PAUSE' : crossed ? 'FILL' : 'BUY-OK';
    label = state === 'PAUSE' ? 'PAUSE: below its ' + L + '-day SMA ' + streak + ' day(s): no new buys, sells as usual'
          : state === 'FILL' ? 'FILL: closed back above its ' + L + '-day SMA today: fill empty slots today'
          : 'BUY-OK: above its ' + L + '-day SMA';
  } else {
    state = streak >= CFG.CONFIRM_DAYS ? 'RISK-OFF' : streak > 0 ? 'WATCH' : 'RISK-ON';
    label = state === 'RISK-OFF' ? 'RISK-OFF: sell all today, 100% liquid fund'
          : state === 'WATCH' ? 'WATCH: below SMA ' + streak + ' day(s), exit after ' + CFG.CONFIRM_DAYS + ' in a row'
          : 'RISK-ON: invest';
  }
  return { close: closes[n - 1], sma: smaAt(n - 1), len: L, streak: streak, state: state, label: label };
}

// ------------------------------- REBALANCE PLAN ---------------------------
function buildRebalancePlan() {
  var ss = SpreadsheetApp.getActive(), ui = SpreadsheetApp.getUi();
  var rk = ss.getSheetByName(SH_RANK);
  if (!rk) { ui.alert('Run the scan first.'); return; }
  var port = ss.getSheetByName(SH_PORT);
  if (!port) {
    port = ss.insertSheet(SH_PORT);
    port.getRange('A1:C1').setValues([['Symbol', 'Shares', 'Note']]).setFontWeight('bold');
    port.getRange('E1:F1').setValues([['Liquid fund value (₹)', '']]);
    ui.alert('Portfolio tab created. List your current stock holdings (Symbol, Shares) and liquid-fund value, then run this again.');
    return;
  }
  var market = String(rk.getRange('B5').getValue()).split(':')[0];
  var states = PAUSE ? ['BUY-OK', 'FILL', 'PAUSE'] : ['RISK-ON', 'WATCH', 'RISK-OFF'];
  if (states.indexOf(market) < 0) { ui.alert('Run the scan again (the plan or the Momentum Rank layout changed).'); return; }
  var rows = rk.getRange(RANK_HDR + 1, 1, Math.max(rk.getLastRow() - RANK_HDR, 1), 3).getValues().filter(function (r) { return r[1]; });
  var rank = {}, price = {}, why = {};
  var work = ss.getSheetByName(SH_WORK);
  if (work && work.getLastRow() > 1)
    work.getRange(2, 1, work.getLastRow() - 1, WORK_COLS).getValues().forEach(function (r) {
      if (!r[0]) return;
      if (r[2] !== '') price[r[0]] = r[2];
      why[r[0]] = r[11] && r[11] !== 'PASS' ? r[11] : r[12];
    });
  rows.forEach(function (r) { rank[r[1]] = r[0]; price[r[1]] = r[2]; });

  var hold = port.getRange(2, 1, Math.max(port.getLastRow() - 1, 1), 2).getValues()
    .filter(function (r) { return String(r[0]).trim(); })
    .map(function (r) { return { sym: String(r[0]).trim().toUpperCase(), sh: Number(r[1]) || 0 }; });
  var liquid = Number(port.getRange('F1').getValue()) || 0;

  var plan = [], note;
  var notHeld = function (r) { return !hold.some(function (h) { return h.sym === r[1]; }); };
  var buyRows = function (list, money) {
    var per = list.length && money ? money / list.length / (1 + CFG.COST) : 0;
    list.forEach(function (r) {
      plan.push(['BUY', r[1], per ? Math.floor(per / r[2]) : '', r[2], r[0], per ? 'Amount ≈ ₹' + Math.round(per) : 'Split the money equally']);
    });
  };
  if (market === 'RISK-OFF') {
    note = 'Nifty 500 closed below its ' + CFG.SWITCH_SMA + '-day SMA ' + CFG.CONFIRM_DAYS + '+ days in a row: ' +
           (hold.length ? 'SELL ALL today (any day), move 100% to liquid fund.' : 'stay in the liquid fund.');
    hold.forEach(function (h) { plan.push(['SELL', h.sym, h.sh, price[h.sym] || '', rank[h.sym] || 'Not ranked', 'Market filter']); });
  } else if (!hold.length && (market === 'WATCH' || market === 'PAUSE')) {
    note = market === 'PAUSE'
      ? 'In the liquid fund and the Nifty500 Momentum 50 is below its ' + CFG.PAUSE_SMA + '-day SMA: do nothing. Buy the top ' + CFG.TOP_N +
        ' on the first day it closes back above (the scan shows FILL).'
      : 'In the liquid fund and the Nifty 500 is below its ' + CFG.SWITCH_SMA + '-day SMA: do nothing. Buy back only at a ' + PERIOD + '-end above the SMA.';
  } else if (!hold.length) {
    note = 'Portfolio is in liquid fund / fresh start: BUY top ' + CFG.TOP_N + ' in equal amounts.';
    buyRows(rows.slice(0, CFG.TOP_N), liquid);
  } else if (market === 'FILL') {
    // first close back above the SMA: fill the empty slots with the liquid fund today; no sells until the rebalance day
    var empty = Math.max(0, CFG.TOP_N - hold.length);
    note = 'Nifty500 Momentum 50 closed back above its ' + CFG.PAUSE_SMA + '-day SMA today: ' +
           (empty ? 'fill the ' + empty + ' empty slot(s) today with the liquid fund, split equally. Keep everything else until the ' + PERIOD + '-end rebalance.'
                  : 'no empty slots, nothing to buy. Rebalance as usual at ' + PERIOD + '-end.');
    hold.forEach(function (h) { plan.push(['KEEP', h.sym, h.sh, price[h.sym] || '', rank[h.sym] || 'Not ranked', '']); });
    buyRows(rows.filter(notHeld).slice(0, empty), liquid);
  } else {
    note = (market === 'WATCH' ? 'Nifty 500 below its SMA for fewer than ' + CFG.CONFIRM_DAYS + ' days: not an exit, rebalance as usual. ' : '') +
           (market === 'PAUSE' ? 'Nifty500 Momentum 50 is below its ' + CFG.PAUSE_SMA + '-day SMA: sell as usual but BUY NOTHING; the sale money goes to the liquid fund. ' : '') +
           'Invested: keep ranks 1-' + CFG.KEEP_RANK + ', sell the rest (including stocks that fail a filter)' +
           (market === 'PAUSE' ? '.' : ', refill to ' + CFG.TOP_N + ' with the sale proceeds plus any liquid fund, split equally.') +
           ' Kept holdings are NOT resized.';
    var kept = [], proceeds = 0;
    hold.forEach(function (h) {
      var r = rank[h.sym];
      if (r && r <= CFG.KEEP_RANK) { kept.push(h.sym); plan.push(['KEEP', h.sym, h.sh, price[h.sym], r, '']); }
      else {
        var p = price[h.sym] || '';
        if (p) proceeds += h.sh * p * (1 - CFG.COST);
        plan.push(['SELL', h.sym, h.sh, p, r || 'Not ranked',
                   (r ? 'Rank > ' + CFG.KEEP_RANK : 'Not ranked' + (why[h.sym] ? ' (' + why[h.sym] + ')' : '')) +
                   (p ? '' : ' — no price found, add its sale value to the buy amounts')]);
      }
    });
    if (market !== 'PAUSE') buyRows(rows.filter(notHeld).slice(0, CFG.TOP_N - kept.length), proceeds + liquid);
  }
  var sh = ss.getSheetByName(SH_PLAN) || ss.insertSheet(SH_PLAN);
  sh.clear();
  sh.getRange('A1').setValue('Rebalance plan — ' + rk.getRange('B1').getDisplayValue()).setFontWeight('bold');
  sh.getRange('A2').setValue(note);
  sh.getRange('A3').setValue(market === 'RISK-OFF' ? 'Market exit: execute today, at the close. Costs assumed 0.25% per trade.'
    : market === 'FILL' ? 'Fill day: place the buys today, at the close. Costs assumed 0.25% per trade.'
    : 'Execute only on the last trading day of the ' + PERIOD + ', at the close. Costs assumed 0.25% per trade.');
  sh.getRange(5, 1, 1, 6).setValues([['Action', 'Symbol', 'Shares', 'Price', 'Rank', 'Note']]).setFontWeight('bold').setBackground('#00ffff');
  if (plan.length) sh.getRange(6, 1, plan.length, 6).setValues(plan);
  sh.activate();
}

// ------------------------------- RULES ------------------------------------
/** Momentum menu -> Show rules. Writes the strategy rules (from CFG) to the Rules tab.
 *  These are the Momentum Study base-case rules; change them only together with the backtest. */
function writeRules() {
  var ss = SpreadsheetApp.getActive(), sh = ss.getSheetByName(SH_RULES) || ss.insertSheet(SH_RULES, 0);
  var pct = function (x) { return Math.round(x * 1000) / 10 + '%'; };
  var rows = [], sections = [];
  var sec = function (t) { sections.push(rows.length + 1); rows.push([t, '']); };
  var add = function (a, b) { rows.push([a, b]); };

  rows.push(['Momentum Sharpe Scan — Rules & How to Use',
    'Written by the script from its settings (CFG) on ' + Utilities.formatDate(new Date(), CFG.TZ, 'dd-MMM-yyyy HH:mm') +
    '. Rewritten after every scan, so edit the script, not this tab.']);

  sec('STRATEGY RULES');
  add('Plan', PLAN + ': ' + (PAUSE
    ? 'monthly, top ' + CFG.TOP_N + ', with the ' + CFG.PAUSE_SMA + '-day rule on the Nifty500 Momentum 50. In the whole-NSE backtest (2016-2026) the higher-return set-up, with deeper falls.'
    : 'weekly, top ' + CFG.TOP_N + ', with the ' + CFG.SWITCH_SMA + '-day switch on the Nifty 500. In the whole-NSE backtest (2016-2026) the set-up with the smallest falls.') +
    ' To change, set PLAN at the top of the script to ' + (PAUSE ? "'SWITCH'" : "'MA50'") + '.');
  add('Universe', 'Every symbol in MasterData column A (from row 3), whatever the list size, including stocks in NSE\'s BE/BZ (trade-to-trade, delivery-only) series. ' +
    (PAUSE ? 'The market rule uses the Nifty500 Momentum 50 index (via the MOMENTUM50 ETF, GOOGLEFINANCE on the MarketData tab); the Nifty 500 is the trading calendar.'
           : 'The Nifty 500 is the trading calendar and the market series.'));
  add('Filter 1: near high', 'Close within ' + pct(CFG.MAX_FALL) + ' of the all-time high.');
  add('Filter 2: trend', 'Close above its ' + CFG.STOCK_SMA + '-day simple moving average.');
  add('Filter 3: liquidity', 'Average daily turnover (close × volume) over the last ' + CFG.TURNOVER_DAYS + ' sessions above ₹' + CFG.MIN_TURNOVER / 1e7 + ' crore.');
  add('Score', 'Av Sharpe = average over ' + CFG.LOOKBACKS.join('/') + ' sessions of (% return over the window) ÷ (daily-return standard deviation × √252). ' +
    'No risk-free rate. Each window needs ' + pct(CFG.MIN_PRESENT) + ' price data. A stock that fails any filter is not ranked (so it is sold if held).');
  add('Fresh entry', 'Buy the top ' + CFG.TOP_N + ' by Av Sharpe in equal amounts.');
  add('When invested', 'At each ' + PERIOD + '-end keep holdings ranked 1–' + CFG.KEEP_RANK + '. Sell holdings ranked below ' + CFG.KEEP_RANK + ' or not ranked. ' +
    'Refill to ' + CFG.TOP_N + ' with the best-ranked stocks not already held, splitting the sale money (and any liquid fund) equally. Kept holdings are not resized.');
  add('Rebalance day', 'Last trading day of the ' + PERIOD + ', at the close.');
  if (PAUSE) {
    add('Market rule', 'Checked every day on the Nifty500 Momentum 50 and its ' + CFG.PAUSE_SMA + '-day SMA. There is no sell-everything exit.');
    add('PAUSE (below the SMA)', 'No new buys. Holdings are still sold at the ' + PERIOD + '-end when they drop below rank ' + CFG.KEEP_RANK +
      ' or fail a filter; that money waits in the liquid fund. A fresh start waits too.');
    add('FILL (first close back above)', 'That same day, fill every empty slot with the best-ranked stocks not held, splitting the liquid fund equally. No sells that day. ' +
      'If it is also the ' + PERIOD + '-end, do the normal rebalance instead.');
    add('BUY-OK (above the SMA)', 'Normal: rebalance at the ' + PERIOD + '-end.');
  } else {
    add('Market exit', 'Checked every day: if the Nifty 500 closes below its ' + CFG.SWITCH_SMA + '-day SMA ' + CFG.CONFIRM_DAYS +
      ' days in a row (RISK-OFF), sell everything that day and move 100% to a liquid fund.');
    add('Below SMA < ' + CFG.CONFIRM_DAYS + ' days', 'WATCH: not an exit. If invested, rebalance as usual at the ' + PERIOD + '-end. If in the liquid fund, stay there.');
    add('Market re-entry', 'Stay in the liquid fund until a ' + PERIOD + '-end close at or above the ' + CFG.SWITCH_SMA + '-day SMA, then buy the top ' + CFG.TOP_N + '.');
  }
  add('BE/BZ stocks', 'Trade for delivery only and often have 5% or 2% circuit limits. At a locked upper circuit a buy order may not fill: skip it and buy the next-ranked stock.');
  add('Costs', pct(CFG.COST) + ' per buy and per sell (backtest and rebalance plan).');
  add('Prices', 'Yahoo daily close (split-adjusted, not dividend-adjusted) on the Nifty 500 calendar; gaps up to ' + CFG.FFILL_LIMIT +
    ' sessions carried forward; one-day moves over ' + pct(CFG.BAD_RET) + ' ignored.');

  sec('HOW TO USE');
  add('Step 1 · Update MasterData', 'You maintain the stock list yourself: put NSE symbols in MasterData column A (from row 3), industry optional in column B. ' +
    'Add or remove stocks whenever you like (e.g. after index revisions); the next scan uses the list as it is.');
  add('Step 2 · Run the scan', 'Momentum menu → Run scan now. It works in batches of ' + CFG.BATCH + ' stocks and resumes itself every few minutes; ' +
    'wait until Status (Momentum Rank B6) shows Done.');
  add('Step 3 · Check market filter', PAUSE
    ? 'Momentum Rank B1:B5: date, Nifty500 Momentum 50 (MOMENTUM50 ETF) close, its ' + CFG.PAUSE_SMA + '-day SMA, closes in a row below it, and the rule ' +
      '(BUY-OK / PAUSE / FILL). FILL is acted on the same day; the rest only at the ' + PERIOD + '-end.'
    : 'Momentum Rank B1:B5: date, Nifty 500 close, its ' + CFG.SWITCH_SMA + '-day SMA, closes in a row below it, and the filter ' +
      '(RISK-ON / WATCH / RISK-OFF). RISK-OFF is acted on the same day; the rest only at the ' + PERIOD + '-end.');
  add('Step 4 · Read the ranking', 'Table starts at row ' + RANK_HDR + '. Green = rank 1–' + CFG.TOP_N + ' (buy zone). Yellow = rank ' + (CFG.TOP_N + 1) + '–' + CFG.KEEP_RANK +
    ' (hold zone). Below ' + CFG.KEEP_RANK + ' = sell if held. Stocks failing a filter are not listed; the reason is in _ScanWork column L.');
  add('Step 5 · Rebalance', 'Fill Portfolio (Symbol, Shares from row 2; liquid fund value in F1). On the last trading day of the ' + PERIOD + ' (or the day ' + (PAUSE ? 'FILL' : 'RISK-OFF') + ' appears): ' +
    'Momentum menu → Build rebalance plan, then place the BUY / SELL orders at the close.');
  add('Auto-run', 'Momentum menu → Auto-run scan every weekday 4:30 pm (skips weekends). To stop: Momentum menu → Stop auto-run.');
  add('Changing settings', 'All settings (top ' + CFG.TOP_N + ', hold rank ' + CFG.KEEP_RANK + ', filters, Sharpe windows, market SMA, cost) are in the CFG block at the top of the Apps Script. ' +
    'Change them only together with the backtest. The Parameters tab is not read by the current script.');

  sec('SHEETS IN THIS FILE');
  add(SH_RULES, 'This page. Written by the script (Momentum → Show rules, and after every scan).');
  add('MasterData', 'Input: NSE symbol (column A) and industry (column B) from row 3. The scan reads its universe from here.');
  add(SH_RANK, 'Output of the scan: summary in rows 1–7, ranked table from row ' + RANK_HDR + '. Overwritten on every run.');
  add(SH_PORT, 'Input: current holdings (Symbol, Shares from row 2) and liquid fund value in F1. Used by Build rebalance plan.');
  add(SH_PLAN, 'Output of Build rebalance plan: BUY / SELL / KEEP orders. Overwritten each time.');
  add(SH_WORK, 'Hidden working sheet (per-stock results, filter reasons, universe and index calendar). Do not delete.');
  add(SH_ATH, 'Hidden cache of each stock\'s all-time high, re-downloaded every ' + CFG.ATH_REFRESH_DAYS + ' days (sooner after a split). ' +
    'Safe to delete: the next scan rebuilds it, just more slowly.');
  add('Parameters', 'Not used by the current script (left from an older version).');
  add('Note', 'For education and research only. Not investment advice.');

  sh.clear();
  sh.getRange(1, 1, rows.length, 2).setValues(rows).setWrap(true).setVerticalAlignment('top');
  sh.getRange(2, 1, rows.length - 1, 1).setFontWeight('bold');
  sh.getRange(1, 1).setFontWeight('bold').setFontSize(13);
  sh.getRange(1, 2).setFontStyle('italic').setFontColor('#666666');
  sections.forEach(function (r) { sh.getRange(r, 1, 1, 2).setFontWeight('bold').setBackground('#00ffff'); });
  sh.setColumnWidth(1, 210); sh.setColumnWidth(2, 760);
  sh.setFrozenRows(1);
}

// ------------------------------- HELPERS ----------------------------------
function setStatus_(msg) {
  var ss = SpreadsheetApp.getActive(), sh = ss.getSheetByName(SH_RANK) || ss.insertSheet(SH_RANK);
  sh.getRange('A6:B6').setValues([['Status', msg]]);
}
function clearTriggers_(fn) {
  ScriptApp.getProjectTriggers().forEach(function (t) { if (t.getHandlerFunction() === fn) ScriptApp.deleteTrigger(t); });
}
function installDailyTrigger() {
  clearTriggers_('dailyScan');
  ScriptApp.newTrigger('dailyScan').timeBased().everyDays(1).atHour(16).nearMinute(30).inTimezone(CFG.TZ).create();
  SpreadsheetApp.getUi().alert('Scan will run every day around 4:30 pm IST (skips weekends).');
}
function removeDailyTrigger() { clearTriggers_('dailyScan'); clearTriggers_('continueScan'); }
function dailyScan() {
  var d = Number(Utilities.formatDate(new Date(), CFG.TZ, 'u'));   // 6 = Sat, 7 = Sun
  if (d >= 6) return;
  startScan();
}

