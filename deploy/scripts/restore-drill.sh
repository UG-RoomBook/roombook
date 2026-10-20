#!/usr/bin/env bash
# Restore drill: prove the newest Production backup can actually be restored.
#
#   deploy/scripts/restore-drill.sh [s3 key]
#
# Runs on the Test host (never on Production). Downloads the dump, restores it
# into a throwaway PostgreSQL container, checks the schema and data, reports
# the measured restore time, and removes everything it created.
set -euo pipefail

# shellcheck source=/dev/null
. /etc/roombook/site.env
aws="${AWS_CLI:-/snap/bin/aws}"
postgres_image="postgres:17.11@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3"
key="${1:-}"
if [[ -z "$key" ]]; then
  key=$("$aws" s3api list-objects-v2 --bucket "$OPS_BUCKET" --prefix backups/production/ --region "$AWS_REGION" \
    --query 'sort_by(Contents, &LastModified)[-1].Key' --output text)
fi
[[ "$key" == backups/production/*.dump ]] || { echo "No Production backup found ($key)" >&2; exit 1; }

work=$(mktemp -d)
name="roombook-restore-drill-$$"
cleanup() { docker rm -f "$name" >/dev/null 2>&1 || true; rm -rf "$work"; }
trap cleanup EXIT

started=$(date +%s)
"$aws" s3 cp "s3://$OPS_BUCKET/$key" "$work/backup.dump" --region "$AWS_REGION" --only-show-errors
docker run -d --name "$name" -e POSTGRES_USER=roombook -e POSTGRES_PASSWORD=drill -e POSTGRES_DB=roombook \
  --tmpfs /var/lib/postgresql/data "$postgres_image" >/dev/null
for _ in $(seq 1 30); do docker exec "$name" pg_isready -U roombook -d roombook >/dev/null 2>&1 && break; sleep 1; done
docker exec -i "$name" pg_restore --username roombook --dbname roombook --no-owner --exit-on-error < "$work/backup.dump"
restored=$(date +%s)

query() { docker exec "$name" psql --username roombook --dbname roombook --tuples-only --no-align -c "$1"; }
revision=$(query "select version_num from alembic_version")
rooms=$(query "select count(*) from rooms")
bookings=$(query "select count(*) from bookings")
[[ -n "$revision" ]] || { echo "Restored database has no Alembic revision" >&2; exit 1; }
[[ "$rooms" -ge 1 ]] || { echo "Restored database has no rooms" >&2; exit 1; }

jq -n --arg key "$key" --arg revision "$revision" --argjson rooms "$rooms" --argjson bookings "$bookings" \
  --argjson restore_seconds "$(( restored - started ))" \
  '{backup: $key, alembic_revision: $revision, rooms: $rooms, bookings: $bookings,
    restore_seconds: $restore_seconds, result: "restored and verified"}'
