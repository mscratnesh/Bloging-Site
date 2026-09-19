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

## Private admin app

Open a second PowerShell window and run:

```powershell
$env:LET_MONEY_EARN_ADMIN_PASSWORD="your-strong-password"
py admin_app.py
```

Open http://127.0.0.1:8001/admin-login.html. The admin app binds to `127.0.0.1` only and is not served by the public app on port 8000.

Customer reviews submitted on the public site remain pending. After signing in, moderate them at http://127.0.0.1:8001/admin_reviews.html and approve them before they appear publicly.

Article comments are submitted from each detailed article page and remain pending until approved at http://127.0.0.1:8001/admin_comments.html.
