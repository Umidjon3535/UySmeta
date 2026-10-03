"""
Ma'lumotlarga kirish qatlami: bir necha joyda ishlatiladigan so'rovlar.
Ruxsatlarni tekshirish — chaqiruvchi (view) vazifasi.
"""

import json
import secrets
from datetime import timedelta

from django.db import transaction
from django.db.models import Avg, Case, Count, Exists, ExpressionWrapper, FloatField, IntegerField, OuterRef, Q, Sum, Value, When
from django.db.models.functions import Cast, Coalesce, Round
from django.utils import timezone

from .constants import MASTER_PLANS
from .estimate import normalize_prices
from .models import ContactRequest, Estimate, Master, PlanOrder, Setting, TelegramLink, User
from .regions import DEFAULT_ENABLED_REGIONS, REGIONS, is_region_key, region_default_prices

# ============================ SOZLAMALAR ============================


def _get_setting(key: str) -> Setting | None:
    return Setting.objects.filter(key=key).first()


def _set_setting(key: str, value) -> None:
    Setting.objects.update_or_create(key=key, defaults={"value": json.dumps(value, ensure_ascii=False), "updated_at": timezone.now()})


# ============================ NARXLAR ============================


def get_prices(region: str) -> dict:
    """Hudud narxlari. Saqlanmagan bo'lsa — hudud uchun boshlang'ich narxlar."""
    row = _get_setting(f"prices:{region}")
    return normalize_prices(json.loads(row.value)) if row else region_default_prices(region)


def get_prices_updated_at(region: str):
    row = _get_setting(f"prices:{region}")
    return row.updated_at if row else None


def save_prices(region: str, prices: dict) -> None:
    _set_setting(f"prices:{region}", prices)


def reset_prices(region: str) -> None:
    Setting.objects.filter(key=f"prices:{region}").delete()


# ============================ HUDUDLAR ============================


def get_enabled_regions() -> list[str]:
    """Saytda ishlayotgan hududlar (tartib — REGIONS ro'yxati bo'yicha)."""
    row = _get_setting("regions")
    stored = json.loads(row.value) if row else DEFAULT_ENABLED_REGIONS
    chosen = [k for k in stored if is_region_key(k)] if isinstance(stored, list) else []
    ordered = [r.key for r in REGIONS if r.key in chosen]
    return ordered or list(DEFAULT_ENABLED_REGIONS)


def set_enabled_regions(keys: list[str]) -> None:
    valid = [k for k in keys if is_region_key(k)]
    if valid:
        _set_setting("regions", valid)


# ============================ TO'LOV KARTALARI ============================


def get_payment_cards() -> list[dict]:
    row = _get_setting("payment_cards")
    try:
        cards = json.loads(row.value) if row else []
    except ValueError:
        return []
    if not isinstance(cards, list):
        return []
    return [c for c in cards if isinstance(c, dict) and str(c.get("number", "")).isdigit() and len(str(c["number"])) == 16]


def save_payment_cards(cards: list[dict]) -> None:
    _set_setting("payment_cards", cards)


# ============================ USTALAR ============================


def masters_with_rating():
    return Master.objects.annotate(rating=Round(Avg("reviews__rating"), 1), reviews_count=Count("reviews"))


# "Eng yaxshi" — ishonchli reyting (Bayes o'rtachasi): har bir ustaga RATING_PRIOR_N ta RATING_PRIOR baholi "xayoliy"
# sharh qo'shib hisoblanadi. Shunda 1 ta 5★ sharhli yangi usta 40 ta 4.9★ sharhli ustadan oldinga chiqib ketmaydi.
RATING_PRIOR = 4.0
RATING_PRIOR_N = 5


def approved_masters_qs(*, region: str = "", specialty: str = "", district: str = "", q: str = "", sort: str = "rating"):
    """Tasdiqlangan ustalar (filtr + saralash) — sahifalash uchun queryset."""
    qs = masters_with_rating().filter(status="approved")
    if specialty:
        qs = qs.filter(specialty=specialty)
    if region:
        qs = qs.filter(region=region)
    if district:
        qs = qs.filter(district=district)
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(bio__icontains=q) | Q(specialty__icontains=q))
    # Pullik tarifdagi ustalar (muddati o'tmagan) har qanday saralashda oldinda: Top, keyin Pro
    now = timezone.now()
    qs = qs.annotate(
        plan_rank=Case(
            *(When(plan=key, plan_until__gt=now, then=Value(info["level"])) for key, info in MASTER_PLANS.items()),
            default=Value(0),
            output_field=IntegerField(),
        ),
        score=ExpressionWrapper(
            (Cast(Coalesce(Sum("reviews__rating"), 0), FloatField()) + RATING_PRIOR * RATING_PRIOR_N)
            / (Cast(Count("reviews"), FloatField()) + RATING_PRIOR_N),
            output_field=FloatField(),
        ),
    )
    if sort == "jobs":
        return qs.order_by("-plan_rank", "-jobs_done", "-score", "id")
    if sort == "new":
        return qs.order_by("-plan_rank", "-created_at", "-id")
    return qs.order_by("-plan_rank", "-score", "-jobs_done", "id")


def list_approved_masters(*, limit: int = 100, **filters):
    return list(approved_masters_qs(**filters)[:limit])


def get_master(master_id: int) -> Master | None:
    return masters_with_rating().filter(id=master_id).first()


def get_master_by_user(user_id: int) -> Master | None:
    return masters_with_rating().filter(user_id=user_id).first()


def set_master_status(master_id: int, status: str) -> None:
    with transaction.atomic():
        master = Master.objects.select_for_update().filter(id=master_id).first()
        if not master:
            return
        master.status = status
        master.save(update_fields=["status"])
        # Tasdiqlangan usta hisobiga 'master' roli beriladi (admin bo'lsa o'zgarmaydi)
        if master.user_id:
            User.objects.filter(id=master.user_id).exclude(role="admin").update(
                role="master" if status == "approved" else "user"
            )


def has_contacted_master(user_id: int, master_id: int) -> bool:
    """Sharh qoldirish huquqi: shu ustaga so'rov yuborgan foydalanuvchi."""
    return ContactRequest.objects.filter(user_id=user_id, master_id=master_id).exists()


# ============================ SMETALAR ============================


def new_public_id() -> str:
    return secrets.token_urlsafe(9)


def claim_estimate(public_id: str, user_id: int) -> None:
    """Kirmasdan saqlangan smetani kirgandan keyin hisobga biriktirish."""
    Estimate.objects.filter(public_id=public_id, user__isnull=True).update(user_id=user_id)


# ============================ SO'ROVLAR VA BUYURTMALAR ============================


def requests_qs():
    return ContactRequest.objects.select_related("master", "estimate")


def orders_qs():
    return PlanOrder.objects.select_related("user", "estimate")


def count_recent_requests_by_phone(phone: str) -> int:
    return ContactRequest.objects.filter(phone=phone, created_at__gt=timezone.now() - timedelta(hours=1)).count()


# ============================ STATISTIKA ============================


def get_public_stats() -> dict:
    return {
        "estimates": Estimate.objects.count(),
        "masters": Master.objects.filter(status="approved").count(),
    }


def get_admin_stats() -> dict:
    week_ago = timezone.now() - timedelta(days=7)
    real_users = User.objects.exclude(password_hash="!disabled")
    return {
        "users": real_users.count(),
        "usersWeek": real_users.filter(created_at__gt=week_ago).count(),
        "estimates": Estimate.objects.count(),
        "estimatesWeek": Estimate.objects.filter(created_at__gt=week_ago).count(),
        "mastersApproved": Master.objects.filter(status="approved").count(),
        "mastersPending": Master.objects.filter(status="pending").count(),
        "requestsNew": ContactRequest.objects.filter(status="new").count(),
        "ordersNew": PlanOrder.objects.filter(status="new").count(),
        "paidSum": PlanOrder.objects.filter(status__in=["paid", "done"]).aggregate(s=Sum("amount"))["s"] or 0,
    }


def list_users(search: str = "", limit: int = 200):
    q = "".join(ch for ch in search.strip() if ch.isalnum() or ch in " +")
    qs = User.objects.exclude(password_hash="!disabled").annotate(
        estimates_count=Count("estimates", distinct=True),
        telegram=Exists(TelegramLink.objects.filter(phone=OuterRef("phone"))),
    )
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(phone__contains=q))
    return list(qs.order_by("-created_at")[:limit])


def get_region_stats() -> dict:
    """Hududlar bo'yicha: tasdiqlangan ustalar va smetalar soni."""
    stats: dict[str, dict] = {}
    for row in Master.objects.filter(status="approved").values("region").annotate(c=Count("id")):
        stats.setdefault(row["region"], {"masters": 0, "estimates": 0})["masters"] = row["c"]
    for row in Estimate.objects.values("region").annotate(c=Count("id")):
        stats.setdefault(row["region"], {"masters": 0, "estimates": 0})["estimates"] = row["c"]
    return stats
