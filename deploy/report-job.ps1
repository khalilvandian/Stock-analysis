<#
Deploys the reports to Azure (issue #60, docs/APPLICATION.md):
  1. Blob storage stockreportsbk, container `reports`: private, no account key in use (only
     Entra sign-ins), Standard LRS (the subscription's free 5 GB)
  2. who may use it: this user and the report job write, the Pages workflow (the deploy app)
     reads
  3. the Container Apps Job stock-report (image of Dockerfile.report), which runs
     `python -m stock_analysis.report {render,validate,email} RUN_KEY` when Airflow starts it
  4. its managed identity's rights: the container, its own database firewall rules; and the
     Airflow VM's right to start it
Safe to rerun: it creates what is missing and updates the rest.

  -StorageOnly does 1 and 2 (the job's image is built from main, so it exists after the merge).

Needs: az login (role changes: a sign-in with MFA), .env with STOCK_WRITER_DB_PASSWORD,
BREVO_API_KEY and WATCHLIST_EMAIL_FROM (the last two not for -StorageOnly). Who gets the email is in
the database (python -m stock_analysis.app recipients).

Usage (from the repository root):
  powershell -ExecutionPolicy Bypass -File deploy\report-job.ps1 -StorageOnly
  powershell -ExecutionPolicy Bypass -File deploy\report-job.ps1
#>
param(
    [string]$ResourceGroup = "stock-rg",
    [string]$Location = "italynorth",
    [string]$Environment = "stock-jobs-env",
    [string]$Storage = "stockreportsbk",
    [string]$Container = "reports",
    [string]$Job = "stock-report",
    [string]$Image = "ghcr.io/khalilvandian/stock-analysis-report:latest",
    [string]$Server = "stock-db-bk",
    [string]$Vm = "airflow-vm",
    [string]$DeployApp = "stock-analysis-deploy",
    [switch]$StorageOnly
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
# A lookup that may find nothing (Windows PowerShell 5.1 makes stderr an error under "Stop").
function AzFind { $ErrorActionPreference = "Continue"; $out = & $az @args 2>$null; if ($LASTEXITCODE -eq 0) { $out } }
function Grant([string]$principal, [string]$type, [string]$role, [string]$scope) {
    $has = AzFind role assignment list --assignee $principal --scope $scope --role $role --query "[0].id" -o tsv
    if (-not $has) {
        Az role assignment create --assignee-object-id $principal --assignee-principal-type $type `
            --role $role --scope $scope --only-show-errors | Out-Null
        Write-Host "  granted $role"
    }
}

Write-Host "1/4 Blob storage $Storage, container $Container"
if (-not (AzFind storage account show -n $Storage -g $ResourceGroup --query name -o tsv)) {
    Az storage account create -n $Storage -g $ResourceGroup -l $Location --sku Standard_LRS --kind StorageV2 `
        --access-tier Hot --min-tls-version TLS1_2 --https-only true --allow-blob-public-access false `
        --allow-shared-key-access false --only-show-errors | Out-Null
}
if (-not (AzFind storage container-rm show --storage-account $Storage -n $Container -g $ResourceGroup --query name -o tsv)) {
    Az storage container-rm create --storage-account $Storage -n $Container -g $ResourceGroup --only-show-errors | Out-Null
}
$storageId = (Az storage account show -n $Storage -g $ResourceGroup --query id -o tsv)
$scope = "$storageId/blobServices/default/containers/$Container"

Write-Host "2/4 Who may use it"
Grant (Az ad signed-in-user show --query id -o tsv) "User" "Storage Blob Data Contributor" $scope
$deploy = (Az ad sp list --display-name $DeployApp --query "[0].id" -o tsv)
if (-not $deploy) { throw "No service principal ${DeployApp}: run deploy\github-oidc.ps1 first" }
Grant $deploy "ServicePrincipal" "Storage Blob Data Reader" $scope
if ($StorageOnly) { Write-Host "Done: storage only"; exit 0 }

Write-Host "3/4 Job $Job"
$writer = Read-DotEnv "STOCK_WRITER_DB_PASSWORD"
$brevo = Read-DotEnv "BREVO_API_KEY"
$from = Read-DotEnv "WATCHLIST_EMAIL_FROM"
$subscription = (Az account show --query id -o tsv)
$secrets = @("writer-password=$writer", "brevo-key=$brevo", "email-from=$from")
$envVars = @(
    "STOCK_DB_TARGET=server-writer",
    "STOCK_WRITER_DB_PASSWORD=secretref:writer-password",
    "BREVO_API_KEY=secretref:brevo-key",
    "WATCHLIST_EMAIL_FROM=secretref:email-from",
    "STOCK_REPORTS_URL=https://$Storage.blob.core.windows.net/$Container",
    "AZURE_SUBSCRIPTION_ID=$subscription"
)
if (-not (AzFind containerapp job show -n $Job -g $ResourceGroup --query name -o tsv)) {
    Az containerapp job create -n $Job -g $ResourceGroup --environment $Environment `
        --trigger-type Manual --replica-timeout 1800 --replica-retry-limit 0 --parallelism 1 `
        --replica-completion-count 1 --image $Image --cpu 1 --memory 2Gi --mi-system-assigned `
        --secrets @secrets --env-vars @envVars --only-show-errors | Out-Null
} else {
    Az containerapp job secret set -n $Job -g $ResourceGroup --secrets @secrets --only-show-errors | Out-Null
    Az containerapp job update -n $Job -g $ResourceGroup --image $Image --cpu 1 --memory 2Gi `
        --replica-timeout 1800 --set-env-vars @envVars --only-show-errors | Out-Null
}

Write-Host "4/4 Rights"
$principal = (Az containerapp job show -n $Job -g $ResourceGroup --query identity.principalId -o tsv)
$jobId = (Az containerapp job show -n $Job -g $ResourceGroup --query id -o tsv)
$serverId = (Az postgres flexible-server show -n $Server -g $ResourceGroup --query id -o tsv)
$vmPrincipal = (Az vm show -n $Vm -g $ResourceGroup --query identity.principalId -o tsv)
Grant $principal "ServicePrincipal" "Storage Blob Data Contributor" $scope
Grant $principal "ServicePrincipal" "Contributor" $serverId
Grant $vmPrincipal "ServicePrincipal" "Container Apps Jobs Operator" $jobId
Write-Host "Done"
