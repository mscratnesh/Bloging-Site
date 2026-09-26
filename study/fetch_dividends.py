"""Fetches dividend history for every stock in the study's price data.

Yahoo's dividend amounts are on today's share basis (after splits and bonuses), while the price cache
can hold older bars on the old basis. So each dividend is stored as a yield, the amount divided by
the close of the session before the ex-date, both from the same fresh download.

Output: study/dividends.json  {symbol: {ex-date: yield}}
Run: py study/fetch_dividends.py      (re-run to refresh; ~900 requests)
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import momentum  # noqa: E402

RANGE = "10y"


def dividends(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}.NS?range={RANGE}&interval=1d&events=div"
    try:
        res = json.loads(momentum._get(url, timeout=30))["chart"]["result"][0]
    except momentum.FETCH_ERRORS:
        return symbol, None
    day = lambda ts: datetime.fromtimestamp(ts, tz=momentum.IST).strftime("%Y-%m-%d")
    closes = {day(ts): c for ts, c in zip(res.get("timestamp") or [], res["indicators"]["quote"][0].get("close") or []) if c}
    days = sorted(closes)
    out = {}
    for ev in (res.get("events") or {}).get("dividends", {}).values():
        ex = day(ev["date"])
        before = [d for d in days if d < ex]
        if before and ev.get("amount"):
            out[ex] = round(ev["amount"] / closes[before[-1]], 6)
    return symbol, out


def main():
    store = json.loads((HERE.parent / "momentum_prices.json").read_text(encoding="utf-8"))
    extra = json.loads((HERE / "prices_extra.json").read_text(encoding="utf-8"))
    symbols = sorted(set(store["stocks"]) | {d.get("yahooSymbol", s) for s, d in extra.items()})
    print(f"fetching dividends for {len(symbols)} stocks")
    got, failed = {}, []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for symbol, divs in pool.map(dividends, symbols):
            if divs is None:
                failed.append(symbol)
            elif divs:
                got[symbol] = divs
    (HERE / "dividends.json").write_text(json.dumps(got, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    n = sum(len(v) for v in got.values())
    big = sorted(((y, s, d) for s, v in got.items() for d, y in v.items() if y > 0.1), reverse=True)
    print(f"{len(got)} stocks paid {n} dividends; {len(failed)} failed: {', '.join(failed)}")
    print("yields over 10% (check):", big[:15])


if __name__ == "__main__":
    main()
