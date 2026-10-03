#!/usr/bin/env bash
# UySmeta — Ubuntu serverini (Oracle Cloud Free VM) bir buyruqda tayyorlash.
# Repozitoriy ichida ishga tushiring:  bash deploy/setup.sh
# Qiladi: Docker o'rnatadi, 80/443 portlarni ochadi, .env yaratadi (maxfiy kalitlar avtomatik), saytni ishga tushiradi.
set -euo pipefail
cd "$(dirname "$0")/.."

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

# 1. Docker
if ! command -v docker >/dev/null 2>&1; then
  say "Docker o'rnatilmoqda"
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER" || true
fi
DOCKER="docker"
docker info >/dev/null 2>&1 || DOCKER="sudo docker"

# 1b. Kichik serverda (1 GB RAM, VM.Standard.E2.1.Micro) yig'ish xotira yetmay to'xtamasin — 2 GB swap
mem_mb=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
if [ "$mem_mb" -lt 2000 ] && ! swapon --show | grep -q .; then
  say "Xotira kam (${mem_mb} MB) — 2 GB swap qo'shilmoqda"
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile >/dev/null && sudo swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
  export WEB_CONCURRENCY=2
fi

# 2. Oracle Ubuntu tasvirlarida iptables 80/443 ni yopiq tutadi — ochamiz (bulut "Security List"da ham ochish kerak, DEPLOY.md)
say "80 va 443 portlar ochilmoqda"
for port in 80 443; do
  sudo iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null || sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport "$port" -j ACCEPT
done
sudo iptables -C INPUT -p udp --dport 443 -j ACCEPT 2>/dev/null || sudo iptables -I INPUT 6 -p udp --dport 443 -j ACCEPT
if command -v netfilter-persistent >/dev/null 2>&1; then sudo netfilter-persistent save; else
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y iptables-persistent >/dev/null && sudo netfilter-persistent save; fi

# 3. .env (bir marta). Maxfiy kalitlar avtomatik, qolganini so'raymiz
if [ ! -f .env ]; then
  say ".env yaratilmoqda"
  cp deploy/env.production.example .env
  secret() { openssl rand -base64 48 | tr -d '\n/+=' | cut -c1-60; }
  # sed almashtirishida maxsus belgilar (\ & |) parol yoki tokenni buzmasin
  esc() { printf '%s' "$1" | sed -e 's/[\\&|]/\\&/g'; }
  sed -i "s|^DJANGO_SECRET_KEY=__AUTO__|DJANGO_SECRET_KEY=$(secret)|; s|^OTP_SECRET=__AUTO__|OTP_SECRET=$(secret)|" .env

  ip=$(curl -fsS https://api.ipify.org || true)
  default_domain="${ip//./-}.sslip.io"
  read -rp "Domen [Enter — ${default_domain}]: " domain
  domain=${domain:-$default_domain}
  domain=$(esc "$domain")
  sed -i "s|^DOMAIN=.*|DOMAIN=${domain}|; s|^SITE_URL=.*|SITE_URL=https://${domain}|" .env

  read -rp "Administrator telefoni [+998954825335]: " admin_phone
  sed -i "s|^ADMIN_PHONE=.*|ADMIN_PHONE=$(esc "${admin_phone:-+998954825335}")|" .env
  while :; do
    read -rsp "Administrator paroli (kamida 8 belgi): " admin_pass; echo
    [ ${#admin_pass} -ge 8 ] && break
    echo "Parol juda qisqa"
  done
  sed -i "s|^ADMIN_PASSWORD=.*|ADMIN_PASSWORD=$(esc "$admin_pass")|" .env

  read -rsp "Telegram bot tokeni (@BotFather; bo'sh qoldirsa ham bo'ladi): " tg_token; echo
  sed -i "s|^TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN=$(esc "$tg_token")|" .env
  chmod 600 .env
  echo "AI kalitlarini (GEMINI_API_KEY, ANTHROPIC_API_KEY) keyin .env ga qo'shishingiz mumkin: nano .env"
fi

# 4. Ishga tushirish
say "Sayt yig'ilmoqda va ishga tushirilmoqda (birinchi marta 3–6 daqiqa)"
$DOCKER compose -f docker-compose.prod.yml up -d --build

domain=$(grep '^DOMAIN=' .env | cut -d= -f2)
say "Tayyor! Sayt: https://${domain}"
echo "HTTPS sertifikati 1–2 daqiqada olinadi. Keyingi qadam: admin panel → Tizim holati → «Botni saytga ulash»."
echo "Loglar: $DOCKER compose -f docker-compose.prod.yml logs -f uysmeta"
