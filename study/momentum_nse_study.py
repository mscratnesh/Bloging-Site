"""Momentum Scan rules on the whole NSE (not just the Nifty 500): how many stocks to hold, how far a
holding may fall in the ranking before it is sold, and weekly vs monthly rebalancing.

Grid: buy the top N (10, 15 ... 50), sell below rank 2N (20, 30 ... 100), rebalanced at each week's or
each month's last close. Everything else is the Momentum Scan rules (study/momentum_study.py BASE):
  - score: average of return / annualised volatility over 252, 184, 126 and 63 trading days
  - filters: close within 25% of its high since 2015, above its 233-day average, Rs 1 crore average
    daily traded value over the last year, traded that day in any series (EQ, or the BE/BZ trade-to-trade
    series a stock can be moved into), no ETFs
  - market switch: after 3 closes in a row below the Nifty 500's 200-day average, sell everything and
    wait in a liquid fund (6.5% a year); buy back at the first rebalance above it
  - splits and bonuses adjusted; dividends (from NSE's corporate-actions list) paid into cash on the
    ex-date; 0.25% a side; no tax unless stated
For each combination it also runs: with Indian capital-gains tax (and 30% on dividends), with 0.5% a side
(wider spreads on small stocks), EQ series only (the old rule), without dividends, skipping buys in a stock
that closed locked at an upper circuit (no sellers, so the order would not fill; far more common in BE/BZ),
and with random picks from the same filtered list (does the ranking add anything?).
It also runs every combination with the Momentum 50 rule in place of the market switch ("ma50"): no new
buys while the Nifty500 Momentum 50 closes below its 50-day average, empty slots filled on the day it
closes back above, holdings sold only by the ranking (no switch to the liquid fund).

Second benchmark: the Nifty500 Momentum 50 index (price), the fund version of this idea. Index closes to
22 May 2026 (study/nf500mom50_index.json), then carried on with the daily moves of a Momentum 50 ETF
(study/nf500mom50_etf.json); both from the author's own export.

Input:  study/nse_prices.npz (study/nse_data.py), study/nf500mom50_index.json, study/nf500mom50_etf.json
Output: momentum_nse_study.json
Run:    py study/momentum_nse_study.py
"""
import json
import sys
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import momentum_study as ms  # noqa: E402

TOP_NS = (10, 15, 20, 25, 30, 35, 40, 45, 50)
FREQS = (("weekly", "Weekly"), ("month_end", "Monthly"))
SPLIT = "2021-01-01"  # first half / second half
RANDOM_SEEDS = 10
BASE = replace(ms.BASE, universe="nse")
MA50 = dict(market_ma=None, buy_gate_ma=50, buy_gate_fill=True)  # the Momentum 50 rule instead of the switch


class NseData:
    """The same fields momentum_study.Features and backtest read, built from the all-NSE cache."""

    def __init__(self):
        z = np.load(HERE / "nse_prices.npz")
        self.calendar = [str(d) for d in z["calendar"]]
        self.day_index = {d: i for i, d in enumerate(self.calendar)}
        self.symbols = [str(s) for s in z["symbols"]]
        self.col = {s: j for j, s in enumerate(self.symbols)}
        self.index = z["index"]
        self.series = z["series"]
        self.div = z["div"]
        close = z["close"]
        self.ath = np.fmax.accumulate(np.fmax(z["high"], close), axis=0)
        self.turnover_daily = z["value"]
        filled, gap = close.copy(), np.zeros(close.shape[1])
        for i in range(1, len(filled)):
            missing = np.isnan(filled[i])
            gap = np.where(missing, gap + 1, 0)
            use = missing & (gap <= ms.MAX_FFILL)
            filled[i, use] = filled[i - 1, use]
        self.close = filled
        with np.errstate(invalid="ignore", divide="ignore"):
            r = filled[1:] / filled[:-1] - 1
        r[np.abs(r) > ms.MAX_DAILY_MOVE] = np.nan
        self.ret = np.vstack([np.full((1, close.shape[1]), np.nan), r])
        # closed at the day's high after a rise of 1.9% or more (BE/BZ bands can be 2%): an upper circuit
        self.locked = (close >= z["high"] * 0.999) & (np.nan_to_num(self.ret) > 0.019)
        self.cash_ret = {}

    def universe_mask(self, name, day):
        s = self.series[self.day_index[day]]
        return s == 1 if name == "nse_eq" else s > 0


def trimmed(run, t0):
    """The run from calendar index t0 on, so weekly and monthly are scored over the same days."""
    k = run["dates"].index(run_cal[t0])
    out = dict(run)
    out["equity"] = run["equity"][k:]
    out["dates"] = run["dates"][k:]
    out["trades"] = [t for t in run["trades"] if t["exit"] >= run_cal[t0]]
    return out


def period_cagr(dates, eq, lo, hi):
    idx = [i for i, d in enumerate(dates) if lo <= d < hi]
    a, b = idx[0], idx[-1]
    years = (date.fromisoformat(dates[b]) - date.fromisoformat(dates[a])).days / 365.25
    return float((eq[b] / eq[a]) ** (1 / years) - 1)


def rolling_stats(dates, eq, bench, days=756):
    """3-year windows, every week: worst and median CAGR, and how often the strategy beat the Nifty 500."""
    s = eq[days:] / eq[:-days]
    b = bench[days:] / bench[:-days]
    s, b = s[::5], b[::5]
    cagr = s ** (252 / days) - 1
    one = eq[252:] / eq[:-252] - 1
    return {"worst3y": float(cagr.min()), "median3y": float(np.median(cagr)),
            "beat3y": float(np.mean(s > b)), "worst1y": float(one.min())}


def row_for(feat, p, t0, bench):
    run = trimmed(ms.backtest(feat, p, record=True), t0)
    s = ms.summary(run)
    dates, eq = run["dates"], run["equity"]
    s.update(rolling_stats(dates, eq, bench))
    s["firstHalf"] = period_cagr(dates, eq, "0000", SPLIT)
    s["secondHalf"] = period_cagr(dates, eq, SPLIT, "9999")
    s["yearly"] = ms.yearly_returns(dates, eq)
    s["exits"] = sum(1 for e in run["events"] if e["type"] == "EXIT")
    expo = [(t, h) for t, h, _ in run["exposure"] if t >= t0]
    s["invested"] = float(np.mean([bool(h) for _, h in expo]))
    held = [len(h) for _, h in expo if h]
    s["avgHoldings"] = float(np.mean(held)) if held else 0.0
    s["rebalances"] = sum(1 for t in run["rebalances"] if t >= t0)
    s["trade"] = ms.trade_stats(run["trades"], feat.data) if run["trades"] else None
    s["capacity"] = ms.capacity(feat, run)
    s["drawdowns"] = ms.drawdowns(dates, eq)
    return s, run


def mom50(calendar):
    """Nifty500 Momentum 50 on the study calendar: the index, then the ETF's moves after the index data ends."""
    idx = json.loads((HERE / "nf500mom50_index.json").read_text(encoding="utf-8"))
    etf = json.loads((HERE / "nf500mom50_etf.json").read_text(encoding="utf-8"))
    join = max(idx)
    series = dict(idx)
    series.update({d: idx[join] * v / etf[join] for d, v in etf.items() if d > join})
    keys = sorted(series)
    out, j, last = np.full(len(calendar), np.nan), 0, np.nan
    for i, day in enumerate(calendar):
        while j < len(keys) and keys[j] <= day:
            last = series[keys[j]]
            j += 1
        out[i] = last
    return out, join


def bench_stats(cal, curve, ref):
    b = ms.stats(cal, curve)
    b.update(rolling_stats(cal, curve, ref))
    b["firstHalf"] = period_cagr(cal, curve, "0000", SPLIT)
    b["secondHalf"] = period_cagr(cal, curve, SPLIT, "9999")
    b["yearly"] = ms.yearly_returns(cal, curve)
    b["drawdowns"] = ms.drawdowns(cal, curve)
    return b


def main():
    global run_cal
    data = NseData()
    run_cal = data.calendar
    feat = ms.Features(data)
    print(f"{len(data.symbols)} stocks, {data.calendar[0]} to {data.calendar[-1]}")

    # common start: the later of the first weekly and first monthly rebalance
    first = {f: ms.backtest(feat, replace(BASE, rebalance=f, top_n=10, exit_rank=20))["rebalances"][0] for f, _ in FREQS}
    t0 = max(first.values())
    cal = data.calendar[t0:]
    bench = data.index[t0:] / data.index[t0]
    bstats = bench_stats(cal, bench, bench)
    m50, m50_join = mom50(data.calendar)
    data.buy_gate = m50  # the gate for the MA50 runs
    m50 = m50[t0:] / m50[t0]
    m50stats = bench_stats(cal, m50, bench)  # beat3y here: how often it beat the Nifty 500
    m50stats["indexTo"] = m50_join

    rows, curves = [], {"nifty500": bench, "mom50": m50}
    for freq, label in FREQS:
        for n in TOP_NS:
            p = replace(BASE, rebalance=freq, top_n=n, exit_rank=2 * n)
            key = f"{'w' if freq == 'weekly' else 'm'}{n}"
            s, run = row_for(feat, p, t0, bench)
            s.update({"key": key, "freq": freq, "freqLabel": label, "topN": n, "exitRank": 2 * n})
            s["afterTax"] = ms.summary(trimmed(ms.backtest(feat, replace(p, taxes=True)), t0))["cagr"]
            s["cost50"] = ms.summary(trimmed(ms.backtest(feat, replace(p, cost=0.005)), t0))["cagr"]
            s["eqOnly"] = ms.summary(trimmed(ms.backtest(feat, replace(p, universe="nse_eq")), t0))["cagr"]
            s["skipLocked"] = ms.summary(trimmed(ms.backtest(feat, replace(p, skip_locked=True)), t0))["cagr"]
            s["noDiv"] = ms.summary(trimmed(ms.backtest(feat, replace(p, dividends=False)), t0))["cagr"]
            g, grun = row_for(feat, replace(p, **MA50), t0, bench)
            s["ma50"] = {k: g[k] for k in ("cagr", "maxDD", "vol", "sharpe", "calmar", "worst3y", "worst1y", "beat3y",
                                          "firstHalf", "secondHalf", "yearly", "invested", "turnoverPerYear", "multiple")}
            s["ma50"]["afterTax"] = ms.summary(trimmed(ms.backtest(feat, replace(p, taxes=True, **MA50)), t0))["cagr"]
            s["ma50"]["fills"] = sum(1 for e in grun["events"] if e["type"] == "FILL")
            curves[key + "g"] = grun["equity"] / grun["equity"][0]
            rnd = [ms.summary(trimmed(ms.backtest(feat, p, rng=np.random.default_rng(seed)), t0))["cagr"]
                   for seed in range(RANDOM_SEEDS)]
            s["random"] = {"median": float(np.median(rnd)), "best": float(max(rnd)), "worst": float(min(rnd))}
            rows.append(s)
            curves[key] = run["equity"] / run["equity"][0]
            print(f"{label:8} top {n:2} exit {2 * n:3}: CAGR {s['cagr']:6.1%}  maxDD {s['maxDD']:6.1%}  "
                  f"Sharpe {s['sharpe']:.2f}  after tax {s['afterTax']:6.1%}  0.5% cost {s['cost50']:6.1%}  "
                  f"EQ only {s['eqOnly']:6.1%}  skip locked {s['skipLocked']:6.1%}  no div {s['noDiv']:6.1%}  "
                  f"random {s['random']['median']:6.1%}  turnover {s['turnoverPerYear']:.1f}x | MA50: CAGR "
                  f"{s['ma50']['cagr']:6.1%}  maxDD {s['ma50']['maxDD']:6.1%}  Sharpe {s['ma50']['sharpe']:.2f}")

    # overall score: average rank on CAGR, Sharpe, Calmar, after-tax CAGR, worst 3-year CAGR, weaker half
    metrics = {"cagr": 1, "sharpe": 1, "calmar": 1, "afterTax": 1, "worst3y": 1}
    for r in rows:
        r["weakHalf"] = min(r["firstHalf"], r["secondHalf"])
    metrics["weakHalf"] = 1
    for m in metrics:
        order = sorted(rows, key=lambda r: -r[m])
        for i, r in enumerate(order):
            r.setdefault("ranks", {})[m] = i + 1
    for r in rows:
        r["score"] = float(np.mean(list(r["ranks"].values())))
    best = min(rows, key=lambda r: r["score"])

    step = max(1, len(cal) // 700)
    keep = list(range(0, len(cal), step)) + ([len(cal) - 1] if (len(cal) - 1) % step else [])
    curve = [{"d": cal[i], **{k: round(float(v[i]), 4) for k, v in curves.items()}} for i in keep]

    out = {"generatedAt": datetime.now().isoformat(timespec="seconds"), "asOf": data.calendar[-1], "from": cal[0],
           "split": SPLIT, "stocks": len(data.symbols), "rules": {k: v for k, v in BASE.__dict__.items()},
           "topNs": TOP_NS, "randomSeeds": RANDOM_SEEDS, "rows": rows, "best": best["key"], "bench": bstats, "mom50": m50stats,
           "curve": curve, "events": _events_summary(), "locked": _locked_share(data)}
    (ROOT / "momentum_nse_study.json").write_text(json.dumps(out, default=ms._json_default, separators=(",", ":")),
                                                   encoding="utf-8")
    print("best overall:", best["key"], "wrote", ROOT / "momentum_nse_study.json")


def _events_summary():
    ev = json.loads((HERE / "nse_events.json").read_text(encoding="utf-8"))
    adj = ev["adjustments"]
    return {"joins": len(ev["joins"]), "adjustments": len(adj), "fromPrices": sum(a["how"] == "prices" for a in adj),
            "etfs": len(ev.get("etfs", [])), "indexLike": len(ev.get("indexLike", {})),
            "dividends": ev.get("dividends", 0), "barsBySeries": ev.get("barsBySeries", {})}


def _locked_share(data):
    """How often a bar closed locked at an upper circuit, by series."""
    return {"eq": float(data.locked[data.series == 1].mean()), "beBz": float(data.locked[data.series > 1].mean())}


if __name__ == "__main__":
    main()
