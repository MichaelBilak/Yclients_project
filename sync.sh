#!/usr/bin/env bash
# Docker-first запуск синхронизации данных YClients -> PostgreSQL
# Запуск вручную:  ./sync.sh incremental manual cli

set -euo pipefail

MODE="${1:-incremental}"
TRIGGER="${2:-manual}"
INITIATOR="${3:-shell}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cd "$SCRIPT_DIR"

DOCKER_BIN="${DOCKER_BIN:-docker}"
if ! command -v "$DOCKER_BIN" >/dev/null 2>&1; then
  if [ -x "/Applications/Docker.app/Contents/Resources/bin/docker" ]; then
    DOCKER_BIN="/Applications/Docker.app/Contents/Resources/bin/docker"
  else
    echo "Docker CLI не найден. Установите Docker и/или добавьте docker в PATH." >&2
    exit 127
  fi
fi

exec "$DOCKER_BIN" compose run --rm sync \
  --mode "$MODE" \
  --trigger "$TRIGGER" \
  --initiator "$INITIATOR"
