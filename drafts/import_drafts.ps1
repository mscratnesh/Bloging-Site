# Adds the articles in articles.json to the site, published (dated the day build_drafts.py ran), through the admin app.
# Run it on the server, while the admin app is running (dist\start_admin.bat):
#   powershell -ExecutionPolicy Bypass -File import_drafts.ps1
# Articles whose title already exists on the site are skipped, so running it twice is safe.
param(
    [string]$AdminUrl = "http://127.0.0.1:8001",
    [string]$File = (Join-Path $PSScriptRoot "articles.json")
)

$ErrorActionPreference = "Stop"
$posts = [System.IO.File]::ReadAllText($File, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
$password = $env:LET_MONEY_EARN_ADMIN_PASSWORD
if (-not $password) {
    $secure = Read-Host "Admin password" -AsSecureString
    $password = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
}

$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
function Send-Json($Method, $Path, $Body) {
    $bytes = [System.Text.Encoding]::UTF8.GetBytes(($Body | ConvertTo-Json -Depth 5 -Compress))
    Invoke-RestMethod -Uri "$AdminUrl$Path" -Method $Method -Body $bytes -ContentType "application/json; charset=utf-8" -WebSession $session
}

Send-Json Post "/api/admin/login" @{ password = $password } | Out-Null
$existing = @(Invoke-RestMethod -Uri "$AdminUrl/api/admin/posts" -WebSession $session | ForEach-Object { $_.title })

$added = 0
foreach ($post in $posts) {
    if ($existing -contains $post.title) { Write-Host "Skipped (already on the site): $($post.title)"; continue }
    Send-Json Post "/api/admin/posts" $post | Out-Null
    Write-Host "Added ($($post.status)): $($post.title)"
    $added++
}
Write-Host "$added article(s) added. Edit or unpublish any of them from the admin."
