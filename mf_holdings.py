#!/usr/bin/env python3
"""
mf_holdings.py  -  Let Money Earn: monthly mutual fund holdings for the Fund Holdings Explorer (mf-holdings.html).

SEBI makes every fund house publish each scheme's full portfolio as of month-end by the 10th of the next
month. AMFI only links to those files, so this job downloads them from the fund houses' own sites
(the requests their disclosure pages make), parses them and publishes:

    data/mf_holdings/index.json      every scheme: id, name, fund house, as-of date, AMFI codes, counts
    data/mf_holdings/f/<id>.json     one scheme's holdings (ISIN, name, sector, kind, weight %)
    data/mf_holdings/stocks.json     ISIN -> name, sector and [scheme id, weight %] for "which funds hold it"

Covered: SBI, ICICI Prudential, HDFC, Nippon India, Aditya Birla Sun Life, Axis, UTI, Mirae Asset, DSP,
PPFAS and Motilal Oswal. (Kotak is left out: its site puts automated visitors behind a CAPTCHA.)

All the files follow SEBI's standard layout (instrument, ISIN, industry/rating, quantity, market value,
% to NAV), so one parser reads them all: it finds each header row, maps columns by name, and takes the
rows with an ISIN below it. A fund house that fails one month keeps its last good month (each scheme
shows its own as-of date); the job publishes only if enough fund houses parse.

The server runs it on the 15th of each month (app.py: build_mf_holdings_monthly). By hand:
    py mf_holdings.py                 # latest month-end
    py mf_holdings.py --month 2026-08

Paths: MF_HOLDINGS_DIR (data/mf_holdings), MF_HOLDINGS_CACHE_DIR (var/mf_holdings). Runs are logged in
betas.db, table mf_holdings_runs.

Requires: pandas, requests, openpyxl, xlrd
"""

import argparse
import calendar
import datetime as dt
import io
import json
import os
import re
import shutil
import sys
import time
import urllib.parse
import uuid
import zipfile
from pathlib import Path

import pandas as pd
import requests

import betas

ROOT = betas.ROOT
MF_HOLDINGS_DIR = Path(os.environ.get("MF_HOLDINGS_DIR") or ROOT / "data" / "mf_holdings")
MF_HOLDINGS_CACHE_DIR = Path(os.environ.get("MF_HOLDINGS_CACHE_DIR") or ROOT / "var" / "mf_holdings")
RUN_TABLE = "mf_holdings_runs"
MIN_FUND_HOUSES = 8            # publish only if at least this many fund houses have data (fresh or last good)
MIN_SCHEMES_PER_HOUSE = 5      # a fund house's parse counts only with at least this many schemes
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

AMCS = {
    "sbi": "SBI Mutual Fund", "icici": "ICICI Prudential Mutual Fund", "hdfc": "HDFC Mutual Fund",
    "nippon": "Nippon India Mutual Fund", "absl": "Aditya Birla Sun Life Mutual Fund", "axis": "Axis Mutual Fund",
    "uti": "UTI Mutual Fund", "mirae": "Mirae Asset Mutual Fund", "dsp": "DSP Mutual Fund",
    "ppfas": "PPFAS Mutual Fund", "motilal": "Motilal Oswal Mutual Fund",
}


class HoldingsError(Exception):
    """A fund house's files for the month couldn't be found, downloaded or parsed."""


# ---------- finding each fund house's files for a month ----------
# Each returns [(url, label)] for the month ending on `month_end`, or [] if not published yet.

def _months(month_end):
    full, abbr = month_end.strftime("%B"), month_end.strftime("%b")
    return full, abbr, str(month_end.year), month_end.strftime("%y")


def _sbi(s, month_end):
    full, _, year, _ = _months(month_end)
    r = s.post("https://www.sbimf.com/ajaxcall/CMS/GetSchemePortfolioSheets",
               json={"FundId": "", "PSYear": "", "PSMonth": "", "PSFrequency": "Monthly"},
               headers={"Referer": "https://www.sbimf.com/portfolios", "X-Requested-With": "XMLHttpRequest"}, timeout=60)
    r.raise_for_status()
    links = re.findall(r'href="([^"]+\.xlsx?[^"]*)"[^>]*>([^<]+)<', r.text)
    return [(u, t) for u, t in links if re.search(rf"all schemes monthly portfolio.*{full}\s+{year}", t, re.I)][:1]


def _icici(s, month_end):
    full, _, year, _ = _months(month_end)
    r = s.post("https://apimf.icicipruamc.com/nms/v1/downloads/files", timeout=60,
               headers={"Referer": "https://www.icicipruamc.com/", "Origin": "https://www.icicipruamc.com",
                        "requestapiid": str(uuid.uuid4()), "sourceurl": "DOWNLOADS", "env": "api"},
               json={"categoryId": "26a073d7-08d2-4a95-95fa-f83a4ee51e40", "schemeCategory": "", "userType": "Investor",
                     "fileType": "All", "page": "1", "size": "24", "filter": [], "categoryName": "OTHERS"})
    r.raise_for_status()
    files = r.json()["success"]["data"]["files"]
    # file paths are served from /blob on the main site (the /downloads redirect goes to a host that doesn't resolve)
    return [("https://www.icicipruamc.com/blob" + urllib.parse.quote(f["url"]), f["title"]["text"]) for f in files
            if re.fullmatch(rf"monthly portfolio disclosure {full} {year}", f["title"]["text"].strip(), re.I)][:1]


def _hdfc(s, month_end):
    r = s.post("https://cms.hdfcfund.com/en/hdfc/api/v2/disclosures/monthfortportfolio", timeout=60,
               files={"year": (None, str(month_end.year)), "type": (None, "monthly"), "month": (None, str(month_end.month))},
               headers={"Origin": "https://www.hdfcfund.com", "Referer": "https://www.hdfcfund.com/"})
    r.raise_for_status()
    files = (r.json().get("data") or {}).get("files") or []
    return [(f["file"]["url"], f["title"]) for f in files
            if f["title"].lower().startswith("monthly") and "overlap" not in f["title"].lower()]


def _nippon(s, month_end):
    _, abbr, year, yy = _months(month_end)
    r = s.get("https://mf.nipponindiaim.com/investor-service/downloads/factsheet-portfolio-and-other-disclosures", timeout=60)
    r.raise_for_status()
    links = set(re.findall(r'href="([^"]*MONTHLY-PORTFOLIO[^"]*\.xlsx?)"', r.text, re.I))
    hits = [u for u in links if "FORTNIGHTLY" not in u.upper() and re.search(rf"{abbr}[a-z]*[-_ ]*({yy}|{year})\b", u, re.I)]
    return [("https://mf.nipponindiaim.com" + u if u.startswith("/") else u, u.rsplit("/", 1)[-1]) for u in sorted(hits)][:1]


def _absl(s, month_end):
    full, _, year, _ = _months(month_end)
    r = s.get("https://mutualfund.adityabirlacapital.com/postlogin/CustomApi/Resources/FactsheetAccordionById", timeout=60,
              params={"id": "3ccab227-9de5-4494-b78d-2b4f7c0c054a",
                      "ctype": "/sitecore/content/Root/BSL/Library/Lists/FAQ/Customer Types/Individual", "month": " ", "year": "0"},
              headers={"Referer": "https://mutualfund.adityabirlacapital.com/forms-and-downloads/portfolio", "X-Requested-With": "XMLHttpRequest"})
    r.raise_for_status()
    out = []
    for item in r.json().get("AccordionList", []):
        if re.search(rf"monthly portfolios? as on {full} \d+, {year}", item.get("ResourceLink", ""), re.I):
            # the CDN host in pdfUrl doesn't resolve everywhere; the same path is served from the main site
            path = urllib.parse.urlparse(item["pdfUrl"]).path
            out.append(("https://mutualfund.adityabirlacapital.com" + path, item["ResourceLink"]))
    return out[:1]


def _axis(s, month_end):
    full, _, year, _ = _months(month_end)
    head = {"Referer": "https://www.axismf.com/statutory-disclosures", "Content-Type": "application/json", "browser-id": str(uuid.uuid4())}
    token = s.post("https://www.axismf.com/cms/token", json={}, headers={**head, "Authorization": ""}, timeout=60).json()["data"]["token"]
    r = s.post("https://www.axismf.com/cms/get-scheme-documents", headers={**head, "Authorization": token}, timeout=60,
               json={"sdType": "yearMonthSchemeDocs", "sdID": "sdMonthSchemePortfolio", "year": year, "month": full, "schemeCode": "Consolidated"})
    r.raise_for_status()
    docs = (r.json().get("data") or {}).get("documentList") or []
    return [(d["docuementURL"], d["documentName"]) for d in docs if d.get("documentName", "").lower().startswith("monthly portfolio")][:1]


def _uti(s, month_end):
    full, _, year, _ = _months(month_end)
    r = s.get("https://www.utimf.com/api/get-consolidate-portfolio-disclosure", params={"year": year, "month": full}, timeout=60)
    r.raise_for_status()
    return [(row["url"], row["name"]) for row in (r.json().get("rows") or [])][:1]


def _mirae(s, month_end):
    full, _, year, _ = _months(month_end)
    r = s.post("https://www.miraeassetmf.co.in/AjaxService/GetDownloadsData", timeout=60,
               json={"request": {"modulename": "portfolio_tab1", "pgno": 1, "pgsize": 400}},
               headers={"Referer": "https://www.miraeassetmf.co.in/downloads/portfolio", "X-Requested-With": "XMLHttpRequest"})
    r.raise_for_status()
    return [(urllib.parse.urljoin("https://www.miraeassetmf.co.in/", d["URL"]), d["Title"]) for d in r.json().get("Data", [])
            if re.search(rf"as on \d+\w* {full} {year}", d["Title"], re.I)]


def _dsp(s, month_end):
    _, abbr, year, _ = _months(month_end)
    r = s.get("https://www.dspim.com/mandatory-disclosures/portfolio-disclosures", timeout=60)
    r.raise_for_status()
    links = set(re.findall(r'href="([^"]*monthend-portfolio-as-on-\d+-[^"]*\.zip)"', r.text, re.I))
    return [(u, u.rsplit("/", 1)[-1]) for u in sorted(links) if re.search(rf"-{abbr.lower()}[a-z]*-{year}\.zip$", u.lower())][:1]


def _ppfas(s, month_end):
    full, _, year, _ = _months(month_end)
    r = s.get("https://amc.ppfas.com/downloads/portfolio-disclosure/", timeout=60)
    r.raise_for_status()
    links = set(re.findall(r'href="([^"]*Monthly_Portfolio_Report_[^"]*\.xlsx?)(?:\?[^"]*)?"', r.text, re.I))
    return [("https://amc.ppfas.com" + u if u.startswith("/") else u, u.rsplit("/", 1)[-1]) for u in sorted(links)
            if re.search(rf"{full}_\d+_{year}", u, re.I)]


def _motilal(s, month_end):
    full, abbr, year, _ = _months(month_end)
    r = s.get("https://www.motilaloswalmf.com/content/aem-cloud-dept-backend-motilal-oswal/api/search-documents.json",
              params={"year": "", "category": "month end portfolio", "month": "", "type": "mf"}, timeout=60)
    r.raise_for_status()
    return [("https://www.motilaloswalmf.com" + urllib.parse.quote(d["path"]), d["title"]) for d in r.json().get("results", [])
            if re.fullmatch(rf"scheme portfolio details ({full}|{abbr}) {year}", d["title"].strip(), re.I)][:1]


FINDERS = {"sbi": _sbi, "icici": _icici, "hdfc": _hdfc, "nippon": _nippon, "absl": _absl, "axis": _axis,
           "uti": _uti, "mirae": _mirae, "dsp": _dsp, "ppfas": _ppfas, "motilal": _motilal}


# ---------- reading the workbooks ----------

HEADER_PCT = re.compile(r"%\s*(to|of)\s*(nav|net|aum)", re.I)
ISIN_RX = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
NAME_SKIP = re.compile(r"mutual fund\s*$|asset management|registered office|portfolio statement|monthly portfolio|"
                       r"an open[- ]?ended|back to index|^\(|cin\b|investment manager|as on\b|^index$|half yearly|unaudited|"
                       r"^total\b|^grand total|^sub ?total|^net assets|^\*|in case of|funds management|pvt\.? ?l|"
                       r"private limited|regulations|scheme code", re.I)
NAME_HINT = re.compile(r"fund|plan|etf|fof|scheme|savings|portfolio|index|series|insurance|gilt|liquid", re.I)


def _text(v):
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()


def _num(v):
    try:
        x = float(str(v).replace(",", "").strip())
        return None if pd.isna(x) else x
    except ValueError:
        return None


def _columns(row):
    """Map a header row's cells to the fields we read."""
    cols = {}
    for i, cell in enumerate(row):
        t = _text(cell).lower()
        if not t:
            continue
        if "isin" in t and "isin" not in cols:
            cols["isin"] = i
        elif HEADER_PCT.search(t) and "pct" not in cols:
            cols["pct"] = i
        elif re.search(r"name of (the )?instrument|instrument|security name|company|issuer", t) and "name" not in cols:
            cols["name"] = i
        elif re.search(r"industry|rating", t) and "industry" not in cols:
            cols["industry"] = i
        elif re.search(r"market|fair value|value", t) and "value" not in cols:
            cols["value"] = i
    return cols if {"isin", "pct", "name"} <= cols.keys() else None


def _scheme_name(rows_above, fallback):
    """The scheme's name from the rows just above its header: the nearest cell that looks like a fund name."""
    for row in reversed(rows_above):
        if any(ISIN_RX.match(_text(c).upper()) for c in row):      # a holding of the scheme above, not a title
            continue
        for cell in row:
            t = re.sub(r"\s+", " ", _text(cell))
            t = re.sub(r"^scheme( name)?\s*:\s*", "", t, flags=re.I)
            # drop descriptions like "(An open ended ...)" or "(Formerly known as ...)", keep "(FMP) - Series 1 (3668 Days)"
            t = re.sub(r"\s*\((an?|open|close|interval|formerly|erstwhile|earlier)\b.*$", "", t, flags=re.I).strip(" .-")
            if (len(t) < 6 or len(t) > 110 or " " not in t or not re.search(r"[A-Za-z]{3}", t)   # sheet codes like GOLDETF
                    or NAME_SKIP.search(t) or not NAME_HINT.search(t)):
                continue
            return t
    return None


def _section(text, current):
    t = text.lower()
    if re.search(r"derivative|futures?|options?\b", t):
        return "derivative"
    if re.search(r"foreign|overseas|international|adr|gdr", t) and re.search(r"equit|share|securit", t):
        return "foreign"
    if re.search(r"equity|shares", t):
        return "equity"
    if re.search(r"reit|invit", t):
        return "reit"
    if re.search(r"mutual fund|units of|exchange traded|etf", t):
        return "fund"
    if re.search(r"debt|bond|debenture|money market|certificate of deposit|commercial paper|treasury|t-bill|government|"
                 r"g-sec|state development|securitised|ptc|treps|reverse repo|tri-party|cash|net current", t):
        return "debt"
    return current


def parse_sheet(df, fallback_name):
    """Every scheme block in one sheet: [{name, holdings: [{isin, name, industry, kind, value, pct}]}]."""
    rows = df.values.tolist()
    blocks = []
    headers = [i for i, row in enumerate(rows) if _columns(row)]
    for n, h in enumerate(headers):
        cols = _columns(rows[h])
        end = headers[n + 1] if n + 1 < len(headers) else len(rows)
        prev = headers[n - 1] + 1 if n else 0
        name = _scheme_name(rows[max(prev, h - 14):h], fallback_name)
        section, holdings = "equity", []
        for row in rows[h + 1:end]:
            isin = _text(row[cols["isin"]]).upper() if cols["isin"] < len(row) else ""
            if not ISIN_RX.match(isin):
                label = " ".join(_text(c) for c in row if _text(c))[:120]
                if label and not re.search(r"\d{4,}", label.replace(" ", "")):
                    section = _section(label, section)
                if re.search(r"^grand total|^net assets|^total net assets", label.lower()):
                    break
                continue
            pct = _num(row[cols["pct"]]) if cols["pct"] < len(row) else None
            if pct is None:
                continue
            raw_name = _text(row[cols["name"]])
            kind = "foreign" if not isin.startswith("IN") and section == "equity" else section
            if re.search(r"\b(invit|reit)s?\b", raw_name, re.I):          # UTI lists InvIT units inside its equity section
                kind = "reit"
            holdings.append({
                "isin": isin,
                "name": re.sub(r"^(EQ|INVIT|REIT)\s*-\s*", "", raw_name, flags=re.I),
                "industry": _text(row[cols["industry"]]) if "industry" in cols else "",
                "kind": kind,
                "value": _num(row[cols["value"]]) if "value" in cols else None,
                "pct": pct,
            })
        if not holdings:
            continue
        if name is None and blocks:            # a second table in the same scheme's sheet (e.g. defaulted securities)
            blocks[-1]["holdings"] += holdings
        else:
            blocks.append({"name": name or fallback_name, "holdings": holdings})
    return blocks


def _normalise_weights(scheme):
    """Weights as % of NAV: some files give 9.57, others 0.0957."""
    total = sum(abs(h["pct"]) for h in scheme["holdings"])
    scale = 100 if total <= 2.5 else 1
    for h in scheme["holdings"]:
        h["pct"] = round(h["pct"] * scale, 4)
    return scheme


def parse_workbook(data: bytes, label: str):
    """All schemes in one workbook (xls or xlsx). Sheets without a SEBI-style header are skipped
    (index sheets, risk-o-meters, dividend tables)."""
    try:
        sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, header=None, dtype=object)
    except Exception as e:
        raise HoldingsError(f"{label}: unreadable workbook ({type(e).__name__}: {e})") from None
    schemes = []
    for sheet, df in sheets.items():
        if df.empty:
            continue
        for block in parse_sheet(df, sheet):
            schemes.append(_normalise_weights(block))
    return schemes


def parse_file(data: bytes, label: str):
    """A downloaded file: an Excel workbook, or a zip of them."""
    if data[:2] == b"PK" and _is_plain_zip(data):
        schemes = []
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for name in z.namelist():
                low = name.lower()
                if low.endswith((".xls", ".xlsx")) and not re.search(r"divmast|fut disclo|risk-o-meter|riskometer|overlap", low):
                    schemes += parse_workbook(z.read(name), name)
        return schemes
    return parse_workbook(data, label)


def _is_plain_zip(data):
    """xlsx files are zips too; a plain zip has no [Content_Types].xml at its root."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return "[Content_Types].xml" not in z.namelist()
    except zipfile.BadZipFile:
        return False


# ---------- matching schemes to AMFI codes ----------

CODE_STOP = {"fund", "plan", "direct", "regular", "growth", "option", "the", "scheme", "an", "open", "ended", "mutual",
             "of", "and", "ltd", "limited", "mf"}


def name_key(name: str) -> str:
    t = name.lower().replace("&", " and ")
    t = re.sub(r"\(.*?\)", " ", t)
    t = re.sub(r"\b(aditya birla sun life|absl)\b", "aditya birla sun life", t)
    t = re.sub(r"\b(icici pru)\b", "icici prudential", t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    t = re.sub(r"\b(small|mid|large|flexi|multi|micro) cap\b", r"\1cap", t)     # "Small Cap" = "Smallcap"
    return " ".join(w for w in t.split() if w not in CODE_STOP)


def amfi_codes(mf_betas_path: Path):
    """AMFI scheme codes by name key, from mf_betas.json (Growth plans; Direct and Regular share a key)."""
    try:
        funds = json.loads(Path(mf_betas_path).read_text(encoding="utf-8"))["funds"]
    except (OSError, ValueError, KeyError):
        return {}
    keys = {}
    for code, f in funds.items():
        keys.setdefault(name_key(f["name"]), []).append(code)
    return keys


# ---------- the build ----------

def last_month_end(today: dt.date) -> dt.date:
    return today.replace(day=1) - dt.timedelta(days=1)


def month_end_of(year: int, month: int) -> dt.date:
    return dt.date(year, month, calendar.monthrange(year, month)[1])


def fetch_house(amc: str, month_end: dt.date, session: requests.Session):
    """Download and parse one fund house's files for the month. Raises HoldingsError."""
    try:
        files = FINDERS[amc](session, month_end)
    except Exception as e:
        raise HoldingsError(f"listing failed: {type(e).__name__}: {e}") from None
    if not files:
        raise HoldingsError(f"no file for {month_end:%b %Y} yet")
    schemes = []
    for url, label in files:
        try:
            r = session.get(url, timeout=300, headers={"Referer": "https://www.google.com/"})
            r.raise_for_status()
        except Exception as e:
            raise HoldingsError(f"download failed ({label}): {type(e).__name__}: {e}") from None
        schemes += parse_file(r.content, urllib.parse.urlparse(url).path or label)
    seen, unique = set(), []
    for sc in schemes:                                   # the same scheme can appear in two files (e.g. DSP equity + debt)
        key = name_key(sc["name"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(sc)
    if len(unique) < MIN_SCHEMES_PER_HOUSE:
        raise HoldingsError(f"only {len(unique)} schemes parsed")
    return unique


def scheme_id(amc: str, name: str) -> str:
    return amc + "-" + re.sub(r"[^a-z0-9]+", "-", name_key(name)).strip("-")[:70]


def build(month_end: dt.date = None, out_dir: Path = None, cache_dir: Path = None, db_path: Path = None, houses=None):
    """Fetch every fund house for the month (default: last month-end), fall back to each one's last good
    month on failure, and publish the data folder in one swap. Returns the index payload."""
    month_end = month_end or last_month_end(dt.datetime.now(betas.IST).date())
    out_dir, cache_dir = Path(out_dir or MF_HOLDINGS_DIR), Path(cache_dir or MF_HOLDINGS_CACHE_DIR)
    started = dt.datetime.now(betas.IST).isoformat(timespec="seconds")
    status, message, notes, n_schemes = "failed", "interrupted", [], 0
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        session = requests.Session()
        session.headers.update({"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"})
        houses_data = {}
        for amc in AMCS:
            good = cache_dir / f"{amc}.json"
            try:
                if houses and amc not in houses:
                    raise HoldingsError("not fetched this run")
                schemes = fetch_house(amc, month_end, session)
                betas.write_atomic(good, {"asof": month_end.isoformat(), "schemes": schemes})
                houses_data[amc] = (month_end.isoformat(), schemes)
                print(f"  {amc}: {len(schemes)} schemes for {month_end:%b %Y}")
            except HoldingsError as e:
                try:
                    last = json.loads(good.read_text(encoding="utf-8"))
                    houses_data[amc] = (last["asof"], last["schemes"])
                    notes.append(f"{amc}: {e}; kept {last['asof']}")
                except (OSError, ValueError, KeyError):
                    # first run before the 10th (fund houses' deadline): nothing saved yet, so take the month before
                    prev = last_month_end(month_end)
                    try:
                        if houses and amc not in houses:
                            raise HoldingsError("not fetched this run")
                        schemes = fetch_house(amc, prev, session)
                        betas.write_atomic(good, {"asof": prev.isoformat(), "schemes": schemes})
                        houses_data[amc] = (prev.isoformat(), schemes)
                        notes.append(f"{amc}: {e}; used {prev:%b %Y}")
                    except HoldingsError as e2:
                        notes.append(f"{amc}: {e}; {prev:%b %Y}: {e2}; no earlier data")
                print(f"  {amc}: {e}" + (f"; used {houses_data[amc][0]}" if amc in houses_data else ""))
        if len(houses_data) < MIN_FUND_HOUSES:
            raise HoldingsError(f"only {len(houses_data)} fund houses have data (need {MIN_FUND_HOUSES})")

        codes_by_key = amfi_codes(Path(os.environ.get("MF_BETA_JSON_PATH") or ROOT / "data" / "mf_betas.json"))
        index, stocks, files = [], {}, {}
        for amc, (asof, schemes) in houses_data.items():
            for sc in schemes:
                sid = scheme_id(amc, sc["name"])
                if sid in files:
                    continue
                holdings = sorted(sc["holdings"], key=lambda h: -h["pct"])
                eq = [h for h in holdings if h["kind"] in ("equity", "foreign")]
                files[sid] = {"id": sid, "name": sc["name"], "amc": AMCS[amc], "asof": asof,
                              "holdings": [[h["isin"], h["name"], h["industry"], h["kind"], round(h["pct"], 3)] for h in holdings]}
                index.append({"id": sid, "name": sc["name"], "amc": AMCS[amc], "asof": asof,
                              "codes": codes_by_key.get(name_key(sc["name"]), []), "n": len(holdings),
                              "eq": round(sum(h["pct"] for h in eq), 1)})
                for h in eq:
                    st = stocks.setdefault(h["isin"], {"name": h["name"], "industry": h["industry"], "funds": []})
                    st["funds"].append([sid, round(h["pct"], 3)])
        n_schemes = len(index)
        index.sort(key=lambda f: (f["amc"], f["name"]))
        payload = {"generated": dt.datetime.now(betas.IST).isoformat(timespec="seconds"), "month_end": month_end.isoformat(),
                   "houses": {AMCS[a]: houses_data[a][0] for a in houses_data}, "count": n_schemes, "funds": index}
        publish(out_dir, payload, files, {"count": len(stocks), "stocks": stocks})
        print(f"Wrote {n_schemes} schemes from {len(houses_data)} fund houses to {out_dir} (month-end {month_end})")
        status, message = "ok", "; ".join(notes)
        return payload
    except Exception as e:
        status, message = "failed", f"{type(e).__name__}: {e}" + (f" | {'; '.join(notes)}" if notes else "")
        print(f"Fund holdings build failed, previous data kept: {message}")
        raise
    finally:
        with betas.run_log(db_path, RUN_TABLE) as database:
            database.execute(
                f"INSERT INTO {RUN_TABLE} (started_at, finished_at, status, asof, stocks, days, message) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (started, dt.datetime.now(betas.IST).isoformat(timespec="seconds"), status, month_end.isoformat(), n_schemes, None, message))


def publish(out_dir: Path, index: dict, files: dict, stocks: dict):
    """Write the whole folder beside the live one, then swap it in, so visitors never see a half-built set."""
    tmp, old = out_dir.with_name(out_dir.name + ".tmp"), out_dir.with_name(out_dir.name + ".old")
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / "f").mkdir(parents=True)
    for sid, data in files.items():
        (tmp / "f" / f"{sid}.json").write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    (tmp / "stocks.json").write_text(json.dumps(stocks, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    (tmp / "index.json").write_text(json.dumps(index, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    shutil.rmtree(old, ignore_errors=True)
    if out_dir.exists():
        _replace(out_dir, old)
    _replace(tmp, out_dir)
    shutil.rmtree(old, ignore_errors=True)


def _replace(src: Path, dst: Path, tries: int = 30):
    """os.replace, retried: on Windows antivirus or the search indexer briefly holds just-written files,
    and renaming their folder then fails with Access is denied."""
    for attempt in range(tries):
        try:
            return os.replace(src, dst)
        except PermissionError:
            if attempt == tries - 1:
                raise
            time.sleep(2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", help="YYYY-MM of the month-end to fetch (default: last month)")
    ap.add_argument("--only", nargs="*", help="fund houses to fetch, e.g. sbi hdfc (others keep their last good month)")
    a = ap.parse_args()
    month_end = month_end_of(*map(int, a.month.split("-"))) if a.month else None
    try:
        build(month_end, houses=a.only)
    except Exception:
        sys.exit(1)


if __name__ == "__main__":
    main()
