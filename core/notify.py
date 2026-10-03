"""
Telegram orqali bildirishnoma. Raqam egasi avval botda kontaktini tasdiqlagan bo'lsa yuboriladi
(ro'yxatdan o'tish yoki parolni tiklashda bu avtomatik bo'ladi). Xato saytning ishiga ta'sir qilmaydi.
"""

import html
import logging

from django.conf import settings

from .models import TelegramLink, User
from .telegram import send_telegram_message, telegram_configured

log = logging.getLogger("uysmeta.notify")


def escape_html(text: str) -> str:
    return html.escape(text or "", quote=False)


def notify_phone(phone: str, text: str) -> bool:
    if not telegram_configured():
        return False
    try:
        link = TelegramLink.objects.filter(phone=phone).first()
        if not link:
            return False
        send_telegram_message(link.chat_id, text)
        return True
    except Exception as error:
        log.warning("[notify] %s", error)
        return False


def notify_admins(text: str) -> None:
    """Barcha administratorlarga."""
    if not telegram_configured():
        return
    for phone in User.objects.filter(role="admin").values_list("phone", flat=True):
        notify_phone(phone, text)


def request_message(client_name: str, client_phone: str, message: str, estimate_id: str | None) -> str:
    site = settings.SITE_URL
    lines = [
        "🔔 <b>Yangi mijoz so'rovi — UySmeta</b>",
        "",
        f"👤 {escape_html(client_name)}",
        f"📞 {client_phone}",
        f"💬 {escape_html(message)}" if message else "",
        f"📄 Smeta: {site}/smeta/{estimate_id}" if estimate_id else "",
        "",
        f"Barcha so'rovlar: {site}/profil",
    ]
    # Ketma-ket bo'sh qatorlarni bittaga qisqartirish
    out = [line for i, line in enumerate(lines) if line != "" or (lines[i - 1] if i else "") != ""]
    return "\n".join(out)


# ---------- Mijozga xabarlar (holat o'zgarganda) ----------


def order_status_message(plan_title: str, status: str, order_id: int | None = None) -> str | None:
    site = settings.SITE_URL
    plan = f"<b>{escape_html(plan_title)}</b>"
    if status == "new":
        if order_id:
            return (
                f"🧾 {plan} buyurtmangiz (#{order_id}) qabul qilindi.\n\n"
                f"💳 To'lash va chek yuklash: {site}/buyurtma/{order_id}\n\nTo'lov tasdiqlangach shu yerga xabar beramiz."
            )
        return f"🧾 {plan} buyurtmangiz qabul qilindi.\n\nHolatini kuzatish: {site}/profil"
    if status == "paid":
        return f"✅ {plan} uchun to'lov qabul qilindi. Rahmat!\n\nTayyorlashni boshladik — tayyor bo'lgach shu yerga xabar beramiz."
    if status == "done":
        return f"🎉 {plan} tayyor!\n\nNatija bo'yicha operatorimiz siz bilan bog'lanadi. Buyurtmalaringiz: {site}/profil"
    if status == "cancelled":
        return f"{plan} buyurtmangiz bekor qilindi.\n\nSavollar bo'lsa, shu botga yoki @{settings.CONTACT_TELEGRAM} ga yozing."
    return None


def request_status_message(master_name: str, master_id: int, status: str) -> str | None:
    site = settings.SITE_URL
    master = f"<b>{escape_html(master_name)}</b>"
    if status == "new":
        return f"📨 So'rovingiz usta {master}ga yuborildi.\n\nUsta tez orada siz bilan bog'lanadi. Holatini shu yerda xabar qilamiz."
    if status == "contacted":
        return f"📞 Usta {master} so'rovingizni ko'rib chiqdi va siz bilan bog'lanmoqda.\n\nQo'ng'irog'ini o'tkazib yubormang!"
    if status == "done":
        return (
            f"✅ {master} bilan ish bajarildi deb belgilandi.\n\n"
            f"⭐ Iltimos, ustaga baho bering — bu boshqa mijozlarga yordam beradi:\n{site}/ustalar/{master_id}#reviews-title"
        )
    if status == "cancelled":
        return f"So'rovingiz ({master}) bekor qilindi. Boshqa usta topish: {site}/ustalar"
    return None
