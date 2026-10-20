variable "region" {
  description = "AWS region. AWS Academy Learner Lab only allows us-east-1 and us-west-2."
  type        = string
  default     = "us-east-1"
}

variable "name" {
  description = "Prefix for every resource name."
  type        = string
  default     = "roombook"
}

variable "availability_zone" {
  description = "Zone for the single public subnet that holds all three hosts."
  type        = string
  default     = "us-east-1a"
}

variable "instance_types" {
  description = "Instance size per ADR-012 role. Learner Lab allows up to *.large."
  type        = map(string)
  default = {
    ci         = "t3.medium" # Docker builds of the React + FastAPI image
    test       = "t3.medium" # disposable Testing stacks plus persistent Staging
    production = "t3.medium" # application, PostgreSQL, Caddy and monitoring
  }

  validation {
    condition     = alltrue([for role in ["ci", "test", "production"] : contains(keys(var.instance_types), role)])
    error_message = "instance_types must define ci, test and production."
  }
}

variable "root_volume_gb" {
  description = "Encrypted gp3 root volume size per host (Learner Lab maximum is 100)."
  type        = map(number)
  default = {
    ci         = 40
    test       = 40
    production = 40
  }
}

variable "instance_profile" {
  description = "Existing instance profile. Learner Lab cannot create IAM roles, so it supplies LabInstanceProfile (S3, SSM and Session Manager access)."
  type        = string
  default     = "LabInstanceProfile"
}

variable "key_name" {
  description = "Optional EC2 key pair for emergency console access. Operators normally use Session Manager, and port 22 stays closed."
  type        = string
  default     = null
}

variable "staging_host" {
  description = "Public hostname for Staging, e.g. roombook-staging.zenora.dev. Empty uses <elastic-ip>.sslip.io until DNS is ready."
  type        = string
  default     = ""
}

variable "production_host" {
  description = "Public hostname for Production, e.g. roombook.zenora.dev. Empty uses <elastic-ip>.sslip.io until DNS is ready."
  type        = string
  default     = ""
}

variable "web_ingress_cidrs" {
  description = "Who may reach 80/443 on the Test/Staging and Production hosts."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "alert_email" {
  description = "Optional email for CloudWatch host alarms. AWS sends a confirmation link first."
  type        = string
  default     = ""
}

variable "github_repository" {
  description = "Repository the self-hosted runners register with."
  type        = string
  default     = "UG-RoomBook/roombook"
}

variable "backup_retention_days" {
  description = "Days to keep database dumps under backups/ in the operations bucket."
  type        = number
  default     = 35
}
