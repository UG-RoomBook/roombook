# Deployment runbook

How to build, operate and tear down the ADR-012 environments on AWS Academy
Learner Lab (`us-east-1`). Commands are PowerShell, run from the repository root
on an operator's computer. Pipeline design: [docs/ci/pipeline.md](../ci/pipeline.md).

## What gets built

| Resource | Purpose |
|---|---|
| VPC 10.40.0.0/16, one public subnet | Hosts reach GitHub, GHCR and AWS directly; no NAT gateway |
| `roombook-ci` (t3.medium, 10.40.1.10) | Runner `ci`: builds and publishes the image |
| `roombook-test` (t3.medium, 10.40.1.20, Elastic IP) | Runner `test`: Testing stacks, Staging, restore drills |
| `roombook-production` (t3.medium, 10.40.1.30, Elastic IP) | Runner `production`: Production, monitoring, backups |
| Security groups | 80/443 public on Test and Production; 9100/8080 from Production only; nothing else inbound |
| S3 `roombook-ops-<account>` | Ansible bundle, database backups (35 days), evidence |
| S3 `roombook-tfstate-<account>` | Terraform state with native locking |
| CloudWatch alarms and SNS topic | Host status checks and Production CPU, independent of the hosts |

Every host configures itself on first boot: Terraform user data installs
ansible-core and runs `infra/ansible` locally (hardening, Docker, node-exporter,
cAdvisor, runtime files, GitHub runner).

## One-time tools

```powershell
winget install Hashicorp.Terraform
winget install Amazon.AWSCLI
winget install Amazon.SessionManagerPlugin
```

## Each Learner Lab session

Start the lab, open **AWS Details > AWS CLI: Show** and paste the block into
`$HOME\.aws\credentials`. The keys change every session. Check with:

```powershell
aws sts get-caller-identity
```

Instances may be stopped when a session ends. Start the lab (and the instances,
if stopped) at least 15 minutes before a demonstration; the Elastic IPs keep
the same addresses, and the runners reconnect by themselves.

## 1. Create the two S3 buckets (once)

```powershell
.\infra\scripts\bootstrap.ps1      # or infra/scripts/bootstrap.sh in AWS CloudShell
```

It prints the state bucket name, `roombook-tfstate-<account id>`. The buckets
are created with the AWS CLI because Learner Lab denies
`s3:GetBucketObjectLockConfiguration`, which Terraform's `aws_s3_bucket`
resource needs; Terraform then manages the operations bucket's versioning,
encryption, public access block and lifecycle.

## 2. Create the environments

```powershell
cd infra\terraform
terraform init -backend-config="bucket=roombook-tfstate-<account id>"
terraform validate
terraform plan -out tf.plan
terraform apply tf.plan
terraform output
```

Wait about five minutes for first-boot configuration. Check a host:

```powershell
aws ssm start-session --target <instance id>      # from `terraform output shell_commands`
sudo tail -n 30 /var/log/roombook-bootstrap.log   # ends with PLAY RECAP ... failed=0
```

## 3. Register the three runners

GitHub: **roombook > Settings > Actions > Runners > New self-hosted runner**,
copy the value after `--token`, then:

```powershell
.\infra\scripts\register-runners.ps1
```

**Settings > Actions > Runners** should list `roombook-ci`, `roombook-test` and
`roombook-production` as Idle.

## 4. First release

1. Actions > **Candidate pipeline** > Run workflow (or merge to `main`).
2. When it is green, open its summary and copy the run ID.
3. Actions > **Release to Production** > Run workflow > paste the run ID.
4. Actions > **Operations** > Run workflow > `monitoring` (needs Production deployed once).

Staging and Production URLs come from `terraform output site_hosts`
(`<elastic-ip>.sslip.io` until DNS is set).

## 5. Switch to zenora.dev names

Ask the DNS owner for two **DNS only** A records: `roombook-staging` to the
Test Elastic IP and `roombook` to the Production Elastic IP. Then:

```powershell
# infra\terraform\terraform.tfvars
#   staging_host    = "roombook-staging.zenora.dev"
#   production_host = "roombook.zenora.dev"
terraform apply
.\infra\scripts\configure-hosts.ps1
```

Run the candidate pipeline again; Caddy obtains certificates for the new names.

## Application secrets and accounts

Secrets live in SSM Parameter Store, never in Git:

```powershell
.\infra\scripts\set-app-setting.ps1 -Environment staging -Name ROOMBOOK_AUTH_SUPABASE_URL -Value https://<ref>.supabase.co
.\infra\scripts\set-app-setting.ps1 -Environment staging -Name ROOMBOOK_AUTH_SUPABASE_PUBLISHABLE_KEY
.\infra\scripts\set-app-setting.ps1 -Environment staging -Name ROOMBOOK_AUTH_TOKEN_ENCRYPTION_KEY
.\infra\scripts\set-app-setting.ps1 -Environment staging -Name ROOMBOOK_AUTH_SITE_URL -Value https://roombook-staging.zenora.dev
.\infra\scripts\set-app-setting.ps1 -Environment staging -Name ROOMBOOK_AUTH_ENABLED -Value true -Apply
```

Repeat for `production`, then redeploy. The Discord alert webhook is
`/roombook/production/discord-webhook-url`:

```powershell
aws ssm put-parameter --name /roombook/production/discord-webhook-url --type SecureString --value <url> --overwrite
.\infra\scripts\configure-hosts.ps1 -Role production
```

## Release modes

| Mode | How |
|---|---|
| Deferred (default) | Release to Production > Run workflow with a validated candidate run ID |
| Automatic | Repository variable `PROD_AUTO_PROMOTE` = `true`: every validated candidate continues to Production |
| Rollback | Release to Production > Run workflow > action `rollback` |

The release workflow refuses manifests that did not pass Staging, commits not
on `main`, and candidates older than what Production runs.

## Monitoring

```powershell
# from `terraform output grafana_tunnel`
aws ssm start-session --target <production id> --document-name AWS-StartPortForwardingSession --parameters portNumber=3000,localPortNumber=3000
```

Open http://localhost:3000, user `admin`. The password is on the Production host
in `/etc/roombook/secrets/grafana-admin-password` (read it in a Session Manager
shell with `sudo cat`). The **RoomBook overview** dashboard shows host CPU,
memory, disk I/O, free disk, network, HTTP latency percentiles, request and
error rates, container usage, the deployed commit and deployment annotations.

## Room opening hours

RB-51 keeps every room unavailable until its hours are confirmed. The reviewed
operator command `scripts.set_room_hours` confirms Monday-Friday 09:00-17:00 for
the two reference rooms (other days, times or rooms via `--days`, `--opens`,
`--closes`, `--room`). It is a dry run without `--confirm`, does nothing when the
hours are already set, and is rejected with `BOOKINGS_AFFECTED` (nothing written)
if the change would leave an active or future booking outside the hours.

| Environment | How it is applied |
|---|---|
| Testing | Every candidate run, after seeding the rooms |
| Staging | Every candidate run, before the Staging browser journeys |
| Production | Actions > **Operations** > Run workflow > `room-hours` (after a release) |

The browser journeys in `tests/e2e/specs/booking.spec.ts` rely on these hours:
a weekday interval must offer a bookable room and a Saturday must not.

## Failure handling

| Symptom | First check | Recovery |
|---|---|---|
| Jobs stay queued | Settings > Actions > Runners; lab and instances running | Start instances; `configure-hosts.ps1` |
| Bootstrap failed | `/var/log/roombook-bootstrap.log` | Fix `infra/ansible`, `terraform apply`, `configure-hosts.ps1` |
| Release verification failed | Release run log; `deployments.jsonl` | Automatic rollback already ran; fix forward |
| Rollback also failed | `docker compose -p roombook-production ps`, app logs | Operator restores manually; record the incident |
| HTTPS fails | DNS records, Caddy logs | Use sslip.io names until DNS resolves |
| Backup or drill failed | Operations run log | Re-run Operations; check S3 access |

On a host, `/srv/roombook/<environment>/deployments.jsonl` records every
deployment with its result and duration, and `current.ref` and `previous.ref`
hold the running and previous digests.

## Cost and teardown

Three t3.medium hosts, volumes and Elastic IPs cost roughly US$3.70 per day
while running. Stop the CI host when idle if the budget is tight; pushes then
wait for it.

After final marking, archive evidence, empty the operations bucket, then:

```powershell
cd infra\terraform
terraform destroy
```
