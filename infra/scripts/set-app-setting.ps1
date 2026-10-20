<#
.SYNOPSIS
  Stores one application setting for Staging or Production in SSM Parameter Store.

.DESCRIPTION
  Settings are encrypted (SecureString) under /roombook/<environment>/app/<NAME>.
  The host turns every parameter there into a line of /etc/roombook/<environment>.env
  the next time its configuration is applied, so secrets never enter Git, an
  image or a workflow log. Then redeploy (or restart the app) to pick them up.

.EXAMPLE
  .\infra\scripts\set-app-setting.ps1 -Environment staging -Name ROOMBOOK_AUTH_ENABLED -Value true
  .\infra\scripts\set-app-setting.ps1 -Environment production -Name ROOMBOOK_AUTH_TOKEN_ENCRYPTION_KEY
  (omit -Value to type a secret without echoing it)
#>
param(
  [Parameter(Mandatory)][ValidateSet('staging', 'production')] [string] $Environment,
  [Parameter(Mandatory)][ValidatePattern('^ROOMBOOK_[A-Z0-9_]+$')] [string] $Name,
  [string] $Value,
  [string] $Region = 'us-east-1',
  [switch] $Apply
)
$ErrorActionPreference = 'Stop'

if (-not $PSBoundParameters.ContainsKey('Value')) {
  $secure = Read-Host "$Name" -AsSecureString
  $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
  try { $Value = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
  finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

aws ssm put-parameter --region $Region --name "/roombook/$Environment/app/$Name" `
  --type SecureString --value $Value --overwrite | Out-Null
Write-Host "Stored /roombook/$Environment/app/$Name."

if ($Apply) {
  $role = if ($Environment -eq 'staging') { 'test' } else { 'production' }
  & (Join-Path $PSScriptRoot 'configure-hosts.ps1') -Role $role -Region $Region
} else {
  Write-Host 'Run with -Apply (or configure-hosts.ps1) to write it to the host, then redeploy.'
}
