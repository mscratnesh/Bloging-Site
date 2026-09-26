"""Report for the Multi Year Breakout sheet-rules backtest (study/breakout_spec_study.py): the sheet rules
today, each [PROPOSED] change on its own, a few combinations, the equity curves and every signal.

Reuses the look, chart and sortable-table code of study/backtest_report_template.html and fills it
with breakout_spec_study.json (run study/breakout_spec_study.py first).
Output: study/breakout_spec_report.html (local only, not shipped in dist/)
Run: py study/breakout_spec_report.py
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

src = (HERE / "backtest_report_template.html").read_text(encoding="utf-8")
style = re.search(r"<style>.*?</style>", src, re.S).group(0)
helpers = src[src.index("function sortableTable"):src.index("function monthCard")]
charts = src[src.index("function css(v)"):src.index("function drawCharts")]
data = json.loads((ROOT / "breakout_spec_study.json").read_text(encoding="utf-8"))

EXTRA_CSS = """<style>
:root { --s5: #8a63d2; }
:root[data-theme="dark"] { --s5: #a585e6; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --s5: #a585e6; } }
tr.grp td { background: var(--surface-2); font-weight: 650; }
tr.base td { font-weight: 650; }
tr.best td:first-child { box-shadow: inset 3px 0 0 var(--s1); }
td.sub { padding-left: 22px; min-width: 250px; }
tr.base td:first-child { min-width: 250px; }
.why-stop { color: var(--neg); } .why-trail { color: var(--text-2); } .why-open { color: var(--s1); }
.find { margin: 0; padding-left: 20px; } .find li { margin: 6px 0; }
.seg { display: inline-flex; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; margin: 0 0 10px; }
.seg button { font: inherit; font-size: 13.5px; padding: 6px 12px; border: 0; background: var(--surface); color: var(--text-2); cursor: pointer; }
.seg button + button { border-left: 1px solid var(--border); }
.seg button[aria-pressed="true"] { background: var(--s1); color: #fff; font-weight: 600; }
.d { font-size: 11.5px; color: var(--muted); display: block; }
</style>"""

SCRIPT = r"""
const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pct = (v, dp = 1, sign = false) => v == null || isNaN(v) ? "–" : (sign && v > 0 ? "+" : "") + (v * 100).toFixed(dp) + "%";
const cls = v => v > 0 ? "pos" : v < 0 ? "neg" : "";
const spct = (v, dp = 1) => `<span class="${cls(v)}">${pct(v, dp, true)}</span>`;
const MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const fdate = d => d ? `${+d.slice(8, 10)} ${MON[+d.slice(5, 7) - 1]} ${d.slice(0, 4)}` : "–";
const rs = v => (v < 0 ? "−" : "") + "₹" + Math.round(Math.abs(v)).toLocaleString("en-IN");
const lakh = v => "₹" + (v / 1e5).toFixed(1) + "L";
const WHY = { failed: "Failed breakout", stop: "Stop", trail: "Trail", breakeven: "Breakeven", open: "Still held" };
const V = k => DATA.variants.find(v => v.key === k);
// a change against the sheet rules, coloured when it moves by more than `tol`
const delta = (v, b, tol = 0.005) => v == null || b == null ? "" : `<span class="d">${Math.abs(v - b) < tol ? "same" : `<span class="${cls(v - b)}">${v > b ? "+" : "−"}${Math.abs((v - b) * 100).toFixed(1)}</span>`}</span>`;

function render() {
  const D = DATA, B = V("base"), N = D.bench.find(b => b.key === "nifty500"), G = D.bench.find(b => b.key === "gold");
  const best = V("sl97ma30"), ma30 = V("ma30"), sl97 = V("sl97");
  const ch = V("ch"), chma = V("chma30"), both = V("bothbest"), res = V("bothres"), NR = D.benchRecent[0];
  const vm = V("v2myb"), vm30 = V("v2mybma30"), vc = V("v2ch"), vc30 = V("v2chma30"), vco = V("v2choneil");
  const h = [];
  h.push(`<button class="theme-btn" id="theme" type="button">Theme</button>
  <h1>Breakout sheet: rules backtest</h1>
  <p class="sub">The weekly MasterData / Tracker rules as written in the rules spec, tested on point-in-time Nifty 500 stocks from ${fdate(D.from)} to ${fdate(D.asOf)}, then each [PROPOSED] change one at a time. Cup and handle on O'Neil's rules, alone and in the same portfolio. ${rs(D.capital)} to start, 10 slots.</p>
  <nav class="nav"><a href="#findings">Findings</a><a href="#compare">All variants</a><a href="#curve">Equity</a><a href="#signals">Every signal</a><a href="#method">Method</a></nav>

  <h2 id="findings" class="first">1. What the test says</h2>
  <div class="card"><ul class="find">
    <li><b>Breakouts are rare.</b> ${B.signals.n} signals in ${((new Date(D.asOf) - new Date(D.from)) / 3.156e10).toFixed(1)} years across the Nifty 500. ${pct(D.signalsPerWeek.zeroWeeks, 0)} of weeks had none, and the busiest week had ${D.signalsPerWeek.max}. So the portfolio was on average ${pct(B.portfolio.avgCash, 0)} in cash, and ranking or liquidity rules hardly ever matter.</li>
    <li><b>The signal has an edge; the exit throws it away.</b> Six months after a signal, stocks were up ${pct(B.signals["6m"].mean, 1)} on average, ${pct(B.signals["6m"].excess, 1)} more than the Nifty 500. But with the 2-week-low trail the median trade lasted ${B.signals.medWeeks} weeks, and the average trade made only ${pct(B.signals.avgRet, 1)} after costs (${pct(B.signals.winRate, 0)} winners).</li>
    <li><b>Gold did the work.</b> With idle money in GOLDBEES, the sheet rules made ${pct(B.portfolio.cagr)} a year, but gold alone made ${pct(G.cagr)}. With idle money in a liquid fund instead, the same trades made ${pct(B.portfolioLiquid.cagr)} a year, about what the liquid fund earns by itself.</li>
    <li><b>The older 30-week-average trail was better.</b> Average trade ${pct(ma30.signals.avgRet)} vs ${pct(B.signals.avgRet)}; liquid-fund CAGR ${pct(ma30.portfolioLiquid.cagr)} vs ${pct(B.portfolioLiquid.cagr)}. Fewer trades, held longer (median ${ma30.signals.medWeeks} weeks).</li>
    <li><b>The 3% buffer under R helps.</b> First stop max(0.97 R, breakout-week low): ${pct(sl97.signals.winRate, 0)} winners vs ${pct(B.signals.winRate, 0)}, fewer shake-outs on a retest. Combined with the 30-week trail it was the best set tested: ${pct(best.signals.avgRet)} a trade, CAGR ${pct(best.portfolio.cagr)} with gold / ${pct(best.portfolioLiquid.cagr)} with a liquid fund, worst fall ${pct(best.portfolio.maxDD)}.</li>
    <li><b>Most entry filters cut good trades with bad ones.</b> The top-third close filter made results worse. The 0-5% window, base-depth and 2-test filters improved win rate or 6-month returns a little, but left 28-59 signals, too few to trust the difference. The 5 and 10 crore liquidity floors removed nothing: every signal already traded more. The breakeven stop never came into play, because the 2-week-low trail had already passed the buy price by then.</li>
    <li><b>Cup and handle (O'Neil) signals far more often, with a weaker edge.</b> ${ch.signals.n} signals, against ${B.signals.n} multi-year breakouts. Six months later they were up ${pct(ch.signals["6m"].mean)}, ${pct(ch.signals["6m"].excess)} more than the Nifty 500 (multi-year: ${pct(B.signals["6m"].excess)}). The same exit problem applies: ${pct(ch.signals.avgRet)} a trade with the handle-low stop and 2-week-low trail, ${pct(chma.signals.avgRet)} with the 30-week trail. As a portfolio of its own: ${pct(ch.portfolioLiquid.cagr)} a year with idle money in a liquid fund, ${pct(chma.portfolioLiquid.cagr)} with the 30-week trail.</li>
    <li><b>Mixing both in 10 slots hurts the multi-year trades.</b> Cup-and-handle trades fill the slots, and the rarer, stronger multi-year breakouts find none free. Both setups with the better exits made ${pct(both.portfolioLiquid.cagr)} a year with a liquid fund, against ${pct(best.portfolioLiquid.cagr)} for multi-year alone. Keeping C&amp;H to 5 slots: ${pct(res.portfolioLiquid.cagr)} (${pct(res.portfolio.cagr)} with gold, worst fall ${pct(res.portfolio.maxDD)}). If you run both, give multi-year breakouts first call on the money.</li>
    <li><b>Since ${fdate(D.fullFrom)}</b> the Nifty 500 fell ${pct(-NR.cagr)} a year and C&amp;H trades broke even on average (${ch.signalsRecent.n} signals, ${pct(Math.abs(ch.signalsRecent.avgRet) < 0.0005 ? 0 : ch.signalsRecent.avgRet)} a trade with sheet exits).</li>
    <li><b>Your v2 script.</b> Its entry gates (market filter, Rs 5 Cr, 10% risk cap) help both setups. Multi-year v2: ${pct(vm.portfolioLiquid.cagr)} a year with a liquid fund under its two-stage exits, ${pct(vm30.portfolioLiquid.cagr)} with the 0.97 R stop and 30-week trail instead (average trade ${pct(vm.signals.avgRet)} vs ${pct(vm30.signals.avgRet)}). Cup and handle as the updated scanner finds it (apps-script/BreakoutTracker.gs): ${vc.signals.n} signals, ${pct(vc.signals["6m"].excess)} ahead of the Nifty 500 after 6 months, ${pct(vc.portfolioLiquid.cagr)} a year with the two-stage exits, better than with the 30-week trail (${pct(vc30.portfolioLiquid.cagr)}) or with the stricter O'Neil settings (${pct(vco.portfolioLiquid.cagr)}). The volume rule (1.4× the 10-week average) mattered most; cup depth, U shape, prior rise and handle limits each moved results by a point or less.</li>
    <li><b>Treat all of this as a small sample.</b> ${B.signals.n} signals, mostly in 2023-24. One or two big winners move every number here.</li>
  </ul></div>

  <h2 id="compare">2. All variants</h2>
  <p class="sub">Every signal: each breakout traded on its own, no slot limit. Portfolio: 10 slots, longest base first, idle money in GOLDBEES (or a liquid fund at 6.5%). Grey figures under each number: change against the sheet rules, in % points.</p>
  <div class="card tbl-wrap"><table>
    <thead><tr><th>Rule set</th><th class="n">Signals</th><th class="n">Winners</th><th class="n">Avg trade</th><th class="n">Median trade</th><th class="n">Median weeks</th><th class="n">6 months after signal</th><th class="n">vs Nifty 500</th>
      <th class="n">CAGR, gold</th><th class="n">CAGR, liquid</th><th class="n">Worst fall</th><th class="n">CAGR since ${fdate(D.fullFrom).slice(-8)}</th></tr></thead>
    <tbody>${table()}</tbody>
    <tfoot><tr><td>Nifty 500 index</td><td colspan="7"></td><td class="n">${pct(N.cagr)}</td><td class="n">${pct(N.cagr)}</td><td class="n">${pct(N.maxDD)}</td><td class="n">${pct(D.benchRecent[0].cagr)}</td></tr>
      <tr><td>GOLDBEES (buy and hold)</td><td colspan="7"></td><td class="n">${pct(G.cagr)}</td><td class="n"></td><td class="n">${pct(G.maxDD)}</td><td class="n">${pct(D.benchRecent[1].cagr)}</td></tr></tfoot>
  </table></div>

  <h2 id="curve">3. Equity</h2>
  <p class="sub">${rs(D.capital)} from ${fdate(D.from)}. Log scale.</p>
  <div class="card"><div class="legend">
    <span><i style="background:var(--s1);height:3px"></i>Sheet rules, gold</span><span><i style="background:var(--s3);height:3px"></i>Multi-year + C&amp;H, 0.97 stop + 30-week trail, gold</span>
    <span><i style="background:var(--s2);height:3px"></i>0.97 R stop + 30-week trail, gold</span><span><i style="background:var(--s5)"></i>... liquid fund</span>
    <span><i style="background:var(--text-2)"></i>Nifty 500</span><span><i style="background:var(--s4)"></i>GOLDBEES</span>
  </div><div class="chart" id="eqChart"></div></div>

  <h2 id="signals">4. Every signal under the sheet exits</h2>
  <p class="sub">Traded on its own at the weekly close, sold on a weekly close below the stop (R, or the handle low for C&amp;H) or below the 2-week low. Returns after 0.25% a side. Click a heading to sort.</p>
  <div class="seg" id="setupSeg"><button type="button" data-k="base">Multi-year base (${D.signalList.base.length})</button><button type="button" data-k="ch">Cup and handle (${D.signalList.ch.length})</button></div>
  <div class="card tbl-wrap"><table id="sigTbl">
    <thead><tr><th class="sort" data-k="s">Stock</th><th class="sort" data-k="sig">Signal week</th><th class="sort" data-k="base">Base</th><th class="sort n" data-k="above">Above R / pivot</th><th class="sort n" data-k="vr">Vol ratio</th>
      <th class="sort" data-k="exit">Exit week</th><th class="sort n" data-k="weeks">Weeks</th><th class="sort" data-k="why">Why</th><th class="sort n" data-k="ret">Return</th></tr></thead><tbody></tbody></table></div>

  <h2 id="method">5. Method and limits</h2>
  <div class="card"><ul class="rules" style="margin:0;padding-left:20px">
    <li>Weekly bars from daily prices; a week ends on its last trading day. Signals and exits on weekly closes, as the sheet is reviewed on weekends.</li>
    <li>Resistance R = highest weekly high from 260 weeks ago to 4 weeks ago. Base age = weeks since that high / 365 days, at least 2 years. BREAKOUT: close 0-10% above R, this week's volume at least 1.5 times the average of the previous 5 weeks, close above the 30-week average.</li>
    <li>Universe: the Nifty 500 list of the day, and at least Rs 1 crore average daily traded value over the last year.</li>
    <li>Portfolio: 10 equal slots; each buy gets the idle pool divided by the empty slots. Breakouts in a week with no free slot are skipped, not chased. 0.25% a side on stocks and GOLDBEES, dividends added on the ex-date, no tax.</li>
    <li><b>Short history.</b> Prices start in Sep 2019, so until ${fdate(D.fullFrom)} R is the highest high of 2-5 years, not a full 5. A stock with a higher high before 2019 can show a breakout here that the sheet would not. The last column shows ${fdate(D.fullFrom)} onward on its own, with the full window.</li>
    <li><b>No daily lows.</b> A week's low is its lowest close. That is higher than the real low, so the 2-week-low trail here is a little tighter than in the sheet, and the breakout-week low is a little higher.</li>
    <li>Prices are split-adjusted (splits and bonus issues removed) and volume scaled to match.</li>
    <li>Cup and handle, O'Neil: a cup 7-65 weeks from the left rim (the highest high before the right rim) to the right rim, 12-35% deep, after a rise of at least 30% in the year before the left rim. The right rim within 10% below (or 3% above) the left rim. A handle of 1-10 weeks that stays under the right rim, at most 12% deep and in the upper half of the cup. Pivot = handle high. Buy on a weekly close 0-5% above the pivot, with the same volume (1.5×) and 30-week rules; the sheet's SL is the handle low. Not modelled: the cup's U shape and volume drying up in the handle.</li>
    <li>Both setups: a stock that fits both counts as multi-year. In a week with more signals than free slots, multi-year bases go first, then the longest cups.</li>
    <li>Not tested: your sheet's own C&amp;H formulas (these are O'Neil's rules; checked against your current GNFC and POLICYBZR picks, the pivots and cup lengths match), the U/D volume and dry-up ratios as filters, and the half-size option for trades that risk more than 10%.</li>
  </ul></div>`);
  $("#app").innerHTML = h.join("");
  const showSignals = k => {
    document.querySelectorAll("#setupSeg button").forEach(b => b.setAttribute("aria-pressed", b.dataset.k === k));
    const tbl = $("#sigTbl"), fresh = tbl.cloneNode(true);  // drop the old sort listeners
    tbl.replaceWith(fresh);
    sortableTable("#sigTbl", D.signalList[k], "sig", -1, signalRow);
  };
  document.querySelectorAll("#setupSeg button").forEach(b => b.addEventListener("click", () => showSignals(b.dataset.k)));
  showSignals("base");
  $("#theme").addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("bt-theme", document.documentElement.dataset.theme); } catch (e) {}
    drawCharts();
  });
  drawCharts();
}

function signalRow(t) {
  return `<tr><td>${esc(t.s)}</td><td>${fdate(t.sig)}</td><td>${esc(t.base)}</td><td class="n">${pct(t.above)}</td>
    <td class="n">${t.vr.toFixed(2)}×</td><td>${fdate(t.exit)}</td><td class="n">${t.weeks}</td><td class="why-${t.why}">${WHY[t.why] || t.why}</td><td class="n">${spct(t.ret)}</td></tr>`;
}

function table() {
  const B = V("base");
  let last = "", out = "";
  DATA.variants.forEach(v => {
    if (v.group !== last && v.key !== "base") out += `<tr class="grp"><td colspan="12">${esc(v.group)}</td></tr>`;
    last = v.group;
    const s = v.signals, p = v.portfolio, isB = v.key === "base", d = (a, b) => isB ? "" : delta(a, b);
    out += `<tr class="${isB ? "base" : v.key === "sl97ma30" ? "best" : ""}"><td class="${isB ? "" : "sub"}">${esc(v.label)}</td>
      <td class="n">${s.n}</td><td class="n">${pct(s.winRate, 0)}${d(s.winRate, B.signals.winRate)}</td>
      <td class="n">${spct(s.avgRet)}${d(s.avgRet, B.signals.avgRet)}</td><td class="n">${spct(s.medRet)}</td><td class="n">${s.medWeeks}</td>
      <td class="n">${spct(s["6m"].mean)}</td><td class="n">${spct(s["6m"].excess)}</td>
      <td class="n">${pct(p.cagr)}${d(p.cagr, B.portfolio.cagr)}</td><td class="n">${pct(v.portfolioLiquid.cagr)}${d(v.portfolioLiquid.cagr, B.portfolioLiquid.cagr)}</td>
      <td class="n">${pct(p.maxDD)}</td><td class="n">${pct(v.portfolioRecent.cagr)}</td></tr>`;
  });
  return out;
}

function drawCharts() {
  const ticks = (lo, hi) => [5e5, 7.5e5, 1e6, 1.25e6, 1.5e6, 2e6, 2.5e6, 3e6, 4e6, 5e6].filter(t => t >= lo * 0.98 && t <= hi * 1.02);
  lineChart($("#eqChart"), { height: 340, log: true, ticksY: ticks, fmtY: lakh, series: [
    { k: "gold", name: "GOLDBEES", c: "--s4", w: 1.2, fmt: rs },
    { k: "nifty500", name: "Nifty 500", c: "--text-2", w: 1.2, fmt: rs },
    { k: "bestLiquid", name: "0.97 R + 30-wk, liquid", c: "--s5", w: 1.3, fmt: rs },
    { k: "bothBest", name: "MYB + C&H, gold", c: "--s3", w: 2, fmt: rs },
    { k: "best", name: "0.97 R + 30-wk, gold", c: "--s2", w: 2.3, fmt: rs },
    { k: "base", name: "Sheet rules, gold", c: "--s1", w: 2.3, fmt: rs }] });
}

try { const t = localStorage.getItem("bt-theme"); if (t) document.documentElement.dataset.theme = t; } catch (e) {}
render();
let rz; addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(drawCharts, 150); });
"""

page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Breakout Sheet Rules Backtest</title>
{style}
{EXTRA_CSS}
</head>
<body>
<div class="wrap" id="app"></div>
<script>
const DATA = {json.dumps(data, separators=(",", ":")).replace("</", "<\\/")};
{helpers}
{charts}
{SCRIPT}
</script>
</body>
</html>
"""
(HERE / "breakout_spec_report.html").write_text(page, encoding="utf-8")
print("wrote", HERE / "breakout_spec_report.html")
