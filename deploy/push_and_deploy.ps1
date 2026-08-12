param(
    [string]$Message = "Deploy: $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
)
# Full push-to-production pipeline: commit+push to GitHub, then rebuild+redeploy
# both the backend (GCP VM, via SSH) and frontend (Vercel). Run from anywhere --
# it cd's to the repo root itself. See docs/DEPLOYMENT.md for the full writeup.
#
# Deliberately does NOT use $ErrorActionPreference = "Stop": PowerShell 5.1
# converts ANY stderr output from a native command into an error record, and
# git/gcloud/vercel all routinely write harmless status noise to stderr (e.g.
# git's benign "credential-manager-core" warning on every single push, seen
# and confirmed non-fatal repeatedly). With Stop set, that noise would abort
# the whole pipeline despite the command actually succeeding. Real failures
# are caught via $LASTEXITCODE instead, which reflects the command's actual
# exit status regardless of what it wrote to stderr.
$RepoRoot = Split-Path -Parent $PSScriptRoot
$env:Path += ";$env:LOCALAPPDATA\Google\Cloud SDK\google-cloud-sdk\bin"

$VM_NAME = "fpl-backend"
$VM_ZONE = "us-west1-b"
$BACKEND_URL = "https://35-252-212-174.sslip.io"

function Step($label) {
    Write-Host "`n=== $label ===" -ForegroundColor Cyan
}
function Check($label) {
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED: $label (exit code $LASTEXITCODE)" -ForegroundColor Red
        exit 1
    }
}

Step "1/4 Committing and pushing to GitHub"
Set-Location $RepoRoot
git add -A
$staged = git diff --cached --name-only
if ($staged) {
    git commit -m $Message
    Check "git commit"
} else {
    Write-Host "Nothing to commit, skipping." -ForegroundColor Yellow
}
git push
Check "git push"

Step "2/4 Deploying backend (GCP VM)"
gcloud compute ssh $VM_NAME --zone=$VM_ZONE --command="cd repo && git pull && docker compose up -d --build" --quiet
Check "backend deploy"

Step "3/4 Deploying frontend (Vercel)"
Set-Location "$RepoRoot\frontend"
vercel --prod --yes
Check "frontend deploy"
Set-Location $RepoRoot

Step "4/4 Verifying"
Start-Sleep -Seconds 3
$health = curl.exe -s "$BACKEND_URL/api/health"
Write-Host "Backend health: $health"
Write-Host "`nDone. Backend: $BACKEND_URL" -ForegroundColor Green
Write-Host "Frontend: check the 'Production' URL printed above by vercel." -ForegroundColor Green
