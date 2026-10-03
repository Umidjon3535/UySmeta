"""Usta kabineti: kelgan so'rovlar (/usta/sorovlar) va portfolio (/usta/portfolio) — alohida sahifalar."""

from django.http import HttpResponseRedirect
from django.shortcuts import render

from ..auth import require_user
from ..constants import REQUEST_STATUS_LABELS
from ..data import get_master_by_user, requests_qs
from ..forms import EMPTY
from ..models import Review, TelegramLink
from ..telegram import bot_link, telegram_configured
from ..wallet import master_plan_info
from .accounts import set_request_status
from .masters import portfolio_action, portfolio_limit


def _own_master(user):
    """Rad etilmagan usta profili; bo'lmasa — None (sahifa usta arizasiga yo'naltiradi)."""
    master = get_master_by_user(user.id)
    return master if master and master.status != "rejected" else None


def master_home(request, master):
    """Ustaning bosh sahifasi (/) — mijoz kabinetidan (kalkulyator, smetalar) mustaqil, faqat usta ishi."""
    user = request.current_user
    own_requests = requests_qs().filter(master=master)
    portfolio_count = master.portfolio.count()
    portfolio_max = portfolio_limit(master)
    approved = master.status == "approved"
    telegram_ok = TelegramLink.objects.filter(phone=master.phone).exists()
    # Profil to'liqligi: har bir band — bajarilganmi va qayerda bajariladi
    checklist = [
        {"done": approved, "title": "Ariza tasdiqlangan", "hint": "Administrator hujjatingizni ko'rib chiqmoqda", "href": "/profil#usta"},
        {"done": bool(master.document), "title": "Portfolio hujjati yuklangan", "hint": "PDF yoki DOCX — profil sozlamalarida", "href": "/profil#usta"},
        {"done": portfolio_count >= 3, "title": "Portfolioda kamida 3 ta rasm", "hint": f"Hozir {portfolio_count} ta", "href": "/usta/portfolio"},
        {"done": bool(master.bio), "title": "O'zingiz haqingizda yozilgan", "hint": "Ommaviy sahifada chiqadi", "href": "/profil#usta"},
        {"done": telegram_ok, "title": "Telegram ulangan", "hint": "Yangi so'rovlar darhol Telegram'ga keladi",
         "href": bot_link() if telegram_configured() else "/profil#usta", "external": telegram_configured()},
    ]
    done = sum(1 for c in checklist if c["done"])
    return render(
        request,
        "pages/master_home.html",
        {
            "master": master,
            "user": user,
            "plan": master_plan_info(master),
            "new_count": own_requests.filter(status="new").count(),
            "total_requests": own_requests.count(),
            "recent_requests": list(own_requests.order_by("-created_at", "-id")[:5]),
            "recent_reviews": list(Review.objects.filter(master=master).select_related("user").order_by("-created_at")[:3]),
            "portfolio_count": portfolio_count,
            "portfolio_max": portfolio_max,
            "portfolio_preview": list(master.portfolio.all()[:4]),
            "checklist": checklist,
            "checklist_done": done,
            "checklist_percent": round(done * 100 / len(checklist)),
            "request_statuses": REQUEST_STATUS_LABELS,
        },
    )


@require_user
def master_requests(request):
    user = request.current_user
    master = _own_master(user)
    if not master:
        return HttpResponseRedirect("/profil#usta" if get_master_by_user(user.id) else "/usta-bolish")
    if request.method == "POST" and request.POST.get("_action") == "request_status":
        set_request_status(request, user)
        return HttpResponseRedirect(request.get_full_path())

    all_requests = requests_qs().filter(master=master)
    counts = {key: 0 for key in REQUEST_STATUS_LABELS}
    for status in all_requests.values_list("status", flat=True):
        counts[status] = counts.get(status, 0) + 1
    current = request.GET.get("holat") if request.GET.get("holat") in REQUEST_STATUS_LABELS else ""
    items = all_requests.filter(status=current) if current else all_requests
    chips = [{"key": "", "label": "Barchasi", "count": sum(counts.values())}]
    chips += [{"key": key, "label": label, "count": counts.get(key, 0)} for key, label in REQUEST_STATUS_LABELS.items()]
    return render(
        request,
        "pages/master_requests.html",
        {
            "master": master,
            "incoming": list(items.order_by("-created_at", "-id")[:300]),
            "chips": chips,
            "current": current,
            "request_statuses": REQUEST_STATUS_LABELS,
        },
    )


@require_user
def master_portfolio(request):
    user = request.current_user
    master = _own_master(user)
    if not master:
        return HttpResponseRedirect("/profil#usta" if get_master_by_user(user.id) else "/usta-bolish")
    portfolio_state = EMPTY
    if request.method == "POST" and request.POST.get("_action") in ("portfolio_add", "portfolio_delete"):
        portfolio_state = portfolio_action(request, master)
        if portfolio_state.get("ok"):
            return HttpResponseRedirect("/usta/portfolio?ok=1")
    return render(
        request,
        "pages/master_portfolio.html",
        {
            "master": master,
            "portfolio": list(master.portfolio.all()),
            "portfolio_max": portfolio_limit(master),
            "master_plan": master_plan_info(master),
            "portfolio_state": portfolio_state,
            "saved": bool(request.GET.get("ok")),
        },
    )
