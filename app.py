from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import base64
import csv
import gzip
import html
import io
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
import http.client
import http.cookiejar
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from hmac import compare_digest

import market_reel
import momentum

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
DB_PATH = ROOT / "let_money_earn.db"
BREAKOUT_DATA_PATH = ROOT / "breakout_data.json"
HISTORY_CACHE_PATH = ROOT / "price_history_cache.json"
HISTORY_CACHE_TTL_SECONDS = 24 * 3600
HISTORY_SYMBOL_RE = re.compile(r"^[A-Z0-9&\-]{1,20}$")
FUNDAMENTALS_CACHE_PATH = ROOT / "fundamentals_cache.json"
FUNDAMENTALS_CACHE_TTL_SECONDS = 24 * 3600
BREAKOUT_SHEET_ID = "1gLrCYp_GmRSpEkrCVwwEn_Ec97IQr6YfNo7mvPQLZgk"
BREAKOUT_SHEET_GID_CH = "649235540"
BREAKOUT_SHEET_GID_MYB = "1080335833"
BREAKOUT_CACHE_TTL = 15 * 60
NSE_INDICES_URL = "https://nsearchives.nseindia.com/content/indices/ind_close_all_{date}.csv"
NSE_INDICES_CACHE_PATH = ROOT / "nse_indices_cache.json"
NSE_INDICES_CACHE_TTL = 30 * 60
NSE_FO_BHAVCOPY_URL = "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{date}_F_0000.csv.zip"
OI_CHANGE_CACHE_PATH = ROOT / "oi_change_cache.json"
OI_CHANGE_CACHE_TTL = 30 * 60
BETA_JSON_PATH = Path(os.environ.get("BETA_JSON_PATH") or ROOT / "data" / "betas.json")   # written weekly by betas.py
MF_BETA_JSON_PATH = Path(os.environ.get("MF_BETA_JSON_PATH") or ROOT / "data" / "mf_betas.json")   # and by mf_betas.py
DATA_JSON_GZIP = {}   # path -> (etag, gzipped body) for the beta files, so each weekly file is compressed once
MF_API_URL = "https://api.mfapi.in/mf"
MF_CACHE_DIR = ROOT / "mf_nav_cache"
MF_CODE_RE = re.compile(r"^\d{1,8}$")
SITE_URL = "https://letmoneyearn.in"
SITEMAP_STATIC_PAGES = ("", "services.html", "sheets.html", "gold-vs-nifty.html", "momentum-study.html", "breakout-study.html", "nse-indices.html", "oi-change.html", "portfolio-beta.html", "calculators.html", "mf-compare.html", "mf-sip.html", "mf-swp.html", "loan-prepayment.html", "review.html", "question.html", "about.html", "contact.html", "privacy.html", "terms.html")
UPLOADS_DIR = ROOT / "uploads"
UPLOAD_EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
ADMIN_PASSWORD = os.environ.get("LET_MONEY_EARN_ADMIN_PASSWORD")
SESSIONS = set()
PUBLIC_ONLY = False

SEED_POSTS = [
    ("How to build your first investment plan", "A practical starting point for setting goals, understanding risk, and investing with consistency.", "Basics", "24 Aug 2026", "RATNESH KUMAR SINGH", "RS", "featured", "https://images.unsplash.com/photo-1559526324-593bc073d938?auto=format&fit=crop&w=1200&q=85"),
    ("Mutual funds: a simple beginner's guide", "Understand how mutual funds work and what to check before making your first investment.", "Investing", "19 Aug 2026", "Let Money Earn", "LM", "desk", "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?auto=format&fit=crop&w=800&q=85"),
    ("What is portfolio beta?", "Learn how beta helps you understand the relationship between market movement and portfolio risk.", "Markets", "12 Aug 2026", "Let Money Earn", "LM", "paper", "https://images.unsplash.com/photo-1535320903710-d993d3d77d29?auto=format&fit=crop&w=800&q=85"),
    ("Five habits for long-term wealth", "Small, repeatable decisions that can make your financial journey more deliberate.", "Personal Finance", "04 Aug 2026", "Let Money Earn", "LM", "window", "https://images.unsplash.com/photo-1554224155-6726b3ff858f?auto=format&fit=crop&w=800&q=85"),
]

DEMO_CONTENT = {
    "Mutual funds: a simple beginner's guide": "<p>A mutual fund collects money from many investors and invests it across a basket of assets. This can make it easier to start investing without selecting every security yourself.</p><h2>Start with the goal</h2><p>Before choosing a fund, decide what the money is for, when you may need it, and how much movement you can accept along the way. A clear goal is more useful than chasing last year's return.</p><h2>Check the essentials</h2><ul><li>Understand the fund's investment objective.</li><li>Compare costs and portfolio risk.</li><li>Choose an investment horizon that matches your goal.</li></ul><p>Consistency, suitable risk, and patience usually matter more than making frequent changes.</p>",
    "What is portfolio beta?": "<p>Portfolio beta is a way to compare how strongly a portfolio has moved in relation to a broader market index. A beta of 1 suggests similar movement, while a beta above or below 1 suggests more or less sensitivity.</p><h2>Why it matters</h2><p>Beta is one useful lens for understanding market risk. It does not predict returns, and it does not capture every risk, but it can help you ask better questions about diversification and volatility.</p><blockquote>Risk is not a single number. Use beta as a starting point for investigation, not as a final decision.</blockquote><p>Review beta alongside your goals, time horizon, asset mix, and ability to handle losses.</p>",
    "Five habits for long-term wealth": "<p>Building wealth is less about finding one perfect decision and more about creating a system you can follow through changing markets and changing priorities.</p><h2>Five durable habits</h2><ol><li>Keep a clear monthly saving target.</li><li>Invest regularly instead of waiting for perfect timing.</li><li>Build an emergency reserve before taking unnecessary risk.</li><li>Review your portfolio on a schedule, not every day.</li><li>Keep learning and question advice that promises certainty.</li></ol><p>Small decisions repeated over years can give your financial plan the stability it needs.</p>",
}

DEMO_REVIEWS = [
    ("Amit Sharma", "The mutual fund session helped me understand where to begin without feeling overwhelmed.", 5, "approved"),
    ("Priya Mehta", "Clear explanations and practical examples. I finally understand the basics of portfolio risk.", 5, "approved"),
    ("Rahul Verma", "The market classes gave me a much better foundation for my own research.", 4, "approved"),
]


def connection():
    database = sqlite3.connect(DB_PATH)
    database.row_factory = sqlite3.Row
    return database


def initialize_database():
    with connection() as database:
        database.execute("""CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, summary TEXT NOT NULL, content TEXT DEFAULT '', status TEXT DEFAULT 'published', active INTEGER DEFAULT 1,
            category TEXT NOT NULL, published_at TEXT NOT NULL, author TEXT NOT NULL,
            initials TEXT NOT NULL, image_class TEXT NOT NULL, image_url TEXT NOT NULL
        )""")
        database.execute("""CREATE TABLE IF NOT EXISTS call_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT, service TEXT NOT NULL, name TEXT NOT NULL,
            email TEXT NOT NULL, phone TEXT NOT NULL, message TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        database.execute("""CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            email TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        database.execute("""CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, review TEXT NOT NULL,
            rating INTEGER NOT NULL DEFAULT 5, status TEXT NOT NULL DEFAULT 'pending', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            image_url TEXT DEFAULT ''
        )""")
        database.execute("""CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER NOT NULL, name TEXT NOT NULL,
            comment TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        columns = {row[1] for row in database.execute("PRAGMA table_info(posts)")}
        if "content" not in columns:
            database.execute("ALTER TABLE posts ADD COLUMN content TEXT DEFAULT ''")
        if "status" not in columns:
            database.execute("ALTER TABLE posts ADD COLUMN status TEXT DEFAULT 'published'")
        if "active" not in columns:
            database.execute("ALTER TABLE posts ADD COLUMN active INTEGER DEFAULT 1")
        database.execute("UPDATE posts SET active = 1 WHERE active IS NULL")
        review_columns = {row[1] for row in database.execute("PRAGMA table_info(reviews)")}
        if "image_url" not in review_columns:
            database.execute("ALTER TABLE reviews ADD COLUMN image_url TEXT DEFAULT ''")
        if database.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 0:
            database.executemany("INSERT INTO posts (title, summary, category, published_at, author, initials, image_class, image_url, content, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [post + (post[1], "published") for post in SEED_POSTS])
        for title, content in DEMO_CONTENT.items():
            database.execute("UPDATE posts SET content = ? WHERE title = ? AND (content IS NULL OR content = '')", (content, title))
        database.execute("UPDATE posts SET author = 'RATNESH KUMAR SINGH' WHERE author = 'Ratnesh Kumar Singh'")
        if database.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 0:
            database.executemany("INSERT INTO reviews (name, review, rating, status) VALUES (?, ?, ?, ?)", DEMO_REVIEWS)
        if database.execute("SELECT COUNT(*) FROM comments").fetchone()[0] == 0:
            post_id = database.execute("SELECT id FROM posts WHERE title = ?", ("Mutual funds: a simple beginner's guide",)).fetchone()[0]
            database.executemany("INSERT INTO comments (post_id, name, comment, status) VALUES (?, ?, ?, 'approved')", [
                (post_id, "Neha Kapoor", "This made mutual funds much easier to understand. The goal-first approach is very helpful."),
                (post_id, "Vikram Joshi", "A useful beginner's overview. I am going to revisit the checklist before investing."),
            ])


def load_json_cache(path):
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_json_cache(path, cache):
    try:
        path.write_text(json.dumps(cache), encoding="utf-8")
    except OSError:
        pass


HISTORY_FETCH_ERRORS = (urllib.error.URLError, TimeoutError, KeyError, IndexError, ValueError, json.JSONDecodeError, csv.Error)


def _fetch_symbol_history_yahoo_host(host, symbol, period1, period2):
    url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{symbol}.NS?period1={period1}&period2={period2}&interval=1d"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=6) as response:
        payload = json.loads(response.read().decode("utf-8"))
    result = payload["chart"]["result"][0]
    timestamps = result["timestamp"]
    quote = result["indicators"]["quote"][0]
    closes = quote["close"]
    opens = quote.get("open") or [None] * len(closes)
    highs = quote.get("high") or [None] * len(closes)
    lows = quote.get("low") or [None] * len(closes)
    volumes = quote.get("volume") or [None] * len(closes)
    points = [
        {
            "date": datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d"),
            "open": round(o, 2) if o is not None else close,
            "high": round(h, 2) if h is not None else close,
            "low": round(l, 2) if l is not None else close,
            "close": round(close, 2),
            "volume": volume,
        }
        for ts, o, h, l, close, volume in zip(timestamps, opens, highs, lows, closes, volumes)
        if close is not None
    ]
    if not points:
        raise ValueError(f"Yahoo ({host}) returned an empty series.")
    return points


def fetch_symbol_history_yahoo(symbol, period1, period2):
    """Primary source. Confirmed working with real requests during development."""
    return _fetch_symbol_history_yahoo_host("query1", symbol, period1, period2)


def fetch_symbol_history_stooq(symbol, period1, period2):
    """Fallback 1. Blocked by a JS anti-bot challenge from the dev network as of writing —
    kept as a fallback in case it's reachable from wherever this actually runs."""
    d1 = datetime.fromtimestamp(period1, tz=timezone.utc).strftime("%Y%m%d")
    d2 = datetime.fromtimestamp(period2, tz=timezone.utc).strftime("%Y%m%d")
    url = f"https://stooq.com/q/d/l/?s={symbol}.IN&d1={d1}&d2={d2}&i=d"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=6) as response:
        text = response.read().decode("utf-8")
    if not text or "Date,Open" not in text:
        raise ValueError("Stooq returned no data for this symbol.")
    def parse_num(value, fallback):
        return round(float(value), 2) if value not in (None, "", "N/D") else fallback

    points = []
    for row in csv.DictReader(io.StringIO(text)):
        if row.get("Close") in (None, "", "N/D"):
            continue
        close = round(float(row["Close"]), 2)
        points.append({
            "date": row["Date"],
            "open": parse_num(row.get("Open"), close),
            "high": parse_num(row.get("High"), close),
            "low": parse_num(row.get("Low"), close),
            "close": close,
            "volume": int(row["Volume"]) if row.get("Volume") not in (None, "", "N/D") else None,
        })
    if not points:
        raise ValueError("Stooq returned an empty series.")
    return points


def fetch_symbol_history_yahoo_alt(symbol, period1, period2):
    """Fallback 2. Yahoo's alternate edge host (query2 instead of query1) — cheap extra
    redundancy against a single Yahoo edge/host having an outage, no new dependency."""
    return _fetch_symbol_history_yahoo_host("query2", symbol, period1, period2)


def fetch_symbol_history(symbol, years):
    period2 = int(time.time())
    period1 = int((datetime.now(timezone.utc) - timedelta(days=365 * years)).timestamp())
    last_error = None
    for source in (fetch_symbol_history_yahoo, fetch_symbol_history_stooq, fetch_symbol_history_yahoo_alt):
        try:
            return source(symbol, period1, period2)
        except HISTORY_FETCH_ERRORS as error:
            last_error = error
    raise last_error


def get_symbol_history(symbol, years):
    cache_key = f"{symbol}:{years}y"
    cache = load_json_cache(HISTORY_CACHE_PATH)
    entry = cache.get(cache_key)
    now = time.time()
    if entry and now - entry.get("fetchedAt", 0) < HISTORY_CACHE_TTL_SECONDS:
        return entry["data"], False
    try:
        points = fetch_symbol_history(symbol, years)
    except HISTORY_FETCH_ERRORS:
        if entry:
            return entry["data"], True
        return None, False
    cache[cache_key] = {"fetchedAt": now, "data": points}
    save_json_cache(HISTORY_CACHE_PATH, cache)
    return points, False


FUNDAMENTALS_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}
FUNDAMENTALS_FETCH_ERRORS = HISTORY_FETCH_ERRORS + (TypeError, http.client.HTTPException)


def fetch_fundamentals_yahoo(symbol):
    """Yahoo quoteSummary key statistics, as {field: raw number}. Needs a cookie + crumb."""
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    try:
        opener.open(urllib.request.Request("https://fc.yahoo.com", headers=FUNDAMENTALS_UA), timeout=8)
    except urllib.error.HTTPError:
        pass  # fc.yahoo.com answers 404 but still sets the session cookie
    crumb_request = urllib.request.Request("https://query1.finance.yahoo.com/v1/test/getcrumb", headers=FUNDAMENTALS_UA)
    crumb = opener.open(crumb_request, timeout=8).read().decode("utf-8").strip()
    url = (f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{urllib.parse.quote(symbol)}.NS"
           f"?modules=summaryDetail,defaultKeyStatistics,financialData&crumb={urllib.parse.quote(crumb)}")
    with opener.open(urllib.request.Request(url, headers=FUNDAMENTALS_UA), timeout=8) as response:
        payload = json.loads(response.read().decode("utf-8"))
    raw = {}
    for module in payload["quoteSummary"]["result"][0].values():
        for key, value in module.items():
            if isinstance(value, dict) and isinstance(value.get("raw"), (int, float)):
                raw.setdefault(key, value["raw"])
    return raw


def build_fundamentals(yahoo):
    """Turns Yahoo's raw statistics into display groups of {label, value} with pre-formatted text."""
    def num(value, digits=2, suffix=""):
        return f"{value:,.{digits}f}{suffix}" if isinstance(value, (int, float)) else None

    def pct(value):
        return num(value * 100, 1, "%") if isinstance(value, (int, float)) else None

    def crore(value):
        return f"₹ {value / 1e7:,.0f} Cr" if isinstance(value, (int, float)) else None

    def rupee(value):
        return f"₹ {value:,.2f}" if isinstance(value, (int, float)) else None

    debt_to_equity = yahoo.get("debtToEquity")
    high52, low52 = yahoo.get("fiftyTwoWeekHigh"), yahoo.get("fiftyTwoWeekLow")
    groups = [
        ("Valuation", [
            ("Market cap", crore(yahoo.get("marketCap"))),
            ("P/E (TTM)", num(yahoo.get("trailingPE"))),
            ("Forward P/E", num(yahoo.get("forwardPE"))),
            ("P/B", num(yahoo.get("priceToBook"))),
            ("EV/EBITDA", num(yahoo.get("enterpriseToEbitda"))),
            ("Book value", rupee(yahoo.get("bookValue"))),
            ("Dividend yield", pct(yahoo.get("dividendYield"))),
        ]),
        ("Profitability", [
            ("ROE", pct(yahoo.get("returnOnEquity"))),
            ("ROA", pct(yahoo.get("returnOnAssets"))),
            ("Operating margin", pct(yahoo.get("operatingMargins"))),
            ("Net margin", pct(yahoo.get("profitMargins"))),
            ("EPS (TTM)", num(yahoo.get("trailingEps"))),
        ]),
        ("Growth & balance sheet", [
            ("Revenue growth (YoY)", pct(yahoo.get("revenueGrowth"))),
            ("Earnings growth (YoY)", pct(yahoo.get("earningsGrowth"))),
            # Yahoo reports debt/equity as a percentage (7.0 = 0.07x).
            ("Debt / equity", num(debt_to_equity / 100) if isinstance(debt_to_equity, (int, float)) else None),
            ("Insider holding", pct(yahoo.get("heldPercentInsiders"))),
            ("52W high / low", f"{rupee(high52)} / {rupee(low52)}" if high52 and low52 else None),
        ]),
    ]
    return [
        {"title": title, "items": [{"label": label, "value": value} for label, value in items if value]}
        for title, items in groups
        if any(value for _, value in items)
    ]


def get_symbol_fundamentals(symbol):
    cache = load_json_cache(FUNDAMENTALS_CACHE_PATH)
    entry = cache.get(symbol)
    now = time.time()
    if entry and now - entry.get("fetchedAt", 0) < FUNDAMENTALS_CACHE_TTL_SECONDS:
        return entry["data"], False
    try:
        groups = build_fundamentals(fetch_fundamentals_yahoo(symbol))
    except FUNDAMENTALS_FETCH_ERRORS:
        groups = []
    if not groups:
        if entry:
            return entry["data"], True
        return None, False
    data = {"groups": groups, "asOf": datetime.now(IST).strftime("%d %b %Y")}
    cache[symbol] = {"fetchedAt": now, "data": data}
    save_json_cache(FUNDAMENTALS_CACHE_PATH, cache)
    return data, False


MF_FETCH_ERRORS = HISTORY_FETCH_ERRORS + (TypeError, AttributeError, http.client.HTTPException)
MF_SCHEMES_PATH = MF_CACHE_DIR / "schemes.json"
MF_SCHEMES = {"fetchedAt": 0, "rows": []}
MF_SCHEMES_LOCK = threading.Lock()


def fetch_mfapi_json(path, timeout=12):
    request = urllib.request.Request(f"{MF_API_URL}/{path}", headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def last_ist_midnight():
    return datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def mf_search_text(text):
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def index_mf_schemes(rows):
    """(code, name, words, words run together, has an ISIN) for each scheme in mfapi.in's full list."""
    indexed = []
    for row in rows:
        try:
            code, name = str(row["schemeCode"]), row["schemeName"].strip()
        except (KeyError, TypeError, AttributeError):
            continue
        words = mf_search_text(name)
        indexed.append((code, name, f" {words}", words.replace(" ", ""), bool(row.get("isinGrowth") or row.get("isinDivReinvestment"))))
    return indexed


def get_mf_schemes():
    """Every scheme mfapi.in knows (about 40,000), kept in memory and on disk until midnight (IST).
    If mfapi.in can't be reached the last saved list is used."""
    with MF_SCHEMES_LOCK:
        midnight = last_ist_midnight()
        if MF_SCHEMES["rows"] and MF_SCHEMES["fetchedAt"] >= midnight:
            return MF_SCHEMES["rows"]
        saved = load_json_cache(MF_SCHEMES_PATH)
        if saved.get("fetchedAt", 0) >= midnight and saved.get("rows"):
            MF_SCHEMES.update(fetchedAt=saved["fetchedAt"], rows=index_mf_schemes(saved["rows"]))
            return MF_SCHEMES["rows"]
        try:
            rows = fetch_mfapi_json("", timeout=60)
            if not rows:
                raise ValueError("Empty scheme list.")
        except MF_FETCH_ERRORS:
            if MF_SCHEMES["rows"]:
                return MF_SCHEMES["rows"]
            if saved.get("rows"):
                MF_SCHEMES.update(fetchedAt=saved["fetchedAt"], rows=index_mf_schemes(saved["rows"]))
                return MF_SCHEMES["rows"]
            raise
        now = time.time()
        try:
            MF_CACHE_DIR.mkdir(exist_ok=True)
        except OSError:
            pass
        save_json_cache(MF_SCHEMES_PATH, {"fetchedAt": now, "rows": rows})
        MF_SCHEMES.update(fetchedAt=now, rows=index_mf_schemes(rows))
        return MF_SCHEMES["rows"]


def search_mf_schemes(query):
    """Schemes whose name contains every word of the query, in any order ("hdfc flexi", "flexicap"
    and "hdfc flexi cap direct" all find HDFC Flexi Cap Fund). Words that start a word in the name
    rank first, then those matching more whole words ("nifty 50" before "Nifty 500"), then schemes
    that still have an ISIN (closed and merged schemes mostly don't)."""
    terms = mf_search_text(query).split()
    if not terms:
        return []
    matches = []
    for code, name, words, joined, has_isin in get_mf_schemes():
        if all(term in words or term in joined for term in terms):
            at_word_start = all(f" {term}" in words for term in terms)
            whole_words = sum(f" {term} " in f"{words} " for term in terms)
            matches.append((not at_word_start, -whole_words, not has_isin, len(name), name, code))
    matches.sort()
    return [{"code": code, "name": name} for *_, name, code in matches[:60]]


def parse_mf_history(payload):
    """mfapi.in gives dd-mm-yyyy dates, newest first; return ISO dates, oldest first."""
    meta = payload["meta"]
    navs = {}
    for row in payload["data"]:
        try:
            nav = float(row["nav"])
            day, month, year = row["date"].split("-")
        except (KeyError, TypeError, ValueError):
            continue
        if nav > 0:
            navs[f"{year}-{month}-{day}"] = nav
    return {
        "code": str(meta["scheme_code"]),
        "name": meta["scheme_name"],
        "house": meta.get("fund_house") or "",
        "category": meta.get("scheme_category") or "",
        "points": sorted(navs.items()),
    }


def get_mf_history(code):
    """Full NAV history for one scheme, cached on disk (one file per scheme) until midnight (IST)."""
    path = MF_CACHE_DIR / f"{code}.json"
    entry = load_json_cache(path)
    now = time.time()
    if entry and entry.get("fetchedAt", 0) >= last_ist_midnight():
        return entry["data"], False
    try:
        data = parse_mf_history(fetch_mfapi_json(code))
        if not data["points"]:
            raise ValueError("No NAV history.")
    except MF_FETCH_ERRORS:
        if entry:
            return entry["data"], True
        return None, False
    try:
        MF_CACHE_DIR.mkdir(exist_ok=True)
    except OSError:
        pass
    save_json_cache(path, {"fetchedAt": now, "data": data})
    return data, False


def refresh_mf_cache():
    """Re-fetch the scheme list and every cached fund whose copy is from before midnight (IST).
    A fund that fails keeps its old copy."""
    try:
        get_mf_schemes()
    except MF_FETCH_ERRORS:
        pass
    try:
        codes = sorted(path.stem for path in MF_CACHE_DIR.glob("*.json"))
    except OSError:
        codes = []
    for code in codes:
        if MF_CODE_RE.match(code):
            get_mf_history(code)
            time.sleep(1)


def refresh_mf_cache_nightly():
    """Refresh the fund cache just after each midnight (IST), so the day starts on fresh NAVs
    (AMFI publishes the day's NAVs by about 11 pm). Loads the scheme list first, so the first
    search after a start doesn't wait for it."""
    try:
        get_mf_schemes()
    except MF_FETCH_ERRORS:
        pass
    while True:
        now = datetime.now(IST)
        next_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        time.sleep((next_midnight - now).total_seconds() + 60)
        refresh_mf_cache()


def build_market_reel_daily():
    """Build the FII/DII + OI market reel and post it to Instagram on weekday evenings (IST): every
    30 minutes from 8:30 pm until midnight, since NSE's files land at different times. market_reel.run
    does nothing on holidays, before NSE has published or once the day is posted, so repeat runs cost
    one NSE request. Each run's outcome is appended to market_reel.log next to the server."""
    log = ROOT / "market_reel.log"
    if os.environ.get("MARKET_REEL_TEST_OUT"):    # check a build: one unposted reel for the latest data, at startup
        try:
            print("Market reel test:", market_reel.run(ROOT, fetch_oi_change, force=True, post=False, keep=os.environ["MARKET_REEL_TEST_OUT"]))
        except Exception as error:
            print("Market reel test failed:", type(error).__name__, error)
    while True:
        now = datetime.now(IST)
        start = now.replace(hour=20, minute=30, second=0, microsecond=0)
        if now.weekday() < 5 and now >= start:
            try:
                status = market_reel.run(ROOT, fetch_oi_change)
            except Exception as error:            # network, ffmpeg or Instagram trouble: retried next run
                status = f"failed: {type(error).__name__}: {error}"
            with open(log, "a", encoding="utf-8") as out:
                out.write(f"[{datetime.now(IST):%Y-%m-%d %H:%M}] {status}\n")
            wake = datetime.now(IST) + timedelta(minutes=30)
            if wake.date() != now.date():
                wake = start + timedelta(days=1)
        else:
            wake = start if now < start else start + timedelta(days=1)
        time.sleep(max(60, (wake - datetime.now(IST)).total_seconds()))


def build_betas_weekly():
    """Rebuild the Portfolio Beta tool's data every Friday from 8:15 pm IST, once NSE has published the
    week's last bhavcopy: betas.json (stocks, betas.py), then mf_betas.json (mutual funds, mf_betas.py,
    which reuses the downloaded bhavcopies for its benchmark). The stock build counts as done once it
    succeeds with Friday's data, or with any data after Friday midnight (a Friday holiday); the fund
    build once it succeeds after Friday 8:15 pm (AMFI publishes Friday's NAVs late at night, so it
    may run to Thursday). A missed week (server down) runs at the next start, and so does the first
    ever start. Runs are logged in betas.db, never in the blog's database."""
    try:
        import betas                              # pandas + requests: if missing, the tool's data just stays stale
        import mf_betas
    except ImportError as error:
        print("Portfolio beta builder disabled:", error)
        return
    while True:
        now = datetime.now(IST)
        friday = (now - timedelta(days=(now.weekday() - 4) % 7)).replace(hour=20, minute=15, second=0, microsecond=0)
        if friday > now:
            friday -= timedelta(days=7)
        saturday = (friday + timedelta(days=1)).replace(hour=0, minute=0)
        last = betas.last_success()
        stocks_done = (last is not None and betas.BETA_JSON_PATH.is_file()
                       and (last["asof"] >= friday.date().isoformat() or datetime.fromisoformat(last["finished_at"]) >= saturday))
        last_mf = betas.last_success(table=mf_betas.RUN_TABLE)
        funds_done = (last_mf is not None and mf_betas.MF_BETA_JSON_PATH.is_file()
                      and datetime.fromisoformat(last_mf["finished_at"]) >= friday)
        if stocks_done and funds_done:
            wake = friday + timedelta(days=7)
        else:
            failed = False
            for done, job in ((stocks_done, betas.build), (funds_done, mf_betas.build)):
                if done:
                    continue
                try:
                    job()
                except Exception as error:         # failed a sanity check or NSE/AMFI trouble: the old file stays
                    print("Portfolio beta build failed:", type(error).__name__, error)
                    failed = True
            # Friday's bhavcopy may not be out yet, so check again in 30 minutes; after a failure, in 2 hours
            wake = datetime.now(IST) + (timedelta(hours=2) if failed else timedelta(minutes=30))
        time.sleep(max(60, (wake - datetime.now(IST)).total_seconds()))


def post_slugs(database):
    """Each published post's URL slug, from its title: /post/<slug>. A later post whose title gives
    the same slug as an earlier one gets its id on the end."""
    slugs, taken = {}, set()
    for row in database.execute("SELECT id, title FROM posts WHERE status = 'published' AND active = 1 ORDER BY id"):
        slug = re.sub(r"[^a-z0-9]+", "-", re.sub(r"['’]", "", row["title"].lower())).strip("-") or "post"
        if slug in taken:
            slug = f"{slug}-{row['id']}"
        taken.add(slug)
        slugs[row["id"]] = slug
    return slugs


def format_sitemap_date(value):
    try:
        return datetime.strptime(value, "%d %b %Y").strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


IST = timezone(timedelta(hours=5, minutes=30))
BREAKOUT_HINDI_MONTHS = {
    "जनवरी": "Jan", "जन": "Jan", "फ़रवरी": "Feb", "फ़र": "Feb", "फरवरी": "Feb", "फर": "Feb",
    "मार्च": "Mar", "अप्रैल": "Apr", "मई": "May", "जून": "Jun", "जुलाई": "Jul", "जुल": "Jul",
    "अगस्त": "Aug", "अग": "Aug", "सितंबर": "Sep", "सित": "Sep", "अक्टूबर": "Oct", "अक्टू": "Oct",
    "नवंबर": "Nov", "नव": "Nov", "दिसंबर": "Dec", "दिस": "Dec",
}


def breakout_hindi_date_to_en(value):
    text = (value or "").strip().replace("॰", "")
    if not text:
        return None
    for hindi, english in sorted(BREAKOUT_HINDI_MONTHS.items(), key=lambda item: -len(item[0])):
        if hindi in text:
            return text.replace(hindi, english)
    return text


def breakout_num(value):
    text = (value or "").strip().replace(",", "").rstrip("%")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def fetch_breakout_sheet_csv(gid):
    url = f"https://docs.google.com/spreadsheets/d/{BREAKOUT_SHEET_ID}/export?format=csv&gid={gid}"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.read().decode("utf-8")


def parse_breakout_ch_rows(csv_text):
    rows = []
    for record in csv.DictReader(io.StringIO(csv_text)):
        symbol = (record.get("Symbol") or "").strip()
        status = (record.get("C&H Signal") or "").strip()
        if not symbol or not status:
            continue
        rows.append({
            "symbol": symbol,
            "setup": "C&H",
            "status": status,
            "cmp": breakout_num(record.get("CMP")),
            "pivot": breakout_num(record.get("Pivot")),
            "distPct": breakout_num(record.get("Dist %")),
            "cupWks": breakout_num(record.get("Cup Wks")),
            "cupDepth": breakout_num(record.get("Cup Depth %")),
            "handleWks": breakout_num(record.get("Handle Wks")),
            "handleDepth": breakout_num(record.get("Handle Depth %")),
            "leftRimDate": breakout_hindi_date_to_en(record.get("Left Rim Date")),
            "volRatio": breakout_num(record.get("Vol Ratio")),
            "ma30": breakout_num(record.get("30W MA")),
        })
    return rows


def parse_breakout_myb_rows(csv_text):
    rows = []
    for record in csv.reader(io.StringIO(csv_text)):
        if len(record) < 7:
            continue
        symbol = record[0].strip()
        setup = record[6].strip().upper()
        if not symbol or setup != "MYB":
            continue
        rows.append({
            "symbol": symbol,
            "setup": "MYB",
            "status": record[4].strip(),
            "cmp": breakout_num(record[1]),
            "base": record[5].strip() or None,
            "pct52w": breakout_num(record[3]),
            "stop": breakout_num(record[7]) if len(record) > 7 else None,
        })
    return rows


def parse_breakout_ch_stops(csv_text):
    # The MYB tab also lists C&H rows with their SL (column H); the C&H tab has no SL column.
    stops = {}
    for record in csv.reader(io.StringIO(csv_text)):
        if len(record) < 8 or record[6].strip().upper() != "C&H":
            continue
        symbol, stop = record[0].strip(), breakout_num(record[7])
        if symbol and stop is not None:
            stops[symbol] = stop
    return stops


BREAKOUT_CACHE = {"data": None, "fetched_at": 0.0}


def fetch_breakout_data():
    now = time.time()
    cached = BREAKOUT_CACHE["data"]
    if cached is not None and (now - BREAKOUT_CACHE["fetched_at"]) < BREAKOUT_CACHE_TTL:
        return cached
    try:
        ch_rows = parse_breakout_ch_rows(fetch_breakout_sheet_csv(BREAKOUT_SHEET_GID_CH))
        myb_csv = fetch_breakout_sheet_csv(BREAKOUT_SHEET_GID_MYB)
        myb_rows = parse_breakout_myb_rows(myb_csv)
        ch_stops = parse_breakout_ch_stops(myb_csv)
        for row in ch_rows:
            row["stop"] = ch_stops.get(row["symbol"])
        data = {
            "updatedAt": datetime.now(IST).isoformat(timespec="seconds"),
            "rows": myb_rows + ch_rows,
        }
        BREAKOUT_CACHE["data"] = data
        BREAKOUT_CACHE["fetched_at"] = now
        return data
    except Exception:
        if cached is not None:
            return cached
        if BREAKOUT_DATA_PATH.is_file():
            try:
                return json.loads(BREAKOUT_DATA_PATH.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        return {"updatedAt": None, "rows": []}


def parse_nse_indices_csv(csv_text):
    rows = []
    for record in csv.DictReader(io.StringIO(csv_text)):
        name = (record.get("Index Name") or "").strip()
        if not name:
            continue
        rows.append({
            "name": name,
            "open": breakout_num(record.get("Open Index Value")),
            "high": breakout_num(record.get("High Index Value")),
            "low": breakout_num(record.get("Low Index Value")),
            "close": breakout_num(record.get("Closing Index Value")),
            "change": breakout_num(record.get("Points Change")),
            "changePct": breakout_num(record.get("Change(%)")),
            "volume": breakout_num(record.get("Volume")),
            "turnover": breakout_num(record.get("Turnover (Rs. Cr.)")),
            "pe": breakout_num(record.get("P/E")),
            "pb": breakout_num(record.get("P/B")),
            "divYield": breakout_num(record.get("Div Yield")),
        })
    return rows


NSE_INDICES_CACHE = {"data": None, "fetched_at": 0.0}


def fetch_nse_indices():
    # NSE posts the day's index closing file in the evening, so walk back from today
    # (IST) to the most recent trading day that has one.
    now = time.time()
    cached = NSE_INDICES_CACHE["data"]
    if cached is not None and (now - NSE_INDICES_CACHE["fetched_at"]) < NSE_INDICES_CACHE_TTL:
        return cached
    today = datetime.now(IST).date()
    for back in range(10):
        day = today - timedelta(days=back)
        if day.weekday() >= 5:
            continue
        url = NSE_INDICES_URL.format(date=day.strftime("%d%m%Y"))
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                text = response.read().decode("utf-8-sig")
        except (urllib.error.URLError, OSError, ValueError):
            continue
        if not text.startswith("Index Name"):
            continue
        rows = parse_nse_indices_csv(text)
        if not rows:
            continue
        data = {"date": day.isoformat(), "fetchedAt": datetime.now(IST).isoformat(timespec="seconds"), "rows": rows}
        NSE_INDICES_CACHE["data"] = data
        NSE_INDICES_CACHE["fetched_at"] = now
        save_json_cache(NSE_INDICES_CACHE_PATH, data)
        return data
    if cached is not None:
        return cached
    stored = load_json_cache(NSE_INDICES_CACHE_PATH)
    if stored.get("rows"):
        return stored
    return {"date": None, "fetchedAt": None, "rows": []}


def oi_buildup(price_change, oi_change):
    if not price_change or not oi_change:
        return None
    if oi_change > 0:
        return "Long buildup" if price_change > 0 else "Short buildup"
    return "Short covering" if price_change > 0 else "Long unwinding"


def parse_fo_bhavcopy(csv_text):
    # One row per underlying: futures OI summed over all expiries, price from the nearest
    # expiry's future, and option OI split into calls and puts. OI is in shares.
    symbols = {}
    for record in csv.DictReader(io.StringIO(csv_text)):
        kind = record.get("FinInstrmTp")
        if kind not in ("IDF", "STF", "IDO", "STO"):
            continue
        symbol = (record.get("TckrSymb") or "").strip()
        row = symbols.setdefault(symbol, {
            "symbol": symbol, "index": kind in ("IDF", "IDO"), "expiry": None,
            "price": None, "prevClose": None, "spot": None, "lot": None,
            "futOi": 0.0, "futOiChg": 0.0, "futContracts": 0.0,
            "ceOi": 0.0, "ceOiChg": 0.0, "peOi": 0.0, "peOiChg": 0.0,
        })
        oi = breakout_num(record.get("OpnIntrst")) or 0.0
        chg = breakout_num(record.get("ChngInOpnIntrst")) or 0.0
        if kind in ("IDF", "STF"):
            row["futOi"] += oi
            row["futOiChg"] += chg
            row["futContracts"] += breakout_num(record.get("TtlTradgVol")) or 0.0
            expiry = record.get("XpryDt") or ""
            if row["expiry"] is None or expiry < row["expiry"]:
                row.update(expiry=expiry, price=breakout_num(record.get("ClsPric")),
                           prevClose=breakout_num(record.get("PrvsClsgPric")),
                           spot=breakout_num(record.get("UndrlygPric")),
                           lot=breakout_num(record.get("NewBrdLotQty")))
        else:
            side = "ce" if record.get("OptnTp") == "CE" else "pe"
            row[side + "Oi"] += oi
            row[side + "OiChg"] += chg
            if row["spot"] is None:
                row["spot"] = breakout_num(record.get("UndrlygPric"))
    rows = []
    for row in symbols.values():
        if not row["futOi"]:
            continue
        price, prev = row["price"], row["prevClose"]
        row["priceChgPct"] = round((price / prev - 1) * 100, 2) if price and prev else None
        base = row["futOi"] - row["futOiChg"]
        row["futOiChgPct"] = round(row["futOiChg"] / base * 100, 2) if base > 0 else None
        row["pcr"] = round(row["peOi"] / row["ceOi"], 2) if row["ceOi"] else None
        row["buildup"] = oi_buildup(row["priceChgPct"], row["futOiChg"])
        rows.append(row)
    rows.sort(key=lambda r: (not r["index"], r["symbol"]))
    return rows


def parse_nifty_hedge(csv_text, min_days=7):
    """For the Portfolio Beta tool's hedge sizer: NIFTY's lot size and spot, each futures expiry's price,
    and the closing premium of every NIFTY put between 80% and 101% of spot for the futures (monthly)
    expiries at least min_days after the file's date. Strikes with no open interest are left out."""
    futures, puts, spot, lot, trade_date = {}, {}, None, None, None
    records = [r for r in csv.DictReader(io.StringIO(csv_text)) if (r.get("TckrSymb") or "").strip() == "NIFTY"]
    for record in records:
        if record.get("FinInstrmTp") == "IDF":
            futures[record["XpryDt"]] = breakout_num(record.get("ClsPric"))
            spot = spot or breakout_num(record.get("UndrlygPric"))
            lot = lot or breakout_num(record.get("NewBrdLotQty"))
            trade_date = trade_date or record.get("TradDt")
    if not futures or not spot or not lot:
        return None
    start = (datetime.fromisoformat(trade_date) + timedelta(days=min_days)).date().isoformat() if trade_date else ""
    expiries = sorted(e for e in futures if e >= start)
    for record in records:
        if record.get("FinInstrmTp") != "IDO" or record.get("OptnTp") != "PE" or record.get("XpryDt") not in expiries:
            continue
        strike, premium = breakout_num(record.get("StrkPric")), breakout_num(record.get("ClsPric"))
        oi = breakout_num(record.get("OpnIntrst")) or 0
        if strike and premium and oi > 0 and 0.8 * spot <= strike <= 1.01 * spot:
            puts.setdefault(record["XpryDt"], []).append([strike, premium, int(oi), int(breakout_num(record.get("TtlTradgVol")) or 0)])
    return {
        "spot": spot, "lot": int(lot),
        "futures": [{"expiry": e, "price": futures[e]} for e in sorted(futures)],
        "puts": [{"expiry": e, "strikes": sorted(puts[e])} for e in expiries if puts.get(e)],
    }


OI_CHANGE_CACHE = {"data": None, "fetched_at": 0.0}


def fetch_oi_change():
    # Walk back from today (IST) to the latest F&O bhavcopy. A day already held in the cache
    # is not downloaded again, so once the evening file is in, later checks cost nothing.
    now = time.time()
    cached = OI_CHANGE_CACHE["data"]
    if cached is None:
        stored = load_json_cache(OI_CHANGE_CACHE_PATH)
        cached = stored if stored.get("rows") else None
        OI_CHANGE_CACHE["data"] = cached
    if cached is not None and (now - OI_CHANGE_CACHE["fetched_at"]) < OI_CHANGE_CACHE_TTL:
        return cached
    today = datetime.now(IST).date()
    for back in range(10):
        day = today - timedelta(days=back)
        if day.weekday() >= 5:
            continue
        if cached is not None and cached.get("date") == day.isoformat() and "niftyHedge" in cached:
            OI_CHANGE_CACHE["fetched_at"] = now
            return cached
        url = NSE_FO_BHAVCOPY_URL.format(date=day.strftime("%Y%m%d"))
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.nseindia.com/"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = response.read()
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                text = archive.read(archive.namelist()[0]).decode("utf-8-sig")
        except (urllib.error.URLError, OSError, ValueError, zipfile.BadZipFile, IndexError):
            continue
        rows = parse_fo_bhavcopy(text)
        if not rows:
            continue
        data = {"date": day.isoformat(), "fetchedAt": datetime.now(IST).isoformat(timespec="seconds"), "rows": rows,
                "niftyHedge": parse_nifty_hedge(text)}
        OI_CHANGE_CACHE["data"] = data
        OI_CHANGE_CACHE["fetched_at"] = now
        save_json_cache(OI_CHANGE_CACHE_PATH, data)
        return data
    return cached or {"date": None, "fetchedAt": None, "rows": []}


class BlogHandler(BaseHTTPRequestHandler):
    def is_admin(self):
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        token = cookie.get("admin_session")
        return token is not None and token.value in SESSIONS

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def serve_robots(self):
        body = (
            "User-agent: *\n"
            "Allow: /\n"
            "Disallow: /admin.html\n"
            "Disallow: /admin-login.html\n"
            "Disallow: /admin_comments.html\n"
            "Disallow: /admin_questions.html\n"
            "Disallow: /admin_reviews.html\n"
            "Disallow: /api/\n\n"
            f"Sitemap: {SITE_URL}/sitemap.xml\n"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_sitemap(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        entries = [
            f"<url><loc>{SITE_URL}/{page}</loc><lastmod>{today}</lastmod><changefreq>weekly</changefreq></url>"
            for page in SITEMAP_STATIC_PAGES
        ]
        with connection() as database:
            posts = database.execute(
                "SELECT id, published_at FROM posts WHERE status = 'published' AND active = 1 ORDER BY id DESC"
            ).fetchall()
            slugs = post_slugs(database)
        for post in posts:
            entries.append(
                f"<url><loc>{SITE_URL}/post/{slugs[post['id']]}</loc>"
                f"<lastmod>{format_sitemap_date(post['published_at'])}</lastmod>"
                f"<changefreq>monthly</changefreq></url>"
            )
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + "".join(entries) + "</urlset>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/xml; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_data_json(self, path):
        """The Portfolio Beta tool's data files (betas.json, mf_betas.json). They change once a week, so
        browsers may keep them an hour and then revalidate with the ETag (the file's mtime and size),
        which costs a 304 rather than the whole file. Sent gzipped when the browser accepts it."""
        try:
            stat = path.stat()
        except OSError:
            self.send_error(404)
            return
        etag = f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"'
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "public, max-age=3600")
            self.end_headers()
            return
        body = path.read_bytes()
        zipped = "gzip" in (self.headers.get("Accept-Encoding") or "")
        if zipped:
            cached = DATA_JSON_GZIP.get(path)
            if not cached or cached[0] != etag:
                cached = DATA_JSON_GZIP[path] = (etag, gzip.compress(body, 6))
            body = cached[1]
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        if zipped:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Vary", "Accept-Encoding")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(body)

    def redirect(self, location):
        self.send_response(301)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def serve_post_page(self, slug=None):
        """/post/<slug>; the old /post.html?id=N links redirect there."""
        template = (ROOT / "post.html").read_text(encoding="utf-8").replace("<head>", '<head><base href="/">', 1)
        post = None
        with connection() as database:
            slugs = post_slugs(database)
            if slug is None:
                post_id = parse_qs(urlparse(self.path).query).get("id", [""])[0]
                if post_id.isdigit() and int(post_id) in slugs:
                    self.redirect(f"/post/{slugs[int(post_id)]}")
                    return
            else:
                post_id = next((i for i, s in slugs.items() if s == slug), None)
                if post_id is not None:
                    post = database.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
        if post:
            post = dict(post)
            page_url = f"{SITE_URL}/post/{slug}"
            image = post["image_url"] or "https://raw.githubusercontent.com/mscratnesh/htmlSite/main/images/Let_Money_Earn_Logo_Cropped.png"
            if image.startswith("/"):
                image = f"{SITE_URL}{image}"
            title = html.escape(f"{post['title']} | Let Money Earn")
            description = html.escape(post["summary"], quote=True)
            image_attr = html.escape(image, quote=True)
            structured_data = json.dumps({
                "@context": "https://schema.org",
                "@type": "Article",
                "headline": post["title"],
                "description": post["summary"],
                "image": image,
                "author": {"@type": "Person", "name": post["author"]},
                "publisher": {"@type": "Organization", "name": "Let Money Earn"},
                "datePublished": post["published_at"],
                "mainEntityOfPage": {"@type": "WebPage", "@id": page_url},
            })
            head_tags = (
                f'<link rel="canonical" href="{page_url}">'
                f'<meta name="robots" content="index, follow">'
                f'<meta property="og:type" content="article">'
                f'<meta property="og:site_name" content="Let Money Earn">'
                f'<meta property="og:title" content="{html.escape(post["title"], quote=True)}">'
                f'<meta property="og:description" content="{description}">'
                f'<meta property="og:url" content="{page_url}">'
                f'<meta property="og:image" content="{image_attr}">'
                f'<meta name="twitter:card" content="summary_large_image">'
                f'<meta name="twitter:title" content="{html.escape(post["title"], quote=True)}">'
                f'<meta name="twitter:description" content="{description}">'
                f'<meta name="twitter:image" content="{image_attr}">'
                f'<script type="application/ld+json">{structured_data}</script>'
            )
            template = template.replace(
                '<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Article | Let Money Earn</title>',
                f'<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                f'<meta name="description" content="{description}"><title>{title}</title>{head_tags}',
                1,
            ).replace("<body>", f'<body data-post-id="{post["id"]}">', 1)
        body = template.encode("utf-8")
        self.send_response(200 if post else 404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        route = urlparse(self.path).path
        if route == "/robots.txt":
            self.serve_robots()
            return
        if route == "/sitemap.xml":
            self.serve_sitemap()
            return
        if route == "/post.html":
            self.serve_post_page()
            return
        if route.startswith("/post/"):
            self.serve_post_page(urllib.parse.unquote(route[len("/post/"):]).strip("/").lower())
            return
        if PUBLIC_ONLY and (route.startswith("/admin") or route.startswith("/api/admin")):
            self.send_error(404)
            return
        if route in ("/admin.html", "/admin_reviews.html", "/admin_comments.html", "/admin_questions.html", "/api/admin/session") and not self.is_admin():
            if route == "/api/admin/session":
                self.send_json({"authenticated": False}, 401)
            else:
                self.send_error(403, "Admin access required")
            return
        if route == "/api/admin/session":
            self.send_json({"authenticated": True})
            return
        if route == "/api/breakout-desk":
            self.send_json(fetch_breakout_data())
            return
        if route == "/api/nse-indices":
            self.send_json(fetch_nse_indices())
            return
        if route == "/api/oi-change":
            self.send_json({key: value for key, value in fetch_oi_change().items() if key != "niftyHedge"})
            return
        if route == "/api/nifty-hedge":
            data = fetch_oi_change()
            self.send_json({"date": data.get("date"), **(data.get("niftyHedge") or {})})
            return
        if route in ("/tools/portfolio-beta", "/tools/portfolio-beta/"):
            self.redirect("/portfolio-beta.html")
            return
        if route == "/data/betas.json":
            self.serve_data_json(BETA_JSON_PATH)
            return
        if route == "/data/mf_betas.json":
            self.serve_data_json(MF_BETA_JSON_PATH)
            return
        if route == "/api/momentum":
            self.send_json(momentum.load_state(ROOT))
            return
        if route == "/api/mf/search":
            query = parse_qs(urlparse(self.path).query).get("q", [""])[0].strip()
            if not 3 <= len(query) <= 80:
                self.send_json({"results": []})
                return
            try:
                results = search_mf_schemes(query)
            except MF_FETCH_ERRORS:
                self.send_json({"error": "Could not search funds right now."}, 502)
                return
            self.send_json({"results": results})
            return
        if route.startswith("/api/mf/nav/"):
            code = route.rsplit("/", 1)[1]
            if not MF_CODE_RE.match(code):
                self.send_json({"error": "Invalid scheme code."}, 400)
                return
            data, stale = get_mf_history(code)
            if data is None:
                self.send_json({"error": "Could not load NAV history."}, 502)
                return
            self.send_json({**data, "stale": stale})
            return
        if route.startswith("/api/breakout-desk/fundamentals/"):
            symbol = urllib.parse.unquote(route.rsplit("/", 1)[1]).upper()
            if not HISTORY_SYMBOL_RE.match(symbol):
                self.send_json({"error": "Invalid symbol."}, 400)
                return
            data, stale = get_symbol_fundamentals(symbol)
            if data is None:
                self.send_json({"error": "Could not load fundamentals."}, 502)
                return
            self.send_json({"symbol": symbol, **data, "stale": stale})
            return
        if route.startswith("/api/breakout-desk/history/"):
            symbol = route.rsplit("/", 1)[1].upper()
            if not HISTORY_SYMBOL_RE.match(symbol):
                self.send_json({"error": "Invalid symbol."}, 400)
                return
            try:
                years = float(parse_qs(urlparse(self.path).query).get("years", ["2"])[0])
            except (TypeError, ValueError):
                years = 2.0
            years = round(max(0.5, min(15, years)), 1)
            points, stale = get_symbol_history(symbol, years)
            if points is None:
                self.send_json({"error": "Could not load price history."}, 502)
                return
            self.send_json({"symbol": symbol, "points": points, "stale": stale})
            return
        if route == "/api/posts":
            with connection() as database:
                posts = [dict(row) for row in database.execute("SELECT * FROM posts WHERE status = 'published' AND active = 1 ORDER BY id DESC")]
                slugs = post_slugs(database)
            for post in posts:
                post["slug"] = slugs[post["id"]]
            self.send_json(posts)
            return
        if route == "/api/reviews":
            with connection() as database:
                reviews = [dict(row) for row in database.execute("SELECT id, name, review, rating, image_url, created_at FROM reviews WHERE status = 'approved' ORDER BY id DESC")]
            self.send_json(reviews)
            return
        if route == "/api/admin/reviews":
            if not self.is_admin():
                self.send_json({"error": "Admin access required."}, 401)
                return
            with connection() as database:
                reviews = [dict(row) for row in database.execute("SELECT * FROM reviews ORDER BY id DESC")]
            self.send_json(reviews)
            return
        if route == "/api/admin/comments":
            if not self.is_admin():
                self.send_json({"error": "Admin access required."}, 401)
                return
            with connection() as database:
                comments = [dict(row) for row in database.execute("SELECT comments.*, posts.title AS post_title FROM comments JOIN posts ON posts.id = comments.post_id ORDER BY comments.id DESC")]
            self.send_json(comments)
            return
        if route == "/api/admin/questions":
            if not self.is_admin():
                self.send_json({"error": "Admin access required."}, 401)
                return
            with connection() as database:
                questions = [dict(row) for row in database.execute("SELECT * FROM questions ORDER BY id DESC")]
            self.send_json(questions)
            return
        if route.startswith("/api/posts/"):
            try:
                post_id = int(route.rsplit("/", 1)[1])
            except ValueError:
                self.send_json({"error": "Invalid post id."}, 400)
                return
            with connection() as database:
                post = database.execute("SELECT * FROM posts WHERE id = ? AND status = 'published' AND active = 1", (post_id,)).fetchone()
            self.send_json(dict(post) if post else {"error": "Post not found."}, 200 if post else 404)
            return
        if route.startswith("/api/comments/"):
            try:
                post_id = int(route.rsplit("/", 1)[1])
            except ValueError:
                self.send_json({"error": "Invalid post id."}, 400)
                return
            with connection() as database:
                comments = [dict(row) for row in database.execute("SELECT id, name, comment, created_at FROM comments WHERE post_id = ? AND status = 'approved' ORDER BY id DESC", (post_id,))]
            self.send_json(comments)
            return
        if route == "/api/admin/posts":
            with connection() as database:
                posts = [dict(row) for row in database.execute("SELECT * FROM posts ORDER BY id DESC")]
            self.send_json(posts)
            return
        if route.startswith("/api/admin/posts/"):
            try:
                post_id = int(route.rsplit("/", 1)[1])
            except ValueError:
                self.send_json({"error": "Invalid post id."}, 400)
                return
            with connection() as database:
                post = database.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
            if post:
                self.send_json(dict(post))
            else:
                self.send_json({"error": "Post not found."}, 404)
            return
        file_path = ROOT / ("index.html" if route == "/" else route.lstrip("/"))
        if file_path.is_file() and ROOT in file_path.parents:
            content_type = {".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}.get(file_path.suffix, "application/octet-stream")
            body = file_path.read_bytes()
            if route == "/admin.html":
                body += b'<script src="admin_active.js"></script>'
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def do_POST(self):
        route = urlparse(self.path).path
        if PUBLIC_ONLY and route.startswith("/api/admin"):
            self.send_error(404)
            return
        if route == "/api/admin/login":
            if not ADMIN_PASSWORD:
                self.send_json({"error": "Set LET_MONEY_EARN_ADMIN_PASSWORD before starting the server."}, 503)
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                password = json.loads(self.rfile.read(length)).get("password", "")
            except (ValueError, json.JSONDecodeError):
                password = ""
            if not compare_digest(password, ADMIN_PASSWORD):
                self.send_json({"error": "Incorrect password."}, 401)
                return
            token = secrets.token_urlsafe(32)
            SESSIONS.add(token)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Set-Cookie", f"admin_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800")
            self.end_headers()
            self.wfile.write(json.dumps({"message": "Signed in."}).encode())
            return
        if route == "/api/admin/logout":
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            token = cookie.get("admin_session")
            if token:
                SESSIONS.discard(token.value)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Set-Cookie", "admin_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")
            self.end_headers()
            self.wfile.write(b'{"message":"Signed out."}')
            return
        if route == "/api/admin/posts":
            if not self.is_admin():
                self.send_json({"error": "Admin access required."}, 401)
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                post = json.loads(self.rfile.read(length))
                fields = [post.get(field, "").strip() for field in ("title", "summary", "category", "published_at", "author", "initials", "image_class", "image_url")]
                if not all(fields[:-1]):
                    self.send_json({"error": "All fields except the image are required."}, 400)
                    return
                content = post.get("content", "").strip()
                status = post.get("status", "draft").strip()
                active = 1 if post.get("active", True) in (True, 1, "1", "true", "on") else 0
                if status not in ("draft", "published"):
                    status = "draft"
                with connection() as database:
                    if fields[6] == "featured":
                        database.execute("UPDATE posts SET image_class='desk' WHERE image_class='featured'")
                    database.execute("INSERT INTO posts (title, summary, category, published_at, author, initials, image_class, image_url, content, status, active) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", fields + [content, status, active])
                self.send_json({"message": "Post saved."}, 201)
            except (ValueError, json.JSONDecodeError):
                self.send_json({"error": "Invalid post data."}, 400)
            return
        if route == "/api/call-request":
            try:
                length = int(self.headers.get("Content-Length", 0))
                request = json.loads(self.rfile.read(length))
                service = request.get("service", "Mutual Fund").strip()
                name = request.get("name", "").strip()
                email = request.get("email", "").strip()
                phone = request.get("phone", "").strip()
                message = request.get("message", "").strip()
                if not name or "@" not in email or not phone:
                    self.send_json({"error": "Name, valid email, and phone are required."}, 400)
                    return
                with connection() as database:
                    database.execute("INSERT INTO call_requests (service, name, email, phone, message) VALUES (?, ?, ?, ?, ?)", (service, name, email, phone, message))
                self.send_json({"message": "Your enquiry has been saved. We will contact you soon."}, 201)
            except (ValueError, json.JSONDecodeError, OSError):
                self.send_json({"error": "The request could not be saved. Please try again."}, 400)
            return
        if route == "/api/questions":
            try:
                length = int(self.headers.get("Content-Length", 0))
                question = json.loads(self.rfile.read(length))
                name = question.get("name", "").strip()
                email = question.get("email", "").strip()
                message = question.get("message", "").strip()
                if not name or "@" not in email or len(message) < 5:
                    self.send_json({"error": "Name, valid email, and a question are required."}, 400)
                    return
                with connection() as database:
                    database.execute("INSERT INTO questions (name, email, message) VALUES (?, ?, ?)", (name, email, message))
                self.send_json({"message": "Thanks — your question has been sent."}, 201)
            except (ValueError, json.JSONDecodeError, OSError):
                self.send_json({"error": "The question could not be saved. Please try again."}, 400)
            return
        if route == "/api/reviews":
            try:
                length = int(self.headers.get("Content-Length", 0))
                review = json.loads(self.rfile.read(length))
                name = review.get("name", "").strip()
                text = review.get("review", "").strip()
                rating = max(1, min(5, int(review.get("rating", 5))))
                if not name or len(text) < 10:
                    self.send_json({"error": "Please enter your name and a review of at least 10 characters."}, 400)
                    return
                with connection() as database:
                    database.execute("INSERT INTO reviews (name, review, rating) VALUES (?, ?, ?)", (name, text, rating))
                self.send_json({"message": "Thank you. Your review was saved for approval."}, 201)
            except (ValueError, json.JSONDecodeError):
                self.send_json({"error": "Invalid review."}, 400)
            return
        if route == "/api/admin/upload":
            if not self.is_admin():
                self.send_json({"error": "Admin access required."}, 401)
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                if length > int(MAX_UPLOAD_BYTES * 1.4):
                    self.send_json({"error": "File is too large (max 5 MB)."}, 413)
                    return
                payload = json.loads(self.rfile.read(length))
                data_url = payload.get("data", "")
                header, _, encoded = data_url.partition(",")
                mime = header.split(";")[0].replace("data:", "")
                extension = UPLOAD_EXTENSIONS.get(mime)
                if not encoded or not extension:
                    self.send_json({"error": "Only PNG, JPG, GIF, or WEBP images are supported."}, 400)
                    return
                binary = base64.b64decode(encoded)
                if len(binary) > MAX_UPLOAD_BYTES:
                    self.send_json({"error": "File is too large (max 5 MB)."}, 413)
                    return
                UPLOADS_DIR.mkdir(exist_ok=True)
                filename = f"{secrets.token_hex(8)}{extension}"
                (UPLOADS_DIR / filename).write_bytes(binary)
                self.send_json({"url": f"/uploads/{filename}"}, 201)
            except (ValueError, json.JSONDecodeError, OSError):
                self.send_json({"error": "Could not process the upload."}, 400)
            return
        if route == "/api/admin/reviews":
            if not self.is_admin():
                self.send_json({"error": "Admin access required."}, 401)
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                review = json.loads(self.rfile.read(length))
                name = review.get("name", "").strip()
                text = review.get("review", "").strip()
                image_url = review.get("image_url", "").strip()
                rating = max(1, min(5, int(review.get("rating", 5))))
                if not name or not (text or image_url):
                    self.send_json({"error": "Add a name and either a review or a screenshot URL."}, 400)
                    return
                with connection() as database:
                    database.execute("INSERT INTO reviews (name, review, rating, image_url, status) VALUES (?, ?, ?, ?, 'approved')", (name, text, rating, image_url))
                self.send_json({"message": "Review added and published."}, 201)
            except (ValueError, json.JSONDecodeError):
                self.send_json({"error": "Invalid review."}, 400)
            return
        if route == "/api/comments":
            try:
                length = int(self.headers.get("Content-Length", 0))
                comment = json.loads(self.rfile.read(length))
                post_id = int(comment.get("post_id", 0))
                name = comment.get("name", "").strip()
                text = comment.get("comment", "").strip()
                if not post_id or not name or len(text) < 3:
                    self.send_json({"error": "Post, name, and comment are required."}, 400)
                    return
                with connection() as database:
                    database.execute("INSERT INTO comments (post_id, name, comment) VALUES (?, ?, ?)", (post_id, name, text))
                self.send_json({"message": "Comment saved for approval."}, 201)
            except (ValueError, json.JSONDecodeError):
                self.send_json({"error": "Invalid comment."}, 400)
            return
        self.send_error(404)

    def do_PUT(self):
        route = urlparse(self.path).path
        if not route.startswith("/api/admin/posts/") or not self.is_admin():
            self.send_json({"error": "Admin access required."}, 401)
            return
        try:
            post_id = int(route.rsplit("/", 1)[1])
            length = int(self.headers.get("Content-Length", 0))
            post = json.loads(self.rfile.read(length))
            fields = [post.get(field, "").strip() for field in ("title", "summary", "category", "published_at", "author", "initials", "image_class", "image_url")]
            status = post.get("status", "draft").strip()
            active = 1 if post.get("active", True) in (True, 1, "1", "true", "on") else 0
            if not all(fields[:-1]) or status not in ("draft", "published"):
                self.send_json({"error": "Valid post fields are required."}, 400)
                return
            with connection() as database:
                if fields[6] == "featured":
                    database.execute("UPDATE posts SET image_class='desk' WHERE image_class='featured' AND id != ?", (post_id,))
                result = database.execute("UPDATE posts SET title=?, summary=?, category=?, published_at=?, author=?, initials=?, image_class=?, image_url=?, content=?, status=?, active=? WHERE id=?", fields + [post.get("content", "").strip(), status, active, post_id])
            if result.rowcount == 0:
                self.send_json({"error": "Post not found."}, 404)
                return
            self.send_json({"message": "Post updated."})
        except (ValueError, json.JSONDecodeError):
            self.send_json({"error": "Invalid post data."}, 400)

    def do_DELETE(self):
        route = urlparse(self.path).path
        if not route.startswith("/api/admin/posts/") or not self.is_admin():
            self.send_json({"error": "Admin access required."}, 401)
            return
        try:
            post_id = int(route.rsplit("/", 1)[1])
        except ValueError:
            self.send_json({"error": "Invalid post id."}, 400)
            return
        with connection() as database:
            result = database.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        self.send_json({"message": "Post deleted."} if result.rowcount else {"error": "Post not found."}, 200 if result.rowcount else 404)

    def do_PATCH(self):
        route = urlparse(self.path).path
        if not (route.startswith("/api/admin/reviews/") or route.startswith("/api/admin/comments/")) or not self.is_admin():
            self.send_json({"error": "Admin access required."}, 401)
            return
        try:
            review_id = int(route.rsplit("/", 1)[1])
            status = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)))).get("status", "")
            if status not in ("approved", "rejected", "pending"):
                self.send_json({"error": "Invalid review status."}, 400)
                return
            table = "comments" if route.startswith("/api/admin/comments/") else "reviews"
            with connection() as database:
                result = database.execute(f"UPDATE {table} SET status = ? WHERE id = ?", (status, review_id))
            self.send_json({"message": "Review status updated."} if result.rowcount else {"error": "Review not found."}, 200 if result.rowcount else 404)
        except (ValueError, json.JSONDecodeError):
            self.send_json({"error": "Invalid review request."}, 400)


if __name__ == "__main__":
    PUBLIC_ONLY = True
    initialize_database()
    host = os.environ.get("LET_MONEY_EARN_HOST", "127.0.0.1")
    port = int(os.environ.get("LET_MONEY_EARN_PORT", "8000"))
    server = ThreadingHTTPServer((host, port), BlogHandler)
    threading.Thread(target=refresh_mf_cache_nightly, daemon=True).start()
    threading.Thread(target=build_market_reel_daily, daemon=True).start()
    threading.Thread(target=build_betas_weekly, daemon=True).start()
    display_host = "127.0.0.1" if host == "0.0.0.0" else host
    print(f"Let Money Earn is running at http://{display_host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
