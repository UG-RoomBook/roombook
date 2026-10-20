# Delivery pipeline

Follows [ADR-012](https://github.com/UG-RoomBook/wiki/blob/main/decisions/ADR-012-restore-submitted-aws-pipeline.md)
(three EC2 roles, Docker Compose, self-hosted runners) and ADR-003 (one image
promoted by digest). Operating steps are in the [deployment runbook](../deploy/runbook.md).

## Environments

| Environment | Where | Runner label | Lifetime |
|---|---|---|---|
| Development | Laptops, `compose.dev.yml` | none | Developer-owned |
| CI/build | EC2 `roombook-ci` (10.40.1.10) | `ci` | Build caches only |
| Testing | EC2 `roombook-test` (10.40.1.20), Compose project `rb-test-<run>` | `test` | Created and deleted per run |
| Staging | EC2 `roombook-test`, Compose project `roombook-staging` | `test` | Persistent, own database and secrets |
| Production | EC2 `roombook-production` (10.40.1.30), project `roombook-production` | `production` | Persistent, backed up, monitored |

Runners connect outbound to GitHub, so no host accepts SSH or deployment
traffic. Operators use AWS Session Manager. Only Caddy (80/443) is public on the
Test and Production hosts.

## Workflows

| Workflow | Trigger | Runs on | What it does |
|---|---|---|---|
| `backend.yml` | PR touching `backend/`; called by the candidate pipeline | GitHub-hosted | uv locked install, Ruff, strict mypy, pytest with coverage on PostgreSQL 17, `alembic check`, OpenAPI drift |
| `frontend.yml` | PR touching `frontend/`; called by the candidate pipeline | GitHub-hosted | Client drift, Prettier, ESLint, tsc, Vitest with coverage, Vite build |
| `candidate.yml` | Push to `main`, or Run workflow | `ci`, then `test` | Build once, smoke test, secret scan, Trivy (fails on fixable critical), SBOM, GHCR by digest; Testing stack with backend unit/integration, frontend unit and Playwright journeys; Staging deploy, HTTPS verification and journeys; validated release manifest; automatic Production when `PROD_AUTO_PROMOTE` is `true` |
| `release.yml` | Run workflow (deferred mode) or called by the candidate pipeline (automatic mode) | `production` | Accepts only a validated manifest from a successful candidate run on `main` that is not older than Production; backs up, migrates, deploys, verifies over HTTPS, rolls back automatically on failure; `rollback` action redeploys the previous release |
| `operations.yml` | Nightly, monitoring changes on `main`, or Run workflow | `production`, `test` | Nightly Production backup to S3 and restore drill on the Test server; deploys Prometheus, Alertmanager and Grafana |
| `infra.yml` | PR or push touching `infra/`, `deploy/` or workflows | GitHub-hosted | Terraform fmt/validate, ansible-lint, ShellCheck, actionlint, Compose/Prometheus/Caddy validation, Trivy configuration scan |

Third-party actions are pinned to full commit SHAs and tool images to digests.
The repository is private on the free organisation plan, so branch protection
and environment reviewers are unavailable: one independent review before merge,
and the reviewed run ID for a deferred Production release, are team rules.

## The application image

`ghcr.io/ug-roombook/roombook:sha-<7>`, built from the root `Dockerfile`: Node
24.19.0 builds React, Python 3.12.14 with uv 0.13.1 installs the locked backend,
and the non-root runtime serves both. The commit is baked in, so `/version`
reports it in every environment; the same digest runs in Testing, Staging and
Production. `/metrics` (Prometheus format) is reachable on the private network
only; Caddy answers 404 for it publicly.

## Release gates

A candidate reaches Production only after every gate passes:

1. PR checks on the merged source.
2. Smoke test, secret scan and vulnerability gate on the built image.
3. Backend unit and integration tests (real PostgreSQL), frontend unit tests and
   browser journeys on the Test server against that digest.
4. Staging deployment of the same digest, verified over HTTPS (`/ready`,
   `/version` commit, rooms, React app, `/metrics` not public) and the browser
   journeys again.
5. The release workflow's provenance checks (manifest, `main` ancestry, not stale).
6. Production verification after deployment; failure restores the previous image.

Migrations must be backward compatible (expand now, contract in a later
release), because rollback restores the previous image and never downgrades
the database.

## Evidence to capture

Run graph per stage; runner names in job logs (`roombook-ci`, `roombook-test`,
`roombook-production`); candidate summary with commit and digest; Trivy report
and SBOM artifacts; test and browser reports; Staging and Production
`/version`; release summary and GitHub Deployments page; Grafana dashboard
with the deployment annotation; one failing test that stopped promotion; one
automatic rollback; nightly backup and restore-drill summaries.
