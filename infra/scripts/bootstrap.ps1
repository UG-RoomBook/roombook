<#
.SYNOPSIS
  Creates the Terraform state bucket and the operations bucket (once per account).

.DESCRIPTION
  Learner Lab denies s3:GetBucketObjectLockConfiguration, which Terraform's
  aws_s3_bucket resource needs, so the buckets are created with the AWS CLI and
  Terraform manages only their configuration. Safe to re-run.
#>
param([string] $Region = 'us-east-1')
$ErrorActionPreference = 'Stop'
$account = aws sts get-caller-identity --query Account --output text

function Ensure-Bucket([string] $Bucket) {
  aws s3api head-bucket --bucket $Bucket 2>$null
  if ($LASTEXITCODE -eq 0) { Write-Host "exists:  s3://$Bucket" }
  else {
    if ($Region -eq 'us-east-1') { aws s3api create-bucket --bucket $Bucket --region $Region | Out-Null }
    else { aws s3api create-bucket --bucket $Bucket --region $Region --create-bucket-configuration "LocationConstraint=$Region" | Out-Null }
    Write-Host "created: s3://$Bucket"
  }
  aws s3api put-public-access-block --bucket $Bucket --public-access-block-configuration `
    'BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true'
}

$state = "roombook-tfstate-$account"
Ensure-Bucket $state
aws s3api put-bucket-versioning --bucket $state --versioning-configuration Status=Enabled
# A file avoids PowerShell's JSON quoting differences between versions.
$encryption = Join-Path $env:TEMP 'roombook-encryption.json'
'{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}' | Set-Content -Path $encryption -Encoding ascii
aws s3api put-bucket-encryption --bucket $state --server-side-encryption-configuration "file://$encryption"
Remove-Item $encryption
Ensure-Bucket "roombook-ops-$account"

Write-Host "`nNext: cd infra\terraform; terraform init -backend-config=`"bucket=$state`""
