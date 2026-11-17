<#
Deploys the ingest job to Azure (issue #18, docs/INGEST.md): an Azure Container Apps Job that
runs `python -m stock_analysis.db ingest` on a schedule, from the image the "Build ingest image"
workflow pushes to GitHub Container Registry. Safe to rerun: it creates what is missing and
updates the rest.

What it sets up, all in resource group stock-rg:
  1. the database: migrations up to date and the working users' rights (as stock_admin)
  2. the Container Apps environment stock-jobs-env (Consumption: billed per second while a job
     runs, inside the monthly free grant)
  3. the job stock-ingest: schedule, 1.5 vCPU / 3 GiB, at most 3 hours, no retries (the next run
     picks up where this one stopped), the secrets, and a system-assigned managed identity
  4. the identity's right to change the database server's firewall rules (Contributor on the
     server only), so each run can let its own address in and remove it afterwards

Needs: az login (Azure for Students subscription), .env with STOCK_SERVER_DB_PASSWORD,
STOCK_WRITER_DB_PASSWORD and SEC_USER_AGENT (and optionally GITHUB_DISPATCH_TOKEN), and this
PC's IP allowed on the database
(uv run python -m stock_analysis.db allow-my-ip).

Usage (from the repository root):
  powershell -ExecutionPolicy Bypass -File deploy\ingest-job.ps1
  powershell -ExecutionPolicy Bypass -File deploy\ingest-job.ps1 -RunNow   # also start one run
#>
param(
    [string]$ResourceGroup = "stock-rg",
    [string]$Location = "italynorth",
    [string]$Environment = "stock-jobs-env",
    [string]$Job = "stock-ingest",
    [string]$Image = "ghcr.io/khalilvandian/stock-analysis-ingest:latest",
    [string]$Server = "stock-db-bk",
    [string]$Cron = "30 22 * * *",   # UTC: 23:30 in Italy in winter, after the US close
    [switch]$RunNow
)
$ErrorActionPreference = "Stop"
$az = (Get-Command az -ErrorAction SilentlyContinue).Source
if (-not $az) { $az = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd" }

function Read-DotEnv([string]$name, [switch]$Optional) {
    $line = Get-Content .env | Where-Object { $_ -match "^$name=" } | Select-Object -First 1
    if (-not $line) { if ($Optional) { return $null }; throw "$name is missing from .env" }
    return $line.Substring($name.Length + 1).Trim().Trim('"')
}
function Az { & $az @args; if ($LASTEXITCODE -ne 0) { throw "az $($args -join ' ') failed" } }

$writer = Read-DotEnv "STOCK_WRITER_DB_PASSWORD"
$agent = Read-DotEnv "SEC_USER_AGENT"
# Optional: lets each run start the site's Pages workflow when it finishes (docs/INGEST.md).
$dispatch = Read-DotEnv "GITHUB_DISPATCH_TOKEN" -Optional
$subscription = (Az account show --query id -o tsv)

Write-Host "1/4 Database: migrations and the users' rights"
$python = if (Test-Path .venv\Scripts\python.exe) { ".venv\Scripts\python.exe" } else { "python" }
& $python -m stock_analysis.db init --target server
if ($LASTEXITCODE -ne 0) { throw "database init failed (is this PC's IP allowed? allow-my-ip)" }
& $python -m stock_analysis.db create-roles --target server
if ($LASTEXITCODE -ne 0) { throw "create-roles failed" }

Write-Host "2/4 Container Apps environment $Environment"
Az extension add --name containerapp --upgrade --only-show-errors
Az provider register --namespace Microsoft.App --wait
Az provider register --namespace Microsoft.OperationalInsights --wait
$exists = & $az containerapp env show -n $Environment -g $ResourceGroup --query name -o tsv 2>$null
if (-not $exists) {
    Az containerapp env create -n $Environment -g $ResourceGroup -l $Location --only-show-errors
}

Write-Host "3/4 Job $Job ($Cron UTC)"
$envVars = @(
    "STOCK_DB_TARGET=server-writer",
    "STOCK_WRITER_DB_PASSWORD=secretref:writer-password",
    "SEC_USER_AGENT=secretref:sec-user-agent",
    "AZURE_SUBSCRIPTION_ID=$subscription"
)
$secrets = @("writer-password=$writer", "sec-user-agent=$agent")
if ($dispatch) {
    $secrets += "github-dispatch=$dispatch"
    $envVars += "GITHUB_DISPATCH_TOKEN=secretref:github-dispatch"
}
$exists = & $az containerapp job show -n $Job -g $ResourceGroup --query name -o tsv 2>$null
if (-not $exists) {
    Az containerapp job create -n $Job -g $ResourceGroup --environment $Environment `
        --trigger-type Schedule --cron-expression $Cron `
        --replica-timeout 10800 --replica-retry-limit 0 --parallelism 1 --replica-completion-count 1 `
        --image $Image --cpu 1.5 --memory 3Gi --mi-system-assigned `
        --secrets @secrets --env-vars @envVars --only-show-errors
} else {
    Az containerapp job secret set -n $Job -g $ResourceGroup --secrets @secrets --only-show-errors
    Az containerapp job update -n $Job -g $ResourceGroup --cron-expression $Cron `
        --image $Image --cpu 1.5 --memory 3Gi --replica-timeout 10800 `
        --set-env-vars @envVars --only-show-errors
}

Write-Host "4/4 Let the job's identity manage the database firewall rules"
$principal = (Az containerapp job show -n $Job -g $ResourceGroup --query identity.principalId -o tsv)
$serverId = (Az postgres flexible-server show -n $Server -g $ResourceGroup --query id -o tsv)
$has = & $az role assignment list --assignee $principal --scope $serverId --role Contributor --query "[0].id" -o tsv 2>$null
if (-not $has) {
    Az role assignment create --assignee-object-id $principal --assignee-principal-type ServicePrincipal `
        --role Contributor --scope $serverId --only-show-errors
}

if ($RunNow) {
    Write-Host "Starting one run now"
    Az containerapp job start -n $Job -g $ResourceGroup --only-show-errors
}
Write-Host "Done. Runs: az containerapp job execution list -n $Job -g $ResourceGroup -o table"
