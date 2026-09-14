#!/usr/bin/env bash
# Run on a Linux Docker host. Images must already exist in the registry.
# No database credentials are transferred from GitHub: env files live on the host.
set -euo pipefail
image=${1:?Usage: deploy.sh ghcr.io/owner/image:commit_sha}
[[ "$image" =~ ^ghcr\.io/[a-z0-9._/-]+:[a-f0-9]{40}$ ]] || {
  echo 'Expected GHCR image pinned to a 40-character commit SHA' >&2; exit 1;
}
deploy_dir=${DEPLOY_DIR:-/opt/transfercar}
env_file=${APP_ENV_FILE:-$deploy_dir/app.env}
migration_env=${MIGRATION_ENV_FILE:-$deploy_dir/migration.env}
container=transfercar-dashboard
[[ -r "$env_file" && -r "$migration_env" ]] || {
  echo 'Configure app.env and migration.env on the deployment host first' >&2; exit 1;
}
# flock prevents concurrent host-side deployments.
exec 9>"$deploy_dir/deploy.lock"
flock -n 9 || { echo 'Deployment already in progress' >&2; exit 1; }
docker pull "$image"
docker run --rm --env-file "$migration_env" "$image" transfercar migrate
docker run --rm --env-file "$env_file" "$image" transfercar check-db
previous="${container}-rollback-$(date +%s)"
had_previous=false
renamed=false
rollback() {
  trap - ERR
  if "$renamed"; then
    docker rm -f "$container" >/dev/null 2>&1 || true
    docker rename "$previous" "$container"
    docker start "$container"
  elif "$had_previous"; then
    docker start "$container"
  else
    docker rm -f "$container" >/dev/null 2>&1 || true
  fi
  echo 'Deployment failed; restored previous application when available. Migrations retained.' >&2
  exit 1
}
trap rollback ERR
if docker container inspect "$container" >/dev/null 2>&1; then
  had_previous=true
  docker stop "$container"
  docker rename "$container" "$previous"
  renamed=true
fi
docker run -d --name "$container" --restart unless-stopped \
  --env-file "$env_file" -p 127.0.0.1:8501:8501 "$image"
healthy=false
for attempt in $(seq 1 30); do
  if curl --fail --silent http://127.0.0.1:8501/_stcore/health >/dev/null; then
    healthy=true
    break
  fi
  sleep 2
done
"$healthy"
trap - ERR
if "$had_previous"; then docker rm "$previous"; fi
echo "Deployed $image"
