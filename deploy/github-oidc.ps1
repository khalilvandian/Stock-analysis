<#
Lets GitHub Actions deploy to Azure (the workflow .github/workflows/deploy.yml, issue #30)
without a stored password: OpenID Connect. Run once, signed in to Azure (az login; MFA when
asked) and to GitHub (gh auth login). Safe to rerun.

It creates:
  1. the Azure AD app registration stock-analysis-deploy and its service principal
  2. a federated credential: only workflows on this repository's main branch may sign in as it
  3. its role: Contributor on the resource group stock-rg only (the jobs, the VM, the apps,
     the database's firewall rules)
  4. the repository secrets AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_SUBSCRIPTION_ID and
     STOCK_SERVER_DB_PASSWORD (from .env; the migrations run as the server's admin)

Usage (from the repository root):
  powershell -ExecutionPolicy Bypass -File deploy\github-oidc.ps1
#>
param(
    [string]$App = "stock-analysis-deploy",
    [string]$Repository = "khalilvandian/Stock-analysis",
    [string]$ResourceGroup = "stock-rg"
)
$ErrorActionPreference = "Stop"
$az = (Get-Command az -ErrorAction SilentlyContinue).Source
if (-not $az) { $az = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd" }
function Az { $ErrorActionPreference = "Continue"; & $az @args; if ($LASTEXITCODE -ne 0) { throw "az $($args[0..1] -join ' ') failed (exit $LASTEXITCODE)" } }
function AzFind { $ErrorActionPreference = "Continue"; $out = & $az @args 2>$null; if ($LASTEXITCODE -eq 0) { $out } }
function Read-DotEnv([string]$name) {
    $line = Get-Content .env | Where-Object { $_ -match "^$name=" } | Select-Object -First 1
    if (-not $line) { throw "$name is missing from .env" }
    return $line.Substring($name.Length + 1).Trim().Trim('"')
}

Write-Host "1/4 App registration $App"
$appId = AzFind ad app list --display-name $App --query "[0].appId" -o tsv
if (-not $appId) { $appId = (Az ad app create --display-name $App --sign-in-audience AzureADMyOrg --query appId -o tsv) }
if (-not (AzFind ad sp show --id $appId --query id -o tsv)) { Az ad sp create --id $appId -o none }
$principal = (Az ad sp show --id $appId --query id -o tsv)

Write-Host "2/4 Federated credential for $Repository, branch main"
$subject = "repo:${Repository}:ref:refs/heads/main"
$has = AzFind ad app federated-credential list --id $appId --query "[?subject=='$subject'].name" -o tsv
if (-not $has) {
    $file = Join-Path $env:TEMP "github-federated.json"
    @{ name = "github-main"; issuer = "https://token.actions.githubusercontent.com"; subject = $subject;
       audiences = @("api://AzureADTokenExchange") } | ConvertTo-Json | Set-Content -Path $file -Encoding ascii
    Az ad app federated-credential create --id $appId --parameters "@$file" -o none
    Remove-Item $file -Force
}

Write-Host "3/4 Contributor on $ResourceGroup"
$scope = (Az group show -n $ResourceGroup --query id -o tsv)
if (-not (AzFind role assignment list --assignee $principal --scope $scope --role Contributor --query "[0].id" -o tsv)) {
    Az role assignment create --assignee-object-id $principal --assignee-principal-type ServicePrincipal `
        --role Contributor --scope $scope -o none
}

Write-Host "4/4 Repository secrets"
$tenant = (Az account show --query tenantId -o tsv)
$subscription = (Az account show --query id -o tsv)
gh secret set AZURE_CLIENT_ID --repo $Repository --body $appId
gh secret set AZURE_TENANT_ID --repo $Repository --body $tenant
gh secret set AZURE_SUBSCRIPTION_ID --repo $Repository --body $subscription
gh secret set STOCK_SERVER_DB_PASSWORD --repo $Repository --body (Read-DotEnv "STOCK_SERVER_DB_PASSWORD")
Write-Host "Done. GitHub Actions can now deploy main: .github/workflows/deploy.yml"
