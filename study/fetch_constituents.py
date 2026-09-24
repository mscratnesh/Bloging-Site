"""Downloads archived Nifty 500 constituent lists from the Wayback Machine into study/constituents/.

These point-in-time lists let the study measure survivorship bias: NSE publishes only the current
list, so older versions come from web.archive.org snapshots of NSE's own CSV files.
Run once: py study/fetch_constituents.py
"""
import csv
import io
import json
import time
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent / "constituents"
UA = {"User-Agent": "Mozilla/5.0 (research; point-in-time index constituents)"}
FILE = "ind_nifty500list.csv"
HOSTS = ["niftyindices.com/IndexConstituent/", "archives.nseindia.com/content/indices/", "www.nseindia.com/content/indices/"]


def get(url, timeout=120):
    for attempt in range(4):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()
        except Exception:
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"Could not fetch {url}")


def main():
    OUT.mkdir(exist_ok=True)
    snapshots = {}
    for host in HOSTS:
        api = f"http://web.archive.org/cdx/search/cdx?url={host}{FILE}&output=json&filter=statuscode:200&collapse=timestamp:6"
        for row in json.loads(get(api) or b"[]")[1:]:
            snapshots.setdefault(row[1][:6], (row[1], row[2]))  # one per month
    saved = []
    for month, (stamp, original) in sorted(snapshots.items()):
        text = get(f"http://web.archive.org/web/{stamp}id_/{original}").decode("utf-8", errors="replace")
        text = text.replace("\r\n", "\n").replace("\r", "\n")  # some snapshots use bare CR line endings
        symbols = sorted({(r.get("Symbol") or "").strip() for r in csv.DictReader(io.StringIO(text))} - {""})
        symbols = [s for s in symbols if not s.startswith("DUMMY")]
        if len(symbols) < 450:  # an error page or a partial file
            print(f"{stamp}: skipped ({len(symbols)} symbols)")
            continue
        date = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}"
        (OUT / f"nifty500_{date}.csv").write_text("Symbol\n" + "\n".join(symbols) + "\n", encoding="utf-8")
        saved.append((date, len(symbols)))
        print(f"{date}: {len(symbols)} symbols")
    print(f"saved {len(saved)} snapshots to {OUT}")


if __name__ == "__main__":
    main()
