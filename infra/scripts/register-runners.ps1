<#
.SYNOPSIS
  Registers the ci, test and production self-hosted runners with GitHub.

.DESCRIPTION
  1. In GitHub open roombook > Settings > Actions > Runners > New self-hosted runner
     and copy the value after `--token` (valid for one hour, reusable within it).
  2. Run this script and paste the token when asked (it is not echoed).

  The token is stored briefly as an encrypted SSM parameter, each host registers
  its runner (named roombook-<role>, labelled with its role), and the parameter
  is deleted again. A runner that is already registered is left as it is.
#>
param([string] $Region = 'us-east-1')
$ErrorActionPreference = 'Stop'

$parameter = '/roombook/github/runner-token'
$secure = Read-Host 'Runner registration token' -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
  $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
} finally {
  [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}
if (-not $token) { throw 'No token entered.' }

aws ssm put-parameter --region $Region --name $parameter --type SecureString --value $token --overwrite | Out-Null
Remove-Variable token
try {
  & (Join-Path $PSScriptRoot 'configure-hosts.ps1') -Region $Region
} finally {
  aws ssm delete-parameter --region $Region --name $parameter | Out-Null
  Write-Host 'Registration token parameter deleted.'
}
Write-Host 'Check GitHub: Settings > Actions > Runners should list roombook-ci, roombook-test and roombook-production as Idle.'
