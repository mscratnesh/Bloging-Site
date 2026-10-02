"""NIFTY monthly iron fly, one trade a month, entered only when India VIX is 12-17.

Rules, all decided at daily closes on NSE's monthly NIFTY options:
    entry   - close of the first trading day after a monthly expiry (about 30 days to the next one), only if
              India VIX closes within VIX_BAND that day; otherwise skip the month
    legs    - per set: sell 1 lot of the ATM call and put (strike nearest the current-month future, rounded to
              100), buy 1 lot of the call and put WING away (rounded to 100); LOTS sets
    target  - close everything at the first close where the open profit, after costs paid and the cost of
              closing, is at least TARGET rupees per sold lot
    roll    - if the future closes ROLL_PCT or more from the short strike, buy back the short call and put and
              sell them at the new ATM strike (the bought wings stay); at most MAX_ROLLS times
    stop    - on the roll trigger after MAX_ROLLS rolls, close everything
    time    - otherwise close EXIT_BEFORE trading days before expiry
    VIX     - ignored once in a trade; the "VIX +20%" variant also closes once VIX is 20% above its entry level

Prices: close when the option traded that day, else NSE's settle price. Rupees are per sold lot (the LOTS-set
position divided by LOTS; brokerage is per order whatever the lots, so a single set pays a little more).
Costs: SLIP_SHORT / SLIP_WING points per lot per order, STT of 0.1% on sold premium, BROKERAGE per order.

Inputs: study/fno_bhavcopy/fo_<year>.parquet (from study/fetch_fno_bhavcopy.py) and study/india_vix_daily.csv
(downloaded from Yahoo Finance, ^INDIAVIX, if missing; needs yfinance)
Output: printed summary and study/nifty_iron_fly_trades.csv
Run: py study/nifty_iron_fly_study.py
"""
import csv
from collections import defaultdict
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
SYMBOL = "NIFTY"
LOT, LOTS = 65, 4
ENTRY_DAY, EXIT_BEFORE = 1, 1
VIX_BAND = (12, 17)
WING, ROLL_PCT, MAX_ROLLS = 0.02, 0.02, 1
TARGET = 3000
VIX_BRAKE = 1.2
SLIP_SHORT, SLIP_WING, STT, BROKERAGE = 1.0, 0.5, 0.001, 20.0


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


def trade(opt, fut, m, path, ref, exit_if=None):
    px = lambda d, k, t: opt.get((d, m, k, t))
    k, kc, kp = r100(ref), r100(ref * (1 + WING)), r100(ref * (1 - WING))
    d0 = path[0]
    entry = [px(d0, k, "CE"), px(d0, k, "PE"), px(d0, kc, "CE"), px(d0, kp, "PE")]
    if None in entry or not all(p > 0 for p in entry):
        return None
    cash = LOTS * (entry[0] + entry[1] - entry[2] - entry[3])          # points x lots received
    cost = LOTS * 2 * (SLIP_SHORT + SLIP_WING) + STT * LOTS * (entry[0] + entry[1]) + 4 * BROKERAGE / LOT
    credit, rolls, strikes = entry[0] + entry[1] - entry[2] - entry[3], 0, [k]
    for i, d in enumerate(path[1:], 1):
        last = i == len(path) - 1
        f = fut.get((d, m))
        sc, sp, wc, wp = px(d, k, "CE"), px(d, k, "PE"), px(d, kc, "CE"), px(d, kp, "PE")
        if None in (sc, sp, wc, wp):
            if last:
                return None
            continue
        close_cost = LOTS * 2 * (SLIP_SHORT + SLIP_WING) + STT * LOTS * (wc + wp) + 4 * BROKERAGE / LOT
        pnl = cash - LOTS * (sc + sp) + LOTS * (wc + wp) - cost - close_cost
        reason = "exit day" if last else None
        if reason is None and pnl * LOT >= TARGET * LOTS:
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
                cost += LOTS * 4 * SLIP_SHORT + STT * LOTS * (nc + np_) + 4 * BROKERAGE / LOT
                k, rolls = nk, rolls + 1
                strikes.append(k)
            continue
        if reason:
            rs = round(pnl * LOT)
            return dict(month=m, entry=d0, exit=d, reason=reason, future_in=round(ref, 2),
                        future_out=round(f, 2) if f else "", shorts=" > ".join(f"{s:.0f}" for s in strikes),
                        wings=f"{kp:.0f}PE/{kc:.0f}CE", rolls=rolls, credit=round(credit, 2), rs_net=rs,
                        rs_per_sold_lot=round(rs / LOTS))
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
          f"wings {WING:.0%}, roll shorts at {ROLL_PCT:.0%} (max {MAX_ROLLS}), target Rs {TARGET:,}/sold lot; "
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

    rows = [t for ts in results.values() for t in ts]
    with (HERE / "nifty_iron_fly_trades.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["variant"] + [k for k in rows[0] if k != "variant"])
        w.writeheader()
        w.writerows(rows)
    print(f"\n{len(rows)} trades written to study/nifty_iron_fly_trades.csv")


if __name__ == "__main__":
    main()
