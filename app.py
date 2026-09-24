from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import base64
import csv
import html
import io
import json
import os
import re
import secrets
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from hmac import compare_digest

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
DB_PATH = ROOT / "let_money_earn.db"
BREAKOUT_DATA_PATH = ROOT / "breakout_data.json"
HISTORY_CACHE_PATH = ROOT / "price_history_cache.json"
HISTORY_CACHE_TTL_SECONDS = 24 * 3600
HISTORY_SYMBOL_RE = re.compile(r"^[A-Z0-9&\-]{1,20}$")
BREAKOUT_SHEET_ID = "1gLrCYp_GmRSpEkrCVwwEn_Ec97IQr6YfNo7mvPQLZgk"
BREAKOUT_SHEET_GID_CH = "649235540"
BREAKOUT_SHEET_GID_MYB = "1080335833"
BREAKOUT_CACHE_TTL = 15 * 60
SITE_URL = "https://letmoneyearn.in"
SITEMAP_STATIC_PAGES = ("", "services.html", "calculators.html", "review.html", "question.html")
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


def load_history_cache():
    if not HISTORY_CACHE_PATH.is_file():
        return {}
    try:
        return json.loads(HISTORY_CACHE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_history_cache(cache):
    try:
        HISTORY_CACHE_PATH.write_text(json.dumps(cache), encoding="utf-8")
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
    cache = load_history_cache()
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
    save_history_cache(cache)
    return points, False


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
        for post in posts:
            entries.append(
                f"<url><loc>{SITE_URL}/post.html?id={post['id']}</loc>"
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

    def serve_post_page(self):
        post_id = parse_qs(urlparse(self.path).query).get("id", [None])[0]
        template = (ROOT / "post.html").read_text(encoding="utf-8")
        post = None
        if post_id and post_id.isdigit():
            with connection() as database:
                post = database.execute(
                    "SELECT * FROM posts WHERE id = ? AND status = 'published' AND active = 1",
                    (int(post_id),),
                ).fetchone()
        if post:
            post = dict(post)
            page_url = f"{SITE_URL}/post.html?id={post['id']}"
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
            )
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
    display_host = "127.0.0.1" if host == "0.0.0.0" else host
    print(f"Let Money Earn is running at http://{display_host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
