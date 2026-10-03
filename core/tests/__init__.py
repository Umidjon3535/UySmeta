"""
Testlar .env dagi haqiqiy Telegram botiga bog'liq bo'lmasin (va unga xabar yubormasin): bot sozlamalari olib tashlanadi.
Telegram'ni sinaydigan testlar (TelegramOtpTests) o'z soxta sozlamalarini mock.patch.dict bilan qo'yadi.
"""

import os

for _key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_USERNAME", "TELEGRAM_WEBHOOK_SECRET"):
    os.environ.pop(_key, None)
