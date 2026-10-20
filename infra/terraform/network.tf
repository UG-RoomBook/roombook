# One VPC with a single public subnet. The three hosts reach GitHub, GHCR and
# AWS APIs directly through the internet gateway, so no NAT gateway (and its
# hourly cost) is needed. Nothing listens for management traffic: operators use
# Session Manager and the runners connect outbound to GitHub.

locals {
  vpc_cidr    = "10.40.0.0/16"
  subnet_cidr = "10.40.1.0/24"

  # Fixed private addresses, so Prometheus on Production can scrape the other
  # hosts from a static configuration in the repository.
  private_ips = {
    ci         = "10.40.1.10"
    test       = "10.40.1.20"
    production = "10.40.1.30"
  }
}

resource "aws_vpc" "main" {
  cidr_block           = local.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = "${var.name}-vpc" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${var.name}-igw" }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = local.subnet_cidr
  availability_zone       = var.availability_zone
  map_public_ip_on_launch = true
  tags                    = { Name = "${var.name}-public" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${var.name}-public" }
}

resource "aws_route" "internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.main.id
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# ---------- security groups ----------

# Every host: no inbound by default, all outbound (GitHub, GHCR, apt, AWS APIs).
resource "aws_security_group" "host" {
  name        = "${var.name}-host"
  description = "RoomBook hosts: outbound only, plus metrics scraping from Production"
  vpc_id      = aws_vpc.main.id
  tags        = { Name = "${var.name}-host" }
}

resource "aws_vpc_security_group_egress_rule" "host_all" {
  security_group_id = aws_security_group.host.id
  description       = "Outbound to GitHub, GHCR, package mirrors and AWS APIs"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

# Prometheus on Production scrapes node-exporter and cAdvisor on every host,
# over the private network only.
resource "aws_vpc_security_group_ingress_rule" "node_exporter" {
  security_group_id = aws_security_group.host.id
  description       = "node-exporter, scraped by Prometheus on Production"
  ip_protocol       = "tcp"
  from_port         = 9100
  to_port           = 9100
  cidr_ipv4         = "${local.private_ips.production}/32"
}

resource "aws_vpc_security_group_ingress_rule" "cadvisor" {
  security_group_id = aws_security_group.host.id
  description       = "cAdvisor, scraped by Prometheus on Production"
  ip_protocol       = "tcp"
  from_port         = 8080
  to_port           = 8080
  cidr_ipv4         = "${local.private_ips.production}/32"
}

# Public web entry for Staging (Test host) and Production, served by Caddy.
resource "aws_security_group" "web" {
  name        = "${var.name}-web"
  description = "HTTP and HTTPS to Caddy on the Test/Staging and Production hosts"
  vpc_id      = aws_vpc.main.id
  tags        = { Name = "${var.name}-web" }
}

resource "aws_vpc_security_group_ingress_rule" "http" {
  for_each          = toset(var.web_ingress_cidrs)
  security_group_id = aws_security_group.web.id
  description       = "HTTP (Caddy redirects to HTTPS and answers ACME challenges)"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  cidr_ipv4         = each.value
}

resource "aws_vpc_security_group_ingress_rule" "https" {
  for_each          = toset(var.web_ingress_cidrs)
  security_group_id = aws_security_group.web.id
  description       = "HTTPS"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = each.value
}
