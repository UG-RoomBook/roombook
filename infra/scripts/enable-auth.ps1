<#
.SYNOPSIS
  Turns on RoomBook accounts (Supabase sign-in) for Staging or Production.

.DESCRIPTION
  Asks for the environment's Supabase project URL and publishable key (typed
  hidden), generates the token encryption key itself (only if one is not
  stored yet, so existing sessions survive a re-run), stores everything as
  SecureString parameters under /roombook/<environment>/app/ and writes them
  to the host. No value is printed or written to disk.

  Afterwards redeploy so the app reads the new settings:
    production  Release to Production > Run workflow with the current run ID
    staging     re-run "Deploy and verify Staging" of the latest green candidate

  In the Supabase project, set Site URL to the same origin and use the email
  templates in docs/backend/RB-46-accounts.md.

.EXAMPLE
  .\infra\scripts\enable-auth.ps1 -Environment production
#>
param(
  [Parameter(Mandatory)][ValidateSet('staging', 'production')] [string] $Environment,
  # Exact browser origin. Defaults to the sslip.io name of the environment's Elastic IP.
  [string] $SiteUrl,
  [string] $Region = 'us-east-1',
  # Replace an existing encryption key (signs everyone out).
  [switch] $RotateKey
)
$ErrorActionPreference = 'Stop'
$setting = Join-Path $PSScriptRoot 'set-app-setting.ps1'
$prefix = "/roombook/$Environment/app"

if (-not $SiteUrl) {
  if ($Environment -eq 'production') { $SiteUrl = 'https://100-56-214-89.sslip.io' }
  else { $SiteUrl = 'https://54-242-122-137.sslip.io' }
}
if ($SiteUrl -notmatch '^https://[^/]+$') { throw "SiteUrl must be an https origin with no path or trailing slash: $SiteUrl" }

aws sts get-caller-identity --region $Region --query Account --output text | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'AWS credentials are missing or expired: paste the Learner Lab AWS CLI block into ~/.aws/credentials.' }

Write-Host "Enabling accounts for $Environment at $SiteUrl"
$supabaseUrl = (Read-Host "Supabase project URL for $Environment (https://<ref>.supabase.co)").Trim().TrimEnd('/')
if ($supabaseUrl -notmatch '^https://[a-z0-9-]+\.supabase\.co$') { throw "That does not look like a Supabase project URL: $supabaseUrl" }

$secure = Read-Host "Supabase publishable key for $Environment (hidden)" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try { $publishable = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
if ([string]::IsNullOrWhiteSpace($publishable)) { throw 'The publishable key is empty.' }

& $setting -Environment $Environment -Region $Region -Name ROOMBOOK_AUTH_SUPABASE_URL -Value $supabaseUrl
& $setting -Environment $Environment -Region $Region -Name ROOMBOOK_AUTH_SUPABASE_PUBLISHABLE_KEY -Value $publishable
$publishable = $null

# A missing parameter is expected on the first run; do not let its error stop the script.
$names = aws ssm get-parameters --region $Region --names "$prefix/ROOMBOOK_AUTH_TOKEN_ENCRYPTION_KEY" --query 'Parameters[].Name' --output text
$hasKey = -not [string]::IsNullOrWhiteSpace($names)
if ($hasKey -and -not $RotateKey) {
  Write-Host 'Keeping the existing token encryption key.'
} else {
  # Fernet key: 32 random bytes, URL-safe base64.
  $bytes = New-Object byte[] 32
  [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $key = [Convert]::ToBase64String($bytes).Replace('+', '-').Replace('/', '_')
  & $setting -Environment $Environment -Region $Region -Name ROOMBOOK_AUTH_TOKEN_ENCRYPTION_KEY -Value $key
  $key = $null; [Array]::Clear($bytes, 0, $bytes.Length)
}

& $setting -Environment $Environment -Region $Region -Name ROOMBOOK_AUTH_SITE_URL -Value $SiteUrl
& $setting -Environment $Environment -Region $Region -Name ROOMBOOK_AUTH_ENABLED -Value true -Apply

Write-Host ''
Write-Host "Stored settings for ${Environment}:"
aws ssm get-parameters-by-path --region $Region --path "$prefix/" --query 'Parameters[].Name' --output text
Write-Host ''
if ($Environment -eq 'production') {
  Write-Host 'Next: Actions > Release to Production > Run workflow with the current validated run ID.'
} else {
  Write-Host 'Next: re-run "Deploy and verify Staging" of the latest green Candidate pipeline run.'
}
Write-Host "Supabase: set Site URL to $SiteUrl and the email templates from docs/backend/RB-46-accounts.md."
