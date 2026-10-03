#!/usr/bin/env bash
# Yangi kodni GitHub'dan olib, saytni qayta yig'ish (baza va rasmlar saqlanadi).
# Ishlatish:  bash deploy/update.sh
set -euo pipefail
cd "$(dirname "$0")/.."
DOCKER="docker"
docker info >/dev/null 2>&1 || DOCKER="sudo docker"

git pull --ff-only
$DOCKER compose -f docker-compose.prod.yml up -d --build
$DOCKER image prune -f >/dev/null
echo "Yangilandi."
