"""Momentum rotation across a fixed list of NSE ETFs.

Same score and filters as the stock study (average of % return / annualised volatility over
252/184/126/63 sessions; within 25% of the all-time high; above the 233-day SMA; Rs 1 crore average
daily turnover). Each month-end, hold the top N as equal "slots" (1/N of the portfolio each); a
holding is sold when it drops below `exit_rank` or fails a filter. Empty slots wait in LIQUIDCASE
(a liquid-fund ETF; 6.5% a year before it existed). No market safety switch: each ETF comes and goes
on its own momentum. An ETF is only eligible once it has enough trading history, so the list grows
over time exactly as it did for a real investor.

Inputs: study/etf_prices.json ({symbol: {date: [close, high, volume]}}, from Yahoo via momentum.py)
Output: etf_study.json
Run: py study/etf_study.py
"""
import json
import math
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TRADING_DAYS = 252
LIQUID_ANNUAL = 0.065
CASH_ETF = "LIQUIDCASE"
MAX_FFILL = 5
COVERAGE = 0.9


@dataclass(frozen=True)
class Params:
    lookbacks: tuple = (252, 184, 126, 63)
    max_fall: float = 0.25          # None = no all-time-high filter
    sma_days: int = 233             # None = no trend filter
    min_turnover: float = 1e7       # Rs per day, None = no liquidity filter
    top_n: int = 5
    exit_rank: int = 7
    cost: float = 0.0025            # per side
    market_ma: int = None           # None = no market switch; else exit to cash when NIFTYBEES < its MA at month-end


BASE = Params()


class Data:
    def __init__(self):
        raw = json.loads((HERE / "etf_prices.json").read_text(encoding="utf-8"))
        self.calendar = sorted({d for s in raw.values() for d in s})
        self.day = {d: i for i, d in enumerate(self.calendar)}
        self.symbols = [s for s in sorted(raw) if s != CASH_ETF]
        T, N = len(self.calendar), len(self.symbols)
        close, high, vol = (np.full((T, N), np.nan) for _ in range(3))
        self.dropped = {}
        for j, s in enumerate(self.symbols):
            last = None
            for d in sorted(raw[s]):
                c, h, v = raw[s][d]
                # Yahoo has a few bad prints (e.g. NIFTYBEES/GOLDBEES/PSUBNKBEES at 1/10 or 1/100 of the
                # price on 19-20 Dec 2019). A close under half or over double the last good one is skipped.
                if last is not None and not 0.5 < c / last < 2:
                    self.dropped.setdefault(s, []).append(d)
                    continue
                last = c
                close[self.day[d], j], high[self.day[d], j], vol[self.day[d], j] = c, min(h, c * 1.5), v
        self.turnover_daily = close * vol
        filled, gap = close.copy(), np.zeros(N)
        for i in range(1, T):
            miss = np.isnan(filled[i])
            gap = np.where(miss, gap + 1, 0)
            use = miss & (gap <= MAX_FFILL)
            filled[i, use] = filled[i - 1, use]
        self.close = filled
        with np.errstate(invalid="ignore", divide="ignore"):
            r = filled[1:] / filled[:-1] - 1
        self.ret = np.vstack([np.full((1, N), np.nan), r])
        self.ath = np.fmax.accumulate(np.fmax(high, close), axis=0)
        # cash: LIQUIDCASE's own daily return once it trades, 6.5% a year before that
        liquid = (1 + LIQUID_ANNUAL) ** (1 / TRADING_DAYS) - 1
        cash_close = np.full(T, np.nan)
        for d, (c, _, _) in raw.get(CASH_ETF, {}).items():
            cash_close[self.day[d]] = c
        self.cash_ret = np.full(T, liquid)
        for i in range(1, T):
            if not np.isnan(cash_close[i]) and not np.isnan(cash_close[i - 1]):
                self.cash_ret[i] = cash_close[i] / cash_close[i - 1] - 1
        self.col = {s: j for j, s in enumerate(self.symbols)}

    def month_ends(self):
        out = [i for i in range(len(self.calendar) - 1) if self.calendar[i + 1][:7] != self.calendar[i][:7]]
        return out  # the last (unfinished) month is excluded


def window_stats(x, n, t):
    """Mean and sample std of the last n values up to t, NaN-aware; (None, None) if coverage is too low."""
    w = x[max(0, t - n + 1):t + 1]
    ok = ~np.isnan(w)
    if t - n + 1 < 0 or ok.sum() < max(2, n * COVERAGE):
        return None
    return w[ok]


def score(d, t, j, p):
    parts = []
    for n in p.lookbacks:
        if t - n < 0 or np.isnan(d.close[t, j]) or np.isnan(d.close[t - n, j]):
            return None
        r = window_stats(d.ret[:, j], n, t)
        if r is None:
            return None
        vol = r.std(ddof=1) * math.sqrt(TRADING_DAYS)
        if not vol > 0:
            return None
        parts.append((d.close[t, j] / d.close[t - n, j] - 1) / vol)
    return float(np.mean(parts))


def passes(d, t, j, p):
    c = d.close[t, j]
    if np.isnan(c):
        return False
    if p.max_fall is not None and (d.ath[t, j] - c) / d.ath[t, j] >= p.max_fall:
        return False
    if p.sma_days:
        w = window_stats(d.close[:, j], p.sma_days, t)
        if w is None or c <= w.mean():
            return False
    if p.min_turnover:
        w = window_stats(d.turnover_daily[:, j], TRADING_DAYS, t)
        if w is None or w.mean() <= p.min_turnover:
            return False
    return True


def why_not(d, t, j, p):
    """Why ETF j isn't eligible at day t (None if it is)."""
    c = d.close[t, j]
    if np.isnan(c):
        return "Not trading yet"
    if score(d, t, j, p) is None:
        return "Less than a year of prices"
    if p.max_fall is not None and (d.ath[t, j] - c) / d.ath[t, j] >= p.max_fall:
        return f"{(d.ath[t, j] - c) / d.ath[t, j]:.0%} below its all-time high"
    if p.sma_days:
        w = window_stats(d.close[:, j], p.sma_days, t)
        if w is None or c <= w.mean():
            return f"Below its {p.sma_days}-day average"
    if p.min_turnover:
        w = window_stats(d.turnover_daily[:, j], TRADING_DAYS, t)
        if w is None or w.mean() <= p.min_turnover:
            return f"Trades under ₹{p.min_turnover / 1e7:g} crore a day"
    return None


def ranking(d, t, p):
    scored = []
    for j in range(len(d.symbols)):
        s = score(d, t, j, p)
        if s is not None and passes(d, t, j, p):
            scored.append((s, j))
    scored.sort(reverse=True)
    return [j for _, j in scored], {j: s for s, j in scored}


def market_sma(d, n):
    c = d.close[:, d.col["NIFTYBEES"]]
    out = np.full(len(c), np.nan)
    for i in range(n - 1, len(c)):
        w = c[i - n + 1:i + 1]
        if not np.isnan(w).any():
            out[i] = w.mean()
    return out


def backtest(d, p, start=None, record=False):
    ends = d.month_ends()
    need = max(max(p.lookbacks), p.sma_days or 0, TRADING_DAYS) + 5
    rebal = [t for t in ends if t >= need and (start is None or d.calendar[t] >= start)]
    if start is None:  # begin at the first month-end where some ETF is eligible
        first = next(i for i, t in enumerate(rebal) if ranking(d, t, p)[0])
        rebal = rebal[first:]
    t0 = rebal[0]
    rset = set(rebal)
    sma = market_sma(d, p.market_ma) if p.market_ma else None
    cash, hold, entry = 1.0, {}, {}
    equity, trades, log = [], [], []
    for t in range(t0, len(d.calendar)):
        if t > t0:
            for j in hold:
                r = d.ret[t, j]
                hold[j] *= 1 + (0.0 if np.isnan(r) else r)
            cash *= 1 + d.cash_ret[t]
        if t in rset:
            total = cash + sum(hold.values())
            order, scores = ranking(d, t, p)
            rank = {j: i + 1 for i, j in enumerate(order)}
            out = sma is not None and not np.isnan(sma[t]) and d.close[t, d.col["NIFTYBEES"]] < sma[t]
            keep = set() if out else {j for j in order[:p.exit_rank]}
            sold, bought = [], []
            for j in [j for j in hold if j not in keep]:
                v = hold.pop(j)
                cash += v * (1 - p.cost)
                e = entry.pop(j)
                trades.append({"s": d.symbols[j], "in": e["day"], "out": d.calendar[t], "ret": v * (1 - p.cost) / e["basis"] - 1,
                               "days": (date.fromisoformat(d.calendar[t]) - date.fromisoformat(e["day"])).days})
                reason = ("Market switch: NIFTYBEES below its average" if out
                          else why_not(d, t, j, p) or f"Rank fell to {rank[j]} (sell below {p.exit_rank})")
                sold.append({"s": d.symbols[j], "ret": trades[-1]["ret"], "rank": rank.get(j), "in": e["day"],
                             "days": trades[-1]["days"], "why": reason})
            if not out:
                slot = total / p.top_n
                for j in [j for j in order if j not in hold][:p.top_n - len(hold)]:
                    spend = min(slot, cash)
                    if spend <= 1e-12:
                        break
                    cash -= spend
                    hold[j] = spend * (1 - p.cost)
                    entry[j] = {"day": d.calendar[t], "basis": spend}
                    bought.append({"s": d.symbols[j], "rank": rank[j], "score": scores[j], "px": float(d.close[t, j])})
            if record:
                total = cash + sum(hold.values())
                log.append({"t": t, "date": d.calendar[t], "eligible": len(order), "available": int(np.sum(~np.isnan(d.close[t]))),
                            "value": total, "ranked": [{"s": d.symbols[j], "score": scores[j], "held": j in hold} for j in order],
                            "left": [{"s": d.symbols[j], "why": why_not(d, t, j, p)} for j in range(len(d.symbols))
                                     if j not in rank and not np.isnan(d.close[t, j])],
                            "sold": sold, "bought": bought, "cash": cash / total,
                            "held": [{"s": d.symbols[j], "col": j, "w": v / total, "rank": rank.get(j), "new": any(b["s"] == d.symbols[j] for b in bought)}
                                     for j, v in sorted(hold.items(), key=lambda kv: rank.get(kv[0], 99))]})
        equity.append(cash + sum(hold.values()))
    if record:  # returns from each rebalance to the next
        for k, m in enumerate(log):
            a, b = m["t"], (log[k + 1]["t"] if k + 1 < len(log) else len(d.calendar) - 1)
            m["until"] = d.calendar[b]
            m["periodRet"] = float(equity[b - t0] / equity[a - t0] - 1)
            nb = d.close[:, d.col["NIFTYBEES"]]
            m["niftyRet"] = float(nb[b] / nb[a] - 1)
            for h in m["held"]:
                h["pr"] = float(np.prod(1 + np.nan_to_num(d.ret[a + 1:b + 1, h.pop("col")])) - 1)
            del m["t"]
    for j, v in hold.items():  # mark open positions, for trade stats
        trades.append({"s": d.symbols[j], "in": entry[j]["day"], "out": None, "ret": v / entry[j]["basis"] - 1,
                       "days": (date.fromisoformat(d.calendar[-1]) - date.fromisoformat(entry[j]["day"])).days})
    return {"dates": d.calendar[t0:], "equity": np.array(equity), "trades": trades, "log": log, "t0": t0}


def stats(dates, eq):
    years = (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days / 365.25
    daily = eq[1:] / eq[:-1] - 1
    vol = daily.std(ddof=1) * math.sqrt(TRADING_DAYS)
    dd = eq / np.maximum.accumulate(eq) - 1
    cagr = (eq[-1] / eq[0]) ** (1 / years) - 1
    return {"cagr": float(cagr), "vol": float(vol), "maxDD": float(dd.min()),
            "sharpe": float((daily.mean() * TRADING_DAYS - LIQUID_ANNUAL) / vol) if vol else None,
            "calmar": float(cagr / abs(dd.min())) if dd.min() < 0 else None, "multiple": float(eq[-1] / eq[0]),
            "from": dates[0], "to": dates[-1]}


def buy_hold(d, symbol, t0):
    c = d.close[t0:, d.col[symbol]]
    return c / c[0]


def yearly(dates, eq):
    out, st = {}, 0
    for i, day in enumerate(dates):
        if i == len(dates) - 1 or dates[i + 1][:4] != day[:4]:
            out[day[:4]] = float(eq[i] / eq[st] - 1)
            st = i
    return out


def monthly(dates, eq):
    out, last = [], None
    for i, day in enumerate(dates):
        if i == len(dates) - 1 or dates[i + 1][:7] != day[:7]:
            if last is not None:
                out.append([day[:7], float(eq[i] / eq[last] - 1)])
            last = i
    return out


def drawdowns(dates, eq, top=5):
    rows, peak_i, trough_i, in_dd = [], 0, 0, False
    for i in range(1, len(eq)):
        if eq[i] >= eq[peak_i]:
            if in_dd:
                rows.append((peak_i, trough_i, i))
                in_dd = False
            peak_i = i
        else:
            if not in_dd:
                in_dd, trough_i = True, i
            if eq[i] < eq[trough_i]:
                trough_i = i
    if in_dd:
        rows.append((peak_i, trough_i, None))
    out = [{"peak": dates[a], "trough": dates[b], "recovered": dates[c] if c else None, "depth": float(eq[b] / eq[a] - 1)} for a, b, c in rows]
    return sorted(out, key=lambda r: r["depth"])[:top]


def main():
    d = Data()
    run = backtest(d, BASE, record=True)
    dates, eq, t0 = run["dates"], run["equity"], run["t0"]
    nifty, gold = buy_hold(d, "NIFTYBEES", t0), buy_hold(d, "GOLDBEES", t0)
    closed = [t for t in run["trades"] if t["out"]]
    rets = np.array([t["ret"] for t in closed])
    held_time = {}
    for m in run["log"]:
        for h in m["held"]:
            held_time[h["s"]] = held_time.get(h["s"], 0) + 1
    listed = {s: next(d.calendar[i] for i in range(len(d.calendar)) if not np.isnan(d.close[i, d.col[s]])) for s in d.symbols}

    def row(label, p, start=dates[0]):
        r = backtest(d, p, start=start)
        return {"label": label, **stats(r["dates"], r["equity"]), "trades": sum(1 for t in r["trades"] if t["out"])}

    sens = {
        "ETFs held": [row(f"Top {n}" + (" (base)" if n == BASE.top_n else ""), replace(BASE, top_n=n, exit_rank=max(n, n + 2))) for n in (2, 3, 5, 7)],
        "Sell when out of": [row(f"Top {k}" + (" (base)" if k == BASE.exit_rank else ""), replace(BASE, exit_rank=k)) for k in (5, 7, 10)],
        "Filters": [row("All filters (base)", BASE), row("No turnover filter", replace(BASE, min_turnover=None)),
                    row("No all-time-high filter", replace(BASE, max_fall=None)), row("No 233-day trend filter", replace(BASE, sma_days=None)),
                    row("No filters at all", replace(BASE, max_fall=None, sma_days=None, min_turnover=None))],
        "Costs per side": [row(f"{c * 100:.2g}%" + (" (base)" if c == BASE.cost else ""), replace(BASE, cost=c)) for c in (0.001, 0.0025, 0.005)],
        "Market switch": [row("None (base)", BASE), row("NIFTYBEES below its 200-day average at month-end: all to cash", replace(BASE, market_ma=200))],
    }
    # the same rules from the date the full 16-ETF list was available
    late_start = max(listed.values())
    late = run
    li = next(i for i, x in enumerate(late["dates"]) if x >= late_start)
    late_eq = late["equity"][li:]
    ti = d.day[late["dates"][li]]
    out = {
        "asOf": d.calendar[-1], "base": BASE.__dict__, "listed": listed,
        "stats": [{"label": "ETF momentum", **stats(dates, eq)}, {"label": "NIFTYBEES (buy and hold)", **stats(dates, nifty)},
                  {"label": "GOLDBEES (buy and hold)", **stats(dates, gold)}],
        "sinceAllListed": {"from": late["dates"][li], "strategy": stats(late["dates"][li:], late_eq),
                           "nifty": stats(late["dates"][li:], buy_hold(d, "NIFTYBEES", ti)), "gold": stats(late["dates"][li:], buy_hold(d, "GOLDBEES", ti))},
        "yearly": {"strategy": yearly(dates, eq), "nifty": yearly(dates, nifty), "gold": yearly(dates, gold)},
        "monthly": {"strategy": monthly(dates, eq), "nifty": monthly(dates, nifty)},
        "drawdowns": drawdowns(dates, eq), "niftyDrawdowns": drawdowns(dates, nifty, 3),
        "trades": {"count": len(closed), "winRate": float(np.mean(rets > 0)), "avgWin": float(rets[rets > 0].mean()),
                   "avgLoss": float(rets[rets <= 0].mean()), "medianDays": float(np.median([t["days"] for t in closed])),
                   "list": run["trades"]},
        "monthsHeld": dict(sorted(held_time.items(), key=lambda kv: -kv[1])), "months": len(run["log"]),
        "avgCash": float(np.mean([m["cash"] for m in run["log"]])),
        "sensitivity": sens, "log": run["log"],
        "curve": [{"date": dates[i], "strategy": round(float(eq[i]), 4), "nifty": round(float(nifty[i]), 4), "gold": round(float(gold[i]), 4)}
                  for i in range(len(dates)) if i == len(dates) - 1 or date.fromisoformat(dates[i]).weekday() == 4],
    }
    (ROOT / "etf_study.json").write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    # The public teaser page gets only the curve and headline numbers, no rules or ETF list.
    head = lambda s: {"cagr": s["cagr"], "maxDD": s["maxDD"], "multiple": s["multiple"]}
    teaser = {"asOf": out["asOf"], "from": dates[0], "to": dates[-1], "strategy": head(out["stats"][0]),
              "nifty": head(out["stats"][1]), "gold": head(out["stats"][2]),
              "curve": [{k: p[k] for k in ("date", "strategy", "nifty", "gold")} for p in out["curve"]]}
    (ROOT / "etf_teaser.json").write_text(json.dumps(teaser, separators=(",", ":")), encoding="utf-8")
    pct = lambda v: f"{v * 100:6.1f}%"
    for s in out["stats"]:
        print(f"{s['label']:26s} {s['from']}..{s['to']} CAGR {pct(s['cagr'])} maxDD {pct(s['maxDD'])} vol {pct(s['vol'])} Sharpe {s['sharpe']:.2f} x{s['multiple']:.2f}")
    sl = out["sinceAllListed"]
    print(f"since all 16 listed ({sl['from']}): strategy {pct(sl['strategy']['cagr'])}/{pct(sl['strategy']['maxDD'])}, nifty {pct(sl['nifty']['cagr'])}, gold {pct(sl['gold']['cagr'])}")
    print("YEARLY", {y: (pct(v), pct(out['yearly']['nifty'][y]), pct(out['yearly']['gold'][y])) for y, v in out["yearly"]["strategy"].items()})
    print("DD", [(x["peak"], x["trough"], x["recovered"], pct(x["depth"])) for x in out["drawdowns"][:3]])
    tr = out["trades"]
    print(f"TRADES {tr['count']} win {pct(tr['winRate'])} avgWin {pct(tr['avgWin'])} avgLoss {pct(tr['avgLoss'])} medianDays {tr['medianDays']}")
    print("MONTHS HELD", out["monthsHeld"], "of", out["months"], "avg cash", pct(out["avgCash"]))
    for g, rows in sens.items():
        print(g)
        for r in rows:
            print(f"   {r['label']:60s} CAGR {pct(r['cagr'])} maxDD {pct(r['maxDD'])} Sharpe {r['sharpe']:.2f} trades {r['trades']}")
    print("LISTED", listed)
    print("LAST", out["log"][-1]["date"], [(h["s"], round(h["w"], 2)) for h in out["log"][-1]["held"]], "cash", round(out["log"][-1]["cash"], 2))


if __name__ == "__main__":
    main()
