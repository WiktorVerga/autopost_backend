#!/usr/bin/env bash
# Scarica i segreti da Parameter Store e scrive deploy/.env
set -euo pipefail
cd "$(dirname "$0")"
aws ssm get-parameters-by-path \
  --path /autopost/prod/ --with-decryption --region eu-central-1 \
  --query 'Parameters[*].[Name,Value]' --output text |
while IFS=$'\t' read -r name value; do
  printf '%s=%s\n' "${name##*/}" "$value"
done > .env
chmod 600 .env
echo "Scritte $(wc -l < .env) variabili in deploy/.env"