#!/usr/bin/env bash
# Deploy one validated image to a persistent environment, verify it, and roll
# back to the previous image if verification fails (ADR-003, ADR-005, ADR-012).
#
#   deploy/scripts/deploy.sh <staging|production> <ghcr.io/...@sha256:...> <commit sha>
#
# Runs on the host's self-hosted runner (test host for staging, production host
# for production). The workflow has already logged in to GHCR.
#
# Steps: lock -> pull by digest -> check the image was built from the commit ->
# start the database -> (production) back up -> migrate -> seed reference rooms ->
# start the new app -> verify /ready and /version inside and over HTTPS ->
# record the release, or restore the previous image and fail.
#
# Migrations must be backward compatible (expand, then contract in a later
# release): rollback restores the previous image and never downgrades the
# database.
set -euo pipefail

environment="${1:?environment: staging or production}"
ref="${2:?image reference pinned by digest}"
commit="${3:?full commit SHA}"

case "$environment" in staging | production) ;; *) echo "Unknown environment: $environment" >&2; exit 2 ;; esac
[[ "$ref" =~ ^ghcr\.io/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$ ]] || { echo "Not a digest-pinned GHCR reference: $ref" >&2; exit 2; }
[[ "$commit" =~ ^[0-9a-f]{40}$ ]] || { echo "Not a full commit SHA: $commit" >&2; exit 2; }

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
deploy_dir="$(cd "$here/.." && pwd)"
state="/srv/roombook/$environment"
project="roombook-$environment"
export ROOMBOOK_ENV_FILE="/etc/roombook/$environment.env"
[[ -r "$ROOMBOOK_ENV_FILE" ]] || { echo "Missing $ROOMBOOK_ENV_FILE: run infra/scripts/configure-hosts.ps1" >&2; exit 1; }
# shellcheck source=/dev/null
. /etc/roombook/site.env
export SITE_HOST

# Each release keeps its own copy of the deployment files, so containers never
# depend on the runner's workspace (the next checkout rewrites it), and a
# rollback runs with the previous release's own configuration.
config_dir="$state/releases/${commit:0:12}"
compose() {
  docker compose -p "$project" -f "$config_dir/compose/stack.yml" \
    --env-file /etc/roombook/site.env "$@"
}
log() { printf '%s %s\n' "$(date -u +%H:%M:%S)" "$*"; }
record() {
  jq -cn --arg at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg env "$environment" \
    --arg result "$1" --arg ref "$ref" --arg commit "$commit" --arg previous "${previous:-}" \
    --arg run "${GITHUB_SERVER_URL:-}/${GITHUB_REPOSITORY:-}/actions/runs/${GITHUB_RUN_ID:-local}" \
    --argjson seconds "$(( $(date +%s) - started ))" \
    '{at: $at, environment: $env, result: $result, ref: $ref, commit: $commit,
      previous: $previous, seconds: $seconds, run: $run}' >> "$state/deployments.jsonl"
}

# Check one running release: readiness inside the container, then the public
# HTTPS endpoint must report the expected commit.
verify() {
  local expected="$1"
  log "Verifying commit ${expected:0:7} on $environment"
  for _ in $(seq 1 30); do
    if compose exec -T app python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=2).status == 200 else 1)" 2>/dev/null; then
      break
    fi
    sleep 2
  done
  compose exec -T app python - "$expected" <<'PY' || return 1
import json, sys, urllib.request
want = sys.argv[1]
ready = urllib.request.urlopen("http://127.0.0.1:8000/ready", timeout=3)
assert ready.status == 200, f"/ready returned {ready.status}"
version = json.load(urllib.request.urlopen("http://127.0.0.1:8000/version", timeout=3))
assert version["commit_sha"] == want, f"/version reports {version['commit_sha']}, expected {want}"
print(f"inside: ready, commit {want[:7]}, environment {version['environment']}")
PY
  # Public path: Caddy, TLS certificate and DNS (first issuance can take a minute).
  local body
  body=$(curl -fsS --retry 20 --retry-all-errors --retry-delay 3 --max-time 10 "https://$SITE_HOST/version") || {
    echo "HTTPS check failed for https://$SITE_HOST/version" >&2; return 1; }
  jq -e --arg want "$expected" '.commit_sha == $want' <<<"$body" >/dev/null || {
    echo "Public /version reports $(jq -r .commit_sha <<<"$body"), expected $expected" >&2; return 1; }
  curl -fsS --max-time 10 "https://$SITE_HOST/api/v1/rooms?limit=1" | jq -e '.total >= 1' >/dev/null || {
    echo "Room listing failed over HTTPS" >&2; return 1; }
  curl -fsS --max-time 10 "https://$SITE_HOST/" | grep -q 'id="root"' || {
    echo "The React app is not served at /" >&2; return 1; }
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "https://$SITE_HOST/metrics")
  [[ "$code" == 404 ]] || { echo "/metrics is publicly reachable (HTTP $code)" >&2; return 1; }
  log "public: https://$SITE_HOST serves commit ${expected:0:7}"
}

mkdir -p "$state"
exec 9>"$state/deploy.lock"
log "Waiting for the $environment deployment lock"
flock -w 900 9 || { echo "Another $environment deployment is still running" >&2; exit 1; }

started=$(date +%s)
previous="$(cat "$state/current.ref" 2>/dev/null || true)"
previous_commit="$(cat "$state/current.commit" 2>/dev/null || true)"
log "Deploying ${ref##*@} (commit ${commit:0:7}) to $environment; previous: ${previous:+${previous##*@}}${previous:-none}"

mkdir -p "$config_dir/compose"
cp "$deploy_dir/compose/stack.yml" "$config_dir/compose/stack.yml"
cp -r "$deploy_dir/caddy" "$config_dir/"
current_config="$config_dir"

docker pull --quiet "$ref" >/dev/null
revision=$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$ref")
[[ "$revision" == "$commit" ]] || { echo "Image was built from $revision, not $commit" >&2; exit 1; }

export ROOMBOOK_IMAGE="$ref"
compose up -d --wait db

if [[ "$environment" == production ]]; then
  "$here/backup.sh" production "pre-${commit:0:7}"
fi

log "Applying migrations with the new image"
compose run --rm --no-deps -T app alembic upgrade head
log "Seeding reference rooms (inserts only missing rooms)"
compose run --rm --no-deps -T app python -m scripts.seed_rooms

log "Starting the new application"
compose up -d --wait --wait-timeout 180 --remove-orphans app caddy

if verify "$commit"; then
  # Keep the five newest release folders.
  find "$state/releases" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -rn | tail -n +6 \
    | cut -d' ' -f2- | xargs -r rm -rf
  echo "$ref" > "$state/current.ref"
  echo "$commit" > "$state/current.commit"
  if [[ -n "$previous" && "$previous" != "$ref" ]]; then
    echo "$previous" > "$state/previous.ref"
    echo "$previous_commit" > "$state/previous.commit"
  fi
  record success
  log "Release live on $environment in $(( $(date +%s) - started )) s"
  exit 0
fi

echo "::error::Verification failed for ${commit:0:7} on $environment" >&2
compose logs --no-color --tail 100 app >&2 || true
if [[ -n "$previous" && "$previous" != "$ref" ]]; then
  log "Rolling back to the previous image ${previous##*@}"
  export ROOMBOOK_IMAGE="$previous"
  previous_config="$state/releases/${previous_commit:0:12}"
  [[ -f "$previous_config/compose/stack.yml" ]] && config_dir="$previous_config" || config_dir="$current_config"
  compose up -d --wait --wait-timeout 180 app
  if verify "$previous_commit"; then
    record rolled-back
    echo "::error::Rolled back to ${previous_commit:0:7}; the failed release is not live." >&2
  else
    record rollback-failed
    echo "::error::Rollback verification also failed. Operator intervention needed (see docs/deploy/runbook.md)." >&2
  fi
else
  record failed
  echo "::error::No previous release to roll back to." >&2
fi
exit 1
