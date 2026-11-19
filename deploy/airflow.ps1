<#
Deploys Airflow to Azure (issue #30, docs/ORCHESTRATION.md, "Where it runs"). Safe to rerun: it
creates what is missing and updates the rest. Run it after the merge to main, once the "Build
Airflow image" workflow has pushed ghcr.io/khalilvandian/stock-airflow (made public), and
after deploy\ingest-job.ps1 and deploy\quotes-job.ps1 (they switch the jobs to trigger Manual,
so only Airflow starts them).

What it sets up, in resource group stock-rg:
  1. the settings from .env (AIRFLOW_DB_PASSWORD is generated into .env if missing)
  2. Airflow's metadata: the database `airflow` and its owner `airflow` on stock-db-bk
  3. Blob storage for the task logs: a storage account and its container airflow-logs
  4. the UI: the Container App airflow-ui (api-server --apps core) in stock-jobs-env, scaling to
     zero, open only to this PC's address; its identity may set its own database firewall rule
     and read the logs
  5. the VM airflow-vm: B2ats v2 (the free-account size), Ubuntu, Docker and 3 GiB of swap at
     first boot, SSH only from this PC's address, a fixed public IP allowed on the database
  6. the VM's identity: Container Apps Jobs Operator on stock-ingest and stock-quotes only,
     and Storage Blob Data Contributor on the logs
  7. Airflow on the VM (deploy/airflow/compose.vm.yaml): the metadata schema, then the
     scheduler, DAG processor, triggerer and execution API; the two DAGs unpaused

Needs: az login (with MFA when Azure asks: az login --claims-challenge ...), the OpenSSH client,
and .env with STOCK_SERVER_DB_PASSWORD, STOCK_WRITER_DB_PASSWORD, AIRFLOW__API_AUTH__JWT_SECRET,
AZURE_SUBSCRIPTION_ID, BREVO_API_KEY, WATCHLIST_EMAIL_FROM, PIPELINE_ALERT_TO and
GITHUB_DISPATCH_TOKEN (fine-grained, this repository, Actions: write).

The free hours apply to the B2ats v2 size with a 64 GB P6 disk: Azure's "Free account virtual
machine" page creates the same VM. To use one made there, name it with -Vm; the script then
skips creating it.

Usage (from the repository root):
  powershell -ExecutionPolicy Bypass -File deploy\airflow.ps1
  powershell -ExecutionPolicy Bypass -File deploy\airflow.ps1 -SkipUi    # only the VM
#>
param(
    [string]$ResourceGroup = "stock-rg",
    [string]$Location = "italynorth",
    [string]$Environment = "stock-jobs-env",
    [string]$Server = "stock-db-bk",
    [string]$Vm = "airflow-vm",
    [string]$VmSize = "Standard_B2ats_v2",
    [string]$Storage = "stockairflowlogs",
    [string]$UiApp = "airflow-ui",
    [string]$Image = "ghcr.io/khalilvandian/stock-airflow:latest",
    [string[]]$Jobs = @("stock-ingest", "stock-quotes"),
    [switch]$SkipUi,
    [switch]$SkipVm
)
$ErrorActionPreference = "Stop"
$az = (Get-Command az -ErrorAction SilentlyContinue).Source
if (-not $az) { $az = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd" }
$python = ".venv\Scripts\python.exe"

function Read-DotEnv([string]$name, [switch]$Optional) {
    $line = Get-Content .env | Where-Object { $_ -match "^$name=" } | Select-Object -First 1
    if (-not $line) { if ($Optional) { return $null }; throw "$name is missing from .env" }
    return $line.Substring($name.Length + 1).Trim().Trim('"')
}
function Az { $ErrorActionPreference = "Continue"; & $az @args; if ($LASTEXITCODE -ne 0) { throw "az $($args[0..1] -join ' ') failed (exit $LASTEXITCODE)" } }
function AzFind { $ErrorActionPreference = "Continue"; $out = & $az @args 2>$null; if ($LASTEXITCODE -eq 0) { $out } }
function Grant([string]$principal, [string]$role, [string]$scope) {
    $has = AzFind role assignment list --assignee $principal --scope $scope --role $role --query "[0].id" -o tsv
    if (-not $has) {
        Az role assignment create --assignee-object-id $principal --assignee-principal-type ServicePrincipal `
            --role $role --scope $scope --only-show-errors | Out-Null
    }
}

Write-Host "1/7 Settings"
# A new subscription has few resource providers registered; Azure answers SubscriptionNotFound
# for a resource of an unregistered one.
foreach ($ns in "Microsoft.Storage", "Microsoft.Compute", "Microsoft.Network") {
    if ((AzFind provider show --namespace $ns --query registrationState -o tsv) -ne "Registered") {
        Write-Host "  registering $ns"
        Az provider register --namespace $ns --wait | Out-Null
    }
}
if (-not (Read-DotEnv "AIRFLOW_DB_PASSWORD" -Optional)) {
    $bytes = New-Object byte[] 24; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $generated = [Convert]::ToBase64String($bytes).Replace("+", "A").Replace("/", "B").Replace("=", "")
    Add-Content .env "`n# Airflow's metadata database on stock-db-bk (deploy/airflow.ps1)`nAIRFLOW_DB_PASSWORD=$generated"
    Write-Host "  generated AIRFLOW_DB_PASSWORD into .env"
}
$airflowPw = Read-DotEnv "AIRFLOW_DB_PASSWORD"
$writerPw = Read-DotEnv "STOCK_WRITER_DB_PASSWORD"
$jwt = Read-DotEnv "AIRFLOW__API_AUTH__JWT_SECRET"
$subscription = Read-DotEnv "AZURE_SUBSCRIPTION_ID"
$dispatch = Read-DotEnv "GITHUB_DISPATCH_TOKEN" -Optional
if (-not $dispatch) { Write-Warning "No GITHUB_DISPATCH_TOKEN in .env: the nightly site rebuild will fail until it is added" }
$homeIp = (Invoke-RestMethod -Uri "https://api.ipify.org").Trim()
$dbHost = "$Server.postgres.database.azure.com"
$metadataUrl = "postgresql+psycopg2://airflow:$([uri]::EscapeDataString($airflowPw))@${dbHost}:5432/airflow?sslmode=require"
$stockUrl = "postgresql://stock_writer:$([uri]::EscapeDataString($writerPw))@${dbHost}:5432/stock?sslmode=require"
$logs = @(
    "AIRFLOW__LOGGING__REMOTE_LOGGING=True",
    "AIRFLOW__LOGGING__REMOTE_BASE_LOG_FOLDER=wasb-airflow-logs",
    "AIRFLOW__LOGGING__REMOTE_LOG_CONN_ID=azure_logs",
    "AIRFLOW__AZURE_REMOTE_LOGGING__REMOTE_WASB_LOG_CONTAINER=airflow-logs"
)
# No key: the hook signs in with the app's or the VM's managed identity.
$logConn = '{"conn_type": "wasb", "host": "https://' + $Storage + '.blob.core.windows.net"}'

Write-Host "2/7 Airflow's database on $Server"
if (-not (AzFind postgres flexible-server db show -g $ResourceGroup --server-name $Server --name airflow --query name -o tsv)) {
    Az postgres flexible-server db create -g $ResourceGroup --server-name $Server --name airflow --only-show-errors | Out-Null
}
$env:AIRFLOW_DB_PASSWORD_NEW = $airflowPw
& $python deploy\airflow\metadata_db.py
if ($LASTEXITCODE -ne 0) { throw "creating the airflow role failed (is this PC's IP allowed? allow-my-ip)" }
Remove-Item Env:AIRFLOW_DB_PASSWORD_NEW

Write-Host "3/7 Blob storage $Storage for the task logs"
if (-not (AzFind storage account show -n $Storage -g $ResourceGroup --query name -o tsv)) {
    Az storage account create -n $Storage -g $ResourceGroup -l $Location --sku Standard_LRS --kind StorageV2 `
        --min-tls-version TLS1_2 --allow-blob-public-access false --only-show-errors | Out-Null
}
if (-not (AzFind storage container-rm show --storage-account $Storage -n airflow-logs -g $ResourceGroup --query name -o tsv)) {
    Az storage container-rm create --storage-account $Storage -n airflow-logs -g $ResourceGroup --only-show-errors | Out-Null
}
$storageId = (Az storage account show -n $Storage -g $ResourceGroup --query id -o tsv)
$serverId = (Az postgres flexible-server show -n $Server -g $ResourceGroup --query id -o tsv)

$uiUrl = $null
if (-not $SkipUi) {
    Write-Host "4/7 UI $UiApp (scales to zero, open to $homeIp only)"
    $uiEnv = @(
        "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=secretref:metadata-url",
        "AIRFLOW__API_AUTH__JWT_SECRET=secretref:jwt-secret",
        "AIRFLOW__DATABASE__SQL_ALCHEMY_POOL_SIZE=2",
        "AIRFLOW__DATABASE__SQL_ALCHEMY_MAX_OVERFLOW=1",
        "AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_ALL_ADMINS=true",
        "AIRFLOW_CONN_AZURE_LOGS=$logConn",
        "AZURE_SUBSCRIPTION_ID=$subscription",
        "AZURE_RESOURCE_GROUP=$ResourceGroup",
        "AZURE_DB_SERVER=$Server"
    ) + $logs
    $uiSecrets = @("metadata-url=$metadataUrl", "jwt-secret=$jwt")
    # Opens its database firewall rule, then runs `airflow api-server --apps core`. No argument
    # starts with a dash: the Azure CLI would take it for one of its own options.
    $start = "/opt/stock/orchestration/plugins/stock_orch/ui.py"
    if (-not (AzFind containerapp show -n $UiApp -g $ResourceGroup --query name -o tsv)) {
        Az containerapp create -n $UiApp -g $ResourceGroup --environment $Environment --image $Image `
            --cpu 0.5 --memory 1Gi --min-replicas 0 --max-replicas 1 `
            --ingress external --target-port 8080 --system-assigned `
            --secrets @uiSecrets --env-vars @uiEnv --command python --args $start --only-show-errors | Out-Null
    } else {
        Az containerapp secret set -n $UiApp -g $ResourceGroup --secrets @uiSecrets --only-show-errors | Out-Null
        Az containerapp update -n $UiApp -g $ResourceGroup --image $Image --set-env-vars @uiEnv `
            --command python --args $start --only-show-errors | Out-Null
    }
    $uiPrincipal = (Az containerapp show -n $UiApp -g $ResourceGroup --query identity.principalId -o tsv)
    Grant $uiPrincipal "Contributor" $serverId            # its own firewall rule, as the jobs do
    Grant $uiPrincipal "Storage Blob Data Reader" $storageId
    Az containerapp ingress access-restriction set -n $UiApp -g $ResourceGroup --rule-name home `
        --ip-address "$homeIp/32" --action Allow --only-show-errors | Out-Null
    $uiUrl = "https://" + (Az containerapp show -n $UiApp -g $ResourceGroup --query properties.configuration.ingress.fqdn -o tsv)
    Az containerapp update -n $UiApp -g $ResourceGroup --set-env-vars "AIRFLOW__API__BASE_URL=$uiUrl" --only-show-errors | Out-Null
} else {
    Write-Host "4/7 UI: skipped"
    $fqdn = AzFind containerapp show -n $UiApp -g $ResourceGroup --query properties.configuration.ingress.fqdn -o tsv
    if ($fqdn) { $uiUrl = "https://$fqdn" }
}

if ($SkipVm) { Write-Host "5-7/7 VM: skipped"; Write-Host "Done. UI: $uiUrl"; exit 0 }

Write-Host "5/7 VM $Vm ($VmSize)"
if (-not (AzFind vm show -n $Vm -g $ResourceGroup --query name -o tsv)) {
    Az vm create -n $Vm -g $ResourceGroup -l $Location --size $VmSize `
        --image "Canonical:ubuntu-24_04-lts:server:latest" --admin-username azureuser --generate-ssh-keys `
        --assign-identity "[system]" --public-ip-sku Standard --public-ip-address-allocation static `
        --os-disk-size-gb 64 --storage-sku Premium_LRS --nsg-rule NONE `
        --custom-data deploy\airflow\cloud-init.yaml --only-show-errors | Out-Null
}
$nsg = (Az network nic show --ids (Az vm show -n $Vm -g $ResourceGroup --query "networkProfile.networkInterfaces[0].id" -o tsv) `
        --query "networkSecurityGroup.id" -o tsv).Split("/")[-1]
Az network nsg rule create -g $ResourceGroup --nsg-name $nsg -n ssh-home --priority 1000 `
    --source-address-prefixes "$homeIp/32" --destination-port-ranges 22 --access Allow --protocol Tcp --only-show-errors | Out-Null
$vmIp = (Az vm show -d -n $Vm -g $ResourceGroup --query publicIps -o tsv)
Az postgres flexible-server firewall-rule create -g $ResourceGroup --server-name $Server --name airflow-vm `
    --start-ip-address $vmIp --end-ip-address $vmIp --only-show-errors | Out-Null

Write-Host "6/7 The VM's rights: start the jobs, write the logs"
$vmPrincipal = (Az vm show -n $Vm -g $ResourceGroup --query identity.principalId -o tsv)
foreach ($job in $Jobs) {
    Grant $vmPrincipal "Container Apps Jobs Operator" (Az containerapp job show -n $job -g $ResourceGroup --query id -o tsv)
}
Grant $vmPrincipal "Storage Blob Data Contributor" $storageId

Write-Host "7/7 Airflow on the VM ($vmIp)"
$settings = @(
    "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=$metadataUrl",
    "AIRFLOW__API_AUTH__JWT_SECRET=$jwt",
    "AIRFLOW_CONN_AZURE_LOGS=$logConn",
    "STOCK_PIPELINE_DB_URL=$stockUrl",
    "AZURE_SUBSCRIPTION_ID=$subscription",
    "AZURE_RESOURCE_GROUP=$ResourceGroup",
    "BREVO_API_KEY=$(Read-DotEnv 'BREVO_API_KEY')",
    "WATCHLIST_EMAIL_FROM=`"$(Read-DotEnv 'WATCHLIST_EMAIL_FROM')`"",
    "PIPELINE_ALERT_TO=$(Read-DotEnv 'PIPELINE_ALERT_TO')"
) + $logs
if ($dispatch) { $settings += "GITHUB_DISPATCH_TOKEN=$dispatch" }
if ($uiUrl) { $settings += "AIRFLOW__API__BASE_URL=$uiUrl" }
$envFile = Join-Path $env:TEMP "airflow-vm.env"
Set-Content -Path $envFile -Value ($settings -join "`n") -Encoding ascii -NoNewline
$target = "azureuser@$vmIp"
$ssh = @("-o", "StrictHostKeyChecking=accept-new")
& ssh @ssh $target "cloud-init status --wait > /dev/null"
& scp @ssh deploy\airflow\compose.vm.yaml "${target}:/opt/airflow/compose.vm.yaml"
& scp @ssh $envFile "${target}:/opt/airflow/.env"
Remove-Item $envFile -Force
& ssh @ssh $target ("cd /opt/airflow && chmod 600 .env && docker compose -f compose.vm.yaml pull -q && " +
    "docker compose -f compose.vm.yaml run --rm init && docker compose -f compose.vm.yaml up -d && " +
    "sleep 60 && docker compose -f compose.vm.yaml exec -T scheduler airflow dags unpause stock_nightly && " +
    "docker compose -f compose.vm.yaml exec -T scheduler airflow dags unpause stock_quotes")
if ($LASTEXITCODE -ne 0) { throw "starting Airflow on the VM failed: ssh $target, then docker compose logs" }
Write-Host "Done. UI: $uiUrl  VM: ssh $target (cd /opt/airflow; docker compose -f compose.vm.yaml ps)"
