"""History behind the FII/DII Activity page (fii-dii.html), in one file, data/fiidii.json.

Two series, both in Rs crore:
  nse  FII/FPI and DII buy, sell and net in the cash market, NSE's provisional figures (NSE + BSE + MSEI)
       published each trading evening. NSE only ever shows the latest day, so a row is saved every
       weekday evening by the market reel job (app.py, build_market_reel_daily) and kept in
       var/fiidii/nse.json; days before this started come from the reel's market_reel_state.json (net only).
  fpi  Foreign investment from NSDL's daily FPI report (custodian-confirmed, by reporting date), from
       2005: equity on the stock exchange (buy, sell, net), all equity, debt, others and total net.
       Fetched a month at a time from NSDL's archive and kept per month in var/fiidii/fpi_YYYY-MM.json;
       finished months are never fetched again, the last two are refreshed at most every 6 hours.

Run by hand: py fiidii.py            (fetch what's missing and rewrite data/fiidii.json)
             py fiidii.py --nse      (also record today's NSE figures)
"""
import datetime as dt
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

import requests

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
OUT_PATH = Path(os.environ.get("FIIDII_JSON_PATH") or ROOT / "data" / "fiidii.json")
CACHE_DIR = Path(os.environ.get("FIIDII_CACHE_DIR") or ROOT / "var" / "fiidii")
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
FPI_START = (2005, 1)
FPI_REFRESH_SECONDS = 6 * 3600
NSDL_ARCHIVE = "https://www.fpi.nsdl.co.in/web/Reports/Archive.aspx"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
NSE_FIELDS = ["date", "fii_buy", "fii_sell", "fii_net", "dii_buy", "dii_sell", "dii_net"]
FPI_FIELDS = ["date", "eq_buy", "eq_sell", "eq_net", "eq_all_net", "debt_net", "other_net", "total_net"]
LOCK = threading.Lock()          # the startup backfill and the nightly update may overlap


def _write_json(path: Path, data, compact=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")) if compact else json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


# ---------- NSE provisional (saved nightly) ----------
def record_nse(fd: dict, cache_dir: Path = None) -> bool:
    """Save one day of market_reel.fetch_fiidii() output. Returns True if the row is new or changed."""
    path = Path(cache_dir or CACHE_DIR) / "nse.json"
    with LOCK:
        rows = _read_json(path, {})
        day = fd["date"].isoformat()
        row = [round(fd["FII"]["buy"], 2), round(fd["FII"]["sell"], 2), round(fd["FII"]["net"], 2),
               round(fd["DII"]["buy"], 2), round(fd["DII"]["sell"], 2), round(fd["DII"]["net"], 2)]
        if rows.get(day) == row:
            return False
        rows[day] = row
        _write_json(path, dict(sorted(rows.items())), compact=False)
        return True


def nse_rows(cache_dir: Path = None, reel_state: Path = None):
    """Saved NSE days, plus net-only days the market reel recorded before this file existed."""
    rows = _read_json(Path(cache_dir or CACHE_DIR) / "nse.json", {})
    history = _read_json(Path(reel_state or ROOT / "market_reel_state.json"), {}).get("history", {})
    merged = {d: [None, None, round(v["FII"], 2), None, None, round(v["DII"], 2)] for d, v in history.items()
              if "FII" in v and "DII" in v}
    merged.update(rows)
    return [[d] + v for d, v in sorted(merged.items())]


# ---------- NSDL FPI (fetched by month) ----------
NUM = r"\(?-?[\d,]+(?:\.\d+)?\)?"
CATEGORY = re.compile(r"\b(Debt-General Limit|Debt-VRR|Debt-FAR|Debt|Equity|Hybrid|Mutual Funds|AIFs)\b(?! schemes)")
DATE = re.compile(r"\b(\d\d-[A-Z][a-z]{2}-\d{4})\b")


def _num(s: str) -> float:
    neg = s.startswith("(") or s.startswith("-")
    v = float(s.strip("()-").replace(",", ""))
    return -v if neg else v


def _nums_after(text: str, label: str, n: int = 3):
    i = text.find(label)
    if i < 0:
        return None
    found = re.findall(NUM, text[i + len(label):])
    return [_num(x) for x in found[:n]] if len(found) >= n else None


def parse_archive(html: str) -> dict:
    """NSDL's 'Daily Trends in FPI Investments up to <date>' page -> {iso date: row (FPI_FIELDS[1:])}.
    Handles the old layout (Equity / Debt lines only) and the newer one with routes, sub-totals and totals."""
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).replace("&nbsp;", " ").replace("&amp;", "&")
    start = text.find("Reporting Date")
    if start < 0:
        return {}
    body = text[start:]
    for tail in ("Total for ", "Grand Total", "The data presented above"):   # month/year/all-time summaries, footer
        if tail in body:
            body = body[:body.find(tail)]
    body = re.sub(r"Rs\.\s*[\d.,]+", " ", body)
    parts = DATE.split(body)
    out = {}
    for k in range(1, len(parts) - 1, 2):
        day, seg = dt.datetime.strptime(parts[k], "%d-%b-%Y").date().isoformat(), parts[k + 1]
        total = re.search(rf"(?<![-\w])Total\s+({NUM})\s+({NUM})\s+({NUM})", seg)
        if total:
            seg = seg[:total.end()]
        cats = list(CATEGORY.finditer(seg))
        nets, eq = {}, None
        for j, m in enumerate(cats):
            span = seg[m.end(): cats[j + 1].start() if j + 1 < len(cats) else (total.start() if total else len(seg))]
            sub = _nums_after(span, "Sub-total")
            first = [_num(x) for x in re.findall(NUM, span)[:3]]
            vals = sub or (first if len(first) == 3 else None)
            if not vals:
                continue
            nets[m.group(1)] = nets.get(m.group(1), 0) + vals[2]
            if m.group(1) == "Equity":
                se = _nums_after(span, "Stock Exchange") or vals
                eq = (se, vals[2])
        if eq is None:
            continue
        debt = sum(v for c, v in nets.items() if c.startswith("Debt"))
        other = sum(v for c, v in nets.items() if c in ("Hybrid", "Mutual Funds", "AIFs"))
        tot = _num(total.group(3)) if total else sum(nets.values())
        out[day] = [round(eq[0][0], 2), round(eq[0][1], 2), round(eq[0][2], 2), round(eq[1], 2),
                    round(debt, 2), round(other, 2), round(tot, 2)]
    return out


def fetch_fpi_month(year: int, month: int, session: requests.Session) -> dict:
    """Every reporting day of one month from NSDL's archive (an ASP.NET form: GET for the tokens, then post the date)."""
    last = (dt.date(year + month // 12, month % 12 + 1, 1) - dt.timedelta(days=1))
    page = session.get(NSDL_ARCHIVE, timeout=60)
    page.raise_for_status()
    form = dict(re.findall(r'<input type="hidden" name="(__[A-Z]+)" id="[^"]*" value="([^"]*)"', page.text))
    form.update({"__EVENTTARGET": "btnSubmit1", "__EVENTARGUMENT": "", "txtDate": "", "hdnDate": last.strftime("%d-%b-%Y"),
                 "HdnValexceldata": "", "hdnFlag": ""})
    r = session.post(NSDL_ARCHIVE, data=form, timeout=120)
    r.raise_for_status()
    prefix = f"{year:04d}-{month:02d}-"
    return {d: v for d, v in parse_archive(r.text).items() if d.startswith(prefix)}


def update_fpi(cache_dir: Path = None, today: dt.date = None, pause: float = 1.0, log=print, progress=None):
    """Fetch the months not cached yet, and refresh the last two if their copy is over 6 hours old.
    progress() is called after every 12 months fetched, so a first backfill shows up while it runs."""
    cache_dir = Path(cache_dir or CACHE_DIR)
    cache_dir.mkdir(parents=True, exist_ok=True)
    today = today or dt.datetime.now(IST).date()
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    y, m = FPI_START
    recent = {(today.year, today.month), ((today.replace(day=1) - dt.timedelta(days=1)).year,
                                          (today.replace(day=1) - dt.timedelta(days=1)).month)}
    fetched = failed = 0
    while (y, m) <= (today.year, today.month):
        path = cache_dir / f"fpi_{y:04d}-{m:02d}.json"
        stale = not path.exists() or ((y, m) in recent and time.time() - path.stat().st_mtime > FPI_REFRESH_SECONDS)
        if stale:
            try:
                rows = fetch_fpi_month(y, m, session)
                if rows or (y, m) in recent:          # an empty finished month means a failed page: retry next time
                    _write_json(path, rows)
                fetched += 1
                if progress and fetched % 12 == 0:
                    progress()
            except Exception as e:                   # NSDL down or slow: keep what's cached, retry next run
                failed += 1
                log(f"  NSDL FPI {y}-{m:02d}: {type(e).__name__}: {e}")
            time.sleep(pause)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return fetched, failed


def fpi_rows(cache_dir: Path = None):
    rows = {}
    for path in sorted(Path(cache_dir or CACHE_DIR).glob("fpi_*.json")):
        rows.update(_read_json(path, {}))
    return [[d] + v for d, v in sorted(rows.items())]


# ---------- the published file ----------
def publish(out_path: Path = None, cache_dir: Path = None, reel_state: Path = None) -> dict:
    with LOCK:
        nse, fpi = nse_rows(cache_dir, reel_state), fpi_rows(cache_dir)
        payload = {"generated": dt.datetime.now(IST).isoformat(timespec="seconds"),
                   "nse": {"fields": NSE_FIELDS, "rows": nse}, "fpi": {"fields": FPI_FIELDS, "rows": fpi}}
        _write_json(Path(out_path or OUT_PATH), payload)
        return payload


def nightly(fetch_fiidii=None, log=print) -> str:
    """Called from the reel job each evening run: record NSE's figures, top up NSDL, rewrite the file."""
    notes = []
    if fetch_fiidii:
        try:
            fd = fetch_fiidii()
            notes.append(f"NSE {fd['date']} {'saved' if record_nse(fd) else 'unchanged'}")
        except Exception as e:
            notes.append(f"NSE failed: {type(e).__name__}: {e}")
    publish()                                     # whatever is saved already, before the slow NSDL part
    fetched, failed = update_fpi(log=log, progress=publish)
    notes.append(f"NSDL {fetched} month(s) fetched" + (f", {failed} failed" if failed else ""))
    p = publish()
    notes.append(f"{len(p['nse']['rows'])} NSE days, {len(p['fpi']['rows'])} FPI days")
    return "fii-dii: " + "; ".join(notes)


if __name__ == "__main__":
    fetch = None
    if "--nse" in sys.argv:
        import market_reel
        fetch = market_reel.fetch_fiidii
    print(nightly(fetch))
