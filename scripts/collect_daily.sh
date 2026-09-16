#!/usr/bin/env bash
# Run from cron or manually. The private env file supplies the collector's DATABASE_URL.
set -euo pipefail
umask 077

project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$project_dir"
export TZ=Pacific/Auckland
day=$(date +%F)
state_dir="$project_dir/.local"
log_dir="$state_dir/logs/collection"
mkdir -p "$log_dir"
exec >>"$log_dir/$day.log" 2>&1

# This also covers manual invocations; PostgreSQL additionally locks the collection scope.
exec 9>"$state_dir/collect-daily.lock"
if ! flock -n 9; then
  printf '[%s] Skipped: another local collection is running.\n' "$(date -Is)"
  exit 0
fi

finish() {
  result=$?
  printf '[%s] Finished: exit_code=%s\n' "$(date -Is)" "$result"
}
trap finish EXIT
printf '[%s] Starting daily collection for %s.\n' "$(date -Is)" "$day"

config="$state_dir/supabase-runtime.env"
python="$project_dir/.venv/bin/python"
[[ -r "$config" ]] || { echo 'Missing .local/supabase-runtime.env' >&2; exit 1; }
[[ -x "$python" ]] || { echo 'Missing project Python virtual environment' >&2; exit 1; }
# Load only the configured connection, never fall back to an inherited admin/dev URL.
unset DATABASE_URL
set -a
source "$config"
set +a
[[ -n "${DATABASE_URL:-}" ]] || { echo 'DATABASE_URL is missing from runtime config' >&2; exit 1; }
unset DASHBOARD_DATABASE_URL SUPABASE_ADMIN_DATABASE_URL

# Same NZ date => same logical batch. Successful replays do not fetch or insert again.
run_id=$("$python" -c 'import sys,uuid; print(uuid.uuid5(uuid.NAMESPACE_URL, "transfercar-history:daily:all-nz:v1:" + sys.argv[1]))' "$day")
printf 'run_id=%s\n' "$run_id"
timeout --signal=TERM --kill-after=30s 20m \
  "$python" -m transfercar.cli collect --run-id "$run_id"
