"""
Telegram Bot API (https://core.telegram.org/bots/api) — faqat kerakli metodlar.
Sozlash: @BotFather'da bot ochib, TELEGRAM_BOT_TOKEN va TELEGRAM_BOT_USERNAME ni kiriting.
"""

import hashlib
import os
from urllib.parse import quote

import requests


def telegram_configured() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_BOT_USERNAME"))


def bot_username() -> str:
    return (os.environ.get("TELEGRAM_BOT_USERNAME") or "").lstrip("@")


def bot_link(start_param: str | None = None) -> str:
    return f"https://t.me/{bot_username()}" + (f"?start={quote(start_param)}" if start_param else "")


def webhook_secret() -> str:
    """Webhook so'rovlarini tekshirish uchun maxfiy kalit (bot tokenidan hosil qilinadi, alohida sozlash shart emas)."""
    if os.environ.get("TELEGRAM_WEBHOOK_SECRET"):
        return os.environ["TELEGRAM_WEBHOOK_SECRET"]
    return hashlib.sha256(f"uysmeta-webhook:{os.environ.get('TELEGRAM_BOT_TOKEN')}".encode()).hexdigest()[:48]


class TelegramError(Exception):
    pass


def tg(method: str, body: dict | None = None):
    # TELEGRAM_API_BASE — faqat testlar uchun (soxta Telegram serveri); odatda bo'sh qoldiriladi
    base = os.environ.get("TELEGRAM_API_BASE") or "https://api.telegram.org"
    try:
        res = requests.post(f"{base}/bot{os.environ.get('TELEGRAM_BOT_TOKEN')}/{method}", json=body or {}, timeout=20)
        data = res.json()
    except (requests.RequestException, ValueError) as error:
        raise TelegramError(f"Telegram {method}: {error}") from error
    if not data.get("ok"):
        raise TelegramError(f"Telegram {method}: {data.get('description') or res.status_code}")
    return data.get("result")


def send_telegram_message(chat_id: str, text: str, extra: dict | None = None):
    return tg("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "HTML", **(extra or {})})


# Foydalanuvchidan o'z raqamini yuborishni so'raydigan tugma
CONTACT_KEYBOARD = {
    "reply_markup": {
        "keyboard": [[{"text": "📱 Raqamimni yuborish", "request_contact": True}]],
        "resize_keyboard": True,
        "one_time_keyboard": True,
    }
}

REMOVE_KEYBOARD = {"reply_markup": {"remove_keyboard": True}}
