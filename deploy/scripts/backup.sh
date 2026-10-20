#!/usr/bin/env bash
# Dump an environment's PostgreSQL database and upload it to the private S3
# operations bucket (encrypted at rest, expired by bucket lifecycle).
#
#   deploy/scripts/backup.sh <staging|production> [label]
#
# Called by deploy.sh before every Production migration and nightly by
# .github/workflows/backup.yml. Prints the S3 key of the dump.
set -euo pipefail

environment="${1:?environment: staging or production}"
label="${2:-scheduled}"
case "$environment" in staging | production) ;; *) echo "Unknown environment: $environment" >&2; exit 2 ;; esac
[[ "$label" =~ ^[a-z0-9-]+$ ]] || { echo "Label may contain only a-z, 0-9 and -" >&2; exit 2; }

# shellcheck source=/dev/null
. /etc/roombook/site.env
aws="${AWS_CLI:-/snap/bin/aws}"
project="roombook-$environment"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
local_dir="/srv/roombook/$environment/backups"
file="$local_dir/$stamp-$label.dump"
key="backups/$environment/$stamp-$label.dump"
mkdir -p "$local_dir"

container=$(docker ps --quiet --filter "label=com.docker.compose.project=$project" \
  --filter "label=com.docker.compose.service=db")
[[ -n "$container" ]] || { echo "No running database for $project" >&2; exit 1; }

started=$(date +%s)
docker exec "$container" pg_dump --username roombook --dbname roombook --format custom --no-owner > "$file"
size=$(stat -c %s "$file")
[[ "$size" -gt 0 ]] || { echo "Empty dump" >&2; exit 1; }

"$aws" s3 cp "$file" "s3://$OPS_BUCKET/$key" --region "$AWS_REGION" --only-show-errors \
  --metadata "environment=$environment,label=$label"

# Keep the three newest dumps on the host for a fast local restore.
find "$local_dir" -maxdepth 1 -name "*.dump" -printf "%T@ %p\n" | sort -rn | tail -n +4 | cut -d" " -f2- | xargs -r rm -f

echo "Backup $key ($size bytes) in $(( $(date +%s) - started )) s" >&2
echo "$key"
