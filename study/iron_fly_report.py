"""Report for the NIFTY monthly iron fly study: rules, results, why the VIX band, equity curve, years, exits,
every trade and the month-by-month log.

Reuses the look, chart and sortable-table code of study/backtest_report_template.html and fills it with
iron_fly_study.json (run study/nifty_iron_fly_study.py first).
Output: study/iron_fly_report.html (local only: it has the exact rules and every trade, which are sold in the
        handbook, so it is not part of the site build), and nifty-iron-fly.html at the site root, the public
        one-page summary with results only.
Run: py study/iron_fly_report.py
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
data = json.loads((ROOT / "iron_fly_study.json").read_text(encoding="utf-8"))

EXTRA_CSS = """<style>
.wrap.site-top { padding-bottom: 0; } .wrap.site-top + .wrap { padding-top: 4px; padding-bottom: 0; } .wrap.site-bottom { padding-top: 0; }
.site-back { display: inline-block; margin: 0; font-size: 13px; color: var(--text-2); text-decoration: none; }
.site-disclaimer { font-size: 12px; color: var(--muted); border-top: 1px solid var(--border); padding: 16px 0 28px; margin-top: 30px; }
.bars text { fill: var(--muted); font-size: 11px; }
.chart-note { font-size: 12.5px; color: var(--muted); margin: 6px 0 0; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.steps td:first-child { white-space: nowrap; font-weight: 650; }
tr.hl td { background: var(--surface-2); font-weight: 600; }
.mgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(118px, 1fr)); gap: 6px; }
.mcell { border: 1px solid var(--border); border-radius: 8px; padding: 6px 8px; font-size: 12px; background: var(--surface); }
.mcell b { display: block; font-size: 13px; }
.mcell.skip { opacity: .55; background: transparent; }
.why-stop { color: var(--bad); } .why-target { color: var(--good); }
.pbtn { font: inherit; font-size: 12px; padding: 2px 8px; border-radius: 6px; border: 1px solid var(--border); background: var(--surface-2); color: var(--text-2); cursor: pointer; }
.pbtn:hover, .pbtn.on { border-color: var(--s1); color: var(--text); }
.payoff svg text { fill: var(--muted); font-size: 11px; }
.payoff .facts { display: flex; flex-wrap: wrap; gap: 6px 22px; font-size: 13px; color: var(--text-2); margin: 8px 0 0; }
@media (max-width: 760px) { .two { grid-template-columns: 1fr; } }
</style>"""

SCRIPT = r"""
const MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pct = (v, dp = 0) => (v * 100).toFixed(dp) + "%";
const cls = v => v > 0 ? "pos" : v < 0 ? "neg" : "";
const fdate = d => d ? `${+d.slice(8, 10)} ${MON[+d.slice(5, 7) - 1]} ${d.slice(0, 4)}` : "–";
const fmonth = m => `${MON[+m.slice(5, 7) - 1]} ${m.slice(0, 4)}`;
const rs = v => (v < 0 ? "−" : "") + "₹" + Math.round(Math.abs(v)).toLocaleString("en-IN");
const srs = v => v == null ? "<span class='muted'>–</span>" : `<span class="${cls(v)}">${v > 0 ? "+" : ""}${rs(v)}</span>`;
const WHY = { target: "Target", stop: "Stop (2nd trigger)", "exit day": "Time exit", "vix brake": "VIX brake", open: "Still open" };

function render() {
  const D = DATA, R = D.rules, H = D.hold, B = D.brake, U = D.unfiltered;
  const lo = R.vixBand[0], hi = R.vixBand[1];
  const skipped = D.monthsList.filter(m => !m.traded).length;
  const h = [];
  h.push(`<button class="theme-btn" id="theme" type="button">Theme</button>
  <h1>NIFTY monthly iron fly: backtest report</h1>
  <p class="sub">One iron fly a month on NIFTY's monthly options, entered only when India VIX is ${lo}–${hi}. ${fdate(D.start)} to ${fdate(D.end)}.</p>
  <nav class="nav"><a href="#results">Results</a><a href="#rules">Rules</a><a href="#margin">Margin &amp; costs</a><a href="#vix">Why VIX ${lo}–${hi}</a><a href="#curve">Equity</a><a href="#years">Yearly</a><a href="#exits">Exits</a><a href="#trades">Trades</a><a href="#months">Months</a><a href="#method">Method</a></nav>

  <h2 id="results" class="first">1. Results</h2>
  <p class="sub">Rupees per sold lot (${R.lot} units) after costs. A set is 1 sold call + 1 sold put + 1 bought call + 1 bought put; the backtest ran ${R.lots} sets and divides by ${R.lots}.</p>
  <div class="tiles">
    <div class="tile"><div class="k">Trades</div><div class="v">${H.trades}</div><div class="c">of ${D.months} months; ${skipped} skipped on VIX</div></div>
    <div class="tile"><div class="k">Winners</div><div class="v">${pct(H.win)}</div><div class="c">average win ${rs(H.avgWin)}</div></div>
    <div class="tile"><div class="k">Average trade</div><div class="v ${cls(H.avg)}">${rs(H.avg)}</div><div class="c">average loss ${rs(H.avgLoss)}</div></div>
    <div class="tile"><div class="k">Total</div><div class="v ${cls(H.total)}">${rs(H.total)}</div><div class="c">≈ ${rs(H.perMonth)} a month over all ${D.months} months</div></div>
    <div class="tile"><div class="k">Worst trade</div><div class="v neg">${rs(H.worst)}</div><div class="c">worst run of losses ${rs(H.maxDD)}</div></div>
    <div class="tile"><div class="k">Average holding</div><div class="v">${H.avgHeld.toFixed(1)} days</div><div class="c">trading days, about ${Math.round(H.avgHeldCal)} calendar days</div></div>
    <div class="tile"><div class="k">Years up</div><div class="v">${H.yearsUp} / ${H.years}</div><div class="c">with the VIX brake: ${B.yearsUp} / ${B.years}</div></div>
  </div>
  ${currentBox()}
  <div class="note"><b>What the backtest says:</b><ul style="margin:6px 0 0;padding-left:20px">
    <li>Most months end at the target (${pct(R.targetFrac)} of the credit received) within about two weeks. ${D.reasons.target.n} of ${H.trades} trades did.</li>
    <li>Losses are rare but large: the average loss (${rs(H.avgLoss)}) is about ${Math.round(-H.avgLoss / H.avgWin)} times the average win, so one stop-out takes back several winning months.</li>
    <li>The VIX filter is what makes it work. Taking every month instead gives ${U.trades} trades, ${pct(U.win)} winners and ${srs(U.total)} in total, with a worst trade of ${rs(U.worst)}.</li>
    <li>The settings (VIX band, one roll, the target) were chosen after testing several versions on this same data, so expect live results to be weaker than these.</li></ul></div>

  <h2 id="rules">2. The rules</h2>
  <div class="card tbl-wrap"><table class="steps"><thead><tr><th>Step</th><th>Rule</th></tr></thead><tbody>
    <tr><td>1. Entry day</td><td>Close of the first trading day after the monthly expiry (about 30 days to the next expiry). One trade per month.</td></tr>
    <tr><td>2. VIX filter</td><td>Enter only if India VIX closes between ${lo} and ${hi} that day. Otherwise skip the month.</td></tr>
    <tr><td>3. Position (per set)</td><td>Sell 1 lot ATM call + 1 lot ATM put (strike nearest the monthly future, rounded to 100). Buy 1 lot call and 1 lot put ${pct(R.wing)} away (rounded to 100).</td></tr>
    <tr><td>4. Target</td><td>Close everything at the first close where profit after costs reaches ${pct(R.targetFrac)} of the net credit received at entry (about ${Math.round(R.targetFrac * 370)} points, or ${rs(R.targetFrac * 370 * R.lot)} per sold lot, on a 370-point credit). Being a share of the premium, it grows with NIFTY's level.</td></tr>
    <tr><td>5. Roll</td><td>If the future closes ${pct(R.rollPct)} or more from the short strike, roll the short call and put to the new ATM strike. The bought wings stay. Only ${R.maxRolls === 1 ? "once" : R.maxRolls + " times"}.</td></tr>
    <tr><td>6. Stop</td><td>If the ${pct(R.rollPct)} trigger hits again after the roll, close everything.</td></tr>
    <tr><td>7. Time exit</td><td>Otherwise close at the close ${R.exitBefore} trading day before expiry.</td></tr>
    <tr><td>8. After entry</td><td>Ignore VIX. Optional emergency brake: close if VIX rises ${pct(R.vixBrake - 1)} or more above its entry level.</td></tr>
  </tbody></table></div>
  ${example()}

  ${marginSection()}

  <h2 id="vix">3. Why VIX ${lo}–${hi}</h2>
  <p class="sub">The same trade taken every month, grouped by India VIX at entry. Below ${lo} the premium is too thin to pay for costs and rolls; above ${hi} NIFTY moves enough to trigger rolls and stops.</p>
  <div class="card tbl-wrap"><table><thead><tr><th>VIX at entry</th><th class="n">Trades</th><th class="n">Winners</th><th class="n">Average trade</th><th class="n">Worst trade</th><th class="n">Total</th></tr></thead><tbody>
    ${D.bands.map(b => `<tr class="${b.lo === lo ? "hl" : ""}"><td>${b.lo === 0 ? "below " + b.hi : b.hi >= 99 ? b.lo + " and above" : b.lo + "–" + b.hi}</td><td class="n">${b.trades}</td><td class="n">${pct(b.win)}</td><td class="n">${srs(b.avg)}</td><td class="n">${srs(b.worst)}</td><td class="n">${srs(b.total)}</td></tr>`).join("")}
    <tr class="muted"><td>Every month (no filter)</td><td class="n">${U.trades}</td><td class="n">${pct(U.win)}</td><td class="n">${srs(U.avg)}</td><td class="n">${srs(U.worst)}</td><td class="n">${srs(U.total)}</td></tr>
  </tbody></table></div>

  <h2 id="curve">4. Equity curve</h2>
  <div class="card"><div class="legend"><span><i style="background:var(--s1)"></i>Rules as above</span><span><i style="background:var(--s2)"></i>With the VIX brake</span></div><div class="chart" id="eqChart"></div>
  <p class="chart-note">Cumulative profit per sold lot, one point per month (flat in skipped months). The brake made ${rs(B.total)} against ${rs(H.total)} without it: it cuts a few losing trades short, but also closes some that would have recovered to the target. Treat it as an emergency option, not a profit rule.</p></div>

  <h2 id="years">5. Year by year</h2><p class="sub">By entry year. ${Object.keys(D.yearly)[0]} and ${Object.keys(D.yearly).slice(-1)[0]} are part years.</p>
  <div class="two"><div class="card"><div class="chart" id="yrChart"></div></div>
  <div class="card tbl-wrap"><table><thead><tr><th>Year</th><th class="n">Trades</th><th class="n">Rules</th><th class="n">With brake</th></tr></thead><tbody>
    ${Object.entries(D.yearly).map(([y, v]) => `<tr><td>${y}</td><td class="n">${v.n}</td><td class="n">${srs(v.hold)}</td><td class="n">${srs(v.brake)}</td></tr>`).join("")}</tbody></table></div></div>

  <h2 id="exits">6. How the trades ended</h2>
  <div class="card tbl-wrap"><table><thead><tr><th>Exit</th><th class="n">Trades</th><th class="n">Total</th><th class="n">Average</th><th class="n">Average days held</th></tr></thead><tbody>
    ${Object.entries(D.reasons).sort((a, b) => b[1].n - a[1].n).map(([k, v]) => { const ts = D.trades.filter(x => x.why === k); return `<tr><td>${WHY[k] || k}</td><td class="n">${v.n}</td><td class="n">${srs(v.pnl)}</td><td class="n">${srs(v.pnl / v.n)}</td><td class="n">${(ts.reduce((a, x) => a + x.held, 0) / ts.length).toFixed(1)}</td></tr>`; }).join("")}</tbody></table></div>

  <h2 id="trades">7. Every trade</h2>
  <p class="sub">Short strikes show each roll (for example 24400 &gt; 23900). Click a column to sort, or <b>Payoff</b> to draw that trade's payoff below the table.</p>
  <div class="card tbl-wrap"><table id="tradeTbl"><thead><tr><th class="sort" data-k="m">Month</th><th class="sort n" data-k="vix">VIX</th><th class="sort" data-k="entry">Entry</th><th class="sort" data-k="exit">Exit</th><th class="sort n" data-k="held">Days</th><th class="sort" data-k="why">How</th><th class="sort n" data-k="fin">Future in</th><th>Short strikes</th><th>Wings</th><th class="sort n" data-k="credit">Credit (pts)</th><th class="sort n" data-k="pnl">Rs / sold lot</th><th class="sort n" data-k="brake">With brake</th><th></th></tr></thead><tbody></tbody></table></div>
  <div class="card payoff" id="payoffCard"></div>

  <h2 id="months">8. Month by month</h2>
  <p class="sub">Every monthly contract in the test with India VIX at entry. Faded months were skipped.</p>
  <div class="mgrid">${D.monthsList.map(m => { const t = D.trades.find(x => x.m === m.month);
    return `<div class="mcell ${m.traded ? "" : "skip"}"><b>${fmonth(m.month)}</b>VIX ${m.vix == null ? "–" : m.vix.toFixed(1)}<br>${t ? srs(t.pnl) : "skipped"}</div>`; }).join("")}</div>

  <h2 id="method">9. Data and method</h2><div class="note"><ul style="margin:0;padding-left:20px">
    <li><b>Prices:</b> NSE's daily F&amp;O bhavcopy for every NIFTY monthly option and future, ${fdate(D.start)} to ${fdate(D.asOf)}. An option's close when it traded that day, otherwise NSE's settle price. India VIX daily closes from Yahoo Finance (^INDIAVIX).</li>
    <li><b>Closes only:</b> every decision (entry, roll, stop, target, exit) uses the day's closing prices. A real trade would fill during the last minutes of the day at slightly different prices; on gap days the stop can come out worse.</li>
    <li><b>Costs:</b> ${R.slipShort} point slippage per lot per order on the sold strikes and ${R.slipWing} on the wings, STT of ${(R.stt * 100).toFixed(1)}% on the premium sold, ₹${R.brokerage} brokerage per order, NSE transaction charges (${(R.exch * 100).toFixed(5)}%) and the SEBI fee on premium traded, stamp duty (${(R.stamp * 100).toFixed(3)}%) on premium bought, and GST (${pct(R.gst)}) on brokerage and fees. Every result on this page is after all of them. Brokerage is per order whatever the lots, so a single set pays a little more per lot than the ${R.lots}-set backtest.</li>
    <li><b>Lot size:</b> ${R.lot} units in every year so the years compare. NSE's NIFTY lot has been 25 to 75 over this period.</li>
    <li><b>Expiry dates:</b> a contract's real expiry is its last trading day (holiday moves and the 2025 switch to Tuesday expiries are followed).</li>
    <li><b>Margin:</b> not modelled. The bought wings cap the loss of each set, but check the margin your broker asks for before trading.</li>
    <li><b>Hindsight:</b> about a dozen variants were tested on this data before settling on these rules (other structures, strangles, rolling rules, filters). The ${lo}–${hi} band held up when moved a point either way and in both halves of the period, but it is still fitted to the past.</li></ul></div>`);
  $("#app").innerHTML = h.join("");
  const rows = D.trades.map(t => ({ ...t, brake: t.brake ?? -1e9 }));
  sortableTable("#tradeTbl", rows, "m", -1, t => `<tr><td>${fmonth(t.m)}</td><td class="n">${t.vix.toFixed(1)}</td><td>${fdate(t.entry)}</td><td>${fdate(t.exit)}</td><td class="n">${t.held}</td><td class="why-${t.why === "stop" ? "stop" : t.why === "target" ? "target" : ""}">${WHY[t.why] || t.why}</td><td class="n">${Math.round(t.fin).toLocaleString("en-IN")}</td><td>${esc(t.shorts)}</td><td>${esc(t.wings)}</td><td class="n">${t.credit.toFixed(1)}</td><td class="n">${srs(t.pnl)}</td><td class="n">${t.brake === -1e9 ? srs(null) : srs(t.brake)}</td><td><button class="pbtn" type="button" data-m="${t.m}">Payoff</button></td></tr>`);
  $("#tradeTbl").addEventListener("click", e => { const b = e.target.closest(".pbtn"); if (b) { payoff(b.dataset.m); $("#payoffCard").scrollIntoView({ behavior: "smooth", block: "nearest" }); } });
  const cur = currentTrade();
  if ($("#curPayoff")) $("#curPayoff").addEventListener("click", () => { payoff("current"); $("#payoffCard").scrollIntoView({ behavior: "smooth", block: "nearest" }); });
  payoff(cur ? "current" : D.trades[D.trades.length - 1].m);
  drawCharts();
  $("#theme").addEventListener("click", () => {
    const dark = getComputedStyle(document.documentElement).colorScheme.includes("dark");
    document.documentElement.dataset.theme = dark ? "light" : "dark";
    drawCharts();
  });
}

function currentTrade() {
  const c = DATA.current;
  if (!c || c.status === "skipped") return null;
  return { m: c.month, vix: c.vix, entry: c.entry, exit: c.exit || c.asOf, why: c.reason || "open", fin: c.future,
    fout: c.markFuture, shorts: c.shorts || String(c.k), wings: `${c.kp}PE/${c.kc}CE`, credit: c.credit, pnl: c.pnl,
    kc: c.kc, kp: c.kp, steps: c.steps, open: c.status === "open" };
}

function currentBox() {
  const c = DATA.current;
  if (!c) return "";
  if (c.status === "skipped") return `<div class="card"><h3 style="margin-top:0">This month (${fmonth(c.month)})</h3><p style="margin:0">Skipped: India VIX closed at ${c.vix == null ? "–" : c.vix.toFixed(2)} on ${fdate(c.entry)}, outside ${DATA.rules.vixBand.join("–")}. Next chance: the day after the ${fdate(c.expiry)} expiry.</p></div>`;
  const legs = Object.entries(c.legs), R = DATA.rules;
  const state = c.status === "open"
    ? `Still open at the ${fdate(c.asOf)} close: NIFTY future ${Math.round(c.markFuture).toLocaleString("en-IN")}, ${srs(c.pnl)} per sold lot if closed then.`
    : `Closed on ${fdate(c.exit)} (${(WHY[c.reason] || c.reason).toLowerCase()}) at ${srs(c.pnl)} per sold lot.`;
  return `<div class="card"><h3 style="margin-top:0">Current trade: ${fmonth(c.month)} (expiry ${fdate(c.expiry)})</h3>
    <p style="margin:0 0 8px">Entered at the ${fdate(c.entry)} close with India VIX at ${c.vix.toFixed(2)} and the ${fmonth(c.month)} future at ${Math.round(c.future).toLocaleString("en-IN")}. ${state}</p>
    <div class="tbl-wrap"><table><thead><tr><th>Leg</th><th class="n">Entry price</th></tr></thead><tbody>
      ${legs.map(([n, px], i) => `<tr><td>${i < 2 ? "Sell" : "Buy"} ${esc(n)}</td><td class="n">${px.toFixed(2)}</td></tr>`).join("")}
      <tr class="hl"><td>Net credit</td><td class="n">${c.credit.toFixed(2)} pts (${rs(c.credit * R.lot)} per set)</td></tr></tbody></table></div>
    <p class="chart-note">Target: profit after costs of ${pct(R.targetFrac)} of the credit, about ${c.targetPts} points (${rs(c.targetPts * R.lot)} per sold lot). Roll the short strikes once if the future closes at or below ${c.rollDown.toLocaleString("en-IN")} or at or above ${c.rollUp.toLocaleString("en-IN")}; close everything on the next trigger. Otherwise close at the close on the trading day before ${fdate(c.expiry)}. <button class="pbtn" type="button" id="curPayoff">Payoff</button></p></div>`;
}

function marginSection() {
  const M = DATA.roi, H = DATA.hold, C = H.costs;
  const KIND = { slip: "Slippage", stt: "STT", brk: "Brokerage", exch: "NSE transaction charges and SEBI fee", gst: "GST", stamp: "Stamp duty" };
  const p1 = v => pct(v, 1);
  return `<h2 id="margin">Return on margin and costs</h2>
  <p class="sub">${esc(M.note)}. Margin moves roughly with NIFTY, so the "scaled" figures size each trade's margin by NIFTY at its entry (today's quote applies at NIFTY ${M.niftyNow.toLocaleString("en-IN")}). Simple returns, not compounded, before tax.</p>
  <div class="tiles">
    <div class="tile"><div class="k">Margin per set</div><div class="v">${rs(M.margin)}</div><div class="c">₹3,50,000 for 5 sets</div></div>
    <div class="tile"><div class="k">Return a year</div><div class="v pos">${p1(M.scaledYear)}</div><div class="c">scaled; ${p1(M.flatYear)} on a flat ${rs(M.margin)}</div></div>
    <div class="tile"><div class="k">Average trade</div><div class="v">${p1(M.scaledTrade)}</div><div class="c">of margin, in about ${Math.round(H.avgHeldCal)} days</div></div>
    <div class="tile"><div class="k">Worst trade</div><div class="v neg">${p1(M.scaledWorst)}</div><div class="c">of margin (${rs(H.worst)})</div></div>
    <div class="tile"><div class="k">Margin in use</div><div class="v">${pct(M.deployed)}</div><div class="c">of the time; free otherwise</div></div>
  </div>
  <div class="two"><div class="card tbl-wrap"><table><thead><tr><th>Year</th><th class="n">Trades</th><th class="n">Return on margin</th></tr></thead><tbody>
    ${M.byYear.map((y, i) => `<tr><td>${y.year}${i === 0 || i === M.byYear.length - 1 ? " (part)" : ""}</td><td class="n">${y.trades}</td><td class="n"><span class="${cls(y.roi)}">${p1(y.roi)}</span></td></tr>`).join("")}
    <tr class="hl"><td>Full years, average</td><td class="n"></td><td class="n">${p1(M.scaledFullYears)}</td></tr></tbody></table></div>
  <div class="card tbl-wrap"><table><thead><tr><th>Costs per sold lot, ten years</th><th class="n">Total</th><th class="n">Per trade</th></tr></thead><tbody>
    <tr><td>Profit before costs</td><td class="n">${srs(H.gross)}</td><td class="n">${srs(H.gross / H.trades)}</td></tr>
    ${Object.entries(KIND).map(([k, n]) => `<tr><td>${n}</td><td class="n">${rs(-C[k])}</td><td class="n">${rs(-C[k] / H.trades)}</td></tr>`).join("")}
    <tr><td><b>All costs</b></td><td class="n"><b>${rs(-H.cost)}</b></td><td class="n"><b>${rs(-H.avgCost)}</b></td></tr>
    <tr class="hl"><td>Profit after costs</td><td class="n">${srs(H.total)}</td><td class="n">${srs(H.avg)}</td></tr></tbody></table>
    <p class="chart-note">Costs take ${pct(H.cost / H.gross)} of the profit before costs. Slippage is the largest: with worse fills the result falls quickly.</p></div></div>`;
}

function example() {
  const t = DATA.trades[DATA.trades.length - 1], R = DATA.rules;
  return `<div class="note"><b>Latest trade (${fmonth(t.m)}):</b> on ${fdate(t.entry)} NIFTY's monthly future closed at ${Math.round(t.fin).toLocaleString("en-IN")} and India VIX at ${t.vix.toFixed(2)}, inside the band. Sold the ${esc(t.shorts.split(" > ")[0])} call and put, bought the ${esc(t.wings.replace("/", " and "))}, for a net credit of ${t.credit.toFixed(1)} points (${rs(t.credit * R.lot)} per set). It ended on ${fdate(t.exit)} (${(WHY[t.why] || t.why).toLowerCase()}) at ${srs(t.pnl)} per sold lot.</div>`;
}

function barChart(el, { cats, vals, height }) {
  const W = Math.max(300, el.clientWidth), Hh = height, m = { l: 56, r: 10, t: 10, b: 28 };
  const hi = Math.max(0, ...vals), lo = Math.min(0, ...vals);
  const y = v => m.t + (1 - (v - lo) / (hi - lo || 1)) * (Hh - m.t - m.b);
  const bw = (W - m.l - m.r) / cats.length;
  let svg = `<svg class="bars" viewBox="0 0 ${W} ${Hh}" role="img">`;
  for (let k = 0; k <= 4; k++) { const t = lo + (hi - lo) * k / 4; svg += `<line x1="${m.l}" x2="${W - m.r}" y1="${y(t)}" y2="${y(t)}" stroke="${css("--grid")}"/><text x="${m.l - 6}" y="${y(t) + 4}" text-anchor="end">${rs(t)}</text>`; }
  svg += `<line x1="${m.l}" x2="${W - m.r}" y1="${y(0)}" y2="${y(0)}" stroke="${css("--muted")}"/>`;
  cats.forEach((c, i) => {
    const v = vals[i], top = y(Math.max(v, 0)), hgt = Math.abs(y(v) - y(0));
    svg += `<rect x="${m.l + i * bw + bw * 0.18}" y="${top}" width="${bw * 0.64}" height="${Math.max(hgt, 0.5)}" rx="2" fill="${css(v >= 0 ? "--s1" : "--neg")}"><title>${c}: ${rs(v)}</title></rect>`;
    svg += `<text x="${m.l + i * bw + bw / 2}" y="${Hh - 8}" text-anchor="middle">${c}</text>`;
  });
  el.innerHTML = svg + "</svg>";
}

function drawCharts() {
  const step = v => { const p = Math.pow(10, Math.floor(Math.log10(v || 1))); return [1, 2, 2.5, 5, 10].map(k => k * p).find(s => v / s <= 6); };
  lineChart($("#eqChart"), { height: 320, log: false, fmtY: t => rs(t),
    ticksY: (lo, hi) => { const s = step(hi - lo), o = []; for (let t = Math.ceil(lo / s) * s; t <= hi + 1e-9; t += s) o.push(t); return o; },
    series: [{ k: "brake", name: "With the VIX brake", c: "--s2", w: 1.3, fmt: rs }, { k: "hold", name: "Rules as above", c: "--s1", w: 2.4, fmt: rs }] });
  const Y = DATA.yearly;
  barChart($("#yrChart"), { height: 240, cats: Object.keys(Y), vals: Object.values(Y).map(v => v.hold) });
  if (shownPayoff) payoff(shownPayoff);
}

let shownPayoff = null;
function payoff(m) {
  shownPayoff = m;
  document.querySelectorAll(".pbtn").forEach(b => b.classList.toggle("on", b.dataset.m === m));
  const t = m === "current" ? currentTrade() : DATA.trades.find(x => x.m === m), L = DATA.rules.lot, el = $("#payoffCard");
  const wing = Math.max(t.kc - t.steps[0].k, t.steps[0].k - t.kp);
  const strikes = [t.kp, t.kc, ...t.steps.map(p => p.k), t.fin, t.fout].filter(v => v);
  const x0 = Math.min(...strikes) - wing * 0.8, x1 = Math.max(...strikes) + wing * 0.8;
  const pay = (p, S) => (p.cash - Math.abs(S - p.k) + Math.max(S - t.kc, 0) + Math.max(t.kp - S, 0)) * L;
  const knots = p => [x0, t.kp, p.k, t.kc, x1].sort((a, b) => a - b);
  const all = t.steps.flatMap(p => knots(p).map(S => pay(p, S)));
  const lo = Math.min(0, ...all), hi = Math.max(0, ...all);
  const W = Math.max(320, el.clientWidth - 32), H = 280, mg = { l: 64, r: 14, t: 16, b: 30 };
  const X = S => mg.l + (S - x0) / (x1 - x0) * (W - mg.l - mg.r);
  const Yy = v => mg.t + (1 - (v - lo) / (hi - lo || 1)) * (H - mg.t - mg.b);
  const cols = ["--s1", "--s2", "--s3"];
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Payoff at expiry">`;
  for (let k = 0; k <= 4; k++) { const v = lo + (hi - lo) * k / 4; svg += `<line x1="${mg.l}" x2="${W - mg.r}" y1="${Yy(v)}" y2="${Yy(v)}" stroke="${css("--grid")}"/><text x="${mg.l - 6}" y="${Yy(v) + 4}" text-anchor="end">${rs(v)}</text>`; }
  svg += `<line x1="${mg.l}" x2="${W - mg.r}" y1="${Yy(0)}" y2="${Yy(0)}" stroke="${css("--muted")}"/>`;
  [t.kp, ...new Set(t.steps.map(p => p.k)), t.kc].forEach(S => svg += `<text x="${X(S)}" y="${H - 10}" text-anchor="middle">${S}</text>`);
  t.steps.forEach((p, i) => {
    const d = knots(p).map((S, j) => `${j ? "L" : "M"}${X(S).toFixed(1)},${Yy(pay(p, S)).toFixed(1)}`).join("");
    svg += `<path d="${d}" fill="none" stroke="${css(cols[i % 3])}" stroke-width="${i === t.steps.length - 1 ? 2.4 : 1.5}" ${i < t.steps.length - 1 ? 'stroke-dasharray="5 4"' : ""}/>`;
  });
  const mark = (S, label, c) => S ? `<line x1="${X(S)}" x2="${X(S)}" y1="${mg.t}" y2="${H - mg.b}" stroke="${css(c)}" stroke-dasharray="2 3"/><text x="${X(S) + 4}" y="${mg.t + 10}" style="fill:${css(c)}">${label} ${Math.round(S)}</text>` : "";
  svg += mark(t.fin, "entry", "--text-2") + mark(t.fout, t.open ? "now" : "exit", t.pnl >= 0 ? "--good" : "--bad") + "</svg>";
  const facts = t.steps.map((p, i) => {
    const ks = knots(p), vals = ks.map(S => pay(p, S)), be = [];
    for (let j = 1; j < ks.length; j++) { const a = vals[j - 1], c = vals[j];
      if ((a < 0 && c >= 0) || (a >= 0 && c < 0)) be.push(Math.round(ks[j - 1] + (ks[j] - ks[j - 1]) * (0 - a) / (c - a))); }
    return `<span><i style="display:inline-block;width:14px;height:2px;vertical-align:middle;margin-right:6px;background:${css(cols[i % 3])}"></i><b>${i ? "After roll on " + fdate(p.d) : "At entry"}:</b> short ${p.k}, net credit ${p.cash.toFixed(1)} pts · max profit ${rs(Math.max(...vals))} · max loss ${rs(Math.min(...vals))} · ${be.length ? "breakeven " + be.join(" and ") : "no breakeven in range"}</span>`; }).join("");
  el.innerHTML = `<h3 style="margin-top:0">Payoff at expiry: ${fmonth(t.m)} trade${t.open ? " (open)" : ""} (per set, before costs)</h3>${svg}<div class="facts">${facts}<span><b>${t.open ? "So far" : "Result"}:</b> ${t.open ? `at the ${fdate(t.exit)} close, ${srs(t.pnl)} per sold lot after costs if closed then` : `${(WHY[t.why] || t.why).toLowerCase()} on ${fdate(t.exit)}, ${srs(t.pnl)} per sold lot after costs`}</span></div>
    <p class="chart-note">The lines show what the position would be worth at expiry with NIFTY at each level; ${t.open ? "the trade is still open and will be closed by its own rules, at the latest the day before expiry." : "the trade itself was closed earlier, on its exit day, at market prices."} Bought wings ${t.kp} put and ${t.kc} call stay through any roll. ${t.steps.length > 1 ? "Dashed = the position before the roll; the solid line includes the loss booked by rolling." : ""}</p>`;
}

render();
let rz; addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(drawCharts, 150); });
if (matchMedia) matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", drawCharts);
"""

TITLE = "NIFTY Monthly Iron Fly Report"
DESC = ("Backtest of a NIFTY monthly iron fly entered only when India VIX is 12-17, with one roll, a stop and a "
        "profit target of 12% of the credit received, on ten years of NSE option prices: rules, results, every trade.")
page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{TITLE}</title>
<meta name="description" content="{DESC}">
{style}
{EXTRA_CSS}
</head>
<body>
<div class="wrap site-top"><a class="site-back" href="../index.html">&larr; Let Money Earn</a></div>
<div class="wrap" id="app"></div>
<div class="wrap site-bottom"><p class="site-disclaimer"><b>Important disclaimer.</b> This is a backtest for educational purposes only, not investment advice or a recommendation to trade any security or derivative. Options trading can lose more than expected, past results do not predict future returns, and settings fitted to past data usually do worse live. The author is not a SEBI registered financial adviser. Do your own due diligence and consult a qualified financial adviser before acting.</p></div>
<script>
const DATA = {json.dumps(data, separators=(",", ":")).replace("</", "<\\/")};
{helpers}
{charts}
{SCRIPT}
</script>
</body>
</html>
"""
(HERE / "iron_fly_report.html").write_text(page, encoding="utf-8")

# ---- public one-page summary (nifty-iron-fly.html): results only, no rules and no trade details (those are in
# the handbook). Site style: styles.css, the layout of gold-vs-nifty.html, header and footer from sheets.html.
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
day = lambda d: f"{int(d[8:])} {MONTHS[int(d[5:7]) - 1]} {d[:4]}"
site = (ROOT / "sheets.html").read_text(encoding="utf-8")
header = re.search(r'(?:<div class="top-strip">.*?</div>\s*)?<header class="site-header">.*?</header>', site, re.S).group(0)
site_footer = re.search(r"<footer>.*?</footer>", site, re.S).group(0)
gold = (ROOT / "gold-vs-nifty.html").read_text(encoding="utf-8")
gn_style = re.search(r"<style>.*?</style>", gold, re.S).group(0)
disclaimer = re.search(r'<aside class="disclaimer">.*?</aside>', gold, re.S).group(0).replace(
    "past results do not guarantee future returns.", "past results do not guarantee future returns. Options can lose more than expected.")


def inr(v, sign=False):
    s = str(round(abs(v)))
    if len(s) > 3:
        head_, tail_ = s[:-3], s[-3:]
        groups = []
        while len(head_) > 2:
            groups.insert(0, head_[-2:])
            head_ = head_[:-2]
        s = ",".join(([head_] if head_ else []) + groups) + "," + tail_
    return ("−" if v < 0 else "+" if sign and v > 0 else "") + "₹" + s


def lakh(v):
    return ("−" if v < 0 else "") + f"₹{abs(v) / 1e5:.2f} lakh"


R, Hs, Us, RO = data["rules"], data["hold"], data["unfiltered"], data["roi"]
pc = lambda v: f"{v:.0%}"
fmt_pct = lambda v: f"{v:.1%}".replace("-", "−")
COST_NAMES = dict(slip="Slippage", stt="STT", brk="Brokerage", exch="NSE and SEBI charges", gst="GST", stamp="Stamp duty")
cost_rows = "".join(f"<tr><td>{n}</td><td>{inr(-Hs['costs'][k])}</td><td>{inr(-Hs['costs'][k] / Hs['trades'])}</td></tr>"
                    for k, n in COST_NAMES.items())
years = list(data["yearly"].items())
year_rows = "".join(f"<tr><td>{y}{' (part)' if i in (0, len(years) - 1) else ''}</td><td>{v['n']}</td><td>{inr(v['hold'], True)}</td></tr>"
                    for i, (y, v) in enumerate(years))
ONE_TITLE = "NIFTY Monthly Iron Fly | Let Money Earn"
ONE_DESC = (f"A rule-based NIFTY monthly iron fly with defined risk: {Hs['trades']} trades, {pc(Hs['win'])} winners and "
            f"{lakh(Hs['total'])} per sold lot in a ten-year backtest on NSE option prices, after costs.")
ONE_URL = "https://letmoneyearn.in/nifty-iron-fly.html"
LOGO = "https://raw.githubusercontent.com/mscratnesh/htmlSite/main/images/Let_Money_Earn_Logo_Cropped.png"
one = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="{ONE_DESC}">
  <link rel="canonical" href="{ONE_URL}">
  <meta name="robots" content="index, follow">
  <title>{ONE_TITLE}</title>
<link rel="icon" type="image/png" href="{LOGO}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="Let Money Earn">
  <meta property="og:title" content="{ONE_TITLE}">
  <meta property="og:description" content="{ONE_DESC}">
  <meta property="og:url" content="{ONE_URL}">
  <meta property="og:image" content="{LOGO}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{ONE_TITLE}">
  <meta name="twitter:description" content="{ONE_DESC}">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=Manrope:wght@400;500;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="styles.css">
  {gn_style}
  <style>.gn-table td:last-child{{white-space:nowrap}}.gn-list strong{{color:var(--ink)}}.gn-years tbody tr:first-child td{{font:inherit;font-size:15px}}</style>
</head>
<body>
  {header}
  <main>
    <section class="gn-hero">
      <p class="eyebrow">Research · NIFTY options · monthly iron fly</p>
      <h1>NIFTY Monthly Iron Fly</h1>
      <p>A rule-based options strategy on NIFTY's monthly expiry: at most one iron fly a month, with the loss capped by bought options on both sides, taken only when market conditions suit it and closed by fixed exits.</p>
      <p>This page shows what the rules did over ten years of real NSE option prices, after all trading costs. The exact rules are in the handbook.</p>
      <p class="gn-stamp">Tested {day(data['start'])} to {day(data['end'])} · NSE monthly option prices · per sold lot of {R['lot']}</p>
    </section>

    <section class="gn-section"><div class="section-label"><span>The idea</span><span>Rules, not forecasts</span></div>
      <div class="gn-cols">
        <div><h2>Sell premium, cap the risk</h2><p>An iron fly sells at-the-money options and buys protection further out. It earns as option premium melts, and the bought options put a <strong>known limit on the loss</strong>.</p></div>
        <div><h2>Selective, not every month</h2><p>The rules trade only when conditions have favoured this kind of trade, and sit out the rest. In the test that was <strong>{Hs['trades']} of {data['months']} months</strong>.</p></div>
        <div><h2>Fixed exits</h2><p>Every trade has a set profit target, one adjustment if NIFTY moves, and a stop. All decisions are made at the day's close, so the rules can be followed <strong>without watching the screen</strong>.</p></div>
      </div>
    </section>

    <section class="gn-section"><div class="section-label"><span>Backtest</span><span>{day(data['start'])} – {day(data['end'])}</span></div>
      <p class="gn-lead">{Hs['trades']} trades, {pc(Hs['win'])} winners and {lakh(Hs['total'])} per sold lot{", with every year positive" if Hs['yearsUp'] == Hs['years'] else ""}.</p>
      <p class="gn-sub">The selection is what makes it work: the same trade taken every month, with no selection, made {inr(Us['total'], True)} over the same period.</p>
      <table class="gn-table">
        <thead><tr><th></th><th>With the rules</th><th>Every month, no selection</th></tr></thead>
        <tbody>
          <tr><td>Total profit per sold lot</td><td>{inr(Hs['total'], True)}</td><td>{inr(Us['total'], True)}</td></tr>
          <tr><td>Trades</td><td>{Hs['trades']}</td><td>{Us['trades']}</td></tr>
          <tr><td>Winning trades</td><td>{pc(Hs['win'])}</td><td>{pc(Us['win'])}</td></tr>
          <tr><td>Average trade</td><td>{inr(Hs['avg'], True)}</td><td>{inr(Us['avg'], True)}</td></tr>
          <tr><td>Average losing trade</td><td>{inr(Hs['avgLoss'])}</td><td>{inr(Us['avgLoss'])}</td></tr>
          <tr><td>Worst trade</td><td>{inr(Hs['worst'])}</td><td>{inr(Us['worst'])}</td></tr>
          <tr><td>Average holding period</td><td>{Hs['avgHeld']:.1f} days</td><td>{Us['avgHeld']:.1f} days</td></tr>
          <tr><td>Years with a profit</td><td>{Hs['yearsUp']} of {Hs['years']}</td><td>{Us['yearsUp']} of {Us['years']}</td></tr>
        </tbody>
      </table>
      <p class="gn-note">Holding period in trading days, entry to exit (with the rules, about {Hs['avgHeldCal']:.0f} calendar days). Per sold lot of {R['lot']} units in every year, after all costs: slippage, STT, brokerage, NSE and SEBI charges, stamp duty and GST. Decisions use daily closing prices. A backtest shows what the rules would have done, not what they will do.</p>
    </section>

    <section class="gn-section"><div class="section-label"><span>Return on margin</span><span>₹{RO['margin']:,} margin per set</span></div>
      <p class="gn-lead">About {RO['scaledFullYears']:.0%}–{RO['scaledYear']:.0%} a year on margin, after all costs.</p>
      <p class="gn-sub">{RO['note']}. Margin moves roughly with NIFTY, so the scaled column sizes each trade's margin by NIFTY at its entry. Simple returns, not compounded, before tax.</p>
      <table class="gn-table">
        <thead><tr><th></th><th>Margin scaled to NIFTY</th><th>Flat ₹{RO['margin']:,}</th></tr></thead>
        <tbody>
          <tr><td>Return a year on margin</td><td>{RO['scaledYear']:.1%}</td><td>{RO['flatYear']:.1%}</td></tr>
          <tr><td>Average trade, share of margin</td><td>{RO['scaledTrade']:.1%}</td><td>{RO['flatTrade']:.1%}</td></tr>
          <tr><td>Worst trade, share of margin</td><td>{fmt_pct(RO['scaledWorst'])}</td><td>{fmt_pct(RO['flatWorst'])}</td></tr>
          <tr><td>Margin in use</td><td>{RO['deployed']:.0%} of the time</td><td>{RO['deployed']:.0%} of the time</td></tr>
        </tbody>
      </table>
      <table class="gn-table gn-years" style="margin-top:22px">
        <thead><tr><th>Costs per sold lot, ten years</th><th>Total</th><th>Per trade</th></tr></thead>
        <tbody>
          <tr><td>Profit before costs</td><td>{inr(Hs['gross'], True)}</td><td>{inr(Hs['gross'] / Hs['trades'], True)}</td></tr>
          {cost_rows}
          <tr><td>All costs</td><td>{inr(-Hs['cost'])}</td><td>{inr(-Hs['avgCost'])}</td></tr>
          <tr><td>Profit after costs</td><td>{inr(Hs['total'], True)}</td><td>{inr(Hs['avg'], True)}</td></tr>
        </tbody>
      </table>
      <p class="gn-note">Margin changes with NIFTY's level, volatility and the broker's rules; check yours before trading and keep a buffer for adjustment days. F&amp;O profits are taxed as business income.</p>
    </section>

    <section class="gn-section"><div class="section-label"><span>Year by year</span><span>Profit per sold lot</span></div>
      <table class="gn-table gn-years"><thead><tr><th>Year</th><th>Trades</th><th>Profit</th></tr></thead><tbody>{year_rows}</tbody></table>
      <p class="gn-note">By the year a trade was opened. The first and last years are part years.</p>
    </section>

    <section class="gn-section"><div class="section-label"><span>Know before you use it</span><span>Honest limits</span></div>
      <ul class="gn-list">
        <li><strong>Losses are rare but large.</strong> The average loss ({inr(Hs['avgLoss'])}) is about {round(-Hs['avgLoss'] / Hs['avgWin'])} times the average win, so one bad month takes back several good ones.</li>
        <li><strong>Fitted to the past.</strong> The rules were chosen after testing many versions on this same data. Expect live results to be weaker.</li>
        <li><strong>Closing prices only.</strong> Every decision uses the day's close. Real fills differ, and a gap open can push a loss past the stop.</li>
        <li><strong>Margin and liquidity.</strong> Selling options needs margin even with protection bought. Size so a {inr(Hs['worst'])} month is affordable.</li>
        <li><strong>Not every month.</strong> About half the months are skipped, so profits come in bursts with flat stretches between.</li>
        <li><strong>Small sample.</strong> {Hs['trades']} trades over ten years. A few unusual months could change the picture.</li>
      </ul>
    </section>

    <section class="book-band"><div><p class="eyebrow">The handbook · ₹500</p><h2>NIFTY Iron Fly:<br><em>the complete rules.</em></h2><p>Everything behind this page, in a Word handbook: the exact entry, exit and adjustment rules with worked examples, all {Hs['trades']} trades, and a checklist to run it at your broker.</p><a class="book-link" href="contact.html">Ask for the handbook</a></div>
      <ul>
        <li>The exact rules, step by step, with the numbers</li>
        <li>Worked examples, including a trade that needed the adjustment</li>
        <li>Every trade with strikes, adjustments and results</li>
        <li>Why the selection filter matters, band by band</li>
        <li>Costs, margin, a daily routine and the risks</li>
      </ul>
    </section>

    {disclaimer}
  </main>
  {site_footer}
  <script src="nav.js"></script>
</body>
</html>
"""
(ROOT / "nifty-iron-fly.html").write_text(one, encoding="utf-8")


# ---- unlisted public copy of the full report (iron-fly-study.html): the site's header, hero and footer instead of
# the back link. Nothing on the site links to it and it is marked noindex; it is reached only by its address.
# Header styles come from study/breakout_report.py so they stay in sync with the site.
breakout_src = (HERE / "breakout_report.py").read_text(encoding="utf-8")
site_styles = re.search(r'(<link rel="icon".*?</style>)', breakout_src, re.S).group(1)
lo, hi = data["rules"]["vixBand"]
SITE_HEAD = f"""<meta name="robots" content="noindex, nofollow">
{site_styles}
"""
hero = f"""<section class="study-hero"><div>
  <p class="eyebrow">Research · NIFTY options · monthly iron fly</p>
  <h1>NIFTY Monthly Iron Fly Study</h1>
  <p>One iron fly a month on NIFTY's monthly options: sell the ATM call and put, buy wings {data['rules']['wing']:.0%} away, roll the short strikes once if NIFTY moves {data['rules']['rollPct']:.0%}, and take profit at {data['rules']['targetFrac']:.0%} of the credit received. The trade is taken only when India VIX is between {lo} and {hi}.</p>
  <p>Tested on every NIFTY monthly option price NSE published, with every trading cost charged on every order: slippage, STT, brokerage, NSE and SEBI charges, stamp duty and GST.</p>
  <p class="stamp">Tested {day(data["start"])} to {day(data["end"])} · per sold lot · fixed snapshot</p>
</div></section>"""
footer = site_footer.replace("<footer>", '<footer class="site-footer">', 1)
back = '<div class="wrap site-top"><a class="site-back" href="../index.html">&larr; Let Money Earn</a></div>'
for part in (f"<title>{TITLE}</title>", "</head>", back, "</body>"):
    assert page.count(part) == 1, part
public = (page.replace(f"<title>{TITLE}</title>", "<title>NIFTY Monthly Iron Fly Study | Let Money Earn</title>")
          .replace("</head>", SITE_HEAD + "</head>")
          .replace(back, header + "\n" + hero)
          .replace("</body>", footer + '\n<script src="nav.js"></script>\n</body>'))
(ROOT / "iron-fly-study.html").write_text(public, encoding="utf-8")
print("wrote study/iron_fly_report.html, nifty-iron-fly.html and iron-fly-study.html (unlisted)")
