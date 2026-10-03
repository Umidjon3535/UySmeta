"""Javobni kutdirmaydigan fon vazifalari (Telegram xabarlari). Xato saytning ishiga ta'sir qilmaydi."""

import logging
import threading

from django.conf import settings
from django.db import close_old_connections, transaction

log = logging.getLogger("uysmeta.background")


def run_after(fn, *args, **kwargs) -> None:
    """Tranzaksiya yakunlangach alohida oqimda bajaradi (testlarda — darhol, sinxron)."""

    def target():
        try:
            fn(*args, **kwargs)
        except Exception:
            log.exception("fon vazifasi xatosi")
        finally:
            close_old_connections()

    def start():
        if settings.TESTING:
            target()
        else:
            threading.Thread(target=target, daemon=True).start()

    transaction.on_commit(start)
