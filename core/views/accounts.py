"""Kirish, ro'yxatdan o'tish (tasdiqlash kodi bilan), parolni tiklash, chiqish va profil."""

import secrets

from django.conf import settings
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from .. import tg_login
from ..auth import (
    check_rate_limit,
    client_ip,
    create_session,
    destroy_session,
    require_user,
    reset_rate_limit,
    safe_next_path,
)
from ..background import run_after
from ..constants import NAME_MAX, PASSWORD_LENGTH, PHONE_CODE_ERROR, REQUEST_STATUS_LABELS, SPECIALTIES, format_phone, has_valid_phone_code, normalize_phone, valid_person_name, valid_public_id
from ..data import claim_estimate, get_enabled_regions, get_master_by_user, requests_qs
from ..forms import EMPTY, form_values, state, text
from ..models import ContactRequest, PlanOrder, Session, User
from ..notify import notify_phone, request_status_message
from ..otp import otp_channels, resolve_channel, send_otp, verify_otp
from ..passwords import hash_password, verify_password
from ..regions import form_regions
from ..telegram import bot_link, telegram_configured
from ..uploads import delete_document
from ..wallet import grant_signup_bonus, master_plan_info
from .masters import portfolio_limit, read_master_document, read_master_form


def _claim_pending(post, user_id: int) -> None:
    """Kirishdan oldin saqlangan smetani yangi hisobga biriktirish."""
    public_id = valid_public_id(post.get("claim"))
    if public_id:
        claim_estimate(public_id, user_id)


def _check_new_password(password: str, confirm: str) -> dict:
    errors = {}
    if len(password) != PASSWORD_LENGTH:
        errors["password"] = f"Parol aynan {PASSWORD_LENGTH} belgidan iborat bo'lsin"
    if password != confirm:
        errors["passwordConfirm"] = "Parollar mos kelmadi"
    return errors


def _redirect_params(request) -> dict:
    source = request.POST if request.method == "POST" else request.GET
    nxt = source.get("next")
    return {
        "next": safe_next_path(nxt) if nxt else "",
        "claim": source.get("claim") or "",
    }


def _is_partial(request) -> bool:
    """Bosh sahifadagi karta / JS formani sahifani yangilamasdan yuboradi — javob faqat forma qismi."""
    return request.headers.get("X-Auth-Partial") == "1"


def _auth_done(request, url: str):
    return JsonResponse({"redirect": url}) if _is_partial(request) else HttpResponseRedirect(url)


def _render_auth(request, page: str, partial: str, context: dict, status: int = 200):
    if _is_partial(request):
        prefix = request.POST.get("_p", "")
        context["p"] = prefix if prefix in ("l-", "r-", "t-") else ""
        return render(request, partial, context, status=status)
    return render(request, page, context, status=status)


def _query(params: dict) -> str:
    from urllib.parse import urlencode

    q = urlencode({k: v for k, v in params.items() if v})
    return f"?{q}" if q else ""


# ============================ KIRISH ============================


def login_view(request):
    params = _redirect_params(request)
    if request.current_user and request.method == "GET":
        return HttpResponseRedirect(params["next"] or "/profil")

    form_state = EMPTY
    if request.method == "POST":
        post = request.POST
        phone = normalize_phone(post.get("phone"))
        password = post.get("password") or ""
        values = form_values(post)
        if not phone or not password:
            errors = {}
            if not phone:
                errors["phone"] = "Telefon raqamni kiriting"
            if not password:
                errors["password"] = "Parolni kiriting"
            form_state = state(errors=errors, values=values)
        else:
            limit_key = f"login:{phone}:{client_ip(request)}"
            if not check_rate_limit(limit_key):
                form_state = state(message="Juda ko'p noto'g'ri urinish. 10 daqiqadan keyin qayta urinib ko'ring", values=values)
            else:
                user = User.objects.filter(phone=phone).first()
                if user and user.password_hash == "!telegram":
                    # Bot orqali ro'yxatdan o'tgan — paroli yo'q
                    form_state = state(message="Siz Telegram orqali ro'yxatdan o'tgansiz: «Telegram orqali kirish» ni bosing yoki «Parolni tiklash» orqali parol qo'ying", values=values)
                elif not user or not verify_password(password, user.password_hash):
                    form_state = state(message="Telefon raqam yoki parol noto'g'ri", values=values)
                else:
                    reset_rate_limit(limit_key)
                    _claim_pending(post, user.id)
                    response = _auth_done(
                        request, safe_next_path(post.get("next"), "/admin" if user.role == "admin" else "/smetalar")
                    )
                    create_session(response, user.id)
                    return response

    return _render_auth(
        request,
        "auth/login.html",
        "auth/login_form.html",
        {"state": form_state, "channels": otp_channels(), **params, "register_query": _query(params)},
        status=400 if form_state.get("errors") or form_state.get("message") else 200,
    )


TG_COOKIE = "tg_login"


def telegram_login_view(request):
    """
    "Telegram orqali kirish": tugma botni ochadi, foydalanuvchi botda raqamini yuboradi — hisob bo'lsa kiradi,
    bo'lmasa bot o'zi ro'yxatdan o'tkazadi (core/tg_login.py). Sahifa holatni so'rab turadi va o'zi kiritadi.
    POST (JS: Accept: application/json) — token yaratadi; token shu brauzerga cookie orqali bog'lanadi.
    """
    params = _redirect_params(request)
    if request.current_user and request.method == "GET":
        return HttpResponseRedirect(params["next"] or "/profil")

    form_state = EMPTY
    login = None
    if request.method == "POST":
        if not telegram_configured():
            form_state = state(message="Telegram bot hozircha ulanmagan. Parol bilan kiring yoki keyinroq urinib ko'ring")
        elif not check_rate_limit(f"tglogin:{client_ip(request)}", 30, 60 * 60):
            form_state = state(message="Juda ko'p urinish. Birozdan keyin qayta urinib ko'ring")
        else:
            login = tg_login.start_login(safe_next_path(request.POST.get("next"), ""))
            form_state = state(ok=True, data={"tgToken": login.token, "tgUrl": tg_login.login_url(login)})
        if "application/json" in request.headers.get("Accept", ""):
            if not login:
                return JsonResponse({"error": form_state["message"]}, status=429 if telegram_configured() else 503)
            response = JsonResponse({"token": login.token, "url": form_state["data"]["tgUrl"]})
            _bind_tg_cookie(response, login.token)
            return response

    response = _render_auth(
        request,
        "auth/telegram_login.html",
        "auth/telegram_login_form.html",
        {"state": form_state, **params, "register_query": _query(params)},
    )
    if login:
        _bind_tg_cookie(response, login.token)
    return response


def _bind_tg_cookie(response, token: str) -> None:
    response.set_cookie(TG_COOKIE, token, max_age=int(tg_login.LOGIN_TTL.total_seconds()), httponly=True, samesite="Lax", secure=settings.SITE_URL.startswith("https://") and not settings.DEBUG)


def _tg_session(request, token: str):
    """Shu brauzerda boshlangan va botda tasdiqlangan kirish — sessiya ochiladigan TelegramLogin, aks holda None."""
    if request.COOKIES.get(TG_COOKIE) != token:
        return None
    return tg_login.consume(token)


def telegram_login_status(request, token: str):
    """Sahifa har 2 soniyada so'raydi: pending → ok (sessiya ochiladi) yoki expired."""
    login = tg_login.active_login(token)
    if not login or request.COOKIES.get(TG_COOKIE) != token:
        return JsonResponse({"status": "expired"})
    if login.status == "pending":
        return JsonResponse({"status": "pending", "opened": bool(login.chat_id)})
    done = _tg_session(request, token)
    if not done:
        return JsonResponse({"status": "expired"})
    response = JsonResponse({"status": "ok", "redirect": tg_login.redirect_after(done), "new": done.is_new_user})
    create_session(response, done.user_id)
    response.delete_cookie(TG_COOKIE)
    return response


def telegram_login_finish(request, token: str):
    """Botdagi "Saytga qaytish" tugmasi: shu brauzerda boshlangan bo'lsa — kiritadi."""
    done = _tg_session(request, token)
    if done:
        response = HttpResponseRedirect(tg_login.redirect_after(done))
        create_session(response, done.user_id)
        response.delete_cookie(TG_COOKIE)
        return response
    if request.current_user:
        return HttpResponseRedirect("/")
    login = tg_login.active_login(token)
    if login and login.status == "pending" and request.COOKIES.get(TG_COOKIE) == token:
        message_state = state(ok=True, data={"tgToken": token, "tgUrl": tg_login.login_url(login)})
    else:
        message_state = state(message="Bu havola eskirgan yoki kirish boshqa brauzerda boshlangan. Shu yerda «Telegram orqali kirish» ni qayta bosing")
    params = _redirect_params(request)
    return render(request, "auth/telegram_login.html", {"state": message_state, **params, "register_query": _query(params)})


@require_POST
def logout_view(request):
    response = HttpResponseRedirect("/")
    destroy_session(request, response)
    return response


# ============================ TASDIQLASH KODI ============================


def _requested_channel(post) -> str:
    value = text(post, "channel")
    return value if value in ("sms", "dev") else "telegram"


def _code_sent_state(phone: str, sent: dict, values: dict) -> dict:
    """Kod yuborilgandan keyingi forma holati (sahifa keyingi bosqichni ko'rsatadi)."""
    if sent["channel"] == "telegram":
        message = (
            "Kod Telegram'ingizga yuborildi. UySmeta botidagi xabarni oching."
            if sent["delivered"]
            else "Endi Telegram botni oching va «Raqamimni yuborish» tugmasini bosing — kod o'sha yerga keladi."
        )
    elif sent["channel"] == "sms":
        message = f"SMS kod {format_phone(phone)} raqamiga yuborildi."
    else:
        message = "Dev rejim: SMS xizmati ulanmagan, kod pastda ko'rsatilgan."
    data = {"codeSent": "1", "channel": sent["channel"]}
    if sent.get("telegram_url"):
        data["telegramUrl"] = sent["telegram_url"]
    if sent.get("dev_code"):
        data["devCode"] = sent["dev_code"]
    return state(ok=True, message=message, data=data, values=values)


def _kept_data(post) -> dict:
    """2-bosqichda xato bo'lsa, yo'riqnoma (bot havolasi, test kodi) yo'qolmasin."""
    data = {"codeSent": "1", "channel": text(post, "channel")}
    telegram_url = text(post, "telegramUrl")
    if telegram_url.startswith("https://t.me/"):
        data["telegramUrl"] = telegram_url
    if text(post, "devCode").isdigit():
        data["devCode"] = text(post, "devCode")
    return data


def _otp_values(post) -> dict:
    # Ikki bosqichli formada parollar ham qayta to'ldiriladi (foydalanuvchi ularni qayta yozmasin)
    return {k: post.get(k, "") for k in ("name", "surname", "phone", "password", "passwordConfirm", "oferta", "code")}


def _step(post) -> str:
    return post.get("step") or ("confirm" if post.get("codeSent") else "send")


def _validate_registration(post):
    first = text(post, "name")
    surname = text(post, "surname")
    phone = normalize_phone(post.get("phone"))
    password = post.get("password") or ""
    errors = {}
    if not valid_person_name(first):
        errors["name"] = f"Ismingizni harflarda kiriting (2–{NAME_MAX} belgi)"
    if not valid_person_name(surname):
        errors["surname"] = f"Familiyangizni harflarda kiriting (2–{NAME_MAX} belgi)"
    # Bazada bitta maydon: "Ism Familiya" (User.first_name birinchi so'zni oladi)
    name = f"{first} {surname}"
    if not phone:
        errors["phone"] = "Telefon raqamni to'liq kiriting, masalan (90)-123-45-67"
    elif not has_valid_phone_code(phone):
        errors["phone"] = PHONE_CODE_ERROR
    errors.update(_check_new_password(password, post.get("passwordConfirm") or ""))
    if not post.get("oferta"):
        errors["oferta"] = "Ro'yxatdan o'tish uchun oferta shartlarini qabul qiling"
    if phone and "phone" not in errors and User.objects.filter(phone=phone).exists():
        errors["phone"] = "Bu raqam allaqachon ro'yxatdan o'tgan. «Kirish» sahifasidan foydalaning"
    return name, phone, password, errors


def register_view(request):
    params = _redirect_params(request)
    if request.current_user and request.method == "GET":
        return HttpResponseRedirect(params["next"] or "/profil")

    form_state = EMPTY
    if request.method == "POST":
        post = request.POST
        values = _otp_values(post)
        name, phone, password, errors = _validate_registration(post)
        if _step(post) == "send":
            # 1-bosqich: ma'lumotlarni tekshirib, tasdiqlash kodini yuborish
            keep = _kept_data(post) if post.get("codeSent") else {}
            if errors:
                form_state = state(errors=errors, values=values, data=keep)
            # Mobil operatorlarda ko'p foydalanuvchi bitta IP ortida bo'ladi — chegara yumshoqroq
            elif not check_rate_limit(f"register:{client_ip(request)}", 30, 60 * 60):
                form_state = state(message="Juda ko'p urinish. Birozdan keyin qayta urinib ko'ring", values=values, data=keep)
            else:
                sent = send_otp(phone, "register", _requested_channel(post))
                form_state = (
                    _code_sent_state(phone, sent, values) if sent["ok"] else state(message=sent["error"], values=values, data=keep)
                )
        else:
            # 2-bosqich: kodni tekshirib, hisob yaratish
            keep = _kept_data(post)
            if errors:
                form_state = state(errors=errors, values=values, data=keep)
            else:
                ok, error = verify_otp(phone, "register", text(post, "code"))
                if not ok:
                    form_state = state(errors={"code": error}, values=values, data=keep)
                else:
                    user = User.objects.create(phone=phone, name=name, password_hash=hash_password(password))
                    grant_signup_bonus(user)
                    _claim_pending(post, user.id)
                    response = _auth_done(request, safe_next_path(post.get("next"), "/smetalar?xush=1"))
                    create_session(response, user.id)
                    return response

    return _render_auth(
        request,
        "auth/register.html",
        "auth/register_form.html",
        {"state": form_state, "channels": otp_channels(), **params, "register_query": _query(params)},
    )


def reset_view(request):
    form_state = EMPTY
    if request.method == "POST":
        post = request.POST
        values = _otp_values(post)
        phone = normalize_phone(post.get("phone"))
        if _step(post) == "send":
            # Raqam ro'yxatda bo'lmasa ham bir xil javob (raqamlarni aniqlashning oldini oladi)
            keep = _kept_data(post) if post.get("codeSent") else {}
            channel = resolve_channel(_requested_channel(post))
            if not phone:
                form_state = state(errors={"phone": "Telefon raqamni to'liq kiriting"}, values=values, data=keep)
            elif not check_rate_limit(f"reset:{client_ip(request)}", 20, 60 * 60):
                form_state = state(message="Juda ko'p urinish. Birozdan keyin qayta urinib ko'ring", values=values, data=keep)
            elif not channel:
                form_state = state(
                    message="Tasdiqlash xizmati hozircha sozlanmagan. Administratorga murojaat qiling", values=values, data=keep
                )
            else:
                user = User.objects.filter(phone=phone).first()
                if not user or user.password_hash == "!disabled":
                    # Haqiqiy javobdan farq qilmasin (dev kanalida kod ko'rsatilmaydi — u faqat test rejimi)
                    fake = {"ok": True, "channel": channel, "delivered": channel != "telegram"}
                    if channel == "telegram":
                        fake["telegram_url"] = bot_link(secrets.token_urlsafe(12))
                    form_state = _code_sent_state(phone, fake, values)
                else:
                    sent = send_otp(phone, "reset", channel)
                    form_state = (
                        _code_sent_state(phone, sent, values)
                        if sent["ok"]
                        else state(message=sent["error"], values=values, data=keep)
                    )
        else:
            # 2-bosqich: kod + yangi parol. Barcha eski sessiyalar yopiladi
            keep = _kept_data(post)
            password = post.get("password") or ""
            errors = {} if phone else {"phone": "Telefon raqamni to'liq kiriting"}
            if phone:
                errors.update(_check_new_password(password, post.get("passwordConfirm") or ""))
            if errors:
                form_state = state(errors=errors, values=values, data=keep)
            else:
                ok, error = verify_otp(phone, "reset", text(post, "code"))
                user = User.objects.filter(phone=phone).first()
                if not ok or not user:
                    form_state = state(errors={"code": error if not ok else "Kod noto'g'ri"}, values=values, data=keep)
                else:
                    User.objects.filter(id=user.id).update(password_hash=hash_password(password))
                    Session.objects.filter(user_id=user.id).delete()
                    response = HttpResponseRedirect("/profil?parol=1")
                    create_session(response, user.id)
                    return response

    return render(request, "auth/reset.html", {"state": form_state, "channels": otp_channels()})


# ============================ PROFIL ============================


@require_user
def profile_view(request):
    user = request.current_user
    states = {}
    response_cookie_user = None

    if request.method == "POST":
        post = request.POST
        action = post.get("_action")
        if action == "profile":
            name = text(post, "name")
            if len(name) < 2 or len(name) > 60:
                states["profile"] = state(errors={"name": "Ismingizni kiriting (2–60 belgi)"})
            else:
                User.objects.filter(id=user.id).update(name=name)
                user.name = name
                states["profile"] = state(ok=True, message="Ma'lumotlar saqlandi")
        elif action == "password":
            current = post.get("currentPassword") or ""
            new = post.get("password") or ""
            errors = _check_new_password(new, post.get("passwordConfirm") or "")
            if not verify_password(current, user.password_hash):
                errors["currentPassword"] = "Joriy parol noto'g'ri"
            if errors:
                states["password"] = state(errors=errors)
            else:
                User.objects.filter(id=user.id).update(password_hash=hash_password(new))
                # Boshqa qurilmalardagi sessiyalarni yopib, joriysini yangilaymiz
                Session.objects.filter(user_id=user.id).delete()
                response_cookie_user = user.id
                states["password"] = state(ok=True, message="Parol yangilandi. Boshqa qurilmalardan chiqarildingiz")
        elif action == "master":
            master = get_master_by_user(user.id)
            if not master:
                states["master"] = state(message="Usta profili topilmadi")
            else:
                errors, data = read_master_form(post)
                document = read_master_document(request, errors, required=False)
                if errors:
                    states["master"] = state(errors=errors, values=form_values(post))
                else:
                    if document:
                        delete_document(master.document)
                        data["document"], data["document_name"] = document
                    for key, value in data.items():
                        setattr(master, key, value)
                    master.save(update_fields=list(data))
                    states["master"] = state(ok=True, message="Profil yangilandi")
        elif action == "request_status":
            set_request_status(request, user)
            return HttpResponseRedirect("/profil")

    master = get_master_by_user(user.id)
    enabled = get_enabled_regions()
    context = {
        "user": user,
        "master": master,
        "master_regions": form_regions(list(dict.fromkeys([*enabled, master.region])) if master else enabled),
        "incoming": list(requests_qs().filter(master=master).order_by("-created_at", "-id")) if master and master.status == "approved" else [],
        "new_requests": requests_qs().filter(master=master, status="new").count() if master and master.status == "approved" else 0,
        "sent": list(requests_qs().filter(user=user).order_by("-created_at", "-id")),
        "orders": list(PlanOrder.objects.filter(user=user).order_by("-created_at", "-id")),
        "request_statuses": REQUEST_STATUS_LABELS,
        "specialties": SPECIALTIES,
        "states": states,
        "ariza": bool(request.GET.get("ariza")),
        "parol": bool(request.GET.get("parol")),
        "master_open": "master" in states,
        "portfolio": list(master.portfolio.all()) if master else [],
        "portfolio_max": portfolio_limit(master) if master else 0,
        "master_plan": master_plan_info(master) if master else None,
    }
    response = render(request, "pages/profile.html", context)
    if response_cookie_user:
        create_session(response, response_cookie_user)
    return response


def set_request_status(request, user) -> None:
    """So'rov holatini o'zgartirish: shu so'rov kelgan usta yoki administrator."""
    try:
        request_id = int(request.POST.get("id", ""))
    except ValueError:
        return
    status = text(request.POST, "status")
    if status not in REQUEST_STATUS_LABELS:
        return
    req = ContactRequest.objects.select_related("master").filter(id=request_id).first()
    if not req:
        return
    own_master = get_master_by_user(user.id)
    if not (user.role == "admin" or (own_master and own_master.id == req.master_id)):
        return
    previous = req.status
    ContactRequest.objects.filter(id=req.id).update(status=status)
    # Mijozga Telegram'da xabar (faqat holat haqiqatan o'zgarganda)
    if previous != status:
        message = request_status_message(req.master.name, req.master_id, status)
        if message:
            run_after(notify_phone, req.phone, message)
