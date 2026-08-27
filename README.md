# Let Money Earn Blog

A professional financial education blog powered by Python's standard library and SQLite.

## Run on Windows

From this folder, run the public website:

```powershell
py app.py
```

Open http://127.0.0.1:8000. The first run creates `let_money_earn.db` and seeds the finance articles.

Mutual Fund call requests are saved in the `call_requests` table.

## Private admin app

Open a second PowerShell window and run:

```powershell
$env:LET_MONEY_EARN_ADMIN_PASSWORD="your-strong-password"
py admin_app.py
```

Open http://127.0.0.1:8001/admin-login.html. The admin app binds to `127.0.0.1` only and is not served by the public app on port 8000.

Customer reviews submitted on the public site remain pending. After signing in, moderate them at http://127.0.0.1:8001/admin_reviews.html and approve them before they appear publicly.

Article comments are submitted from each detailed article page and remain pending until approved at http://127.0.0.1:8001/admin_comments.html.
