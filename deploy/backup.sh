#!/usr/bin/env bash
set -euo pipefail
cd /home/autopost/autopost/deploy
mkdir -p /home/autopost/backups
docker compose exec -T db pg_dump -U autopost -Fc autopost \
  > /home/autopost/backups/autopost_$(date +%F).dump
find /home/autopost/backups -name '*.dump' -mtime +7 -delete   # conserva 7 giorni