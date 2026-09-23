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
2. Replace the VM's `dist` folder with the new build — **except** `let_money_earn.db` (and `uploads\`, if present). The live database holds real articles, comments, reviews, and questions; never overwrite it with a locally-built copy. Update it in place with targeted SQL instead of replacing the file.
3. Run `dist\setup_all.bat` as Administrator — copies `nginx.conf`, tests it, and starts nginx plus both apps.
4. Verify at https://www.letmoneyearn.in/.

### Starting after a reboot

nginx and both apps run as plain processes, not Windows services, so they don't survive a reboot on their own.

- The public site + nginx auto-start via a Task Scheduler task running `dist\autostart_public.bat` (registered with `schtasks /create ... /sc onstart /ru SYSTEM`). It's idempotent — safe to run manually too.
- The admin app is **not** auto-started (avoids storing its password on disk). Run `dist\start_admin.bat` and enter the password manually whenever you need it.

### Featuring a post on the homepage

The homepage hero story is whichever post has `image_class = 'featured'` in the database — there's only ever one. In the admin editor, check **"Feature on homepage"** on the post you want highlighted and save; the server automatically un-features whichever post had it before.

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
