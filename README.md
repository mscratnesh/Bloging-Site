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
2. Replace the VM's `dist` folder with the new build — **except** `let_money_earn.db` (and `uploads\`, if present). The live database holds real articles, comments, reviews, and questions; never overwrite it with a locally-built copy. Update it in place with targeted SQL instead of replacing the file. Make sure the build includes the market-tool data files (`momentum_teaser.json`, `momentum_nse_teaser.json`, `etf_teaser.json`, `breakout_data.json`) — see [Building the executables](#building-the-executables).
3. Run `dist\setup_all.bat` as Administrator — copies `nginx.conf`, tests it, and starts nginx plus both apps.
4. Verify at https://www.letmoneyearn.in/.

### Starting after a reboot

nginx and both apps run as plain processes, not Windows services, so they don't survive a reboot on their own.

- The public site + nginx auto-start via a Task Scheduler task running `dist\autostart_public.bat` (registered with `schtasks /create ... /sc onstart /ru SYSTEM`). It's idempotent — safe to run manually too.
- The admin app is **not** auto-started (avoids storing its password on disk). Run `dist\start_admin.bat` and enter the password manually whenever you need it.

### Featuring a post on the homepage

The homepage hero story is whichever post has `image_class = 'featured'` in the database — there's only ever one. In the admin editor, check **"Feature on homepage"** on the post you want highlighted and save; the server automatically un-features whichever post had it before.

## Market tools

The site menu has a **Calculators** dropdown (All Calculators: `calculators.html`; Loan EMI & Prepayment: `loan-prepayment.html`; Risk Profile & Goal SIP: `goal-sip-calculator.html`; Portfolio Beta: `portfolio-beta.html`; MF Holdings Explorer: `mf-holdings.html`), a **Mutual Funds** dropdown (Rolling Returns Compare: `mf-compare.html`; Fund SIP Calculator: `mf-sip.html`; Fund SWP Calculator: `mf-swp.html`), a **Studies** dropdown (Momentum Study, Gold vs Nifty, Multi-Year Breakout: `breakout-study.html`, NIFTY Iron Fly: `nifty-iron-fly.html`), a **Markets** dropdown (NSE Index Dashboard: `nse-indices.html`; F&O OI Change: `oi-change.html`) and Sheets, which sells the Google Sheets behind them. The dropdown markup is repeated in every public page's header; its styles are at the end of `styles.css` and its open/close script in `nav.js`. All of them are for information only and carry a not-investment-advice disclaimer. Every public page's footer links to the Privacy Policy (`privacy.html`), which covers the forms, server logs, cookies and the Google AdSense wording AdSense requires; update it if the site starts collecting anything new.

### Draft articles (`drafts/`)

`drafts/articles.py` holds draft articles (HTML, in the same format the admin editor saves). `py drafts/build_drafts.py` writes `drafts/articles.json` and a readable preview of each one in `drafts/preview/` (open `index.html`). `build_drafts.py` sets each article's status (currently `published`) and dates it the day it runs. To load them into the live site, start the admin app (`dist\start_admin.bat`) and run `powershell -ExecutionPolicy Bypass -File import_articles\import_drafts.ps1` from `dist` (the build copies both files there); it asks for the admin password and skips any title already on the site. Edit or unpublish them from the admin afterwards.

### Fund Compare (`mf-compare.html`)

A public mutual fund comparison tool (menu: **Mutual Funds → Rolling Returns Compare**; the homepage also links to it from a card next to the Kindle books). Pick up to six schemes and a holding period (1–10 years) to see rolling returns (CAGR from every NAV date), the range of outcomes (average, median, worst, best, spread, share of losing periods), how the returns fall into bands, how often each fund beat the others on the same dates, growth of ₹10,000 with volatility and worst fall, and trailing 1/3/5/10-year returns. A link opens the SIP calculator with the same funds. By default only the dates all chosen funds share are compared. The chosen funds and settings are kept in the URL (`?funds=122639,120716&years=5`), so a comparison can be shared as a link.

### Fund SIP Calculator (`mf-sip.html`)

Menu: **Mutual Funds → Fund SIP Calculator**. Pick up to six funds, a monthly amount, a start month, a SIP date and an optional yearly step-up, and see what the SIP would have become on the funds' actual NAVs: each instalment buys at the first NAV on or after its date, and every fund is valued on the latest date they all have a NAV. Shows a value-vs-invested chart and a table of invested, value, gain and XIRR. It is the same script as Fund Compare (`mf-compare.js`), switched to SIP mode by `<body data-mf-page="sip">`, and uses the same data routes below. Settings are kept in the URL (`?funds=118955&sip=10000&sipfrom=2016-09&sipday=5&stepup=10`). The Calculators page keeps its own SIP calculator, which assumes a fixed return.

### Fund SWP Calculator (`mf-swp.html`)

Menu: **Mutual Funds → Fund SWP Calculator**. Pick up to six funds, an amount invested, a monthly withdrawal, a start month, a withdrawal date and an optional yearly increase. The lump sum buys units at the first NAV on or after the start date; from the next month each withdrawal sells units at the first NAV on or after its date, until the latest common NAV or until the units run out. Shows a value chart (with the cumulative amount withdrawn), a table of total withdrawn, value left, run-out date, lowest value, XIRR and "most it could pay" (the largest monthly withdrawal that would have lasted, found by bisection), and a second table that reruns the same SWP from every start month for 5–20 years (share that lasted, median/worst/best value left, worst start month). Same script as Fund Compare (`mf-compare.js`), switched by `<body data-mf-page="swp">`. Settings are kept in the URL (`?funds=122639&amount=1000000&swp=6000&swpfrom=2016-09&swpday=5&stepup=6&horizon=10`). The Calculators page keeps its own fixed-return SWP calculator and links here.

- **Data:** NAV history from [mfapi.in](https://www.mfapi.in/) (AMFI data), fetched by the server: `/api/mf/search?q=` (searches mfapi.in's full scheme list, about 40,000 schemes, matching every word typed in any order; the list is saved in `mf_nav_cache/schemes.json`) and `/api/mf/nav/<scheme code>` (full history, cached on disk in `mf_nav_cache/<code>.json`, git-ignored; if mfapi.in can't be reached the last saved copy is served). Both caches last until midnight IST: the public app loads the scheme list when it starts, and just after midnight a background thread re-fetches it and every cached fund (`refresh_mf_cache_nightly`), so each day starts on the previous evening's NAVs. All return maths runs in the browser (`mf-compare.js`).
- The "+ Nifty 50 index fund" button and the ready-made comparisons use fixed scheme codes (`BENCHMARK_CODE`, `PRESETS` in `mf-compare.js`).
- Returns come from published NAVs and ignore exit loads and taxes.

### Risk Profile & Goal SIP Calculator (`goal-sip-calculator.html`)

Menu: **Calculators → Risk Profile & Goal SIP**, also linked from the top of `calculators.html`. Kept out of search for now (`noindex`, not in `SITEMAP_STATIC_PAGES`) until compliance signs it off (BRS CR-08). Everything runs in the browser and nothing is stored or sent. Ten scored questions give a risk capacity score (Q1–5) and a willingness score (Q6–10); the lower one picks one of five profiles and its equity/debt/gold mix, with equity capped for goals under 7 years. For up to six goals it shows the inflated cost, monthly SIP (start of month), step-up SIP and lumpsum, funds goals from the monthly surplus in priority order, and lists what-if levers for goals left short. "Save as PDF" prints an A4 report with the disclaimers on every page.

- `goal-sip-config.js`: everything compliance reviews (CR-09): ARN, score bands, allocations, horizon caps, default rates and inflation, and all question and report wording (`strings.en`, so a Hindi block can be added).
- `goal-sip-calc.js`: the maths, no DOM. Tests: `node --test tests/goal-sip.test.js` checks every figure against a month-by-month simulation to within ₹1.
- `goal-sip.js`: the steps, the live report and printing.

After sign-off: change the page's robots meta to `index, follow` and add the page to `SITEMAP_STATIC_PAGES` in `app.py`.

### Loan EMI & Prepayment (`loan-prepayment.html`)

Menu: **Calculators → Loan EMI & Prepayment**; the EMI calculator on `calculators.html` links here. Everything runs in the browser (`loan-prepayment.js`), with no server route. Enter a loan (amount, rate, tenure, first EMI month) and any prepayments: a one-off amount after a chosen EMI, a yearly amount after every 12th EMI, a monthly amount, and a yearly EMI increase. Prepayments either shorten the tenure (same EMI) or lower the EMI (recalculated over the remaining original tenure). Shows interest saved, the new closing date, a balance chart and a year-by-year schedule. "Prepay or invest?" gives both plans the same monthly budget until the original loan would end and compares the wealth each builds at an after-tax investment return, plus the break-even return (the loan's effective yearly rate). Assumes a fixed rate and ignores prepayment charges and home-loan tax breaks. Settings are kept in the URL (`?amount=5000000&rate=8.5&years=20&yearly=100000&mode=emi`).

### Portfolio Beta Calculator (`portfolio-beta.html`)

Menu: **Calculators → Portfolio Beta**, also listed on `calculators.html` and in the sitemap; `/tools/portfolio-beta/` redirects here. Visitors paste stocks and mutual funds (Excel rows, CSV, a Zerodha holdings export or a bare `Symbol Qty` list) and see their portfolio's beta against Nifty 50, a 10% fall estimate, the Nifty hedge notional, a sortable table and a hedge sizer. "Download sample (CSV)" saves the same sample "Try a sample" uses (one `SAMPLE` array in the page), built in the browser with a UTF-8 BOM so Excel opens it cleanly. All parsing and maths run in the browser; the page makes no POSTs. It downloads `/data/betas.json`, `/data/mf_betas.json` (only once a pasted row looks like a fund) and `/api/nifty-hedge` (once results show).

- **Funds** are matched by ISIN or AMFI code (exact) or by name: every pasted word must be in the scheme name (prefixes like "pru" and run-together words like "bluechip" count), on the same plan (Direct only if the text says so), fewest extra words wins. Bracketed old names such as "(erstwhile Bluechip Fund)" match without counting as extras, and overseas funds need a foreign-market word. Name matches are listed for the visitor to check ("?" marks a near tie or an inexact match).
- **Hedge sizer:** futures lots = amount ÷ (futures price × lot), put lots = amount ÷ (spot × lot), cost = lots × lot × closing premium, with a 10% fall example. `app.py`'s `parse_nifty_hedge` takes NIFTY's lot size, spot, futures prices and put closes (80–101% of spot, open interest > 0, the monthly expiries at least 7 days away) from the F&O bhavcopy `fetch_oi_change` already downloads for the OI page, and serves them at `/api/nifty-hedge`. The page lists every rule, the data source and the disclaimer, plus a visible FAQ that is repeated word for word in the page's `FAQPage` JSON-LD (with `WebApplication` and a Home › Calculators breadcrumb): edit both together, since Google ignores FAQ markup that doesn't match the page.

`betas.py` builds `data/betas.json` (beta, R², last close and observation count for about 2,600 NSE symbols) from the last 250 NSE cash-market bhavcopy files (UDiFF, `nsearchives.nseindia.com`). Daily return is `ClsPric / PrvsClsgPric - 1`: NSE adjusts the previous close on ex-dates, so splits and bonuses need no extra step. Series EQ/BE/BZ, moves beyond ±35% are dropped as bad prints, at least 120 shared days, benchmark NIFTYBEES. Don't switch it to NSE's MCP data service: NSE limits that to non-commercial use.

`mf_betas.py` (kept separate) builds `data/mf_betas.json`: beta, R², last NAV, observation count, ISIN and category for about 3,300 open-ended Growth plans. No portfolio holdings are needed: each fund's daily NAVs come from AMFI's NAV history download (`portal.amfiindia.com`, one ~27 MB file per month for every scheme), are read on NIFTYBEES's trading days from the bhavcopy cache, and go through the same `betas.compute()`, so stock and fund betas add up. IDCW/dividend plans are skipped (payouts look like falls), NAV moves beyond ±15% are dropped, and overseas funds get `"x": 1` so the page can warn that their betas read low.

- **Schedule:** the server's `build_betas_weekly` thread runs `betas.py` and then `mf_betas.py` on Fridays from 8:15 pm IST. The stock build retries every 30 minutes until Friday's file is in (or midnight passes, for a Friday holiday); the fund build is done once it succeeds after 8:15 pm (AMFI publishes Friday's NAVs late at night, so it may run to Thursday). A failed run retries in 2 hours. A missed week, or a first start with no data, builds at startup. The first builds download about 250 bhavcopies and 13 months of AMFI files (about 6 minutes in all); later builds fetch only the new days and the current month.
- **Run by hand:** `py betas.py`, then `py mf_betas.py` (options: `--end YYYY-MM-DD`, `--days`, `--min-obs`). Each exits non-zero and keeps its previous JSON if fewer than 200 trading days come out, NIFTYBEES is missing, or fewer than 1,000 stock / 1,500 fund betas come out. Files are written to a temp file and swapped in, so visitors never get half a file.
- **Files** (all git-ignored, created on first run, keep them on the VM across deploys): `data/betas.json` and `data/mf_betas.json`; `var/bhavcopy_cache/` (zips, pruned after 400 days, about 50 MB); `var/amfi_nav_cache/` (one gzip per month, about 1.3 MB each; a month is final once fetched 7 days after it ends); `betas.db`, the run log (`beta_runs` and `mf_beta_runs` tables: one row per run with status, as-of date, count and error). It is a separate file: the blog's `let_money_earn.db` is never touched. Override the paths with `BETA_JSON_PATH`, `MF_BETA_JSON_PATH`, `BHAVCOPY_CACHE_DIR`, `AMFI_NAV_CACHE_DIR` and `BETA_DB_PATH`.
- **Caching:** `app.py` serves both JSON files gzipped (`mf_betas.json` is ~480 KB, ~80 KB gzipped) with `Cache-Control: public, max-age=3600` and an ETag, so browsers revalidate with a cheap 304.
- **Tests:** `py -m unittest tests.test_betas` (no network): `compute()` recovers known betas of 1.6, 0.5 and 1.2 from synthetic data with a 1:1 bonus; a synthetic fund's beta of 0.8 is recovered across a missing NAV; AMFI parsing keeps only open-ended Growth plans; failed sanity checks leave the old files untouched; `parse_nifty_hedge` picks monthly puts near spot; and the page, redirect, gzip and JSON headers.

### Mutual Fund Holdings Explorer (`mf-holdings.html`)

Menu: **Calculators → MF Holdings Explorer**, also on `calculators.html` and in the sitemap; `/tools/mf-holdings/` redirects here. Visitors pick up to five funds and see each fund's holdings and asset mix, the sector split side by side, overlap between each pair (sum over shared stocks of the smaller weight), a combined look-through for amounts they enter, and "which funds hold this stock?". Choices stay in the browser and the URL (`?f=<ids>&a=<amounts>`); no POSTs. The page carries SEBI's mutual fund risk warning, the distributor disclosure and no ratings or invest buttons.

`mf_holdings.py` builds `data/mf_holdings/` from the monthly portfolio statements SEBI makes fund houses publish by the 10th. AMFI only links to them, so each fund house is fetched from its own site through the request its disclosure page makes: SBI (`GetSchemePortfolioSheets`), ICICI Prudential (`apimf…/nms/v1/downloads/files`; files under `/blob`), HDFC (`cms.hdfcfund.com …/monthfortportfolio`; its HTML page blocks bots, the API doesn't), Nippon (page HTML, `NIMF-MONTHLY-PORTFOLIO-*.xls`), Aditya Birla (`FactsheetAccordionById`; files from the main domain, the Azure CDN host doesn't resolve everywhere), Axis (`/cms/token` anonymous token, then `/cms/get-scheme-documents`), UTI (`/api/get-consolidate-portfolio-disclosure`), Mirae (`/AjaxService/GetDownloadsData`), DSP and PPFAS (page HTML) and Motilal Oswal (`search-documents.json`). Kotak is not covered: its site puts automated visitors behind an hCaptcha, which we don't try to get around.

- **Parsing:** one generic parser for all of them, since every file follows SEBI's layout. It finds each header row (ISIN + "% to NAV/Net Assets/AUM" + instrument name), maps columns by name, takes rows with an ISIN, sorts them into equity / foreign / debt / fund units / REIT-InvIT / derivatives by the statement's section lines, normalises weights given as fractions, and reads the scheme name from the rows above the header (skipping fund-house names, descriptions such as "(An open ended…)", TOTAL rows and footnotes). A second table in the same sheet without a title (defaulted securities, derivatives) joins the scheme above. Scheme names are matched to AMFI codes from `mf_betas.json` where possible (about 70%; ETFs and FMPs aren't in that file).
- **Output:** `index.json` (every scheme with id, fund house, as-of date, AMFI codes; ~24 KB gzipped), `f/<id>.json` per scheme (~2 KB, loaded when picked), `stocks.json` (ISIN → funds holding it; ~280 KB gzipped, loaded only for the stock lookup). The folder is written beside the live one and swapped in. `app.py` serves `/data/mf_holdings/` (strict path pattern) gzipped with an hour's cache and an ETag.
- **Schedule:** `build_mf_holdings_monthly` runs on the 15th of each month from 9 am IST for the month just ended. A fund house that fails or hasn't published keeps its last good month (each scheme shows its own as-of date) and is retried alone once a day for three days. It publishes only if at least 8 fund houses have data; otherwise the previous data stays.
- **First run before the 10th:** a fund house with no saved month that hasn't published last month yet is fetched for the month before instead, so a fresh VM gets data straight away. The final folder swap retries for up to a minute, because Windows antivirus can briefly lock the ~1,000 new files ("Access is denied").
- **Run by hand:** `py mf_holdings.py` (last month-end), `py mf_holdings.py --month 2026-08`, or `--only sbi hdfc` to refetch some fund houses. A full run downloads ~350 files in about a minute.
- **Files** (git-ignored; keep on the VM): `data/mf_holdings/`; `var/mf_holdings/<amc>.json` (each fund house's last good month); runs in `betas.db`, table `mf_holdings_runs`. Paths: `MF_HOLDINGS_DIR`, `MF_HOLDINGS_CACHE_DIR`.
- **When a fund house changes its site:** that house fails and keeps last month's data (the run log says which and why). Fix its finder function (`_sbi`, `_hdfc`, …) in `mf_holdings.py`; parsing rarely needs changes.
- **Tests:** `py -m unittest tests.test_mf_holdings` (no network): SBI- and UTI-style workbooks (labels, stacked schemes, fraction weights, foreign ISINs, InvITs, derivatives tables), zips, AMFI name matching, falling back to a fund house's last good month, keeping old data when too few parse, and the routes' path checks.

### Sheets for sale (`sheets.html`)

A one-page sales page (menu: **Sheets**) for the two Google Sheets: the Momentum Sharpe Scan (₹4,999) (`apps-script/MomentumScan.gs`) and the Multi-Year Breakout Tracker (₹500, `apps-script/BreakoutTracker.gs`); both together ₹5,499. It describes what each sheet does and deliberately doesn't link to the studies. Orders go through the same `/api/call-request` route as the Services form and land in the `call_requests` table with `service` set to the chosen sheet (for example `Momentum Sharpe Scan sheet (₹4,999)`). Buyers pay first by UPI (`mscratnesh@oksbi`; the QR code is `upi-qr.png`, cropped from the Google Pay QR, and on phones a `upi://pay` link carries the amount for the chosen option) and enter the UPI transaction ID in the form; it is saved at the start of `message`. There is no admin page for orders yet, so read them from the database, match the transaction ID against the UPI app, then share a copy of the sheet with the buyer's Google account. Keep the feature lists on the page in step with the scripts when their rules change, but describe what each sheet does without the exact rules (no thresholds, windows or averages): the sheets are what is being sold.

### Gold vs Nifty (`gold-vs-nifty.html`)

A one-page summary of the Gold vs Nifty rotation (NiftyBeES or a Momentum 50 ETF vs GoldBeES, switching when their price ratio breaks out of its recent range): the idea, headline backtest results for both versions (Feb 2010 to May 2026, after 20% STCG and STT) and limits, ending in a link to the ebook on Amazon. It keeps the exact rules for the book and sits under Studies in the menu. Its numbers come from the handbook (section 7.2). The source files (`study/GoldVsNifty.xlsx`, the handbook PDF and Word file) are git-ignored because the handbook is sold; the spreadsheet's trade log uses 15% STCG, so it doesn't match the handbook's 20% figures.

### Breakout Desk (`breakout-desk.html`)

Not in the site menu and not linked from any page; it still ships in `dist` and opens at `/breakout-desk.html`.

NSE stocks breaking out of multi-year bases and cup-and-handle patterns.

- **Data:** read live from the tracked Google Sheet (IDs in `app.py`, `BREAKOUT_SHEET_*`) via `/api/breakout-desk`. The server keeps the result in memory for 15 minutes; if the sheet can't be reached it serves the last cached copy, then falls back to `breakout_data.json`.
- **SL** comes from column H of the sheet's multi-year-base tab (also used for cup-and-handle rows, matched by symbol). For open positions the page replaces it with the low of the week before entry once the chart loads.
- **Charts:** `/api/breakout-desk/history/<SYMBOL>` — daily prices from Yahoo (Stooq and a second Yahoo host as fallbacks), cached on disk for 24 hours in `price_history_cache.json`.
- **Fundamentals** in the expanded card view: `/api/breakout-desk/fundamentals/<SYMBOL>` — valuation, profitability and growth ratios from Yahoo Finance, cached for 24 hours in `fundamentals_cache.json`, shown with an "as of" date.

### Momentum Study (`momentum-study.html`)

A public **teaser** for the three momentum studies (Nifty 500, whole NSE, ETFs): a short intro, then headline numbers and an equity curve for each, with **no rules**. It reads `momentum_teaser.json` (Nifty 500), `momentum_nse_teaser.json` (whole NSE, against the Nifty 500 and the Nifty500 Momentum 50) and `etf_teaser.json`, **fixed snapshots** (prices to Sep 2026) that the site never refreshes.

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

### ETF momentum study (`study/etf_*`)

A momentum rotation across 16 NSE ETFs (index, sector, gold, silver, long gilt; LIQUIDCASE as cash): same score and filters as the stock study, top 5 held as equal slots, sell below rank 9, no market switch. Each ETF is eligible only once it has about a year of prices, so the list grows as it did for a real investor.

- `study/etf_prices.json` — daily prices from Yahoo (`momentum.fetch_daily("<ETF>.NS", "10y")`; `"max"` returns monthly bars). Bad prints (a close under half or over double the last good one) are dropped when loading.
- `study/etf_study.py` — writes `etf_study.json` (full study) and `etf_teaser.json` (curve and headline numbers for the public page).
- `study/etf_report.py` — writes `study/etf_report.html`, the month-by-month log (reuses `study/backtest_report_template.html`'s look).
- `study/etf-study-full.html` — the full ETF study page (reads `etf_study.json`), kept out of the site build like `study/momentum-study-full.html`.

```powershell
py study\etf_study.py
py study\etf_report.py
```

### Multi-year breakout study (`breakout-study.html`, `study/breakout_*`)

Backtests of buying Nifty 500 stocks (point-in-time lists) that close above their highest price of the last 2, 3 or 4 years, where that high was set at least a year earlier. Each lookback is a separate backtest from the first day it can be measured, run with three stop-losses: the previous week's lowest close, the lowest close of the last 2 weeks, and the 2-week low that stops trailing once it is 5% above the buy price and then rises 1% every 2 months. Up to 10 stocks from a watchlist of the best 20 recent breakouts, bought on Friday's close; ₹10 lakh to start (₹1 lakh a slot); idle money waits in one GOLDBEES pool shared equally by the empty slots; dividends added on the ex-date; 0.25% cost per side on stocks and GOLDBEES. Breakouts and stops use split-adjusted closes (the price cache has no daily lows).

Unlike the momentum and ETF studies, the **full report is public**: `breakout-study.html` ships in `dist` and is linked from the Studies menu (the Breakout Desk itself links to the Breakout Tracker sheet on `sheets.html`).

- `study/fetch_dividends.py` — dividend history from Yahoo into `study/dividends.json`, stored as yields (dividend ÷ previous close) so splits don't distort them.
- `study/breakout_study.py` — runs the nine backtests (needs `numpy`, ~1 minute) and writes `breakout_study.json`.
- `study/breakout_report.py` — writes `study/breakout_report.html` and the public copy `breakout-study.html` at the site root (reuses `study/backtest_report_template.html`'s look). The public copy gets the site's header and footer, with the menu copied from `sheets.html`, so rerun it after changing the menu.

```powershell
py study\fetch_dividends.py      # only to refresh dividends
py study\breakout_study.py
py study\breakout_report.py
```

### NIFTY monthly iron fly study (`nifty-iron-fly.html`, `iron-fly-study.html`, `study/nifty_iron_fly_study.py`)

One iron fly a month on NIFTY's monthly options, entered at the close of the first trading day after a monthly expiry only when India VIX closes between 12 and 17: sell the ATM call and put, buy a call and put 2% away, roll the short strikes once to the new ATM if the future closes 2% from them, close everything on the next 2% trigger, take profit at 12% of the net credit received (about ₹2,900 per sold lot on today's credit; a share of the premium so it grows with NIFTY's level), otherwise close a trading day before expiry. Costs: 1 point slippage per lot per order on the sold strikes and 0.5 on the wings, 0.1% STT on sold premium, ₹20 brokerage per order, NSE transaction charges and SEBI fee on premium traded, stamp duty on premium bought, and 18% GST on brokerage and fees; lot size 65 in every year.

Result (Oct 2016 to Sep 2026, per sold lot): 57 trades in 119 months, 96% winners, about ₹2,670 a trade and ₹1.52 lakh in total after all costs (₹41k of slippage, STT, brokerage, NSE and SEBI charges, stamp duty and GST), worst trade −₹24,986, all 10 years positive. On Zerodha's ₹70,000 margin per set (Oct 2026), about 28–31% a year on margin, simple and before tax (`MARGIN_PER_SET` in the study). Taking every month instead (no VIX filter) loses about ₹15k. Targets of 10–13% of the credit behave almost the same; above that, stops and drawdowns grow. The settings were chosen after testing many variants on the same data, which the page says.

Two public pages, both shipped in `dist`: `nifty-iron-fly.html`, a one-page summary in the site's own style (layout of `gold-vs-nifty.html`) that the Studies menu links to and the sitemap lists, with the idea, the headline backtest, year-by-year results and the limits (no rules or trade details); and `iron-fly-study.html`, the full report (rules, every trade, payoff diagrams, the current trade), which is **unlisted**: nothing on the site links to it and it is marked noindex, so it is reached only by its address. The summary page shows results only and offers the ₹500 handbook (`study/iron_fly_handbook/`, git-ignored). It shows the trade still running at the end of the data (or that the month was skipped), with its legs, target, roll levels and payoff, then the rules, results, the VIX-band table, equity curve, yearly figures, exits, every trade with its payoff diagram, and the month-by-month log.

- `study/nifty_iron_fly_study.py` — runs the backtest on the F&O bhavcopy in `study/fno_bhavcopy/` (from `study/fetch_fno_bhavcopy.py`) and India VIX in `study/india_vix_daily.csv` (downloaded from Yahoo Finance if missing; needs `yfinance`), prints the summary, and writes `study/nifty_iron_fly_trades.csv` and `iron_fly_study.json`.
- `study/iron_fly_report.py` — writes `study/iron_fly_report.html`, the public copy `iron-fly-study.html` and the summary `nifty-iron-fly.html` at the site root (reuses `study/backtest_report_template.html`'s look; header and footer from `sheets.html`, header styles from `study/breakout_report.py`), so rerun it after changing the menu.

```powershell
py study\fetch_fno_bhavcopy.py     # only to add newer days
py study\nifty_iron_fly_study.py
py study\iron_fly_report.py
```

### Momentum book (`book/`)

"Riding the Winners", a book (Word, A4) on momentum investing built from the study: what momentum is, its history, why it works, the exact rules, the honest backtest and every stress test. All numbers and charts come from `momentum_study.json`, so rebuild it after rerunning the study. Not part of the site build.

```powershell
cd book; npm install; cd ..        # once (installs docx; node_modules is git-ignored)
py book\make_charts.py             # charts\*.png and book_extra.json (needs momentum_study.json and etf_study.json)
py book\make_cover.py              # charts\cover.png, the full-page front cover
node book\build_book.js            # Momentum_Investing_Book.docx
```

Open the .docx in Word and update the table of contents (right-click it > Update Field) after rebuilding.

## Reels (`reels/`)

Short portrait videos (1080×1920) for Instagram, drawn on a canvas. Not part of the site build.

- `reels/madhur-vani-reel.html` — the Kabir doha on sweet speech (ऐसी वाणी बोलिए…): title card, the doha word by word, its meaning, and a recap, over a tanpura drone. Open it in a browser to preview or record a silent 25-second version.
- `reels/madhur-vani-reel.mp4` — the finished reel (36.8 s), narrated by the Azure neural voice `hi-IN-SwaraNeural` over the tanpura.
- `reels/make_reel_video.py` — builds the MP4: speaks the title, doha and meaning with `edge-tts`, renders every frame of the page in Microsoft Edge (Playwright), renders the page's tanpura offline, and mixes everything with ffmpeg. The page's sections are stretched to fit the narration; the spoken text, rates and start times are in `CLIPS` and the section timings in `KNOTS`, so update both together. Voice clips and intermediates go to `reels/build/` (git-ignored). Needs an internet connection for the voice and the Google Fonts.

```powershell
py -m pip install edge-tts imageio-ffmpeg playwright   # once; uses the installed Edge, no browser download
py reels\make_reel_video.py                            # writes reels\madhur-vani-reel.mp4
```

## Daily market reel (`market_reel.py`)

The public server builds a 2-minute English market-data reel every weekday evening and posts it to the @let.money.earn Instagram account as a Reel. `app.py` (`build_market_reel_daily`) calls `market_reel.run()` every 30 minutes from 8:30 pm IST until midnight; a run does nothing on holidays, before NSE has published, or once the day is posted. Scenes: FII/DII cash flows, a 5-session FII/DII trend (once 3 days are saved), index-futures long/short by participant, NIFTY/BANKNIFTY F&O, OI change across all F&O stocks, the four buildups, and a disclaimer with the ARN. Data comes from NSE's provisional FII/DII API, the participant-wise OI file and the F&O bhavcopy (`fetch_oi_change`).

Each scene is drawn with Pillow and joined by ffmpeg with crossfades and background music, in a temporary folder that is deleted afterwards, so no browser and no extra folder are needed on the server. The brand background, music and Mukta fonts (`market-reel/assets/`) and an ffmpeg binary (from `imageio-ffmpeg`) are bundled into `LetMoneyEarn.exe` by the spec. Two files sit next to the exe:

- `instagram.env` — `INSTAGRAM_USER_ID` and `INSTAGRAM_TOKEN` (see `market-reel/instagram.env.example`). Without it no reel is built. The token lasts 60 days and is not refreshed by this code; paste a new one before it expires.
- `market_reel_state.json` — saved FII/DII history and the dates already posted (so a day is never posted twice).

The caption carries the FII/DII figures, the site link, the disclaimer with the ARN and five hashtags (no WhatsApp link). The video fades in from black, so the post sets `thumb_offset` to 2 s and Instagram takes the cover from the intro card; a cover can't be changed through the API after posting (edit it in the app).

Each run's outcome goes to `market_reel.log` next to the exe. `failed: URLError ... CERTIFICATE_VERIFY_FAILED` means the VM's Windows certificate store lacks a root NSE needs: `app.py` points `SSL_CERT_FILE` at `certifi`'s bundle at startup so `urllib` trusts the same roots as `requests`, so rebuild the exe if an older build shows it. To check a build without posting, start the exe with `MARKET_REEL_TEST_OUT=C:\path\preview.mp4`: it builds one reel for the latest data at startup. From source: `py market_reel.py --force --no-post --out preview.mp4`.

## SEO checklist for public pages

**Required on every change.** Whenever a public page is added, renamed, removed, or its content or purpose changes, update its SEO in the same change, then run `py -m unittest tests.test_seo` and fix every failure before committing or building `dist`. `CLAUDE.md` makes this a standing rule for Claude Code sessions.

Every indexable page has:

1. A `<title>` of 65 characters or less ending in `| Let Money Earn` (the home page leads with the brand instead).
2. A meta description of 70 to 160 characters (longer ones are cut off in Google results). Rewrite it when the page's content changes.
3. `<link rel="canonical" href="https://letmoneyearn.in/<page>">` (the home page is `https://letmoneyearn.in/`).
4. `<meta name="robots" content="index, follow, max-image-preview:large">`.
5. Open Graph and Twitter tags: `og:type`, `og:site_name`, `og:title`, `og:description`, `og:url` (same as the canonical), `og:image`, `twitter:card`, `twitter:title`, `twitter:description`, kept in step with the title and description.
6. JSON-LD where it fits: `WebApplication` for tools, `Article` for posts.
7. Exactly one `<h1>` (including any rendered by the page's script).
8. An entry in `SITEMAP_STATIC_PAGES` in `app.py` (`/sitemap.xml` lists those plus every published post), and a link in the site menu, which must be identical on every page.

Pages kept out of search (`goal-sip-calculator.html`, `iron-fly-study.html`, `breakout-desk.html`) use `noindex` and must not be in the sitemap. When a page is removed, take it out of the sitemap and every menu.

`tests/test_seo.py` checks points 1-5, 7 and 8 on every public page, that sitemap entries exist, and that all menus match.

## Building the executables

The VM runs PyInstaller builds (`LetMoneyEarn.spec` and `LetMoneyEarnAdmin.spec` are in git; both exclude pandas' unused optional extras such as pyarrow, scipy and matplotlib, which otherwise push the one-file exe past 350 MB and make PyInstaller fail at `set_exe_build_timestamp`; expect about 111 MB and 75 MB). For the market-data tools (Portfolio Beta, MF Holdings Explorer), run `deploy\setup_data_tools.bat` once on the build VM: it installs the packages below, adds `openpyxl` and `xlrd` to `hiddenimports` in `LetMoneyEarn.spec` (pandas loads them dynamically, so PyInstaller misses them otherwise), checks the VM can reach NSE, AMFI and the fund houses, and can rebuild the exe. The build Python needs `pillow` and `imageio-ffmpeg` for the market reel, and `pandas` and `requests` for the portfolio beta builder (`py -m pip install pillow imageio-ffmpeg pandas requests openpyxl xlrd`; `openpyxl` and `xlrd` read the fund houses' Excel files for the holdings explorer). If pandas is missing from a build, the site still runs; only the weekly beta update is skipped (the console says so):

```powershell
py -m PyInstaller --noconfirm LetMoneyEarn.spec
py -m PyInstaller --noconfirm LetMoneyEarnAdmin.spec
```

Then copy the site files next to the executables in `dist\`: every `*.html` (including `breakout-study.html`), `*.js`, `*.css`, `upi-qr.png` (the payment QR on `sheets.html`), plus `breakout_data.json`, `momentum_teaser.json`, `momentum_nse_teaser.json` and `etf_teaser.json` (not `momentum_study.json`, `momentum_nse_study.json` or `etf_study.json`: they hold the full studies). Never copy `let_money_earn.db` over the VM's live database, keep the VM's `betas.db`, `data\` and `var\` (portfolio beta and fund holdings data; built on the VM), and keep the VM's own `instagram.env` and `market_reel_state.json` (copy `instagram.env` there once). The runtime caches (`price_history_cache.json`, `fundamentals_cache.json`) are created on the VM as needed; `momentum_prices.json` and `study\prices_extra.json` are only for regenerating snapshots locally and don't belong in `dist`.

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

## Pending

- [ ] **Fund overlap analysis** — a Market tools page that shows how much two or more mutual funds hold in common (shared stocks and overlap by weight), to sit alongside Fund Compare.
