"""Download MCX crude oil futures from the exchange's daily bhav copy.

Calls the same endpoint the bhav copy page uses (https://www.mcxindia.com/market-data/bhavcopy,
GET .../GetDateWiseBhavCopy?InstrumentName=FUTCOM&fromDate=dd/mm/yyyy) once per weekday and keeps
the CRUDEOIL and CRUDEOILM rows. MCX sits behind Akamai, which rejects plain `requests`, so this
uses curl_cffi to look like Chrome (pip install curl_cffi).

Resumable: dates already in the output (or recorded as holidays) are skipped, so re-running only
fetches what is missing.

Output: study/mcx_crude_bhav.csv (date, symbol, expiry, open, high, low, close, prev_close,
        volume, oi) and study/mcx_crude_holidays.txt (weekdays with no crude rows)
Run: py study/mcx_crude_download.py [from YYYY-MM-DD] [to YYYY-MM-DD]
"""
import csv
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from curl_cffi import requests

HERE = Path(__file__).resolve().parent
OUT = HERE / "mcx_crude_bhav.csv"
HOLIDAYS = HERE / "mcx_crude_holidays.txt"
PAGE = "https://www.mcxindia.com/market-data/bhavcopy"
API = PAGE + "/GetDateWiseBhavCopy"
SYMBOLS = {"CRUDEOIL", "CRUDEOILM"}
FIELDS = ["date", "symbol", "expiry", "open", "high", "low", "close", "prev_close", "volume", "oi"]


def session():
    s = requests.Session(impersonate="chrome")
    s.get(PAGE, timeout=60)
    return s


def fetch(s, d):
    headers = {"Referer": PAGE, "X-Requested-With": "XMLHttpRequest",
               "Accept": "application/json, text/javascript, */*; q=0.01"}
    r = s.get(API, params={"InstrumentName": "FUTCOM", "fromDate": d.strftime("%d/%m/%Y")},
              headers=headers, timeout=60)
    r.raise_for_status()
    rows = []
    for x in r.json().get("Data") or []:
        sym = (x.get("Symbol") or "").strip()
        if sym not in SYMBOLS:
            continue
        expiry = datetime.strptime(x["ExpiryDate"].strip(), "%d%b%Y").date()
        rows.append([d.isoformat(), sym, expiry.isoformat(), x["Open"], x["High"], x["Low"],
                     x["Close"], x["PreviousClose"], x["Volume"], x["OpenInterest"]])
    return rows


def main():
    start = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2021, 9, 1)
    end = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else date.today() - timedelta(days=1)

    done = set()
    if OUT.exists():
        with OUT.open(newline="") as f:
            done = {row["date"] for row in csv.DictReader(f)}
    if HOLIDAYS.exists():
        done |= set(HOLIDAYS.read_text().split())

    todo = [start + timedelta(n) for n in range((end - start).days + 1)]
    todo = [d for d in todo if d.weekday() < 5 and d.isoformat() not in done]
    print(f"{len(todo)} weekdays to fetch ({start} to {end})", flush=True)

    new_file = not OUT.exists()
    s = session()
    with OUT.open("a", newline="") as out, HOLIDAYS.open("a") as hol:
        w = csv.writer(out)
        if new_file:
            w.writerow(FIELDS)
        for i, d in enumerate(todo, 1):
            for attempt in range(4):
                try:
                    rows = fetch(s, d)
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
                hol.write(d.isoformat() + "\n")
                hol.flush()
            if i % 50 == 0:
                print(f"{i}/{len(todo)} up to {d}", flush=True)
            time.sleep(0.4)
    print("done", flush=True)


if __name__ == "__main__":
    main()
