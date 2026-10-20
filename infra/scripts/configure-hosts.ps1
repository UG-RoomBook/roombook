<#
.SYNOPSIS
  Re-applies the host configuration (infra/ansible) on the RoomBook EC2 hosts.

.DESCRIPTION
  `terraform apply` uploads the current infra/ansible bundle to S3. This script
  asks each running host, through AWS Systems Manager, to download that bundle
  and apply it locally. No SSH, open port or local Ansible installation is
  needed. Running it again on a correct host changes nothing.

.EXAMPLE
  .\infra\scripts\configure-hosts.ps1
  .\infra\scripts\configure-hosts.ps1 -Role production
#>
param(
  [ValidateSet('all', 'ci', 'test', 'production')]
  [string] $Role = 'all',
  [string] $Region = 'us-east-1'
)
$ErrorActionPreference = 'Stop'

$filters = @('Name=tag:Project,Values=roombook', 'Name=instance-state-name,Values=running')
if ($Role -ne 'all') { $filters += "Name=tag:Role,Values=$Role" }

$ids = @(aws ec2 describe-instances --region $Region --filters $filters `
    --query 'Reservations[].Instances[].InstanceId' --output text) -split '\s+' | Where-Object { $_ }
if (-not $ids) { throw "No running RoomBook hosts matched role '$Role'. Is the lab started?" }
Write-Host "Configuring $($ids.Count) host(s): $($ids -join ', ')"

$commandId = aws ssm send-command --region $Region --instance-ids $ids `
  --document-name AWS-RunShellScript `
  --comment 'roombook-configure (infra/ansible)' `
  --timeout-seconds 1800 `
  --parameters 'commands=/usr/local/sbin/roombook-configure' `
  --query Command.CommandId --output text

$deadline = (Get-Date).AddMinutes(30)
do {
  Start-Sleep -Seconds 10
  $states = aws ssm list-command-invocations --region $Region --command-id $commandId `
    --query 'CommandInvocations[].Status' --output text
  Write-Host "  status: $states"
} while (($states -match 'Pending|InProgress|Delayed') -and (Get-Date) -lt $deadline)

$failed = $false
foreach ($id in $ids) {
  $result = aws ssm get-command-invocation --region $Region --command-id $commandId --instance-id $id | ConvertFrom-Json
  $role = aws ec2 describe-tags --region $Region --filters "Name=resource-id,Values=$id" 'Name=key,Values=Role' `
    --query 'Tags[0].Value' --output text
  Write-Host "`n=== $role ($id): $($result.Status)"
  # Ansible's PLAY RECAP is at the end of the output.
  $out = $result.StandardOutputContent
  if ($out.Length -gt 1500) { $out = '...' + $out.Substring($out.Length - 1500) }
  Write-Host $out
  if ($result.Status -ne 'Success') {
    $failed = $true
    Write-Host $result.StandardErrorContent
  }
}
if ($failed) { throw 'At least one host failed. Read the output above, or /var/log/roombook-bootstrap.log on the host.' }
Write-Host "`nAll hosts configured."
