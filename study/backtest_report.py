"""Detailed backtest report for the momentum strategy on point-in-time Nifty 500 lists.

Replays the base-case rules with universe="pit500" and writes a self-contained HTML report with the
equity curve, drawdowns, yearly/monthly returns, a month-by-month change log (what was sold and why,
what was bought and at which rank, which index list was in force) and every trade.

Inputs: same as momentum_study.py, plus study/constituents_raw/*.csv for company names/industries.
Output: study/backtest_report.html (template: study/backtest_report_template.html)
Run: py study/backtest_report.py
"""
import csv
import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np

import momentum_study as ms

HERE = Path(__file__).resolve().parent
P = replace(ms.BASE, universe="pit500")
RANK_SHOWN = 15  # ranked candidates listed per rebalance


def names_and_industries(data):
    name, industry = {}, {}
    for row in csv.DictReader((ms.ROOT / "nifty750_backtest_list.csv").open(encoding="utf-8")):
        industry[row["Symbol"]] = row["Industry"]
    for path in sorted((HERE / "constituents_raw").glob("ind_nifty500list_*.csv")):  # newest wins
        for row in csv.DictReader(path.open(encoding="utf-8")):
            c = data.canonical((row.get("Symbol") or "").strip())
            if c:
                name[c] = (row.get("Company Name") or "").strip() or name.get(c, c)
                industry[c] = (row.get("Industry") or "").strip() or industry.get(c, "Other")
    return name, industry


def period_return(d, j, a, b):
    """Holding return of column j from close of day a to close of day b (engine's NaN handling)."""
    r = d.ret[a + 1:b + 1, j]
    return float(np.prod(1 + np.nan_to_num(r))) - 1


def sell_reason(feat, t, j, universe, rank):
    d = feat.data
    if not universe[j]:
        return "Dropped from the Nifty 500 list"
    price = d.close[t, j]
    if np.isnan(price):
        return "No price data"
    ath = d.ath[t, j]
    if (ath - price) / ath >= P.max_fall:
        return f"Fell {(ath - price) / ath:.0%} from its all-time high (limit {P.max_fall:.0%})"
    sma = feat.sma(t, P.sma_days)[j]
    if not np.isnan(sma) and price <= sma:
        return f"Closed below its {P.sma_days}-day average"
    tv = feat.turnover(t)[j]
    if not np.isnan(tv) and tv <= P.min_turnover:
        return "Daily turnover below Rs 1 crore"
    if np.isnan(feat.score(t, P)[j]):
        return "Not enough price history for a score"
    return f"Rank fell to {rank} (sell when below {P.exit_rank})" if rank else f"Ranked below {P.exit_rank}"


def main():
    data = ms.Data()
    feat = ms.Features(data)
    d, cal = data, data.calendar
    name, industry = names_and_industries(data)
    run = ms.backtest(feat, P, record=True)
    eq, dates = run["equity"], run["dates"]
    t0 = run["rebalances"][0]
    bench = d.index[t0:] / d.index[t0]
    msma = ms.market_sma(d.index, P.market_ma)
    exposure = {t: (hold, cash) for t, hold, cash in run["exposure"]}
    sym = lambda j: d.symbols[j]

    trades_by_exit = {}
    for tr in run["trades"]:
        trades_by_exit[(tr["col"], tr["exit"])] = tr

    # closes in a row below the market MA, up to each day
    streak = np.zeros(len(cal), dtype=int)
    for i in range(len(cal)):
        if not np.isnan(msma[i]) and d.index[i] < msma[i]:
            streak[i] = (streak[i - 1] if i else 0) + 1
    rebal_set = {t for t in run["rebalances"] if t >= t0}
    exit_days = {d.day_index[e["date"]] for e in run["events"] if e["type"] == "EXIT"}
    actions = sorted(rebal_set | exit_days)  # month-end rebalances plus any mid-month market exits
    log = []
    prev_hold = {}
    for k, t in enumerate(actions):
        day = cal[t]
        nxt = actions[k + 1] if k + 1 < len(actions) else len(cal) - 1
        hold, cash = exposure[t]
        total = cash + sum(hold.values())
        universe = d.universe_mask(P.universe, day)
        list_date = max(sd for sd, _, _ in d.pit if sd <= day) if any(sd <= day for sd, _, _ in d.pit) else d.pit[0][0]
        below = not np.isnan(msma[t]) and d.index[t] < msma[t]
        exited = t in exit_days
        order = feat.ranking(t, P, universe)
        rank_of = {int(j): i + 1 for i, j in enumerate(order.tolist())}
        score = feat.score(t, P)

        sold = []
        for j in prev_hold:
            if j in hold:
                continue
            tr = trades_by_exit.get((j, day))
            reason = (f"Market filter: Nifty 500 closed below its {P.market_ma}-day average {streak[t]} day(s) in a row" if exited
                      else sell_reason(feat, t, j, universe, rank_of.get(j)))
            sold.append({"s": sym(j), "n": name.get(sym(j), sym(j)), "in": tr["entry"] if tr else None,
                         "ret": tr["ret"] if tr else None, "days": tr["days"] if tr else None, "why": reason})
        bought = [{"s": sym(j), "n": name.get(sym(j), sym(j)), "ind": industry.get(sym(j), "Other"),
                   "rank": rank_of.get(j), "score": float(score[j]), "px": float(d.close[t, j])}
                  for j in hold if j not in prev_hold]
        bought.sort(key=lambda b: b["rank"] or 999)
        held = []
        for j, v in sorted(hold.items(), key=lambda kv: rank_of.get(kv[0], 999)):
            held.append({"s": sym(j), "n": name.get(sym(j), sym(j)), "ind": industry.get(sym(j), "Other"),
                         "w": v / total, "rank": rank_of.get(j), "new": j not in prev_hold,
                         "pr": period_return(d, j, t, nxt)})
        ranked = [{"s": sym(j), "rank": i + 1, "score": float(score[j]), "held": int(j) in hold}
                  for i, j in enumerate(order[:RANK_SHOWN].tolist())]
        if exited:
            status = "EXIT"
        elif not hold:
            status = "CASH"
        else:
            status = "ENTER" if not prev_hold else ("SWAP" if sold or bought else "HOLD")
        log.append({
            "date": day, "until": cal[nxt], "status": status, "list": list_date, "mid": t not in rebal_set,
            "listSize": int(universe.sum()), "eligible": int(len(order)), "streak": int(streak[t]),
            "nifty": float(d.index[t]), "sma": float(msma[t]), "below": bool(below), "out": not hold,
            "value": float(total), "cash": float(cash / total) if total else 1.0,
            "periodRet": float(eq[nxt - t0] / eq[t - t0] - 1),
            "benchRet": float(d.index[nxt] / d.index[t] - 1),
            "sold": sold, "bought": bought, "held": held, "ranked": ranked,
        })
        prev_hold = dict(hold)

    trades = sorted(({"s": sym(tr["col"]), "n": name.get(sym(tr["col"]), sym(tr["col"])),
                      "ind": industry.get(sym(tr["col"]), "Other"), "in": tr["entry"], "out": tr["exit"],
                      "days": tr["days"], "ret": tr["ret"]} for tr in run["trades"]), key=lambda x: x["in"])
    # positions still open at the end (return so far, before the selling cost)
    last_buy = {b["col"]: b for b in run["buys"]}
    hold_end, cash_end = exposure[len(cal) - 1]
    tot_end = cash_end + sum(hold_end.values())
    open_pos = [{"s": sym(j), "n": name.get(sym(j), sym(j)), "ind": industry.get(sym(j), "Other"),
                 "in": cal[last_buy[j]["t"]], "w": v / tot_end, "ret": v / last_buy[j]["value"] - 1,
                 "days": (date.fromisoformat(cal[-1]) - date.fromisoformat(cal[last_buy[j]["t"]])).days}
                for j, v in sorted(hold_end.items(), key=lambda kv: -kv[1])]

    base = ms.summary(run)
    series = {"Strategy": eq, "Nifty 500": bench}
    stats = [{"label": k, **ms.stats(dates, v)} for k, v in series.items()]
    stats[0].update({k: base[k] for k in ("trades", "winRate", "turnoverPerYear", "avgHoldDays")})

    def yearly(v):
        out, start = {}, 0
        for i, day in enumerate(dates):
            if i == len(dates) - 1 or dates[i + 1][:4] != day[:4]:
                out[day[:4]] = float(v[i] / v[start] - 1)
                start = i
        return out

    # Same rules, but money waits in GOLDBEES instead of the liquid fund when the market filter is out
    gold_run = ms.backtest(feat, replace(P, cash_asset="GOLDBEES"))
    geq = gold_run["equity"]
    gold = np.cumprod(1 + d.cash_ret["GOLDBEES"][t0:])
    gold = gold / gold[0]
    gs = ms.summary(gold_run)
    spells, exit_day = [], None
    for ev in run["events"]:
        if ev["type"] == "EXIT":
            exit_day = ev["date"]
        elif ev["type"] == "ENTER" and exit_day:
            a, b = d.day_index[exit_day], d.day_index[ev["date"]]
            spells.append({"from": exit_day, "to": ev["date"], "gold": float(np.prod(1 + d.cash_ret["GOLDBEES"][a + 1:b + 1]) - 1),
                           "liquid": (1 + ms.LIQUID_ANNUAL) ** ((b - a) / ms.TRADING_DAYS) - 1})
            exit_day = None
    if exit_day:
        a, b = d.day_index[exit_day], len(cal) - 1
        spells.append({"from": exit_day, "to": None, "gold": float(np.prod(1 + d.cash_ret["GOLDBEES"][a + 1:b + 1]) - 1),
                       "liquid": (1 + ms.LIQUID_ANNUAL) ** ((b - a) / ms.TRADING_DAYS) - 1})

    peak = np.maximum.accumulate(eq)
    bpeak = np.maximum.accumulate(bench)
    curve = [{"d": dates[i], "s": round(float(eq[i]), 5), "b": round(float(bench[i]), 5),
              "g": round(float(geq[i]), 5),
              "dd": round(float(eq[i] / peak[i] - 1), 5), "bdd": round(float(bench[i] / bpeak[i] - 1), 5)}
             for i in range(len(dates))]
    rets = np.array([t["ret"] for t in trades])
    per_stock = {}
    for tr in trades:
        ps = per_stock.setdefault(tr["s"], {"s": tr["s"], "n": tr["n"], "ind": tr["ind"], "trades": 0, "days": 0, "wins": 0, "rets": []})
        ps["trades"] += 1
        ps["days"] += tr["days"]
        ps["wins"] += tr["ret"] > 0
        ps["rets"].append(tr["ret"])
    stocks = []
    for ps in per_stock.values():
        ps["comp"] = float(np.prod([1 + r for r in ps.pop("rets")]) - 1)
        stocks.append(ps)
    stocks.sort(key=lambda x: -x["comp"])

    out = {
        "asOf": cal[-1], "from": dates[0], "to": dates[-1],
        "rules": {"lookbacks": list(P.lookbacks), "maxFall": P.max_fall, "sma": P.sma_days, "turnover": P.min_turnover,
                  "topN": P.top_n, "exitRank": P.exit_rank, "marketMa": P.market_ma, "marketCheck": P.market_check, "confirmDays": P.confirm_days, "cost": P.cost,
                  "liquid": ms.LIQUID_ANNUAL},
        "stats": stats,
        "yearly": {k: yearly(v) for k, v in series.items()},
        "monthly": {"strategy": ms.monthly_returns(dates, eq), "bench": ms.monthly_returns(dates, bench)},
        "drawdowns": ms.drawdowns(dates, eq, top=8),
        "benchDrawdowns": ms.drawdowns(dates, bench, top=3),
        "curve": curve,
        "log": log,
        "trades": trades,
        "open": open_pos,
        "tradeStats": {"count": len(rets), "winRate": float(np.mean(rets > 0)),
                       "avgWin": float(rets[rets > 0].mean()), "avgLoss": float(rets[rets <= 0].mean()),
                       "best": float(rets.max()), "worst": float(rets.min()),
                       "medianDays": float(np.median([t["days"] for t in trades]))},
        "stocks": stocks,
        "goldCompare": {
            "rows": [{"label": f"Liquid fund ({ms.LIQUID_ANNUAL:.1%} a year)", **base},
                     {"label": "GOLDBEES", **gs},
                     {"label": "Gold only (GOLDBEES bought and held)", **ms.stats(dates, gold)}],
            "yearly": {"liquid": yearly(eq), "goldbees": yearly(geq), "gold": yearly(gold)},
            "spells": spells,
        },
        "lists": [{"date": sd, "members": len(syms), "withPrices": int(m.sum())} for sd, m, syms in d.pit],
    }
    template = (HERE / "backtest_report_template.html").read_text(encoding="utf-8")
    payload = json.dumps(out, separators=(",", ":"), default=float).replace("</", "<\\/")
    (HERE / "backtest_report.html").write_text(template.replace("/*__DATA__*/null", payload), encoding="utf-8")
    s = stats[0]
    print(f"{dates[0]} -> {dates[-1]}: CAGR {s['cagr']:.1%}, maxDD {s['maxDD']:.1%}, Sharpe {s['sharpe']:.2f}, "
          f"{len(log)} log entries, {len(trades)} trades -> study/backtest_report.html")


if __name__ == "__main__":
    main()
