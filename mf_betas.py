#!/usr/bin/env python3
"""
mf_betas.py  -  Let Money Earn: weekly mutual fund beta builder for the Portfolio Beta tool.

Kept apart from the stock betas (betas.py / betas.json): writes data/mf_betas.json, which the page
downloads only when a pasted row looks like a mutual fund.

Each fund's beta comes from its own daily NAVs (no portfolio holdings needed), against the same
benchmark and window as the stocks, so stock and fund betas add up in one portfolio:
    daily return = NAV / previous trading day's NAV - 1   (NAVs read on NIFTYBEES's trading days)
    beta = cov(fund, NIFTYBEES) / var(NIFTYBEES)          (betas.compute, unchanged)

Source: AMFI's NAV history download (one file per month for every scheme, with ISIN and category).
Only open-ended Growth plans are kept: IDCW/dividend NAVs drop on payout days and would look like falls.
Completed months are cached (gzip) in AMFI_NAV_CACHE_DIR and never downloaded again.

Run by hand (after betas.py, whose bhavcopy cache it reads for the benchmark):
    py mf_betas.py

Paths come from environment variables, defaulting to the folder the server runs from:
    MF_BETA_JSON_PATH   data/mf_betas.json
    AMFI_NAV_CACHE_DIR  var/amfi_nav_cache
Runs are logged in betas.db, table mf_beta_runs.

Requires: pandas, requests
"""

import argparse
import datetime as dt
import gzip
import os
import re
import sys
from pathlib import Path

import pandas as pd
import requests

import betas

ROOT = betas.ROOT
MF_BETA_JSON_PATH = Path(os.environ.get("MF_BETA_JSON_PATH") or ROOT / "data" / "mf_betas.json")
AMFI_NAV_CACHE_DIR = Path(os.environ.get("AMFI_NAV_CACHE_DIR") or ROOT / "var" / "amfi_nav_cache")
AMFI_URL = "https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx?frmdt={start}&todt={end}"
AMFI_HEADERS = {"User-Agent": betas.HEADERS["User-Agent"]}

MIN_FUNDS = 1500                # sanity check: fewer funds with a beta than this keeps the old file
MAX_ABS_RET = 0.15              # a fund NAV moving 15% in a day is a data error (equity funds fell ~13% at worst in March 2020)
MONTH_FINAL_AFTER_DAYS = 7      # AMFI can correct late NAVs; a month's cached file is final once fetched this long after it ends
RUN_TABLE = "mf_beta_runs"

NOT_GROWTH = re.compile(r"idcw|income distribution|dividend|bonus|payout|reinvest|unclaimed|segregated", re.I)
# NAVs struck on overseas markets lag Nifty by a day, so their betas read too low: the page flags them
OVERSEAS = re.compile(r"overseas|nasdaq|s&p ?500|\bus\b|u\.s\.|global|international|world|greater china|"
                      r"hang seng|japan|taiwan|emerging market|europe|fang|developed market", re.I)


def month_file(cache: Path, year: int, month: int) -> Path:
    return cache / f"nav_{year}{month:02d}.txt.gz"


def fetch_month(year: int, month: int, cache: Path, today: dt.date, session: requests.Session) -> str:
    """One month of every scheme's NAVs as AMFI's ';'-separated text. A month that ended more than
    MONTH_FINAL_AFTER_DAYS before its cached copy was saved is read from the cache."""
    first = dt.date(year, month, 1)
    last = (first + dt.timedelta(days=32)).replace(day=1) - dt.timedelta(days=1)
    f = month_file(cache, year, month)
    if f.exists():
        saved = dt.date.fromtimestamp(f.stat().st_mtime)
        if saved > last + dt.timedelta(days=MONTH_FINAL_AFTER_DAYS):
            return gzip.decompress(f.read_bytes()).decode("utf-8", "replace")
    r = session.get(AMFI_URL.format(start=first.strftime("%d-%b-%Y"), end=min(last, today).strftime("%d-%b-%Y")),
                    headers=AMFI_HEADERS, timeout=300)
    r.raise_for_status()
    text = r.content.decode("utf-8", "replace")
    if "Scheme Code" not in text[:200]:
        raise ValueError(f"AMFI NAV history for {first:%b %Y} came back in an unexpected format.")
    cache.mkdir(parents=True, exist_ok=True)
    f.write_bytes(gzip.compress(text.encode("utf-8")))
    return text


def parse_navs(text: str) -> pd.DataFrame:
    """Rows (code, name, isin, cat, date, nav) for open-ended Growth plans. AMFI's file interleaves
    category lines ("Open Ended Schemes ( Equity Scheme - Large Cap Fund )"), fund-house lines and
    data lines "code;name;plan;option;isin growth/payout;isin reinvest;nav;date"."""
    rows, cat = [], None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("Scheme Code"):
            continue
        if ";" not in line:
            m = re.match(r"(Open Ended|Close Ended|Interval Fund)\s*Schemes?\s*\(\s*(.*?)\s*\)\s*$", line, re.I)
            if m:
                cat = m.group(2) if m.group(1).lower() == "open ended" else None
            continue
        parts = line.split(";")
        if cat is None or len(parts) < 8 or not parts[0].strip().isdigit():
            continue
        name = parts[1].strip()
        if "growth" not in name.lower() or NOT_GROWTH.search(name):
            continue
        try:
            nav = float(parts[6])
            day = dt.datetime.strptime(parts[7].strip(), "%d-%b-%Y").date()
        except ValueError:
            continue
        if nav > 0:
            rows.append((parts[0].strip(), name, parts[4].strip() or parts[5].strip(), cat, day, nav))
    return pd.DataFrame(rows, columns=["code", "name", "isin", "cat", "date", "nav"])


def collect_navs(start: dt.date, end: dt.date, cache: Path) -> pd.DataFrame:
    session = requests.Session()
    frames, month = [], start.replace(day=1)
    while month <= end:
        print(f"  AMFI NAVs for {month:%b %Y}")
        frames.append(parse_navs(fetch_month(month.year, month.month, cache, end, session)))
        month = (month + dt.timedelta(days=32)).replace(day=1)
    navs = pd.concat(frames, ignore_index=True)
    navs["date"] = pd.to_datetime(navs["date"])
    return navs.drop_duplicates(["code", "date"], keep="last")


def fund_returns(navs: pd.DataFrame, bench: pd.DataFrame) -> pd.DataFrame:
    """Rows shaped like betas.collect's (sym, close, ret, date) for each fund, plus the benchmark's own
    rows. A fund's NAVs are read on the benchmark's trading days, so each return covers the same
    interval as the benchmark's; a day either side of a missing NAV gives no return."""
    days = pd.DatetimeIndex(sorted(bench["date"].unique()))
    wide = navs.pivot_table(index="date", columns="code", values="nav").reindex(days)
    rets = (wide / wide.shift(1) - 1).iloc[1:]
    long = rets.stack().rename("ret").reset_index()
    long.columns = ["date", "sym", "ret"]
    close = wide.stack().rename("close").reset_index()
    close.columns = ["date", "sym", "close"]
    funds = long.merge(close, on=["date", "sym"])
    bench = bench[bench["date"] > days[0]][["date", "sym", "ret", "close"]]
    return pd.concat([funds, bench], ignore_index=True)


def build(out: Path = None, nav_cache: Path = None, bhav_cache: Path = None, end: dt.date = None,
          days: int = 250, min_obs: int = 120, benchmark: str = "NIFTYBEES", db_path: Path = None):
    """Collect, compute, check and publish mf_betas.json; every run is logged in mf_beta_runs.
    Raises betas.BetaBuildError when a sanity check fails; the previous file is then left untouched."""
    out, nav_cache = Path(out or MF_BETA_JSON_PATH), Path(nav_cache or AMFI_NAV_CACHE_DIR)
    bhav_cache = Path(bhav_cache or betas.BHAVCOPY_CACHE_DIR)
    end = end or dt.datetime.now(betas.IST).date()
    bench_sym = benchmark.upper()
    started = dt.datetime.now(betas.IST).isoformat(timespec="seconds")
    asof = ndays = None
    funds = {}
    status, message = "failed", "interrupted"
    try:
        print(f"Collecting {bench_sym} for {days} trading days up to {end} ...")
        try:
            stock_data = betas.collect(days, bhav_cache, end)
        except SystemExit as e:
            raise betas.BetaBuildError(str(e)) from None
        bench = stock_data[stock_data["sym"] == bench_sym]
        if bench.empty:
            raise betas.BetaBuildError(f"Benchmark {bench_sym} is missing from the collected bhavcopy files.")
        first = bench["date"].min().date()
        print(f"Collecting AMFI NAVs from {first} ...")
        navs = collect_navs(first - dt.timedelta(days=10), end, nav_cache)
        if navs.empty:
            raise betas.BetaBuildError("No NAVs could be read from AMFI.")
        stats, asof, ndays = betas.compute(fund_returns(navs, bench), bench_sym, min_obs, MAX_ABS_RET)
        stats.pop(bench_sym, None)
        if ndays < betas.MIN_DAYS:
            raise betas.BetaBuildError(f"Only {ndays} trading days collected (need {betas.MIN_DAYS}).")
        if len(stats) < MIN_FUNDS:
            raise betas.BetaBuildError(f"Only {len(stats)} funds got a beta (need {MIN_FUNDS}).")
        info = navs.sort_values("date").groupby("code").tail(1).set_index("code")
        cats = sorted(info.loc[list(stats), "cat"].unique())
        cat_index = {c: i for i, c in enumerate(cats)}
        for code, st in stats.items():
            name, isin, cat = info.at[code, "name"], info.at[code, "isin"], info.at[code, "cat"]
            fund = {"name": name, "isin": isin, "c": cat_index[cat], **st}
            if "fof overseas" in cat.lower() or OVERSEAS.search(name):
                fund["x"] = 1
            funds[code] = fund
        payload = {"asof": asof.isoformat(), "benchmark": bench_sym, "window_days": ndays,
                   "count": len(funds), "cats": cats, "funds": funds}
        betas.write_atomic(out, payload)
        print(f"Wrote {len(funds)} fund betas to {out} (as of {asof}, {ndays} days)")
        status, message = "ok", ""
        return payload
    except Exception as e:
        status, message = "failed", f"{type(e).__name__}: {e}"
        print(f"Fund beta build failed, previous {out.name} kept: {message}")
        raise
    finally:
        with betas.run_log(db_path, RUN_TABLE) as database:
            database.execute(
                f"INSERT INTO {RUN_TABLE} (started_at, finished_at, status, asof, stocks, days, message) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (started, dt.datetime.now(betas.IST).isoformat(timespec="seconds"), status,
                 asof.isoformat() if asof else None, len(funds), ndays, message))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(MF_BETA_JSON_PATH))
    ap.add_argument("--nav-cache-dir", default=str(AMFI_NAV_CACHE_DIR))
    ap.add_argument("--days", type=int, default=250, help="trading days (~1 year)")
    ap.add_argument("--min-obs", type=int, default=120)
    ap.add_argument("--end", help="YYYY-MM-DD, default today (IST)")
    a = ap.parse_args()
    try:
        build(Path(a.out), Path(a.nav_cache_dir), end=dt.date.fromisoformat(a.end) if a.end else None,
              days=a.days, min_obs=a.min_obs)
    except Exception:
        sys.exit(1)


if __name__ == "__main__":
    main()
