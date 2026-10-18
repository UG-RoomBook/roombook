# CI, image and candidate pipeline

Owner: Prattay (RB-20, RB-21, RB-22, RB-23 Testing part). Reviewers per Jira.
Follows ADR-003 (one image promoted by digest) and ADR-010 (GitHub-hosted CI
and Testing; no application builds on the VPS).

## Workflows

| Workflow | Trigger | What it does |
|---|---|---|
| `backend.yml` | Pull request touching `backend/`; called by the candidate pipeline | Locked install with uv, Ruff lint and format, strict mypy, pytest with coverage against PostgreSQL 17, `alembic check`, OpenAPI export drift check. JUnit and coverage XML kept as artifacts |
| `frontend.yml` | Pull request touching `frontend/`; called by the candidate pipeline | Generated-client drift, Prettier, ESLint, tsc, Vitest with coverage, Vite build |
| `candidate.yml` | Push to `main`, or Run workflow | Both check workflows, then build **one** image, smoke-test it, scan it for bundled secrets, publish to GHCR, record the digest, then test that exact digest against a disposable PostgreSQL |

All jobs run on GitHub-hosted `ubuntu-24.04`. Third-party actions are pinned to
full commit SHAs. The repository is private on the free organisation plan, so
branch rulesets are not enforced: one independent review before merge is a
recorded team rule, not platform protection.

## The application image

`ghcr.io/ug-roombook/roombook:sha-<first 7 characters>`, built from the root
`Dockerfile`:

1. Node 24.19.0 builds the React app (`npm ci`, `npm run build`).
2. Python 3.12.14 with uv 0.13.1 installs the locked backend dependencies.
3. The runtime stage holds the virtual environment, `app/`, `alembic/`,
   `scripts/` and the React build in `/app/static`; it runs as a non-root user.

`ROOMBOOK_STATIC_DIR=/app/static` turns on the React fallback
(`app/core/frontend.py`). It is registered after every API route, so `/api/*`,
`/health`, `/ready` and `/version` always reach FastAPI and unknown `/api` paths
keep the JSON 404 envelope. Fingerprinted `/assets/*` files are cached for a
year; `index.html` is revalidated on every request.

The commit is baked in (`ROOMBOOK_COMMIT_SHA`), so `/version` reports the
source commit in every environment. Supply at runtime:

| Variable | Example |
|---|---|
| `ROOMBOOK_DATABASE_URL` | `postgresql+psycopg://user:password@host:5432/roombook` (secret) |
| `ROOMBOOK_ENVIRONMENT` | `staging` or `production` |

Release steps, run with the same image before switching traffic:

```bash
alembic upgrade head
python -m scripts.seed_rooms
```

Build and run locally (PowerShell or bash, from the repository root):

```bash
docker build -t roombook:local --build-arg COMMIT_SHA=$(git rev-parse HEAD) .
docker run --rm -p 8000:8000 -e ROOMBOOK_ENVIRONMENT=local roombook:local
```

## What each candidate run proves

| Check | Where |
|---|---|
| All PR checks pass on the merged source | `backend-checks`, `frontend-checks` |
| API routes win over the React fallback; `/version` reports the commit | build job smoke test |
| No `.env` files, private keys or database URLs with passwords in the image | build job secret check |
| Image published once, with its digest | build job summary and `candidate-manifest` artifact |
| The exact digest migrates, seeds, connects to PostgreSQL and serves rooms | `test-candidate` |

The manifest marks every candidate `promotable: false` until the Staging,
browser and release gates exist and pass (RB-23, RB-26).

## Attaching the next stages

- **Browser journeys (Daniel):** add Playwright steps to `test-candidate`
  against `http://127.0.0.1:8000` (marked in the workflow).
- **Staging (RB-23, with Bhathiya):** a `staging` job after `test-candidate`
  that calls the server-owned deploy command over the restricted Staging SSH
  identity with `needs.build.outputs.ref`, then verifies HTTPS, `/ready` and
  `/version`.
- **Production (RB-26):** `workflow_dispatch` by default, accepting a validated
  candidate run, never an arbitrary tag.

## Evidence to capture

Pipeline run graph; run summary with commit, image and digest; GHCR package page
with `sha-` tags; `candidate-manifest` artifact; build time; a run where a
failing check stopped the build; `test-candidate` log showing `/ready` and rooms.
