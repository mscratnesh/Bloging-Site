from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
import base64
import json
import os
import secrets
import sqlite3
from http.cookies import SimpleCookie
from hmac import compare_digest

ROOT = Path(__file__).parent
DB_PATH = ROOT / "let_money_earn.db"
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

    def do_GET(self):
        route = urlparse(self.path).path
        if PUBLIC_ONLY and (route.startswith("/admin") or route.startswith("/api/admin")):
            self.send_error(404)
            return
        if route in ("/admin.html", "/admin_reviews.html", "/admin_comments.html", "/api/admin/session") and not self.is_admin():
            if route == "/api/admin/session":
                self.send_json({"authenticated": False}, 401)
            else:
                self.send_error(403, "Admin access required")
            return
        if route == "/api/admin/session":
            self.send_json({"authenticated": True})
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
                if not all(fields):
                    self.send_json({"error": "All fields are required."}, 400)
                    return
                content = post.get("content", "").strip()
                status = post.get("status", "draft").strip()
                active = 1 if post.get("active", True) in (True, 1, "1", "true", "on") else 0
                if status not in ("draft", "published"):
                    status = "draft"
                with connection() as database:
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
            if not all(fields) or status not in ("draft", "published"):
                self.send_json({"error": "Valid post fields are required."}, 400)
                return
            with connection() as database:
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
    server = ThreadingHTTPServer(("127.0.0.1", 8000), BlogHandler)
    print("Let Money Earn is running at http://127.0.0.1:8000")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
