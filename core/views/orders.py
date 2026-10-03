"""Tariflar sahifasi (buyurtma berish) va buyurtma/to'lov sahifasi (kartaga o'tkazma + chek)."""

from django.conf import settings
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.utils import timezone

from ..auth import login_redirect, require_user
from ..background import run_after
from ..constants import MASTER_FREE_PLAN, MASTER_PLAN_DAYS, MASTER_PLANS, PLANS, plan_info, valid_public_id
from ..data import get_payment_cards
from ..estimate import ROOM_LABELS, format_money
from ..forms import EMPTY, state, text
from ..models import Estimate, Master, PlanOrder
from ..notify import escape_html, notify_admins, notify_phone
from ..uploads import ImageError, delete_image, photo_url, save_image
from ..wallet import PLAN_LEVEL, WalletError, buy_master_plan, buy_plan, master_plan_info, plan_price_for


def pricing(request):
    """Tariflar: balansdan bir zumda sotib olinadi, buyurtma avtomatik "To'langan", imkoniyatlar darhol ochiladi."""
    user = request.current_user
    buy_state = EMPTY
    if request.method == "POST":
        if not user:
            return login_redirect("/narxlar")
        plan = text(request.POST, "plan")
        try:
            if plan in MASTER_PLANS:
                order = buy_master_plan(user, plan)
            else:
                order = buy_plan(
                    user,
                    plan,
                    estimate_public_id=valid_public_id(text(request.POST, "estimate")),
                    comment=text(request.POST, "comment"),
                )
        except WalletError as error:
            buy_state = state(message=str(error), values={"plan": plan})
        else:
            title = plan_info(plan)["title"]
            run_after(notify_phone, user.phone, f"✅ <b>{escape_html(title)}</b> tarifi faollashtirildi (buyurtma #{order.id}). Rahmat!")
            run_after(
                notify_admins,
                f"💳 <b>Tarif sotildi #{order.id}: {title}</b>\n\n👤 {escape_html(user.name)} · 📞 {user.phone}\n"
                f"Balansdan to'landi: {format_money(order.amount).replace(chr(0xA0), ' ')}",
            )
            return HttpResponseRedirect(f"/buyurtma/{order.id}?yangi=1")

    # Usta (tasdiqlangan yoki tekshiruvdagi) — ustalar tariflari; ?mijoz=1 — mijoz tariflari ham ko'rinadi
    master = Master.objects.filter(user_id=user.id).exclude(status="rejected").first() if user else None
    if master and not request.GET.get("mijoz"):
        current = master.active_plan
        return render(
            request,
            "pages/pricing_master.html",
            {
                "master": master,
                "buy_state": buy_state,
                "master_plans": [MASTER_FREE_PLAN, *MASTER_PLANS.values()],
                "current": master_plan_info(master),
                "current_level": master_plan_info(master)["level"],
                "plan_until": master.plan_until if current else None,
                "days": MASTER_PLAN_DAYS,
            },
        )

    estimates = []
    plan_prices = {}
    if user:
        user.refresh_from_db()
        for e in Estimate.objects.filter(user=user).order_by("-created_at", "-id")[:20]:
            label = e.title or ROOM_LABELS.get(e.room_type, e.room_type)
            estimates.append({"public_id": e.public_id, "label": f"{label} — {format_money(e.total)}"})
        plan_prices = {key: plan_price_for(user, key) for key in PLANS}
    return render(
        request,
        "pages/pricing.html",
        {
            "estimates": estimates,
            "buy_state": buy_state,
            "plan_prices": plan_prices,
            "active_plan": user.plan if user else "",
            "plan_levels": PLAN_LEVEL,
            "needed": text(request.GET, "kerak"),
        },
    )


CARD_STYLE = {
    "uzcard": {"label": "UZCARD", "cls": "from-[#1d6fd8] to-[#0f4c9c]"},
    "humo": {"label": "HUMO", "cls": "from-[#0f766e] to-[#115e59]"},
}


@require_user
def order_detail(request, order_id: int):
    user = request.current_user
    order = PlanOrder.objects.select_related("user").filter(id=order_id).first()
    # Faqat buyurtma egasi yoki admin ko'radi
    if not order or (order.user_id != user.id and user.role != "admin"):
        raise Http404

    receipt_state = EMPTY
    if request.method == "POST":
        receipt_state = _submit_receipt(request, order)
        order.refresh_from_db()

    cards = [{**c, **CARD_STYLE.get(c["type"], CARD_STYLE["uzcard"])} for c in get_payment_cards()]
    return render(
        request,
        "pages/order.html",
        {
            "order": order,
            "plan": plan_info(order.plan),
            "cards": cards,
            "yangi": bool(request.GET.get("yangi")),
            "receipt_state": receipt_state,
        },
    )


def _submit_receipt(request, order: PlanOrder) -> dict:
    """Mijoz kartaga o'tkazmadan keyin chek (skrinshot) yuklaydi."""
    if order.user_id != request.current_user.id:
        return state(message="Buyurtma topilmadi")
    if order.status != "new":
        return state(message="Bu buyurtma allaqachon ko'rib chiqilgan")
    try:
        name = save_image(request.FILES.get("receipt"))
    except ImageError as error:
        return state(errors={"receipt": str(error)})
    if not name:
        return state(errors={"receipt": "To'lov cheki (skrinshot) rasmini tanlang"})

    previous = order.receipt
    updated = PlanOrder.objects.filter(id=order.id, user_id=order.user_id, status="new").update(
        receipt=name, receipt_at=timezone.now()
    )
    if not updated:
        delete_image(name)
        return state(message="Chekni saqlab bo'lmadi. Qayta urinib ko'ring")
    delete_image(previous)

    link = photo_url(name)
    receipt_link = link if link.startswith("https://") else f"{settings.SITE_URL}{link}"
    run_after(
        notify_admins,
        "\n".join(
            [
                f"💳 <b>To'lov cheki yuklandi — buyurtma #{order.id}</b>",
                "",
                f"{escape_html(plan_info(order.plan)['title'])} · {format_money(order.amount).replace(chr(0xA0), ' ')}",
                f"👤 {escape_html(order.user.name)} · 📞 {order.user.phone}",
                f"🧾 Chek: {receipt_link}",
                "",
                f"Kartangizga pul tushganini tekshirib, tasdiqlang: {settings.SITE_URL}/admin?tab=buyurtmalar",
            ]
        ),
    )
    return state(ok=True, message="Chek yuborildi! To'lovni tekshirib, tez orada tasdiqlaymiz — Telegram'da xabar olasiz.")
