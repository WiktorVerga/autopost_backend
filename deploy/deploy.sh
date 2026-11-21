#!/usr/bin/env bash
set -euo pipefail
cd /opt/autopost
git pull --ff-only
cd deploy
./load-env.sh
docker compose pull backend
docker compose up -d
docker image prune -f
echo "Deploy completato: $(date -u)"