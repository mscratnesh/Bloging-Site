# Let Money Earn Blog

A professional financial education blog powered by Python's standard library and SQLite.

## Run on Windows

From this folder, run the public website:

```powershell
py app.py
```

Open http://127.0.0.1:8000. The first run creates `let_money_earn.db` and seeds the finance articles.

Mutual Fund call requests are saved in the `call_requests` table.

## Production hosting (Windows VM)

The live site (letmoneyearn.in) runs on a Windows VM using the prebuilt `dist/` folder — packaged executables (`LetMoneyEarn.exe`, `LetMoneyEarnAdmin.exe`), static assets, the SQLite database, and a set of `.bat` scripts. It does not run `python app.py` directly in production.

**Architecture:** nginx (port 80/443) reverse-proxies to `LetMoneyEarn.exe` (public site, `127.0.0.1:8000`). `LetMoneyEarnAdmin.exe` (admin app, `127.0.0.1:8001`) is never exposed through nginx or the firewall — it's only reachable locally on the VM.

### One-time setup (already done on the current VM)

- `dist\install_nginx_http.bat` — downloads and installs nginx to `C:\nginx`.
- `dist\setup_http_domain.bat` — copies `dist\nginx.conf` to `C:\nginx\conf\nginx.conf` and does the first start.
- `dist\setup_firewall.bat` — opens ports 80, 443, 8000 in Windows Firewall.
- **HTTPS**: issued via [Certify The Web](https://certifytheweb.com/) (Let's Encrypt, HTTP-01 challenge). `dist\nginx.conf` serves the ACME challenge from `C:\nginx\acme-challenge`. On renewal, Certify's deployment tasks export the cert/key to `C:\nginx\ssl\letmoneyearn.pem`/`.key` and run `dist\reload_nginx_ssl.bat` to reload nginx — no manual steps needed for renewal.

### Deploying an update

1. Stop everything:
   ```bat
   taskkill /IM LetMoneyEarn.exe /F
   taskkill /IM LetMoneyEarnAdmin.exe /F
   C:\nginx\nginx.exe -s stop
   ```
2. Replace the VM's `dist` folder with the new build — **except** `let_money_earn.db` (and `uploads\`, if present). The live database holds real articles, comments, reviews, and questions; never overwrite it with a locally-built copy. Update it in place with targeted SQL instead of replacing the file. Make sure the build includes the market-tool data files (`momentum_teaser.json`, `breakout_data.json`) — see [Building the executables](#building-the-executables).
3. Run `dist\setup_all.bat` as Administrator — copies `nginx.conf`, tests it, and starts nginx plus both apps.
4. Verify at https://www.letmoneyearn.in/.

### Starting after a reboot

nginx and both apps run as plain processes, not Windows services, so they don't survive a reboot on their own.

- The public site + nginx auto-start via a Task Scheduler task running `dist\autostart_public.bat` (registered with `schtasks /create ... /sc onstart /ru SYSTEM`). It's idempotent — safe to run manually too.
- The admin app is **not** auto-started (avoids storing its password on disk). Run `dist\start_admin.bat` and enter the password manually whenever you need it.

### Featuring a post on the homepage

The homepage hero story is whichever post has `image_class = 'featured'` in the database — there's only ever one. In the admin editor, check **"Feature on homepage"** on the post you want highlighted and save; the server automatically un-features whichever post had it before.

## Market tools

Two pages in the site menu are data-driven stock tools rather than articles: Breakout Desk and Momentum Study. Both are for information only and carry a not-investment-advice disclaimer.

### Breakout Desk (`breakout-desk.html`)

NSE stocks breaking out of multi-year bases and cup-and-handle patterns.

- **Data:** read live from the tracked Google Sheet (IDs in `app.py`, `BREAKOUT_SHEET_*`) via `/api/breakout-desk`. The server keeps the result in memory for 15 minutes; if the sheet can't be reached it serves the last cached copy, then falls back to `breakout_data.json`.
- **SL** comes from column H of the sheet's multi-year-base tab (also used for cup-and-handle rows, matched by symbol). For open positions the page replaces it with the low of the week before entry once the chart loads.
- **Charts:** `/api/breakout-desk/history/<SYMBOL>` — daily prices from Yahoo (Stooq and a second Yahoo host as fallbacks), cached on disk for 24 hours in `price_history_cache.json`.
- **Fundamentals** in the expanded card view: `/api/breakout-desk/fundamentals/<SYMBOL>` — valuation, profitability and growth ratios from Yahoo Finance, cached for 24 hours in `fundamentals_cache.json`, shown with an "as of" date.

### Momentum Study (`momentum-study.html`)

A public **teaser** for the momentum research: a short intro, headline numbers and the equity curve against the Nifty 500, with **no rules**. It reads `momentum_teaser.json` (curve and headline numbers only), a **fixed snapshot** (prices to 24 Sep 2026) that the site never refreshes.

The full study (every rule, stress test and table) is kept out of the site build in `study/momentum-study-full.html`, which reads `momentum_study.json`; it may become paid content later, so don't deploy either file until they sit behind a login. To view it locally, serve the repo root (`py -m http.server`) and open `/study/momentum-study-full.html`.

- **Strategy (base case):** a stock must be within 25% of its all-time high, trade above ₹1 Cr average daily turnover and close above its SMA233; ranked by average Sharpe (plain % return ÷ annualised volatility) over 252/184/126/63 sessions. Hold the top 10, sell a holding only when it leaves the top 30, rebalance at month-end. Market filter (checked daily): move everything to a liquid fund on the day Nifty 500 completes 3 closes in a row below its 200-day SMA (`Params.market_check = "daily"`, `confirm_days = 3`); buy back at a month-end above the SMA.
- **What it tests:** survivorship bias (point-in-time vs today's list), skill vs luck (random portfolios), parameter sensitivity, rebalance-day timing, costs, Indian capital-gains tax, capacity, risk, a 10% stop-loss, gold (GOLDBEES) instead of the liquid fund, and the 50/100/150/200-day average behind the market filter.
- **Stocks tested:** every result uses the point-in-time Nifty 500 lists in `study/constituents/` (`Params.universe = "pit500"`). `nifty750_backtest_list.csv` (the NSE list of 24 Sep 2026) is used only for the biased comparison runs, and is linked from the page.
- **Google Sheet scanner:** `apps-script/MomentumScan.gs` is the Apps Script behind the owner's Momentum Sharpe Scan sheet. It uses the same stock rules and formulas as the base case (checked stock-by-stock against `momentum.py`'s `Scanner`), so keep the two in sync when either changes. Exception: the sheet and `momentum.py` still apply the market filter only at month-end; the study's base case now exits after 3 daily closes in a row below the 200-day SMA.

There used to be a separate Momentum Scan page (`momentum-scan.html`) showing the latest ranked list; it was removed from the site and can be restored from git history if needed. `momentum.py` (the backtest engine behind it) is kept: it builds the local price cache `momentum_prices.json` (git-ignored) that the study reads, and reads its stocks only from `nifty750_backtest_list.csv`, so reruns always test the same 750 stocks. Its output `momentum_state.json` is no longer shown on the site.

Everything to reproduce the study is in `study/` (run `py momentum.py` first if `momentum_prices.json` is missing):

- `study/fetch_constituents.py` — downloads archived Nifty 500 constituent lists from the Wayback Machine into `study/constituents/` (already done; the lists are committed).
- `study/fetch_extra_prices.py` — fetches prices for past index members outside the 750 into `study/prices_extra.json` (git-ignored). `study/renames.py` maps renamed NSE symbols; `study/prices_missing.json` lists past members with no price data (mostly delisted or merged).
- `study/prices_cash.json` — GOLDBEES daily prices for the "gold instead of the liquid fund" test (fetched with `momentum.fetch_daily("GOLDBEES.NS", "7y")`).
- `study/backtest_report.py` — writes `study/backtest_report.html`, a detailed month-by-month backtest on the point-in-time Nifty 500 lists (template: `study/backtest_report_template.html`).
- `study/momentum_study.py` — runs every variant offline (needs `numpy`, ~30 seconds) and writes `momentum_study.json` (full study) and `momentum_teaser.json` (public page).

```powershell
py study\fetch_extra_prices.py   # only if study\prices_extra.json is missing
py study\momentum_study.py
```

### Momentum book (`book/`)

"Riding the Winners", a plain-English book (Word, A4) on momentum investing built from the study: what momentum is, its history, why it works, the exact rules, the honest backtest and every stress test. All numbers and charts come from `momentum_study.json`, so rebuild it after rerunning the study. Not part of the site build.

```powershell
cd book; npm install; cd ..        # once (installs docx; node_modules is git-ignored)
py book\make_charts.py             # charts\*.png and book_extra.json
node book\build_book.js            # Momentum_Investing_Book.docx
```

Open the .docx in Word and update the table of contents (right-click it > Update Field) after rebuilding.

## Building the executables

The VM runs PyInstaller builds (the `.spec` files are git-ignored but live in this folder):

```powershell
py -m PyInstaller --noconfirm LetMoneyEarn.spec
py -m PyInstaller --noconfirm LetMoneyEarnAdmin.spec
```

Then copy the site files next to the executables in `dist\`: every `*.html`, `*.js`, `*.css`, plus `breakout_data.json` and `momentum_teaser.json` (not `momentum_study.json`: it holds the full study). Never copy `let_money_earn.db` over the VM's live database. The runtime caches (`price_history_cache.json`, `fundamentals_cache.json`) are created on the VM as needed; `momentum_prices.json` and `study\prices_extra.json` are only for regenerating snapshots locally and don't belong in `dist`.

## Punam Numerology (subdomain site)

`punam-numerology/` is a separate, standalone site — services + consultation booking for a numerology practice, meant to run at `numerology.letmoneyearn.in`. It reuses the same pure-Python/SQLite pattern as the main site but is its own app with its own database; it does not share content or the admin login with the finance blog.

Run it locally the same way:

```powershell
cd punam-numerology
py app.py
```

Open http://127.0.0.1:8020. The first run creates `punam_numerology.db`. Bookings from the consultation form land in the `bookings` table; reviews and comments are moderated the same pending/approved way as the main site.

Admin app (bookings inbox + review/comment moderation), in a second PowerShell window:

```powershell
cd punam-numerology
$env:PUNAM_NUMEROLOGY_ADMIN_PASSWORD="your-strong-password"
py admin_app.py
```

Open http://127.0.0.1:8021/admin-login.html.

**Content to review before going live:** the bio on the homepage, the services list and "contact for pricing" note on `services.html`, and the disclaimer wording — these are placeholders and should reflect Punam's actual background, offerings, and any real pricing.

**Going live on `numerology.letmoneyearn.in`:** this isn't wired into production yet. To deploy it alongside the main site on the same Windows VM:
1. Add a DNS A record for `numerology.letmoneyearn.in` pointing at the VM's IP (same as the existing `letmoneyearn.in` record).
2. Package it the same way as the main site — a PyInstaller `.spec` mirroring `LetMoneyEarn.spec`/`LetMoneyEarnAdmin.spec` — or run `py app.py`/`py admin_app.py` directly on the VM with `PUNAM_NUMEROLOGY_HOST=0.0.0.0`.
3. Add a new `server` block to `dist/nginx.conf` for `numerology.letmoneyearn.in` that proxies to `127.0.0.1:8020` (copy the existing block, swap `server_name` and `proxy_pass`).
4. Include `numerology.letmoneyearn.in` in the Certify The Web certificate (it can issue a multi-domain cert, or a separate one) so HTTPS covers the subdomain.
5. Add the new app to the autostart scripts (`dist\autostart_public.bat` equivalent) so it survives a reboot, same as the main site.

## Private admin app

Open a second PowerShell window and run:

```powershell
$env:LET_MONEY_EARN_ADMIN_PASSWORD="your-strong-password"
py admin_app.py
```

Open http://127.0.0.1:8001/admin-login.html. The admin app binds to `127.0.0.1` only and is not served by the public app on port 8000.

Customer reviews submitted on the public site remain pending. After signing in, moderate them at http://127.0.0.1:8001/admin_reviews.html and approve them before they appear publicly.

Article comments are submitted from each detailed article page and remain pending until approved at http://127.0.0.1:8001/admin_comments.html.
