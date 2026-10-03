"""
Bir martalik tasdiqlash kodlari. Yetkazish kanallari:
 - telegram: foydalanuvchi botga o'z kontaktini yuboradi, bot raqamni tekshirib kodni yuboradi (bepul);
 - sms: Eskiz.uz orqali;
 - dev: hech qaysi kanal sozlanmagan bo'lsa, lokal ishlab chiqishda kod ekranda ko'rsatiladi.
Kod 6 xonali, 10 daqiqa amal qiladi, bazada faqat xeshi saqlanadi, 5 ta urinish.
"""

import hashlib
import logging
import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.db.models import F
from django.utils import timezone

from .constants import normalize_phone
from .models import OtpCode, TelegramLink
from .sms import send_sms, sms_configured, sms_dev_mode
from . import support, tg_login
from .telegram import CONTACT_KEYBOARD, REMOVE_KEYBOARD, bot_link, send_telegram_message, telegram_configured

log = logging.getLogger("uysmeta.otp")

CODE_TTL = timedelta(minutes=10)
RESEND_COOLDOWN_S = 60
MAX_PER_HOUR = 6
MAX_ATTEMPTS = 5

PURPOSE_TEXT = {
    "register": "ro'yxatdan o'tish",
    "reset": "parolni tiklash",
    "login": "tizimga kirish",
}


def hash_code(phone: str, code: str) -> str:
    return hashlib.sha256(f"{phone}:{code}:{settings.OTP_SECRET}".encode()).hexdigest()


def new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def sms_text(purpose: str, code: str) -> str:
    return f"UySmeta: {PURPOSE_TEXT[purpose]} kodi {code}. Kodni hech kimga bermang."


def telegram_text(purpose: str, code: str) -> str:
    return (
        f"🔐 UySmeta — {PURPOSE_TEXT[purpose]} kodi:\n\n<b>{code}</b>\n\n"
        "Kodni saytga kiriting. Uni hech kimga bermang — UySmeta xodimlari kod so'ramaydi."
    )


def otp_channels() -> list[str]:
    """Qaysi kanallar mavjud (UI shunga qarab tugmalarni ko'rsatadi)."""
    channels = []
    if telegram_configured():
        channels.append("telegram")
    if sms_configured():
        channels.append("sms")
    if not channels and sms_dev_mode():
        channels.append("dev")
    return channels


def resolve_channel(requested: str) -> str | None:
    """So'ralgan kanal ulangan bo'lsa o'shani, aks holda birinchi mavjud kanalni qaytaradi."""
    channels = otp_channels()
    if requested in channels:
        return requested
    return channels[0] if channels else None


def send_otp(phone: str, purpose: str, requested: str) -> dict:
    """{"ok": True, "channel", "telegram_url"?, "delivered", "dev_code"?} yoki {"ok": False, "error"}."""
    channel = resolve_channel(requested)
    if not channel:
        return {"ok": False, "error": "Tasdiqlash xizmati hozircha sozlanmagan. Administratorga murojaat qiling"}

    now = timezone.now()
    last = OtpCode.objects.filter(phone=phone, purpose=purpose).order_by("-id").first()
    if last:
        age = int((now - last.created_at).total_seconds())
        if age < RESEND_COOLDOWN_S:
            return {"ok": False, "error": f"Yangi kod olish uchun {RESEND_COOLDOWN_S - age} soniya kuting"}
    recent = OtpCode.objects.filter(phone=phone, created_at__gt=now - timedelta(hours=1)).count()
    if recent >= MAX_PER_HOUR:
        return {"ok": False, "error": "Juda ko'p kod so'raldi. Bir soatdan keyin urinib ko'ring"}

    # Oldingi ishlatilmagan kodlar bekor qilinadi
    OtpCode.objects.filter(phone=phone, purpose=purpose, used_at__isnull=True).update(used_at=now)
    expires = now + CODE_TTL

    if channel == "telegram":
        token = secrets.token_urlsafe(12)
        # Raqam avval botda tasdiqlangan bo'lsa — kod darhol yuboriladi
        link = TelegramLink.objects.filter(phone=phone).first()
        delivered = False
        code_hash = None
        if link:
            code = new_code()
            try:
                send_telegram_message(link.chat_id, telegram_text(purpose, code))
                code_hash = hash_code(phone, code)
                delivered = True
            except Exception as error:
                # Foydalanuvchi botni bloklagan bo'lishi mumkin — kontakt orqali qayta tasdiqlaydi
                log.warning("[otp] telegram yuborilmadi: %s", error)
        OtpCode.objects.create(
            phone=phone,
            purpose=purpose,
            channel="telegram",
            code_hash=code_hash,
            start_token=token,
            tg_chat_id=link.chat_id if delivered else None,
            expires_at=expires,
        )
        return {"ok": True, "channel": channel, "telegram_url": bot_link(token), "delivered": delivered}

    code = new_code()
    OtpCode.objects.create(phone=phone, purpose=purpose, channel=channel, code_hash=hash_code(phone, code), expires_at=expires)
    if channel == "sms":
        if not send_sms(phone, sms_text(purpose, code)):
            return {"ok": False, "error": "SMS yuborib bo'lmadi. Telegram orqali urinib ko'ring"}
        return {"ok": True, "channel": channel, "delivered": True}
    log.info("[otp:dev] %s: %s", phone, code)
    return {"ok": True, "channel": channel, "delivered": True, "dev_code": code}


def verify_otp(phone: str, purpose: str, code: str) -> tuple[bool, str]:
    """Kodni tekshiradi va to'g'ri bo'lsa ishlatilgan deb belgilaydi. (ok, xato matni)."""
    row = OtpCode.objects.filter(phone=phone, purpose=purpose, used_at__isnull=True).order_by("-id").first()
    if not row:
        return False, "Avval tasdiqlash kodini oling"
    if row.expires_at < timezone.now():
        return False, "Kod muddati tugagan. Yangi kod oling"
    if not row.code_hash:
        return False, "Kod hali yuborilmagan: Telegram botni ochib, raqamingizni yuboring"
    if row.attempts >= MAX_ATTEMPTS:
        return False, "Urinishlar tugadi. Yangi kod oling"

    if row.code_hash != hash_code(phone, re.sub(r"\D", "", code or "")):
        OtpCode.objects.filter(id=row.id).update(attempts=F("attempts") + 1)
        left = MAX_ATTEMPTS - row.attempts - 1
        return False, (f"Kod noto'g'ri. Yana {left} ta urinish qoldi" if left > 0 else "Urinishlar tugadi. Yangi kod oling")

    OtpCode.objects.filter(id=row.id).update(used_at=timezone.now())
    return True, ""


# ============================ TELEGRAM BOT ============================


def handle_telegram_update(update: dict) -> None:
    """Telegram'dan kelgan xabarni qayta ishlash (webhook yoki lokal polling orqali)."""
    msg = update.get("message") or {}
    chat = msg.get("chat") or {}
    if not msg or chat.get("type") != "private":
        return
    chat_id = str(chat["id"])
    text = msg.get("text") or ""
    now = timezone.now()

    # 1) /start <token> — saytdan kelgan foydalanuvchi
    if text.startswith("/start"):
        parts = text.split()
        token = parts[1] if len(parts) > 1 else None
        # "Telegram orqali kirish" (ro'yxatdan o'tish ham) — core/tg_login.py
        if token and token.startswith(tg_login.START_PREFIX):
            tg_login.handle_start(chat_id, token[len(tg_login.START_PREFIX):])
            return
        if token:
            updated = OtpCode.objects.filter(start_token=token, used_at__isnull=True, expires_at__gt=now).update(tg_chat_id=chat_id)
            if not updated:
                send_telegram_message(chat_id, "⏳ Bu havola eskirgan. Saytga qaytib, yangi kod so'rang.")
                return
            send_telegram_message(
                chat_id,
                "👋 Assalomu alaykum! Bu <b>UySmeta</b> boti.\n\nTelefon raqamingizni tasdiqlash uchun pastdagi "
                "<b>«📱 Raqamimni yuborish»</b> tugmasini bosing — kodni shu yerga yuboramiz.",
                CONTACT_KEYBOARD,
            )
            return
        send_telegram_message(
            chat_id,
            "👋 Bu <b>UySmeta</b> boti — ta'mirlash smetasi xizmati.\n\nSaytga kirish yoki ro'yxatdan o'tish uchun saytda "
            f"<b>«Telegram orqali kirish»</b> tugmasini bosing: {settings.SITE_URL}/kirish/telegram",
        )
        return

    # Administrator yordam chati xabariga "Reply" qildi — javob mijozga (core/support.py)
    if msg.get("reply_to_message") and support.handle_admin_telegram_reply(chat_id, msg):
        return

    # 2) Kontakt yuborildi — raqam foydalanuvchining o'ziniki ekanini tekshiramiz
    contact = msg.get("contact")
    if contact:
        sender = msg.get("from") or {}
        if not sender or contact.get("user_id") != sender.get("id"):
            send_telegram_message(
                chat_id, "❗ Iltimos, boshqa odamning emas, <b>o'z</b> raqamingizni tugma orqali yuboring.", CONTACT_KEYBOARD
            )
            return
        login = tg_login.pending_for_chat(chat_id)
        if login:
            tg_login.handle_contact(chat_id, login, contact, sender)
            return
        phone = normalize_phone(contact.get("phone_number"))
        pending = (
            OtpCode.objects.filter(tg_chat_id=chat_id, channel="telegram", used_at__isnull=True, expires_at__gt=now)
            .order_by("-id")
            .first()
        )
        if not pending:
            send_telegram_message(
                chat_id, "Faol so'rov topilmadi. Saytda «Telegram orqali kod olish» tugmasini qayta bosing.", REMOVE_KEYBOARD
            )
            return
        if not phone or phone != pending.phone:
            send_telegram_message(
                chat_id,
                "❗ Telegram raqamingiz saytda kiritilgan raqamga mos kelmadi.\n\n"
                "Saytda Telegram'ingizga ulangan raqamni kiriting yoki SMS orqali tasdiqlang.",
                REMOVE_KEYBOARD,
            )
            return
        code = new_code()
        OtpCode.objects.filter(id=pending.id).update(code_hash=hash_code(phone, code), attempts=0)
        TelegramLink.objects.update_or_create(phone=phone, defaults={"chat_id": chat_id, "updated_at": now})
        send_telegram_message(chat_id, telegram_text(pending.purpose, code), REMOVE_KEYBOARD)
        return

    send_telegram_message(chat_id, f"Saytga kirish uchun saytda «Telegram orqali kirish» tugmasini bosing: {settings.SITE_URL}/kirish/telegram")
