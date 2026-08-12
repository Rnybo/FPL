param(
    [string]$Message = "Deploy: $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
)
# Full push-to-production pipeline: commit+push to GitHub, then rebuild+redeploy
# both the backend (GCP VM, via SSH) and frontend (Vercel). Run from anywhere --
# it cd's to the repo root itself. See docs/DEPLOYMENT.md for the full writeup
# and for what to do if any individual step here fails.
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$env:Path += ";$env:LOCALAPPDATA\Google\Cloud SDK\google-cloud-sdk\bin"

$VM_NAME = "fpl-backend"
$VM_ZONE = "us-west1-b"
$BACKEND_URL = "https://35-252-212-174.sslip.io"

function Step($label) {
    Write-Host "`n=== $label ===" -ForegroundColor Cyan
}

Step "1/4 Committing and pushing to GitHub"
Set-Location $RepoRoot
git add -A
$staged = git diff --cached --name-only
if ($staged) {
    git commit -m $Message
} else {
    Write-Host "Nothing to commit, skipping." -ForegroundColor Yellow
}
git push

Step "2/4 Deploying backend (GCP VM)"
gcloud compute ssh $VM_NAME --zone=$VM_ZONE --command="cd repo && git pull && docker compose up -d --build" --quiet

Step "3/4 Deploying frontend (Vercel)"
Set-Location "$RepoRoot\frontend"
vercel --prod --yes

Step "4/4 Verifying"
Start-Sleep -Seconds 3
$health = curl.exe -s "$BACKEND_URL/api/health"
Write-Host "Backend health: $health"
Write-Host "`nDone. Backend: $BACKEND_URL" -ForegroundColor Green
Write-Host "Frontend: check the 'Production' URL printed above by vercel." -ForegroundColor Green

Set-Location $RepoRoot
