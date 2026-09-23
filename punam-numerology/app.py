from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import json
import os
import secrets
import sqlite3
import sys
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from hmac import compare_digest

ROOT = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
DB_PATH = ROOT / "punam_numerology.db"
ADMIN_PASSWORD = os.environ.get("PUNAM_NUMEROLOGY_ADMIN_PASSWORD")
SESSIONS = set()
PUBLIC_ONLY = False
SITE_URL = "https://numerology.letmoneyearn.in"
SITEMAP_STATIC_PAGES = ("", "services.html", "review.html")

SERVICES = [
    "Life Path & Birth Number Reading",
    "Name Numerology & Corrections",
    "Compatibility & Matchmaking",
    "Business & Brand Numerology",
    "Baby Naming",
    "Lucky Dates & Numbers",
    "Yearly Forecast (Personal Year)",
]


def connection():
    database = sqlite3.connect(DB_PATH)
    database.row_factory = sqlite3.Row
    return database


def initialize_database():
    with connection() as database:
        database.execute("""CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT NOT NULL,
            phone TEXT NOT NULL, dob TEXT DEFAULT '', service TEXT NOT NULL, message TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        database.execute("""CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, review TEXT NOT NULL,
            rating INTEGER NOT NULL DEFAULT 5, status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        database.execute("""CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT, page TEXT NOT NULL DEFAULT 'general', name TEXT NOT NULL,
            comment TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")


class NumerologyHandler(BaseHTTPRequestHandler):
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

    def read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length))

    def serve_robots(self):
        body = (
            "User-agent: *\n"
            "Allow: /\n"
            "Disallow: /admin-login.html\n"
            "Disallow: /admin_bookings.html\n"
            "Disallow: /admin_comments.html\n"
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
            f"<url><loc>{SITE_URL}/{page}</loc><lastmod>{today}</lastmod><changefreq>monthly</changefreq></url>"
            for page in SITEMAP_STATIC_PAGES
        ]
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

    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path
        if route == "/robots.txt":
            self.serve_robots()
            return
        if route == "/sitemap.xml":
            self.serve_sitemap()
            return
        if PUBLIC_ONLY and (route.startswith("/admin") or route.startswith("/api/admin")):
            self.send_error(404)
            return
        if route in ("/admin_bookings.html", "/admin_reviews.html", "/admin_comments.html", "/api/admin/session") and not self.is_admin():
            if route == "/api/admin/session":
                self.send_json({"authenticated": False}, 401)
            else:
                self.send_error(403, "Admin access required")
            return
        if route == "/api/admin/session":
            self.send_json({"authenticated": True})
            return
        if route == "/api/services":
            self.send_json(SERVICES)
            return
        if route == "/api/reviews":
            with connection() as database:
                reviews = [dict(row) for row in database.execute("SELECT id, name, review, rating, created_at FROM reviews WHERE status = 'approved' ORDER BY id DESC")]
            self.send_json(reviews)
            return
        if route == "/api/comments":
            page = parse_qs(parsed.query).get("page", ["general"])[0]
            with connection() as database:
                comments = [dict(row) for row in database.execute("SELECT id, name, comment, created_at FROM comments WHERE page = ? AND status = 'approved' ORDER BY id DESC", (page,))]
            self.send_json(comments)
            return
        if route == "/api/admin/bookings":
            if not self.is_admin():
                self.send_json({"error": "Admin access required."}, 401)
                return
            with connection() as database:
                bookings = [dict(row) for row in database.execute("SELECT * FROM bookings ORDER BY id DESC")]
            self.send_json(bookings)
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
                comments = [dict(row) for row in database.execute("SELECT * FROM comments ORDER BY id DESC")]
            self.send_json(comments)
            return
        file_path = ROOT / ("index.html" if route == "/" else route.lstrip("/"))
        if file_path.is_file() and ROOT in file_path.parents:
            content_type = {".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}.get(file_path.suffix, "application/octet-stream")
            body = file_path.read_bytes()
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
                self.send_json({"error": "Set PUNAM_NUMEROLOGY_ADMIN_PASSWORD before starting the server."}, 503)
                return
            try:
                password = self.read_json().get("password", "")
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
        if route == "/api/booking":
            try:
                booking = self.read_json()
                name = booking.get("name", "").strip()
                email = booking.get("email", "").strip()
                phone = booking.get("phone", "").strip()
                dob = booking.get("dob", "").strip()
                service = booking.get("service", "").strip() or SERVICES[0]
                message = booking.get("message", "").strip()
                if not name or "@" not in email or not phone:
                    self.send_json({"error": "Name, valid email, and phone are required."}, 400)
                    return
                with connection() as database:
                    database.execute("INSERT INTO bookings (name, email, phone, dob, service, message) VALUES (?, ?, ?, ?, ?, ?)", (name, email, phone, dob, service, message))
                self.send_json({"message": "Thank you. Punam will contact you soon to schedule your reading."}, 201)
            except (ValueError, json.JSONDecodeError, OSError):
                self.send_json({"error": "The request could not be saved. Please try again."}, 400)
            return
        if route == "/api/reviews":
            try:
                review = self.read_json()
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
        if route == "/api/comments":
            try:
                comment = self.read_json()
                page = comment.get("page", "general").strip() or "general"
                name = comment.get("name", "").strip()
                text = comment.get("comment", "").strip()
                if not name or len(text) < 3:
                    self.send_json({"error": "Name and comment are required."}, 400)
                    return
                with connection() as database:
                    database.execute("INSERT INTO comments (page, name, comment) VALUES (?, ?, ?)", (page, name, text))
                self.send_json({"message": "Comment saved for approval."}, 201)
            except (ValueError, json.JSONDecodeError):
                self.send_json({"error": "Invalid comment."}, 400)
            return
        self.send_error(404)

    def do_PATCH(self):
        route = urlparse(self.path).path
        if not (route.startswith("/api/admin/reviews/") or route.startswith("/api/admin/comments/")) or not self.is_admin():
            self.send_json({"error": "Admin access required."}, 401)
            return
        try:
            item_id = int(route.rsplit("/", 1)[1])
            status = self.read_json().get("status", "")
            if status not in ("approved", "rejected", "pending"):
                self.send_json({"error": "Invalid status."}, 400)
                return
            table = "comments" if route.startswith("/api/admin/comments/") else "reviews"
            with connection() as database:
                result = database.execute(f"UPDATE {table} SET status = ? WHERE id = ?", (status, item_id))
            self.send_json({"message": "Status updated."} if result.rowcount else {"error": "Not found."}, 200 if result.rowcount else 404)
        except (ValueError, json.JSONDecodeError):
            self.send_json({"error": "Invalid request."}, 400)


if __name__ == "__main__":
    PUBLIC_ONLY = True
    initialize_database()
    host = os.environ.get("PUNAM_NUMEROLOGY_HOST", "127.0.0.1")
    port = int(os.environ.get("PUNAM_NUMEROLOGY_PORT", "8020"))
    server = ThreadingHTTPServer((host, port), NumerologyHandler)
    display_host = "127.0.0.1" if host == "0.0.0.0" else host
    print(f"Punam Numerology is running at http://{display_host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
