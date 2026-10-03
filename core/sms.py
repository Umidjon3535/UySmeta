"""
SMS yuborish. Provayder: Eskiz.uz (https://notify.eskiz.uz).
ESKIZ_EMAIL va ESKIZ_PASSWORD berilmagan bo'lsa:
 - DEBUG rejimida SMS konsolga yoziladi va kod ekranda ko'rsatiladi (sinash uchun);
 - production'da xato qaytadi (kod hech qayerda ko'rinmaydi).
Eslatma: Eskiz'da yuboriladigan matn shabloni oldindan tasdiqlangan bo'lishi kerak.
"""

import logging
import os
import time

import requests
from django.conf import settings

log = logging.getLogger("uysmeta.sms")

ESKIZ_BASE = "https://notify.eskiz.uz/api"


def sms_configured() -> bool:
    return bool(os.environ.get("ESKIZ_EMAIL") and os.environ.get("ESKIZ_PASSWORD"))


def sms_dev_mode() -> bool:
    """
    SMS provayderisiz dev rejimi: kod foydalanuvchiga ekranda ko'rsatiladi.
    Production'da faqat SMS_DEBUG_SHOW_CODE=true bilan (test/staging serverlar uchun) — haqiqiy saytda YOQMANG.
    """
    return not sms_configured() and (settings.DEBUG or settings.TESTING or os.environ.get("SMS_DEBUG_SHOW_CODE") == "true")


_cached_token: dict | None = None


def _eskiz_token(force_refresh: bool = False) -> str:
    global _cached_token
    if not force_refresh and _cached_token and _cached_token["expires_at"] > time.time():
        return _cached_token["value"]
    res = requests.post(
        f"{ESKIZ_BASE}/auth/login",
        data={"email": os.environ["ESKIZ_EMAIL"], "password": os.environ["ESKIZ_PASSWORD"]},
        timeout=20,
    )
    if not res.ok:
        raise RuntimeError(f"Eskiz login xatosi: {res.status_code}")
    token = (res.json().get("data") or {}).get("token")
    if not token:
        raise RuntimeError("Eskiz token qaytarmadi")
    # Token 30 kun amal qiladi — xavfsizlik uchun 20 kun keshlaymiz
    _cached_token = {"value": token, "expires_at": time.time() + 20 * 24 * 60 * 60}
    return token


def _eskiz_send(phone: str, message: str, retry: bool = True) -> None:
    token = _eskiz_token(force_refresh=not retry)
    res = requests.post(
        f"{ESKIZ_BASE}/message/sms/send",
        headers={"Authorization": f"Bearer {token}"},
        data={"mobile_phone": phone.lstrip("+"), "message": message, "from": os.environ.get("ESKIZ_FROM") or "4546"},
        timeout=20,
    )
    if res.status_code == 401 and retry:
        return _eskiz_send(phone, message, retry=False)  # token eskirgan
    if not res.ok:
        raise RuntimeError(f"Eskiz SMS xatosi: {res.status_code} {res.text}")


def send_sms(phone: str, message: str) -> bool:
    if sms_configured():
        try:
            _eskiz_send(phone, message)
            return True
        except Exception:
            log.exception("[sms] yuborilmadi")
            return False
    if sms_dev_mode():
        log.info("[sms:dev] %s: %s", phone, message)
        return True
    log.error("[sms] ESKIZ_EMAIL / ESKIZ_PASSWORD sozlanmagan")
    return False
