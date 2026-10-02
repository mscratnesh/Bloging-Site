"""HTML report for study/fly_study.py: today's signal and positions, the payoff of any trade, the equity
curves of the two ways of closing over the Supertrend colours, results by year and every trade.

Reuses the look of study/backtest_report_template.html. Called by fly_study.py; can also be run on its own
from study/fly_study.json.
Output: study/fly_report.html (local only)
Run: py study/fly_report.py
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent

CSS = """<style>
:root { --up: #1baf7a; --down: #d03b3b; --s5: #8a63d2; --s6: #6b6a66; }
:root[data-theme="dark"] { --up: #199e70; --down: #e66767; --s5: #a585e6; --s6: #a8a79f; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --up: #199e70; --down: #e66767; --s5: #a585e6; --s6: #a8a79f; } }
.sig { display: inline-flex; align-items: center; gap: 6px; font-weight: 650; }
.sig i { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
.seg { display: inline-flex; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.seg button { font: inherit; font-size: 13.5px; padding: 6px 12px; border: 0; background: var(--surface); color: var(--text-2); cursor: pointer; }
.seg button + button { border-left: 1px solid var(--border); }
.seg button[aria-pressed="true"] { background: var(--s1); color: #fff; font-weight: 600; }
.legs { font-variant-numeric: tabular-nums; font-size: 13.5px; }
.legs td, .legs th { padding: 4px 8px; }
.kv { display: flex; flex-wrap: wrap; gap: 6px 22px; font-size: 13.5px; color: var(--text-2); margin: 8px 0 0; }
.kv b { color: var(--text); font-variant-numeric: tabular-nums; }
tbody tr.pick { cursor: pointer; }
tbody tr.pick:hover td { background: var(--surface-2); }
tbody tr.sel td { background: var(--surface-2); }
.strip-lbl { fill: var(--text-2) !important; }
.brandbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 0 0 18px; padding-bottom: 12px; border-bottom: 2px solid #2f6b46; }
.brandbar a { display: flex; align-items: center; gap: 10px; text-decoration: none; color: var(--text); font-weight: 650; }
.brandbar img { height: 44px; width: auto; }
.brandbar .site { font-size: 13px; color: var(--text-2); }
.disclaimer { margin-top: 36px; font-size: 12.5px; color: var(--text-2); border-top: 1px solid var(--border); padding-top: 14px; }
.sitefoot { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 6px 16px; font-size: 12.5px; color: var(--muted); margin-top: 12px; }
#resTiles .tile .v { font-size: 21px; white-space: nowrap; }
select.trade { font: inherit; font-size: 13.5px; padding: 5px 8px; border-radius: 6px; border: 1px solid var(--border); background: var(--surface); color: var(--text); max-width: 100%; }
</style>"""

BODY = r"""
<div class="wrap" id="app">
<div class="brandbar"><a href="https://letmoneyearn.in/" target="_blank" rel="noopener"><img src="https://raw.githubusercontent.com/mscratnesh/htmlSite/main/images/Let_Money_Earn_Logo_Cropped.png" alt="Let Money Earn"></a><span class="site">Let Money Earn · <a href="https://letmoneyearn.in/" style="display:inline;color:inherit;font-weight:400">letmoneyearn.in</a> · Learn. Invest. Grow.</span><button class="theme-btn" id="themeBtn" type="button" style="float:none">Theme</button></div>
<h1>NIFTY Supertrend butterfly</h1>
<p class="sub">Daily and weekly Supertrend (10, 3) on NIFTY pick the side; a 1-2-1 butterfly with 1000-point
wings is bought on that side, in an expiry at least two months out. Backtested on NSE's F&amp;O bhavcopy,
<span id="span"></span>.</p>
<nav class="nav"><a href="#today">Today</a><a href="#payoff">Payoff</a><a href="#results">Results</a><a href="#years">By year</a><a href="#trades">Trades</a><a href="#method">Method</a></nav>

<h2 id="today" class="first">Today</h2>
<div class="tiles" id="todayTiles"></div>
<div id="openCards"></div>

<h2 id="payoff">Payoff at expiry</h2>
<p class="sub">Profit or loss of one set (lot 65) at expiry for the chosen trade, after its entry debit (costs left out).
Pick a trade here or click one in the trade list.</p>
<div class="card">
  <select class="trade" id="tradePick" aria-label="Trade"></select>
  <div class="kv" id="payKv"></div>
  <div class="legend" id="payLegend" style="margin-top:12px"></div>
  <div class="chart" id="payChart"></div>
  <div class="tbl-wrap"><table class="legs" id="payLegs"></table></div>
</div>

<h2 id="results">Results</h2>
<p class="sub">Rupees for a position of <span id="setsNote"></span> sets (each set 1 lot on each leg: buy 1, sell 2, buy 1)
at a lot of <span id="lotNote"></span> for every year, so years compare. A and B take the same positions on the same days and differ only in when the sets are closed;
C books whole positions and so re-enters on different days. Cumulative profit includes open positions at each day's prices and the cost of <span id="costNote"></span>.</p>
<div id="resTiles"></div>
<div class="card">
  <div class="legend" id="eqLegend"></div>
  <div class="chart" id="eqChart"></div>
  <div class="chart" id="stripChart" style="margin-top:6px"></div>
</div>

<h2 id="years">By year</h2>
<p class="sub">Rupees closed in each year; a booked set counts in the year it was booked.</p>
<div class="card tbl-wrap"><table id="yearTbl"></table></div>

<h2 id="trades">Trades</h2>
<div class="filters"><div class="seg" id="varSeg"></div><span class="muted" id="tradeCount"></span></div>
<div class="card tbl-wrap"><table id="tradeTbl"><thead><tr>
  <th class="sort" data-k="in">Entry</th><th class="sort" data-k="out">Exit</th><th class="sort" data-k="side">Side</th>
  <th>Strikes</th><th class="sort" data-k="expiry">Expiry</th><th class="sort n" data-k="spot_in">NIFTY in</th>
  <th class="sort n" data-k="spot_out">NIFTY out</th><th class="sort n" data-k="debit">Debit</th>
  <th class="sort n" data-k="exit_value">Exit value</th><th class="sort n" data-k="net">Pts a set</th><th class="sort n" data-k="sets">Sets</th><th class="sort n" data-k="rs">Net ₹</th>
  <th class="sort n" data-k="days">Days</th><th class="sort" data-k="why_out">Exit</th>
</tr></thead><tbody></tbody></table></div>

<h2 id="method">Method</h2>
<div class="card"><ul class="rules" id="rules"></ul></div>
<p class="disclaimer"><b>Important disclaimer.</b> This study is for educational purposes only. It is a backtest on past data, not a forecast, and not a recommendation to buy or sell anything. The author is a mutual fund distributor associated with Nirmal Bang and an investor; the author does not give investment advice and is not registered with SEBI as an investment adviser. This content is not issued, reviewed or endorsed by Nirmal Bang. Options can lose the whole amount paid and the sold legs need margin. Do your own due diligence and consult a qualified adviser before acting.</p>
<div class="sitefoot"><span>Ratnesh Kumar Singh · Let Money Earn</span><span><a href="https://letmoneyearn.in/">letmoneyearn.in</a> · <a href="https://t.me/+nxbISOilZJoxOTFl">Telegram</a></span><span>© 2026 Let Money Earn</span></div>
</div>
"""

SCRIPT = r"""
const V = Object.keys(DATA.variants);
const VC = { A: "--s1", B: "--s2", C: "--s3", D: "--s4", E: "--s5", F: "--s6" };
const lbl = v => V.length > 1 ? `${v}. ${esc(DATA.variants[v].name)}` : esc(DATA.variants[v].name);
const num = (v, dp = 0) => v == null ? "–" : v.toLocaleString("en-IN", { maximumFractionDigits: dp, minimumFractionDigits: dp });
const spts = v => `<span class="${cls(v)}">${v > 0 ? "+" : ""}${num(v, 0)}</span>`;
const srs = v => `<span class="${cls(v)}">${v > 0 ? "+" : v < 0 ? "−" : ""}₹${num(Math.abs(v), 0)}</span>`;
const shortRs = v => (v < 0 ? "−" : "") + "₹" + (Math.abs(v) >= 1e5 ? (Math.abs(v) / 1e5).toFixed(1) + "L" : Math.abs(v) >= 1e3 ? Math.round(Math.abs(v) / 1e3) + "k" : Math.abs(v));
const sideName = s => s === "CE" ? "Call side" : "Put side";
const sigHtml = v => v == null ? "–" : `<span class="sig"><i style="background:var(${v ? "--up" : "--down"})"></i>${v ? "Green" : "Red"}</span>`;
const strikes = t => t.ks.map((k, i) => `${i === 1 ? "−2×" : "+1×"} ${k}`).join(" · ");
let curVar = "A", picked = null;

function render() {
  $("#span").textContent = `${fdate(DATA.start)} to ${fdate(DATA.asof)}`;
  $("#lotNote").textContent = DATA.lot;
  $("#setsNote").textContent = DATA.sets;
  $("#costNote").textContent = `${DATA.cost} point per option per trade, none at expiry settlement`;
  const T = DATA.today;
  $("#todayTiles").innerHTML = [["Daily", T.D, T.Dl], ["Weekly", T.W, T.Wl]].map(([k, v, l]) =>
    `<div class="tile"><div class="k">${k} Supertrend</div><div class="v" style="font-size:20px">${sigHtml(v)}</div><div class="c">line ${num(l)}</div></div>`).join("")
    + `<div class="tile"><div class="k">NIFTY close</div><div class="v">${num(T.spot, 2)}</div><div class="c">${fdate(DATA.asof)}</div></div>`;
  $("#openCards").innerHTML = V.map(v => {
    const x = DATA.variants[v], o = x.open, p = x.pending;
    const next = p ? `Next session: ${p[0] === "open" ? "open the " + sideName(p[1]).toLowerCase() : p[0] === "reverse" ? "close and open the " + sideName(p[1]).toLowerCase() : "close the position"}.` : "Nothing to do next session.";
    if (!o) return `<div class="card"><b>${lbl(v)}</b>: no position. ${next}</div>`;
    return `<div class="card"><b>${lbl(v)}</b>: ${sideName(o.side)} since ${fdate(o.in)}, expiry ${fdate(o.expiry)} (${o.tier}).
      <div class="kv"><span>Strikes <b>${strikes(o)}</b></span><span>Debit <b>${num(o.debit, 2)}</b></span>
      <span>Value now <b>${num(o.value_now, 2)}</b></span><span>Open P&amp;L <b>${srs(o.rs * o.sets)}</b> on ${o.sets} set${o.sets > 1 ? "s" : ""} still open (${srs(o.rs)} a set, ${spts(o.open_pnl)} pts)</span></div>
      <p class="muted" style="margin:8px 0 0">${next}</p></div>`;
  }).join("");

  $("#resTiles").innerHTML = V.map(v => {
    const s = DATA.variants[v].stats;
    return `<h3><span class="sw" style="display:inline-block;width:14px;height:3px;border-radius:2px;background:var(${VC[v]});vertical-align:middle;margin-right:8px"></span>${lbl(v)}</h3>
    <div class="tiles">
      <div class="tile"><div class="k">Net</div><div class="v">${srs(s.final)}</div><div class="c">closed ${srs(s.net)}, the rest open</div></div>
      <div class="tile"><div class="k">Positions</div><div class="v">${s.trades}</div><div class="c">${s.wins} won (${s.trades ? Math.round(s.wins / s.trades * 100) : 0}%)${s.booked ? `, ${s.booked} sets booked early` : ""}</div></div>
      <div class="tile"><div class="k">Average position</div><div class="v">${srs(s.avg)}</div><div class="c">best ${srs(s.best)}, worst ${srs(s.worst)}</div></div>
      <div class="tile"><div class="k">Average cost</div><div class="v">₹${num(s.avg_debit)}</div><div class="c">of ${DATA.sets} sets, the most a position can lose</div></div>
      <div class="tile"><div class="k">Max drawdown</div><div class="v">${srs(s.maxdd)}</div><div class="c">from the high</div></div>
      <div class="tile"><div class="k">Held</div><div class="v">${num(s.avg_days)}</div><div class="c">days a position on average</div></div>
    </div>`;
  }).join("");

  const years = [...new Set(V.flatMap(v => Object.keys(DATA.variants[v].stats.years)))].sort();
  $("#yearTbl").innerHTML = `<thead><tr><th>Year</th>${V.map(v => `<th class="n">${lbl(v)}</th>`).join("")}</tr></thead><tbody>`
    + years.map(y => `<tr><td>${y}</td>${V.map(v => `<td class="n">${srs(DATA.variants[v].stats.years[y] || 0)}</td>`).join("")}</tr>`).join("")
    + `<tr class="hl"><td>Total</td>${V.map(v => `<td class="n">${srs(DATA.variants[v].stats.net)}</td>`).join("")}</tr></tbody>`;

  $("#varSeg").style.display = V.length > 1 ? "" : "none";
  $("#varSeg").innerHTML = V.map(v => `<button type="button" data-v="${v}" aria-pressed="${v === curVar}">${v}. ${esc(DATA.variants[v].name)}</button>`).join("");
  $("#varSeg").onclick = e => { const b = e.target.closest("button"); if (!b) return; curVar = b.dataset.v; picked = null; render(); };
  const rows = DATA.variants[curVar].trades.map((t, i) => ({ ...t, i }));
  $("#tradeCount").textContent = `${rows.length} trades · click a row to see its payoff`;
  sortableTable("#tradeTbl", rows, "in", -1, t => `<tr class="pick${picked === t.i ? " sel" : ""}" data-i="${t.i}">
    <td>${fdate(t.in)}</td><td>${fdate(t.out)}</td><td>${sigHtml(t.side === "CE")}</td><td class="num">${strikes(t)}</td>
    <td>${fdate(t.expiry)}<span class="co">${t.tier}</span></td><td class="n">${num(t.spot_in)}</td><td class="n">${num(t.spot_out)}</td>
    <td class="n">${num(t.debit, 2)}</td><td class="n">${num(t.exit_value, 2)}</td><td class="n">${spts(t.net)}</td><td class="n">${t.sets}</td><td class="n">${srs(t.rs)}</td>
    <td class="n">${t.days}</td><td>${t.why_out}${t.untraded ? `<span class="co">${t.untraded} leg price${t.untraded > 1 ? "s" : ""} from settlement</span>` : ""}</td></tr>`);
  $("#tradeTbl tbody").onclick = e => { const r = e.target.closest("tr"); if (!r) return; picked = +r.dataset.i; fillPick(); $("#payoff").scrollIntoView({ behavior: "smooth" }); };

  $("#rules").innerHTML = [
    "Supertrend (10, 3) on NIFTY daily and weekly bars, ATR by Wilder smoothing as on TradingView. The week in progress counts as a bar so far, as the chart shows it at that day's close.",
    "Green: buy 1 call at the nearest in-the-money 1000 strike, sell 2 calls 1000 higher, buy 1 call 2000 higher. Red: the same in puts, downward.",
    `Expiry: between ${DATA.min_dte} and ${DATA.max_dte} days out, the nearest March, June, September or December expiry when all three strikes have open interest; otherwise the nearest monthly expiry that has it; otherwise the nearest listed (marked 'no open interest').`,
    "Enter when daily and weekly are the same colour, on that side; exit when the weekly changes colour, and enter again when the two next agree.",
    `A position is ${DATA.sets} sets. A: all of them run to the weekly flip or expiry. B: one set is booked at the close where the open profit a set first reaches ` + DATA.scale.map(x => "₹" + num(x)).join(", then ") + `; the last set runs as in A. C: all sets run as in A, or all are booked at the close where the open profit a set reaches ₹${num(DATA.book_all)}; the position then waits flat for the next entry signal and re-enters in a later expiry than the booked one, ${DATA.reentry_dte} to ${DATA.max_dte} days out, with open interest on all three strikes.`,
    "At expiry a position settles at intrinsic value on the NIFTY close. A new one opens at that close only if daily and weekly still agree on the same side that day; otherwise it waits flat for the next entry signal.",
    "The signal is taken at a day's close and traded at the next session's close. A leg that traded that day is priced at its close; one that didn't at NSE's settlement price, which is a model price, so treat those fills (counted in the trade list) as approximate.",
    `Costs: ${DATA.cost} point per option per trade (4 options each way), for brokerage, taxes and slippage together. Rupees are for ${DATA.sets} sets at a lot of ${DATA.lot} for all years; NSE's NIFTY lot was 75, 50 and 25 at times.`,
].map(s => `<li>${s}</li>`).join("");

  fillPick();
  drawCharts();
}

function allPicks() {
  const x = DATA.variants[curVar], out = [];
  if (x.open) out.push({ ...x.open, out: null, label: `Open now: ${sideName(x.open.side)} from ${fdate(x.open.in)}`, key: "open" });
  [...x.trades].map((t, i) => ({ ...t, i })).reverse().forEach(t => out.push({ ...t, label: `${fdate(t.in)} → ${fdate(t.out)} · ${sideName(t.side)} · ${srs(t.rs).replace(/<[^>]+>/g, "")}`, key: t.i }));
  return out;
}

function fillPick() {
  const picks = allPicks(), sel = $("#tradePick");
  sel.innerHTML = picks.map(p => `<option value="${p.key}">${esc(p.label)}</option>`).join("");
  if (picked != null) sel.value = picked;
  sel.onchange = () => { picked = sel.value === "open" ? null : +sel.value; drawPayoff(); };
  drawPayoff();
}

function currentPick() {
  const picks = allPicks(), v = $("#tradePick").value;
  return picks.find(p => String(p.key) === v) || picks[0];
}

function payoffAt(t, S) {
  const intr = k => t.side === "CE" ? Math.max(S - k, 0) : Math.max(k - S, 0);
  return intr(t.ks[0]) - 2 * intr(t.ks[1]) + intr(t.ks[2]) - t.debit;
}

function drawPayoff() {
  const el = $("#payChart"), t = currentPick();
  if (!t) { el.innerHTML = "<p class='muted'>No trades.</p>"; return; }
  const lo = Math.min(...t.ks) - DATA.width, hi = Math.max(...t.ks) + DATA.width;
  const W = Math.max(320, el.clientWidth), H = 300, m = { l: 56, r: 16, t: 14, b: 30 };
  const N = 240, xs = Array.from({ length: N + 1 }, (_, i) => lo + (hi - lo) * i / N), ys = xs.map(S => payoffAt(t, S) * DATA.lot);
  const yMax = Math.max(...ys, 0), yMin = Math.min(...ys, 0), pad = (yMax - yMin) * 0.08 || 10;
  const y0 = yMin - pad, y1 = yMax + pad;
  const X = S => m.l + (S - lo) / (hi - lo) * (W - m.l - m.r), Y = v => m.t + (1 - (v - y0) / (y1 - y0)) * (H - m.t - m.b);
  const step = [2500, 5000, 10000, 20000, 25000, 50000].find(s => (y1 - y0) / s <= 6) || 100000;
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Payoff at expiry">`;
  for (let v = Math.ceil(y0 / step) * step; v <= y1; v += step)
    svg += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(v)}" y2="${Y(v)}" stroke="${css(v === 0 ? "--muted" : "--grid")}" stroke-width="1"/><text x="${m.l - 8}" y="${Y(v) + 4}" text-anchor="end">${shortRs(v)}</text>`;
  for (let S = lo; S <= hi; S += DATA.width / 2)
    svg += `<text x="${X(S)}" y="${H - 8}" text-anchor="middle">${num(S)}</text>`;
  const line = xs.map((S, i) => `${i ? "L" : "M"}${X(S).toFixed(1)},${Y(ys[i]).toFixed(1)}`).join("");
  svg += `<clipPath id="cpUp"><rect x="0" y="0" width="${W}" height="${Y(0)}"/></clipPath><clipPath id="cpDn"><rect x="0" y="${Y(0)}" width="${W}" height="${H}"/></clipPath>`;
  svg += `<path d="${line}L${X(hi)},${Y(0)}L${X(lo)},${Y(0)}Z" fill="${css("--up")}" opacity="0.16" clip-path="url(#cpUp)"/>`;
  svg += `<path d="${line}L${X(hi)},${Y(0)}L${X(lo)},${Y(0)}Z" fill="${css("--down")}" opacity="0.16" clip-path="url(#cpDn)"/>`;
  const marks = [[t.spot_in, "Entry", "--s2"], [t.out ? t.spot_out : DATA.today.spot, t.out ? "Exit" : "Today", "--s4"]];
  marks.forEach(([S, name, c], j) => { if (S >= lo && S <= hi) svg += `<line x1="${X(S)}" x2="${X(S)}" y1="${m.t}" y2="${H - m.b}" stroke="${css(c)}" stroke-width="2" stroke-dasharray="4 3"/><text x="${X(S) + 4}" y="${m.t + 10 + 14 * j}" class="strip-lbl">${name}</text>`; });
  svg += `<path d="${line}" fill="none" stroke="${css("--s1")}" stroke-width="2" stroke-linejoin="round"/>`;
  t.ks.forEach(k => svg += `<circle cx="${X(k)}" cy="${Y(payoffAt(t, k) * DATA.lot)}" r="4" fill="${css("--s1")}" stroke="${css("--surface")}" stroke-width="2"/>`);
  svg += `<line id="pxh" y1="${m.t}" y2="${H - m.b}" stroke="${css("--muted")}" stroke-dasharray="3 3" visibility="hidden"/><circle id="pdot" r="4" fill="${css("--s1")}" stroke="${css("--surface")}" stroke-width="2" visibility="hidden"/>`;
  svg += `<rect x="${m.l}" y="0" width="${W - m.l - m.r}" height="${H}" fill="transparent"/></svg><div class="tip"></div>`;
  el.innerHTML = svg;
  const sv = el.querySelector("svg"), tip = el.querySelector(".tip"), xh = sv.querySelector("#pxh"), dot = sv.querySelector("#pdot");
  sv.addEventListener("pointermove", ev => {
    const r = sv.getBoundingClientRect(), px = (ev.clientX - r.left) * (W / r.width);
    const S = Math.round(Math.max(lo, Math.min(hi, lo + (px - m.l) / (W - m.l - m.r) * (hi - lo))) / 10) * 10, v = payoffAt(t, S) * DATA.lot;
    xh.setAttribute("x1", X(S)); xh.setAttribute("x2", X(S)); xh.setAttribute("visibility", "visible");
    dot.setAttribute("cx", X(S)); dot.setAttribute("cy", Y(v)); dot.setAttribute("visibility", "visible");
    tip.innerHTML = `<b>NIFTY ${num(S)} at expiry</b><div class="row"><span>One set</span><b>${srs(v)}</b></div><div class="row"><span>Points</span><b>${spts(v / DATA.lot)}</b></div>`;
    tip.style.display = "block";
    const left = X(S) / W * r.width;
    tip.style.left = (left > r.width / 2 ? left - tip.offsetWidth - 12 : left + 12) + "px"; tip.style.top = "8px";
  });
  sv.addEventListener("pointerleave", () => { tip.style.display = "none"; xh.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); });

  const maxP = DATA.width - t.debit, dir = t.side === "CE" ? 1 : -1;
  const be = [t.ks[0] + dir * t.debit, t.ks[2] - dir * t.debit].sort((a, b) => a - b);
  $("#payKv").innerHTML = `<span>${sigHtml(t.side === "CE")} ${sideName(t.side)}</span><span>Expiry <b>${fdate(t.expiry)}</b></span>
    <span>Debit <b>₹${num(t.debit * DATA.lot)}</b> (${num(t.debit, 2)} pts)</span><span>Max profit <b>₹${num(maxP * DATA.lot)}</b> at ${num(t.ks[1])}</span>
    <span>Max loss <b>₹${num(t.debit * DATA.lot)}</b></span><span>Breakevens <b>${maxP > 0 ? be.map(b => num(b)).join(" and ") : "none"}</b></span>
    ${t.out ? `<span>Result <b>${srs(t.rs)}</b> on ${t.sets} set${t.sets > 1 ? "s" : ""} (${t.why_out})</span>` : `<span>Open P&amp;L <b>${srs(t.rs * t.sets)}</b> on ${t.sets} set${t.sets > 1 ? "s" : ""}</span>`}`;
  $("#payLegend").innerHTML = `<span><i style="background:var(--s1)"></i>P&amp;L at expiry</span><span><i style="background:var(--s2)"></i>NIFTY at entry</span><span><i style="background:var(--s4)"></i>NIFTY at ${t.out ? "exit" : "today"}</span>`;
  const outP = t.out ? t.prices_out : t.prices_now;
  $("#payLegs").innerHTML = `<thead><tr><th>Leg</th><th class="n">Strike</th><th class="n">Entry price</th><th class="n">${t.out ? "Exit" : "Now"}</th></tr></thead><tbody>`
    + t.ks.map((k, i) => `<tr><td>${i === 1 ? "Sell 2" : "Buy 1"} ${t.side}</td><td class="n">${num(k)}</td><td class="n">${num(t.prices_in[i], 2)}</td><td class="n">${num(outP[i], 2)}</td></tr>`).join("") + "</tbody>";
}

function drawEquity() {
  const el = $("#eqChart"), dates = DATA.dates, n = dates.length;
  const W = Math.max(320, el.clientWidth), H = 320, m = { l: 56, r: 64, t: 10, b: 26 };
  const all = V.flatMap(v => DATA.variants[v].curve);
  let lo = Math.min(0, ...all), hi = Math.max(0, ...all);
  const x = i => m.l + i / (n - 1) * (W - m.l - m.r), y = v => m.t + (1 - (v - lo) / (hi - lo)) * (H - m.t - m.b);
  const step = [10000, 20000, 25000, 50000, 100000, 200000].find(s => (hi - lo) / s <= 7) || 500000;
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Cumulative rupees">`;
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step)
    svg += `<line x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}" stroke="${css(v === 0 ? "--muted" : "--grid")}"/><text x="${m.l - 8}" y="${y(v) + 4}" text-anchor="end">${shortRs(v)}</text>`;
  let ly = "";
  dates.forEach((d, i) => { const yr = d.slice(0, 4); if (yr !== ly) { if (ly) svg += `<text x="${x(i)}" y="${H - 6}" text-anchor="middle">${yr}</text>`; ly = yr; } });
  V.forEach(v => {
    const c = DATA.variants[v].curve;
    svg += `<path d="${c.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p).toFixed(1)}`).join("")}" fill="none" stroke="${css(VC[v])}" stroke-width="2" stroke-linejoin="round"/>`;
    svg += `<text x="${x(n - 1) + 6}" y="${y(c[n - 1]) + 4}" class="strip-lbl">${V.length > 1 ? v + " " : ""}${shortRs(c[n - 1])}</text>`;
  });
  svg += `<line id="xh" y1="${m.t}" y2="${H - m.b}" stroke="${css("--muted")}" stroke-dasharray="3 3" visibility="hidden"/>`;
  V.forEach(v => svg += `<circle class="dot" r="4" fill="${css(VC[v])}" stroke="${css("--surface")}" stroke-width="2" visibility="hidden"/>`);
  svg += `<rect x="${m.l}" y="0" width="${W - m.l - m.r}" height="${H}" fill="transparent"/></svg><div class="tip"></div>`;
  el.innerHTML = svg;
  $("#eqLegend").innerHTML = V.map(v => `<span><i style="background:var(${VC[v]})"></i>${lbl(v)}</span>`).join("");
  const sv = el.querySelector("svg"), tip = el.querySelector(".tip"), xh = sv.querySelector("#xh"), dots = sv.querySelectorAll(".dot");
  sv.addEventListener("pointermove", ev => {
    const r = sv.getBoundingClientRect(), px = (ev.clientX - r.left) * (W / r.width);
    const i = Math.max(0, Math.min(n - 1, Math.round((px - m.l) / (W - m.l - m.r) * (n - 1))));
    xh.setAttribute("x1", x(i)); xh.setAttribute("x2", x(i)); xh.setAttribute("visibility", "visible");
    V.forEach((v, k) => { dots[k].setAttribute("cx", x(i)); dots[k].setAttribute("cy", y(DATA.variants[v].curve[i])); dots[k].setAttribute("visibility", "visible"); });
    tip.innerHTML = `<b>${fdate(dates[i])}</b>` + V.map(v => `<div class="row"><span><span class="sw" style="background:var(${VC[v]})"></span>${v}</span><b>${srs(DATA.variants[v].curve[i])}</b></div>`).join("");
    tip.style.display = "block";
    const left = x(i) / W * r.width;
    tip.style.left = (left > r.width / 2 ? left - tip.offsetWidth - 12 : left + 12) + "px"; tip.style.top = "8px";
  });
  sv.addEventListener("pointerleave", () => { tip.style.display = "none"; xh.setAttribute("visibility", "hidden"); dots.forEach(d => d.setAttribute("visibility", "hidden")); });

  // Supertrend colours under the curve, on the same x scale
  const sEl = $("#stripChart"), idx = Object.fromEntries(dates.map((d, i) => [d, i])), rowH = 12, gap = 4;
  let s2 = `<svg viewBox="0 0 ${W} ${2 * (rowH + gap)}" role="img" aria-label="Supertrend colours: daily, weekly">`;
  [["D", "Daily"], ["W", "Weekly"]].forEach(([k, name], r) => {
    const yy = r * (rowH + gap);
    s2 += `<text x="${m.l - 8}" y="${yy + rowH - 2}" text-anchor="end" class="strip-lbl">${name}</text>`;
    DATA.strip[k].forEach(([a, b, v]) => {
      const x0 = x(idx[a]), x1 = x(Math.min(n - 1, idx[b] + 1));
      s2 += `<rect x="${x0.toFixed(1)}" y="${yy}" width="${Math.max(0.5, x1 - x0).toFixed(1)}" height="${rowH}" fill="${css(v == null ? "--mid" : v ? "--up" : "--down")}"><title>${name} ${v == null ? "n/a" : v ? "green" : "red"}: ${fdate(a)} – ${fdate(b)}</title></rect>`;
    });
  });
  sEl.innerHTML = s2 + "</svg>";
}

function drawCharts() { drawEquity(); drawPayoff(); }

$("#themeBtn").onclick = () => {
  const dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("bt-theme", document.documentElement.dataset.theme); } catch (e) {}
  drawCharts();
};
try { const t = localStorage.getItem("bt-theme"); if (t) document.documentElement.dataset.theme = t; } catch (e) {}
render();
let rz; addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(drawCharts, 150); });
if (matchMedia) matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", drawCharts);
"""


def build(data):
    src = (HERE / 'backtest_report_template.html').read_text(encoding='utf-8')
    style = re.search(r'<style>.*?</style>', src, re.S).group(0)
    helpers = src[src.index('const $ = '):src.index('const STATUS')] + \
        src[src.index('function sortableTable'):src.index('function monthCard')] + \
        src[src.index('function css(v)'):src.index('function lineChart')]
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NIFTY Supertrend Butterfly</title>
<meta name="author" content="Ratnesh Kumar Singh, Let Money Earn">
<meta name="description" content="Let Money Earn backtest of a NIFTY butterfly traded on daily and weekly Supertrend colours, with payoff diagrams and every trade.">
{style}
{CSS}
</head>
<body>
{BODY}
<script>
const DATA = {json.dumps(data, separators=(',', ':'))};
{helpers}
{SCRIPT}
</script>
</body>
</html>"""
    (HERE / 'fly_report.html').write_text(html, encoding='utf-8')


if __name__ == '__main__':
    build(json.loads((HERE / 'fly_study.json').read_text(encoding='utf-8')))
    print('wrote study/fly_report.html')
