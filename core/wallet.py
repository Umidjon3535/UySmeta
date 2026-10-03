"""
Ichki hamyon (to'lov tizimisiz, bepul format).
 - Ro'yxatdan o'tganda WALLET_SIGNUP_BONUS (standart 300 000 so'm) bonus beriladi.
 - Tarif balansdan bir zumda sotib olinadi: buyurtma avtomatik "To'langan", tarif imkoniyatlari darhol ochiladi.
 - Pul yechish: summa darhol ushlanadi, admin kartaga o'tkazgach tasdiqlaydi; rad etilsa balansga qaytadi.
Balans faqat shu moduldagi funksiyalar orqali, foydalanuvchi qatori qulflangan tranzaksiya ichida o'zgaradi —
ikki marta bosish yoki bir vaqtdagi so'rovlar pulni ikki marta yechmaydi.
"""

import re
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .constants import MASTER_FREE_PLAN, MASTER_PLAN_DAYS, MASTER_PLANS, PLANS
from .models import Estimate, Master, PlanOrder, User, WalletTransaction, WithdrawRequest

# Tarif darajalari: yuqori tarif pastkisining barcha imkoniyatlarini o'z ichiga oladi
PLAN_LEVEL = {"": 0, "pdf": 1, "design3d": 2}


class WalletError(Exception):
    pass


def _move(user_id: int, amount: int, kind: str, description: str, order=None) -> WalletTransaction:
    """Balansni o'zgartirish (chaqiruvchi transaction.atomic ichida bo'lishi shart)."""
    user = User.objects.select_for_update().get(id=user_id)
    if amount < 0 and user.balance + amount < 0:
        raise WalletError("Balansda mablag' yetarli emas")
    user.balance += amount
    user.save(update_fields=["balance"])
    return WalletTransaction.objects.create(
        user=user, amount=amount, kind=kind, description=description, balance_after=user.balance, order=order
    )


# ============================ BONUS ============================


def grant_signup_bonus(user: User) -> bool:
    """Bir marta beriladi (qayta chaqirilsa hech narsa qilmaydi)."""
    bonus = settings.WALLET_SIGNUP_BONUS
    if bonus <= 0 or user.password_hash == "!disabled":
        return False
    with transaction.atomic():
        User.objects.select_for_update().get(id=user.id)
        if WalletTransaction.objects.filter(user_id=user.id, kind="bonus").exists():
            return False
        _move(user.id, bonus, "bonus", "Ro'yxatdan o'tish bonusi")
    return True


def grant_missing_bonuses() -> int:
    """Hamyon paydo bo'lishidan oldin ro'yxatdan o'tganlarga ham bonus (migrate paytida)."""
    count = 0
    for user in User.objects.exclude(password_hash="!disabled").exclude(transactions__kind="bonus"):
        count += int(grant_signup_bonus(user))
    return count


# ============================ TARIF ============================


def has_plan(user, plan: str) -> bool:
    """Foydalanuvchida shu tarif (yoki undan yuqorisi) bormi. Administrator hamma narsani ko'ra oladi."""
    if not user:
        return False
    return user.role == "admin" or PLAN_LEVEL.get(user.plan, 0) >= PLAN_LEVEL[plan]


def plan_price_for(user: User, plan: str) -> int:
    """Yuqori tarifga o'tishda faqat farq to'lanadi (PDF bor bo'lsa, 3D dizayn 199 000 − 49 000)."""
    price = PLANS[plan]["price"]
    if user.plan and PLAN_LEVEL[user.plan] < PLAN_LEVEL[plan]:
        price -= PLANS[user.plan]["price"]
    return max(0, price)


def buy_plan(user: User, plan: str, *, estimate_public_id: str | None = None, comment: str = "") -> PlanOrder:
    if plan not in PLANS:
        raise WalletError("Tarif topilmadi")
    with transaction.atomic():
        fresh = User.objects.select_for_update().get(id=user.id)
        if PLAN_LEVEL.get(fresh.plan, 0) >= PLAN_LEVEL[plan]:
            raise WalletError(f"Sizda «{PLANS[fresh.plan]['title']}» tarifi allaqachon faol")
        price = plan_price_for(fresh, plan)
        if fresh.balance < price:
            raise WalletError(f"Balansda mablag' yetarli emas: kerak {price:,} so'm, balansda {fresh.balance:,} so'm".replace(",", " "))
        order = PlanOrder.objects.create(
            user=fresh,
            plan=plan,
            amount=price,
            estimate=Estimate.objects.filter(public_id=estimate_public_id, user=fresh).first() if estimate_public_id else None,
            comment=comment[:500],
            status="paid",  # balansdan to'landi — admin tasdiqlashi shart emas
        )
        title = PLANS[plan]["title"]
        _move(fresh.id, -price, "purchase", f"«{title}» tarifi (buyurtma #{order.id})", order=order)
        User.objects.filter(id=fresh.id).update(plan=plan, plan_since=timezone.now())
    user.plan = plan
    return order


# ============================ USTA TARIFI ============================


def master_plan_info(master) -> dict:
    """Ustaning hozir amaldagi tarifi (muddati o'tgan bo'lsa — bepul Start)."""
    return MASTER_PLANS.get(master.active_plan, MASTER_FREE_PLAN)


def buy_master_plan(user: User, plan: str) -> PlanOrder:
    """
    Usta tarifi — MASTER_PLAN_DAYS kunlik obuna. Shu tarif faol bo'lsa muddati uzaytiriladi, yuqorisiga o'tilsa bugundan
    boshlanadi. Faol tarifdan pastrog'ini olish mumkin emas (muddati tugagach olinadi).
    """
    if plan not in MASTER_PLANS:
        raise WalletError("Tarif topilmadi")
    info = MASTER_PLANS[plan]
    with transaction.atomic():
        fresh = User.objects.select_for_update().get(id=user.id)
        master = Master.objects.select_for_update().filter(user_id=fresh.id).exclude(status="rejected").first()
        if not master:
            raise WalletError("Usta tariflari faqat ustalar uchun. Avval usta bo'lib ro'yxatdan o'ting")
        current = master.active_plan
        if current and MASTER_PLANS[current]["level"] > info["level"]:
            raise WalletError(f"Sizda «{MASTER_PLANS[current]['title']}» tarifi faol. Pastroq tarifni muddati tugagach olishingiz mumkin")
        price = info["price"]
        if fresh.balance < price:
            raise WalletError(f"Balansda mablag' yetarli emas: kerak {price:,} so'm, balansda {fresh.balance:,} so'm".replace(",", " "))
        start = master.plan_until if current == plan else timezone.now()
        order = PlanOrder.objects.create(user=fresh, plan=plan, amount=price, status="paid")
        _move(fresh.id, -price, "purchase", f"«{info['title']}» tarifi, {MASTER_PLAN_DAYS} kun (buyurtma #{order.id})", order=order)
        master.plan, master.plan_until = plan, start + timedelta(days=MASTER_PLAN_DAYS)
        master.save(update_fields=["plan", "plan_until"])
    return order


# ============================ PUL YECHISH ============================


def withdrawable_amount(user: User) -> int:
    """Yechib olish mumkin bo'lgan summa. WALLET_BONUS_WITHDRAWABLE=false bo'lsa bonus qismi yechilmaydi."""
    balance = User.objects.get(id=user.id).balance
    if settings.WALLET_BONUS_WITHDRAWABLE:
        return balance
    bonus = WalletTransaction.objects.filter(user_id=user.id, kind="bonus").aggregate(s=Sum("amount"))["s"] or 0
    return max(0, balance - bonus)


def request_withdraw(user: User, amount_raw, card_raw, holder_raw) -> tuple[WithdrawRequest | None, dict]:
    """(so'rov, xatolar). Summa darhol balansdan ushlanadi."""
    errors = {}
    try:
        amount = int(re.sub(r"[\s ]", "", str(amount_raw or "")))
    except ValueError:
        amount = 0
    card = re.sub(r"\D", "", str(card_raw or ""))
    holder = str(holder_raw or "").strip()[:60]
    minimum = settings.WALLET_MIN_WITHDRAW
    available = withdrawable_amount(user)
    if amount < minimum:
        errors["amount"] = f"Eng kam summa — {minimum:,} so'm".replace(",", " ")
    elif amount > available:
        errors["amount"] = f"Yechish mumkin bo'lgan summa: {available:,} so'm".replace(",", " ")
    if len(card) != 16 or not card.startswith(("8600", "5614", "9860", "4", "5")):
        errors["card"] = "Karta raqamini to'liq kiriting (16 ta raqam: Uzcard, Humo, Visa yoki Mastercard)"
    if len(holder) < 3:
        errors["holder"] = "Karta egasining ism-familiyasini kiriting"
    if errors:
        return None, errors
    try:
        with transaction.atomic():
            request = WithdrawRequest.objects.create(user=user, amount=amount, card_number=card, card_holder=holder.upper())
            _move(user.id, -amount, "withdraw", f"Pul yechish so'rovi #{request.id} (karta ···{card[-4:]})")
    except WalletError as error:
        return None, {"amount": str(error)}
    return request, {}


def process_withdraw(request_id: int, approve: bool, note: str = "") -> WithdrawRequest | None:
    """Admin: kartaga o'tkazildi (done) yoki rad etildi (pul balansga qaytadi)."""
    with transaction.atomic():
        request = WithdrawRequest.objects.select_for_update().filter(id=request_id, status="pending").first()
        if not request:
            return None
        request.status = "done" if approve else "rejected"
        request.note = note[:200]
        request.processed_at = timezone.now()
        request.save(update_fields=["status", "note", "processed_at"])
        if not approve:
            _move(request.user_id, request.amount, "refund", f"Pul yechish so'rovi #{request.id} rad etildi — qaytarildi")
    return request


def admin_adjust(user_id: int, amount: int, reason: str) -> WalletTransaction:
    with transaction.atomic():
        return _move(user_id, amount, "admin", reason[:200] or "Administrator tuzatishi")
