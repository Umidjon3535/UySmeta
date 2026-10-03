"""Bosh sahifa (kalkulyator), smetani saqlash, smeta sahifasi va "Mening smetalarim"."""

import json
from urllib.parse import quote

from django.http import Http404, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST

from ..ai import ai_enabled, analyze_room_photo
from ..auth import check_rate_limit, require_user
from ..data import claim_estimate, get_enabled_regions, get_master_by_user, get_prices, get_public_stats, list_approved_masters, new_public_id
from ..estimate import (
    QUALITIES,
    QUALITY_LABELS,
    ROOM_LABELS,
    ROOM_TYPES,
    calculate_estimate,
    estimate_to_text,
    format_number,
    validate_input,
)
from ..forms import EMPTY, state, text
from ..models import Estimate, RoomDesign
from ..otp import otp_channels
from ..regions import get_region, regions_label
from ..room_analysis import sanitize_analysis
from ..uploads import ImageError, delete_image, read_image, save_image
from ..wallet import has_plan
from .master_cabinet import master_home

DEFAULT_DIMENSIONS = {"length": "2.5", "width": "2.0", "height": "2.7", "area": "65"}

# Xona turiga mos usta mutaxassisliklari
RELATED_SPECIALTIES = {
    "bathroom": ["Kafelchi", "Santexnik"],
    "kitchen": ["Kafelchi", "Elektrik"],
    "living": ["Suvoqchi", "Bo'yoqchi", "Laminat ustasi"],
    "apartment": ["Universal usta", "Suvoqchi"],
}

ROOM_ICONS = {"bathroom": "bath", "kitchen": "cooking-pot", "living": "sofa", "apartment": "building2"}


# ============================ KALKULYATOR ============================


def _calc_raw(source) -> dict:
    return {
        "roomType": source.get("roomType"),
        "quality": source.get("quality"),
        **{k: source.get(k, "") for k in DEFAULT_DIMENSIONS},
    }


def _pick_region(requested: str, enabled: list[str]) -> str:
    """Hudud — faqat saytda yoqilganlaridan biri."""
    return requested if requested in enabled else enabled[0]


def calculate_view_data(raw: dict, region: str, has_photo: bool) -> dict:
    """Kalkulyator natijasi: to'g'ri bo'lsa hisob, aks holda xatolar."""
    ok, payload = validate_input(raw)
    is_sample = (
        raw.get("roomType") == "bathroom"
        and raw.get("quality") == "standard"
        and all(raw.get(k) == DEFAULT_DIMENSIONS[k] for k in ("length", "width", "height"))
        and not has_photo
    )
    if not ok:
        return {"ok": False, "errors": payload}
    result = calculate_estimate(payload, get_prices(region))
    return {"ok": True, "errors": {}, "result": result, "is_sample": is_sample}


def _result_label(is_sample: bool) -> str:
    return "Namuna hisob — yuqorida o'z o'lchamlaringizni kiriting" if is_sample else "Sizning smetangiz"


def _estimate_view_html(result: dict, is_sample: bool) -> str:
    return render_to_string(
        "includes/estimate_view.html", {"result": result, "sample": is_sample, "label": _result_label(is_sample)}
    )


def home(request):
    if request.method == "POST":
        if not request.current_user:
            return HttpResponseRedirect("/royxat")
        return _save_estimate(request)
    # Usta uchun bosh sahifa — o'z kabineti (so'rovlar, portfolio, reyting), mijoz kalkulyatori emas
    user = request.current_user
    master = get_master_by_user(user.id) if user else None
    if master and master.status != "rejected":
        return master_home(request, master)
    return _render_home(request, EMPTY)


def _render_home(request, form_state: dict, status: int = 200):
    enabled = get_enabled_regions()
    values = form_state.get("values") or {}
    calc = {
        "region": _pick_region(values.get("region", ""), enabled),
        "roomType": values.get("roomType") if values.get("roomType") in ROOM_TYPES else "bathroom",
        "quality": values.get("quality") if values.get("quality") in QUALITIES else "standard",
        **{k: values.get(k, v) for k, v in DEFAULT_DIMENSIONS.items()},
        "title": values.get("title", ""),
    }
    computed = calculate_view_data(calc, calc["region"], has_photo=False)
    if not computed["ok"]:
        # Saqlashda xato bo'lgan qiymatlar — natija o'rniga namuna ko'rsatiladi
        computed = calculate_view_data({**calc, **DEFAULT_DIMENSIONS, "roomType": "bathroom"}, calc["region"], False)
    result = computed["result"]

    stats = get_public_stats()
    place = regions_label(enabled)
    hero_stats = [
        (format_number(stats["estimates"]), "tuzilgan smeta") if stats["estimates"] >= 100 else ("100%", "bepul smeta"),
        (format_number(stats["masters"]), "tekshirilgan usta") if stats["masters"] >= 50 else ("2 daqiqa", "hisoblash vaqti"),
        ("±10%", "aniqlik"),
    ]
    user = request.current_user
    context = {
        "state": form_state,
        "calc": calc,
        "regions": [{"key": k, "name": get_region(k).name, "short": get_region(k).short} for k in enabled],
        "room_types": [{"key": k, "label": ROOM_LABELS[k], "icon": ROOM_ICONS[k]} for k in ROOM_TYPES],
        "qualities": [{"key": k, "label": QUALITY_LABELS[k]} for k in QUALITIES],
        "result": result,
        "is_sample": computed["is_sample"],
        "result_label": _result_label(computed["is_sample"]),
        "result_text": estimate_to_text(result),
        "ai_enabled": ai_enabled(),
        "channels": otp_channels(),
        "place": place,
        "hero_stats": hero_stats,
        "masters": list_approved_masters(sort="rating", limit=4),
        "steps": [
            {"icon": "ruler", "title": "O'lchang", "text": "Xona o'lchami va rasmini kiriting"},
            {"icon": "file-text", "title": "Smeta oling", "text": "Material, ish haqi va muddat bir zumda"},
            {"icon": "users", "title": "Usta tanlang", "text": "Reyting va sharhlar bilan tekshirilgan ustalar"},
        ],
    }
    if user:
        # Kabinet: tezkor amallar va oxirgi ishlar
        context["quick_actions"] = [
            {"href": "#kalkulyator", "icon": "calculator", "title": "Smeta hisoblash", "text": "Material, ish haqi va muddat", "cta": "Hisoblash"},
            {"href": "/ai-loyiha", "icon": "sofa", "title": "Xonani jihozlash", "text": "Rasm bo'yicha mebel va jihozlar", "cta": "Loyiha"},
            {"href": "/ustalar", "icon": "users", "title": "Usta topish", "text": "Tekshirilgan ustalar va sharhlar", "cta": "Ko'rish"},
            {"href": "/smetalar", "icon": "file-text", "title": "Smetalarim", "text": "Saqlangan smetalar va PDF", "cta": "Ochish"},
        ]
        context["recent_estimates"] = list(Estimate.objects.filter(user=user).order_by("-created_at", "-id")[:3])
        context["recent_designs"] = list(RoomDesign.objects.filter(user=user).order_by("-created_at")[:3])
    return render(request, "pages/home.html", context, status=status)


def _save_estimate(request):
    """
    Smetani saqlash. Natija mijozdan qabul qilinmaydi — server bazadagi joriy narxlar bilan qayta hisoblaydi.
    Faqat kirgan foydalanuvchi uchun (mehmonlar bosh sahifada kirish/ro'yxat kartasini ko'radi).
    """
    post = request.POST
    values = {k: post.get(k, "") for k in ("region", "roomType", "quality", "length", "width", "height", "area", "title")}
    ok, payload = validate_input(_calc_raw(post))
    if not ok:
        return _render_home(request, state(errors=payload, message="Kiritilgan qiymatlarni tekshiring", values=values), 400)

    region = _pick_region(text(post, "region"), get_enabled_regions())
    try:
        photo = save_image(request.FILES.get("photo"))
    except ImageError as error:
        return _render_home(request, state(errors={"photo": str(error)}, values=values), 400)

    user = request.current_user
    title = text(post, "title")[:80] or None
    result = calculate_estimate(payload, get_prices(region))

    # AI tahlili brauzerdan keladi — sxema bo'yicha tekshirib, faqat rasm bilan birga saqlaymiz
    analysis = None
    if photo:
        try:
            analysis = sanitize_analysis(json.loads(text(post, "analysis") or "null"))
        except ValueError:
            analysis = None

    estimate = Estimate.objects.create(
        public_id=new_public_id(),
        user=user,
        title=title,
        room_type=payload["roomType"],
        quality=payload["quality"],
        input_json=json.dumps(payload),
        result_json=json.dumps(result, ensure_ascii=False),
        total=result["total"],
        photo=photo,
        ai_json=json.dumps(analysis, ensure_ascii=False) if analysis else None,
        region=region,
    )
    return HttpResponseRedirect(f"/smeta/{estimate.public_id}?saqlandi=1")


@require_POST
def api_calculate(request):
    """Kalkulyatorning jonli natijasi: forma o'zgarganda brauzer shu yerga so'rov yuboradi."""
    if not request.current_user:
        return JsonResponse({"ok": False, "error": "Tizimga kiring"}, status=401)
    region = _pick_region(text(request.POST, "region"), get_enabled_regions())
    computed = calculate_view_data(_calc_raw(request.POST), region, has_photo=request.POST.get("hasPhoto") == "1")
    if not computed["ok"]:
        return JsonResponse({"ok": False, "errors": computed["errors"]})
    if request.POST.get("explicit") == "1":
        computed["is_sample"] = False  # «Hisoblash» bosilgan — standart o'lchamlar ham foydalanuvchining tanlovi
    return JsonResponse(
        {
            "ok": True,
            "html": _estimate_view_html(computed["result"], computed["is_sample"]),
            "text": estimate_to_text(computed["result"]),
        }
    )


@require_POST
def api_analyze(request):
    """Xona rasmini AI bilan tahlil qilish. Xarajatni nazorat qilish uchun soatlik chegara bor."""
    user = request.current_user
    if not user:
        return JsonResponse({"ok": False, "error": "Tizimga kiring"}, status=401)
    try:
        image = read_image(request.FILES.get("photo"))
    except ImageError as error:
        return JsonResponse({"ok": False, "error": str(error)})
    if image is None:
        return JsonResponse({"ok": False, "error": "Avval rasm yuklang"})

    if not check_rate_limit(f"ai:user:{user.id}", 20, 60 * 60):
        return JsonResponse({"ok": False, "error": "Bir soatda juda ko'p tahlil so'raldi. Keyinroq urinib ko'ring"})

    data, kind = image
    res = analyze_room_photo(data, {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}[kind])
    if not res["ok"]:
        return JsonResponse(res)
    analysis = res["analysis"]
    html = render_to_string("includes/analysis_card.html", {"analysis": analysis})
    return JsonResponse({"ok": True, "analysis": analysis, "html": html})


# ============================ SMETA SAHIFASI ============================


def estimate_detail(request, public_id):
    estimate = Estimate.objects.filter(public_id=public_id).first()
    if not estimate:
        raise Http404
    user = request.current_user
    is_owner = bool(user and estimate.user_id == user.id)
    path = f"/smeta/{public_id}"
    rename_state = EMPTY

    if request.method == "POST":
        action = request.POST.get("_action")
        if action == "claim":
            if not user:
                return HttpResponseRedirect(f"/royxat?claim={quote(public_id)}&next={quote(path, safe='')}")
            claim_estimate(public_id, user.id)
            return HttpResponseRedirect(path)
        if not user:
            return HttpResponseRedirect(f"/royxat?next={quote(path, safe='')}")
        if action == "delete" and is_owner:
            photo = estimate.photo
            estimate.delete()
            delete_image(photo)
            return HttpResponseRedirect("/smetalar")
        if action == "rename" and is_owner:
            title = text(request.POST, "title")[:80]
            if not title:
                rename_state = state(errors={"title": "Nom kiriting"})
            else:
                estimate.title = title
                estimate.save(update_fields=["title"])
                rename_state = state(ok=True, message="Nom saqlandi")

    result = estimate.result
    masters = []
    for specialty in RELATED_SPECIALTIES.get(result["roomType"], []):
        masters += list_approved_masters(specialty=specialty, sort="rating", region=estimate.region, limit=2)

    title = estimate.title or f"{ROOM_LABELS.get(result['roomType'], '')} smetasi"
    return render(
        request,
        "pages/estimate.html",
        {
            "estimate": estimate,
            "result": result,
            "is_owner": is_owner,
            "is_unclaimed": estimate.user_id is None,
            "path": path,
            "saqlandi": bool(request.GET.get("saqlandi")),
            "masters": masters[:4],
            "rename_state": rename_state,
            "share_text": estimate_to_text(result, f"{request.scheme}://{request.get_host()}{path}"),
            "page_title": title,
            "can_pdf": has_plan(user, "pdf"),
        },
    )


@require_user
def estimates_list(request):
    user = request.current_user
    estimates = list(Estimate.objects.filter(user=user).order_by("-created_at", "-id"))
    return render(request, "pages/estimates.html", {"estimates": estimates, "xush": bool(request.GET.get("xush"))})
