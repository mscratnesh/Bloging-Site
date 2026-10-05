#!/usr/bin/env python3
"""
betas.py  -  Let Money Earn: weekly beta builder for the Portfolio Beta tool (portfolio-beta.html).

Downloads NSE cash-market bhavcopy files (UDiFF format, public archives),
computes every stock's 1-year beta against a benchmark, and writes one small
betas.json that the web page reads. Only derived betas are published, never raw NSE prices.

Why returns come out corporate-action adjusted:
    daily return = ClsPric / PrvsClsgPric - 1
NSE adjusts PrvsClsgPric on the ex-date for splits/bonuses, so a 1:1 bonus
does NOT show up as a -50% day. No separate adjustment step is needed.

The site's server runs build() every Friday evening (app.py: build_betas_weekly). To run it by hand:
    py betas.py

Paths come from environment variables, defaulting to the folder the server runs from:
    BETA_JSON_PATH      data/betas.json            (served at /data/betas.json)
    BHAVCOPY_CACHE_DIR  var/bhavcopy_cache         (downloaded zips; pruned after 400 days)
    BETA_DB_PATH        betas.db                   (run log; its own file, never the blog's database)

Requires: pandas, requests
"""

import argparse
import contextlib
import datetime as dt
import io
import json
import os
import sqlite3
import sys
import time
import zipfile
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
BETA_JSON_PATH = Path(os.environ.get("BETA_JSON_PATH") or ROOT / "data" / "betas.json")
BHAVCOPY_CACHE_DIR = Path(os.environ.get("BHAVCOPY_CACHE_DIR") or ROOT / "var" / "bhavcopy_cache")
BETA_DB_PATH = Path(os.environ.get("BETA_DB_PATH") or ROOT / "betas.db")
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

# sanity checks: a build that fails any of these leaves the previous betas.json in place
MIN_DAYS = 200
MIN_STOCKS = 1000
CACHE_KEEP_DAYS = 400

URL = ("https://nsearchives.nseindia.com/content/cm/"
       "BhavCopy_NSE_CM_0_0_0_{d}_F_0000.csv.zip")
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"),
    "Referer": "https://www.nseindia.com/",
    "Accept": "*/*",
}
SERIES = {"EQ", "BE", "BZ"}          # equity + trade-for-trade; ETFs trade in EQ


class BetaBuildError(Exception):
    """The collected data failed a sanity check; betas.json was not touched."""


def fetch_day(day: dt.date, cache: Path, session: requests.Session):
    """Return the bhavcopy DataFrame for a day, or None on holidays/missing."""
    tag = day.strftime("%Y%m%d")
    f = cache / f"cm_{tag}.csv.zip"
    if not f.exists():
        r = session.get(URL.format(d=tag), headers=HEADERS, timeout=30)
        if r.status_code != 200 or len(r.content) < 1000:
            return None                       # holiday / weekend / not yet published
        f.write_bytes(r.content)
        time.sleep(0.4)                       # be polite to NSE
    with zipfile.ZipFile(f) as z:
        df = pd.read_csv(io.BytesIO(z.read(z.namelist()[0])))
    df.columns = [c.strip() for c in df.columns]
    df = df[df["SctySrs"].astype(str).str.strip().isin(SERIES)]
    out = pd.DataFrame({
        "sym": df["TckrSymb"].astype(str).str.strip().str.upper(),
        "close": pd.to_numeric(df["ClsPric"], errors="coerce"),
        "prev": pd.to_numeric(df["PrvsClsgPric"], errors="coerce"),
    }).dropna()
    out = out[(out["prev"] > 0) & (out["close"] > 0)]
    out["ret"] = out["close"] / out["prev"] - 1
    out["date"] = pd.Timestamp(day)
    # one row per symbol (if a symbol appears in two series, keep the bigger close row)
    return out.drop_duplicates("sym", keep="first")


def collect(days_needed: int, cache: Path, end: dt.date):
    cache.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.get("https://www.nseindia.com", headers=HEADERS, timeout=30)  # cookies
    frames, day, misses = [], end, 0
    while len(frames) < days_needed and misses < 40:
        if day.weekday() < 5:
            try:
                df = fetch_day(day, cache, s)
            except Exception as e:                       # network hiccup
                print(f"  {day} failed: {e}")
                df = None
            if df is not None and len(df):
                frames.append(df)
                misses = 0
                if len(frames) % 25 == 0:
                    print(f"  {len(frames)} trading days collected (at {day})")
            else:
                misses += 1
        day -= dt.timedelta(days=1)
    if not frames:
        raise SystemExit("No bhavcopy files could be read.")
    return pd.concat(frames, ignore_index=True)


def compute(data: pd.DataFrame, bench: str, min_obs: int, max_abs_ret: float):
    rets = data.pivot_table(index="date", columns="sym", values="ret").sort_index()
    if bench not in rets.columns:
        raise SystemExit(f"Benchmark {bench} not found in bhavcopy.")
    # drop absurd prints (data errors / relisting days) - not corporate actions,
    # those are already handled by PrvsClsgPric
    rets = rets.mask(rets.abs() > max_abs_ret)
    b = rets[bench]
    last = (data.sort_values("date").groupby("sym").tail(1)
                .set_index("sym")["close"])

    stocks = {}
    for sym in rets.columns:
        pair = pd.concat([rets[sym], b], axis=1, keys=["s", "b"]).dropna()
        n = len(pair)
        if n < min_obs or pair["b"].var() == 0:
            continue
        beta = pair["s"].cov(pair["b"]) / pair["b"].var()
        corr = pair["s"].corr(pair["b"])
        stocks[sym] = {"b": round(float(beta), 3),
                       "r2": round(float(corr ** 2), 3),
                       "p": round(float(last.get(sym, float("nan"))), 2),
                       "n": int(n)}
    return stocks, rets.index.max().date(), len(rets)


def prune_cache(cache: Path, today: dt.date, keep_days: int = CACHE_KEEP_DAYS):
    """Delete cached bhavcopy zips whose trading date is more than keep_days old."""
    cutoff = today - dt.timedelta(days=keep_days)
    removed = 0
    for f in cache.glob("cm_*.csv.zip"):
        try:
            day = dt.datetime.strptime(f.name[3:11], "%Y%m%d").date()
        except ValueError:
            continue
        if day < cutoff:
            f.unlink(missing_ok=True)
            removed += 1
    return removed


def write_atomic(path: Path, payload: dict):
    """Write the JSON beside its target, then swap it in, so a visitor never reads a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


@contextlib.contextmanager
def run_log(db_path: Path = None, table: str = "beta_runs"):
    """The run log: its own small SQLite file (never the blog's database). beta_runs logs the stock builds,
    mf_beta_runs the fund builds (mf_betas.py). The table is created on first use. Commits and closes on exit."""
    database = sqlite3.connect(db_path or BETA_DB_PATH)
    try:
        database.row_factory = sqlite3.Row
        database.execute(f"""CREATE TABLE IF NOT EXISTS {table} (
            id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, finished_at TEXT NOT NULL,
            status TEXT NOT NULL, asof TEXT, stocks INTEGER, days INTEGER, message TEXT DEFAULT ''
        )""")
        with database:
            yield database
    finally:
        database.close()


def last_success(db_path: Path = None, table: str = "beta_runs"):
    """The latest successful run (a sqlite3.Row with finished_at and asof), or None."""
    with run_log(db_path, table) as database:
        return database.execute(
            f"SELECT * FROM {table} WHERE status = 'ok' ORDER BY id DESC LIMIT 1").fetchone()


def build(out: Path = None, cache: Path = None, end: dt.date = None, days: int = 250, min_obs: int = 120,
          benchmark: str = "NIFTYBEES", max_abs_ret: float = 0.35, db_path: Path = None):
    """Collect, compute, check and publish betas.json. Every run (ok or failed) is recorded in beta_runs.
    Raises BetaBuildError when a sanity check fails; the previous betas.json is then left untouched."""
    out, cache = Path(out or BETA_JSON_PATH), Path(cache or BHAVCOPY_CACHE_DIR)
    end = end or dt.datetime.now(IST).date()
    bench = benchmark.upper()
    started = dt.datetime.now(IST).isoformat(timespec="seconds")
    asof = ndays = None
    stocks = {}
    status, message = "failed", "interrupted"
    try:
        print(f"Collecting {days} trading days up to {end} ...")
        try:
            data = collect(days, cache, end)
        except SystemExit as e:                      # collect's "nothing readable" exit
            raise BetaBuildError(str(e)) from None
        print(f"  pruned {prune_cache(cache, end)} cached files older than {CACHE_KEEP_DAYS} days")
        if bench not in set(data["sym"]):
            raise BetaBuildError(f"Benchmark {bench} is missing from the collected bhavcopy files.")
        stocks, asof, ndays = compute(data, bench, min_obs, max_abs_ret)
        if ndays < MIN_DAYS:
            raise BetaBuildError(f"Only {ndays} trading days collected (need {MIN_DAYS}).")
        if len(stocks) < MIN_STOCKS:
            raise BetaBuildError(f"Only {len(stocks)} stocks got a beta (need {MIN_STOCKS}).")
        payload = {"asof": asof.isoformat(), "benchmark": bench,
                   "window_days": ndays, "count": len(stocks), "stocks": stocks}
        write_atomic(out, payload)
        print(f"Wrote {len(stocks)} betas to {out} (as of {asof}, {ndays} days)")
        status, message = "ok", ""
        return payload
    except Exception as e:
        status, message = "failed", f"{type(e).__name__}: {e}"
        print(f"Beta build failed, previous {out.name} kept: {message}")
        raise
    finally:
        with run_log(db_path) as database:
            database.execute(
                "INSERT INTO beta_runs (started_at, finished_at, status, asof, stocks, days, message) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (started, dt.datetime.now(IST).isoformat(timespec="seconds"), status,
                 asof.isoformat() if asof else None, len(stocks), ndays, message))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(BETA_JSON_PATH))
    ap.add_argument("--cache-dir", default=str(BHAVCOPY_CACHE_DIR))
    ap.add_argument("--days", type=int, default=250, help="trading days (~1 year)")
    ap.add_argument("--min-obs", type=int, default=120,
                    help="skip stocks with fewer daily returns than this")
    ap.add_argument("--benchmark", default="NIFTYBEES",
                    help="symbol used as the market proxy (Nifty 50 ETF)")
    ap.add_argument("--max-abs-ret", type=float, default=0.35)
    ap.add_argument("--end", help="YYYY-MM-DD, default today (IST)")
    a = ap.parse_args()
    try:
        build(Path(a.out), Path(a.cache_dir), dt.date.fromisoformat(a.end) if a.end else None,
              a.days, a.min_obs, a.benchmark, a.max_abs_ret)
    except Exception:
        sys.exit(1)


if __name__ == "__main__":
    main()
