"""History behind the FII/DII Activity page (fii-dii.html). Stored in SQLite (fiidii.db next to the server);
the page reads data/fiidii.json, which publish() rebuilds from the database.

Two series, both in Rs crore, both from official sources only:
  nse_daily  FII/FPI and DII buy, sell and net in the cash market, NSE's provisional figures (NSE + BSE +
             MSEI) published each trading evening. NSE only ever shows the latest day, so a row is saved
             every weekday evening by the market reel job (app.py, build_market_reel_daily). Days the reel
             saved before this (market_reel_state.json, net only) are kept with source 'reel'. These rows
             can't be fetched again: back up fiidii.db and never overwrite it on deploy.
  fpi_daily  Foreign investment from NSDL's daily FPI report (custodian-confirmed, by reporting date), from
             2005: equity on the stock exchange (buy, sell, net), all equity, debt, others and total net.
             Fetched a month at a time from NSDL's archive; fpi_months records when each month was fetched.
             Finished months are never fetched again, the last two are refreshed at most every 6 hours.

fiidii_seed.db (built with --seed, shipped in dist) holds the NSDL tables and any full NSE rows saved where
it was built, so a new server starts with the full history. It's merged in without replacing anything newer:
a seed NSE row only fills a day that is missing or net-only ('reel'), never one the server saved itself. Older JSON caches in var/fiidii/ are
imported once, so switching to the database loses nothing.

Run by hand: py fiidii.py            (fetch what's missing and rewrite data/fiidii.json)
             py fiidii.py --nse      (also record today's NSE figures)
             py fiidii.py --seed     (write fiidii_seed.db from fiidii.db, for dist)
"""
import datetime as dt
import json
import os
import re
import sqlite3
import sys
import threading
import time
from contextlib import closing
from pathlib import Path

import requests

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("FIIDII_DB_PATH") or ROOT / "fiidii.db")
SEED_PATH = Path(os.environ.get("FIIDII_SEED_PATH") or ROOT / "fiidii_seed.db")
OUT_PATH = Path(os.environ.get("FIIDII_JSON_PATH") or ROOT / "data" / "fiidii.json")
LEGACY_DIR = ROOT / "var" / "fiidii"            # JSON caches from before the database
REEL_STATE = ROOT / "market_reel_state.json"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
FPI_START = (2005, 1)
FPI_REFRESH_SECONDS = 6 * 3600
NSDL_ARCHIVE = "https://www.fpi.nsdl.co.in/web/Reports/Archive.aspx"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
NSE_FIELDS = ["date", "fii_buy", "fii_sell", "fii_net", "dii_buy", "dii_sell", "dii_net"]
FPI_FIELDS = ["date", "eq_buy", "eq_sell", "eq_net", "eq_all_net", "debt_net", "other_net", "total_net"]
LOCK = threading.RLock()         # the startup backfill and the nightly update may overlap

SCHEMA = """
CREATE TABLE IF NOT EXISTS nse_daily (
    date TEXT PRIMARY KEY, fii_buy REAL, fii_sell REAL, fii_net REAL, dii_buy REAL, dii_sell REAL, dii_net REAL,
    source TEXT NOT NULL, saved_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS fpi_daily (
    date TEXT PRIMARY KEY, eq_buy REAL, eq_sell REAL, eq_net REAL, eq_all_net REAL, debt_net REAL, other_net REAL,
    total_net REAL);
CREATE TABLE IF NOT EXISTS fpi_months (month TEXT PRIMARY KEY, fetched_at REAL NOT NULL, days INTEGER NOT NULL);
"""


def _now():
    return dt.datetime.now(IST).isoformat(timespec="seconds")


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def connect(db_path: Path = None, seed_path: Path = None, legacy_dir: Path = None, reel_state: Path = None):
    """Open the database, creating it if needed, and merge in the seed, old JSON caches and the reel's history.
    Every merge is insert-if-missing (or fills a net-only row), so it's safe to run on every open."""
    db_path = Path(db_path or DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(db_path, timeout=30)
    db.executescript(SCHEMA)
    seed = Path(seed_path or SEED_PATH)
    if seed.is_file() and seed.resolve() != db_path.resolve():
        db.execute("ATTACH DATABASE ? AS seed", (str(seed),))
        db.execute("INSERT OR IGNORE INTO fpi_daily SELECT * FROM seed.fpi_daily")
        db.execute("INSERT OR IGNORE INTO fpi_months SELECT * FROM seed.fpi_months")
        if db.execute("SELECT 1 FROM seed.sqlite_master WHERE name = 'nse_daily'").fetchone():
            db.execute("""INSERT INTO nse_daily SELECT * FROM seed.nse_daily WHERE source = 'nse'
                          ON CONFLICT(date) DO UPDATE SET fii_buy=excluded.fii_buy, fii_sell=excluded.fii_sell,
                          fii_net=excluded.fii_net, dii_buy=excluded.dii_buy, dii_sell=excluded.dii_sell,
                          dii_net=excluded.dii_net, source=excluded.source, saved_at=excluded.saved_at
                          WHERE nse_daily.source = 'reel'""")
        db.commit()
        db.execute("DETACH DATABASE seed")
    legacy = Path(legacy_dir or LEGACY_DIR)
    if legacy.is_dir():
        for day, v in _read_json(legacy / "nse.json", {}).items():
            _upsert_nse(db, day, v, "nse", replace=False)
        for path in sorted(legacy.glob("fpi_*.json")):
            month = path.stem[4:]
            if db.execute("SELECT 1 FROM fpi_months WHERE month = ?", (month,)).fetchone():
                continue
            rows = _read_json(path, {})
            db.executemany("INSERT OR IGNORE INTO fpi_daily VALUES (?,?,?,?,?,?,?,?)", [[d] + v for d, v in rows.items()])
            if rows:
                db.execute("INSERT OR IGNORE INTO fpi_months VALUES (?,?,?)", (month, path.stat().st_mtime, len(rows)))
    for day, v in _read_json(Path(reel_state or REEL_STATE), {}).get("history", {}).items():
        if "FII" in v and "DII" in v:
            db.execute("INSERT OR IGNORE INTO nse_daily VALUES (?,?,?,?,?,?,?,?,?)",
                       (day, None, None, round(v["FII"], 2), None, None, round(v["DII"], 2), "reel", _now()))
    db.commit()
    return db


def _upsert_nse(db, day, v, source, replace=True):
    """Save a full NSE row. replace=False only fills a missing day or a net-only 'reel' row."""
    where = "" if replace else " WHERE nse_daily.source = 'reel'"
    db.execute(f"""INSERT INTO nse_daily VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(date) DO UPDATE SET fii_buy=excluded.fii_buy, fii_sell=excluded.fii_sell,
                   fii_net=excluded.fii_net, dii_buy=excluded.dii_buy, dii_sell=excluded.dii_sell,
                   dii_net=excluded.dii_net, source=excluded.source, saved_at=excluded.saved_at{where}""",
               [day] + list(v) + [source, _now()])


# ---------- NSE provisional (saved nightly) ----------
def record_nse(fd: dict, db_path: Path = None) -> bool:
    """Save one day of market_reel.fetch_fiidii() output. Returns True if the row is new or changed."""
    day = fd["date"].isoformat()
    row = [round(fd["FII"]["buy"], 2), round(fd["FII"]["sell"], 2), round(fd["FII"]["net"], 2),
           round(fd["DII"]["buy"], 2), round(fd["DII"]["sell"], 2), round(fd["DII"]["net"], 2)]
    with LOCK, closing(connect(db_path)) as db:
        old = db.execute("SELECT fii_buy, fii_sell, fii_net, dii_buy, dii_sell, dii_net FROM nse_daily WHERE date = ?",
                         (day,)).fetchone()
        if old and list(old) == row:
            return False
        _upsert_nse(db, day, row, "nse")
        db.commit()
        return True


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


def archive_date(year: int, month: int, today: dt.date = None) -> dt.date:
    """The date to ask NSDL's archive for: the month-end, or today for the running month
    (the archive returns nothing for a date in the future)."""
    last = dt.date(year + month // 12, month % 12 + 1, 1) - dt.timedelta(days=1)
    return min(last, today or dt.datetime.now(IST).date())


def fetch_fpi_month(year: int, month: int, session: requests.Session, today: dt.date = None) -> dict:
    """Every reporting day of one month from NSDL's archive (an ASP.NET form: GET for the tokens, then post the date)."""
    last = archive_date(year, month, today)
    page = session.get(NSDL_ARCHIVE, timeout=60)
    page.raise_for_status()
    form = dict(re.findall(r'<input type="hidden" name="(__[A-Z]+)" id="[^"]*" value="([^"]*)"', page.text))
    form.update({"__EVENTTARGET": "btnSubmit1", "__EVENTARGUMENT": "", "txtDate": "", "hdnDate": last.strftime("%d-%b-%Y"),
                 "HdnValexceldata": "", "hdnFlag": ""})
    r = session.post(NSDL_ARCHIVE, data=form, timeout=120)
    r.raise_for_status()
    prefix = f"{year:04d}-{month:02d}-"
    return {d: v for d, v in parse_archive(r.text).items() if d.startswith(prefix)}


def update_fpi(db_path: Path = None, today: dt.date = None, pause: float = 1.0, log=print, progress=None):
    """Fetch the months not in the database yet, and refresh the last two if fetched over 6 hours ago.
    progress() is called after every 12 months fetched, so a first backfill shows up while it runs."""
    today = today or dt.datetime.now(IST).date()
    prev = today.replace(day=1) - dt.timedelta(days=1)
    recent = {f"{today:%Y-%m}", f"{prev:%Y-%m}"}
    with LOCK, closing(connect(db_path)) as db:
        done = dict(db.execute("SELECT month, fetched_at FROM fpi_months").fetchall())
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    y, m = FPI_START
    fetched = failed = 0
    while (y, m) <= (today.year, today.month):
        month = f"{y:04d}-{m:02d}"
        if month not in done or (month in recent and time.time() - done[month] > FPI_REFRESH_SECONDS):
            try:
                rows = fetch_fpi_month(y, m, session, today)
                if rows or month in recent:          # an empty finished month means a failed page: retry next time
                    with LOCK, closing(connect(db_path)) as db:
                        db.execute("DELETE FROM fpi_daily WHERE date LIKE ?", (month + "-%",))
                        db.executemany("INSERT INTO fpi_daily VALUES (?,?,?,?,?,?,?,?)", [[d] + v for d, v in sorted(rows.items())])
                        db.execute("INSERT OR REPLACE INTO fpi_months VALUES (?,?,?)", (month, time.time(), len(rows)))
                        db.commit()
                fetched += 1
                if progress and fetched % 12 == 0:
                    progress()
            except Exception as e:                   # NSDL down or slow: keep what's saved, retry next run
                failed += 1
                log(f"  NSDL FPI {month}: {type(e).__name__}: {e}")
            time.sleep(pause)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return fetched, failed


# ---------- the published file and the seed ----------
def publish(out_path: Path = None, db_path: Path = None) -> dict:
    with LOCK, closing(connect(db_path)) as db:
        nse = [list(r) for r in db.execute(f"SELECT {', '.join(NSE_FIELDS)} FROM nse_daily ORDER BY date")]
        fpi = [list(r) for r in db.execute(f"SELECT {', '.join(FPI_FIELDS)} FROM fpi_daily ORDER BY date")]
    payload = {"generated": _now(), "nse": {"fields": NSE_FIELDS, "rows": nse}, "fpi": {"fields": FPI_FIELDS, "rows": fpi}}
    out = Path(out_path or OUT_PATH)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, out)
    return payload


def write_seed(seed_path: Path = None, db_path: Path = None) -> int:
    """fiidii_seed.db for dist: the NSDL tables, plus full NSE rows (source 'nse') to fill gaps on the server."""
    seed = Path(seed_path or SEED_PATH)
    seed.unlink(missing_ok=True)
    with LOCK, closing(connect(db_path)) as db:
        db.execute("ATTACH DATABASE ? AS seed", (str(seed),))
        db.executescript("""CREATE TABLE seed.fpi_daily AS SELECT * FROM fpi_daily;
                            CREATE TABLE seed.fpi_months AS SELECT * FROM fpi_months;
                            CREATE TABLE seed.nse_daily AS SELECT * FROM nse_daily WHERE source = 'nse';""")
        n = db.execute("SELECT COUNT(*) FROM seed.fpi_daily").fetchone()[0]
        db.commit()
        db.execute("DETACH DATABASE seed")
    return n


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
    if "--seed" in sys.argv:
        print(f"Wrote {SEED_PATH} with {write_seed()} NSDL days")
        sys.exit(0)
    fetch = None
    if "--nse" in sys.argv:
        import market_reel
        fetch = market_reel.fetch_fiidii
    print(nightly(fetch))
