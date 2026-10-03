"""Yordam chati API: GET — suhbat va xabarlar, POST — yangi xabar (mehmon birinchi xabarda ism va telefon yozadi)."""

import json
import secrets

from django.http import JsonResponse

from ..auth import check_rate_limit, client_ip
from ..background import run_after
from ..constants import has_valid_phone_code, normalize_phone
from ..models import SupportThread
from ..support import MAX_TEXT, add_client_message, notify_new_message, thread_messages

COOKIE = "yordam_chat"
COOKIE_AGE = 60 * 60 * 24 * 180


def _thread(request) -> SupportThread | None:
    user = request.current_user
    key = request.COOKIES.get(COOKIE)
    thread = SupportThread.objects.filter(key=key).first() if key else None
    if not thread and user:
        thread = SupportThread.objects.filter(user=user).order_by("-updated_at").first()
    return thread


def support_api(request):
    thread = _thread(request)
    user = request.current_user

    if request.method == "POST":
        try:
            data = json.loads(request.body or b"{}")
        except ValueError:
            data = {}
        text = str(data.get("text") or "").strip()[:MAX_TEXT]
        errors = {}
        if len(text) < 2:
            errors["text"] = "Xabaringizni yozing"
        if not thread and not user:
            name = str(data.get("name") or "").strip()[:60]
            phone = normalize_phone(data.get("phone"))
            if len(name) < 2:
                errors["name"] = "Ismingizni yozing"
            if not phone or not has_valid_phone_code(phone):
                errors["phone"] = "Telefon raqamni to'liq kiriting"
        if errors:
            return JsonResponse({"errors": errors}, status=400)
        if not check_rate_limit(f"yordam:{client_ip(request)}", 30, 60 * 60):
            return JsonResponse({"errors": {"text": "Juda ko'p xabar. Birozdan keyin yozing yoki qo'ng'iroq qiling"}}, status=429)

        first = thread is None
        if first:
            thread = SupportThread.objects.create(
                key=secrets.token_urlsafe(18),
                user=user,
                name=user.name if user else name,
                phone=user.phone if user else phone,
                page=str(data.get("page") or "")[:200],
            )
        elif user and not thread.user_id:
            SupportThread.objects.filter(id=thread.id).update(user=user)
        add_client_message(thread, text)
        run_after(notify_new_message, thread.id, text, first)
        response = JsonResponse({"ok": True, "messages": thread_messages(thread)})
        response.set_cookie(COOKIE, thread.key, max_age=COOKIE_AGE, httponly=True, samesite="Lax")
        return response

    if not thread:
        return JsonResponse({"messages": [], "need_contact": not user, "unread": 0})
    unread = thread.messages.filter(from_admin=True, is_read=False)
    count = unread.count()
    if request.GET.get("read"):  # oyna ochiq — javoblar o'qildi
        unread.update(is_read=True)
    return JsonResponse({"messages": thread_messages(thread), "need_contact": False, "unread": count})
