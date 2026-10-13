#!/usr/bin/env bash
# Update the server to the latest code on GitHub and (re)start everything.
#
#   ./scripts/deploy.sh            pull, install, migrate, build, restart
#   ./scripts/deploy.sh --no-pull  same, without git pull (deploy local changes)
#
# Secrets are never in git: the script reads the database URLs from the
# repo-root .env, which you create once on the server (see .env.example).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

if [[ ! -f .env ]]; then
  echo "Missing $ROOT/.env. Copy .env.example to .env and fill it in first." >&2
  exit 1
fi

if [[ "${1:-}" != "--no-pull" ]]; then
  step "Pulling latest code"
  git pull --ff-only
fi

step "Installing bot dependencies"
[[ -d bot/.venv ]] || python3.12 -m venv bot/.venv
bot/.venv/bin/pip install --quiet --upgrade pip
bot/.venv/bin/pip install --quiet -e bot

step "Installing dashboard dependencies"
(cd dashboard && npm ci --no-audit --no-fund)

# Read KEY=value from .env without executing it (values may contain $, &, ...).
env_value() {
  grep -E "^$1=" .env | tail -n1 | cut -d= -f2- | sed -e 's/^["'\'']//' -e 's/["'\'']$//'
}

step "Applying database migrations"
BOTS_LIST="$(env_value BOTS)"
for id in $(echo "${BOTS_LIST:-vapiano,hubstore,tradezone}" | tr ',' ' '); do
  url="$(env_value "$(echo "$id" | tr '[:lower:]' '[:upper:]')_DATABASE_URL")"
  if [[ -z "$url" ]]; then
    echo "  $id: no database URL in .env, skipped"
    continue
  fi
  echo "  $id"
  (cd dashboard && DATABASE_URL="$url" npx prisma migrate deploy)
done

step "Building dashboard"
(cd dashboard && npm run build)

step "Starting / reloading processes"
pm2 startOrReload ecosystem.config.js --update-env
pm2 save

step "Done"
pm2 status
