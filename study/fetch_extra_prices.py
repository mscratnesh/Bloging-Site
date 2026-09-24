"""Fetches price history for past Nifty 500 members that aren't in momentum_prices.json.

Output: study/prices_extra.json (same format as momentum_prices.json stocks). Symbols Yahoo has no
data for (usually delisted or merged companies) are listed in study/prices_missing.json.
Run once: py study/fetch_extra_prices.py
"""
import csv
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import momentum  # noqa: E402

from renames import RENAMES  # noqa: E402


def main():
    have = set(json.loads((HERE.parent / "momentum_prices.json").read_text(encoding="utf-8"))["stocks"])
    wanted = set()
    for path in (HERE / "constituents").glob("*.csv"):
        wanted.update(row["Symbol"] for row in csv.DictReader(path.open(encoding="utf-8")))
    # Skip stocks we already have, directly or under their current (renamed) symbol.
    wanted = {s for s in wanted if s not in have and RENAMES.get(s) not in have}
    out_path = HERE / "prices_extra.json"
    extra = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    todo = sorted(wanted - set(extra))
    print(f"{len(wanted)} symbols needed beyond the 750 cache, {len(todo)} to fetch")

    def fetch(symbol):
        # Try the symbol as it was listed; fall back to its current name for pure renames.
        for candidate in dict.fromkeys([symbol, RENAMES.get(symbol, symbol)]):
            try:
                data = momentum._full_history(f"{candidate}.NS")
                if data.get("bars"):
                    data["yahooSymbol"] = candidate
                    return symbol, data
            except momentum.FETCH_ERRORS:
                pass
        return symbol, None

    with ThreadPoolExecutor(max_workers=4) as pool:
        for symbol, data in pool.map(fetch, todo):
            if data:
                extra[symbol] = data
    out_path.write_text(json.dumps(extra, separators=(",", ":")), encoding="utf-8")
    missing = sorted(wanted - set(extra))
    (HERE / "prices_missing.json").write_text(json.dumps(missing, indent=1), encoding="utf-8")
    renamed = {s: d["yahooSymbol"] for s, d in extra.items() if d.get("yahooSymbol") != s}
    print(f"have prices for {len(extra)} ({len(renamed)} via renames: {renamed})")
    print(f"missing {len(missing)}: {', '.join(missing)}")


if __name__ == "__main__":
    main()
