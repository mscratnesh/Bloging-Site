"""MCX crude oil calendar spread: trade the current month against the next month, hold to expiry.

Each cycle enters on trading day ENTRY_DAY after a crude contract expires (day 1 is the first
trading day after it). That day the "current" contract is the one expiring next and the "next"
contract is the one after it. The side depends on the spread (current minus next) at the entry
close:
    spread <  THRESHOLD: normal  - buy current, sell next
    spread >= THRESHOLD: reverse - sell current, buy next
Both legs are closed at the close on the current contract's expiry day. Then repeat.

The trade only makes money from a change in the spread, not from the direction of crude:
    normal P&L points  = spread at exit - spread at entry
    reverse P&L points = spread at entry - spread at exit

Prices are bhav copy closes. Rupees are per lot: CRUDEOIL = 100 barrels, CRUDEOILM = 10 barrels,
quoted in Rs per barrel. Costs per round trip of the spread (4 orders): SLIPPAGE points per order,
CTT of 0.01% on the two sell orders, and BROKERAGE rupees per order.

Inputs: study/mcx_crude_bhav.csv (from study/mcx_crude_download.py)
Output: printed summary and study/crude_spread_trades.csv
Run: py study/crude_spread_study.py
"""
import csv
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOT = {"CRUDEOIL": 100, "CRUDEOILM": 10}
ENTRY_DAYS = (1, 2)  # trading days after the previous expiry
THRESHOLD = 50.0     # reverse the trade when the entry spread is at least this many points
SLIPPAGE = 1.0       # points per order
CTT = 0.0001         # on the sell side
BROKERAGE = 20.0     # rupees per order


def load():
    px = defaultdict(dict)            # (symbol) -> {(date, expiry): (close, volume)}
    days = defaultdict(set)
    with (HERE / "mcx_crude_bhav.csv").open(newline="") as f:
        for r in csv.DictReader(f):
            px[r["symbol"]][(r["date"], r["expiry"])] = (float(r["close"]), int(float(r["volume"])))
            days[r["symbol"]].add(r["date"])
    return px, {s: sorted(d) for s, d in days.items()}


def trades(symbol, px, days, entry_day):
    p = px[symbol]
    expiries = sorted({e for _, e in p})
    first, last = days[0], days[-1]
    out = []
    for prev, cur, nxt in zip(expiries, expiries[1:], expiries[2:]):
        if prev < first or cur > last or (cur, cur) not in p:
            continue                  # outside the data, or the contract's expiry day is missing
        after = [d for d in days if prev < d < cur]
        if len(after) < entry_day:
            continue
        entry, exit_ = after[entry_day - 1], cur
        try:
            (c_in, _), (n_in, n_vol) = p[(entry, cur)], p[(entry, nxt)]
            (c_out, _), (n_out, _) = p[(exit_, cur)], p[(exit_, nxt)]
        except KeyError:
            continue
        spread_in, spread_out = c_in - n_in, c_out - n_out
        reverse = spread_in >= THRESHOLD
        pts = (spread_in - spread_out) if reverse else (spread_out - spread_in)
        sells = c_in + n_out if reverse else n_in + c_out
        cost_pts = 4 * SLIPPAGE + CTT * sells + 4 * BROKERAGE / LOT[symbol]
        out.append(dict(symbol=symbol, entry_day=entry_day, entry=entry, exit=exit_, current=cur, next=nxt,
                        side="reverse" if reverse else "normal",
                        cur_entry=c_in, next_entry=n_in, cur_exit=c_out, next_exit=n_out,
                        spread_entry=spread_in, spread_exit=spread_out,
                        next_vol_entry=n_vol, points=pts, cost_points=round(cost_pts, 2),
                        rs_gross=round(pts * LOT[symbol], 2),
                        rs_net=round((pts - cost_pts) * LOT[symbol], 2)))
    return out


def max_drawdown(values):
    peak = equity = dd = 0.0
    for v in values:
        equity += v
        peak = max(peak, equity)
        dd = min(dd, equity - peak)
    return dd


def summary(name, ts, key):
    vals = [t[key] for t in ts]
    if not vals:
        return
    wins = [v for v in vals if v > 0]
    losses = [v for v in vals if v <= 0]
    print(f"  {name:<14} trades {len(vals):>3}  total Rs {sum(vals):>11,.0f}  "
          f"avg {sum(vals) / len(vals):>8,.0f}  win {len(wins) / len(vals):>4.0%}  "
          f"avg win {sum(wins) / max(len(wins), 1):>8,.0f}  avg loss {sum(losses) / max(len(losses), 1):>9,.0f}  "
          f"worst {min(vals):>9,.0f}  max DD {max_drawdown(vals):>10,.0f}")


def main():
    px, days = load()
    all_trades = []
    for entry_day in ENTRY_DAYS:
        for symbol in ("CRUDEOIL", "CRUDEOILM"):
            if symbol not in days:
                continue
            ts = trades(symbol, px, days[symbol], entry_day)
            if not ts:
                continue
            all_trades += ts
            print(f"\n{symbol} ({LOT[symbol]} bbl/lot), entry day {entry_day}, reverse when spread >= {THRESHOLD:g}: "
                  f"{ts[0]['entry']} to {ts[-1]['exit']}, per lot")
            summary("all net", ts, "rs_net")
            summary("normal net", [t for t in ts if t["side"] == "normal"], "rs_net")
            summary("reverse net", [t for t in ts if t["side"] == "reverse"], "rs_net")
            by_year = defaultdict(list)
            for t in ts:
                by_year[t["entry"][:4]].append(t)
            print("    year  trades  reversed  net Rs")
            for y, yt in sorted(by_year.items()):
                print(f"    {y}  {len(yt):>6}  {sum(t['side'] == 'reverse' for t in yt):>8}  "
                      f"{sum(t['rs_net'] for t in yt):>10,.0f}")

    with (HERE / "crude_spread_trades.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(all_trades[0]))
        w.writeheader()
        w.writerows(all_trades)
    print(f"\n{len(all_trades)} trades written to study/crude_spread_trades.csv")


if __name__ == "__main__":
    main()
