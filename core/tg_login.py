"""
Telegram bot orqali kirish va ro'yxatdan o'tish (parolsiz):
 1. Sayt: start_login() → token, havola t.me/<bot>?start=login_<token>
 2. Bot: /start login_<token> → "📱 Raqamimni yuborish" tugmasi
 3. Bot: o'z kontakti keldi → hisob bo'lsa topiladi, bo'lmasa Telegram ismi bilan yaratiladi → "confirmed"
 4. Sayt: holatni so'raydi (yoki botdagi "Saytga qaytish" havolasi) → sessiya ochiladi, token "used"
Token 10 daqiqa amal qiladi va bir marta ishlatiladi.
"""

import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .constants import normalize_phone
from .models import TelegramLink, TelegramLogin, User
from .telegram import CONTACT_KEYBOARD, REMOVE_KEYBOARD, bot_link, send_telegram_message
from .wallet import grant_signup_bonus

log = logging.getLogger("uysmeta.tg_login")

LOGIN_TTL = timedelta(minutes=10)
START_PREFIX = "login_"


def start_login(next_path: str = "") -> TelegramLogin:
    return TelegramLogin.objects.create(
        token=secrets.token_urlsafe(18), next_path=next_path[:200], expires_at=timezone.now() + LOGIN_TTL
    )


def login_url(login: TelegramLogin) -> str:
    return bot_link(START_PREFIX + login.token)


def active_login(token: str) -> TelegramLogin | None:
    return TelegramLogin.objects.filter(token=token, expires_at__gt=timezone.now()).select_related("user").first()


def consume(token: str) -> TelegramLogin | None:
    """Tasdiqlangan tokenni bir marta ishlatish (sessiya ochish uchun). Boshqa holatda None."""
    with transaction.atomic():
        login = TelegramLogin.objects.select_for_update().filter(token=token, status="confirmed", expires_at__gt=timezone.now()).first()
        if not login:
            return None
        login.status = "used"
        login.save(update_fields=["status"])
    return TelegramLogin.objects.select_related("user").get(id=login.id)


def redirect_after(login: TelegramLogin) -> str:
    from .auth import safe_next_path

    user = login.user
    if user.role == "admin":
        default = "/admin"
    elif hasattr(user, "master") and user.master and user.master.status != "rejected":
        default = "/"
    else:
        default = "/smetalar?xush=1" if login.is_new_user else "/smetalar"
    return safe_next_path(login.next_path, default)


# ============================ BOT ============================


def handle_start(chat_id: str, token: str) -> None:
    login = TelegramLogin.objects.filter(token=token, status="pending", expires_at__gt=timezone.now()).first()
    if not login:
        send_telegram_message(chat_id, "⏳ Bu havola eskirgan. Saytga qaytib, «Telegram orqali kirish» tugmasini qayta bosing.")
        return
    TelegramLogin.objects.filter(id=login.id).update(chat_id=chat_id)
    send_telegram_message(
        chat_id,
        "👋 Assalomu alaykum! Bu <b>UySmeta</b> boti.\n\n"
        "Kirish yoki ro'yxatdan o'tish uchun pastdagi <b>«📱 Raqamimni yuborish»</b> tugmasini bosing.\n\n"
        f"<i>Hisobingiz bo'lmasa, avtomatik ochiladi. Davom etib, <a href=\"{settings.SITE_URL}/oferta\">ommaviy oferta</a> "
        "shartlariga rozilik bildirasiz.</i>",
        CONTACT_KEYBOARD,
    )


def pending_for_chat(chat_id: str) -> TelegramLogin | None:
    return (
        TelegramLogin.objects.filter(chat_id=chat_id, status="pending", expires_at__gt=timezone.now())
        .order_by("-id")
        .first()
    )


def handle_contact(chat_id: str, login: TelegramLogin, contact: dict, sender: dict) -> None:
    """O'z kontakti tekshirilgan (chaqiruvchida). Hisob topiladi yoki yaratiladi, token tasdiqlanadi."""
    phone = normalize_phone(contact.get("phone_number"))
    if not phone:
        send_telegram_message(chat_id, "❗ Hozircha faqat O'zbekiston raqamlari (+998) qabul qilinadi.", REMOVE_KEYBOARD)
        return
    user = User.objects.filter(phone=phone).first()
    is_new = False
    if user and user.password_hash == "!disabled":
        send_telegram_message(chat_id, "❗ Bu raqam bilan kirib bo'lmaydi. Administratorga murojaat qiling.", REMOVE_KEYBOARD)
        return
    if not user:
        name = " ".join(filter(None, [contact.get("first_name"), contact.get("last_name")])).strip()
        name = name or " ".join(filter(None, [sender.get("first_name"), sender.get("last_name")])).strip() or "Foydalanuvchi"
        # Parolsiz hisob ("!telegram"): Telegram orqali kiradi; xohlasa «Parolni tiklash» orqali parol qo'yadi
        user = User.objects.create(phone=phone, name=name[:60], password_hash="!telegram")
        grant_signup_bonus(user)
        is_new = True
    TelegramLogin.objects.filter(id=login.id).update(status="confirmed", user=user, is_new_user=is_new)
    TelegramLink.objects.update_or_create(phone=phone, defaults={"chat_id": chat_id, "updated_at": timezone.now()})

    first = user.name.split()[0] if user.name else ""
    text = (
        f"🎉 Xush kelibsiz, <b>{first}</b>! Hisobingiz ochildi va saytga kirdingiz.\n\nRo'yxatdan o'tish bonusi hamyoningizga tushdi."
        if is_new
        else f"✅ Tayyor, <b>{first}</b>! Saytga kirdingiz."
    )
    send_telegram_message(chat_id, text + "\n\nSaytdagi sahifa o'zi yangilanadi. Bo'lmasa — pastdagi tugmani bosing.", REMOVE_KEYBOARD)
    try:
        send_telegram_message(
            chat_id,
            "👇",
            {"reply_markup": {"inline_keyboard": [[{"text": "🌐 Saytga qaytish", "url": f"{settings.SITE_URL}/kirish/telegram/{login.token}"}]]}},
        )
    except Exception as error:  # masalan, lokal (localhost) manzilni Telegram tugma sifatida qabul qilmaydi
        log.warning("[tg_login] saytga qaytish tugmasi yuborilmadi: %s", error)
