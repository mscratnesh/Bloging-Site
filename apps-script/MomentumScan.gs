// ===================== MOMENTUM SHARPE SCAN =====================
/**
 * MOMENTUM SCAN — Google Apps Script (live scan + month-end rebalance plan)
 *
 * Same rules as the Momentum Study base case (study/momentum_study.py, Params / BASE):
 *   Universe   today's Nifty 500 list from MasterData (the backtest uses the list in force each month).
 *   Filters    a stock is ranked only if ALL three pass:
 *                1. within 25% of its all-time high      (ATH - close) / ATH < 25%
 *                2. average daily turnover > Rs 1 crore  mean(close x volume) over 252 sessions
 *                3. close above its 233-day SMA
 *   Score      Av Sharpe = average over 252/184/126/63 sessions of
 *              (plain % return over the window) / (STDEV.S of daily returns x sqrt 252).
 *              No risk-free rate. Each window needs 90% price data.
 *   Prices     Yahoo close (split-adjusted, NOT dividend-adjusted), aligned to the Nifty 500
 *              calendar, gaps up to 5 sessions carried forward, one-day moves > 60% ignored.
 *   Portfolio  top 10; keep a holding while it ranks 1-30 (failing a filter = not ranked = sell);
 *              refill with sale money split equally; rebalance on the last trading day of the month.
 *   Market     checked every day: 3 closes in a row with the Nifty 500 below its 200-day SMA = sell
 *              everything that day, 100% liquid fund. Buy back only at a month-end above the SMA.
 *
 * TABS CREATED:  Rules, Momentum Rank, Portfolio, Rebalance Plan, _ScanWork (hidden)
 */

// ------------------------------- SETTINGS ---------------------------------
var CFG = {
  INDEX_TICKER: '^CRSLDX',          // Nifty 500 on Yahoo
  LOOKBACKS: [252, 184, 126, 63],
  MIN_PRESENT: 0.90,                // share of each window that must have data
  BAD_RET: 0.60,
  FFILL_LIMIT: 5,
  SMA_LEN: 200,                     // market filter (Nifty 500)
  CONFIRM_DAYS: 3,                  // exit after this many closes in a row below the SMA
  STOCK_SMA: 233,                   // trend filter
  TURNOVER_DAYS: 252,
  MIN_TURNOVER: 1e7,                // Rs 1 crore
  MAX_FALL: 0.25,                   // within 25% of all-time high
  TOP_N: 10,
  KEEP_RANK: 30,
  COST: 0.0025,
  BATCH: 20,                        // stocks per batch (2 Yahoo requests each)
  TIME_BUDGET_MS: 4.5 * 60 * 1000,  // stop and resume before the 6-min limit
  TZ: 'Asia/Kolkata'
};

var SH_RULES = 'Rules', SH_RANK = 'Momentum Rank', SH_PORT = 'Portfolio', SH_PLAN = 'Rebalance Plan', SH_WORK = '_ScanWork';
var WORK_COLS = 13;                 // results in A:M
var STORE_COL = 21;                 // universe in U:V, index calendar in W:X
var RANK_HDR = 9;                   // Momentum Rank: summary in A1:B7, table header on row 9

function onOpen() {
  SpreadsheetApp.getUi().createMenu('Momentum')
    .addItem('Show rules', 'writeRules')
    .addItem('Update universe (upload NSE CSV)', 'updateUniverseFromNSE')
    .addItem('Run scan now', 'startScan')
    .addItem('Build rebalance plan', 'buildRebalancePlan')
    .addSeparator()
    .addItem('Auto-run scan every weekday 4:30 pm', 'installDailyTrigger')
    .addItem('Stop auto-run', 'removeDailyTrigger')
    .addToUi();
}

// ------------------------------- DATA -------------------------------------
// Nifty 500 constituents from niftyindices.com, downloaded 24-Sep-2026 (DUMMY rows removed).
// Used only if MasterData and Universe tabs are both missing.
var UNIVERSE_AS_OF = '24-Sep-2026';
var UNIVERSE_INDUSTRIES = ["Financial Services","Diversified","Capital Goods","Construction Materials","Power","Automobile and Auto Components","Fast Moving Consumer Goods","Healthcare","Chemicals","Metals & Mining","Services","Oil Gas & Consumable Fuels","Consumer Services","Realty","Construction","Information Technology","Textiles","Consumer Durables","Telecommunication","Utilities","Forest Materials","Media Entertainment & Publication"];
var UNIVERSE_LIST = '360ONE:0 3MINDIA:1 AADHARHFC:0 AARTIIND:8 AAVAS:0 ABB:2 ABBOTINDIA:7 ABCAPITAL:0 ABDL:6 ABFRL:12 ABLBL:12 ABREL:13 ABSLAMC:0 ACC:3 ACE:2 ACMESOLAR:4 ACUTAAS:7 ADANIENSOL:4 ADANIENT:9 ADANIGREEN:4 ADANIPORTS:10 ADANIPOWER:4 AEGISLOG:11 AEGISVOPAK:11 AFCONS:14 AFFLE:15 AIAENG:2 AIIL:0 AJANTPHARM:7 ALKEM:7 AMBER:17 AMBUJACEM:3 ANANDRATHI:0 ANANTRAJ:13 ANGELONE:0 ANTHEM:7 ANURAS:8 APARINDS:2 APLAPOLLO:2 APOLLOHOSP:7 APOLLOTYRE:5 APTUS:0 ARE&M:5 ASAHIINDIA:5 ASHOKLEY:2 ASIANPAINT:17 ASTERDM:7 ASTRAL:2 ATGL:11 ATHERENERG:5 ATUL:8 AUBANK:0 AUROPHARMA:7 AWL:6 AXISBANK:0 BAJAJ-AUTO:5 BAJAJFINSV:0 BAJAJHFL:0 BAJAJHLDNG:0 BAJFINANCE:0 BALKRISIND:5 BALRAMCHIN:6 BANDHANBNK:0 BANKBARODA:0 BANKINDIA:0 BATAINDIA:17 BAYERCROP:8 BBTC:6 BDL:2 BEL:2 BELRISE:5 BEML:2 BERGEPAINT:17 BHARATFORG:5 BHARTIARTL:18 BHARTIHEXA:18 BHEL:2 BIKAJI:6 BIOCON:7 BLS:12 BLUEDART:10 BLUEJET:7 BLUESTARCO:17 BOSCHLTD:5 BPCL:11 BRIGADE:13 BRITANNIA:6 BSE:0 BSOFT:15 CAMS:0 CANBK:0 CANFINHOME:0 CANHLIFE:0 CAPLIPOINT:7 CARBORUNIV:2 CARTRADE:12 CASTROLIND:11 CCL:6 CDSL:0 CEATLTD:5 CEMPRO:14 CENTRALBK:0 CESC:4 CGCL:0 CGPOWER:2 CHALET:12 CHAMBLFERT:8 CHENNPETRO:11 CHOICEIN:0 CHOLAFIN:0 CHOLAHLDNG:0 CIEINDIA:5 CIPLA:7 CLEAN:8 COALINDIA:11 COCHINSHIP:2 COFORGE:15 COHANCE:7 COLPAL:6 CONCOR:10 CONCORDBIO:7 COROMANDEL:8 CPPLUS:2 CRAFTSMAN:5 CREDITACC:0 CRISIL:0 CROMPTON:17 CUB:0 CUMMINSIND:2 CYIENT:15 DABUR:6 DALBHARAT:3 DATAPATTNS:2 DCMSHRIRAM:1 DEEPAKFERT:8 DEEPAKNTR:8 DELHIVERY:10 DEVYANI:12 DIVISLAB:7 DIXON:17 DLF:13 DMART:12 DOMS:6 DRREDDY:7 ECLERX:10 EICHERMOT:5 EIDPARRY:6 EIHOTEL:12 ELECON:2 ELGIEQUIP:2 EMAMILTD:6 EMCURE:7 EMMVEE:2 ENDURANCE:5 ENGINERSIN:14 ENRIN:2 ERIS:7 ESCORTS:2 ETERNAL:12 EXIDEIND:5 FACT:8 FEDERALBNK:0 FINCABLES:2 FIRSTCRY:12 FIVESTAR:0 FLUOROCHEM:8 FORCEMOT:5 FORTIS:7 FSL:10 GABRIEL:5 GAIL:11 GALLANTT:2 GESHIP:10 GICRE:0 GILLETTE:6 GLAND:7 GLAXO:7 GLENMARK:7 GMDCLTD:9 GMRAIRPORT:10 GODFRYPHLP:6 GODIGIT:0 GODREJCP:6 GODREJIND:1 GODREJPROP:13 GPIL:2 GRANULES:7 GRAPHITE:2 GRASIM:3 GRAVITA:9 GROWW:0 GRSE:2 GVT&D:2 HAL:2 HAVELLS:17 HBLENGINE:2 HCLTECH:15 HDBFS:0 HDFCAMC:0 HDFCBANK:0 HDFCLIFE:0 HEGAM:2 HEROMOTOCO:5 HEXT:15 HFCL:18 HINDALCO:9 HINDCOPPER:9 HINDPETRO:11 HINDUNILVR:6 HINDZINC:9 HOMEFIRST:0 HONASA:6 HONAUT:2 HSCL:8 HUDCO:0 HYUNDAI:5 ICICIAMC:0 ICICIBANK:0 ICICIGI:0 ICICIPRULI:0 IDBI:0 IDEA:18 IDFCFIRSTB:0 IEX:0 IFCI:0 IGIL:10 IGL:11 IIFL:0 IKS:15 INDGN:7 INDHOTEL:12 INDIACEM:3 INDIAMART:12 INDIANB:0 INDIGO:10 INDUSINDBK:0 INDUSTOWER:18 INFY:15 INOXWIND:2 INTELLECT:15 IOB:0 IOC:11 IPCALAB:7 IRB:14 IRCON:14 IRCTC:12 IREDA:0 IRFC:0 ITC:6 ITCHOTELS:12 ITI:18 J&KBANK:0 JAINREC:9 JBMA:5 JINDALSAW:2 JINDALSTEL:9 JIOFIN:0 JKCEMENT:3 JKTYRE:5 JMFINANCIL:0 JPPOWER:4 JSL:9 JSWCEMENT:3 JSWDULUX:17 JSWENERGY:4 JSWINFRA:10 JSWSTEEL:9 JUBLFOOD:12 JUBLINGREA:8 JUBLPHARMA:7 JWL:2 JYOTICNC:2 KAJARIACER:17 KALYANKJIL:17 KARURVYSYA:0 KAYNES:2 KEC:14 KEI:2 KFINTECH:0 KIMS:7 KIRLOSENG:2 KOTAKBANK:0 KPIL:14 KPITTECH:15 KPRMILL:16 LALPATHLAB:7 LATENTVIEW:15 LAURUSLABS:7 LEMONTREE:12 LENSKART:12 LGEINDIA:17 LICHSGFIN:0 LICI:0 LINDEINDIA:8 LLOYDSME:9 LODHA:13 LT:14 LTF:0 LTFOODS:6 LTM:15 LTTS:15 LUPIN:7 M&M:5 M&MFIN:0 MAHABANK:0 MANAPPURAM:0 MANKIND:7 MAPMYINDIA:15 MARICO:6 MARUTI:5 MAXHEALTH:7 MAZDOCK:2 MCX:0 MEDANTA:7 MEESHO:12 MFSL:0 MGL:11 MINDACORP:5 MMTC:10 MOTHERSON:5 MOTILALOFS:0 MPHASIS:15 MRF:5 MRPL:11 MSUMI:5 MUTHOOTFIN:0 NAM-INDIA:0 NATCOPHARM:7 NATIONALUM:9 NAUKRI:12 NAVA:4 NAVINFLUOR:8 NBCC:14 NCC:14 NESTLEIND:6 NETWEB:15 NEULANDLAB:7 NEWGEN:15 NH:7 NHPC:4 NIACL:0 NIVABUPA:0 NLCINDIA:4 NMDC:9 NSLNISP:9 NTPC:4 NTPCGREEN:4 NUVAMA:0 NUVOCO:3 NYKAA:12 OBEROIRLTY:13 OFSS:15 OIL:11 OLAELEC:5 OLECTRA:5 ONESOURCE:7 ONGC:11 PAGEIND:16 PARADEEP:8 PATANJALI:6 PAYTM:0 PCBL:8 PERSISTENT:15 PETRONET:11 PFC:0 PFIZER:7 PFOCUS:21 PGEL:17 PHOENIXLTD:13 PIDILITIND:8 PIIND:8 PINELABS:0 PIRAMALFIN:0 PNB:0 PNBHOUSING:0 POLICYBZR:0 POLYCAB:2 POLYMED:7 POONAWALLA:0 POWERGRID:4 POWERINDIA:2 PPLPHARMA:7 PREMIERENE:2 PRESTIGE:13 PTCIL:2 PVRINOX:21 PWL:12 RADICO:6 RAILTEL:18 RAINBOW:7 RAMCOCEM:3 RBLBANK:0 RECLTD:0 REDINGTON:10 RELIANCE:11 RHIM:2 RITES:14 RKFORGE:5 RPOWER:4 RRKABEL:2 RVNL:14 SAGILITY:15 SAIL:9 SAILIFE:7 SAMMAANCAP:0 SAPPHIRE:12 SARDAEN:9 SAREGAMA:21 SBFC:0 SBICARD:0 SBILIFE:0 SBIN:0 SCHAEFFLER:5 SCHNEIDER:2 SCI:10 SHREECEM:3 SHRIRAMFIN:0 SHYAMMETL:2 SIEMENS:2 SIGNATURE:13 SJVN:4 SOBHA:13 SOLARINDS:8 SONACOMS:5 SONATSOFTW:15 SPLPETRO:8 SRF:8 STARHEALTH:0 SUMICHEM:8 SUNDARMFIN:0 SUNPHARMA:7 SUNTV:21 SUPREMEIND:2 SUZLON:2 SWANCORP:8 SWIGGY:12 SYNGENE:7 SYRMA:2 TARIL:2 TATACAP:0 TATACHEM:8 TATACOMM:18 TATACONSUM:6 TATAELXSI:15 TATAINVEST:0 TATAPOWER:4 TATASTEEL:9 TATATECH:15 TBOTEK:12 TCS:15 TECHM:15 TECHNOE:14 TEGA:2 TEJASNET:18 TENNIND:5 THELEELA:12 THERMAX:2 TIINDIA:5 TIMKEN:2 TITAGARH:2 TITAN:17 TMCV:2 TMPV:5 TORNTPHARM:7 TORNTPOWER:4 TRAVELFOOD:12 TRENT:12 TRIDENT:16 TRITURBINE:2 TTML:18 TVSMOTOR:5 UBL:6 UCOBANK:0 ULTRACEMCO:3 UNIONBANK:0 UNITDSPR:6 UNOMINDA:5 UPL:8 URBANCO:12 USHAMART:2 UTIAMC:0 VBL:6 VEDL:9 VIJAYA:7 VMM:12 VOLTAS:17 VTL:16 WAAREEENER:2 WELCORP:2 WELSPUNLIV:16 WHIRLPOOL:17 WIPRO:15 WOCKPHARMA:7 YESBANK:0 ZEEL:21 ZENSARTECH:15 ZENTEC:2 ZFCVINDIA:5 ZYDUSLIFE:7 ZYDUSWELL:6';

function fetchUniverse_() {
  // Universe source: MasterData (header row has "Symbol"/"Nifty500"/"Nifty750" + "Industry"),
  // then a "Universe" sheet, then the built-in list above as a last resort.
  var ss = SpreadsheetApp.getActive();
  var names = ['MasterData', 'Universe'];
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
  return UNIVERSE_LIST.split(' ').map(function (t) {
    var p = t.split(':');
    return [p[0], UNIVERSE_INDUSTRIES[Number(p[1])]];
  });
}


/** Momentum menu -> Update universe (upload NSE CSV).
 *  NSE blocks direct downloads from Google's servers, so the user downloads the
 *  Nifty 500 constituents CSV and picks it here. Rewrites MasterData A3:B. */
function updateUniverseFromNSE() {
  var html = HtmlService.createHtmlOutput(
    '<div style="font:13px Arial,sans-serif;line-height:1.5">' +
    '<p><b>1.</b> Download the <b>Nifty 500</b> index constituents CSV from niftyindices.com ' +
    '(file name like ind_nifty500list.csv).</p>' +
    '<p><b>2.</b> Choose that file:</p>' +
    '<input type="file" id="f" accept=".csv,text/csv">' +
    '<p id="m" style="white-space:pre-wrap;margin-top:12px"></p>' +
    '<script>' +
    'document.getElementById("f").onchange=function(e){' +
    ' var file=e.target.files[0]; if(!file) return;' +
    ' var m=document.getElementById("m"); m.textContent="Updating MasterData...";' +
    ' var r=new FileReader();' +
    ' r.onload=function(){google.script.run' +
    '  .withSuccessHandler(function(msg){m.textContent=msg;})' +
    '  .withFailureHandler(function(err){m.textContent="Error: "+err.message;})' +
    '  .importUniverseCsv(r.result);};' +
    ' r.readAsText(file);};' +
    '</scr' + 'ipt></div>'
  ).setWidth(460).setHeight(300);
  SpreadsheetApp.getUi().showModalDialog(html, 'Update universe (Nifty 500)');
}

/** Called from the upload dialog. Parses the NSE CSV and rewrites MasterData A3:B. */
function importUniverseCsv(text) {
  var data = Utilities.parseCsv(String(text || '').replace(/^﻿/, ''));
  if (!data.length) throw new Error('The file is empty.');
  var hdr = data[0].map(function (x) { return String(x).trim().toLowerCase(); });
  var iSym = hdr.indexOf('symbol'), iInd = hdr.indexOf('industry');
  if (iSym < 0) throw new Error('No "Symbol" column found. Is this the NSE constituents CSV?');
  var rows = [];
  for (var r = 1; r < data.length; r++) {
    var s = String(data[r][iSym] || '').trim();
    if (s) rows.push([s, iInd >= 0 ? String(data[r][iInd] || '').trim() : '']);
  }
  if (rows.length < 450 || rows.length > 550)
    throw new Error('File has ' + rows.length + ' stocks (expected about 500; the backtest uses the Nifty 500). MasterData was NOT changed.');
  var sh = SpreadsheetApp.getActive().getSheetByName('MasterData');
  var last = sh.getLastRow();
  var oldList = last >= 3 ? sh.getRange(3, 1, last - 2, 1).getValues()
      .map(function (x) { return String(x[0]).trim(); }).filter(String) : [];
  var newList = rows.map(function (x) { return x[0]; });
  var added = newList.filter(function (s) { return oldList.indexOf(s) < 0; });
  var removed = oldList.filter(function (s) { return newList.indexOf(s) < 0; });
  if (last >= 3) sh.getRange(3, 1, last - 2, 2).clearContent();
  sh.getRange(3, 1, rows.length, 2).setValues(rows);
  return 'Done. ' + rows.length + ' stocks written to MasterData.\n\nAdded (' + added.length + '): ' +
    (added.join(', ') || 'none') + '\nRemoved (' + removed.length + '): ' + (removed.join(', ') || 'none') +
    '\n\nClose this box and run Momentum → Run scan now.';
}

function yahooUrl_(ticker, range, interval) {
  return 'https://query1.finance.yahoo.com/v8/finance/chart/' + encodeURIComponent(ticker) +
         '?range=' + range + '&interval=' + interval;
}

function yahooRequest_(ticker, range, interval) {
  return { url: yahooUrl_(ticker, range, interval), muteHttpExceptions: true, headers: { 'User-Agent': 'Mozilla/5.0' } };
}

function dateKey_(ts) {
  return Utilities.formatDate(new Date(ts * 1000), CFG.TZ, 'yyyy-MM-dd');
}

/** Daily bars -> {dateStr: {c, h, v}}. Close/high are split-adjusted, not dividend-adjusted. */
function parseDaily_(text) {
  var j = JSON.parse(text), res = j.chart && j.chart.result && j.chart.result[0];
  if (!res || !res.timestamp) return null;
  var q = res.indicators.quote[0], map = {};
  for (var k = 0; k < res.timestamp.length; k++) {
    var c = q.close[k];
    if (c === null || c === undefined || isNaN(c) || !c) continue;
    var h = q.high && q.high[k], v = q.volume && q.volume[k];
    map[dateKey_(res.timestamp[k])] = { c: c, h: h || c, v: v || 0 };
  }
  return map;
}

/** Weekly bars over the full history -> highest high (the all-time high). */
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

  while (pos < uni.length) {
    if (Date.now() - t0 > CFG.TIME_BUDGET_MS) {
      props.setProperties({ pos: String(pos), retry: JSON.stringify(retry) });
      setStatus_('Scanning ' + pos + ' / ' + uni.length + ' … continuing automatically');
      ScriptApp.newTrigger('continueScan').timeBased().after(60 * 1000).create();
      return;
    }
    var batch = uni.slice(pos, pos + CFG.BATCH);
    processBatch_(batch, cal, work, retry, true);
    pos += batch.length;
  }
  if (retry.length) { Utilities.sleep(5000); processBatch_(retry, cal, work, [], false); }  // one retry for 429s
  props.setProperties({ pos: String(pos), retry: '[]' });
  finalizeScan_();
}

function processBatch_(batch, cal, work, retry, allowRetry) {
  // Two requests per stock: 2 years of daily bars, and weekly bars over the full history (all-time high).
  var reqs = [];
  batch.forEach(function (b) {
    reqs.push(yahooRequest_(b[0] + '.NS', '2y', '1d'));
    reqs.push(yahooRequest_(b[0] + '.NS', 'max', '1wk'));
  });
  var resps = UrlFetchApp.fetchAll(reqs), rows = [];
  for (var k = 0; k < batch.length; k++) {
    var daily = resps[2 * k], weekly = resps[2 * k + 1], sym = batch[k][0], ind = batch[k][1];
    var code = daily.getResponseCode(), wcode = weekly.getResponseCode();
    if ((code === 429 || wcode === 429) && allowRetry) { retry.push(batch[k]); continue; }
    var sc = null, status = 'OK', lastPx = '';
    if (code === 200 && wcode === 200) {
      try {
        var m = parseDaily_(daily.getContentText());
        sc = m ? scoreStock_(m, cal, parseAllTimeHigh_(weekly.getContentText())) : null;
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
  var mk = marketFilter_(st.closes), asOf = cal[cal.length - 1];

  var sh = ss.getSheetByName(SH_RANK) || ss.insertSheet(SH_RANK);
  sh.clear();
  sh.getRange('A1:B7').setValues([
    ['As of (last close)', asOf],
    ['Nifty 500 close', mk.close],
    ['Nifty 500 200-day SMA', mk.sma],
    ['Closes in a row below the SMA', mk.streak],
    ['Market filter', mk.label],
    ['Status', 'Done ' + Utilities.formatDate(new Date(), CFG.TZ, 'dd-MMM-yyyy HH:mm')],
    ['Ranked (pass all filters) / scored / universe', ranked.length + ' / ' + scored.length + ' / ' + data.length]
  ]);
  sh.getRange('B5').setBackground(mk.state === 'RISK-ON' ? '#c8e6c9' : mk.state === 'WATCH' ? '#fff2cc' : '#ffcdd2').setFontWeight('bold');
  if (data.length > 550) sh.getRange('C7').setValue('Universe looks like the Nifty 750: the backtest uses the Nifty 500. Upload the Nifty 500 CSV.')
                           .setFontColor('#c00000');
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
  sh.getRange(RANK_HDR - 1, 4).setValue('Green = top 10 (buy zone)   Yellow = rank 11-30 (hold zone)   Stocks failing a filter are not ranked (see _ScanWork)');
  writeRules();                     // keep the Rules tab in step with CFG
}

/** Mirrors the backtest's daily market check (market_check="daily", confirm_days=3):
 *  RISK-OFF  CONFIRM_DAYS+ closes in a row below the SMA: sell everything today / stay in the liquid fund.
 *  WATCH     below the SMA for fewer days: keep holdings; if in the liquid fund, don't buy back yet.
 *  RISK-ON   close at or above the SMA. */
function marketFilter_(closes) {
  var n = closes.length, L = CFG.SMA_LEN, cum = [0];
  for (var i = 0; i < n; i++) cum.push(cum[i] + closes[i]);
  var smaAt = function (k) { return k >= L - 1 ? (cum[k + 1] - cum[k + 1 - L]) / L : NaN; };
  var streak = 0;
  for (i = n - 1; i >= L - 1 && closes[i] < smaAt(i); i--) streak++;
  var state = streak >= CFG.CONFIRM_DAYS ? 'RISK-OFF' : streak > 0 ? 'WATCH' : 'RISK-ON';
  var label = state === 'RISK-OFF' ? 'RISK-OFF: sell all today, 100% liquid fund'
            : state === 'WATCH' ? 'WATCH: below SMA ' + streak + ' day(s), exit after ' + CFG.CONFIRM_DAYS + ' in a row'
            : 'RISK-ON: invest';
  return { close: closes[n - 1], sma: smaAt(n - 1), streak: streak, state: state, label: label };
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
  var market = String(rk.getRange('B5').getValue()).split(':')[0];   // RISK-ON | WATCH | RISK-OFF
  if (['RISK-ON', 'WATCH', 'RISK-OFF'].indexOf(market) < 0) { ui.alert('Run the scan again (the Momentum Rank layout changed).'); return; }
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
  if (market === 'RISK-OFF') {
    note = 'Nifty 500 closed below its 200-day SMA ' + CFG.CONFIRM_DAYS + '+ days in a row: ' +
           (hold.length ? 'SELL ALL today (any day of the month), move 100% to liquid fund.' : 'stay in the liquid fund.');
    hold.forEach(function (h) { plan.push(['SELL', h.sym, h.sh, price[h.sym] || '', rank[h.sym] || 'Not ranked', 'Market filter']); });
  } else if (!hold.length && market === 'WATCH') {
    note = 'In the liquid fund and the Nifty 500 is below its 200-day SMA: do nothing. Buy back only at a month-end above the SMA.';
  } else if (!hold.length) {
    var each = liquid / CFG.TOP_N / (1 + CFG.COST);
    note = 'Portfolio is in liquid fund / fresh start: BUY top ' + CFG.TOP_N + ' in equal amounts.';
    rows.slice(0, CFG.TOP_N).forEach(function (r) {
      plan.push(['BUY', r[1], liquid ? Math.floor(each / r[2]) : '', r[2], r[0], liquid ? 'Amount ≈ ₹' + Math.round(each) : 'Equal amount']);
    });
  } else {
    note = (market === 'WATCH' ? 'Nifty 500 below its SMA for fewer than ' + CFG.CONFIRM_DAYS + ' days: not an exit, rebalance as usual. ' : '') +
           'Invested: keep ranks 1-' + CFG.KEEP_RANK + ', sell the rest (including stocks that fail a filter), refill to ' + CFG.TOP_N +
           ' with sale proceeds split equally. Kept holdings are NOT resized.';
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
    var need = CFG.TOP_N - kept.length;
    var buys = rows.filter(function (r) { return kept.indexOf(r[1]) < 0 && !hold.some(function (h) { return h.sym === r[1]; }); }).slice(0, need);
    var per = buys.length ? proceeds / buys.length / (1 + CFG.COST) : 0;
    buys.forEach(function (r) {
      plan.push(['BUY', r[1], per ? Math.floor(per / r[2]) : '', r[2], r[0], per ? 'Amount ≈ ₹' + Math.round(per) : 'Split sale proceeds equally']);
    });
  }
  var sh = ss.getSheetByName(SH_PLAN) || ss.insertSheet(SH_PLAN);
  sh.clear();
  sh.getRange('A1').setValue('Rebalance plan — ' + rk.getRange('B1').getDisplayValue()).setFontWeight('bold');
  sh.getRange('A2').setValue(note);
  sh.getRange('A3').setValue(market === 'RISK-OFF' ? 'Market exit: execute today, at the close. Costs assumed 0.25% per trade.'
    : 'Execute only on the last trading day of the month, at the close. Costs assumed 0.25% per trade.');
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
  var rules = [
    ['Section', 'Rule'],
    ['Universe', 'Today\'s Nifty 500 list (Momentum → Update universe; refresh when NSE rebalances the index, usually March and September).'],
    ['Filter 1: near high', 'Close within ' + pct(CFG.MAX_FALL) + ' of the all-time high.'],
    ['Filter 2: trend', 'Close above its ' + CFG.STOCK_SMA + '-day simple moving average.'],
    ['Filter 3: liquidity', 'Average daily turnover (close × volume) over ' + CFG.TURNOVER_DAYS + ' sessions above ₹' + CFG.MIN_TURNOVER / 1e7 + ' crore.'],
    ['Score', 'Av Sharpe = average over ' + CFG.LOOKBACKS.join('/') + ' sessions of (% return over the window) ÷ (daily-return standard deviation × √252). ' +
              'No risk-free rate. Each window needs ' + pct(CFG.MIN_PRESENT) + ' price data. Stocks failing any filter are not ranked.'],
    ['Buy', 'Hold the top ' + CFG.TOP_N + ' by Av Sharpe, equal amounts at entry.'],
    ['Sell', 'At month-end, sell a holding that ranks below ' + CFG.KEEP_RANK + ' or fails a filter (not ranked). Kept holdings are not resized.'],
    ['Refill', 'Split the sale money equally across the best-ranked stocks not already held, back up to ' + CFG.TOP_N + '.'],
    ['Rebalance day', 'Last trading day of the month, at the close.'],
    ['Market exit', 'Checked every day: if the Nifty 500 closes below its ' + CFG.SMA_LEN + '-day SMA ' + CFG.CONFIRM_DAYS +
                    ' days in a row, sell everything that day and move 100% to a liquid fund.'],
    ['Market re-entry', 'Stay in the liquid fund until a month-end close at or above the ' + CFG.SMA_LEN + '-day SMA, then buy the top ' + CFG.TOP_N + '.'],
    ['Below SMA < ' + CFG.CONFIRM_DAYS + ' days', 'Not an exit. If invested, rebalance as usual at month-end.'],
    ['Costs', 'Backtest assumes ' + pct(CFG.COST) + ' per buy and per sell.'],
    ['Prices', 'Yahoo daily close (split-adjusted, not dividend-adjusted) on the Nifty 500 calendar; gaps up to ' + CFG.FFILL_LIMIT +
               ' sessions carried forward; one-day moves over ' + pct(CFG.BAD_RET) + ' ignored.'],
    ['Daily routine', 'Scan runs each weekday ~4:30 pm. If Market filter says RISK-OFF and you hold stocks, build the plan and sell. ' +
                      'On the last trading day of the month, run the scan and Build rebalance plan.']
  ];
  sh.clear();
  sh.getRange(1, 1, rules.length, 2).setValues(rules).setWrap(true).setVerticalAlignment('top');
  sh.getRange(1, 1, 1, 2).setFontWeight('bold').setBackground('#00ffff');
  sh.getRange(2, 1, rules.length - 1, 1).setFontWeight('bold');
  sh.setColumnWidth(1, 170); sh.setColumnWidth(2, 720);
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
