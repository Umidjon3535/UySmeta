"""
UySmeta — Django sozlamalari. Barcha qiymatlar muhit o'zgaruvchilaridan (yoki `.env` faylidan) olinadi.
"""

import sys
from pathlib import Path
from urllib.parse import urlparse

import dj_database_url

from .env import env, env_bool, load_env_file

BASE_DIR = Path(__file__).resolve().parent.parent
load_env_file(BASE_DIR / ".env")

TESTING = len(sys.argv) > 1 and sys.argv[1] == "test"
DEBUG = env_bool("DJANGO_DEBUG", False)

# Saytning ommaviy manzili (sitemap, ulashish havolalari, Telegram webhook)
SITE_URL = (env("SITE_URL") or "http://localhost:8000").rstrip("/")

# Saytdagi aloqa ma'lumotlari (footer, "Biz haqimizda", oferta, bildirishnomalar)
CONTACT_PHONE = env("CONTACT_PHONE") or "+998954825335"
CONTACT_TELEGRAM = (env("CONTACT_TELEGRAM") or "uysmetabot").lstrip("@")

SECRET_KEY = env("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if not DEBUG and not TESTING:
        raise RuntimeError("DJANGO_SECRET_KEY sozlanmagan (production uchun majburiy)")
    SECRET_KEY = "dev-only-insecure-key"

_site_host = urlparse(SITE_URL).hostname or "localhost"
ALLOWED_HOSTS = [h.strip() for h in env("ALLOWED_HOSTS").split(",") if h.strip()] or [_site_host]
if DEBUG or TESTING:
    ALLOWED_HOSTS += ["localhost", "127.0.0.1", "[::1]", "testserver"]
CSRF_TRUSTED_ORIGINS = [f"{urlparse(SITE_URL).scheme}://{urlparse(SITE_URL).netloc}"]

# Ma'lumotlar papkasi: SQLite baza va yuklangan rasmlar
DATA_DIR = Path(env("DATA_DIR") or BASE_DIR / "data")
UPLOAD_DIR = Path(env("UPLOAD_DIR") or DATA_DIR / "uploads")

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "core.middleware.TrailingSlashMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.SecurityHeadersMiddleware",
    "core.middleware.CurrentUserMiddleware",
]

ROOT_URLCONF = "config.urls"
# URL'lar asl saytdagidek oxirgi "/" siz: /kirish, /ustalar/5 (Telegram xabarlaridagi havolalar ham shunday)
APPEND_SLASH = False

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "core.context_processors.site",
            ],
            "builtins": ["core.templatetags.ui"],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# PostgreSQL (Neon, Supabase yoki o'z serveringiz). Bo'sh bo'lsa — lokal SQLite (./data/uysmeta.sqlite3)
DATABASE_URL = env("DATABASE_URL")
if DATABASE_URL:
    DATABASES = {"default": dj_database_url.parse(DATABASE_URL, conn_max_age=60, conn_health_checks=True)}
else:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": DATA_DIR / "uysmeta.sqlite3",
            "OPTIONS": {"timeout": 20},
        }
    }
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

LANGUAGE_CODE = "uz"
TIME_ZONE = "Asia/Tashkent"
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
# Ishlab chiqishda collectstatic'siz ham static fayllar beriladi
WHITENOISE_AUTOREFRESH = DEBUG or TESTING
WHITENOISE_USE_FINDERS = DEBUG or TESTING

# Xona rasmi 5 MB gacha + multipart qo'shimchasi
DATA_UPLOAD_MAX_MEMORY_SIZE = 6 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 6 * 1024 * 1024

# Xavfsizlik
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
_https = SITE_URL.startswith("https://")
CSRF_COOKIE_SECURE = _https and not DEBUG
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if env_bool("BEHIND_PROXY", True) else None
# Odatda HTTPS'ga yo'naltirishni reverse-proxy (nginx, Caddy) bajaradi; kerak bo'lsa shu yerda yoqiladi
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", False)
SECURE_HSTS_SECONDS = int(env("SECURE_HSTS_SECONDS") or 0)
CSRF_FAILURE_VIEW = "core.views.pages.csrf_failure"

# UySmeta sozlamalari
ADMIN_PHONE = env("ADMIN_PHONE")
ADMIN_PASSWORD = env("ADMIN_PASSWORD")
SEED_DEMO_DATA = env_bool("SEED_DEMO_DATA", True)
OTP_SECRET = env("OTP_SECRET") or "uysmeta"

# Ichki hamyon (to'lov tizimisiz, bepul format)
WALLET_SIGNUP_BONUS = int(env("WALLET_SIGNUP_BONUS") or 300_000)  # ro'yxatdan o'tganda beriladi
WALLET_BONUS_WITHDRAWABLE = env_bool("WALLET_BONUS_WITHDRAWABLE", True)  # false — bonusni yechib bo'lmaydi
WALLET_MIN_WITHDRAW = int(env("WALLET_MIN_WITHDRAW") or 10_000)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {"django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False}},
}
