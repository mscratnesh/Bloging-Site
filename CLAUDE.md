# Let Money Earn: working rules

Site docs: `README.md` (features, data jobs, deploy), `DESIGN.md` (visual system, page-to-route map).

## SEO: required on every page change

Whenever a change adds, renames, removes or changes the content or purpose of a public page (any `*.html` except `admin*`), update its SEO in the same change. Do not skip this, and do not leave it for later.

1. Follow the "SEO checklist for public pages" section in `README.md`: title, meta description, canonical, robots, Open Graph and Twitter tags, JSON-LD, one `<h1>`, `SITEMAP_STATIC_PAGES` in `app.py`, and the menu link on every page.
2. When a page's content changes, re-read its title, description and `og:`/`twitter:` text, and rewrite any that no longer describe the page.
3. Run `py -m unittest tests.test_seo` and fix every failure before committing or building `dist`.
4. Update `README.md` (and the route map in `DESIGN.md`) for a new or renamed page.

## Other rules

- Every disclaimer or footer carries the AMFI ARN: ARN-132137.
- Never overwrite the VM's `let_money_earn.db`, `fiidii.db`, `instagram.env`, `market_reel_state.json`, `betas.db`, `data\` or `var\` when deploying (except `data\fiidii.json`, which is rebuilt anyway).
- FII/DII data comes from official sources only (NSE, NSDL); never estimate it or copy it from third-party sites.
- After changing site files, copy them into `dist\`; after changing Python, rebuild the exes (`py -m PyInstaller --noconfirm LetMoneyEarn.spec`, and `LetMoneyEarnAdmin.spec` when `app.py` changes).
