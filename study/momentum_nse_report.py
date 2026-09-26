"""Report for the all-NSE momentum grid (study/momentum_nse_study.py): top 10-50 held, sold below rank 2N,
weekly vs monthly rebalancing. Comparison table, charts by N, equity curves, robustness, year by year,
trading load and the method.

Reuses the look, chart and sortable-table code of study/backtest_report_template.html and fills it
with momentum_nse_study.json (run study/momentum_nse_study.py first).
Output: study/momentum_nse_report.html (local only, not shipped in dist/)
Run: py study/momentum_nse_report.py
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
data = json.loads((ROOT / "momentum_nse_study.json").read_text(encoding="utf-8"))

# Written after reading the results; each item is HTML. Numbers in them are filled from DATA by the page.
FINDINGS = (HERE / "momentum_nse_findings.html").read_text(encoding="utf-8") if (HERE / "momentum_nse_findings.html").exists() else ""

EXTRA_CSS = """<style>
tr.best td { background: var(--surface-2); }
tr.best td:first-child { box-shadow: inset 3px 0 0 var(--s1); font-weight: 650; }
.find { margin: 0; padding-left: 20px; } .find li { margin: 6px 0; }
.seg { display: inline-flex; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; margin: 0 0 10px; flex-wrap: wrap; }
.seg button { font: inherit; font-size: 13.5px; padding: 6px 12px; border: 0; background: var(--surface); color: var(--text-2); cursor: pointer; }
.seg button + button { border-left: 1px solid var(--border); }
.seg button[aria-pressed="true"] { background: var(--s1); color: #fff; font-weight: 600; }
.rk { font-size: 11px; color: var(--muted); display: block; }
.heat td.n { min-width: 58px; }
.grid2 { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 12px; }
.grid2 > * { min-width: 0; }
@media (max-width: 760px) { .grid2 { grid-template-columns: minmax(0, 1fr); } }
.cat .lab { fill: var(--text-2); font-size: 11px; }
th.grpH { text-align: center; border-bottom: 1px solid var(--border); }
</style>"""

SCRIPT = r"""
const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pct = (v, dp = 1, sign = false) => v == null || isNaN(v) ? "–" : (sign && v > 0 ? "+" : "") + (v * 100).toFixed(dp) + "%";
const cls = v => v > 0 ? "pos" : v < 0 ? "neg" : "";
const spct = (v, dp = 1) => `<span class="${cls(v)}">${pct(v, dp, true)}</span>`;
const MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const fdate = d => d ? `${+d.slice(8, 10)} ${MON[+d.slice(5, 7) - 1]} ${d.slice(0, 4)}` : "–";
const f2 = v => v == null ? "–" : v.toFixed(2);
const R = k => DATA.rows.find(r => r.key === k);
const W = n => R("w" + n), M = n => R("m" + n);
const name = r => `${r.freqLabel}, top ${r.topN} / exit ${r.exitRank}`;
const B = DATA.bench;

function render() {
  const D = DATA, best = R(D.best);
  const byCagr = [...D.rows].sort((a, b) => b.cagr - a.cagr)[0];
  const bySharpe = [...D.rows].sort((a, b) => b.sharpe - a.sharpe)[0];
  const byDD = [...D.rows].sort((a, b) => b.maxDD - a.maxDD)[0];
  const h = [];
  h.push(`<button class="theme-btn" id="theme" type="button">Theme</button>
  <h1>Momentum on all NSE stocks: how many to hold, and how often to rebalance</h1>
  <p class="sub">The Momentum Scan rules on every NSE stock (not just the Nifty 500), ${D.stocks.toLocaleString("en-IN")} stocks in all, from ${fdate(D.from)} to ${fdate(D.asOf)}.
  Buy the top N (10 to 50), sell a holding once it drops below rank 2N, and rebalance at each week's or each month's last close: 18 combinations.</p>
  <nav class="nav"><a href="#findings">Findings</a><a href="#compare">Comparison</a><a href="#byn">By N</a><a href="#curve">Equity</a><a href="#robust">Robustness</a><a href="#years">Year by year</a><a href="#load">Trading load</a><a href="#bestd">Best in detail</a><a href="#method">Method</a></nav>

  <div class="tiles">
    <div class="tile"><div class="k">Best overall</div><div class="v">${best.freqLabel} ${best.topN}/${best.exitRank}</div><div class="c">average rank on 6 measures</div></div>
    <div class="tile"><div class="k">Its CAGR</div><div class="v">${pct(best.cagr)}</div><div class="c">Nifty 500: ${pct(B.cagr)}</div></div>
    <div class="tile"><div class="k">Its worst fall</div><div class="v">${pct(best.maxDD)}</div><div class="c">Nifty 500: ${pct(B.maxDD)}</div></div>
    <div class="tile"><div class="k">Its Sharpe</div><div class="v">${f2(best.sharpe)}</div><div class="c">Nifty 500: ${f2(B.sharpe)}</div></div>
    <div class="tile"><div class="k">After tax</div><div class="v">${pct(best.afterTax)}</div><div class="c">a year, STCG/LTCG paid each April</div></div>
  </div>

  <h2 id="findings" class="first">1. What the test says</h2>
  <div class="card"><ul class="find">
    <li><b>Highest CAGR:</b> ${name(byCagr)}, ${pct(byCagr.cagr)} a year (worst fall ${pct(byCagr.maxDD)}). <b>Best Sharpe:</b> ${name(bySharpe)}, ${f2(bySharpe.sharpe)}. <b>Smallest worst fall:</b> ${name(byDD)}, ${pct(byDD.maxDD)}.</li>
    ${FINDINGS_HTML}
  </ul></div>

  <h2 id="compare">2. All 18 combinations</h2>
  <p class="sub">Scored from ${fdate(D.from)}, the same start for weekly and monthly. Sharpe and Sortino are over the 6.5% liquid-fund rate. Calmar = CAGR / worst fall. "Overall" is the average rank on CAGR, Sharpe, Calmar, after-tax CAGR, worst 3-year CAGR and the weaker of the two halves (1 = best); the small grey figure is the rank on that column. Click a heading to sort.</p>
  <div class="seg" id="freqSeg"><button type="button" data-f="all">Both</button><button type="button" data-f="weekly">Weekly</button><button type="button" data-f="month_end">Monthly</button></div>
  <div class="card tbl-wrap"><table id="cmpTbl">
    <thead><tr><th class="sort" data-k="freqLabel">Rebalance</th><th class="sort n" data-k="topN">Top N</th><th class="sort n" data-k="exitRank">Sell below</th>
      <th class="sort n" data-k="cagr">CAGR</th><th class="sort n" data-k="maxDD">Worst fall</th><th class="sort n" data-k="vol">Volatility</th><th class="sort n" data-k="sharpe">Sharpe</th><th class="sort n" data-k="sortino">Sortino</th><th class="sort n" data-k="calmar">Calmar</th>
      <th class="sort n" data-k="afterTax">After tax</th><th class="sort n" data-k="worst3y">Worst 3 yrs</th><th class="sort n" data-k="weakHalf">Weaker half</th><th class="sort n" data-k="multiple">₹1 became</th><th class="sort n" data-k="score">Overall</th></tr></thead>
    <tbody></tbody>
    <tfoot><tr><td colspan="3">Nifty 500 index (price only)</td><td class="n">${pct(B.cagr)}</td><td class="n">${pct(B.maxDD)}</td><td class="n">${pct(B.vol)}</td><td class="n">${f2(B.sharpe)}</td><td class="n">${f2(B.sortino)}</td><td class="n">${f2(B.calmar)}</td><td class="n"></td><td class="n">${pct(B.worst3y)}</td><td class="n">${pct(Math.min(B.firstHalf, B.secondHalf))}</td><td class="n">₹${B.multiple.toFixed(2)}</td><td></td></tr></tfoot>
  </table></div>

  <h2 id="byn">3. Weekly vs monthly, by how many stocks are held</h2>
  <p class="sub">Each point is one combination: top N held, sold below rank 2N. Hover for the numbers.</p>
  <div class="legend"><span><i style="background:var(--s1);height:3px"></i>Weekly</span><span><i style="background:var(--s2);height:3px"></i>Monthly</span><span><i style="background:var(--text-2);height:1px"></i>Nifty 500</span></div>
  <div class="grid2">
    <div class="card"><h3 style="margin-top:0">CAGR</h3><div class="chart" id="cCagr"></div></div>
    <div class="card"><h3 style="margin-top:0">Worst fall</h3><div class="chart" id="cDD"></div></div>
    <div class="card"><h3 style="margin-top:0">Sharpe</h3><div class="chart" id="cSharpe"></div></div>
    <div class="card"><h3 style="margin-top:0">Turnover a year (one way)</h3><div class="chart" id="cTurn"></div></div>
  </div>

  <h2 id="curve">4. Equity</h2>
  <p class="sub">₹1 from ${fdate(D.from)}, log scale. Pick how many stocks are held.</p>
  <div class="seg" id="nSeg">${D.topNs.map(n => `<button type="button" data-n="${n}">${n}</button>`).join("")}</div>
  <div class="card"><div class="legend"><span><i style="background:var(--s1);height:3px"></i>Weekly</span><span><i style="background:var(--s2);height:3px"></i>Monthly</span><span><i style="background:var(--text-2)"></i>Nifty 500</span></div>
  <div class="chart" id="eqChart"></div></div>

  <h2 id="robust">5. Robustness</h2>
  <p class="sub">Does the result hold in both halves (before and after ${D.split.slice(0, 4)}), over every 3-year stretch, with tax, with wider trading costs, and against random picks? "Random picks": same filters, same selling rule, but the buys are drawn at random from the stocks that pass the filters, instead of the top of the ranking (median of ${D.randomSeeds} draws). The gap to it is what the ranking itself adds.</p>
  <div class="card tbl-wrap"><table id="robTbl">
    <thead><tr><th class="sort" data-k="freqLabel">Rebalance</th><th class="sort n" data-k="topN">Top N</th><th class="sort n" data-k="cagr">CAGR</th>
      <th class="sort n" data-k="firstHalf">To ${D.split.slice(0, 4) - 1}</th><th class="sort n" data-k="secondHalf">${D.split.slice(0, 4)} on</th>
      <th class="sort n" data-k="worst3y">Worst 3 yrs</th><th class="sort n" data-k="median3y">Median 3 yrs</th><th class="sort n" data-k="beat3y">3 yrs ahead of Nifty 500</th><th class="sort n" data-k="worst1y">Worst 12 months</th>
      <th class="sort n" data-k="afterTax">After tax</th><th class="sort n" data-k="cost50">At 0.5% a side</th><th class="sort n" data-k="rndMed">Random picks</th><th class="sort n" data-k="edge">Ranking adds</th></tr></thead>
    <tbody></tbody>
    <tfoot><tr><td colspan="2">Nifty 500</td><td class="n">${pct(B.cagr)}</td><td class="n">${pct(B.firstHalf)}</td><td class="n">${pct(B.secondHalf)}</td><td class="n">${pct(B.worst3y)}</td><td class="n">${pct(B.median3y)}</td><td class="n"></td><td class="n">${pct(B.worst1y)}</td><td colspan="4"></td></tr></tfoot>
  </table></div>

  <h2 id="years">6. Year by year</h2>
  <p class="sub">Calendar-year returns. ${D.from.slice(0, 4)} and ${D.asOf.slice(0, 4)} are part years.</p>
  <div class="seg" id="ySeg"><button type="button" data-f="weekly">Weekly</button><button type="button" data-f="month_end">Monthly</button></div>
  <div class="card tbl-wrap"><table class="heat" id="yTbl"></table></div>

  <h2 id="load">7. Trading load and capacity</h2>
  <p class="sub">What it takes to run each combination. Turnover is one way: 3× means the whole portfolio is replaced three times a year. Capacity: each buy's size against the stock's average daily traded value over the previous month, for a ₹10 lakh and a ₹1 crore portfolio (median buy, and the share of buys above 10% of a day's trading).</p>
  <div class="card tbl-wrap"><table id="loadTbl">
    <thead><tr><th class="sort" data-k="freqLabel">Rebalance</th><th class="sort n" data-k="topN">Top N</th><th class="sort n" data-k="trades">Trades</th><th class="sort n" data-k="tpy">Trades a year</th><th class="sort n" data-k="turnoverPerYear">Turnover</th>
      <th class="sort n" data-k="avgHoldDays">Avg days held</th><th class="sort n" data-k="winRate">Winners</th><th class="sort n" data-k="payoff">Avg win / avg loss</th><th class="sort n" data-k="top5">Top 5 trades' share of gains</th>
      <th class="sort n" data-k="invested">Time invested</th><th class="sort n" data-k="exits">Market exits</th><th class="sort n" data-k="cap10l">₹10L: median buy</th><th class="sort n" data-k="cap1c">₹1 Cr: median buy</th><th class="sort n" data-k="cap1cOver">₹1 Cr: buys over 10%</th></tr></thead>
    <tbody></tbody></table></div>

  <h2 id="bestd">8. ${esc(name(best))} in detail</h2>
  <div class="grid2">
    <div class="card tbl-wrap"><h3 style="margin-top:0">Worst falls</h3><table><thead><tr><th>Peak</th><th>Bottom</th><th>Recovered</th><th class="n">Fall</th><th class="n">Days down</th></tr></thead>
      <tbody>${best.drawdowns.map(d => `<tr><td>${fdate(d.peak)}</td><td>${fdate(d.trough)}</td><td>${d.recovered ? fdate(d.recovered) : "not yet"}</td><td class="n">${spct(d.depth)}</td><td class="n">${d.daysDown}</td></tr>`).join("")}</tbody></table>
      <h3>Nifty 500's worst falls</h3><table><thead><tr><th>Peak</th><th>Bottom</th><th>Recovered</th><th class="n">Fall</th></tr></thead>
      <tbody>${B.drawdowns.slice(0, 3).map(d => `<tr><td>${fdate(d.peak)}</td><td>${fdate(d.trough)}</td><td>${d.recovered ? fdate(d.recovered) : "not yet"}</td><td class="n">${spct(d.depth)}</td></tr>`).join("")}</tbody></table></div>
    <div class="card tbl-wrap"><h3 style="margin-top:0">Best trades</h3><table><thead><tr><th>Stock</th><th>Bought</th><th>Sold</th><th class="n">Return</th></tr></thead>
      <tbody>${best.trade.best.map(t => `<tr><td>${esc(t.symbol)}</td><td>${fdate(t.entry)}</td><td>${fdate(t.exit)}</td><td class="n">${spct(t.ret)}</td></tr>`).join("")}</tbody></table>
      <h3>Worst trades</h3><table><thead><tr><th>Stock</th><th>Bought</th><th>Sold</th><th class="n">Return</th></tr></thead>
      <tbody>${best.trade.worst.map(t => `<tr><td>${esc(t.symbol)}</td><td>${fdate(t.entry)}</td><td>${fdate(t.exit)}</td><td class="n">${spct(t.ret)}</td></tr>`).join("")}</tbody></table></div>
  </div>

  <h2 id="method">9. Method and limits</h2>
  <div class="card"><ul class="rules" style="margin:0;padding-left:20px">
    <li><b>Ranking</b> (the Momentum Scan rule): for 252, 184, 126 and 63 trading days, the plain % return divided by the annualised daily volatility; the score is the average of the four. A stock needs 90% of the days in each window.</li>
    <li><b>Filters:</b> close less than 25% below its highest price since Jan 2015, above its 233-day average, at least ₹1 crore average daily traded value over the last year, and trading in the EQ series that day (BE/BZ trade-to-trade stocks and ETFs are never bought).</li>
    <li><b>Portfolio:</b> equal amounts in the top N. At each rebalance a holding is kept while it ranks 2N or better (and still passes the filters); the rest are sold and the free money is split over the best-ranked stocks not held.</li>
    <li><b>Market switch:</b> after 3 closes in a row below the Nifty 500's 200-day average, everything is sold that day and the money waits in a liquid fund at 6.5% a year; it is bought back at the first rebalance that closes above the average. Weekly rebalancing gets back in sooner.</li>
    <li><b>Costs and tax:</b> 0.25% a side (brokerage, STT, spread). The "0.5% a side" column doubles it, closer to what small stocks cost to trade. Tax: STCG 15% / LTCG 10% until 23 Jul 2024, 20% / 12.5% after, losses set off and carried forward, paid each April; the ₹1.25 lakh LTCG exemption is ignored.</li>
    <li><b>Data:</b> NSE daily bhavcopy from Jan 2015, all series, including stocks since delisted (so no survivorship bias). ${D.events.joins} renamed symbols joined to their new names; ${D.events.adjustments} splits, bonuses and demergers adjusted (from NSE's corporate-actions list, and ${D.events.fromPrices} found from prices alone); ${D.events.etfs} ETFs removed. Stocks whose traded value never reached ₹80 lakh a day are left out; the ₹1 crore floor applies on each day.</li>
    <li><b>No dividends.</b> The NSE file has none, so returns are understated by roughly the dividend yield of what is held (about 0.5-1% a year for momentum stocks). The Nifty 500 line is the price index, also without dividends, so the comparison is fair.</li>
    <li><b>Start:</b> the first year of data is used to build the 252-day score, so trading starts in ${D.from.slice(0, 4)}. The "highest price" behind the 25% rule only goes back to Jan 2015.</li>
    <li><b>Not modelled:</b> stocks stuck at an upper or lower circuit (the backtest buys and sells at the close regardless), and the price impact of larger orders (see capacity). Both matter more for small stocks and for weekly trading. Demergers of over 60% in a day are treated as no loss (holders got the new shares); the new company's shares are not tracked.</li>
  </ul></div>`);
  $("#app").innerHTML = h.join("");

  const cmpRow = r => `<tr class="${r.key === D.best ? "best" : ""}"><td>${r.freqLabel}</td><td class="n">${r.topN}</td><td class="n">${r.exitRank}</td>
    <td class="n">${pct(r.cagr)}<span class="rk">#${r.ranks.cagr}</span></td><td class="n">${pct(r.maxDD)}</td><td class="n">${pct(r.vol)}</td>
    <td class="n">${f2(r.sharpe)}<span class="rk">#${r.ranks.sharpe}</span></td><td class="n">${f2(r.sortino)}</td><td class="n">${f2(r.calmar)}<span class="rk">#${r.ranks.calmar}</span></td>
    <td class="n">${pct(r.afterTax)}<span class="rk">#${r.ranks.afterTax}</span></td><td class="n">${spct(r.worst3y)}<span class="rk">#${r.ranks.worst3y}</span></td>
    <td class="n">${pct(r.weakHalf)}<span class="rk">#${r.ranks.weakHalf}</span></td><td class="n">₹${r.multiple.toFixed(2)}</td><td class="n"><b>${r.score.toFixed(1)}</b></td></tr>`;
  const robRow = r => `<tr class="${r.key === D.best ? "best" : ""}"><td>${r.freqLabel}</td><td class="n">${r.topN}</td><td class="n">${pct(r.cagr)}</td>
    <td class="n">${pct(r.firstHalf)}</td><td class="n">${pct(r.secondHalf)}</td><td class="n">${spct(r.worst3y)}</td><td class="n">${pct(r.median3y)}</td><td class="n">${pct(r.beat3y, 0)}</td><td class="n">${spct(r.worst1y)}</td>
    <td class="n">${pct(r.afterTax)}</td><td class="n">${pct(r.cost50)}</td><td class="n">${pct(r.rndMed)}<span class="rk">${pct(r.random.worst, 0)} to ${pct(r.random.best, 0)}</span></td><td class="n">${spct(r.edge)}</td></tr>`;
  const loadRow = r => `<tr class="${r.key === D.best ? "best" : ""}"><td>${r.freqLabel}</td><td class="n">${r.topN}</td><td class="n">${r.trades.toLocaleString("en-IN")}</td><td class="n">${r.tpy.toFixed(0)}</td><td class="n">${r.turnoverPerYear.toFixed(1)}×</td>
    <td class="n">${Math.round(r.avgHoldDays)}</td><td class="n">${pct(r.winRate, 0)}</td><td class="n">${f2(r.payoff)}</td><td class="n">${pct(r.top5, 0)}</td>
    <td class="n">${pct(r.invested, 0)}</td><td class="n">${r.exits}</td><td class="n">${pct(r.cap10l, 2)}</td><td class="n">${pct(r.cap1c, 1)}</td><td class="n">${pct(r.cap1cOver, 0)}</td></tr>`;
  const years = (D.asOf.slice(0, 4) - D.from.slice(0, 4)) + (D.asOf.slice(5) > D.from.slice(5) ? 1 : 0);
  D.rows.forEach(r => {
    r.rndMed = r.random.median; r.edge = r.cagr - r.random.median;
    r.tpy = r.trades / ((new Date(D.asOf) - new Date(D.from)) / 3.156e10);
    r.payoff = r.trade ? r.trade.payoff : null; r.top5 = r.trade ? r.trade.top5ShareOfGains : null;
    const cap = c => r.capacity.find(x => x.capital === c);
    r.cap10l = cap(1e6).medianShareOfAdv; r.cap1c = cap(1e7).medianShareOfAdv; r.cap1cOver = cap(1e7).over10pct;
  });
  let freq = "all";
  const tables = () => {
    const rows = D.rows.filter(r => freq === "all" || r.freq === freq);
    ["#cmpTbl", "#robTbl", "#loadTbl"].forEach(s => { const t = $(s), f = t.cloneNode(true); t.replaceWith(f); });
    sortableTable("#cmpTbl", rows, "score", 1, cmpRow);
    sortableTable("#robTbl", D.rows, "cagr", -1, robRow);
    sortableTable("#loadTbl", D.rows, "topN", 1, loadRow);
    document.querySelectorAll("#freqSeg button").forEach(b => b.setAttribute("aria-pressed", b.dataset.f === freq));
  };
  document.querySelectorAll("#freqSeg button").forEach(b => b.addEventListener("click", () => { freq = b.dataset.f; tables(); }));
  tables();

  const yearTable = f => {
    const rows = D.rows.filter(r => r.freq === f);
    const ys = Object.keys(B.yearly);
    const all = rows.flatMap(r => ys.map(y => r.yearly[y])).filter(v => v != null);
    const mx = Math.max(...all.map(Math.abs));
    const bg = v => v == null ? "" : `background: color-mix(in srgb, var(${v >= 0 ? "--s1" : "--neg"}) ${Math.round(Math.abs(v) / mx * 45)}%, transparent)`;
    $("#yTbl").innerHTML = `<thead><tr><th>Top N</th>${ys.map(y => `<th class="n">${y}</th>`).join("")}</tr></thead><tbody>` +
      rows.map(r => `<tr class="${r.key === D.best ? "best" : ""}"><td>${r.topN} / ${r.exitRank}</td>${ys.map(y => `<td class="n" style="${bg(r.yearly[y])}">${pct(r.yearly[y], 0)}</td>`).join("")}</tr>`).join("") +
      `<tr><td>Nifty 500</td>${ys.map(y => `<td class="n" style="${bg(B.yearly[y])}">${pct(B.yearly[y], 0)}</td>`).join("")}</tr></tbody>`;
    document.querySelectorAll("#ySeg button").forEach(b => b.setAttribute("aria-pressed", b.dataset.f === f));
  };
  document.querySelectorAll("#ySeg button").forEach(b => b.addEventListener("click", () => yearTable(b.dataset.f)));
  yearTable("weekly");

  document.querySelectorAll("#nSeg button").forEach(b => b.addEventListener("click", () => { curN = +b.dataset.n; drawCharts(); }));
  $("#theme").addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("bt-theme", document.documentElement.dataset.theme); } catch (e) {}
    drawCharts();
  });
  drawCharts();
}

let curN = R(DATA.best).topN;

// One measure by N: weekly and monthly as two lines over the same categories, with a hover readout.
function catChart(el, { get, fmt, bench, zero }) {
  const ns = DATA.topNs, w = ns.map(n => get(W(n))), m = ns.map(n => get(M(n)));
  const Wd = Math.max(300, el.clientWidth), H = 220, pad = { l: 46, r: 12, t: 12, b: 28 };
  let vals = [...w, ...m, ...(bench != null ? [bench] : [])];
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (zero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
  const span = hi - lo || 1; lo -= span * 0.08; hi += span * 0.08;
  const x = i => pad.l + (i + 0.5) / ns.length * (Wd - pad.l - pad.r);
  const y = v => pad.t + (1 - (v - lo) / (hi - lo)) * (H - pad.t - pad.b);
  const step = (() => { const raw = (hi - lo) / 4, p = Math.pow(10, Math.floor(Math.log10(raw))); return [1, 2, 2.5, 5, 10].map(k => k * p).find(s => s >= raw); })();
  let svg = `<svg class="cat" viewBox="0 0 ${Wd} ${H}" role="img">`;
  for (let t = Math.ceil(lo / step) * step; t <= hi; t += step)
    svg += `<line x1="${pad.l}" x2="${Wd - pad.r}" y1="${y(t)}" y2="${y(t)}" stroke="${css("--grid")}"/><text x="${pad.l - 6}" y="${y(t) + 4}" text-anchor="end">${fmt(t, true)}</text>`;
  ns.forEach((n, i) => svg += `<text x="${x(i)}" y="${H - 8}" text-anchor="middle">${n}</text>`);
  if (bench != null) svg += `<line x1="${pad.l}" x2="${Wd - pad.r}" y1="${y(bench)}" y2="${y(bench)}" stroke="${css("--text-2")}" stroke-dasharray="4 3"/>`;
  [[m, "--s2"], [w, "--s1"]].forEach(([arr, c]) => {
    svg += `<path d="${arr.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("")}" fill="none" stroke="${css(c)}" stroke-width="2" stroke-linejoin="round"/>`;
    arr.forEach((v, i) => svg += `<circle cx="${x(i)}" cy="${y(v)}" r="4" fill="${css(c)}" stroke="${css("--surface")}" stroke-width="2"/>`);
  });
  svg += `<line class="xh" x1="0" x2="0" y1="${pad.t}" y2="${H - pad.b}" stroke="${css("--muted")}" stroke-dasharray="3 3" visibility="hidden"/>`;
  svg += `<rect x="${pad.l}" y="0" width="${Wd - pad.l - pad.r}" height="${H}" fill="transparent"/></svg><div class="tip"></div>`;
  el.innerHTML = svg;
  const sv = el.querySelector("svg"), tip = el.querySelector(".tip"), xh = sv.querySelector(".xh");
  sv.addEventListener("pointermove", ev => {
    const r = sv.getBoundingClientRect(), px = (ev.clientX - r.left) * (Wd / r.width);
    const i = Math.max(0, Math.min(ns.length - 1, Math.floor((px - pad.l) / (Wd - pad.l - pad.r) * ns.length)));
    xh.setAttribute("x1", x(i)); xh.setAttribute("x2", x(i)); xh.setAttribute("visibility", "visible");
    tip.innerHTML = `<b>Top ${ns[i]}, sell below ${2 * ns[i]}</b><div class="row"><span><span class="sw" style="background:${css("--s1")}"></span>Weekly</span><b>${fmt(w[i])}</b></div><div class="row"><span><span class="sw" style="background:${css("--s2")}"></span>Monthly</span><b>${fmt(m[i])}</b></div>` +
      (bench != null ? `<div class="row"><span>Nifty 500</span><b>${fmt(bench)}</b></div>` : "");
    tip.style.display = "block";
    const left = x(i) / Wd * r.width;
    tip.style.left = (left > r.width / 2 ? left - tip.offsetWidth - 12 : left + 12) + "px"; tip.style.top = "8px";
  });
  sv.addEventListener("pointerleave", () => { tip.style.display = "none"; xh.setAttribute("visibility", "hidden"); });
}

function drawCharts() {
  const p0 = (v, axis) => (v * 100).toFixed(axis ? 0 : 1) + "%";
  catChart($("#cCagr"), { get: r => r.cagr, fmt: p0, bench: B.cagr, zero: true });
  catChart($("#cDD"), { get: r => r.maxDD, fmt: p0, bench: B.maxDD, zero: true });
  catChart($("#cSharpe"), { get: r => r.sharpe, fmt: v => v.toFixed(2), bench: B.sharpe, zero: true });
  catChart($("#cTurn"), { get: r => r.turnoverPerYear, fmt: (v, a) => v.toFixed(a ? 0 : 1) + "×", zero: true });
  document.querySelectorAll("#nSeg button").forEach(b => b.setAttribute("aria-pressed", +b.dataset.n === curN));
  const ticks = (lo, hi) => [0.5, 0.75, 1, 1.5, 2, 3, 4, 5, 6, 8, 10, 15, 20, 30, 40, 50].filter(t => t >= lo * 0.98 && t <= hi * 1.02);
  const rs = v => "₹" + v.toFixed(2);
  lineChart($("#eqChart"), { height: 340, log: true, ticksY: ticks, fmtY: t => t + "×", series: [
    { k: "nifty500", name: "Nifty 500", c: "--text-2", w: 1.2, fmt: rs },
    { k: "m" + curN, name: `Monthly, top ${curN}`, c: "--s2", w: 2, fmt: rs },
    { k: "w" + curN, name: `Weekly, top ${curN}`, c: "--s1", w: 2.2, fmt: rs }] });
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
<title>All-NSE Momentum Grid</title>
{style}
{EXTRA_CSS}
</head>
<body>
<div class="wrap" id="app"></div>
<script>
const DATA = {json.dumps(data, separators=(",", ":")).replace("</", "<\\/")};
{helpers}
{charts}
{SCRIPT.replace("${FINDINGS_HTML}", FINDINGS.replace("`", "\\`"))}
</script>
</body>
</html>
"""
(HERE / "momentum_nse_report.html").write_text(page, encoding="utf-8")
print("wrote", HERE / "momentum_nse_report.html")
