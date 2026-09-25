"""Detailed month-by-month report for the ETF momentum rotation.

Reuses the look, chart and sortable-table code of study/backtest_report_template.html and fills it
with etf_study.json (run study/etf_study.py first).
Output: study/etf_report.html
Run: py study/etf_report.py
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
data = json.loads((ROOT / "etf_study.json").read_text(encoding="utf-8"))

SCRIPT = r"""
const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pct = (v, dp = 1, sign = false) => v == null || isNaN(v) ? "–" : (sign && v > 0 ? "+" : "") + (v * 100).toFixed(dp) + "%";
const cls = v => v > 0 ? "pos" : v < 0 ? "neg" : "";
const spct = (v, dp = 1) => `<span class="${cls(v)}">${pct(v, dp, true)}</span>`;
const MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const fdate = d => d ? `${+d.slice(8, 10)} ${MON[+d.slice(5, 7) - 1]} ${d.slice(0, 4)}` : "–";
const fmonth = d => `${MON[+d.slice(5, 7) - 1]} ${d.slice(0, 4)}`;
const inr = v => "₹" + v.toFixed(2);

function render() {
  const D = DATA, S = D.stats, s = S[0], n = S[1], g = S[2], P = D.base, T = D.trades;
  const h = [];
  h.push(`<button class="theme-btn" id="theme" type="button">Theme</button>
  <h1>ETF momentum rotation: detailed backtest</h1>
  <p class="sub">${Object.keys(D.listed).length + 1} NSE ETFs, each eligible only once it was trading and had a year of prices. ${fdate(s.from)} to ${fdate(s.to)}.</p>
  <nav class="nav"><a href="#summary">Summary</a><a href="#curve">Equity curve</a><a href="#years">Yearly</a><a href="#months">Monthly</a><a href="#dd">Falls</a><a href="#held">What it held</a><a href="#log">Month-by-month log</a><a href="#alltrades">All trades</a><a href="#method">Method</a></nav>
  <h2 id="summary" class="first">1. Summary</h2>
  <div class="tiles">
    <div class="tile"><div class="k">CAGR</div><div class="v">${pct(s.cagr)}</div><div class="c">NIFTYBEES ${pct(n.cagr)} · GOLDBEES ${pct(g.cagr)}</div></div>
    <div class="tile"><div class="k">Worst fall</div><div class="v">${pct(s.maxDD)}</div><div class="c">NIFTYBEES ${pct(n.maxDD)}</div></div>
    <div class="tile"><div class="k">Sharpe</div><div class="v">${s.sharpe.toFixed(2)}</div><div class="c">NIFTYBEES ${n.sharpe.toFixed(2)}</div></div>
    <div class="tile"><div class="k">₹1 became</div><div class="v">${inr(s.multiple)}</div><div class="c">NIFTYBEES ${inr(n.multiple)}</div></div>
    <div class="tile"><div class="k">Trades</div><div class="v">${T.count}</div><div class="c">${pct(T.winRate, 0)} winners, median hold ${Math.round(T.medianDays)} days</div></div>
  </div>
  <div class="card tbl-wrap"><table><thead><tr><th></th><th class="n">CAGR</th><th class="n">Worst fall</th><th class="n">Volatility</th><th class="n">Sharpe</th><th class="n">Calmar</th><th class="n">₹1 became</th></tr></thead>
    <tbody>${S.map((x, i) => `<tr class="${i ? "" : "hl"}"><td>${esc(x.label)}</td><td class="n">${pct(x.cagr)}</td><td class="n">${pct(x.maxDD)}</td><td class="n">${pct(x.vol)}</td><td class="n">${x.sharpe.toFixed(2)}</td><td class="n">${x.calmar.toFixed(2)}</td><td class="n">${inr(x.multiple)}</td></tr>`).join("")}</tbody></table></div>
  <p class="muted" style="font-size:13px">Since all the ETFs were trading (${fdate(D.sinceAllListed.from)}): strategy ${pct(D.sinceAllListed.strategy.cagr)} a year, NIFTYBEES ${pct(D.sinceAllListed.nifty.cagr)}, GOLDBEES ${pct(D.sinceAllListed.gold.cagr)}. On average ${pct(D.avgCash, 0)} of the money sat in cash.</p>
  <h3>The rules tested</h3>
  <div class="card"><ul class="rules" style="margin:0;padding-left:20px">
    <li><b>ETFs:</b> ${Object.keys(D.listed).sort().join(", ")}. LIQUIDCASE is used as cash.</li>
    <li><b>Score:</b> for ${P.lookbacks.join(", ")} trading days, % return ÷ annualised volatility; the average of the four.</li>
    <li><b>Filters:</b> within ${pct(P.max_fall, 0)} of the all-time high, above the ${P.sma_days}-day average, average daily turnover above ₹${P.min_turnover / 1e7} crore.</li>
    <li><b>Portfolio:</b> top ${P.top_n}, each a 1/${P.top_n} slot when bought. Sell when it falls below rank ${P.exit_rank} or fails a filter. Empty slots wait in LIQUIDCASE (a 6.5% a year liquid fund before it existed).</li>
    <li><b>Timing:</b> last trading day of each month. No market safety switch.</li>
    <li><b>Costs:</b> ${pct(P.cost, 2)} on every buy and sell. No tax.</li>
  </ul></div>
  <h2 id="curve">2. Equity curve and drawdowns</h2>
  <div class="card"><div class="legend"><span><i style="background:var(--s1);height:3px"></i>ETF momentum</span><span><i style="background:var(--s2)"></i>NIFTYBEES</span><span><i style="background:var(--s4)"></i>GOLDBEES</span></div><div class="chart" id="eqChart"></div></div>
  <h3>Drawdown</h3><div class="card"><div class="legend"><span><i style="background:var(--s1);height:3px"></i>ETF momentum</span><span><i style="background:var(--s2)"></i>NIFTYBEES</span></div><div class="chart" id="ddChart"></div></div>`);
  const ys = Object.keys(D.yearly.strategy);
  h.push(`<h2 id="years">3. Year by year</h2><div class="card tbl-wrap"><table><thead><tr><th>Year</th><th class="n">ETF momentum</th><th class="n">NIFTYBEES</th><th class="n">GOLDBEES</th></tr></thead>
    <tbody>${ys.map(y => `<tr><td>${y}</td><td class="n">${spct(D.yearly.strategy[y])}</td><td class="n">${spct(D.yearly.nifty[y])}</td><td class="n">${spct(D.yearly.gold[y])}</td></tr>`).join("")}</tbody></table></div>`);
  const mm = Object.fromEntries(D.monthly.strategy), myears = [...new Set(D.monthly.strategy.map(([m]) => m.slice(0, 4)))];
  const cell = v => v == null ? `<td class="n muted">·</td>` : `<td class="n" style="background:color-mix(in srgb, ${v >= 0 ? "var(--pos)" : "var(--neg)"} ${Math.round(Math.min(Math.abs(v) / 0.1, 1) * 55)}%, var(--mid))">${pct(v, 1, true)}</td>`;
  h.push(`<h2 id="months">4. Month by month</h2><div class="card tbl-wrap"><table class="heat"><thead><tr><th>Year</th>${MON.map(m => `<th class="n">${m}</th>`).join("")}</tr></thead>
    <tbody>${myears.map(y => `<tr><td>${y}</td>${MON.map((_, i) => cell(mm[`${y}-${String(i + 1).padStart(2, "0")}`])).join("")}</tr>`).join("")}</tbody></table></div>`);
  h.push(`<h2 id="dd">5. Biggest falls</h2><div class="card tbl-wrap"><table><thead><tr><th>From high on</th><th>Lowest on</th><th class="n">Fall</th><th>Back to high</th></tr></thead>
    <tbody>${D.drawdowns.map(x => `<tr><td>${fdate(x.peak)}</td><td>${fdate(x.trough)}</td><td class="n">${spct(x.depth)}</td><td>${x.recovered ? fdate(x.recovered) : "<span class='muted'>not yet</span>"}</td></tr>`).join("")}</tbody></table></div>`);
  const held = Object.entries(D.monthsHeld), never = Object.keys(D.listed).filter(k => !D.monthsHeld[k]);
  h.push(`<h2 id="held">6. What it held</h2><p class="sub">Months each ETF spent in the portfolio, out of ${D.months}. Never held: ${never.join(", ") || "none"}.</p>
    <div class="card tbl-wrap"><table><thead><tr><th>ETF</th><th>Trading since</th><th class="n">Months held</th><th class="n">Share of months</th></tr></thead>
    <tbody>${held.map(([k, v]) => `<tr><td><b>${esc(k)}</b></td><td>${fdate(D.listed[k])}</td><td class="n">${v}</td><td class="n">${pct(v / D.months, 0)}</td></tr>`).join("")}${never.map(k => `<tr><td class="muted">${esc(k)}</td><td>${fdate(D.listed[k])}</td><td class="n">0</td><td class="n">0%</td></tr>`).join("")}</tbody></table></div>`);
  h.push(`<h2 id="log">7. Month-by-month log</h2><p class="sub">Each month-end: the ETFs that passed the filters and their scores, what was sold and why, what was bought, the portfolio until the next month-end with each ETF's return, and why the others were left out.</p>
    <div class="filters"><label>Year <select id="fYear"><option value="">All</option>${myears.map(y => `<option>${y}</option>`).join("")}</select></label><label>ETF <input id="fEtf" placeholder="e.g. GOLDBEES" size="12"></label><span class="muted" id="fCount"></span></div><div id="monthLog"></div>`);
  h.push(`<h2 id="alltrades">8. All trades</h2><div class="card tbl-wrap"><table id="tradeTbl"><thead><tr><th class="sort" data-k="s">ETF</th><th class="sort" data-k="in">Bought</th><th class="sort" data-k="out">Sold</th><th class="sort n" data-k="days">Days</th><th class="sort n" data-k="ret">Return</th></tr></thead><tbody></tbody></table></div>`);
  h.push(`<h2 id="method">9. Data and method</h2><div class="note"><ul style="margin:0;padding-left:20px">
    <li><b>Prices:</b> Yahoo Finance daily closes. Bad prints on 19–20 Dec 2019 (NIFTYBEES, GOLDBEES, PSUBNKBEES at a tenth or hundredth of the price) are dropped.</li>
    <li><b>Honest start dates:</b> each ETF enters the ranking only after it had traded for about a year, so the list grows over time as it did for a real investor. Early years had only a handful of ETFs.</li>
    <li><b>Hindsight in the list:</b> the ETFs were chosen today. An ETF that closed down in the past can't be in the list.</li>
    <li><b>Not included:</b> tax, and the small tracking error and expense ratio are already inside ETF prices.</li></ul></div>`);
  $("#app").innerHTML = h.join("");
  sortableTable("#tradeTbl", D.trades.list.map(t => ({ ...t, out: t.out || "9999" })), "in", 1, t => `<tr><td><b>${esc(t.s)}</b></td><td>${fdate(t.in)}</td><td>${t.out === "9999" ? "<span class='muted'>still held</span>" : fdate(t.out)}</td><td class="n">${t.days}</td><td class="n">${spct(t.ret)}</td></tr>`);
  renderMonths();
  $("#fYear").addEventListener("change", renderMonths);
  $("#fEtf").addEventListener("input", renderMonths);
  drawCharts();
  $("#theme").addEventListener("click", () => {
    const dark = getComputedStyle(document.documentElement).colorScheme.includes("dark");
    document.documentElement.dataset.theme = dark ? "light" : "dark";
    drawCharts();
  });
}

function monthCard(m) {
  const tbl = (head, rows) => `<div class="tbl-wrap"><table><thead><tr>${head.map((x, i) => `<th class="${i ? "n" : ""}">${x}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
  const sold = m.sold.length ? `<h3>Sold (${m.sold.length})</h3>` + tbl(["ETF", "Bought", "Days", "Trade return", "Why sold"], m.sold.map(x => `<tr><td><b>${esc(x.s)}</b></td><td class="n">${fdate(x.in)}</td><td class="n">${x.days}</td><td class="n">${spct(x.ret)}</td><td class="n why">${esc(x.why)}</td></tr>`)) : "";
  const bought = m.bought.length ? `<h3>Bought (${m.bought.length})</h3>` + tbl(["ETF", "Rank", "Score", "Price"], m.bought.map(x => `<tr><td><b>${esc(x.s)}</b></td><td class="n">${x.rank}</td><td class="n">${x.score.toFixed(2)}</td><td class="n">${x.px.toFixed(2)}</td></tr>`)) : "";
  const held = `<h3>Portfolio until ${fdate(m.until)}</h3>` + tbl(["Holding", "Rank now", "Weight", "Return to next month-end"],
    [...m.held.map(x => `<tr><td><b>${esc(x.s)}</b>${x.new ? '<span class="tag">NEW</span>' : ""}</td><td class="n">${x.rank ?? "–"}</td><td class="n">${pct(x.w)}</td><td class="n">${spct(x.pr)}</td></tr>`),
     m.cash > 0.001 ? `<tr><td class="muted">Cash (LIQUIDCASE)</td><td class="n">–</td><td class="n">${pct(m.cash)}</td><td class="n muted">liquid</td></tr>` : ""]);
  const ranked = m.ranked.length ? `<h3>Passed the filters (${m.ranked.length})</h3><div class="chips">${m.ranked.map((r, i) => `<span class="chip ${r.held ? "on" : ""}" title="score ${r.score.toFixed(2)}">${i + 1}. ${esc(r.s)} · ${r.score.toFixed(2)}</span>`).join("")}</div>` : "";
  const left = m.left.length ? `<p class="muted" style="font-size:12.5px;margin-top:8px">Left out: ${m.left.map(x => `<b>${esc(x.s)}</b> (${esc(x.why)})`).join(" · ")}</p>` : "";
  return `<div class="month"><div class="mhead"><h3>${fmonth(m.date)}${m.sold.length || m.bought.length ? '<span class="badge">CHANGE</span>' : '<span class="badge">HOLD</span>'}</h3>
    <div class="mret">Until next month-end: <b>${spct(m.periodRet)}</b> <span class="muted">· NIFTYBEES ${pct(m.niftyRet, 1, true)}</span></div></div>
    <div class="mmeta">${fdate(m.date)} · ${m.available} ETFs trading, ${m.eligible} passed the filters · ${pct(m.cash, 0)} in cash after trading.</div>
    ${sold}${bought}${held}${ranked}${left}</div>`;
}

function renderMonths() {
  const y = $("#fYear").value, q = $("#fEtf").value.trim().toUpperCase();
  const list = DATA.log.filter(m => (!y || m.date.startsWith(y)) && (!q || [...m.sold, ...m.bought, ...m.held].some(x => x.s.includes(q))));
  $("#monthLog").innerHTML = [...list].reverse().map(monthCard).join("") || `<p class="muted">No months match.</p>`;
  $("#fCount").textContent = `${list.length} of ${DATA.log.length} months (newest first)`;
}

function drawCharts() {
  const pts = DATA.curve;
  let ps = 0, pn = 0;
  DATA.curve = pts.map(p => { ps = Math.max(ps, p.strategy); pn = Math.max(pn, p.nifty); return { ...p, d: p.date, s: p.strategy, b: p.nifty, g: p.gold, dd: p.strategy / ps - 1, bdd: p.nifty / pn - 1 }; });
  const multTicks = (lo, hi) => [0.5, 0.75, 1, 1.5, 2, 3, 4, 5, 6, 8].filter(t => t >= lo * 0.98 && t <= hi * 1.02);
  lineChart($("#eqChart"), { height: 340, log: true, ticksY: multTicks, fmtY: t => t + "×", series: [
    { k: "s", name: "ETF momentum", c: "--s1", w: 2.5, fmt: v => "₹" + v.toFixed(2) },
    { k: "b", name: "NIFTYBEES", c: "--s2", fmt: v => "₹" + v.toFixed(2) },
    { k: "g", name: "GOLDBEES", c: "--s4", fmt: v => "₹" + v.toFixed(2) }] });
  lineChart($("#ddChart"), { height: 220, log: false, area: true,
    ticksY: lo => { const o = []; for (let t = 0; t >= lo - 0.001; t -= 0.1) o.push(+t.toFixed(1)); return o; }, fmtY: t => Math.round(t * 100) + "%",
    series: [{ k: "dd", name: "ETF momentum", c: "--s1", w: 2, fill: true, fmt: v => pct(v) }, { k: "bdd", name: "NIFTYBEES", c: "--s2", fmt: v => pct(v) }] });
}

render();
let rz; addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(drawCharts, 150); });
"""

page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ETF Momentum Report</title>
<meta name="description" content="Month-by-month backtest of a momentum rotation across NSE ETFs: equity curve, drawdowns, returns, holdings log and every trade.">
{style}
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
(HERE / "etf_report.html").write_text(page, encoding="utf-8")
print("wrote study/etf_report.html", len(page) // 1024, "KB")
