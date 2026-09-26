"""Momentum Scan rules on the whole NSE (not just the Nifty 500): how many stocks to hold, how far a
holding may fall in the ranking before it is sold, and weekly vs monthly rebalancing.

Grid: buy the top N (10, 15 ... 50), sell below rank 2N (20, 30 ... 100), rebalanced at each week's or
each month's last close. Everything else is the Momentum Scan rules (study/momentum_study.py BASE):
  - score: average of return / annualised volatility over 252, 184, 126 and 63 trading days
  - filters: close within 25% of its high since 2015, above its 233-day average, Rs 1 crore average
    daily traded value over the last year, EQ series on the day (no BE/BZ trade-to-trade stocks, no ETFs)
  - market switch: after 3 closes in a row below the Nifty 500's 200-day average, sell everything and
    wait in a liquid fund (6.5% a year); buy back at the first rebalance above it
  - 0.25% a side, no dividends (the NSE file has none), no tax unless stated
For each combination it also runs: with Indian capital-gains tax, with 0.5% a side (wider spreads on small
stocks), and with random picks from the same filtered list (does the ranking add anything?).

Input:  study/nse_prices.npz (study/nse_data.py)
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


class NseData:
    """The same fields momentum_study.Features and backtest read, built from the all-NSE cache."""

    def __init__(self):
        z = np.load(HERE / "nse_prices.npz")
        self.calendar = [str(d) for d in z["calendar"]]
        self.day_index = {d: i for i, d in enumerate(self.calendar)}
        self.symbols = [str(s) for s in z["symbols"]]
        self.col = {s: j for j, s in enumerate(self.symbols)}
        self.index = z["index"]
        self.eq = z["eq"]
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
        self.cash_ret = {}

    def universe_mask(self, name, day):
        return self.eq[self.day_index[day]]


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
    bstats = ms.stats(cal, bench)
    bstats.update(rolling_stats(cal, bench, bench))
    bstats["firstHalf"] = period_cagr(cal, bench, "0000", SPLIT)
    bstats["secondHalf"] = period_cagr(cal, bench, SPLIT, "9999")
    bstats["yearly"] = ms.yearly_returns(cal, bench)
    bstats["drawdowns"] = ms.drawdowns(cal, bench)

    rows, curves = [], {"nifty500": bench}
    for freq, label in FREQS:
        for n in TOP_NS:
            p = replace(BASE, rebalance=freq, top_n=n, exit_rank=2 * n)
            key = f"{'w' if freq == 'weekly' else 'm'}{n}"
            s, run = row_for(feat, p, t0, bench)
            s.update({"key": key, "freq": freq, "freqLabel": label, "topN": n, "exitRank": 2 * n})
            s["afterTax"] = ms.summary(trimmed(ms.backtest(feat, replace(p, taxes=True)), t0))["cagr"]
            s["cost50"] = ms.summary(trimmed(ms.backtest(feat, replace(p, cost=0.005)), t0))["cagr"]
            rnd = [ms.summary(trimmed(ms.backtest(feat, p, rng=np.random.default_rng(seed)), t0))["cagr"]
                   for seed in range(RANDOM_SEEDS)]
            s["random"] = {"median": float(np.median(rnd)), "best": float(max(rnd)), "worst": float(min(rnd))}
            rows.append(s)
            curves[key] = run["equity"] / run["equity"][0]
            print(f"{label:8} top {n:2} exit {2 * n:3}: CAGR {s['cagr']:6.1%}  maxDD {s['maxDD']:6.1%}  "
                  f"Sharpe {s['sharpe']:.2f}  after tax {s['afterTax']:6.1%}  0.5% cost {s['cost50']:6.1%}  "
                  f"random {s['random']['median']:6.1%}  turnover {s['turnoverPerYear']:.1f}x")

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
           "topNs": TOP_NS, "randomSeeds": RANDOM_SEEDS, "rows": rows, "best": best["key"], "bench": bstats,
           "curve": curve, "events": _events_summary()}
    (ROOT / "momentum_nse_study.json").write_text(json.dumps(out, default=ms._json_default, separators=(",", ":")),
                                                   encoding="utf-8")
    print("best overall:", best["key"], "wrote", ROOT / "momentum_nse_study.json")


def _events_summary():
    ev = json.loads((HERE / "nse_events.json").read_text(encoding="utf-8"))
    adj = ev["adjustments"]
    return {"joins": len(ev["joins"]), "adjustments": len(adj), "fromPrices": sum(a["how"] == "prices" for a in adj),
            "etfs": len(ev.get("etfs", [])), "indexLike": len(ev.get("indexLike", {}))}


if __name__ == "__main__":
    main()
