# The three ADR-012 hosts: CI/build, Test/Staging and Production.

data "aws_ssm_parameter" "ubuntu" {
  # Canonical's current Ubuntu 24.04 LTS AMI, published for every region.
  name = "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
}

locals {
  web_roles = toset(["test", "production"])

  # Until real DNS records exist, sslip.io maps <a-b-c-d>.sslip.io to a.b.c.d,
  # so Caddy can still obtain a trusted certificate for each Elastic IP.
  site_hosts = {
    test       = var.staging_host != "" ? var.staging_host : "${replace(aws_eip.web["test"].public_ip, ".", "-")}.sslip.io"
    production = var.production_host != "" ? var.production_host : "${replace(aws_eip.web["production"].public_ip, ".", "-")}.sslip.io"
  }
}

# Elastic IPs are created before the instances so DNS records and hostnames
# survive stop/start (Learner Lab may stop instances when a session ends).
resource "aws_eip" "web" {
  for_each = local.web_roles
  domain   = "vpc"
  tags     = { Name = "${var.name}-${each.key}" }
}

resource "aws_instance" "host" {
  for_each = local.private_ips

  ami                    = data.aws_ssm_parameter.ubuntu.insecure_value
  instance_type          = var.instance_types[each.key]
  subnet_id              = aws_subnet.public.id
  private_ip             = each.value
  iam_instance_profile   = var.instance_profile
  key_name               = var.key_name
  vpc_security_group_ids = contains(local.web_roles, each.key) ? [aws_security_group.host.id, aws_security_group.web.id] : [aws_security_group.host.id]

  # IMDSv2 only. Hop limit 2 lets containers read the instance role; tags in
  # metadata let Ansible read the Role and SiteHost tags.
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
    instance_metadata_tags      = "enabled"
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_gb[each.key]
    encrypted             = true
    delete_on_termination = true
    tags                  = { Name = "${var.name}-${each.key}-root" }
  }

  # Installs ansible-core and the AWS CLI, then applies infra/ansible locally.
  # Later configuration changes are re-applied with infra/scripts/configure-hosts.ps1.
  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    role       = each.key
    region     = var.region
    ops_bucket = aws_s3_bucket.ops.bucket
    repository = var.github_repository
  })
  user_data_replace_on_change = false

  tags = {
    Name     = "${var.name}-${each.key}"
    Role     = each.key
    SiteHost = lookup(local.site_hosts, each.key, "none")
  }

  lifecycle {
    # A newer Ubuntu AMI must not silently replace a running host.
    ignore_changes = [ami, user_data]
  }

  depends_on = [aws_s3_object.ansible, aws_route.internet, aws_route_table_association.public]
}

resource "aws_eip_association" "web" {
  for_each      = local.web_roles
  instance_id   = aws_instance.host[each.key].id
  allocation_id = aws_eip.web[each.key].id
}
