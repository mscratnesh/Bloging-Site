// ===================== MOMENTUM SHARPE SCAN =====================
/**
 * MOMENTUM SCAN — Google Apps Script (live scan + month-end rebalance plan)
 *
 * Same rules as the site's backtest (momentum.py / Momentum Study base case):
 *   Universe   Nifty Total Market (750) from MasterData.
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
 *              refill with sale money split equally; Nifty 500 below its 200-day SMA at
 *              month-end = sell all, 100% liquid fund.
 *
 * TABS CREATED:  Momentum Rank, Portfolio, Rebalance Plan, _ScanWork (hidden)
 */

// ------------------------------- SETTINGS ---------------------------------
var CFG = {
  INDEX_TICKER: '^CRSLDX',          // Nifty 500 on Yahoo
  LOOKBACKS: [252, 184, 126, 63],
  MIN_PRESENT: 0.90,                // share of each window that must have data
  BAD_RET: 0.60,
  FFILL_LIMIT: 5,
  SMA_LEN: 200,                     // market filter (Nifty 500)
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

var SH_RANK = 'Momentum Rank', SH_PORT = 'Portfolio', SH_PLAN = 'Rebalance Plan', SH_WORK = '_ScanWork';
var WORK_COLS = 13;                 // results in A:M
var STORE_COL = 21;                 // universe in U:V, index calendar in W:X

function onOpen() {
  SpreadsheetApp.getUi().createMenu('Momentum')
    .addItem('Update universe (upload NSE CSV)', 'updateUniverseFromNSE')
    .addItem('Run scan now', 'startScan')
    .addItem('Build rebalance plan', 'buildRebalancePlan')
    .addSeparator()
    .addItem('Auto-run scan every weekday 4:30 pm', 'installDailyTrigger')
    .addItem('Stop auto-run', 'removeDailyTrigger')
    .addToUi();
}

// ------------------------------- DATA -------------------------------------
// Nifty Total Market (Nifty 750) constituents from niftyindices.com, downloaded 24-Sep-2026
// (DUMMY rows removed). Used only if MasterData and Universe tabs are both missing.
var UNIVERSE_AS_OF = '24-Sep-2026';
var UNIVERSE_INDUSTRIES = ["Financial Services","Diversified","Capital Goods","Construction Materials","Power","Automobile and Auto Components","Fast Moving Consumer Goods","Healthcare","Chemicals","Metals & Mining","Services","Oil Gas & Consumable Fuels","Consumer Services","Realty","Construction","Information Technology","Textiles","Consumer Durables","Telecommunication","Utilities","Forest Materials","Media Entertainment & Publication"];
var UNIVERSE_LIST = '360ONE:0 3MINDIA:1 ABB:2 ACC:3 ACMESOLAR:4 AIAENG:2 APLAPOLLO:2 ASKAUTOLTD:5 AUBANK:0 AWL:6 AXISCADES:2 AADHARHFC:0 AARTIDRUGS:7 AARTIIND:8 AARTIPHARM:7 AAVAS:0 ABBOTINDIA:7 ACE:2 ACUTAAS:7 ADANIENSOL:4 ADANIENT:9 ADANIGREEN:4 ADANIPORTS:10 ADANIPOWER:4 ATGL:11 ABCAPITAL:0 ABFRL:12 ABLBL:12 ABREL:13 ABSLAMC:0 CPPLUS:2 AVL:12 ADVENZYMES:7 AEGISLOG:11 AEGISVOPAK:11 AEQUS:2 AETHER:8 AFCONS:14 AFFLE:15 AHLUCONT:14 AJANTPHARM:7 AKUMS:7 APLLTD:7 ALIVUS:7 ALKEM:7 ALKYLAMINE:8 ABDL:6 ALOKINDS:16 ARE&M:5 AMBER:17 AMBUJACEM:3 ANANDRATHI:0 ANANTRAJ:13 ANGELONE:0 ANTHEM:7 ANURAS:8 APARINDS:2 APOLLOHOSP:7 APOLLO:2 APOLLOTYRE:5 APTUS:0 ACI:8 ARVINDFASN:12 ARVIND:16 ASAHIINDIA:5 ASHAPURMIN:9 ASHOKLEY:2 ASHOKA:14 ASIANPAINT:17 ASTERDM:7 ASTRAMICRO:2 ASTRAL:2 ATHERENERG:5 ATLANTAELE:2 ATUL:8 AURIONPRO:15 AUROPHARMA:7 AIIL:0 AVALON:2 AVANTIFEED:6 DMART:12 CCAVENUE:0 AWFIS:10 AXISBANK:0 AZAD:2 BEML:2 BLS:12 BSE:0 BAJAJ-AUTO:5 BAJAJELEC:17 BAJFINANCE:0 BAJAJFINSV:0 BAJAJHLDNG:0 BAJAJHFL:0 BALAMINES:8 BALKRISIND:5 BALRAMCHIN:6 BALUFORGE:2 BANCOINDIA:5 BANDHANBNK:0 BANKBARODA:0 BANKINDIA:0 MAHABANK:0 BATAINDIA:17 BAYERCROP:8 BELRISE:5 BERGEPAINT:17 BDL:2 BEL:2 BHARATFORG:5 BHEL:2 BPCL:11 BHARTIARTL:18 BHARTIHEXA:18 BIKAJI:6 GROWW:0 BIOCON:7 BIRLACORPN:3 BSOFT:15 BBOX:15 BLACKBUCK:10 BLUEDART:10 BLUEJET:7 BLUESTARCO:17 BLUESTONE:17 BBTC:6 BORORENEW:2 BOSCHLTD:5 FIRSTCRY:12 BRIGADE:13 BRITANNIA:6 MAPMYINDIA:15 CCL:6 CESC:4 CGPOWER:2 CIEINDIA:5 CMSINFO:10 CORONA:7 CRISIL:0 CSBBANK:0 CAMPUS:17 CANFINHOME:0 CANBK:0 CANHLIFE:0 CRAMC:0 CAPILLARY:15 CAPLIPOINT:7 CGCL:0 CARBORUNIV:2 CARTRADE:12 CASTROLIND:11 CEATLTD:5 CELLO:17 CEMPRO:14 CENTRALBK:0 CDSL:0 CENTURYPLY:17 CERA:17 CHALET:12 CHAMBLFERT:8 CHENNPETRO:11 CHOICEIN:0 CHOLAHLDNG:0 CHOLAFIN:0 CIPLA:7 CUB:0 CLEAN:8 COALINDIA:11 COCHINSHIP:2 COFORGE:15 COHANCE:7 COLPAL:6 CAMS:0 CONCORDBIO:7 CONCOR:10 COROMANDEL:8 CRAFTSMAN:5 CREDITACC:0 CRIZAC:12 CROMPTON:17 CUMMINSIND:2 CUPID:6 CYIENT:15 DCBBANK:0 DCMSHRIRAM:1 DLF:13 DOMS:6 DABUR:6 DALBHARAT:3 DATAPATTNS:2 DATAMATICS:15 DEEPAKFERT:8 DEEPAKNTR:8 DELHIVERY:10 DEVYANI:12 DIACABS:2 DBL:14 DIVISLAB:7 DIXON:17 AGARWALEYE:7 LALPATHLAB:7 DRREDDY:7 DYNAMATECH:2 EIDPARRY:6 EIHOTEL:12 EPL:2 EDELWEISS:0 EICHERMOT:5 ELECON:2 EMIL:12 ELECTCAST:2 ELGIEQUIP:2 ELLEN:8 EMAMILTD:6 EMBDL:13 EMCURE:7 EMMVEE:2 ENDURANCE:5 ENGINERSIN:14 ENTERO:12 EIEL:19 EQUITASBNK:0 ERIS:7 ESCORTS:2 ETERNAL:12 ETHOSLTD:17 EUREKAFORB:17 EXIDEIND:5 NYKAA:12 FEDFINA:0 FEDERALBNK:0 FACT:8 FIEMIND:5 FINCABLES:2 FINPIPE:2 FSL:10 FIVESTAR:0 FORCEMOT:5 FORTIS:7 UTLSOLAR:2 GAIL:11 GVT&D:2 GHCL:8 GMMPFAUDLR:2 GMRAIRPORT:10 GMRP&UI:4 GABRIEL:5 GALLANTT:2 GRSE:2 GRWRHITECH:2 GICRE:0 GILLETTE:6 GLAND:7 GLAXO:7 GLENMARK:7 MEDANTA:7 GODIGIT:0 GPIL:2 GODFRYPHLP:6 GODREJAGRO:6 GODREJCP:6 GODREJIND:1 GODREJPROP:13 GOKEX:16 GOKULAGRO:6 GRANULES:7 GRAPHITE:2 GRASIM:3 GRAVITA:9 GESHIP:10 GREAVESCOT:2 GRINDWELL:2 GAEL:6 FLUOROCHEM:8 GMDCLTD:9 GNFC:8 GPPL:10 GSFC:8 HGINFRA:14 HBLENGINE:2 HCLTECH:15 HDBFS:0 HDFCAMC:0 HDFCBANK:0 HDFCLIFE:0 HEGAM:2 HFCL:18 HAPPSTMNDS:15 HAVELLS:17 HCG:7 HEMIPROP:10 HERITGFOOD:6 HEROMOTOCO:5 HEXT:15 HSCL:8 HINDALCO:9 HAL:2 HCC:14 HINDCOPPER:9 HINDPETRO:11 HINDUNILVR:6 HINDZINC:9 POWERINDIA:2 HOMEFIRST:0 HONASA:6 HONAUT:2 HUDCO:0 HYUNDAI:5 ICICIBANK:0 ICICIGI:0 ICICIAMC:0 ICICIPRULI:0 IDBI:0 IDFCFIRSTB:0 IFBIND:17 IFCI:0 IIFLCAPS:0 IIFL:0 INOXINDIA:2 IRB:14 IRCON:14 ITCHOTELS:12 ITC:6 ITI:18 INDGN:7 INDIACEM:3 INDIAGLYCO:6 INDIASHLTR:0 INDIAMART:12 INDIANB:0 IEX:0 INDHOTEL:12 IMFA:9 IOC:11 IOB:0 IRCTC:12 IRFC:0 IREDA:0 INDIGOPNTS:17 ICIL:16 IGL:11 INDUSTOWER:18 INDUSINDBK:0 NAUKRI:12 INFY:15 INOXGREEN:10 INOXWIND:2 INTELLECT:15 INDIGO:10 IGIL:10 IKS:15 IONEXCHANG:19 IPCALAB:7 JKCEMENT:3 JAIBALAJI:9 JBMA:5 JKLAKSHMI:3 JKPAPER:20 JKTYRE:5 JMFINANCIL:0 JSWCEMENT:3 JSWDULUX:17 JSWENERGY:4 JSWINFRA:10 JSWSTEEL:9 JAINREC:9 JPPOWER:4 J&KBANK:0 JAMNAAUTO:5 JSFB:0 JAYNECOIND:2 JSLL:12 JINDALSAW:2 JSL:9 JINDALSTEL:9 JIOFIN:0 JUBLFOOD:12 JUBLINGREA:8 JUBLPHARMA:7 JLHL:7 JWL:2 JUSTDIAL:12 JYOTHYLAB:6 JYOTICNC:2 KPRMILL:16 KEI:2 KNRCON:14 KPIGREEN:4 KPITTECH:15 KRBL:6 KRN:2 KSB:2 KAJARIACER:17 KPIL:14 KALYANKJIL:17 KANSAINER:17 KTKBANK:0 KARURVYSYA:0 KSCL:6 KAYNES:2 KEC:14 KFINTECH:0 KIRLOSBROS:2 KIRLOSENG:2 KIRLPNU:2 KITEX:16 KOTAKBANK:0 KIMS:7 LTF:0 LTTS:15 LGEINDIA:17 LICHSGFIN:0 LTFOODS:6 LTM:15 LT:14 LATENTVIEW:15 LAURUSLABS:7 LXCHEM:8 IXIGO:12 THELEELA:12 LEMONTREE:12 LENSKART:12 LICI:0 LINDEINDIA:8 LLOYDSENGG:2 LLOYDSENT:9 LLOYDSME:9 LODHA:13 LUMAXTECH:5 LUPIN:7 MMTC:10 MOIL:9 MRF:5 MSTCLTD:10 MTARTECH:2 MGL:11 MAHSCOOTER:0 MAHSEAMLES:2 M&MFIN:0 M&M:5 MANAPPURAM:0 MRPL:11 MANKIND:7 MANORAMA:6 MARICO:6 MARKSANS:7 MARUTI:5 MASTEK:15 MFSL:0 MAXHEALTH:7 MAZDOCK:2 MEDPLUS:12 MEESHO:12 METROPOLIS:7 MINDACORP:5 MIDHANI:2 MSUMI:5 MOTILALOFS:0 MPHASIS:15 BECTORFOOD:6 MCX:0 MUTHOOTFIN:0 NATCOPHARM:7 NBCC:14 NCC:14 NEOGEN:8 NESCO:10 NHPC:4 NLCINDIA:4 NMDC:9 NSLNISP:9 NTPCGREEN:4 NTPC:4 NH:7 NATIONALUM:9 NFL:8 NAVA:4 NAVINFLUOR:8 NAZARA:21 NESTLEIND:6 NETWEB:15 NETWORK18:21 NEULANDLAB:7 NEWGEN:15 NAM-INDIA:0 NIVABUPA:0 NUVAMA:0 NUVOCO:3 OBEROIRLTY:13 ONGC:11 OIL:11 OLAELEC:5 OLECTRA:5 PAYTM:0 ONESOURCE:7 OPTIEMUS:18 OFSS:15 ORIENTCEM:3 ORKLAINDIA:6 OSWALPUMPS:2 PNGJL:17 POLICYBZR:0 PCJEWELLER:17 PCBL:8 PGEL:17 PIIND:8 PNBHOUSING:0 PNCINFRA:14 PTC:4 PTCIL:2 PVRINOX:21 PAGEIND:16 PARADEEP:8 PARAS:2 PARKHOSPS:7 PATANJALI:6 PGIL:16 PERSISTENT:15 PETRONET:11 PFIZER:7 PHOENIXLTD:13 PWL:12 PICCADIL:6 PIDILITIND:8 PINELABS:0 PIRAMALFIN:0 PPLPHARMA:7 POLYMED:7 POLYCAB:2 POONAWALLA:0 PFC:0 POWERGRID:4 POWERMECH:14 PRAJIND:2 PREMIERENE:2 PRESTIGE:13 PRICOLLTD:5 PFOCUS:21 PRSMJOHNSN:3 PRIVISCL:8 PRUDENT:0 PNB:0 PURVA:13 QPOWER:2 QUESS:10 RRKABEL:2 RBLBANK:0 RECLTD:0 RHIM:2 RITES:14 RADICO:6 RVNL:14 RAILTEL:18 RAIN:8 RAINBOW:7 RALLIS:8 RKFORGE:5 RCF:8 RATEGAIN:15 RATNAMANI:2 RTNINDIA:12 RTNPOWER:4 RAYMONDLSL:16 REDINGTON:10 REDTAPE:17 REFEX:19 RELAXO:17 RELIANCE:11 RPOWER:4 RELIGARE:0 RBA:12 ROUTE:18 RUBICON:7 SBFC:0 SBICARD:0 SBILIFE:0 SJVN:4 SKFINDUS:2 SKFINDIA:5 SKYGOLD:17 SMLMAH:2 SHRIPISTON:5 SRF:8 LOTUSDEV:13 SAATVIKGL:2 SAFARI:17 SAGILITY:15 SAILIFE:7 SAMHI:12 SAMMAANCAP:0 MOTHERSON:5 SANDUMA:9 SANOFICONR:7 SANSERA:5 SAPPHIRE:12 SARDAEN:9 SAREGAMA:21 SCHAEFFLER:5 SCHNEIDER:2 SENCO:17 STYL:0 SHAILY:17 SHAKTIPUMP:2 SHARDACROP:8 SHAREINDIA:0 SFL:17 SHILPAMED:7 SCI:10 SHREECEM:3 RENUKA:6 SHRIRAMFIN:0 SHYAMMETL:2 ENRIN:2 SIEMENS:2 SIGNATURE:13 SKIPPER:2 SMARTWORKS:10 SOBHA:13 SOLARINDS:8 SONACOMS:5 SONATSOFTW:15 SOUTHBANK:0 STARCEMENT:3 STARHEALTH:0 SBIN:0 SAIL:9 SWSOLAR:14 STLTECH:18 STAR:7 STYRENIX:8 SUBROS:2 SUDARSCHEM:8 SUDEEPPHRM:8 SUMICHEM:8 SPARC:7 SUNPHARMA:7 SUNTV:21 SUNDARMFIN:0 SUNTECK:13 SUPREMEIND:2 SPLPETRO:8 SUPRIYA:7 SURYAROSNI:2 SUZLON:2 SWANCORP:8 SWIGGY:12 SYNGENE:7 SYRMA:2 TARC:13 TBOTEK:12 TDPOWERSYS:2 TSFINV:0 TVSMOTOR:5 TVSSCS:10 TMB:0 TANLA:15 TATACAP:0 TATACHEM:8 TATACOMM:18 TCS:15 TATACONSUM:6 TATAELXSI:15 TATAINVEST:0 TMCV:2 TMPV:5 TATAPOWER:4 TATASTEEL:9 TATATECH:15 TTML:18 TECHM:15 TECHNOE:14 TEGA:2 TEJASNET:18 TENNIND:5 TEXRAIL:2 THANGAMAYL:17 ANUP:2 NIACL:0 RAMCOCEM:3 THERMAX:2 THOMASCOOK:12 THYROCARE:7 TI:6 TIMETECHNO:2 TIMKEN:2 TIPSMUSIC:21 TITAGARH:2 TITAN:17 TORNTPHARM:7 TORNTPOWER:4 TARIL:2 TRANSRAILL:2 TRAVELFOOD:12 TRENT:12 TRIDENT:16 TRIVENI:6 TRITURBINE:2 TIINDIA:5 UCOBANK:0 UNOMINDA:5 UPL:8 UTIAMC:0 UJJIVANSFB:0 ULTRACEMCO:3 UNIONBANK:0 UBL:6 UNITDSPR:6 URBANCO:12 USHAMART:2 VGUARD:17 VMART:12 VIPIND:17 V2RETAIL:12 DBREALTY:13 WABAG:19 VAIBHAVGBL:17 VTL:16 VARROC:5 VBL:6 MANYAVAR:12 VEDL:9 VIJAYA:7 VIKRAMSOLR:2 VMM:12 VIYASH:7 IDEA:18 VOLTAMP:2 VOLTAS:17 WAAREEENER:2 WAAREERTL:2 WAKEFIT:17 WEWORK:10 WEBELSOLAR:2 WELCORP:2 WELENT:14 WELSPUNLIV:16 WESTLIFE:12 WHIRLPOOL:17 WIPRO:15 WOCKPHARMA:7 YATHARTH:7 YESBANK:0 ZFCVINDIA:5 ZAGGLE:15 ZEEL:21 ZENTEC:2 ZENSARTECH:15 ZYDUSLIFE:7 ZYDUSWELL:6 ECLERX:10';

function fetchUniverse_() {
  // Universe source: MasterData (header row has "Nifty750"/"Symbol" + "Industry"),
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
 *  Nifty Total Market constituents CSV and picks it here. Rewrites MasterData A3:B. */
function updateUniverseFromNSE() {
  var html = HtmlService.createHtmlOutput(
    '<div style="font:13px Arial,sans-serif;line-height:1.5">' +
    '<p><b>1.</b> Download the <b>Nifty Total Market</b> index constituents CSV from niftyindices.com ' +
    '(file name like ind_niftytotalmarket_list.csv).</p>' +
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
  SpreadsheetApp.getUi().showModalDialog(html, 'Update universe (Nifty 750)');
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
  if (rows.length < 700) throw new Error('File has only ' + rows.length + ' stocks (expected about 750). MasterData was NOT changed.');
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
  sh.getRange('A1:B6').setValues([
    ['As of (last close)', asOf],
    ['Nifty 500 close', mk.close],
    ['Nifty 500 200-day SMA', mk.sma],
    ['Market filter', mk.riskOn ? 'RISK-ON: invest' : 'RISK-OFF: 100% liquid fund'],
    ['Ranked (pass all filters) / scored / universe', ranked.length + ' / ' + scored.length + ' / ' + data.length],
    ['Status', 'Done ' + Utilities.formatDate(new Date(), CFG.TZ, 'dd-MMM-yyyy HH:mm')]
  ]);
  sh.getRange('B4').setBackground(mk.riskOn ? '#c8e6c9' : '#ffcdd2').setFontWeight('bold');
  var hdr = [['Rank', 'Symbol', 'Close', 'Av Sharpe', 'Sharpe 252', 'Sharpe 184', 'Sharpe 126', 'Sharpe 63',
              'Below ATH', 'Turnover ₹ Cr', 'SMA' + CFG.STOCK_SMA, 'Industry']];
  sh.getRange(8, 1, 1, hdr[0].length).setValues(hdr).setFontWeight('bold').setBackground('#00ffff');
  var out = ranked.map(function (r, i) { return [i + 1, r[0], r[2], r[7], r[3], r[4], r[5], r[6], r[8], r[9], r[10], r[1]]; });
  if (out.length) {
    sh.getRange(9, 1, out.length, hdr[0].length).setValues(out);
    sh.getRange(9, 3, out.length, 6).setNumberFormat('0.00');
    sh.getRange(9, 9, out.length, 1).setNumberFormat('0.0%');
    sh.getRange(9, 10, out.length, 2).setNumberFormat('0.00');
    sh.getRange(9, 1, Math.min(CFG.TOP_N, out.length), hdr[0].length).setBackground('#d9ead3');
    if (out.length > CFG.TOP_N)
      sh.getRange(9 + CFG.TOP_N, 1, Math.min(CFG.KEEP_RANK, out.length) - CFG.TOP_N, hdr[0].length).setBackground('#fff2cc');
  }
  sh.setFrozenRows(8);
  sh.getRange('D7').setValue('Green = top 10 (buy zone)   Yellow = rank 11-30 (hold zone)   Stocks failing a filter are not ranked (see _ScanWork)');
}

function marketFilter_(closes) {
  var n = closes.length, sum = 0;
  for (var i = n - CFG.SMA_LEN; i < n; i++) sum += closes[i];
  var sma = sum / CFG.SMA_LEN, c = closes[n - 1];
  return { close: c, sma: sma, riskOn: !(c < sma) };        // sell only when close < SMA
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
  var riskOn = String(rk.getRange('B4').getValue()).indexOf('RISK-ON') === 0;
  var rows = rk.getRange(9, 1, Math.max(rk.getLastRow() - 8, 1), 3).getValues().filter(function (r) { return r[1]; });
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
  if (!riskOn) {
    note = 'Nifty 500 is below its 200-day SMA: SELL ALL, move 100% to liquid fund.';
    hold.forEach(function (h) { plan.push(['SELL', h.sym, h.sh, price[h.sym] || '', rank[h.sym] || 'Not ranked', 'Market filter']); });
  } else if (!hold.length) {
    var each = liquid / CFG.TOP_N / (1 + CFG.COST);
    note = 'Portfolio is in liquid fund / fresh start: BUY top ' + CFG.TOP_N + ' in equal amounts.';
    rows.slice(0, CFG.TOP_N).forEach(function (r) {
      plan.push(['BUY', r[1], liquid ? Math.floor(each / r[2]) : '', r[2], r[0], liquid ? 'Amount ≈ ₹' + Math.round(each) : 'Equal amount']);
    });
  } else {
    note = 'Invested: keep ranks 1-' + CFG.KEEP_RANK + ', sell the rest (including stocks that fail a filter), refill to ' + CFG.TOP_N +
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
  sh.getRange('A3').setValue('Execute only on the last trading day of the month, at the close. Costs assumed 0.25% per trade.');
  sh.getRange(5, 1, 1, 6).setValues([['Action', 'Symbol', 'Shares', 'Price', 'Rank', 'Note']]).setFontWeight('bold').setBackground('#00ffff');
  if (plan.length) sh.getRange(6, 1, plan.length, 6).setValues(plan);
  sh.activate();
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
