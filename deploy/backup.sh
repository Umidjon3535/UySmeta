#!/usr/bin/env bash
# Zaxira nusxa: baza (SQLite) va yuklangan rasmlar/hujjatlar → ~/uysmeta-backups/uysmeta-YYYY-MM-DD.tar.gz
# Ishlatish:  bash deploy/backup.sh      (har kuni: crontab -e → 0 3 * * * bash ~/uysmeta/deploy/backup.sh)
set -euo pipefail
cd "$(dirname "$0")/.."
DOCKER="docker"
docker info >/dev/null 2>&1 || DOCKER="sudo docker"

dest="$HOME/uysmeta-backups"
mkdir -p "$dest"
name="uysmeta-$(date +%F)"
tmp=$(mktemp -d)
$DOCKER compose -f docker-compose.prod.yml cp uysmeta:/app/data "$tmp/data"
tar -czf "$dest/$name.tar.gz" -C "$tmp" data
rm -rf "$tmp"
# 14 kundan eski nusxalar o'chiriladi
find "$dest" -name 'uysmeta-*.tar.gz' -mtime +14 -delete
echo "Zaxira: $dest/$name.tar.gz"
