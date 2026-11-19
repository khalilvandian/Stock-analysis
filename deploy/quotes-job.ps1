<#
Deploys the live prices to Azure (issue #35, docs/INGEST.md, "Hourly quotes"), in one go:
  1. the database: migrations up to date (raw_tv_quote, v_quote_latest)
  2. the Container Apps Job stock-quotes, which runs `python -m stock_analysis.db quotes`: one
     TradingView request for the last price of every company in the database, stored in
     raw_tv_quote. It uses the image and environment of the ingest job (deploy/ingest-job.ps1
     must have run once)
  3. its managed identity's right to open its own database firewall rule
  4. the web API (api/), whose public GET /quotes the site's pages read
Safe to rerun. Run it after the branch is merged into main: the image is built from main.

Airflow starts it (the DAG stock_quotes, issue #30): trigger Manual by default; -Trigger
Schedule brings back its own cron. Every hour on weekdays, around the clock, so every market's
session is covered whatever exchanges the universe holds: New York, Europe, Tokyo. A run when
no market has moved stores nothing; each run takes seconds, inside the free grant.

Each run lets its own address through the database firewall under the rule quotes-job (not
ingest-job, so the two jobs never remove each other's rule); the job's managed identity gets
Contributor on the database server for that.

Needs: az login, .env with STOCK_WRITER_DB_PASSWORD, and this PC's IP allowed on the database.

Usage (from the repository root):
  powershell -ExecutionPolicy Bypass -File deploy\quotes-job.ps1
  powershell -ExecutionPolicy Bypass -File deploy\quotes-job.ps1 -RunNow   # also start one run
#>
param(
    [string]$ResourceGroup = "stock-rg",
    [string]$Environment = "stock-jobs-env",
    [string]$Job = "stock-quotes",
    [string]$Image = "ghcr.io/khalilvandian/stock-analysis-ingest:latest",
    [string]$Server = "stock-db-bk",
    [ValidateSet("Manual", "Schedule")][string]$Trigger = "Manual",
    [string]$Cron = "5 * * * 1-5",   # only with -Trigger Schedule
    [string]$WebApp = "stock-api-bk",
    [switch]$SkipApi,
    [switch]$RunNow
)
$ErrorActionPreference = "Stop"
$az = (Get-Command az -ErrorAction SilentlyContinue).Source
if (-not $az) { $az = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd" }

function Read-DotEnv([string]$name) {
    $line = Get-Content .env | Where-Object { $_ -match "^$name=" } | Select-Object -First 1
    if (-not $line) { throw "$name is missing from .env" }
    return $line.Substring($name.Length + 1).Trim().Trim('"')
}
function Az { $ErrorActionPreference = "Continue"; & $az @args; if ($LASTEXITCODE -ne 0) { throw "az $($args[0..1] -join ' ') failed (exit $LASTEXITCODE)" } }
function AzFind { $ErrorActionPreference = "Continue"; $out = & $az @args 2>$null; if ($LASTEXITCODE -eq 0) { $out } }

$writer = Read-DotEnv "STOCK_WRITER_DB_PASSWORD"
$subscription = (Az account show --query id -o tsv)

Write-Host "1/4 Database: migrations up to date"
$python = if (Test-Path .venv\Scripts\python.exe) { ".venv\Scripts\python.exe" } else { "python" }
& $python -m stock_analysis.db init --target server
if ($LASTEXITCODE -ne 0) { throw "database init failed (is this PC's IP allowed? allow-my-ip)" }

Write-Host "2/4 Job $Job (trigger $Trigger)"
$envVars = @(
    "STOCK_DB_TARGET=server-writer",
    "STOCK_WRITER_DB_PASSWORD=secretref:writer-password",
    "AZURE_SUBSCRIPTION_ID=$subscription"
)
# Azure can't change a job's trigger type in place: recreate it (step 3 regrants its rights).
$current = AzFind containerapp job show -n $Job -g $ResourceGroup --query properties.configuration.triggerType -o tsv
if ($current -and $current -ne $Trigger) {
    Write-Host "  recreating ${Job}: trigger $current -> $Trigger"
    Az containerapp job delete -n $Job -g $ResourceGroup --yes --only-show-errors
    $current = $null
}
$triggerArgs = if ($Trigger -eq "Schedule") { @("--trigger-type", "Schedule", "--cron-expression", $Cron) } else { @("--trigger-type", "Manual") }
$cronArgs = if ($Trigger -eq "Schedule") { @("--cron-expression", $Cron) } else { @() }
if (-not $current) {
    Az containerapp job create -n $Job -g $ResourceGroup --environment $Environment `
        @triggerArgs `
        --replica-timeout 900 --replica-retry-limit 0 --parallelism 1 --replica-completion-count 1 `
        --image $Image --args quotes --cpu 0.25 --memory 0.5Gi --mi-system-assigned `
        --secrets "writer-password=$writer" --env-vars @envVars --only-show-errors
} else {
    Az containerapp job secret set -n $Job -g $ResourceGroup --secrets "writer-password=$writer" --only-show-errors
    Az containerapp job update -n $Job -g $ResourceGroup @cronArgs `
        --image $Image --args quotes --cpu 0.25 --memory 0.5Gi --replica-timeout 900 `
        --set-env-vars @envVars --only-show-errors
}

Write-Host "3/4 Let the job's identity manage the database firewall rules"
$principal = (Az containerapp job show -n $Job -g $ResourceGroup --query identity.principalId -o tsv)
$serverId = (Az postgres flexible-server show -n $Server -g $ResourceGroup --query id -o tsv)
$has = AzFind role assignment list --assignee $principal --scope $serverId --role Contributor --query "[0].id" -o tsv
if (-not $has) {
    Az role assignment create --assignee-object-id $principal --assignee-principal-type ServicePrincipal `
        --role Contributor --scope $serverId --only-show-errors
}

if ($SkipApi) {
    Write-Host "4/4 Web API: skipped"
} else {
    Write-Host "4/4 Web API $WebApp (GET /quotes for the pages)"
    $zip = Join-Path $env:TEMP "stock-api.zip"
    if (Test-Path $zip) { Remove-Item $zip -Force }
    Compress-Archive -Path api\app.py, api\requirements.txt -DestinationPath $zip
    Az webapp deploy --name $WebApp --resource-group $ResourceGroup --src-path $zip --type zip --only-show-errors
    Remove-Item $zip -Force
}

if ($RunNow) {
    Write-Host "Starting one run now"
    Az containerapp job start -n $Job -g $ResourceGroup --only-show-errors
}
Write-Host "Done. Runs: az containerapp job execution list -n $Job -g $ResourceGroup -o table"
