"""
Sessiyalar bazada saqlanadi. Cookie'da tasodifiy token, bazada esa uning SHA-256 xeshi turadi —
baza sizib chiqsa ham tokenlarni tiklab bo'lmaydi. Cookie nomi va format asl versiya bilan bir xil.
"""

import hashlib
import random
import secrets
from datetime import timedelta
from functools import wraps
from urllib.parse import quote

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import HttpResponseRedirect
from django.utils import timezone

from .models import RateLimit, Session, User

COOKIE_NAME = "uysmeta_session"
SESSION_DAYS = 30


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(response, user_id: int) -> None:
    """Yangi sessiya ochib, cookie'ni javobga yozadi."""
    token = secrets.token_urlsafe(32)
    expires = timezone.now() + timedelta(days=SESSION_DAYS)
    Session.objects.create(id=hash_token(token), user_id=user_id, expires_at=expires)
    # Eskirgan sessiyalarni tozalash
    Session.objects.filter(expires_at__lt=timezone.now()).delete()
    response.set_cookie(
        COOKIE_NAME,
        token,
        expires=expires,
        httponly=True,
        secure=settings.SITE_URL.startswith("https://") and not settings.DEBUG,
        samesite="Lax",
        path="/",
    )


def destroy_session(request, response) -> None:
    token = request.COOKIES.get(COOKIE_NAME)
    if token:
        Session.objects.filter(id=hash_token(token)).delete()
    response.delete_cookie(COOKIE_NAME, path="/", samesite="Lax")


def load_user(request) -> User | None:
    token = request.COOKIES.get(COOKIE_NAME)
    if not token:
        return None
    session = Session.objects.select_related("user").filter(id=hash_token(token), expires_at__gt=timezone.now()).first()
    return session.user if session else None


def safe_next_path(value, fallback: str = "/") -> str:
    """"/smetalar" kabi ichki yo'llargagina qaytarish (open redirect'dan himoya)."""
    nxt = str(value or "")
    return nxt if nxt.startswith("/") and not nxt.startswith("//") and not nxt.startswith("/\\") else fallback


def login_redirect(next_path: str) -> HttpResponseRedirect:
    """Mehmonni ro'yxatdan o'tish sahifasiga yuboradi (u yerda «Kirish» tabi ham bor), keyin next ga qaytadi."""
    return HttpResponseRedirect(f"/royxat?next={quote(next_path, safe='')}")


def require_user(view):
    """Sahifalar uchun: kirmagan bo'lsa ro'yxatdan o'tish sahifasiga yuboradi."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.current_user:
            return login_redirect(request.get_full_path())
        return view(request, *args, **kwargs)

    return wrapper


# ---------- Urinishlar chegarasi (bazada — bir nechta server jarayonida ham to'g'ri ishlaydi) ----------


def check_rate_limit(key: str, limit: int = 5, window_seconds: int = 10 * 60) -> bool:
    """True — ruxsat bor; False — chegara oshdi."""
    now = timezone.now()
    for _ in range(2):
        try:
            with transaction.atomic():
                row = RateLimit.objects.select_for_update().filter(key=key).first()
                if row is None:
                    RateLimit.objects.create(key=key, count=1, reset_at=now + timedelta(seconds=window_seconds))
                    count = 1
                elif row.reset_at < now:
                    row.count, row.reset_at = 1, now + timedelta(seconds=window_seconds)
                    row.save(update_fields=["count", "reset_at"])
                    count = 1
                else:
                    row.count += 1
                    row.save(update_fields=["count"])
                    count = row.count
            break
        except IntegrityError:
            continue  # bir vaqtda ikkita so'rov yangi yozuv yaratdi — qayta urinamiz
    else:
        count = 1
    # Vaqti-vaqti bilan eskirgan yozuvlarni tozalash
    if random.random() < 0.02:
        RateLimit.objects.filter(reset_at__lt=now).delete()
    return count <= limit


def reset_rate_limit(key: str) -> None:
    RateLimit.objects.filter(key=key).delete()


def client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
    return forwarded or request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR") or "local"
