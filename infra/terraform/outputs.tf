output "instance_ids" {
  description = "EC2 instance per ADR-012 role."
  value       = { for role, host in aws_instance.host : role => host.id }
}

output "private_ips" {
  value = local.private_ips
}

output "public_ips" {
  description = "Elastic IPs: point the DNS records here (DNS only, no proxy)."
  value       = { for role, eip in aws_eip.web : role => eip.public_ip }
}

output "site_hosts" {
  description = "Hostnames Caddy serves. sslip.io names work without DNS changes."
  value = {
    staging    = local.site_hosts.test
    production = local.site_hosts.production
  }
}

output "ops_bucket" {
  value = aws_s3_bucket.ops.bucket
}

output "alert_topic_arn" {
  value = aws_sns_topic.alerts.arn
}

output "shell_commands" {
  description = "Open a shell on a host through Session Manager (no SSH)."
  value = {
    for role, host in aws_instance.host :
    role => "aws ssm start-session --region ${var.region} --target ${host.id}"
  }
}

output "grafana_tunnel" {
  description = "Forward Grafana (bound to localhost on Production) to http://localhost:3000."
  value       = "aws ssm start-session --region ${var.region} --target ${aws_instance.host["production"].id} --document-name AWS-StartPortForwardingSession --parameters portNumber=3000,localPortNumber=3000"
}
