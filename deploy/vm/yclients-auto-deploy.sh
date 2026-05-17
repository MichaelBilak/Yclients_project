#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/yclients_bi_system}"
BRANCH="${BRANCH:-main}"
LOCK_FILE="${LOCK_FILE:-/var/lock/yclients-auto-deploy.lock}"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "Deploy is already running"
  exit 0
fi

cd "$APP_DIR"

if [ ! -d .git ]; then
  echo "$APP_DIR is not a git repository"
  exit 1
fi

git fetch --quiet origin "$BRANCH"

local_rev="$(git rev-parse HEAD)"
remote_rev="$(git rev-parse "origin/$BRANCH")"

if [ "$local_rev" = "$remote_rev" ]; then
  echo "Already up to date: $local_rev"
  exit 0
fi

echo "Deploying $local_rev -> $remote_rev"
git reset --hard "origin/$BRANCH"

docker compose build api worker migrate
docker compose run --rm migrate
docker compose up -d api worker

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

curl -fsS "http://127.0.0.1:${API_PORT:-8000}/health"
echo
echo "Deploy completed: $remote_rev"
