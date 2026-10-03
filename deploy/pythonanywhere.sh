#!/usr/bin/env bash
# UySmeta — PythonAnywhere (bepul, karta shart emas) ga joylash.
# PythonAnywhere → Consoles → Bash ichida:
#   git clone https://github.com/Umidjon3535/UySmeta.git && cd UySmeta && bash deploy/pythonanywhere.sh
# Oldin: Account → API token → "Create a new API token", so'ng YANGI Bash konsol oching ($API_TOKEN shunda paydo bo'ladi).
# Qayta ishga tushirsa ham bo'ladi: kod yangilanadi, .env saqlanadi.
set -euo pipefail
cd "$(dirname "$0")/.."
APP_DIR=$(pwd)
say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

USERNAME=${USER}
PA_HOST=${PYTHONANYWHERE_DOMAIN:-pythonanywhere.com}   # pythonanywhere.com yoki eu.pythonanywhere.com
DOMAIN="${USERNAME}.${PA_HOST}"
# API: AQSh hisoblari — www.pythonanywhere.com, Yevropa — eu.pythonanywhere.com
[ "$PA_HOST" = "pythonanywhere.com" ] && API_HOST="www.pythonanywhere.com" || API_HOST="$PA_HOST"
API="https://${API_HOST}/api/v0/user/${USERNAME}"
VENV="$HOME/.virtualenvs/uysmeta"
WSGI="/var/www/${DOMAIN//./_}_wsgi.py"

# 1. Python (eng yangisi) va virtual muhit
PY=""
for v in 3.13 3.12 3.11 3.10; do command -v "python$v" >/dev/null 2>&1 && { PY="python$v"; PYV="$v"; break; }; done
[ -n "$PY" ] || { echo "Python 3.10+ topilmadi"; exit 1; }
say "Virtual muhit ($PY) va kutubxonalar — 3–5 daqiqa"
[ -d "$VENV" ] || "$PY" -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r requirements.txt

# 2. .env (bir marta): haqiqiy rejim, maxfiy kalitlar avtomatik
if [ ! -f .env ]; then
  say ".env yaratilmoqda"
  cp deploy/env.production.example .env
  secret() { "$PY" -c "import secrets; print(secrets.token_urlsafe(48))"; }
  esc() { printf '%s' "$1" | sed -e 's/[\\&|]/\\&/g'; }
  sed -i "s|^DJANGO_SECRET_KEY=__AUTO__|DJANGO_SECRET_KEY=$(secret)|; s|^OTP_SECRET=__AUTO__|OTP_SECRET=$(secret)|" .env
  sed -i "s|^DOMAIN=.*|DOMAIN=${DOMAIN}|; s|^SITE_URL=.*|SITE_URL=https://${DOMAIN}|" .env
  # PythonAnywhere: HTTPS'ga yo'naltirishni o'zi bajaradi (force_https); veb-ilovada oqimlar yo'q — fon vazifalari so'rov ichida
  printf '\n# PythonAnywhere\nBACKGROUND_SYNC=true\n' >> .env

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
fi

# 3. Baza va static fayllar
say "Baza (migrate + boshlang'ich ma'lumotlar) va static fayllar"
"$VENV/bin/python" manage.py migrate --noinput
"$VENV/bin/python" manage.py collectstatic --noinput -v 0

# 4. Veb-ilova (API orqali): yaratish, virtualenv, static, HTTPS
if [ -n "${API_TOKEN:-}" ]; then
  say "Veb-ilova sozlanmoqda: https://${DOMAIN}"
  auth=(-H "Authorization: Token ${API_TOKEN}")
  curl -fsS "${auth[@]}" "$API/webapps/${DOMAIN}/" >/dev/null 2>&1 || \
    curl -fsS "${auth[@]}" -X POST "$API/webapps/" -d "domain_name=${DOMAIN}" -d "python_version=python${PYV//./}" >/dev/null
  curl -fsS "${auth[@]}" -X PATCH "$API/webapps/${DOMAIN}/" \
    -d "virtualenv_path=${VENV}" -d "source_directory=${APP_DIR}" -d "force_https=true" >/dev/null
  # /static/ — PythonAnywhere o'zi beradi (tezroq)
  if ! curl -fsS "${auth[@]}" "$API/webapps/${DOMAIN}/static_files/" | grep -q '"/static/"'; then
    curl -fsS "${auth[@]}" -X POST "$API/webapps/${DOMAIN}/static_files/" -d "url=/static/" -d "path=${APP_DIR}/staticfiles" >/dev/null
  fi
else
  say "API_TOKEN topilmadi — Web bo'limida qo'lda sozlang (DEPLOY.md, PythonAnywhere qismi):"
  echo "  Add a new web app → Manual configuration → Python ${PYV}"
  echo "  Virtualenv: ${VENV}"
  echo "  Static files: URL /static/  →  ${APP_DIR}/staticfiles"
  echo "  Force HTTPS: Enabled  →  Reload"
  echo "  (WSGI fayli tayyor: ${WSGI})"
fi

# 5. WSGI fayli (PythonAnywhere shu faylni ishga tushiradi). Veb-ilova yaratilgandan KEYIN —
# API yangi veb-ilovaga standart WSGI faylini yozadi va bizniki o'chib ketadi
cat > "$WSGI" <<EOF
# UySmeta — deploy/pythonanywhere.sh yaratgan
import os
import sys

sys.path.insert(0, "${APP_DIR}")
os.chdir("${APP_DIR}")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()
EOF

# 6. Qayta yuklash
if [ -n "${API_TOKEN:-}" ]; then
  # WSGI fayli diskka yozilib ulgurishi uchun biroz kutiladi (aks holda eski fayl yuklanishi mumkin)
  sleep 5
  curl -fsS -H "Authorization: Token ${API_TOKEN}" -X POST "$API/webapps/${DOMAIN}/reload/" >/dev/null
  say "Tayyor! Sayt: https://${DOMAIN}"
fi
echo "Keyingi qadam: saytga admin bo'lib kiring → Admin panel → Tizim holati → «Botni saytga ulash»."
