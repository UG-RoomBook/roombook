# Operations bucket: the Ansible bundle the hosts configure themselves from,
# database backups and archived evidence. Private, versioned and encrypted.

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "ops" {
  bucket = "${var.name}-ops-${data.aws_caller_identity.current.account_id}"
  # Backups live here; `terraform destroy` refuses until the bucket is emptied
  # deliberately after the evidence has been archived.
  force_destroy = false
}

resource "aws_s3_bucket_versioning" "ops" {
  bucket = aws_s3_bucket.ops.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "ops" {
  bucket = aws_s3_bucket.ops.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "ops" {
  bucket                  = aws_s3_bucket.ops.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "ops" {
  bucket = aws_s3_bucket.ops.id

  rule {
    id     = "expire-old-backups"
    status = "Enabled"
    filter {
      prefix = "backups/"
    }
    expiration {
      days = var.backup_retention_days
    }
    noncurrent_version_expiration {
      noncurrent_days = 7
    }
  }

  rule {
    id     = "tidy-old-bundles"
    status = "Enabled"
    filter {
      prefix = "ansible/"
    }
    noncurrent_version_expiration {
      noncurrent_days = 14
    }
  }
}

# The host configuration (infra/ansible) is zipped and uploaded on every apply.
# Each host downloads and runs it locally, so operators need no SSH or Ansible
# installation on their own computers.
data "archive_file" "ansible" {
  type        = "zip"
  source_dir  = "${path.module}/../ansible"
  output_path = "${path.module}/.build/ansible.zip"
}

resource "aws_s3_object" "ansible" {
  bucket      = aws_s3_bucket.ops.id
  key         = "ansible/ansible.zip"
  source      = data.archive_file.ansible.output_path
  source_hash = data.archive_file.ansible.output_base64sha256
}
