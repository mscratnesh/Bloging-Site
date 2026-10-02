"""Download MCX CRUDEOIL options (options on futures) from the exchange's daily bhav copy.

Same endpoint as mcx_crude_download.py, with InstrumentName=OPTFUT. Crude options start in May 2018.
To keep the file small, only the two nearest option expiries are kept, and only strikes that are
multiples of STRIKE_STEP within STRIKE_RANGE points of the option's underlying future (the nearest
CRUDEOIL future expiring on or after the option, from study/mcx_crude_bhav.csv, so download the
futures first).

Resumable: dates already in the output (or recorded as no-data days) are skipped.

Output: study/mcx_crude_options.csv (date, expiry, strike, type, open, high, low, close,
        prev_close, volume, oi, underlying, underlying_close) and
        study/mcx_crude_options_nodata.txt (weekdays with no crude option rows)
Run: py study/mcx_crude_options_download.py [from YYYY-MM-DD] [to YYYY-MM-DD]
"""
import csv
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta

from mcx_crude_download import HERE, PAGE, API, session

OUT = HERE / "mcx_crude_options.csv"
NODATA = HERE / "mcx_crude_options_nodata.txt"
FUTURES = HERE / "mcx_crude_bhav.csv"
STRIKE_STEP = 100
STRIKE_RANGE = 1500
FIELDS = ["date", "expiry", "strike", "type", "open", "high", "low", "close", "prev_close",
          "volume", "oi", "underlying", "underlying_close"]


def load_futures():
    fut = defaultdict(dict)             # date -> {expiry: close}
    with FUTURES.open(newline="") as f:
        for r in csv.DictReader(f):
            if r["symbol"] == "CRUDEOIL":
                fut[r["date"]][r["expiry"]] = float(r["close"])
    return fut


def fetch(s, d, fut_today):
    headers = {"Referer": PAGE, "X-Requested-With": "XMLHttpRequest",
               "Accept": "application/json, text/javascript, */*; q=0.01"}
    r = s.get(API, params={"InstrumentName": "OPTFUT", "fromDate": d.strftime("%d/%m/%Y")},
              headers=headers, timeout=60)
    r.raise_for_status()
    crude = [x for x in r.json().get("Data") or [] if (x.get("Symbol") or "").strip() == "CRUDEOIL"]
    if not crude:
        return None
    expiry = lambda x: datetime.strptime(x["ExpiryDate"].strip(), "%d%b%Y").date().isoformat()
    keep = sorted({expiry(x) for x in crude if expiry(x) >= d.isoformat()})[:2]
    rows = []
    for x in crude:
        e = expiry(x)
        if e not in keep:
            continue
        under = min((fe for fe in fut_today if fe >= e), default=None)
        if under is None:
            continue
        u_close = fut_today[under]
        k = float(x["StrikePrice"])
        if k % STRIKE_STEP or abs(k - u_close) > STRIKE_RANGE:
            continue
        rows.append([d.isoformat(), e, int(k), x["OptionType"].strip(), x["Open"], x["High"], x["Low"],
                     x["Close"], x["PreviousClose"], x["Volume"], x["OpenInterest"], under, u_close])
    return rows


def main():
    start = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2018, 5, 1)
    end = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else date.today() - timedelta(days=1)
    fut = load_futures()

    done = set()
    if OUT.exists():
        with OUT.open(newline="") as f:
            done = {row["date"] for row in csv.DictReader(f)}
    if NODATA.exists():
        done |= set(NODATA.read_text().split())

    # Only days the futures file has (a futures holiday has no options either).
    todo = [start + timedelta(n) for n in range((end - start).days + 1)]
    todo = [d for d in todo if d.isoformat() in fut and d.isoformat() not in done]
    print(f"{len(todo)} trading days to fetch ({start} to {end})", flush=True)

    new_file = not OUT.exists()
    s = session()
    with OUT.open("a", newline="") as out, NODATA.open("a") as nod:
        w = csv.writer(out)
        if new_file:
            w.writerow(FIELDS)
        for i, d in enumerate(todo, 1):
            for attempt in range(4):
                try:
                    rows = fetch(s, d, fut[d.isoformat()])
                    break
                except Exception as e:
                    print(f"{d} attempt {attempt + 1} failed: {e}", flush=True)
                    time.sleep(5 * (attempt + 1))
                    s = session()
            else:
                print(f"{d} skipped after 4 failures; re-run to retry", flush=True)
                continue
            if rows:
                w.writerows(rows)
                out.flush()
            else:
                nod.write(d.isoformat() + "\n")
                nod.flush()
            if i % 50 == 0:
                print(f"{i}/{len(todo)} up to {d}", flush=True)
            time.sleep(0.4)
    print("done", flush=True)


if __name__ == "__main__":
    main()
