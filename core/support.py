"""
Yordam chati: mijoz saytdagi oynadan yozadi → xabar bazada saqlanadi va administratorlarga Telegram'da boradi.
Administrator javobi: admin panel (/admin?tab=yordam) yoki Telegram'da bot xabariga "Reply" qilib yozish.
"""

import re

from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone

from .models import SupportMessage, SupportThread, TelegramLink, User
from .notify import escape_html, notify_admins, notify_phone

MAX_TEXT = 1000
# Bot xabaridagi belgi — admin shu xabarga "Reply" qilsa, javob qaysi suhbatga ekani shundan aniqlanadi
THREAD_TAG = re.compile(r"Yordam chat #(\d+)")


def thread_messages(thread: SupportThread) -> list[dict]:
    return [
        {"id": m.id, "admin": m.from_admin, "text": m.text, "time": timezone.localtime(m.created_at).strftime("%H:%M")}
        for m in thread.messages.all()
    ]


def add_client_message(thread: SupportThread, text: str) -> SupportMessage:
    message = SupportMessage.objects.create(thread=thread, text=text[:MAX_TEXT])
    SupportThread.objects.filter(id=thread.id).update(updated_at=timezone.now(), status="open")
    return message


def admin_alert(thread: SupportThread, text: str, first: bool) -> str:
    who = escape_html(thread.name or "Mehmon")
    lines = [
        f"💬 <b>Yordam chat #{thread.id}</b>" + (" — yangi suhbat" if first else ""),
        f"👤 {who}" + (f" · 📞 {thread.phone}" if thread.phone else ""),
        "",
        escape_html(text[:MAX_TEXT]),
        "",
        f"Javob: shu xabarga <b>Reply</b> qilib yozing yoki {settings.SITE_URL}/admin?tab=yordam&amp;chat={thread.id}",
    ]
    return "\n".join(lines)


def add_admin_reply(thread: SupportThread, text: str) -> SupportMessage:
    message = SupportMessage.objects.create(thread=thread, from_admin=True, text=text[:MAX_TEXT])
    SupportThread.objects.filter(id=thread.id).update(updated_at=timezone.now())
    # Mijozning qo'ng'iroq qilmasa ham ko'rishi uchun — Telegram'i ulangan bo'lsa, u yerga ham
    if thread.phone:
        notify_phone(thread.phone, f"💬 <b>UySmeta menejeri javob berdi:</b>\n\n{escape_html(text[:MAX_TEXT])}\n\nSaytdagi chat oynasida davom ettiring: {settings.SITE_URL}")
    # Admin o'qidi deb hisoblanadi
    SupportMessage.objects.filter(thread=thread, from_admin=False, is_read=False).update(is_read=True)
    return message


def unread_for_admin() -> int:
    return SupportMessage.objects.filter(from_admin=False, is_read=False).values("thread").distinct().count()


def threads_for_admin(status: str = "open"):
    qs = SupportThread.objects.annotate(
        unread=Count("messages", filter=Q(messages__from_admin=False, messages__is_read=False)),
        total=Count("messages"),
    ).filter(total__gt=0)
    if status in ("open", "closed"):
        qs = qs.filter(status=status)
    return qs.order_by("-unread", "-updated_at")


def handle_admin_telegram_reply(chat_id: str, msg: dict) -> bool:
    """Admin bot xabariga Reply qilgan bo'lsa — javobni suhbatga yozadi. Qayta ishlangan bo'lsa True."""
    original = (msg.get("reply_to_message") or {}).get("text") or ""
    found = THREAD_TAG.search(original)
    text = (msg.get("text") or "").strip()
    if not found or not text:
        return False
    link = TelegramLink.objects.filter(chat_id=chat_id).first()
    if not link or not User.objects.filter(phone=link.phone, role="admin").exists():
        return False
    thread = SupportThread.objects.filter(id=int(found.group(1))).first()
    if not thread:
        return False
    add_admin_reply(thread, text)
    from .telegram import send_telegram_message

    send_telegram_message(chat_id, f"✅ Javob yuborildi (Yordam chat #{thread.id}).")
    return True


def notify_new_message(thread_id: int, text: str, first: bool) -> None:
    """Fon vazifasi: administratorlarga Telegram'da."""
    thread = SupportThread.objects.filter(id=thread_id).first()
    if thread:
        notify_admins(admin_alert(thread, text, first))
