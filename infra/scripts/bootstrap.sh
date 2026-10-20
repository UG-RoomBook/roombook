#!/usr/bin/env bash
# Creates the two S3 buckets the Terraform stack needs, once per AWS account:
#   roombook-tfstate-<account>  Terraform state (versioned, encrypted, private)
#   roombook-ops-<account>      Ansible bundle, backups, evidence (Terraform
#                               manages its versioning, encryption and lifecycle)
#
# Why not Terraform: AWS Academy Learner Lab's service control policy denies
# s3:GetBucketObjectLockConfiguration, which the Terraform AWS provider calls
# whenever it reads an aws_s3_bucket resource. Creating the buckets here and
# managing only their configuration in Terraform avoids that call.
#
# Run from AWS CloudShell or any bash with the AWS CLI. Safe to re-run.
set -euo pipefail
region="${AWS_REGION:-us-east-1}"
account=$(aws sts get-caller-identity --query Account --output text)

ensure_bucket() {
  local bucket="$1"
  if aws s3api head-bucket --bucket "$bucket" >/dev/null 2>&1; then
    echo "exists:  s3://$bucket"
  else
    if [[ "$region" == us-east-1 ]]; then
      aws s3api create-bucket --bucket "$bucket" --region "$region" >/dev/null
    else
      aws s3api create-bucket --bucket "$bucket" --region "$region" \
        --create-bucket-configuration "LocationConstraint=$region" >/dev/null
    fi
    echo "created: s3://$bucket"
  fi
  aws s3api put-public-access-block --bucket "$bucket" --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
}

state="roombook-tfstate-$account"
ensure_bucket "$state"
aws s3api put-bucket-versioning --bucket "$state" --versioning-configuration Status=Enabled
aws s3api put-bucket-encryption --bucket "$state" --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
ensure_bucket "roombook-ops-$account"

echo
echo "Next: cd infra/terraform && terraform init -backend-config=\"bucket=$state\""
