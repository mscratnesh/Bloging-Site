"""Report for the multi-year breakout study: 2, 3 and 4-year breakouts as separate backtests, each with
the previous-week-low stop and the 2-week-low stop. Rules, comparison, charts, every trade, weekly log.

Reuses the look, chart and sortable-table code of study/backtest_report_template.html and fills it
with breakout_study.json (run study/breakout_study.py first).
Output: study/breakout_report.html, and breakout-study.html at the site root (the public copy,
        shipped in dist/). Also fills the backtest section of breakout-desk.html (between the
        breakout-study:start/end markers), which links to it.
Run: py study/breakout_report.py
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
data = json.loads((ROOT / "breakout_study.json").read_text(encoding="utf-8"))

EXTRA_CSS = """<style>
.wrap.site-top { padding-bottom: 0; } .wrap.site-top + .wrap { padding-top: 4px; padding-bottom: 0; } .wrap.site-bottom { padding-top: 0; }
.site-back { display: inline-block; margin: 0; font-size: 13px; color: var(--text-2); text-decoration: none; }
.site-back:hover { color: var(--s1); }
.site-disclaimer { font-size: 12px; color: var(--muted); border-top: 1px solid var(--border); padding: 16px 0 28px; margin-top: 30px; }
.bars text, .scatter text { fill: var(--muted); font-size: 11px; }
.why-stop { color: var(--neg); } .why-open { color: var(--s1); }
.chart-note { font-size: 12.5px; color: var(--muted); margin: 6px 0 0; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.picker { position: sticky; top: 0; z-index: 5; background: var(--bg); padding: 10px 0; border-bottom: 1px solid var(--border); margin: 26px 0 0; display: flex; flex-wrap: wrap; gap: 8px 18px; align-items: center; }
.seg { display: inline-flex; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.seg button { font: inherit; font-size: 13.5px; padding: 6px 12px; border: 0; background: var(--surface); color: var(--text-2); cursor: pointer; }
.seg button + button { border-left: 1px solid var(--border); }
.seg button[aria-pressed="true"] { background: var(--s1); color: #fff; font-weight: 600; }
.picker .lbl { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; margin-right: 6px; }
tr.grp td { background: var(--surface-2); font-weight: 650; }
td.sub { padding-left: 22px; white-space: nowrap; }
@media (max-width: 760px) { .two { grid-template-columns: 1fr; } }
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
const srs = v => `<span class="${cls(v)}">${v > 0 ? "+" : ""}${rs(v)}</span>`;
const lakh = v => "₹" + (v / 1e5).toFixed(1) + "L";
const px = v => v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const WHY = { stop: "Stop hit", "no prices": "Stopped trading", open: "Still held" };
const STOPS = Object.keys(DATA.stops), SHORT = { prev_week: "1-week low", "low_weeks:2": "2-week low", "lock:2:0.05:0.01:2": "2-week low, then +1% per 2 months" };
const SC = { prev_week: "--s1", "low_weeks:2": "--s3", "lock:2:0.05:0.01:2": "--s2" };
const NC = "--text-2";  // Nifty 500
const stopLegend = (bold) => STOPS.map(s => `<span><i style="background:var(${SC[s]})${bold && s === state.stop ? ";height:3px" : ""}"></i>${SHORT[s]}</span>`).join("");
const isLock = s => s.startsWith("lock:");
let state = { y: 3, stop: "prev_week" };
try { const s = JSON.parse(localStorage.getItem("bo-state")); if (s && DATA.studies.some(x => x.years === s.y) && STOPS.includes(s.stop)) state = s; } catch (e) {}
const study = () => DATA.studies.find(s => s.years === state.y);
const run = () => study().runs.find(r => r.stop === state.stop);

function render() {
  const D = DATA, P = D.base, S = D.studies;
  const h = [];
  h.push(`<button class="theme-btn" id="theme" type="button">Theme</button>
  <h1>Multi-year breakout: backtest report</h1>
  <p class="sub">Nifty 500 stocks breaking above a 2, 3 or 4-year high, each tested separately, with three stop-losses: the previous week's low, the lowest close of the last 2 weeks, and the 2-week low that stops trailing once it is 5% above the buy price and then rises 1% every 2 months. ${rs(D.capital)} to start. Data to ${fdate(D.asOf)}.</p>
  <nav class="nav"><a href="#overview">Comparison</a><a href="#rules">Rules</a><a href="#detail">Backtest</a><a href="#years">Yearly</a><a href="#trades">Trades</a><a href="#after">After a breakout</a><a href="#weeks">Weekly log</a><a href="#method">Method</a></nav>

  <h2 id="overview" class="first">1. All nine backtests side by side</h2>
  <p class="sub">Each lookback is its own backtest from the first day its breakouts can be measured, so the periods differ. Compare each one with the benchmarks in its own block.</p>
  <div class="card tbl-wrap"><table><thead><tr><th></th><th class="n">CAGR</th><th class="n">Worst fall</th><th class="n">Sharpe</th><th class="n">₹10L became</th><th class="n">Profit on stocks</th><th class="n">of which dividends</th><th class="n">Trades</th><th class="n">Winners</th><th class="n">Median hold</th><th class="n">Time in gold</th><th class="n">CAGR with liquid fund</th></tr></thead><tbody>
  ${S.map(st => `<tr class="grp"><td colspan="12">${st.years}-year high · ${fdate(st.from)} to ${fdate(st.to)} · ${st.events.events} breakouts</td></tr>`
    + st.runs.map(r => `<tr><td class="sub" title="${esc(r.label)}">${esc(SHORT[r.stop])}</td><td class="n"><b>${pct(r.cagr)}</b></td><td class="n">${pct(r.maxDD)}</td><td class="n">${r.sharpe.toFixed(2)}</td><td class="n">${lakh(r.endValue)}</td><td class="n">${srs(r.trades.pnl)}</td><td class="n">${srs(r.trades.dividends)}</td><td class="n">${r.trades.count}</td><td class="n">${pct(r.trades.winRate, 0)}</td><td class="n">${Math.round(r.trades.medianDays)}d</td><td class="n">${pct(r.avgCash, 0)}</td><td class="n">${pct(r.liquid.cagr)}</td></tr>`).join("")
    + st.bench.map(b => `<tr class="muted"><td class="sub">${esc(b.label)}</td><td class="n">${pct(b.cagr)}</td><td class="n">${pct(b.maxDD)}</td><td class="n">${b.sharpe.toFixed(2)}</td><td class="n">${lakh(b.endValue)}</td><td class="n" colspan="7"></td></tr>`).join("")).join("")}
  </tbody></table></div>
  <div class="two">
    <div class="card"><h3 style="margin-top:0">CAGR</h3><div class="legend">${stopLegend()}<span><i style="background:var(${NC})"></i>Nifty 500</span><span><i style="background:var(--s4)"></i>GOLDBEES</span></div><div class="chart" id="cagrChart"></div></div>
    <div class="card"><h3 style="margin-top:0">Profit on the stock trades</h3><div class="legend">${stopLegend()}</div><div class="chart" id="pnlChart"></div><p class="chart-note">Profit or loss from the trades alone (stocks still held are valued at the last close), before anything gold earned.</p></div>
  </div>
  ${findings()}

  <h2 id="rules">2. The rules tested</h2>
  <div class="card"><ul class="rules" style="margin:0;padding-left:20px">
    <li><b>Stocks:</b> the Nifty 500 list as it stood on each day (so companies later dropped or merged are included), trading at least ₹${P.min_turnover / 1e7} crore a day on average over the last year.</li>
    <li><b>Breakout:</b> the stock closes above its highest price of the last 2, 3 or 4 years (three separate backtests), and that high was set at least ${Math.round(P.base_days / 21)} months earlier, so the stock had been going sideways or down for a long time first. It needs that many years of prices.</li>
    <li><b>Watchlist:</b> every Friday (the last trading day of the week), the stocks that broke out in the last ${P.fresh_weeks} weeks and still close above their breakout level. Best momentum score first, at most ${P.watch_n} stocks.</li>
    <li><b>Buying:</b> at most ${P.slots} stocks at a time. Empty slots are filled on Friday's close from the top of the watchlist.</li>
    <li><b>Money per stock:</b> ${rs(D.capital)} to start, ${rs(D.capital / P.slots)} per slot. Money not in stocks waits in one pool in GOLDBEES. Each buy gets the pool divided by the number of empty slots: 2 empty slots and ₹1,90,000 means ₹95,000 each. So profits and losses carry into the next buy.</li>
    <li><b>Stop-loss, three versions:</b> (a) <b>1-week low</b>: the stop for the week is the previous week's lowest close. (b) <b>2-week low</b>: the lowest close of the previous 2 weeks. (c) <b>2-week low, then +1% every 2 months</b>: as (b) until that stop is at least 5% above the buy price; from then on the stop no longer follows the weekly lows, it only rises 1% every 2 months from that level (updated each Friday). On any day a stock closes below its stop, it is sold at that close and the money goes back to gold.</li>
    <li><b>Dividends:</b> a stock held into its ex-date gets the dividend, added to that holding (as if reinvested in the stock). GOLDBEES pays none.</li>
    <li><b>Costs:</b> ${pct(P.cost, 2)} on every buy and sell, of stocks and of GOLDBEES. No tax.</li>
  </ul></div>

  <div class="picker" id="detail"><span><span class="lbl">Breakout</span><span class="seg" id="pickY">${S.map(st => `<button type="button" data-y="${st.years}">${st.years}-year high</button>`).join("")}</span></span>
    <span><span class="lbl">Stop</span><span class="seg" id="pickS">${STOPS.map(s => `<button type="button" data-s="${s}">${esc(D.stops[s])}</button>`).join("")}</span></span></div>
  <div id="detailBody"></div>

  <h2 id="method">9. Data and method</h2><div class="note"><ul style="margin:0;padding-left:20px">
    <li><b>Prices:</b> daily close, high and volume from Yahoo Finance, the same data as the momentum study, from September 2019. A breakout over N years needs N years of prices first, so the 2-year test starts in ${fdate(S[0].from)}, the 3-year in ${fdate(S[1].from)} and the 4-year in ${fdate(S[2].from)}. A 5-year test would have only 2 years, too short to judge.</li>
    <li><b>Honest stock list:</b> the Nifty 500 members as they stood on each day. A few past members have no price data (mostly merged or delisted) and are left out.</li>
    <li><b>Stops at the close:</b> the price data has no daily lows, so a week's low is its lowest close and the stop sells at the close of the day it is broken. A real stop order would sell during the day, sometimes better and sometimes worse after a gap down.</li>
    <li><b>Trades at the close:</b> buys happen at Friday's close, the same day the watchlist is built. In practice you would buy on Monday.</li>
    <li><b>Dividends:</b> from Yahoo Finance, each stored as a yield (the dividend ÷ the previous close) so share splits don't distort it. The Nifty 500 benchmark is the price index, so it leaves out dividends (roughly 1–1.5% a year). The "after a breakout" returns are price only.</li>
    <li><b>Not included:</b> tax (on gains and on dividends), and slippage beyond the ${pct(P.cost, 2)} cost.</li>
    <li><b>Short tests:</b> 3 to 5 years each, with one big gold rally in 2025. Treat differences of a few points of CAGR as noise.</li></ul></div>`);
  $("#app").innerHTML = h.join("");
  $("#pickY").addEventListener("click", e => { const b = e.target.closest("button"); if (b) { state.y = +b.dataset.y; renderDetail(); } });
  $("#pickS").addEventListener("click", e => { const b = e.target.closest("button"); if (b) { state.stop = b.dataset.s; renderDetail(); } });
  renderDetail();
  $("#theme").addEventListener("click", () => {
    const dark = getComputedStyle(document.documentElement).colorScheme.includes("dark");
    document.documentElement.dataset.theme = dark ? "light" : "dark";
    drawCharts();
  });
}

function findings() {
  const S = DATA.studies, all = S.flatMap(st => st.runs.map(r => ({ ...r, y: st.years })));
  const best = all.reduce((a, b) => b.cagr > a.cagr ? b : a);
  const by = k => S.map(st => st.runs.find(r => r.stop === k));
  const [w1, w2, lk] = STOPS.map(by);
  const plain = all.filter(r => !isLock(r.stop)), losers = plain.filter(r => r.trades.pnl < 0).length;
  const range = (xs, f) => `${f(Math.min(...xs))}–${f(Math.max(...xs))}`;
  return `<div class="note"><b>What the backtests say:</b><ul style="margin:6px 0 0;padding-left:20px">
    <li><b>Plain 1-week and 2-week lows:</b> the stock trades lost money in ${losers} of ${plain.length} backtests. They sell most trades within 2–4 weeks, so the money sits in gold ${range(plain.map(r => r.avgCash), v => pct(v, 0))} of the time and the CAGR mostly comes from gold. With a liquid fund instead, CAGR is only ${range(plain.map(r => r.liquid.cagr), pct)}.</li>
    <li><b>2-week low, then +1% every 2 months:</b> once a trade is 5% up, the stop stops following the weekly lows, so the winners stay in. Profit on stocks: ${S.map((st, i) => `${st.years}-year ${srs(lk[i].trades.pnl)}`).join(", ")}, against ${S.map(st => srs(st.runs.find(r => r.stop === STOPS[1]).trades.pnl)).join(", ")} with the plain 2-week low. Time in gold falls to ${range(lk.map(r => r.avgCash), v => pct(v, 0))}, and even with a liquid fund instead of gold the CAGR is ${range(lk.map(r => r.liquid.cagr), pct)}.</li>
    <li>Much of that profit is in a few big winners still held, such as BSE and RVNL bought in 2022–23. A stop that rises only 1% every 2 months rarely sells a winner, so the result depends on catching a few of them.</li>
    <li>Highest CAGR: ${best.y}-year high with the ${SHORT[best.stop]} stop, ${pct(best.cagr)}. The 4-year test covers only 3 years.</li></ul></div>`;
}

function renderDetail() {
  try { localStorage.setItem("bo-state", JSON.stringify(state)); } catch (e) {}
  document.querySelectorAll("#pickY button").forEach(b => b.setAttribute("aria-pressed", +b.dataset.y === state.y));
  document.querySelectorAll("#pickS button").forEach(b => b.setAttribute("aria-pressed", b.dataset.s === state.stop));
  const st = study(), r = run(), T = r.trades, others = st.runs.filter(x => x.stop !== state.stop), nifty = st.bench.find(b => b.key === "nifty500"), gold = st.bench.find(b => b.key === "gold");
  const why = {};
  T.list.forEach(t => why[t.why] = (why[t.why] || 0) + 1);
  const hz = ["1m", "3m", "6m", "12m"], hzName = { "1m": "1 month", "3m": "3 months", "6m": "6 months", "12m": "12 months" }, ev = st.events;
  const ys = Object.keys(r.yearly), yrs = [...new Set(r.weeks.map(w => w.date.slice(0, 4)))];
  const statRow = (label, x, hl, pnl) => `<tr class="${hl ? "hl" : ""}"><td>${esc(label)}</td><td class="n">${pct(x.cagr)}</td><td class="n">${pct(x.maxDD)}</td><td class="n">${pct(x.vol)}</td><td class="n">${x.sharpe.toFixed(2)}</td><td class="n">${lakh(x.multiple * DATA.capital)}</td><td class="n">${pnl == null ? "" : srs(pnl)}</td></tr>`;
  $("#detailBody").innerHTML = `
  <h2 class="first" style="margin-top:18px">3. Backtest: ${st.years}-year high, ${esc(DATA.stops[state.stop].toLowerCase())}</h2>
  <p class="sub">${fdate(st.from)} to ${fdate(st.to)}.</p>
  <div class="tiles">
    <div class="tile"><div class="k">CAGR</div><div class="v">${pct(r.cagr)}</div><div class="c">${others.map(o => `${SHORT[o.stop]} ${pct(o.cagr)}`).join(" · ")} · Nifty 500 ${pct(nifty.cagr)}</div></div>
    <div class="tile"><div class="k">Worst fall</div><div class="v">${pct(r.maxDD)}</div><div class="c">Nifty 500 ${pct(nifty.maxDD)}</div></div>
    <div class="tile"><div class="k">${rs(DATA.capital)} became</div><div class="v">${lakh(r.endValue)}</div><div class="c">Nifty 500 ${lakh(nifty.endValue)} · Gold ${lakh(gold.endValue)}</div></div>
    <div class="tile"><div class="k">Profit on stocks</div><div class="v ${cls(T.pnl)}">${rs(T.pnl)}</div><div class="c">incl. ${rs(T.dividends)} dividends · ${others.map(o => `${SHORT[o.stop]} ${rs(o.trades.pnl)}`).join(" · ")}</div></div>
    <div class="tile"><div class="k">Time in gold</div><div class="v">${pct(r.avgCash, 0)}</div><div class="c">with a liquid fund instead: ${pct(r.liquid.cagr)} CAGR</div></div>
  </div>
  <div class="card tbl-wrap"><table><thead><tr><th></th><th class="n">CAGR</th><th class="n">Worst fall</th><th class="n">Volatility</th><th class="n">Sharpe</th><th class="n">₹10L became</th><th class="n">Profit on stocks</th></tr></thead><tbody>
    ${st.runs.map(x => statRow(`Breakout, ${x.label.toLowerCase()}`, x, x.stop === state.stop, x.trades.pnl)).join("")}
    ${st.runs.map(x => statRow(`Breakout, ${x.label.toLowerCase()}, liquid fund instead of gold`, x.liquid, false, x.liquid.pnl)).join("")}
    ${statRow(`Breakout, ${r.label.toLowerCase()}, without dividends`, r.noDiv, false, r.noDiv.pnl)}
    ${st.bench.map(b => statRow(b.label + (b.key === "nifty500" ? " (price, no dividends)" : ""), b, false, null)).join("")}</tbody></table></div>
  <h3>Equity curve</h3>
  <div class="card"><div class="legend">${stopLegend(true)}<span><i style="background:var(${NC})"></i>Nifty 500</span><span><i style="background:var(--s4)"></i>GOLDBEES</span></div><div class="chart" id="eqChart"></div></div>
  <h3>Drawdown</h3><div class="card"><div class="legend">${stopLegend(true)}<span><i style="background:var(${NC})"></i>Nifty 500</span></div><div class="chart" id="ddChart"></div><p class="chart-note">The charts use Friday closes. The worst falls in the table use daily closes, so they can be deeper. The early-2026 fall came mostly from gold: GOLDBEES fell 24% from 29 Jan to 23 Mar 2026 while most of the money sat in it.</p></div>
  <div class="card tbl-wrap"><table><thead><tr><th>Biggest falls (${SHORT[state.stop]} stop): from high on</th><th>Lowest on</th><th class="n">Fall</th><th>Back to high</th></tr></thead>
    <tbody>${r.drawdowns.map(x => `<tr><td>${fdate(x.peak)}</td><td>${fdate(x.trough)}</td><td class="n">${spct(x.depth)}</td><td>${x.recovered ? fdate(x.recovered) : "<span class='muted'>not yet</span>"}</td></tr>`).join("")}</tbody></table></div>

  <h2 id="years">4. Year by year</h2><p class="sub">${ys[0]} and ${ys[ys.length - 1]} are part years.</p>
  <div class="card tbl-wrap"><table><thead><tr><th>Year</th>${st.runs.map(x => `<th class="n">${SHORT[x.stop]}</th>`).join("")}<th class="n">Nifty 500</th><th class="n">GOLDBEES</th></tr></thead>
    <tbody>${ys.map(y => `<tr><td>${y}</td>${st.runs.map(x => `<td class="n">${spct(x.yearly[y])}</td>`).join("")}<td class="n">${spct(nifty.yearly[y])}</td><td class="n">${spct(gold.yearly[y])}</td></tr>`).join("")}</tbody></table></div>

  <h2 id="trades">5. Trades (${SHORT[state.stop]} stop)</h2>
  <div class="tiles">
    <div class="tile"><div class="k">Trades</div><div class="v">${T.count}</div><div class="c">closed; ${T.open} still held (${T.openPnl >= 0 ? "+" : ""}${rs(T.openPnl)} not yet booked)</div></div>
    <div class="tile"><div class="k">Winners</div><div class="v">${pct(T.winRate, 0)}</div><div class="c">average win ${pct(T.avgWin, 1, true)}</div></div>
    <div class="tile"><div class="k">Average trade</div><div class="v ${cls(T.avgRet)}">${pct(T.avgRet, 1, true)}</div><div class="c">average loss ${pct(T.avgLoss)}; win/loss size ${T.payoff.toFixed(1)}×</div></div>
    <div class="tile"><div class="k">Best / worst</div><div class="v">${pct(T.best, 0, true)}</div><div class="c">worst ${pct(T.worst)}</div></div>
    <div class="tile"><div class="k">Median hold</div><div class="v">${Math.round(T.medianDays)} days</div><div class="c">${Object.entries(why).map(([k, v]) => `${v} ${WHY[k].toLowerCase()}`).join(" · ")}</div></div>
  </div>
  <div class="two">
    <div class="card"><h3 style="margin-top:0">Trade returns</h3><div class="chart" id="histChart"></div><p class="chart-note">Number of trades in each 5% return band.</p></div>
    <div class="card"><h3 style="margin-top:0">Return vs days held</h3><div class="chart" id="scatChart"></div><p class="chart-note">Each dot is a trade. Hover for the stock and dates.</p></div>
  </div>
  <h3>Every trade</h3>
  <div class="filters"><label>Stock <input id="fTrade" placeholder="e.g. BSE" size="12"></label><span class="muted" id="fTradeCount"></span></div>
  <div class="card tbl-wrap"><table id="tradeTbl"><thead><tr><th class="sort" data-k="s">Stock</th><th class="sort" data-k="brk">Broke out</th><th class="sort" data-k="in">Bought</th><th class="sort n" data-k="inPx">Buy price</th><th class="sort" data-k="out">Sold</th><th class="sort n" data-k="outPx">Sell price</th><th class="sort n" data-k="days">Days</th><th class="sort n" data-k="basis">Invested</th><th class="sort n" data-k="pnl">Profit</th><th class="sort n" data-k="div">Dividends</th><th class="sort n" data-k="ret">Return</th><th class="sort" data-k="why">Why sold</th>${isLock(state.stop) ? '<th class="sort" data-k="locked">Stop locked on</th>' : ""}</tr></thead><tbody></tbody></table></div>

  <h2 id="after">6. What happens after a ${st.years}-year breakout</h2>
  <p class="sub">Every ${st.years}-year breakout in the Nifty 500 list of the day (${ev.events}), held for a fixed time with no stop. The first breakout per stock in any 3 months counts. Later breakouts have no 12-month result yet.</p>
  <div class="two">
    <div class="card"><div class="legend"><span><i style="background:var(--s1)"></i>Average</span><span><i style="background:var(--s3)"></i>Median</span></div><div class="chart" id="evChart"></div></div>
    <div class="card tbl-wrap"><table><thead><tr><th>Held for</th><th class="n">Breakouts</th><th class="n">Average</th><th class="n">Median</th><th class="n">Up</th><th class="n">Beat Nifty 500</th></tr></thead>
      <tbody>${hz.filter(k => ev[k]).map(k => { const e = ev[k]; return `<tr><td>${hzName[k]}</td><td class="n">${e.n}</td><td class="n">${spct(e.mean)}</td><td class="n">${spct(e.median)}</td><td class="n">${pct(e.hit, 0)}</td><td class="n">${pct(e.beatIndex, 0)}</td></tr>`; }).join("")}</tbody></table></div>
  </div>

  <h2 id="weeks">7. Weekly log (${SHORT[state.stop]} stop)</h2><p class="sub">Each Friday: the watchlist (breakouts of the last ${DATA.base.fresh_weeks} weeks still above their breakout level), what was bought, and what the stop sold during the week.</p>
  <div class="filters"><label>Year <select id="fYear"><option value="">All</option>${yrs.map(y => `<option>${y}</option>`).join("")}</select></label><label>Stock <input id="fStock" placeholder="e.g. RVNL" size="12"></label><label><input type="checkbox" id="fActive" checked> Only weeks with trades</label><span class="muted" id="fCount"></span></div><div id="weekLog"></div>`;

  const rows = T.list.map(t => ({ ...t, out: t.out || "9999", locked: t.locked || "", div: t.div || 0 }));
  const rowFn = t => `<tr><td><b>${esc(t.s)}</b></td><td>${fdate(t.brk)}</td><td>${fdate(t.in)}</td><td class="n">${px(t.inPx)}</td><td>${t.out === "9999" ? "<span class='muted'>still held</span>" : fdate(t.out)}</td><td class="n">${px(t.outPx)}</td><td class="n">${t.days}</td><td class="n">${rs(t.basis)}</td><td class="n">${srs(t.pnl)}</td><td class="n">${t.div ? rs(t.div) : "<span class='muted'>–</span>"}</td><td class="n">${spct(t.ret)}</td><td class="why-${t.why === "stop" ? "stop" : "open"}">${WHY[t.why]}</td>${isLock(state.stop) ? `<td>${t.locked ? fdate(t.locked) : "<span class='muted'>–</span>"}</td>` : ""}</tr>`;
  const paintTrades = () => {
    const q = $("#fTrade").value.trim().toUpperCase();
    const sub = rows.filter(t => !q || t.s.includes(q));
    const fresh = $("#tradeTbl").cloneNode(true);
    fresh.tBodies[0].innerHTML = "";
    $("#tradeTbl").replaceWith(fresh);
    if (sub.length) sortableTable("#tradeTbl", sub, "in", 1, rowFn);
    $("#fTradeCount").textContent = `${sub.length} of ${rows.length} trades`;
  };
  paintTrades();
  $("#fTrade").addEventListener("input", paintTrades);
  renderWeeks();
  ["#fYear", "#fStock", "#fActive"].forEach(k => $(k).addEventListener(k === "#fStock" ? "input" : "change", renderWeeks));
  drawCharts();
}

function weekCard(w, prev) {
  const list = run().trades.list;
  const sold = list.filter(t => t.out && t.out > prev && t.out <= w.date);
  const bought = list.filter(t => t.in === w.date);
  const tbl = (head, rows) => `<div class="tbl-wrap"><table><thead><tr>${head.map((x, i) => `<th class="${i ? "n" : ""}">${x}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
  const s = sold.length ? `<h3>Sold this week (${sold.length})</h3>` + tbl(["Stock", "Sold on", "Bought", "Days", "Profit", "Return"], sold.map(x => `<tr><td><b>${esc(x.s)}</b></td><td class="n">${fdate(x.out)}</td><td class="n">${fdate(x.in)}</td><td class="n">${x.days}</td><td class="n">${srs(x.pnl)}</td><td class="n">${spct(x.ret)}</td></tr>`)) : "";
  const b = bought.length ? `<h3>Bought (${bought.length})</h3>` + tbl(["Stock", "Broke out", "Price", "Invested"], bought.map(x => `<tr><td><b>${esc(x.s)}</b></td><td class="n">${fdate(x.brk)}</td><td class="n">${px(x.inPx)}</td><td class="n">${rs(x.basis)}</td></tr>`)) : "";
  const wl = w.watch.length ? `<h3>Watchlist (${w.watch.length})</h3><div class="chips">${w.watch.map((x, i) => `<span class="chip ${w.bought.includes(x.s) ? "on" : ""}" title="broke out ${fdate(x.brk)} above ${px(x.lvl)}">${i + 1}. ${esc(x.s)} · ${px(x.px)}</span>`).join("")}</div>` : `<p class="mmeta">No stocks on the watchlist.</p>`;
  return `<div class="month"><div class="mhead"><h3>Week to ${fdate(w.date)}${sold.length || bought.length ? '<span class="badge">CHANGE</span>' : '<span class="badge">HOLD</span>'}</h3>
    <div class="mret">${w.held} of ${DATA.base.slots} slots filled · ${pct(w.cash, 0)} in gold</div></div>${s}${b}${wl}</div>`;
}

function renderWeeks() {
  const y = $("#fYear").value, q = $("#fStock").value.trim().toUpperCase(), active = $("#fActive").checked, W = run().weeks, list = run().trades.list;
  const cards = [];
  let shown = 0;
  for (let i = W.length - 1; i >= 0; i--) {
    const w = W[i], prev = i ? W[i - 1].date : "0000";
    if (y && !w.date.startsWith(y)) continue;
    const sold = list.filter(t => t.out && t.out > prev && t.out <= w.date);
    if (active && !sold.length && !w.bought.length) continue;
    if (q && ![...sold.map(t => t.s), ...w.bought, ...w.watch.map(x => x.s)].some(s => s.includes(q))) continue;
    shown++;
    if (cards.length < 150) cards.push(weekCard(w, prev));
  }
  $("#weekLog").innerHTML = cards.join("") || `<p class="muted">No weeks match.</p>`;
  $("#fCount").textContent = `${shown} of ${W.length} weeks (newest first${shown > 150 ? ", first 150 shown" : ""})`;
}

function onCurve(pts, el, opts) {
  const keep = DATA.curve;
  DATA.curve = pts;
  lineChart(el, opts);
  DATA.curve = keep;
}

function barChart(el, { cats, series, fmtY, height }) {
  const W = Math.max(300, el.clientWidth), H = height, m = { l: 52, r: 10, t: 10, b: 28 };
  const vals = series.flatMap(s => s.v);
  const hi = Math.max(0, ...vals), lo = Math.min(0, ...vals);
  const y = v => m.t + (1 - (v - lo) / (hi - lo || 1)) * (H - m.t - m.b);
  const bw = (W - m.l - m.r) / cats.length, inner = bw * 0.76 / series.length;
  const step = (hi - lo) / 4, ticks = [];
  for (let k = 0; k <= 4; k++) ticks.push(lo + step * k);
  if (lo < 0 && hi > 0) ticks.push(0);
  let svg = `<svg class="bars" viewBox="0 0 ${W} ${H}" role="img">`;
  ticks.forEach(t => svg += `<line x1="${m.l}" x2="${W - m.r}" y1="${y(t)}" y2="${y(t)}" stroke="${css(t === 0 ? "--muted" : "--grid")}"/><text x="${m.l - 6}" y="${y(t) + 4}" text-anchor="end">${fmtY(t)}</text>`);
  cats.forEach((c, i) => {
    const x0 = m.l + i * bw + bw * 0.12;
    series.forEach((s, k) => {
      const v = s.v[i], top = y(Math.max(v, 0)), hgt = Math.abs(y(v) - y(0));
      svg += `<rect x="${x0 + k * inner}" y="${top}" width="${Math.max(inner - 2, 1)}" height="${Math.max(hgt, 0.5)}" rx="2" fill="${css(s.c(v, i))}"><title>${esc(c)}${s.name ? " · " + esc(s.name) : ""}: ${s.fmt(v)}</title></rect>`;
    });
    if (cats.length <= 12 || i % 2 === 0) svg += `<text x="${m.l + i * bw + bw / 2}" y="${H - 8}" text-anchor="middle">${esc(c)}</text>`;
  });
  el.innerHTML = svg + "</svg>";
}

function scatter(el, { pts, height }) {
  const W = Math.max(300, el.clientWidth), H = height, m = { l: 44, r: 10, t: 10, b: 28 };
  if (!pts.length) { el.innerHTML = ""; return; }
  const xs = pts.map(p => p.days), ys = pts.map(p => p.ret);
  const xmax = Math.max(...xs), ylo = Math.min(-0.1, ...ys), yhi = Math.max(0.1, ...ys);
  const x = v => m.l + Math.sqrt(v / xmax) * (W - m.l - m.r);
  const y = v => m.t + (1 - (v - ylo) / (yhi - ylo)) * (H - m.t - m.b);
  let svg = `<svg class="scatter" viewBox="0 0 ${W} ${H}" role="img">`;
  for (let t = Math.ceil(ylo * 5) / 5; t <= yhi + 1e-9; t += 0.2) svg += `<line x1="${m.l}" x2="${W - m.r}" y1="${y(t)}" y2="${y(t)}" stroke="${css(Math.abs(t) < 1e-9 ? "--muted" : "--grid")}"/><text x="${m.l - 6}" y="${y(t) + 4}" text-anchor="end">${Math.round(t * 100)}%</text>`;
  [7, 30, 90, 180, 365].filter(d => d <= xmax).forEach(d => svg += `<text x="${x(d)}" y="${H - 8}" text-anchor="middle">${d}d</text>`);
  pts.forEach(p => svg += `<circle cx="${x(p.days)}" cy="${y(p.ret)}" r="3.5" fill="${css(p.ret > 0 ? "--pos" : "--neg")}" opacity="0.7"><title>${esc(p.s)} ${fdate(p.in)} to ${fdate(p.out)}: ${pct(p.ret, 1, true)} in ${p.days} days</title></circle>`);
  el.innerHTML = svg + "</svg>";
}

function drawCharts() {
  const D = DATA, S = D.studies, cats = S.map(st => st.years + "-year high");
  const bench = (st, k) => st.bench.find(b => b.key === k);
  barChart($("#cagrChart"), { height: 240, cats, fmtY: t => Math.round(t * 100) + "%", series: [
    ...STOPS.map(k => ({ name: SHORT[k], v: S.map(st => st.runs.find(r => r.stop === k).cagr), c: () => SC[k], fmt: v => pct(v) })),
    { name: "Nifty 500", v: S.map(st => bench(st, "nifty500").cagr), c: () => NC, fmt: v => pct(v) },
    { name: "GOLDBEES", v: S.map(st => bench(st, "gold").cagr), c: () => "--s4", fmt: v => pct(v) }] });
  barChart($("#pnlChart"), { height: 240, cats, fmtY: t => (t < 0 ? "−" : "") + "₹" + Math.abs(t / 1e5).toFixed(1) + "L", series: [
    ...STOPS.map(k => ({ name: SHORT[k], v: S.map(st => st.runs.find(r => r.stop === k).trades.pnl), c: () => SC[k], fmt: rs }))] });

  const st = study(), r = run();
  const peak = {}, pts = st.curve.map(p => {
    const o = { ...p, d: p.date };
    [...STOPS, "nifty500"].forEach(k => { peak[k] = Math.max(peak[k] || 0, p[k]); o["dd:" + k] = p[k] / peak[k] - 1; });
    return o; });
  const rTicks = (lo, hi) => [5e5, 7.5e5, 1e6, 1.25e6, 1.5e6, 2e6, 2.5e6, 3e6, 4e6, 5e6].filter(t => t >= lo * 0.98 && t <= hi * 1.02);
  const order = [...STOPS.filter(k => k !== state.stop), state.stop];  // selected stop drawn last, on top
  onCurve(pts, $("#eqChart"), { height: 340, log: true, ticksY: rTicks, fmtY: lakh, series: [
    ...order.map(k => ({ k, name: SHORT[k], c: SC[k], w: k === state.stop ? 2.5 : 1.3, fmt: rs })),
    { k: "nifty500", name: "Nifty 500", c: NC, fmt: rs },
    { k: "gold", name: "GOLDBEES", c: "--s4", fmt: rs }] });
  onCurve(pts, $("#ddChart"), { height: 220, log: false, area: true,
    ticksY: lo => { const o = []; for (let t = 0; t >= lo - 0.001; t -= 0.1) o.push(+t.toFixed(1)); return o; }, fmtY: t => Math.round(t * 100) + "%",
    series: [...order.map(k => ({ k: "dd:" + k, name: SHORT[k], c: SC[k], w: k === state.stop ? 2 : 1.2, fill: k === state.stop, fmt: v => pct(v) })),
             { k: "dd:nifty500", name: "Nifty 500", c: NC, fmt: v => pct(v) }] });

  const closed = r.trades.list.filter(t => t.out);
  const edges = [];
  for (let e = -0.25; e < 0.95; e += 0.05) edges.push(+e.toFixed(2));
  const counts = edges.map(() => 0);
  closed.forEach(t => { const k = Math.floor((Math.min(Math.max(t.ret, -0.25), 0.9) + 0.25) / 0.05 + 1e-9); counts[Math.min(k, edges.length - 1)]++; });
  const last = Math.max(counts.findLastIndex(c => c > 0), 6);
  barChart($("#histChart"), { height: 240, cats: edges.slice(0, last + 1).map(e => (e >= 0 ? "+" : "") + Math.round(e * 100)), fmtY: t => Math.round(t),
    series: [{ v: counts.slice(0, last + 1), c: (v, i) => edges[i] < 0 ? "--neg" : "--pos", fmt: v => v + " trades" }] });
  scatter($("#scatChart"), { pts: closed, height: 240 });

  const ev = st.events, hz = ["1m", "3m", "6m", "12m"].filter(k => ev[k]);
  barChart($("#evChart"), { height: 240, cats: hz.map(k => ({ "1m": "1 month", "3m": "3 months", "6m": "6 months", "12m": "12 months" })[k]), fmtY: t => Math.round(t * 100) + "%",
    series: [{ name: "Average", v: hz.map(k => ev[k].mean), c: () => "--s1", fmt: v => pct(v, 1, true) }, { name: "Median", v: hz.map(k => ev[k].median), c: () => "--s3", fmt: v => pct(v, 1, true) }] });
}

render();
let rz; addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(drawCharts, 150); });
if (matchMedia) matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", drawCharts);
"""

page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Multi-Year Breakout Report</title>
<meta name="description" content="Backtests of buying Nifty 500 stocks that break above a 2, 3 or 4-year high, with 1-week, 2-week and locking 2-week low stops (then +1% every 2 months) and idle money in gold, dividends included: rules, charts, every trade and the weekly log.">
{style}
{EXTRA_CSS}
</head>
<body>
<div class="wrap site-top"><a class="site-back" href="breakout-desk.html">&larr; Breakout Desk</a></div>
<div class="wrap" id="app"></div>
<div class="wrap site-bottom"><p class="site-disclaimer"><b>Important disclaimer.</b> This is a backtest for educational purposes only, not investment advice or a recommendation to buy or sell any security. Past results, especially from a short test, do not predict future returns. The author is not a SEBI registered financial adviser. Do your own due diligence and consult a qualified financial adviser before acting.</p></div>
<script>
const DATA = {json.dumps(data, separators=(",", ":")).replace("</", "<\\/")};
{helpers}
{charts}
{SCRIPT}
</script>
</body>
</html>
"""
(HERE / "breakout_report.html").write_text(page, encoding="utf-8")
(ROOT / "breakout-study.html").write_text(page, encoding="utf-8")
print("wrote study/breakout_report.html and breakout-study.html", len(page) // 1024, "KB")

# ---- Breakout Desk section: headline numbers of the best-known setup, linking to the full report
HEADLINE = (3, "lock:2:0.05:0.01:2")  # 3-year high, 2-week low then +1% every 2 months
st = next(x for x in data["studies"] if x["years"] == HEADLINE[0])
run = next(r for r in st["runs"] if r["stop"] == HEADLINE[1])
nifty = next(b for b in st["bench"] if b["key"] == "nifty500")
MON = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
month = lambda d: f"{MON[int(d[5:7]) - 1]} {d[:4]}"
pct = lambda v: f"{v * 100:.1f}%".replace("-", "−")
lakh = lambda v: f"₹{v / 1e5:.1f}L"
rupees = lambda v: ("−" if v < 0 else "+") + "₹" + f"{abs(v) / 1e5:.1f} lakh"
section = f"""<!-- breakout-study:start (filled by study/breakout_report.py) -->
      <section class="bd-study" id="study">
        <h2>Backtest: multi-year breakouts</h2>
        <p class="sub">How a rules-based version of this idea would have done: Nifty 500 stocks (the list as it stood each day) closing above a {HEADLINE[0]}-year high set at least a year earlier, up to 10 held at a time, ₹10 lakh to start, {month(st["from"])} to {month(st["to"])}. Its rules are simpler than the desk's (closing prices only, no volume or 30-week MA check).</p>
        <div class="bd-study-stats">
          <div><span class="l">CAGR</span><span class="n">{pct(run["cagr"])}</span><span class="d">Nifty 500 {pct(nifty["cagr"])}</span></div>
          <div><span class="l">Worst fall</span><span class="n">{pct(run["maxDD"])}</span><span class="d">Nifty 500 {pct(nifty["maxDD"])}</span></div>
          <div><span class="l">₹10L became</span><span class="n">{lakh(run["endValue"])}</span><span class="d">Nifty 500 {lakh(nifty["endValue"])}</span></div>
          <div><span class="l">Profit on stocks</span><span class="n">{rupees(run["trades"]["pnl"])}</span><span class="d">{run["trades"]["count"] + run["trades"]["open"]} trades, incl. dividends</span></div>
        </div>
        <p class="bd-study-note">Stop: the lowest close of the last 2 weeks until it is 5% above the buy price, then it rises 1% every 2 months. Idle money waits in GOLDBEES. Tighter stops (last week's or the 2-week low) lost money on the stocks. Much of the gain comes from a few winners still held, and the test is short, so treat it as a guide, not a forecast.</p>
        <a class="text-link" href="breakout-study.html">Read the full backtest: rules, 9 variants, every trade <b>↗</b></a>
      </section>
      <!-- breakout-study:end -->"""
desk_path = ROOT / "breakout-desk.html"
with open(desk_path, encoding="utf-8", newline="") as f:  # keep the file's own line endings
    desk = f.read()
if "\r\n" in desk:
    section = section.replace("\n", "\r\n")
a, b = desk.index("<!-- breakout-study:start"), desk.index("<!-- breakout-study:end -->") + len("<!-- breakout-study:end -->")
with open(desk_path, "w", encoding="utf-8", newline="") as f:
    f.write(desk[:a] + section + desk[b:])
print("updated the backtest section of breakout-desk.html")
