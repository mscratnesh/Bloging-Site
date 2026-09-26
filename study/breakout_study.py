"""Multi-year breakout study on the same data and point-in-time Nifty 500 lists as the momentum study.

Breakout: a stock closes above the highest high of the previous `years` years, and that high was set
at least `base_days` sessions earlier (a long base, not a stock already making new highs). The stock
must have `years` of price history (90% of sessions), be in the Nifty 500 list of the day and trade
Rs 1 crore a day on average over the last year.

Portfolio (checked daily, trades at the close):
  - Every week-end the watchlist is refreshed: stocks that broke out in the last `fresh_weeks` weeks
    and still close above their breakout level, best momentum score first, at most `watch_n`.
  - Free slots are filled from the top of the watchlist, up to `slots` holdings. Rs 10 lakh to start
    (Rs 1 lakh a slot). Money not in stocks waits in one pool in GOLDBEES; each buy gets the pool
    divided by the number of empty slots (2 empty slots and Rs 1.9 lakh: Rs 95,000 each). So a stock
    sold for Rs 1.1 lakh funds the next buy with Rs 1.1 lakh, plus or minus what gold did meanwhile.
  - Stop: sell on the day a stock closes below the previous week's lowest close (or the lowest close
    of the last 2 weeks). The price cache has no daily lows, so a week's low is its lowest close and
    the stop fills at that day's close.

Each lookback (2, 3, 4 years) is a separate backtest from the first day its breakouts can be measured,
run with both stops and compared with the Nifty 500 and GOLDBEES.
  - 0.25% cost on every buy and sell, of stocks and of GOLDBEES. No tax.

Dividends: a holding gets its dividend on the ex-date, added to the stock's value (as if reinvested in
the stock). Dividend tax is ignored, like capital-gains tax. The Nifty 500 benchmark is the price index,
without dividends.

Inputs: same as study/momentum_study.py, plus study/dividends.json (study/fetch_dividends.py)
Output: breakout_study.json
Run: py study/breakout_study.py
"""
import json
import sys
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import momentum_study as ms  # noqa: E402

CAPITAL = 1_000_000  # Rs 1 lakh per slot x 10 slots
HORIZONS = {"1m": 21, "3m": 63, "6m": 126, "12m": 252}


@dataclass(frozen=True)
class Params:
    years: int = 3                  # breakout above the highest high of this many years
    base_days: int = 252            # ... set at least this many sessions ago
    fresh_weeks: int = 4            # watchlist keeps a breakout this many weeks
    watch_n: int = 20
    slots: int = 10
    stop: str = "prev_week"         # "prev_week" | "low_weeks:N" (lowest close of the last N weeks) | "entry_week" (fixed at buy) | "none"
    #                                 | "lock:N:G:M:P": lowest close of the last N weeks until that stop is G above the buy price;
    #                                   from then on it stops following the lows and rises M every P months from that level
    rank: str = "momentum"          # "momentum" (momentum-study score) | "recent" (newest breakout first)
    market_ma: int = None           # e.g. 200: buy only while the Nifty 500 closes above its 200-day average
    min_turnover: float = 1e7
    cost: float = 0.0025
    start: str = None               # first trading day; None = first day signals are possible for `years`
    cash_asset: str = "GOLDBEES"    # where idle money waits; None = liquid fund at 6.5% a year
    dividends: bool = True          # add dividends to holdings on the ex-date


BASE = Params()


def rolling_max(a, n):
    """out[t] = max of rows t-n .. t-1 (NaN rows ignored; NaN if none)."""
    a2 = np.where(np.isnan(a), -np.inf, a)
    out = np.full(a.shape, -np.inf)
    out[n:] = sliding_window_view(a2, n, axis=0).max(axis=-1)[:-1]
    out[out == -np.inf] = np.nan
    return out


class Breakouts:
    def __init__(self, data, feat):
        self.data, self.feat = data, feat
        d = data
        # Split-adjusted prices: the daily returns skip jumps over 60% (splits, bonus issues, demergers),
        # so chaining them gives a series without those jumps, scaled to the latest actual price.
        # Breakouts and stops use these; trades are still shown at the actual prices.
        chain = np.cumprod(1 + np.nan_to_num(d.ret), axis=0)
        with np.errstate(invalid="ignore", divide="ignore"):
            factor = chain / d.close
        last = np.array([factor[np.flatnonzero(~np.isnan(factor[:, j]))[-1], j] if (~np.isnan(factor[:, j])).any() else 1.0
                         for j in range(factor.shape[1])])
        factor /= last
        self.px = d.raw_close * factor
        self.hi = np.fmax(d.high, d.raw_close) * factor
        self._cache = {}
        cal = d.calendar
        wk = [date.fromisoformat(x).isocalendar()[:2] for x in cal]
        self.week_end = np.array([i == len(cal) - 1 or wk[i + 1] != wk[i] for i in range(len(cal))])
        self.week_id = np.cumsum(np.concatenate([[0], self.week_end[:-1]]))
        idx = np.arange(len(cal))
        self.week_first = np.array([idx[self.week_id == w][0] for w in range(self.week_id[-1] + 1)])
        self.week_start = self.week_first[self.week_id]
        # dividend yield on each ex-date (T x N), from study/dividends.json
        self.div = np.zeros(d.close.shape)
        path = HERE / "dividends.json"
        for sym, divs in (json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}).items():
            j = d.col.get(sym)
            for day, y in divs.items() if j is not None else ():
                t = d.day_index.get(day)
                if t is not None:
                    self.div[t, j] += y
        self.turn_ok = np.zeros(d.close.shape, dtype=bool)
        for t in range(len(cal)):
            with np.errstate(invalid="ignore"):
                self.turn_ok[t] = feat.turnover(t) > 1e7

    def signals(self, years, base_days):
        """(signal T x N bool, breakout level T x N) for the given lookback."""
        key = (years, base_days)
        if key in self._cache:
            return self._cache[key]
        d, n = self.data, years * ms.TRADING_DAYS
        level = rolling_max(self.hi, n)
        recent = rolling_max(self.hi, base_days)
        cnt = self.feat.p_cnt  # cumulative count of closes; rows t-n..t-1 = cnt[t] - cnt[t-n]
        have = np.zeros(d.close.shape)
        have[n:] = cnt[n:-1] - cnt[:-n - 1]
        with np.errstate(invalid="ignore"):
            sig = (self.px > level) & (recent < level) & (have >= n * ms.COVERAGE)
        self._cache[key] = (sig, level)
        return sig, level

    def first_signal_day(self, years):
        return years * ms.TRADING_DAYS + 1


def backtest(b, p, record=False):
    """Each of `slots` slots keeps its own money: it holds one stock or waits in the cash asset, and
    its next buy uses whatever the slot is worth then (sell a stock for Rs 1.1 lakh, buy the next with it)."""
    d, feat = b.data, b.feat
    cal = d.calendar
    sig, level = b.signals(p.years, p.base_days)
    t0 = b.first_signal_day(p.years) if p.start is None else next(i for i, x in enumerate(cal) if x >= p.start)
    t0 = max(t0, b.first_signal_day(p.years))
    liquid = (1 + ms.LIQUID_ANNUAL) ** (1 / ms.TRADING_DAYS) - 1
    idle_ret = d.cash_ret[p.cash_asset] if p.cash_asset else np.full(len(cal), liquid)
    idle_cost = p.cost if p.cash_asset else 0.0  # buying/selling the gold ETF
    msma = ms.market_sma(d.index, p.market_ma) if p.market_ma else None
    lows = int(p.stop.split(":")[1]) if p.stop.startswith(("low_weeks:", "lock:")) else 1
    lock_gain, lock_step, lock_months = ((float(x) for x in (p.stop.split(":") + ["1"])[2:5]) if p.stop.startswith("lock:")
                                         else (None, None, None))

    per_slot = CAPITAL / p.slots
    slots = [{"j": None, "v": per_slot * (1 - idle_cost)} for _ in range(p.slots)]  # all start in gold
    watch = {}  # col -> {"day", "t", "level"}
    equity, trades, weeks = [], [], []

    def sell(s, t, why):
        j, e = s["j"], s
        proceeds = s["v"] * (1 - p.cost)
        trades.append({"s": d.symbols[j], "in": e["day"], "out": cal[t], "inPx": e["px"], "outPx": float(d.close[t, j]),
                       "ret": proceeds / e["basis"] - 1, "pnl": proceeds - e["basis"], "basis": e["basis"],
                       "days": (date.fromisoformat(cal[t]) - date.fromisoformat(e["day"])).days, "why": why, "brk": e["brk"],
                       "locked": e.get("lock") and e["lock"][1], "div": e["div"] * (1 - p.cost)})
        s.clear()
        s.update({"j": None, "v": proceeds * (1 - idle_cost)})

    for t in range(t0, len(cal)):
        day = cal[t]
        if t > t0:
            for s in slots:
                if s["j"] is None:
                    s["v"] *= 1 + idle_ret[t]
                else:
                    r = d.ret[t, s["j"]]
                    s["v"] *= 1 + (0.0 if np.isnan(r) else r)
                    if p.dividends and b.div[t, s["j"]]:  # held into the ex-date: the price drop is paid back
                        paid = s["v"] * b.div[t, s["j"]]
                        s["v"] += paid
                        s["div"] += paid
        sold_today = set()
        for s in slots:
            j = s["j"]
            if j is None:
                continue
            px = b.px[t, j]
            if np.isnan(d.close[t, j]):
                sold_today.add(j)
                sell(s, t, "no prices")
            elif not np.isnan(px) and s["sl"] is not None and px < s["sl"]:
                sold_today.add(j)
                sell(s, t, "stop")

        if b.week_end[t]:
            ws = b.week_start[t]
            for i in range(max(ws, t0), t + 1):
                for j in np.flatnonzero(sig[i]):
                    watch[j] = {"day": cal[i], "t": i, "level": float(level[i, j])}
            universe = d.universe_mask("pit500", day)
            limit = t - p.fresh_weeks * 5 + 1
            for j in list(watch):
                w = watch[j]
                px = b.px[t, j]
                if w["t"] < limit or (not np.isnan(px) and px <= w["level"]):
                    del watch[j]
            held = {s["j"] for s in slots if s["j"] is not None}
            cands = [j for j in watch if universe[j] and b.turn_ok[t, j] and not np.isnan(b.px[t, j])]
            if p.rank == "momentum":
                sc = feat.score(t, ms.BASE)
                cands.sort(key=lambda j: -(sc[j] if not np.isnan(sc[j]) else -99))
            else:
                cands.sort(key=lambda j: -watch[j]["t"])
            cands = cands[:p.watch_n]
            market_ok = msma is None or np.isnan(msma[t]) or d.index[t] > msma[t]
            bought = []
            if market_ok:
                free = [s for s in slots if s["j"] is None]
                pool = sum(s["v"] for s in free)  # one gold pool, shared equally by the empty slots
                for s in free:
                    s["v"] = pool / len(free) if free else 0.0
                for j in cands:
                    if not free:
                        break
                    if j in held or j in sold_today:
                        continue
                    s = free.pop(0)
                    basis = s["v"] * (1 - idle_cost)  # sell the gold, buy the stock with all of it
                    s.update({"j": j, "v": basis * (1 - p.cost), "basis": basis, "day": day, "t": t, "px": float(d.close[t, j]),
                              "adj": float(b.px[t, j]), "brk": watch[j]["day"], "level": watch[j]["level"], "sl": None, "lock": None, "div": 0.0})
                    bought.append(j)
            # stop for the coming week: lowest close of the last `lows` completed weeks
            first = b.week_first[max(0, b.week_id[t] - lows + 1)]
            for s in slots:
                j = s["j"]
                if j is None:
                    continue
                if p.stop == "none":
                    s["sl"] = None
                elif p.stop == "entry_week":
                    s["sl"] = s["sl"] if s["sl"] is not None else float(np.nanmin(b.px[ws:t + 1, j]))
                elif lock_gain is not None and s["lock"]:
                    lvl, since = s["lock"]
                    months = (date.fromisoformat(day) - date.fromisoformat(since)).days / 30.4375
                    s["sl"] = lvl * (1 + lock_step) ** (months / lock_months)
                else:
                    s["sl"] = float(np.nanmin(b.px[first:t + 1, j]))
                    if lock_gain is not None and s["sl"] >= s["adj"] * (1 + lock_gain):
                        s["lock"] = (s["sl"], day)  # stop is 5% above the buy price: stop trailing the lows
            if record:
                total = sum(s["v"] for s in slots)
                weeks.append({"date": day, "watch": [{"s": d.symbols[j], "brk": watch[j]["day"], "lvl": round(watch[j]["level"], 2),
                                                      "px": round(float(b.px[t, j]), 2)} for j in cands],
                              "bought": [d.symbols[j] for j in bought], "held": sum(s["j"] is not None for s in slots),
                              "marketOk": bool(market_ok), "cash": sum(s["v"] for s in slots if s["j"] is None) / total})
        equity.append(sum(s["v"] for s in slots))
    open_ = []
    for s in slots:  # still open at the end
        if s["j"] is not None:
            j = s["j"]
            trades.append({"s": d.symbols[j], "in": s["day"], "out": None, "inPx": s["px"], "outPx": float(d.close[len(cal) - 1, j]),
                           "ret": s["v"] / s["basis"] - 1, "pnl": s["v"] - s["basis"], "basis": s["basis"],
                           "days": (date.fromisoformat(cal[-1]) - date.fromisoformat(s["day"])).days, "why": "open", "brk": s["brk"],
                           "locked": s["lock"] and s["lock"][1], "div": s["div"]})
            open_.append({"s": d.symbols[j], "in": s["day"], "sl": s["sl"], "value": s["v"]})
    return {"dates": cal[t0:], "equity": np.array(equity), "trades": trades, "weeks": weeks, "t0": t0, "open": open_,
            "slots": [round(s["v"]) for s in slots]}


def trade_stats(trades):
    closed = [x for x in trades if x["out"]]
    r = np.array([x["ret"] for x in closed])
    if not len(r):
        return {"count": 0, "open": len(trades), "pnl": float(sum(x["pnl"] for x in trades)),
                "dividends": float(sum(x.get("div", 0) for x in trades))}
    win, loss = r[r > 0], r[r <= 0]
    return {"count": len(closed), "open": len(trades) - len(closed), "winRate": float((r > 0).mean()),
            "pnl": float(sum(x["pnl"] for x in trades)),
            "dividends": float(sum(x.get("div", 0) for x in trades)),
            "openPnl": float(sum(x["pnl"] for x in trades if not x["out"])),
            "avgWin": float(win.mean()) if len(win) else 0.0, "avgLoss": float(loss.mean()) if len(loss) else 0.0,
            "avgRet": float(r.mean()), "medianDays": float(np.median([x["days"] for x in closed])),
            "payoff": float(win.mean() / -loss.mean()) if len(win) and len(loss) and loss.mean() < 0 else None,
            "best": float(r.max()), "worst": float(r.min()),
            "over50": int((r > 0.5).sum()), "over100": int((r > 1.0).sum())}


def event_study(b, years, base_days, from_t):
    """Forward returns after every breakout day (first signal per stock per 60 sessions), vs the Nifty 500."""
    d = b.data
    sig, _ = b.signals(years, base_days)
    last = {}
    rows = {k: [] for k in HORIZONS}
    excess = {k: [] for k in HORIZONS}
    n = 0
    for t in range(from_t, len(d.calendar)):
        uni = d.universe_mask("pit500", d.calendar[t])
        for j in np.flatnonzero(sig[t] & uni & b.turn_ok[t]):
            if j in last and t - last[j] < 60:
                continue
            last[j] = t
            n += 1
            for k, h in HORIZONS.items():
                if t + h < len(d.calendar) and not np.isnan(d.close[t + h, j]):
                    r = d.close[t + h, j] / d.close[t, j] - 1
                    rows[k].append(r)
                    excess[k].append(r - (d.index[t + h] / d.index[t] - 1))
    out = {"events": n}
    for k in HORIZONS:
        r, x = np.array(rows[k]), np.array(excess[k])
        out[k] = {"n": len(r), "mean": float(r.mean()), "median": float(np.median(r)), "hit": float((r > 0).mean()),
                  "beatIndex": float((x > 0).mean()), "meanExcess": float(x.mean())} if len(r) else None
    return out


def rebased(dates_all, eq_all, dates):
    i = dates_all.index(dates[0])
    e = np.asarray(eq_all[i:i + len(dates)], dtype=float)
    return e / e[0] * CAPITAL


YEARS = (2, 3, 4)
STOPS = {"prev_week": "Previous week's low", "low_weeks:2": "Lowest close of the last 2 weeks",
         "lock:2:0.05:0.01:2": "2-week low, then +1% every 2 months once 5% above the buy price"}


def by_year(dates, eq):
    out = {}
    for y in sorted({x[:4] for x in dates}):
        end = max(i for i, x in enumerate(dates) if x[:4] == y)
        start = max([0] + [i for i, x in enumerate(dates) if x[:4] < y])
        out[y] = float(eq[end] / eq[start] - 1)
    return out


def main():
    data = ms.Data()
    feat = ms.Features(data)
    b = Breakouts(data, feat)
    cal = data.calendar
    studies = []
    for y in YEARS:
        # each lookback is its own backtest, from the first day its breakouts can be measured
        p0 = replace(BASE, years=y)
        runs, results = [], {}
        for stop, label in STOPS.items():
            p = replace(p0, stop=stop)
            r = backtest(b, p, record=True)
            liquid = backtest(b, replace(p, cash_asset=None))
            nodiv = backtest(b, replace(p, dividends=False))
            dates, eq = r["dates"], r["equity"]
            results[stop] = r
            runs.append({"stop": stop, "label": label, **ms.stats(dates, eq), "endValue": float(eq[-1]),
                         "liquid": {**ms.stats(dates, liquid["equity"]), "pnl": trade_stats(liquid["trades"])["pnl"]},
                         "noDiv": {**ms.stats(dates, nodiv["equity"]), "pnl": trade_stats(nodiv["trades"])["pnl"], "endValue": float(nodiv["equity"][-1])},
                         "trades": {**trade_stats(r["trades"]), "list": r["trades"]}, "open": r["open"],
                         "avgCash": float(np.mean([w["cash"] for w in r["weeks"]])), "yearly": by_year(dates, eq),
                         "drawdowns": ms.drawdowns(dates, eq), "weeks": r["weeks"]})
        r0 = results["prev_week"]
        dates, t0 = r0["dates"], r0["t0"]
        idx_eq = rebased(cal, data.index, dates)
        gold_eq = CAPITAL * np.cumprod(1 + data.cash_ret["GOLDBEES"][t0:])
        bench = {"nifty500": idx_eq, "gold": gold_eq}
        names = {"nifty500": "Nifty 500 index", "gold": "GOLDBEES (buy and hold)"}
        studies.append({
            "years": y, "from": dates[0], "to": dates[-1], "runs": runs,
            "bench": [{"key": k, "label": names[k], **ms.stats(dates, e), "endValue": float(e[-1]), "yearly": by_year(dates, e)} for k, e in bench.items()],
            "events": event_study(b, y, BASE.base_days, t0),
            "curve": [{"date": dates[i], **{s: round(float(results[s]["equity"][i])) for s in STOPS},
                       **{k: round(float(e[i])) for k, e in bench.items()}}
                      for i in range(len(dates)) if i == len(dates) - 1 or b.week_end[t0 + i]],
        })
    out = {"asOf": cal[-1], "base": BASE.__dict__, "capital": CAPITAL, "stops": STOPS, "studies": studies}
    (ROOT / "breakout_study.json").write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")

    pct = lambda v: f"{v * 100:6.1f}%"
    for st in studies:
        print(f"== {st['years']}-YEAR HIGH  {st['from']} .. {st['to']}   breakouts {st['events']['events']}")
        for r in st["runs"]:
            t = r["trades"]
            print(f"   {r['label']:34s} CAGR {pct(r['cagr'])} maxDD {pct(r['maxDD'])} Sharpe {r['sharpe']:.2f} end Rs{r['endValue']:>11,.0f}"
                  f"  stocks P&L Rs{t['pnl']:>10,.0f} trades {t['count']:3d} win {pct(t['winRate'])} avg {pct(t['avgRet'])} med {t['medianDays']:.0f}d"
                  f"  gold {pct(r['avgCash'])} | liquid CAGR {pct(r['liquid']['cagr'])}")
        for s in st["bench"]:
            print(f"   {s['label']:34s} CAGR {pct(s['cagr'])} maxDD {pct(s['maxDD'])} Sharpe {s['sharpe']:.2f}")
        e = st["events"]
        print("   after breakout", {h: (pct(v["mean"]), pct(v["median"]), pct(v["beatIndex"])) for h, v in e.items() if h != "events" and v})


if __name__ == "__main__":
    main()
