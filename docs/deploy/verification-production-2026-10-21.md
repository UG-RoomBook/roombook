# Production & monitoring verification, 21 October 2026

Owner: Bhathiya Weerasinghe. This records how I verify the production hosting
and monitoring for RoomBook (epic RB-5: RB-10, RB-29–RB-34). The implementation
follows the ADR-012 AWS + Docker Compose baseline; this document points at the
committed files that satisfy each task and gives the exact check and the
evidence captured for it. Live-run evidence (screenshots and command output) is
collected on the AWS Academy hosts during the rehearsal and stored under
`docs/deploy/evidence/`; each check names the file it is recorded in.

## Environment

AWS Academy Learner Lab, `us-east-1`. VPC `10.40.0.0/16`, one public subnet.
Three `t3.medium` hosts, each self-configuring on first boot via Terraform user
data and `infra/ansible` (hardening, Docker, node-exporter, cAdvisor, GitHub
runner):

| Host | Private IP | Role |
|---|---|---|
| `roombook-ci` | 10.40.1.10 | Builds and publishes the image |
| `roombook-test` | 10.40.1.20 (Elastic IP) | Testing, Staging, restore drills |
| `roombook-production` | 10.40.1.30 (Elastic IP) | Production, monitoring, backups |

Security groups: 80/443 public on Test and Production; 9100 (node-exporter) and
8080 (cAdvisor) reachable from Production only; nothing else inbound. Private S3
buckets hold the Ansible bundle, database backups (35-day lifecycle) and
evidence. Operating targets from the brief: p95 latency < 300 ms, 5xx < 1 %,
CPU < 70 %, RAM < 80 %, free disk ≥ 20 %.

Operator commands are PowerShell from the repository root; host commands run
over SSM on the named host. Full procedure: [`docs/deploy/runbook.md`](./runbook.md).

## RB-10 — Environment hosts, access and prerequisites

Implementation: `infra/terraform` (network and hosts), `infra/ansible` (host
configuration), [`docs/deploy/runbook.md`](./runbook.md).

- **Hosts reachable and identified.** `aws sts get-caller-identity` returns the
  lab account; the three instances are running with their fixed private IPs and
  the Test/Production Elastic IPs. Evidence: `evidence/RB-10-hosts.txt`.
- **Access path works.** SSM session opens to each host without inbound SSH; the
  self-hosted runners show *Idle* in the repository's Actions → Runners.
  Evidence: `evidence/RB-10-runners.png`.
- **Prerequisites present.** On each host: Docker running, node-exporter (9100)
  and cAdvisor (8080) answering locally, `/etc/roombook/*.env` present. Evidence:
  `evidence/RB-10-prereqs.txt`.

## RB-29 — Isolated Staging and Production runtimes

Implementation: `deploy/compose/stack.yml` (db + app + caddy),
`deploy/compose/testing.yml`, `deploy/caddy/Caddyfile`.

- **One stack, known images.** `stack.yml` runs `postgres:17.11` pinned by
  digest, the app image injected by `deploy.sh`, and `caddy:2.11.7`; Caddy
  publishes 80/443 (and 443/udp) and the app only exposes 8000 internally.
- **Staging mirrors Production.** Both environments come from the same
  `stack.yml` with a per-environment env file, so Staging on Test is the same
  build and shape as Production. Check: `docker compose -p roombook-production
  -f deploy/compose/stack.yml ps` shows db, app and caddy healthy. Evidence:
  `evidence/RB-29-compose-ps.png`.
- **Database is not exposed.** db sits on the internal `backend` network only;
  the public security group has no database port. Evidence:
  `evidence/RB-29-network.txt`.
- **HTTPS is automatic.** Caddy obtains the certificate; `https://<host>/health`
  serves with a valid certificate. Evidence: `evidence/RB-29-tls.png`.

## RB-30 — Instrument hosts, containers and application traffic

Implementation: `deploy/monitoring/prometheus/prometheus.yml`; node-exporter
and cAdvisor installed by Ansible; application `/metrics` (`roombook_http_*`).

- **Three target types, 15 s scrape.** Prometheus jobs `node` (9100), `cadvisor`
  (8080, relabelled to the series the dashboards use), `roombook-app`
  (`app:8000/metrics`) and `prometheus` self. Check: Prometheus → Status →
  Targets all **UP**. Evidence: `evidence/RB-30-targets.png`.
- **Application metrics present.** `curl -s http://app:8000/metrics` on the
  Production host returns `roombook_http_requests_total` and
  `roombook_http_request_duration_seconds_bucket`. Evidence:
  `evidence/RB-30-app-metrics.txt`.

## RB-31 — Dashboards, alerts and independent availability checks

Implementation: `deploy/monitoring/grafana/**` (dashboard
`roombook-overview.json` + provisioning), `deploy/monitoring/prometheus/rules/
roombook.yml`, `deploy/monitoring/alertmanager/alertmanager.yml`, plus
CloudWatch alarms + SNS (off-host).

- **Dashboard loads.** Grafana shows the RoomBook overview with its panels
  populated from Prometheus. Evidence: `evidence/RB-31-grafana.png`.
- **Alert rules match the targets.** Rules as committed:

  | Alert | Fires when | For | Severity |
  |---|---|---|---|
  | HostDown | `up{job="node"} == 0` | 2m | critical |
  | HostHighCpu | CPU > 70 % | 10m | warning |
  | HostHighMemory | RAM > 80 % | 10m | warning |
  | HostLowDisk | root free < 20 % | 5m | warning |
  | AppDown | `up{job="roombook-app"} == 0` | 2m | critical |
  | AppHighLatency | p95 > 300 ms | 5m | warning |
  | AppErrorRate | 5xx > 1 % | 5m | critical |

  Check: Prometheus → Alerts lists all seven as loaded. Evidence:
  `evidence/RB-31-rules.png`.
- **Alerts reach Discord.** Alertmanager routes to the Discord webhook (secret,
  read from `/etc/alertmanager/discord-url`); `send_resolved` is on and a
  HostDown inhibits that host's warnings. Check: a forced test alert appears in
  the channel. Evidence: `evidence/RB-31-discord.png`.
- **Independent check.** CloudWatch host status + Production CPU alarms notify an
  SNS topic, so the hosts are watched even if the in-cluster monitoring is down.
  Evidence: `evidence/RB-31-cloudwatch.png`.

## RB-32 — Digest deployment and compatible rollback

Implementation: `deploy/scripts/deploy.sh`, `.github/workflows/operations.yml`
and the build/release workflows; pipeline design in
[`docs/ci/pipeline.md`](../ci/pipeline.md).

- **Deploy by digest, tied to a commit.** `deploy.sh <env>
  ghcr.io/...@sha256:<digest> <commit>` pulls by digest, checks the image was
  built from that commit, backs up (Production), migrates, seeds rooms, starts
  the new app, and verifies `/ready` and `/version` inside the container and
  over HTTPS. Evidence: `evidence/RB-32-deploy.txt`.
- **Automatic rollback.** If verification fails, `deploy.sh` restores the
  previous image and never downgrades the database (migrations are
  expand-then-contract). Check: a deliberately broken image is rolled back and
  the previous version stays live. Evidence: `evidence/RB-32-rollback.txt`.

## RB-33 — Private database backups and isolated restoration

Implementation: `deploy/scripts/backup.sh`, `deploy/scripts/restore-drill.sh`,
scheduled by `.github/workflows/operations.yml` (nightly 03:30 Melbourne).

- **Nightly, private, off-host.** `backup.sh production` runs `pg_dump` and
  uploads to the private S3 ops bucket (encrypted, 35-day lifecycle); it also
  runs before every Production migration. Check: the latest dump key is listed.
  Evidence: `evidence/RB-33-backup-s3.png`.
- **Proven restorable.** `restore-drill.sh` runs on the Test host, restores the
  newest dump into a throwaway PostgreSQL container, checks schema and data,
  reports the restore time, and cleans up. Evidence:
  `evidence/RB-33-restore-drill.txt`.

## RB-34 — Qualify Production and recovery drills

Implementation: `.github/workflows/operations.yml` (backup + restore-drill),
`deploy/scripts/deploy.sh` verification, smoke checks in
`.github/workflows/candidate.yml` and `docs/ci/pipeline.md`.

- **Serving check (smoke).** After deploy, the public endpoints answer 200:
  `/health`, `/ready`, `/version`, `/api/v1/rooms`, and `/metrics` internally.
  Evidence: `evidence/RB-34-smoke.txt`.
- **Behaviour under load.** The app holds the operating targets — p95 < 300 ms
  and 5xx < 1 % — under a short sustained load against `/api/v1/rooms` on
  Staging. Evidence: `evidence/RB-34-load.txt`.
- **Recovery drill.** A Production service is stopped on purpose; the matching
  alert fires in Discord and the service is brought back, closing the loop
  between monitoring and recovery. Evidence: `evidence/RB-34-recovery.png`.

## Scope and remaining work

This document is my verification record for RB-5. The implementation files it
references are already on `main`; my contribution is the independent
verification and the evidence. Live-run evidence under `docs/deploy/evidence/`
is captured on the AWS hosts for the Friday rehearsal — items without an
attached file yet are still being recorded. Application implementation remains
Saad's, CI/CD wiring Prattay's, and independent acceptance Daniel's; this record
does not stand in for teammate approval.
