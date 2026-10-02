"""NIFTY monthly iron fly, one trade a month, entered only when India VIX is 12-17.

Rules, all decided at daily closes on NSE's monthly NIFTY options:
    entry   - close of the first trading day after a monthly expiry (about 30 days to the next one), only if
              India VIX closes within VIX_BAND that day; otherwise skip the month
    legs    - per set: sell 1 lot of the ATM call and put (strike nearest the current-month future, rounded to
              100), buy 1 lot of the call and put WING away (rounded to 100); LOTS sets
    target  - close everything at the first close where the open profit, after costs paid and the cost of
              closing, is at least TARGET_FRAC of the net credit received at entry (12%: about 45 points,
              or Rs 2,900 per sold lot, on a 370-point credit; it grows with NIFTY's level)
    roll    - if the future closes ROLL_PCT or more from the short strike, buy back the short call and put and
              sell them at the new ATM strike (the bought wings stay); at most MAX_ROLLS times
    stop    - on the roll trigger after MAX_ROLLS rolls, close everything
    time    - otherwise close EXIT_BEFORE trading days before expiry
    VIX     - ignored once in a trade; the "VIX +20%" variant also closes once VIX is 20% above its entry level

Prices: close when the option traded that day, else NSE's settle price. Rupees are per sold lot (the LOTS-set
position divided by LOTS; brokerage is per order whatever the lots, so a single set pays a little more).
Costs, all charged: SLIP_SHORT / SLIP_WING points per lot per order, STT of 0.1% on sold premium, BROKERAGE per
order, NSE transaction charges and the SEBI fee on premium traded, stamp duty on premium bought, and GST on brokerage
and fees. Return on margin uses MARGIN_PER_SET (a Zerodha quote) scaled by NIFTY's level at each entry.

Inputs: study/fno_bhavcopy/fo_<year>.parquet (from study/fetch_fno_bhavcopy.py) and study/india_vix_daily.csv
(downloaded from Yahoo Finance, ^INDIAVIX, if missing; needs yfinance)
Output: printed summary, study/nifty_iron_fly_trades.csv and iron_fly_study.json at the site root (read by
        study/iron_fly_report.py)
Run: py study/nifty_iron_fly_study.py
"""
import csv
import json
from datetime import date
from collections import defaultdict
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
SYMBOL = "NIFTY"
LOT, LOTS = 65, 4
ENTRY_DAY, EXIT_BEFORE = 1, 1
VIX_BAND = (12, 17)
WING, ROLL_PCT, MAX_ROLLS = 0.02, 0.02, 1
TARGET_FRAC = 0.12
VIX_BRAKE = 1.2
MARGIN_PER_SET = 70000      # Zerodha's margin for 5 sets (5 lots of 65 on each leg) was Rs 3,50,000 in Oct 2026
MARGIN_NOTE = "Zerodha margin for 5 sets (5 lots of 65 on each leg) in October 2026: ₹3,50,000, so ₹70,000 per set"
SLIP_SHORT, SLIP_WING, STT, BROKERAGE = 1.0, 0.5, 0.001, 20.0
EXCH, SEBI, STAMP, GST = 0.0003503, 0.000001, 0.00003, 0.18   # NSE option charges on premium; GST on fees
COST_KINDS = ("slip", "stt", "brk", "exch", "stamp", "gst")


def charges(sell, buy, orders, slip):
    """One batch of orders, in points x lots: sell / buy = premium sold / bought (points x lots)."""
    brk, exch = orders * BROKERAGE / LOT, (EXCH + SEBI) * (sell + buy)
    return dict(slip=slip, stt=STT * sell, brk=brk, exch=exch, stamp=STAMP * buy, gst=GST * (brk + exch))


def load():
    opts, futs = [], []
    for p in sorted((HERE / "fno_bhavcopy").glob("fo_*.parquet")):
        cols = ["date", "expiry", "strike", "option_type", "close", "settle", "contracts"]
        o = pd.read_parquet(p, columns=cols + ["instrument"],
                            filters=[("instrument", "==", "OPTIDX"), ("symbol", "==", SYMBOL)])
        opts.append(o[o["strike"] % 100 == 0][cols])
        futs.append(pd.read_parquet(p, columns=["date", "expiry", "close"],
                                    filters=[("instrument", "==", "FUTIDX"), ("symbol", "==", SYMBOL)]))
    o, f = pd.concat(opts), pd.concat(futs)
    for df in (o, f):
        df["date"] = df["date"].dt.strftime("%Y-%m-%d")
        df["expiry"] = df["expiry"].dt.strftime("%Y-%m-%d")
        df["month"] = df["expiry"].str[:7]
    # each month's real expiry is its contracts' last trading day (a listed date can move for a holiday), and
    # contracts are keyed by month, since NSE re-dated listed contracts when it moved NIFTY expiry day in 2025
    data_end = f["date"].max()
    g = o.groupby("month").agg(listed=("expiry", "max"), last=("date", "max"))
    monthly = sorted(g["last"].where(g["last"] < data_end, g["listed"]))
    o = o[o["expiry"] == o.groupby(["date", "month"])["expiry"].transform("max")]   # drop weeklies
    price = o["close"].where(o["contracts"] > 0, o["settle"])
    opt = {(d, m, k, t): p for d, m, k, t, p in
           zip(o["date"], o["month"], o["strike"], o["option_type"].astype(str), price)}
    f = f[f["expiry"] == f.groupby(["date", "month"])["expiry"].transform("max")]
    fut = {(d, m): c for d, m, c in zip(f["date"], f["month"], f["close"])}
    return opt, fut, sorted(f["date"].unique()), monthly


def load_vix():
    path = HERE / "india_vix_daily.csv"
    if not path.exists():
        import yfinance as yf
        d = yf.download("^INDIAVIX", start="2016-01-01", progress=False, auto_adjust=False)
        d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]
        d[["Open", "High", "Low", "Close"]].to_csv(path, index_label="Date")
    v = pd.read_csv(path, index_col="Date")["Close"]
    v.index = v.index.str[:10]
    return v.to_dict()


def months(fut, days, monthly):
    """Each monthly contract's trading path, from the entry close to the exit close, and its entry future."""
    for prev, cur in zip(monthly, monthly[1:]):
        if prev < days[0] or cur > days[-1]:
            continue
        after = [d for d in days if prev < d <= cur]
        if not after or after[-1] != cur or len(after) < ENTRY_DAY + EXIT_BEFORE + 1:
            continue
        path = after[ENTRY_DAY - 1: len(after) - EXIT_BEFORE]
        ref = fut.get((path[0], cur[:7]))
        if ref is not None:
            yield cur[:7], path, ref


def r100(x):
    return round(x / 100) * 100


def trade(opt, fut, m, path, ref, exit_if=None, target_frac=TARGET_FRAC):
    """target_frac: take profit once the open profit after costs is that share of the entry credit."""
    px = lambda d, k, t: opt.get((d, m, k, t))
    k, kc, kp = r100(ref), r100(ref * (1 + WING)), r100(ref * (1 - WING))
    d0 = path[0]
    entry = [px(d0, k, "CE"), px(d0, k, "PE"), px(d0, kc, "CE"), px(d0, kp, "PE")]
    if None in entry or not all(p > 0 for p in entry):
        return None
    cash = LOTS * (entry[0] + entry[1] - entry[2] - entry[3])          # points x lots received
    # costs in points x lots, kept by kind for the cost breakdown
    parts = charges(LOTS * (entry[0] + entry[1]), LOTS * (entry[2] + entry[3]), 4, LOTS * 2 * (SLIP_SHORT + SLIP_WING))
    cost = sum(parts.values())
    credit, rolls, strikes = entry[0] + entry[1] - entry[2] - entry[3], 0, [k]
    steps = [dict(d=d0, k=k, cash=round(credit, 2))]       # each position held: short strike, net points per set
    for i, d in enumerate(path[1:], 1):
        last = i == len(path) - 1
        f = fut.get((d, m))
        sc, sp, wc, wp = px(d, k, "CE"), px(d, k, "PE"), px(d, kc, "CE"), px(d, kp, "PE")
        if None in (sc, sp, wc, wp):
            if last:
                return None
            continue
        closing = charges(LOTS * (wc + wp), LOTS * (sc + sp), 4, LOTS * 2 * (SLIP_SHORT + SLIP_WING))
        close_cost = sum(closing.values())
        pnl = cash - LOTS * (sc + sp) + LOTS * (wc + wp) - cost - close_cost
        reason = "exit day" if last else None
        goal = target_frac * credit * LOTS
        if reason is None and pnl >= goal:
            reason = "target"
        trigger = f is not None and abs(f - k) >= ROLL_PCT * f
        if reason is None and trigger and rolls >= MAX_ROLLS:
            reason = "stop"
        if reason is None and exit_if and exit_if(d):
            reason = "vix brake"
        if reason is None and trigger:
            nk = r100(f)
            nc, np_ = px(d, nk, "CE"), px(d, nk, "PE")
            if nc is not None and np_ is not None and nk != k:
                cash += LOTS * (nc + np_ - sc - sp)
                roll = charges(LOTS * (nc + np_), LOTS * (sc + sp), 4, LOTS * 4 * SLIP_SHORT)
                parts = {x: parts[x] + roll[x] for x in parts}
                cost += sum(roll.values())
                k, rolls = nk, rolls + 1
                strikes.append(k)
                steps.append(dict(d=d, k=k, cash=round(cash / LOTS, 2)))
            continue
        if reason:
            rs = round(pnl * LOT)
            costs = {x: round((parts[x] + closing[x]) * LOT / LOTS, 2) for x in COST_KINDS}   # rupees per sold lot
            return dict(month=m, entry=d0, exit=d, held=i, held_cal=(date.fromisoformat(d) - date.fromisoformat(d0)).days,
                        reason=reason, future_in=round(ref, 2),
                        future_out=round(f, 2) if f else "", shorts=" > ".join(f"{s:.0f}" for s in strikes),
                        wings=f"{kp:.0f}PE/{kc:.0f}CE", rolls=rolls, credit=round(credit, 2), rs_net=rs,
                        rs_per_sold_lot=round(rs / LOTS), cost_rs=round(sum(costs.values())),
                        **{f"cost_{x}": costs[x] for x in COST_KINDS}, kc=kc, kp=kp, steps=steps)
    return None


def max_drawdown(values):
    peak = equity = dd = 0.0
    for v in values:
        equity += v
        peak = max(peak, equity)
        dd = min(dd, equity - peak)
    return dd


def main():
    opt, fut, days, monthly = load()
    vix = load_vix()
    cycles = list(months(fut, days, monthly))
    results = {}
    for variant in ("hold", "VIX +20%"):
        ts = []
        for m, path, ref in cycles:
            v0 = vix.get(path[0])
            if v0 is None or not VIX_BAND[0] <= v0 <= VIX_BAND[1]:
                continue
            brake = (lambda d, v0=v0: vix.get(d, 0) > VIX_BRAKE * v0) if variant == "VIX +20%" else None
            t = trade(opt, fut, m, path, ref, brake)
            if t:
                ts.append(dict(t, variant=variant, vix_entry=round(v0, 2)))
        results[variant] = ts

    n = len(cycles)
    print(f"{SYMBOL} monthly iron fly: entry day {ENTRY_DAY} after expiry if VIX {VIX_BAND[0]}-{VIX_BAND[1]}, "
          f"wings {WING:.0%}, roll shorts at {ROLL_PCT:.0%} (max {MAX_ROLLS}), target {TARGET_FRAC:.0%} of credit; "
          f"{cycles[0][1][0]} to {cycles[-1][1][-1]}, {n} months, Rs per sold lot after costs\n")
    print(f"{'after entry':<10} {'trades':>6} {'win':>4} {'avg/trade':>9} {'per month':>9} {'avg win':>8} "
          f"{'avg loss':>9} {'worst':>8} {'max DD':>8} {'total':>9} {'yrs+':>5}  exits")
    for variant, ts in results.items():
        v = [t["rs_per_sold_lot"] for t in ts]
        wins, losses = [x for x in v if x > 0], [x for x in v if x <= 0]
        by, reasons = defaultdict(int), defaultdict(int)
        for t in ts:
            by[t["entry"][:4]] += t["rs_per_sold_lot"]
            reasons[t["reason"]] += 1
        print(f"{variant:<10} {len(v):>6} {len(wins) / len(v):>4.0%} {sum(v) / len(v):>9,.0f} {sum(v) / n:>9,.0f} "
              f"{sum(wins) / max(len(wins), 1):>8,.0f} {sum(losses) / max(len(losses), 1):>9,.0f} {min(v):>8,} "
              f"{max_drawdown(v):>8,.0f} {sum(v):>9,} {sum(x > 0 for x in by.values()):>2}/{len(by):<2}  "
              + " ".join(f"{k} {c}" for k, c in sorted(reasons.items())))

    hold = results["hold"]
    years = sorted({t["entry"][:4] for t in hold})
    by = defaultdict(int)
    for t in hold:
        by[t["entry"][:4]] += t["rs_per_sold_lot"]
    print("\nby year (hold), Rs per sold lot\n  " + "  ".join(f"{y} {by[y]:>7,}" for y in years))

    print("\nlast 6 trades (hold)")
    for t in hold[-6:]:
        print(f"  {t['month']}  VIX {t['vix_entry']:>5.2f}  {t['entry']} -> {t['exit']}  {t['reason']:<8} "
              f"shorts {t['shorts']:<12} wings {t['wings']}  credit {t['credit']:>6.1f}  "
              f"Rs/sold lot {t['rs_per_sold_lot']:>7,}")

    rows = [{k: v for k, v in t.items() if k not in ("steps", "kc", "kp")} for ts in results.values() for t in ts]
    with (HERE / "nifty_iron_fly_trades.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["variant"] + [k for k in rows[0] if k != "variant"])
        w.writeheader()
        w.writerows(rows)
    print(f"\n{len(rows)} trades written to study/nifty_iron_fly_trades.csv")
    write_json(opt, fut, days, monthly, vix, cycles, results)


def summary(ts, n_months):
    v = [t["rs_per_sold_lot"] for t in ts]
    wins, losses = [x for x in v if x > 0], [x for x in v if x <= 0]
    by = defaultdict(int)
    for t in ts:
        by[t["entry"][:4]] += t["rs_per_sold_lot"]
    return dict(trades=len(v), win=len(wins) / len(v) if v else 0, avg=sum(v) / len(v) if v else 0,
                perMonth=sum(v) / n_months, avgWin=sum(wins) / max(len(wins), 1),
                avgLoss=sum(losses) / max(len(losses), 1), worst=min(v, default=0), best=max(v, default=0),
                maxDD=max_drawdown(v), total=sum(v), yearsUp=sum(x > 0 for x in by.values()), years=len(by),
                avgHeld=sum(t["held"] for t in ts) / len(ts) if ts else 0,
                avgHeldCal=sum(t["held_cal"] for t in ts) / len(ts) if ts else 0,
                cost=sum(t["cost_rs"] for t in ts), costs={x: sum(t[f"cost_{x}"] for t in ts) for x in COST_KINDS},
                avgCost=sum(t["cost_rs"] for t in ts) / len(ts) if ts else 0,
                gross=sum(v) + sum(t["cost_rs"] for t in ts))


def current_trade(opt, fut, days, monthly, vix):
    """The month still running at the end of the data: skipped, closed early, or open and valued at the last close."""
    prev = max((e for e in monthly if e <= days[-1]), default=None)
    cur = min((e for e in monthly if e > days[-1]), default=None)
    if prev is None or cur is None:
        return None
    after = [d for d in days if d > prev]
    if len(after) < ENTRY_DAY:
        return None
    m, entry = cur[:7], after[ENTRY_DAY - 1]
    v0, ref = vix.get(entry), fut.get((entry, cur[:7]))
    out = dict(month=m, expiry=cur, entry=entry, asOf=days[-1], vix=round(v0, 2) if v0 else None,
               future=round(ref, 2) if ref else None)
    if v0 is None or ref is None or not VIX_BAND[0] <= v0 <= VIX_BAND[1]:
        return dict(out, status="skipped")
    k, kc, kp = r100(ref), r100(ref * (1 + WING)), r100(ref * (1 - WING))
    legs = {f"{k:.0f} CE": opt.get((entry, m, k, "CE")), f"{k:.0f} PE": opt.get((entry, m, k, "PE")),
            f"{kc:.0f} CE": opt.get((entry, m, kc, "CE")), f"{kp:.0f} PE": opt.get((entry, m, kp, "PE"))}
    if None in legs.values():
        return None
    credit = legs[f"{k:.0f} CE"] + legs[f"{k:.0f} PE"] - legs[f"{kc:.0f} CE"] - legs[f"{kp:.0f} PE"]
    out.update(status="open", k=k, kc=kc, kp=kp, legs={n: round(p, 2) for n, p in legs.items()},
               credit=round(credit, 2), targetPts=round(TARGET_FRAC * credit, 1),
               rollDown=round(k / (1 + ROLL_PCT)), rollUp=round(k / (1 - ROLL_PCT)),
               steps=[dict(d=entry, k=k, cash=round(credit, 2))], pnl=0, markFuture=round(ref, 2))
    path = after[ENTRY_DAY - 1:]
    if len(path) > 1:
        # the last close goes in twice: first as an ordinary day (target, roll and stop checks), then as the
        # path's last day, which values whatever is still open
        t = trade(opt, fut, m, path + [path[-1]], ref)
        if t:
            still_open = t["reason"] == "exit day"
            out.update(status="open" if still_open else "closed", exit=None if still_open else t["exit"],
                       reason=None if still_open else t["reason"], pnl=t["rs_per_sold_lot"],
                       markFuture=t["future_out"], steps=t["steps"], shorts=t["shorts"])
    return out


def return_on_margin(ts, cycles, current):
    """Profit as a share of the margin. MARGIN_PER_SET is today's quote, at today's NIFTY; margin moves roughly with
    the index, so the 'scaled' view sizes each trade's margin by NIFTY at its entry."""
    ref_now = (current or {}).get("future") or cycles[-1][2]
    start, end = date.fromisoformat(cycles[0][1][0]), date.fromisoformat(cycles[-1][1][-1])
    years = (end - start).days / 365.25
    pnl = [t["rs_per_sold_lot"] for t in ts]
    scaled = [t["rs_per_sold_lot"] / (MARGIN_PER_SET * t["future_in"] / ref_now) for t in ts]
    by = {str(y): 0.0 for y in range(start.year, end.year + 1)}
    n_by = {y: 0 for y in by}
    for t, r in zip(ts, scaled):
        by[t["entry"][:4]] += r
        n_by[t["entry"][:4]] += 1
    full = [y for y in by if y not in (str(start.year), str(end.year))]
    peak = eq = dd = 0.0
    for r in scaled:
        eq += r
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    return dict(margin=MARGIN_PER_SET, note=MARGIN_NOTE, niftyNow=round(ref_now), years=round(years, 2),
                flatTrade=sum(pnl) / len(pnl) / MARGIN_PER_SET, flatYear=sum(pnl) / years / MARGIN_PER_SET,
                flatWorst=min(pnl) / MARGIN_PER_SET, scaledTrade=sum(scaled) / len(scaled),
                scaledYear=sum(scaled) / years, scaledFullYears=sum(by[y] for y in full) / len(full),
                scaledWorst=min(scaled), scaledBest=max(scaled), scaledDD=dd,
                deployed=sum(t["held_cal"] for t in ts) / (years * 365.25),
                byYear=[dict(year=y, roi=by[y], trades=n_by[y]) for y in by])


def write_json(opt, fut, days, monthly, vix, cycles, results):
    """iron_fly_study.json at the site root: everything study/iron_fly_report.py shows."""
    n = len(cycles)
    by_month = {v: {t["month"]: t for t in ts} for v, ts in results.items()}
    # every month traded regardless of VIX, to show why the band was chosen
    unfiltered = []
    for m, path, ref in cycles:
        t = trade(opt, fut, m, path, ref)
        if t and path[0] in vix:
            unfiltered.append(dict(t, vix_entry=round(vix[path[0]], 2)))
    bands = []
    for lo, hi in [(0, 12), (12, 17), (17, 20), (20, 99)]:
        ts = [t for t in unfiltered if lo <= t["vix_entry"] < hi or (hi == 17 and t["vix_entry"] == 17)]
        if ts:
            bands.append(dict(lo=lo, hi=hi, **summary(ts, n)))
    months_out, curve, cum = [], [], {"hold": 0, "brake": 0}
    for m, path, ref in cycles:
        v0 = vix.get(path[0])
        h, b = by_month["hold"].get(m), by_month["VIX +20%"].get(m)
        traded = h is not None
        months_out.append(dict(month=m, entry=path[0], exitDay=path[-1], vix=round(v0, 2) if v0 else None,
                               traded=traded, future=round(ref, 2)))
        cum["hold"] += h["rs_per_sold_lot"] if h else 0
        cum["brake"] += b["rs_per_sold_lot"] if b else 0
        curve.append(dict(d=(h or {}).get("exit", path[-1]), hold=cum["hold"], brake=cum["brake"]))
    trades = []
    for t in results["hold"]:
        b = by_month["VIX +20%"].get(t["month"])
        trades.append(dict(m=t["month"], vix=t["vix_entry"], entry=t["entry"], exit=t["exit"], why=t["reason"],
                           fin=t["future_in"], fout=t["future_out"], shorts=t["shorts"], wings=t["wings"],
                           rolls=t["rolls"], credit=t["credit"], pnl=t["rs_per_sold_lot"], kc=t["kc"], kp=t["kp"],
                           steps=t["steps"], held=t["held"], heldCal=t["held_cal"], cost=t["cost_rs"],
                           brake=b["rs_per_sold_lot"] if b else None, brakeWhy=b["reason"] if b else None))
    reasons = {}
    for t in results["hold"]:
        r = reasons.setdefault(t["reason"], {"n": 0, "pnl": 0})
        r["n"] += 1
        r["pnl"] += t["rs_per_sold_lot"]
    yearly = {}
    for v, key in (("hold", "hold"), ("VIX +20%", "brake")):
        for t in results[v]:
            y = yearly.setdefault(t["entry"][:4], {"hold": 0, "brake": 0, "n": 0})
            y[key] += t["rs_per_sold_lot"]
            y["n"] += key == "hold"
    current = current_trade(opt, fut, days, monthly, vix)
    roi = return_on_margin(results["hold"], cycles, current)
    data = dict(asOf=days[-1], start=cycles[0][1][0], end=cycles[-1][1][-1], months=n, current=current,
                rules=dict(lot=LOT, lots=LOTS, vixBand=VIX_BAND, wing=WING, rollPct=ROLL_PCT, maxRolls=MAX_ROLLS,
                           targetFrac=TARGET_FRAC, vixBrake=VIX_BRAKE, exitBefore=EXIT_BEFORE, slipShort=SLIP_SHORT,
                           slipWing=SLIP_WING, stt=STT, brokerage=BROKERAGE, exch=EXCH, sebi=SEBI, stamp=STAMP, gst=GST),
                hold=summary(results["hold"], n), brake=summary(results["VIX +20%"], n),
                unfiltered=summary(unfiltered, n), bands=bands, reasons=reasons, yearly=yearly,
                curve=curve, monthsList=months_out, trades=trades, roi=roi)
    path = HERE.parent / "iron_fly_study.json"
    path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {path.name}")


if __name__ == "__main__":
    main()
