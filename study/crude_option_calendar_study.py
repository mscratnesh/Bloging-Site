"""MCX crude oil options calendar spread: sell the current-month option, buy the next-month option at
the same strike, hold to the current option's expiry. Tests the idea that the near-month option loses
time value faster.

Each cycle enters either on trading day N after the previous option expiry ("day N"), or N trading
days before the current option's expiry ("N before"). The next-month option hardly trades until the
last 2-3 days before the current expiry, so only the late entries can really be filled. Strike = the current option's
underlying future at the entry close, rounded to the nearest ROUND (100 = at the money, 1000 = the
nearest round thousand). Calls and puts are tested separately.

Exit on the current option's expiry day: the sold option is valued at its expiry value (intrinsic,
from the underlying future's close that day); the bought option at its close that day.
P&L points = (sold at entry - expiry value) + (bought option's exit close - entry close).

Prices are bhav copy closes; strikes that did not trade carry MCX's calculated close, so the report
counts how often each leg had no volume. Rupees are per lot (100 barrels). Costs per spread:
SLIP_NEAR / SLIP_NEXT points per order on the near / next option (2 orders each), CTT of 0.05% of
premium on the two sell orders, and BROKERAGE rupees per order (4 orders).

Inputs: study/mcx_crude_options.csv (mcx_crude_options_download.py), study/mcx_crude_bhav.csv
Output: printed summary and study/crude_option_calendar_trades.csv
Run: py study/crude_option_calendar_study.py
"""
import csv
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOT = 100
ENTRIES = (("after", 1), ("after", 2), ("before", 3), ("before", 2))
ROUNDS = (100, 1000)
TYPES = ("CE", "PE")
SLIP_NEAR = 2.0      # points per order, current-month option
SLIP_NEXT = 5.0      # points per order, next-month option (thinly traded)
CTT = 0.0005         # on the premium of sell orders
BROKERAGE = 20.0     # rupees per order
WARS = [("2022-02-24", "2022-08-31"), ("2025-06-13", "2025-07-31"), ("2026-03-01", "2099-12-31")]


def load():
    opt = {}                                        # (date, expiry, strike, type) -> (close, volume)
    under = {}                                      # (date, expiry) -> underlying future close
    days = set()
    with (HERE / "mcx_crude_options.csv").open(newline="") as f:
        for r in csv.DictReader(f):
            opt[(r["date"], r["expiry"], int(r["strike"]), r["type"])] = (float(r["close"]), int(float(r["volume"])))
            under[(r["date"], r["expiry"])] = float(r["underlying_close"])
            days.add(r["date"])
    return opt, under, sorted(days)


def trades(opt, under, days, entry, rnd, typ):
    mode, n = entry
    expiries = sorted({e for _, e, _, _ in opt})
    out = []
    for prev, cur, nxt in zip(expiries, expiries[1:], expiries[2:]):
        window = [d for d in days if prev < d < cur]
        if cur not in days or len(window) < n:
            continue
        entry = window[n - 1] if mode == "after" else window[-n]
        if entry >= cur or (entry, cur) not in under or (cur, cur) not in under:
            continue
        f_in = under[(entry, cur)]
        k = int(round(f_in / rnd) * rnd)
        try:
            (near_in, near_vol), (next_in, next_vol) = opt[(entry, cur, k, typ)], opt[(entry, nxt, k, typ)]
            next_out, next_vol_out = opt[(cur, nxt, k, typ)]
        except KeyError:
            continue
        f_out = under[(cur, cur)]
        near_out = max(0.0, f_out - k) if typ == "CE" else max(0.0, k - f_out)
        pts = (near_in - near_out) + (next_out - next_in)
        cost = 2 * SLIP_NEAR + 2 * SLIP_NEXT + CTT * (near_in + next_out) + 4 * BROKERAGE / LOT
        out.append(dict(type=typ, round=rnd, entry_rule=f"{n} {mode}", entry=entry, exit=cur, near=cur, next=nxt,
                        strike=k, fut_entry=f_in, fut_exit=f_out, near_entry=near_in, near_exit=near_out,
                        next_entry=next_in, next_exit=next_out, near_vol_entry=near_vol,
                        next_vol_entry=next_vol, next_vol_exit=next_vol_out,
                        war=any(entry <= b and cur >= a for a, b in WARS),
                        points=round(pts, 2), cost_points=round(cost, 2),
                        rs_net=round((pts - cost) * LOT, 2)))
    return out


def max_drawdown(values):
    peak = equity = dd = 0.0
    for v in values:
        equity += v
        peak = max(peak, equity)
        dd = min(dd, equity - peak)
    return dd


def line(name, ts):
    if not ts:
        print(f"  {name:<16} no trades")
        return
    v = [t["rs_net"] for t in ts]
    g = [t["points"] for t in ts]
    print(f"  {name:<16} trades {len(v):>3}  net Rs {sum(v):>10,.0f}  avg {sum(v) / len(v):>7,.0f}  "
          f"gross avg {sum(g) / len(g):>+6.1f} pts  win {sum(x > 0 for x in v) / len(v):>4.0%}  "
          f"worst {min(v):>8,.0f}  max DD {max_drawdown(v):>9,.0f}  "
          f"next leg untraded {sum(t['next_vol_entry'] == 0 for t in ts) / len(ts):>4.0%}")


def main():
    opt, under, days = load()
    rows = []
    print(f"CRUDEOIL options {days[0]} to {days[-1]}; sell current-month option, buy next-month option, same strike")
    for rnd in ROUNDS:
        for typ in TYPES:
            for entry in ENTRIES:
                ts = trades(opt, under, days, entry, rnd, typ)
                rows += ts
                label = f"day {entry[1]} after previous expiry" if entry[0] == "after" else f"{entry[1]} trading days before expiry"
                print(f"\n{typ}, strike = nearest {rnd}, entry {label}")
                line("all", ts)
                line("without wars", [t for t in ts if not t["war"]])
                by_year = defaultdict(list)
                for t in ts:
                    by_year[t["entry"][:4]].append(t["rs_net"])
                print("    " + "  ".join(f"{y} {sum(v):>8,.0f}" for y, v in sorted(by_year.items())))
    with (HERE / "crude_option_calendar_trades.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"\n{len(rows)} trades written to study/crude_option_calendar_trades.csv")


if __name__ == "__main__":
    main()
