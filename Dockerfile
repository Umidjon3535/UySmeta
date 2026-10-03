# UySmeta — production Docker image (Django + gunicorn)
# Build:  docker build -t uysmeta .
# Run:    docker compose up -d   (docker-compose.yml ga qarang)

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/app/data

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .
# collectstatic sozlamalarni yuklaydi — build vaqtida vaqtinchalik kalit yetarli
RUN DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput

RUN useradd --system --create-home app && mkdir -p /app/data && chown -R app:app /app/data
USER app

EXPOSE 8000
# Baza (SQLite bo'lsa) va rasmlar shu papkada — volume sifatida ulang
VOLUME ["/app/data"]
# Ishga tushishda migratsiyalar (va boshlang'ich ma'lumotlar) avtomatik qo'llanadi
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers ${WEB_CONCURRENCY:-3} --timeout 120 --access-logfile -"]
