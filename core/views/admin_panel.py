"""
Admin panel (/admin). Yashirin: administrator bo'lmagan har kimga oddiy "sahifa topilmadi" ko'rinadi
(kirish sahifasiga ham yo'naltirilmaydi — panel borligi oshkor bo'lmaydi).
"""

import copy
import math
from datetime import timedelta

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse, HttpResponseRedirect
from django.db.models import Count, Sum
from django.shortcuts import render
from django.utils import timezone

from ..ai import ai_enabled, ai_provider_name
from ..background import run_after
from ..constants import MASTER_STATUS_LABELS, ORDER_STATUS_LABELS, plan_info
from ..data import (
    get_admin_stats,
    get_enabled_regions,
    get_payment_cards,
    get_prices,
    get_prices_updated_at,
    get_region_stats,
    list_users,
    masters_with_rating,
    orders_qs,
    requests_qs,
    reset_prices,
    save_payment_cards,
    save_prices,
    set_enabled_regions,
    set_master_status,
)
from ..estimate import DEFAULT_PRICES, PRICE_LABELS, QUALITIES, QUALITY_LABELS
from ..forms import EMPTY, form_values, state, text
from ..catalog import CATEGORY_LABELS, catalog_kinds, name_key
from ..catalog_import import TEMPLATE_CSV, CatalogImportError, import_catalog, process_pending_images
from ..market_prices import collect as collect_market_prices
from ..models import CatalogItem, CatalogRequest, Master, PlanOrder, Shop, ShopProduct, SupportThread, User, WalletTransaction, WithdrawRequest
from ..wallet import process_withdraw
from ..notify import notify_phone, order_status_message
from ..regions import REGIONS, get_region, is_region_key
from ..sms import sms_configured
from ..support import add_admin_reply, threads_for_admin, unread_for_admin
from ..telegram import TelegramError, bot_link, bot_username, telegram_configured, tg, webhook_secret
from ..uploads import DOCUMENT_NAME_PATTERN, DOCUMENT_TYPES, document_dir
from .accounts import set_request_status
from .shops import admin_shops_context, delete_shop, product_action, read_product_form, read_shop_form

# (kalit, nom, ikonka, guruh, qisqa izoh) — izoh menyuda va bosh sahifadagi qo'llanmada ko'rinadi
TABS = [
    ("bosh", "Bosh sahifa", "layout-dashboard", "Asosiy", "Bugungi vazifalar va umumiy ko'rsatkichlar"),
    ("buyurtmalar", "Buyurtmalar", "credit-card", "Kundalik ishlar", "Tarif buyurtmalari: chekni tekshirib, holatini belgilash"),
    ("yordam", "Yordam chat", "message-square", "Kundalik ishlar", "Saytdagi chat oynasidan kelgan savollarga javob berish"),
    ("sorovlar", "Mijoz so'rovlari", "phone-call", "Kundalik ishlar", "Mijozlar ustalarga yuborgan so'rovlar"),
    ("ustalar", "Ustalar", "hard-hat", "Kundalik ishlar", "Usta arizalari: hujjatni ko'rib tasdiqlash yoki rad etish"),
    ("hamyon", "Hamyon va yechish", "wallet", "Kundalik ishlar", "Pul yechish so'rovlari va hamyon tarixi"),
    ("dokonlar", "Do'konlar", "store", "Katalog va narxlar", "Do'konlar va ularning mahsulotlarini qo'shish"),
    ("narxlar", "Narxlar", "tags", "Katalog va narxlar", "Kalkulyatordagi material va ish narxlari"),
    ("katalog", "Katalog (AI)", "package-check", "Katalog va narxlar", "AI loyihalar uchun mahsulotlar va narxlar"),
    ("hududlar", "Hududlar", "map", "Katalog va narxlar", "Saytda ishlaydigan viloyatlarni yoqish"),
    ("foydalanuvchilar", "Foydalanuvchilar", "users", "Sozlamalar", "Ro'yxatdan o'tganlar va ularning rollari"),
    ("tolov", "To'lov kartalari", "banknote", "Sozlamalar", "Mijozlar pul o'tkazadigan kartalar"),
    ("tizim", "Tizim holati", "settings", "Sozlamalar", "Telegram, SMS, AI ulanganmi"),
]
TAB_KEYS = {t[0] for t in TABS}


def admin_view(request):
    user = request.current_user
    if not user or user.role != "admin":
        raise Http404

    params = request.GET
    tab = params.get("tab") if params.get("tab") in TAB_KEYS else "bosh"
    states = {}
    if tab == "katalog" and params.get("shablon"):
        # Hamkor do'konlar uchun namuna CSV (Excel'da ochiladi: UTF-8 BOM bilan)
        response = HttpResponse("﻿" + TEMPLATE_CSV, content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="uysmeta-katalog-namuna.csv"'
        return response

    if request.method == "POST":
        action = request.POST.get("_action")
        redirect_back = HttpResponseRedirect(request.get_full_path())
        if action == "prices":
            states["prices"] = _save_prices(request.POST)
        elif action == "reset_prices":
            region = text(request.POST, "region")
            if is_region_key(region):
                reset_prices(region)
            return redirect_back
        elif action == "toggle_region":
            _toggle_region(text(request.POST, "region"))
            return redirect_back
        elif action == "master_status":
            _set_master_status(request.POST)
            return redirect_back
        elif action == "order_status":
            _set_order_status(request.POST)
            return redirect_back
        elif action == "request_status":
            set_request_status(request, user)
            return redirect_back
        elif action == "payment_cards":
            states["payment_cards"] = _save_payment_cards(request.POST)
        elif action == "connect_telegram":
            states["telegram"] = _connect_telegram()
        elif action in ("catalog_save", "catalog_add"):
            states["catalog"] = _catalog_save(request.POST, create=action == "catalog_add")
            if states["catalog"].get("ok"):
                return redirect_back
        elif action == "catalog_import":
            states["catalog_import"] = _catalog_import(request)
        elif action == "market_refresh":
            # Do'konlardan joriy narxlar — bir necha daqiqa, fonda
            run_after(collect_market_prices)
            states["catalog_import"] = state(ok=True, message="Narxlar fonda yangilanmoqda (1–3 daqiqa). Sahifani keyinroq yangilang.")
        elif action == "catalog_delete":
            CatalogItem.objects.filter(id=_int(request.POST.get("id"))).delete()
            return redirect_back
        elif action in ("withdraw_done", "withdraw_reject"):
            done = process_withdraw(_int(request.POST.get("id")), approve=action == "withdraw_done", note=text(request.POST, "note"))
            if done:
                message = (
                    f"✅ {done.amount:,} so'm kartangizga (···{done.card_number[-4:]}) o'tkazildi.".replace(",", " ")
                    if done.status == "done"
                    else f"Pul yechish so'rovingiz #{done.id} rad etildi, summa balansingizga qaytarildi. {done.note}"
                )
                run_after(notify_phone, done.user.phone, message)
            return redirect_back
        elif action in ("shop_add", "shop_save"):
            shop = Shop.objects.filter(id=_int(request.POST.get("id"))).first() if action == "shop_save" else None
            if action == "shop_add" or shop:
                states["shop"] = read_shop_form(request, shop)
                states["shop_id"] = shop.id if shop else 0
                if states["shop"].get("ok"):
                    return redirect_back
        elif action in ("product_add", "product_delete", "product_stock"):
            shop_id = _int(request.POST.get("shop"))
            back = HttpResponseRedirect(f"/admin?tab=dokonlar&mahsulot={shop_id}#shop-{shop_id}")
            if action != "product_add":
                product_action(request.POST)
                return back
            states["product"] = read_product_form(request)
            if states["product"].get("ok"):
                return back
        elif action in ("support_reply", "support_close", "support_open"):
            thread = SupportThread.objects.filter(id=_int(request.POST.get("chat"))).first()
            if thread:
                if action == "support_reply" and text(request.POST, "text"):
                    add_admin_reply(thread, text(request.POST, "text"))
                elif action != "support_reply":
                    SupportThread.objects.filter(id=thread.id).update(status="closed" if action == "support_close" else "open")
            return HttpResponseRedirect(f"/admin?tab=yordam&chat={thread.id if thread else ''}")
        elif action == "shop_delete":
            delete_shop(_int(request.POST.get("id")))
            return redirect_back
        elif action == "catalog_request_dismiss":
            CatalogRequest.objects.filter(id=_int(request.POST.get("id"))).delete()
            return redirect_back

    stats = get_admin_stats()
    badges = {
        "buyurtmalar": stats["ordersNew"],
        "sorovlar": stats["requestsNew"],
        "ustalar": stats["mastersPending"],
        "katalog": CatalogRequest.objects.count(),
        "hamyon": WithdrawRequest.objects.filter(status="pending").count(),
        "yordam": unread_for_admin(),
    }
    holat = text(params, "holat")
    context = {
        "tab": tab,
        "tabs": [{"key": k, "label": label, "icon": ic, "group": group, "hint": hint, "badge": badges.get(k, 0)} for k, label, ic, group, hint in TABS],
        "stats": stats,
        "states": states,
        "holat": holat,
    }
    context.update(TAB_BUILDERS[tab](request, holat, states))
    return render(request, "admin_panel/admin.html", context)


# ============================ BO'LIMLAR ============================


def _dashboard(request, holat, states):
    orders = list(orders_qs().filter(status="new").order_by("-created_at", "-id")[:50])
    orders.sort(key=lambda o: not o.receipt)  # cheki yuklanganlar birinchi
    stats = get_admin_stats()
    now = timezone.now()
    today = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    paid = PlanOrder.objects.filter(status__in=["paid", "done"])
    withdraw_pending = WithdrawRequest.objects.filter(status="pending")
    catalog_missing = CatalogRequest.objects.count()

    # Bajarilishi kerak: har biri — son, nima qilish kerakligi va qayerga o'tish
    tasks = [
        {"icon": "message-square", "count": unread_for_admin(), "title": "Javobsiz chat xabarlari", "action": "Saytdagi chatdan yozganlarga javob bering", "href": "/admin?tab=yordam"},
        {"icon": "hard-hat", "count": stats["mastersPending"], "title": "Usta arizalari", "action": "Hujjatini ko'rib, tasdiqlang yoki rad eting", "href": "/admin?tab=ustalar&holat=pending"},
        {"icon": "credit-card", "count": stats["ordersNew"], "title": "To'lanmagan buyurtmalar", "action": "Chek yuklangan bo'lsa tekshirib, «To'landi» ni bosing", "href": "/admin?tab=buyurtmalar&holat=new"},
        {"icon": "wallet", "count": withdraw_pending.count(), "title": "Pul yechish so'rovlari", "action": "Kartaga o'tkazib, «O'tkazildi» ni bosing", "href": "/admin?tab=hamyon",
         "money": withdraw_pending.aggregate(s=Sum("amount"))["s"] or 0},
        {"icon": "message-square", "count": stats["requestsNew"], "title": "Javobsiz mijoz so'rovlari", "action": "Usta bog'lanmagan bo'lsa, mijozga qo'ng'iroq qiling", "href": "/admin?tab=sorovlar&holat=new"},
        {"icon": "package-check", "count": catalog_missing, "title": "Katalogda yo'q mahsulotlar", "action": "Mijozlar so'ragan mahsulotlarni katalogga qo'shing", "href": "/admin?tab=katalog"},
    ]
    tasks.sort(key=lambda t: not t["count"])  # ish borlari birinchi
    kpis = [
        {"icon": "wallet", "label": "Tushum, jami", "value": None, "money": stats["paidSum"],
         "sub": f"Bugun {_money(paid.filter(created_at__gte=today).aggregate(s=Sum('amount'))['s'])} · 7 kun {_money(paid.filter(created_at__gte=now - timedelta(days=7)).aggregate(s=Sum('amount'))['s'])}",
         "href": "/admin?tab=buyurtmalar"},
        {"icon": "users", "label": "Foydalanuvchilar", "value": stats["users"], "sub": f"+{stats['usersWeek']} shu hafta", "href": "/admin?tab=foydalanuvchilar"},
        {"icon": "file-text", "label": "Tuzilgan smetalar", "value": stats["estimates"], "sub": f"+{stats['estimatesWeek']} shu hafta"},
        {"icon": "hard-hat", "label": "Tasdiqlangan ustalar", "value": stats["mastersApproved"], "sub": f"{stats['mastersPending']} ta ariza kutmoqda", "href": "/admin?tab=ustalar"},
        {"icon": "store", "label": "Do'konlar", "value": Shop.objects.filter(is_active=True).count(), "sub": f"{ShopProduct.objects.count()} ta mahsulot", "href": "/admin?tab=dokonlar"},
        {"icon": "banknote", "label": "Hamyonlardagi pul", "value": None, "money": User.objects.aggregate(s=Sum("balance"))["s"] or 0, "sub": "Foydalanuvchilar balansi jami", "href": "/admin?tab=hamyon"},
    ]
    new_orders = orders[:5]
    pending_masters = list(masters_with_rating().filter(status="pending").order_by("-created_at")[:5])
    new_requests = list(requests_qs().filter(status="new").order_by("-created_at", "-id")[:5])
    return {
        "kpis": kpis,
        "tasks": tasks,
        "open_tasks": sum(1 for t in tasks if t["count"]),
        "today": now,
        "new_orders": new_orders,
        "pending_masters": pending_masters,
        "new_requests": new_requests,
        "guide": [{"key": k, "label": label, "icon": ic, "hint": hint} for k, label, ic, _, hint in TABS if k != "bosh"],
    }


def _money(value) -> str:
    return f"{value or 0:,}".replace(",", " ") + " so'm"


def _support_tab(request, holat, states):
    current = holat or "open"
    threads = list(threads_for_admin(current)[:200])
    chat = SupportThread.objects.filter(id=_int(request.GET.get("chat"))).first() if request.GET.get("chat") else None
    if not chat and threads:
        chat = threads[0]
    if chat:
        # Admin ochdi — mijoz xabarlari o'qildi
        chat.messages.filter(from_admin=False, is_read=False).update(is_read=True)
    return {
        "support_threads": threads,
        "support_chat": chat,
        "support_messages": list(chat.messages.all()) if chat else [],
        "chips": _chips("/admin?tab=yordam", current, [("open", "Ochiq"), ("closed", "Yopilgan"), ("all", "Barchasi")],
                        {"open": SupportThread.objects.filter(status="open", messages__isnull=False).distinct().count(),
                         "closed": SupportThread.objects.filter(status="closed", messages__isnull=False).distinct().count()},
                        SupportThread.objects.filter(messages__isnull=False).distinct().count()),
    }


def _chips(base: str, current: str, options: list[tuple[str, str]], counts: dict, total: int):
    return [
        {
            "href": f"{base}&holat={key}" if key else base,
            "label": label,
            "count": total if not key else counts.get(key, 0),
            "active": current == key,
        }
        for key, label in options
    ]


def _count_by_status(qs) -> dict:
    counts = {}
    for status in qs.values_list("status", flat=True):
        counts[status] = counts.get(status, 0) + 1
    return counts


def _orders_tab(request, holat, states):
    all_orders = orders_qs().order_by("-created_at", "-id")[:300]
    counts = _count_by_status(orders_qs().all())
    items = [o for o in all_orders if not holat or o.status == holat]
    options = [("", "Barchasi"), ("new", "Yangi"), ("paid", "To'langan"), ("done", "Bajarilgan"), ("cancelled", "Bekor")]
    return {"items": items, "chips": _chips("/admin?tab=buyurtmalar", holat, options, counts, sum(counts.values()))}


def _requests_tab(request, holat, states):
    all_requests = requests_qs().order_by("-created_at", "-id")[:300]
    counts = _count_by_status(requests_qs().all())
    items = [r for r in all_requests if not holat or r.status == holat]
    options = [("", "Barchasi"), ("new", "Yangi"), ("contacted", "Bog'lanildi"), ("done", "Bajarilgan")]
    return {"items": items, "chips": _chips("/admin?tab=sorovlar", holat, options, counts, sum(counts.values()))}


def _masters_tab(request, holat, states):
    all_masters = list(masters_with_rating().order_by("-created_at"))
    counts = {}
    for m in all_masters:
        counts[m.status] = counts.get(m.status, 0) + 1
    current = holat or ("pending" if counts.get("pending") else "")
    options = [("", "Barchasi"), ("pending", "Tekshiruvda"), ("approved", "Tasdiqlangan"), ("rejected", "Rad etilgan")]
    return {
        "items": [m for m in all_masters if not current or m.status == current],
        "chips": _chips("/admin?tab=ustalar", current, options, counts, len(all_masters)),
    }


def _users_tab(request, holat, states):
    q = text(request.GET, "q")
    return {"users": list_users(q), "q": q}


def _payment_tab(request, holat, states):
    cards = get_payment_cards()
    by_type = {c["type"]: c for c in cards}
    form_state = states.get("payment_cards") or EMPTY
    values = form_state.get("values") or {}
    errors = form_state.get("errors") or {}
    fields = []
    for key, label, placeholder in (("uzcard", "Uzcard", "8600 0000 0000 0000"), ("humo", "Humo", "9860 0000 0000 0000")):
        current = by_type.get(key, {})
        fields.append(
            {
                "type": key,
                "label": label,
                "placeholder": placeholder,
                "number": values.get(f"{key}Number", current.get("number", "")),
                "holder": values.get(f"{key}Holder", current.get("holder", "")),
                "number_error": errors.get(f"{key}Number"),
                "holder_error": errors.get(f"{key}Holder"),
            }
        )
    return {"cards": cards, "card_fields": fields}


def _prices_tab(request, holat, states):
    enabled = get_enabled_regions()
    region = text(request.GET, "hudud") or text(request.POST, "region")
    region = region if is_region_key(region) else enabled[0]
    prices = get_prices(region)
    form_state = states.get("prices") or EMPTY
    submitted = form_state.get("values") or {}
    errors = form_state.get("errors") or {}

    def value_of(key, default):
        return submitted.get(key, default) if submitted else default

    quality_rows = [
        {
            "label": QUALITY_LABELS[q],
            "cells": [
                {
                    "key": f"quality.{q}.{kind}",
                    "value": value_of(f"quality.{q}.{kind}", prices["quality"][q][kind]),
                    "error": errors.get(f"quality.{q}.{kind}"),
                    "aria": f"{QUALITY_LABELS[q]} — {'materiallar' if kind == 'material' else 'ish haqi'}",
                }
                for kind in ("material", "labor")
            ],
        }
        for q in QUALITIES
    ]
    groups = [
        {
            "title": meta["title"],
            "fields": [
                {"key": f"{group}.{field}", "label": label, "value": value_of(f"{group}.{field}", prices[group][field]), "error": errors.get(f"{group}.{field}")}
                for field, label in meta["fields"].items()
            ],
        }
        for group, meta in PRICE_LABELS.items()
    ]
    return {
        "region": get_region(region),
        "updated_at": get_prices_updated_at(region),
        "enabled_regions": [get_region(k) for k in enabled],
        "other_regions": [r for r in REGIONS if r.key not in enabled],
        "quality_rows": quality_rows,
        "price_groups": groups,
    }


def _regions_tab(request, holat, states):
    enabled = get_enabled_regions()
    region_stats = get_region_stats()
    return {
        "region_cards": [
            {
                "region": r,
                "on": r.key in enabled,
                "stats": region_stats.get(r.key, {"masters": 0, "estimates": 0}),
                "last": r.key in enabled and len(enabled) == 1,
            }
            for r in REGIONS
        ]
    }


def _system_tab(request, holat, states):
    webhook = None
    if telegram_configured():
        try:
            webhook = tg("getWebhookInfo")
        except TelegramError:
            webhook = None
    expected = f"{settings.SITE_URL}/api/telegram/webhook"
    is_prod = not settings.DEBUG
    return {
        "database_url": bool(settings.DATABASE_URL),
        "is_prod": is_prod,
        "telegram": telegram_configured(),
        "bot_username": bot_username(),
        "bot_link": bot_link(),
        "webhook": webhook or {},
        "webhook_ok": bool(webhook and webhook.get("url") == expected),
        "sms": sms_configured(),
        "ai": ai_enabled(),
        "ai_provider": ai_provider_name(),
        "site_https": settings.SITE_URL.startswith("https://"),
        "demo_data": settings.SEED_DEMO_DATA,
        "upload_dir": str(settings.UPLOAD_DIR),
    }


def _catalog_tab(request, holat, states):
    q = text(request.GET, "q")
    category = text(request.GET, "kategoriya")
    items = CatalogItem.objects.all()
    if category in CATEGORY_LABELS:
        items = items.filter(category=category)
    if holat == "taxminiy":
        items = items.filter(verified=False)
    if q:
        items = items.filter(name__icontains=q)
    return {
        "catalog_items": list(items.order_by("category", "name")[:300]),
        "catalog_requests": list(CatalogRequest.objects.order_by("-times_requested", "-last_requested_at")[:50]),
        "catalog_categories": CATEGORY_LABELS,
        "catalog_q": q,
        "catalog_category": category,
        "catalog_total": CatalogItem.objects.count(),
        "catalog_unverified": CatalogItem.objects.filter(verified=False).count(),
        "catalog_kinds": _kind_coverage(),
        "catalog_images_pending": CatalogItem.objects.exclude(image_source="").count(),
        "catalog_market": CatalogItem.objects.filter(origin="market").count(),
        "catalog_market_updated": CatalogItem.objects.filter(origin="market").order_by("-updated_at").values_list("updated_at", flat=True).first(),
        "catalog_image_errors": list(CatalogItem.objects.exclude(image_error="").order_by("-updated_at")[:20]),
    }


KIND_TARGET = 100  # har turda shuncha xil mahsulot bo'lsa, variantlar takrorlanmaydi


def _kind_coverage() -> list[dict]:
    """Har bir tur bo'yicha nechta mahsulot bor (variantlar xilma-xilligi shunga bog'liq)."""
    counts = dict(CatalogItem.objects.exclude(kind="").values_list("kind").annotate(n=Count("id")))
    rows = [
        {"key": key, "label": info["label"], "category": CATEGORY_LABELS.get(info["category"], ""), "count": counts.get(key, 0)}
        for key, info in catalog_kinds().items()
        if info["category"] != "ish"
    ]
    for row in rows:
        row["percent"] = min(100, round(row["count"] * 100 / KIND_TARGET))
    return sorted(rows, key=lambda r: (r["count"], r["label"]))


def _catalog_import(request) -> dict:
    csv_file = request.FILES.get("csv")
    if not csv_file:
        return state(message="CSV faylni tanlang")
    try:
        result = import_catalog(csv_file, request.FILES.get("zip"))
    except CatalogImportError as error:
        return state(message=str(error))
    if result["images"]:
        run_after(process_pending_images)
    parts = [f"{result['created']} ta yangi", f"{result['updated']} ta yangilandi"]
    if result["images"]:
        parts.append(f"{result['images']} ta rasm fonda qayta ishlanmoqda")
    return state(
        ok=not result["errors"] or bool(result["created"] or result["updated"]),
        message="Import: " + ", ".join(parts) + (f". {len(result['errors'])} ta qatorda xato" if result["errors"] else ""),
        data={"errors": result["errors"][:100]},
    )


def _wallet_tab(request, holat, states):
    # Chiqimlar bazada manfiy — ko'rsatish uchun musbat qilamiz
    totals = {kind: abs(WalletTransaction.objects.filter(kind=kind).aggregate(s=Sum("amount"))["s"] or 0) for kind in ("bonus", "purchase", "withdraw", "refund")}
    current = holat or "pending"
    return {
        "withdrawals": list(WithdrawRequest.objects.select_related("user").filter(**({} if current == "all" else {"status": current})).order_by("-created_at")[:200]),
        "wallet_totals": totals,
        "wallet_balance_sum": User.objects.aggregate(s=Sum("balance"))["s"] or 0,
        "pending_sum": WithdrawRequest.objects.filter(status="pending").aggregate(s=Sum("amount"))["s"] or 0,
        "recent_transactions": list(WalletTransaction.objects.select_related("user").order_by("-created_at", "-id")[:30]),
        "chips": _chips(
            "/admin?tab=hamyon",
            current,
            [("pending", "Kutilmoqda"), ("done", "O'tkazilgan"), ("rejected", "Rad etilgan"), ("all", "Barchasi")],
            _count_by_status(WithdrawRequest.objects.all()),
            WithdrawRequest.objects.count(),
        ),
    }


TAB_BUILDERS = {
    "bosh": _dashboard,
    "buyurtmalar": _orders_tab,
    "sorovlar": _requests_tab,
    "ustalar": _masters_tab,
    "foydalanuvchilar": _users_tab,
    "tolov": _payment_tab,
    "narxlar": _prices_tab,
    "hududlar": _regions_tab,
    "tizim": _system_tab,
    "katalog": _catalog_tab,
    "hamyon": _wallet_tab,
    "dokonlar": lambda request, holat, states: admin_shops_context(request, states),
    "yordam": _support_tab,
}


# ============================ AMALLAR ============================


def _save_prices(post) -> dict:
    """Narxlarni saqlash. Forma maydonlari: "bathroom.tilePerM2", "quality.premium.material" va h.k."""
    region = text(post, "region")
    if not is_region_key(region):
        return state(message="Hudud topilmadi")
    prices = copy.deepcopy(DEFAULT_PRICES)
    errors = {}

    for quality in QUALITIES:
        for kind in ("material", "labor"):
            key = f"quality.{quality}.{kind}"
            value = _parse_number(str(post.get(key, "")).replace(",", "."))
            if value is None or value <= 0 or value > 10:
                errors[key] = "0 dan 10 gacha koeffitsiyent"
            else:
                prices["quality"][quality][kind] = value

    for group, meta in PRICE_LABELS.items():
        for field in meta["fields"]:
            key = f"{group}.{field}"
            value = _parse_number("".join(str(post.get(key, "")).split()))
            if value is None or value < 0 or value > 1_000_000_000:
                errors[key] = "Musbat son kiriting"
            else:
                prices[group][field] = int(math.floor(value + 0.5))

    if errors:
        return state(errors=errors, message="Ba'zi qiymatlar noto'g'ri", values=form_values(post))
    save_prices(region, prices)
    return state(ok=True, message=f"{get_region(region).name} narxlari saqlandi. Kalkulyator yangi narxlar bilan ishlaydi")


def _parse_number(raw: str):
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _toggle_region(region: str) -> None:
    """Hududni saytda yoqish yoki o'chirish. Kamida bitta hudud yoqilgan bo'lishi shart."""
    if not is_region_key(region):
        return
    enabled = get_enabled_regions()
    nxt = [r for r in enabled if r != region] if region in enabled else [*enabled, region]
    if nxt:
        set_enabled_regions(nxt)


def _set_master_status(post) -> None:
    try:
        master_id = int(post.get("id", ""))
    except ValueError:
        return
    status = text(post, "status")
    if status in MASTER_STATUS_LABELS:
        set_master_status(master_id, status)


def _set_order_status(post) -> None:
    try:
        order_id = int(post.get("id", ""))
    except ValueError:
        return
    status = text(post, "status")
    if status not in ORDER_STATUS_LABELS:
        return
    order = PlanOrder.objects.select_related("user").filter(id=order_id).first()
    if not order:
        return
    previous = order.status
    PlanOrder.objects.filter(id=order.id).update(status=status)
    # Mijozga Telegram'da xabar (faqat holat haqiqatan o'zgarganda)
    if previous != status:
        message = order_status_message(plan_info(order.plan)["title"], status)
        if message:
            run_after(notify_phone, order.user.phone, message)


def _save_payment_cards(post) -> dict:
    """Admin: to'lov qabul qilinadigan kartalar."""
    cards = []
    errors = {}
    for kind in ("uzcard", "humo"):
        number = "".join(ch for ch in text(post, f"{kind}Number") if ch.isdigit())
        holder = text(post, f"{kind}Holder")[:60]
        if not number and not holder:
            continue  # bo'sh qoldirilgan — bu karta ishlatilmaydi
        prefix_ok = number.startswith("9860") if kind == "humo" else number.startswith(("8600", "5614"))
        if len(number) != 16 or not prefix_ok:
            errors[f"{kind}Number"] = (
                "Humo karta 9860 bilan boshlanadigan 16 ta raqam" if kind == "humo" else "Uzcard karta 8600 bilan boshlanadigan 16 ta raqam"
            )
        if len(holder) < 3:
            errors[f"{kind}Holder"] = "Karta egasining ism-familiyasini kiriting"
        if f"{kind}Number" not in errors and f"{kind}Holder" not in errors:
            cards.append({"type": kind, "number": number, "holder": holder.upper()})
    if errors:
        return state(errors=errors, message="Karta ma'lumotlarini tekshiring", values=form_values(post))
    save_payment_cards(cards)
    return state(
        ok=True,
        message="Saqlandi. Mijozlar buyurtmadan keyin shu kartalarga to'lay oladi."
        if cards
        else "Kartalar o'chirildi — mijozlarga \"operator qo'ng'iroq qiladi\" deb ko'rsatiladi.",
    )


def _connect_telegram() -> dict:
    """Telegram botni saytga ulash (webhook o'rnatish). "Tizim holati"dagi "Ulash" tugmasi."""
    if not telegram_configured():
        return state(message="Avval TELEGRAM_BOT_TOKEN va TELEGRAM_BOT_USERNAME ni sozlang")
    if not settings.SITE_URL.startswith("https://"):
        return state(message="Webhook faqat https manzil bilan ishlaydi. Lokal kompyuterda `python manage.py bot_dev` dan foydalaning")
    try:
        tg(
            "setWebhook",
            {
                "url": f"{settings.SITE_URL}/api/telegram/webhook",
                "secret_token": webhook_secret(),
                "allowed_updates": ["message"],
                "drop_pending_updates": True,
            },
        )
        tg("setMyCommands", {"commands": [{"command": "start", "description": "Botni ishga tushirish"}]})
        return state(ok=True, message="Telegram bot saytga ulandi")
    except TelegramError as error:
        return state(message=f"Ulab bo'lmadi: {error}")


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _catalog_save(post, create: bool) -> dict:
    """Katalog mahsulotini qo'shish yoki narxini yangilash. So'ralgan (bazada yo'q) narsadan ham qo'shiladi."""
    name = text(post, "name")[:120]
    unit = text(post, "unit")[:20] or "dona"
    category = text(post, "category")
    quality = text(post, "quality") if text(post, "quality") in QUALITIES else "standard"
    price = _parse_number("".join(text(post, "price").split()))
    low = _parse_number("".join(text(post, "price_min").split())) if text(post, "price_min") else None
    high = _parse_number("".join(text(post, "price_max").split())) if text(post, "price_max") else None
    errors = {}
    if create and len(name) < 2:
        errors["name"] = "Nomini kiriting"
    if create and category not in CATEGORY_LABELS:
        errors["category"] = "Toifani tanlang"
    if price is None or price <= 0 or price > 10_000_000_000:
        errors["price"] = "Narxni so'mda kiriting"
    if errors:
        return state(errors=errors, message="Ma'lumotlarni tekshiring", values=form_values(post))

    fields = {
        "price": int(price),
        "price_min": int(low) if low else None,
        "price_max": int(high) if high else None,
        "verified": True,  # admin kiritgan yoki tekshirgan narx
        "source_name": text(post, "source_name")[:80] or "Administrator",
        "source_url": text(post, "source_url") if text(post, "source_url").startswith(("https://", "http://")) else "",
        "updated_at": timezone.now(),
    }
    if create:
        key = name_key(name, unit)
        if CatalogItem.objects.filter(name_key=key).exists():
            return state(errors={"name": "Bu nom va birlik bilan mahsulot allaqachon bor"}, values=form_values(post))
        CatalogItem.objects.create(name=name, name_key=key, category=category, unit=unit, quality=quality, origin="admin", **fields)
        CatalogRequest.objects.filter(id=_int(post.get("request_id"))).delete()
        CatalogRequest.objects.filter(name_key=key).delete()
    else:
        CatalogItem.objects.filter(id=_int(post.get("id"))).update(quality=quality, origin="admin", **fields)
    return state(ok=True, message="Katalog yangilandi")


def master_document(request, name: str):
    """Usta arizasidagi portfolio hujjati — faqat administrator. PDF brauzerda ochiladi, DOCX yuklab olinadi."""
    user = request.current_user
    if not user or user.role != "admin" or not DOCUMENT_NAME_PATTERN.match(name):
        raise Http404
    path = document_dir() / name
    master = Master.objects.filter(document=name).first()
    if not path.is_file() or not master:
        raise Http404
    kind = name.rsplit(".", 1)[1]
    response = FileResponse(path.open("rb"), content_type=DOCUMENT_TYPES[kind], as_attachment=kind == "docx", filename=master.document_name or name)
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response
