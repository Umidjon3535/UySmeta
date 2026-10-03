"""
Lokal ishlab chiqish uchun Telegram bot: getUpdates orqali xabarlarni olib, to'g'ridan-to'g'ri qayta ishlaydi (webhook o'rniga).
Ishlatish:  python manage.py bot_dev
Eslatma: production bot webhook'ga ulangan bo'lsa, lokal uchun alohida test bot oching.
"""

import time

from django.core.management.base import BaseCommand, CommandError

from core.otp import handle_telegram_update
from core.telegram import TelegramError, telegram_configured, tg


class Command(BaseCommand):
    help = "Telegram botni lokal rejimda (polling) ishga tushirish"

    def handle(self, *args, **options):
        if not telegram_configured():
            raise CommandError("TELEGRAM_BOT_TOKEN va TELEGRAM_BOT_USERNAME .env da ko'rsatilmagan")
        info = tg("getWebhookInfo")
        if info.get("url"):
            raise CommandError(f"Bu botga webhook ulangan ({info['url']}). Lokal sinov uchun alohida bot oching.")
        me = tg("getMe")
        self.stdout.write(f"@{me.get('username')} tinglanmoqda (to'xtatish: Ctrl+C)")

        offset = 0
        while True:
            try:
                updates = tg("getUpdates", {"offset": offset, "timeout": 30, "allowed_updates": ["message"]})
                for update in updates:
                    offset = update["update_id"] + 1
                    try:
                        handle_telegram_update(update)
                        self.stdout.write(f"update {update['update_id']} -> ok")
                    except Exception as error:  # bitta xabar xatosi pollingni to'xtatmasin
                        self.stderr.write(f"update {update['update_id']} xatosi: {error}")
            except TelegramError as error:
                self.stderr.write(f"xato: {error}")
                time.sleep(3)
            except KeyboardInterrupt:
                return
