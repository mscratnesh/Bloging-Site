# Let Money Earn — Design

Reference for the site's visual language and how the app is put together. Keep this in sync when either changes.

## 1. Visual design system

### Palette (`styles.css` `:root`)
| Token | Value | Use |
|---|---|---|
| `--ink` | `#17201b` | primary text, dark surfaces |
| `--muted` | `#667069` | secondary text |
| `--paper` | `#f5f4ee` | page background |
| `--line` | `#d9ddd5` | borders/dividers |
| `--lime` | `#d9f06b` | accent (avatars, arrow marks) |
| `--coral` | `#ef795d` | accent (links, emphasis) |
| `--coral-text` | `#a8492f` | accent text (category labels) |
| `--success` | `#2f6b46` | success states |

### Type
- `--serif` (Fraunces) — headings, editorial tone.
- `--sans` (Manrope) — body copy, nav, UI.
- `--mono` (DM Mono) — eyebrows, labels, category tags, uppercase micro-text (`letter-spacing: .08–.1em`).

Headline sizes are fluid (`clamp(48px,7vw,92px)` for the hero `h1`), tight line-height (~0.96–1), negative letter-spacing on display type.

### Layout conventions
- Content max-width ~1180px, centered via `padding: 0 max(24px, calc((100% - 1180px)/2))` on header/footer.
- Section rhythm: a horizontal rule (`border-top`) plus a mono-uppercase `.section-label` precedes each section.
- Cards (`.post-card`, `.feature-card`) use a top rule instead of full borders/shadows — flat, editorial, no rounded corners except circular elements (avatars, `.intro-mark`).
- One breakpoint at `700px` collapses nav into a hamburger (`.menu`) and stacks grids to 1 column.

### Reusable patterns
- `.text-link` / `.post-link` — underlined link with an oversized colored arrow/glyph suffix.
- `.category` / `.eyebrow` — mono, uppercase, coral-tinted labels.
- `.avatar` — lime circle with mono initials.
- Empty/loading states are plain mono-text, no spinners (`.empty-state`, `.loading-note`).

**When adding a new page or component:** reuse these tokens and patterns rather than introducing new colors, fonts, or card treatments. New admin surfaces can be plainer/functional but should still use the `--ink`/`--paper`/`--line` palette and `--mono` for labels to feel part of the same system.

## 2. Architecture

### Stack
Pure Python stdlib — no framework. `http.server.BaseHTTPRequestHandler` (`app.py`) serves both static files and a JSON API over SQLite (`let_money_earn.db`). No build step; pages are static HTML with vanilla JS (`script.js`, `nav.js`, `calculators.js`, `admin_active.js`, `admin_reviews.js`, `post_share.js`) calling the API via `fetch`.

### Two processes, one handler
- `app.py` — public site, port **8000**. Sets `PUBLIC_ONLY = True`, which 404s any `/admin*` or `/api/admin*` route.
- `admin_app.py` — private admin, port **8001**, binds `127.0.0.1` only. Imports `BlogHandler`/`initialize_database` from `app.py` unchanged, so all route logic lives in one place; only the process entry point differs.

Admin session is a random token in `SESSIONS` (in-memory set), set via `HttpOnly` cookie `admin_session` after `/api/admin/login` checks `LET_MONEY_EARN_ADMIN_PASSWORD` with `compare_digest`. No persistence across restarts — restarting either process logs everyone out.

### Data model (SQLite, `let_money_earn.db`)
| Table | Key columns | Notes |
|---|---|---|
| `posts` | title, summary, content, category, status (`draft`/`published`), active (0/1), author, image | listed publicly only when `status='published' AND active=1` |
| `call_requests` | service, name, email, phone, message | Mutual Fund enquiry form; admin-only read (no route shown for listing yet — check `admin.html`) |
| `questions` | name, email, message | from `question.html`; admin view is `admin_questions.html` |
| `reviews` | name, review, rating, status (`pending`/`approved`/`rejected`), image_url | public submissions default `pending`; admin-added reviews (`/api/admin/reviews` POST) are inserted pre-`approved` |
| `comments` | post_id (FK→posts), name, comment, status | same pending/approve flow as reviews, scoped per post |

`initialize_database()` runs `CREATE TABLE IF NOT EXISTS` + ad-hoc `ALTER TABLE` migrations for older DBs, then seeds demo posts/reviews/comments only if the tables are empty. This is the only migration mechanism — there's no migration framework, so schema changes go directly into this function.

### Page ↔ route map
| Page | Purpose | Reads | Writes |
|---|---|---|---|
| `index.html` | home, post grid | `/api/posts` | — |
| `post.html` | article detail | `/api/posts/:id`, `/api/comments/:id` | `/api/comments` (submit) |
| `services.html` | Mutual Fund enquiry | — | `/api/call-request` |
| `question.html` | ask-a-question form | — | `/api/questions` |
| `review.html` | submit a review | — | `/api/reviews` |
| `calculators.html` | finance calculators | client-side only (`calculators.js`) | — |
| `admin-login.html` | admin auth | — | `/api/admin/login` |
| `admin.html` | posts CRUD | `/api/admin/posts` | POST/PUT/DELETE `/api/admin/posts` |
| `admin_reviews.html` | moderate reviews | `/api/admin/reviews` | PATCH status, POST new |
| `admin_comments.html` | moderate comments | `/api/admin/comments` | PATCH status |
| `admin_questions.html` | view submitted questions | `/api/admin/questions` | read-only |

### Conventions to follow when extending
- New public submission flow = new table + `pending`-by-default status column if it needs moderation, plus a matching `admin_<name>.html` page and `/api/admin/<name>` GET + PATCH routes — mirror the `reviews`/`comments` pattern.
- Every admin route must check `self.is_admin()` first and return 401 JSON, not a redirect.
- Keep all HTTP logic inside `BlogHandler` in `app.py`; `admin_app.py` should stay a thin entry point (host/port + startup message only).
- Uploaded images go to `/uploads/<random>.<ext>` via `/api/admin/upload` (5MB cap, PNG/JPG/GIF/WEBP only) — reuse this endpoint rather than adding a new upload path.
