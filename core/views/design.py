"""
Jihozlash bo'limi: /ai-loyiha (forma va tarix), /ai-loyiha/<id> (natija), /api/ai-loyiha/<id> (holat).
Sukut bo'yicha — tezkor rejim (rooms.json qoidalari, bir zumda, bepul). "AI bilan" belgilansa — AI tahlili (fonda).
"""

import json
from datetime import timedelta

from django.db.models import Q
from django.http import Http404, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.utils import timezone

from ..auth import check_rate_limit, client_ip, login_redirect
from ..background import run_after
from ..constants import PLANS
from ..data import get_enabled_regions, new_public_id
from ..design import ROOM_TYPE_LABELS, design_ai_enabled, design_ai_provider, run_design
from ..estimate import QUALITY_LABELS, parse_decimal
from ..forms import EMPTY, form_values, state, text
from ..models import CatalogItem, RoomDesign
from ..planner import build_quick_plan, group_choices, room_choices
from ..regions import get_region
from ..render import expire_stale, render_image_enabled, plan_sections
from ..room_geometry import expire_stale as expire_geometry
from ..room_geometry import clean_corners, run_geometry, start_geometry
from ..scene3d import build_scene
from ..styles import style_plan
from ..room_analysis import CONDITION_LABELS
from ..uploads import ImageError, delete_image, save_image
from ..wallet import has_plan

STALE_AFTER = timedelta(minutes=10)  # server qayta ishga tushsa "tayyorlanmoqda" holatida qolib ketmasin


def design_form(request):
    user = request.current_user
    form_state = EMPTY
    enabled = get_enabled_regions()

    if request.method == "POST":
        if not user:
            return login_redirect("/ai-loyiha")
        form_state = _create(request, enabled)
        if isinstance(form_state, HttpResponseRedirect):
            return form_state

    history = list(RoomDesign.objects.filter(user=user).order_by("-created_at")[:10]) if user else []
    return render(
        request,
        "pages/design_form.html",
        {
            "state": form_state,
            "ai_ready": design_ai_enabled(),
            "ai_provider": design_ai_provider(),
            "room_types": room_choices(),
            "groups": group_choices(),
            "checked_groups": request.POST.getlist("groups") if request.method == "POST" else list(group_choices()),
            "budgets": QUALITY_LABELS,
            "regions": [get_region(k) for k in enabled],
            "history": history,
            "catalog_count": CatalogItem.objects.count(),
            "has_3d": has_plan(user, "design3d"),
            "plan_3d": PLANS["design3d"],
            "steps": [
                {"title": "Rasm yuklang", "text": "Xona butunligicha"},
                {"title": "AI tahlil qiladi" if design_ai_enabled() else "Bo'limlarni tanlang", "text": "Xona turi va holati"},
                {"title": "Ro'yxat va narx", "text": "Mebel, material, ish"},
                {"title": "3D ko'rinish", "text": "«3D dizayn» tarifida", "locked": not has_plan(user, "design3d")},
            ],
        },
        status=400 if form_state.get("errors") or form_state.get("message") else 200,
    )


def _create(request, enabled):
    post = request.POST
    values = form_values(post)
    use_ai = post.get("mode") == "ai"
    if use_ai and not design_ai_enabled():
        return state(message="AI hozircha ulanmagan. Tezkor rejimdan foydalaning", values=values)

    errors = {}
    area = parse_decimal(post.get("area"))
    height = parse_decimal(post.get("height") or "2.7")
    if not (area == area) or area < 2 or area > 500:  # NaN ham shu yerda ushlanadi
        errors["area"] = "Xona maydonini m² da kiriting (2–500), masalan 18.5"
    if not (height == height) or height < 2 or height > 6:
        errors["height"] = "Ship balandligi 2–6 m oralig'ida bo'lsin"
    rooms = room_choices()
    room_type = text(post, "roomType")
    if room_type not in rooms and not (use_ai and room_type == "auto"):
        errors["roomType"] = "Xona turini tanlang"
    windows = _small_int(post.get("windows"), default=1, high=10)
    doors = _small_int(post.get("doors"), default=1, high=6)
    groups = [g for g in post.getlist("groups") if g in group_choices()]
    if not use_ai and not groups:
        errors["groups"] = "Kamida bitta bo'limni belgilang"
    budget = text(post, "budget") if text(post, "budget") in QUALITY_LABELS else "standard"
    region = text(post, "region") if text(post, "region") in enabled else enabled[0]
    wishes = text(post, "wishes")[:600]

    photo = None
    if not errors:
        try:
            photo = save_image(request.FILES.get("photo"))
        except ImageError as error:
            errors["photo"] = str(error)
        else:
            if not photo:
                errors["photo"] = "Xonaning rasmini yuklang"
    if errors:
        return state(errors=errors, values=values)

    user = request.current_user
    fields = dict(
        public_id=new_public_id(),
        user=user,
        photo=photo,
        area=round(area, 1),
        height=round(height, 2),
        room_type=room_type,
        budget=budget,
        region=region,
        wishes=wishes,
        windows=windows,
        doors=doors,
        groups=",".join(groups),
    )

    if not use_ai:
        # Tezkor rejim: natija shu zahoti
        plan = build_quick_plan(
            room_type=room_type, area=fields["area"], height=fields["height"], budget=budget, windows=windows, doors=doors, groups=groups,
            seed=fields["public_id"],  # bir turdagi ko'p mahsulotdan har loyihada boshqasi
        )
        design = RoomDesign(**fields, mode="tez", status="done", total=plan["total"], finished_at=timezone.now())
        plan = style_plan(design, plan, use_ai=False)  # tezkor rejim — AI'siz, variantlar kutubxonasidan
        design.plan_json = json.dumps(plan, ensure_ascii=False)
        design.save()
        return HttpResponseRedirect(f"/ai-loyiha/{design.public_id}")

    # AI rejimi — har bir so'rov AI chaqiruvi, soatlik chegara
    allowed = (
        check_rate_limit(f"design:user:{user.id}", 10, 60 * 60) if user else check_rate_limit(f"design:ip:{client_ip(request)}", 3, 60 * 60)
    )
    if not allowed:
        message = "Bir soatda juda ko'p loyiha so'raldi. Keyinroq urinib ko'ring" if user else "Ko'proq loyiha uchun tizimga kiring"
        return state(message=message, values=values)

    design = RoomDesign.objects.create(**fields, mode="ai")
    run_after(run_design, design.id)
    return HttpResponseRedirect(f"/ai-loyiha/{design.public_id}")


def _small_int(value, *, default: int, high: int) -> int:
    try:
        return min(high, max(0, int(value)))
    except (TypeError, ValueError):
        return default


def _load(public_id: str) -> RoomDesign:
    design = RoomDesign.objects.filter(public_id=public_id).first()
    if not design:
        raise Http404
    if design.status == "processing" and timezone.now() - design.created_at > STALE_AFTER:
        design.status, design.error = "failed", "Tayyorlash juda uzoq cho'zildi. Qayta urinib ko'ring"
        design.save(update_fields=["status", "error"])
    return design


# Narxlar turi bo'yicha: nima sotib olinadi va ustaga qancha to'lanadi
COST_KINDS = [
    ("material", "Materiallar (pol, devor, ship)", {"material"}),
    ("jihoz", "Mebel, texnika va jihozlar", {"mebel", "texnika", "santexnika", "yoritish", "dekor"}),
    ("ish", "Usta ishlari", {"ish"}),
]


def cost_breakdown(plan: dict | None) -> list[dict]:
    rows = [i for g in (plan or {}).get("groups", []) for i in g.get("items", [])]
    out = []
    for key, label, categories in COST_KINDS:
        items = [r for r in rows if r.get("category") in categories]
        if items:
            out.append({"key": key, "label": label, "count": len(items), "total": sum(r["total"] for r in items)})
    other = [r for r in rows if not any(r.get("category") in c for _, _, c in COST_KINDS)]
    if other:
        out.append({"key": "boshqa", "label": "Boshqa", "count": len(other), "total": sum(r["total"] for r in other)})
    return out


MAX_VARIANTS = 5


def _variant_family(design: RoomDesign) -> list[RoomDesign]:
    root_id = design.variant_of_id or design.id
    return list(RoomDesign.objects.filter(Q(id=root_id) | Q(variant_of_id=root_id)).order_by("variant", "id"))


def _new_variant(request, design: RoomDesign):
    """Shu xona (o'sha rasm, o'lcham va so'rov) uchun AI qaytadan, boshqacha jihozlaydi."""
    user = request.current_user
    if not user:
        return login_redirect(f"/ai-loyiha/{design.public_id}")
    if design.user_id != user.id and user.role != "admin":
        raise Http404
    family = _variant_family(design)
    if design.status != "done" or len(family) >= MAX_VARIANTS:
        return HttpResponseRedirect(f"/ai-loyiha/{design.public_id}")
    if not check_rate_limit(f"design:user:{user.id}", 10, 60 * 60):
        return HttpResponseRedirect(f"/ai-loyiha/{design.public_id}?band=1")
    root = family[0]
    use_ai = design_ai_enabled()
    rooms = room_choices()
    # AI'siz (tezkor) variant uchun aniq xona turi kerak: "auto" bo'lsa — AI aniqlagan tur
    room_type = root.room_type if root.room_type in rooms else (design.plan or {}).get("roomType", "")
    if not use_ai and room_type not in rooms:
        return HttpResponseRedirect(f"/ai-loyiha/{design.public_id}")
    variant = RoomDesign(
        public_id=new_public_id(),
        user=root.user,
        photo=root.photo,
        area=root.area,
        height=root.height,
        room_type=root.room_type if use_ai else room_type,
        budget=root.budget,
        region=root.region,
        wishes=root.wishes,
        windows=root.windows,
        doors=root.doors,
        groups=root.groups,
        mode="ai" if use_ai else "tez",
        variant_of=root,
        variant=max(d.variant for d in family) + 1,
        # Rasm o'sha — o'lchangan xona geometriyasi qayta hisoblanmaydi
        geometry=design.geometry if design.geometry_status == "done" else "",
        geometry_status="done" if design.geometry_status == "done" else "",
    )
    if use_ai:
        variant.save()
        run_after(run_design, variant.id)
    else:
        # Tezkor variant: shu turdagi boshqa mahsulotlar (seed — yangi variantning public_id)
        groups = [g for g in root.groups.split(",") if g]
        plan = build_quick_plan(
            room_type=room_type, area=root.area, height=root.height, budget=root.budget,
            windows=root.windows, doors=root.doors, groups=groups, seed=variant.public_id,
        )
        plan = style_plan(variant, plan, use_ai=False)  # oldingi variantlardagi parda, eshik ... takrorlanmaydi
        variant.plan_json, variant.total = json.dumps(plan, ensure_ascii=False), plan["total"]
        variant.status, variant.finished_at = "done", timezone.now()
        variant.save()
    return HttpResponseRedirect(f"/ai-loyiha/{variant.public_id}")


def design_detail(request, public_id: str):
    design = _load(public_id)
    if request.method == "POST" and request.POST.get("_action") == "variant":
        return _new_variant(request, design)
    can_3d = has_plan(request.current_user, "design3d")
    family = _variant_family(design)
    is_owner = bool(request.current_user) and (design.user_id == request.current_user.id or request.current_user.role == "admin")
    if design.status == "done":
        expire_stale(design)
        expire_geometry(design)
        # Real ko'rinish — loyihaning asosiy natijasi: rasm o'lchami bepul AI tahlilida aniqlanadi
        if can_3d and start_geometry(design):
            run_after(run_geometry, design.id)
    scene = legend = None
    if design.status == "done" and can_3d and design.geometry_status == "done":
        scene, legend, _ = build_scene(design)
    ai_ready = render_image_enabled() and design.render_status == "done" and design.render_source in ("photo", "prompt") and bool(design.render_photo)
    return render(
        request,
        "pages/design_result.html",
        {
            "design": design,
            "plan": design.plan,
            "sections": plan_sections(design.plan),
            "costs": cost_breakdown(design.plan),
            "scene": scene,
            "geometry": design.room_geometry,
            "can_edit_geometry": _can_edit(request, design),
            "ai_ready": ai_ready,
            "photo_mode": render_image_enabled(),
            "room_type_label": room_choices().get(design.room_type) or ROOM_TYPE_LABELS.get(design.room_type, design.room_type),
            "budget_label": QUALITY_LABELS.get(design.budget, design.budget),
            "condition_labels": CONDITION_LABELS,
            "room_labels": ROOM_TYPE_LABELS,
            "can_pdf": has_plan(request.current_user, "pdf"),
            "can_3d": can_3d,
            "family": family if len(family) > 1 else [],
            "can_variant": is_owner and design.status == "done" and len(family) < MAX_VARIANTS,
            "max_variants": MAX_VARIANTS,
            "rate_limited": bool(request.GET.get("band")),
        },
    )


def _can_edit(request, design: RoomDesign) -> bool:
    user = request.current_user
    return bool(user) and has_plan(user, "design3d") and design.user_id in (None, user.id)


def design_guide(request, public_id: str):
    """Brauzerda chizilgan 3D kompozitsiyani saqlash (POST multipart "image") — AI fotorealistik variant uchun asos."""
    if request.method != "POST":
        return JsonResponse({"error": "POST kerak"}, status=405)
    design = _load(public_id)
    if not _can_edit(request, design):
        return JsonResponse({"error": "Ruxsat yo'q"}, status=403)
    try:
        name = save_image(request.FILES.get("image"))
    except ImageError as error:
        return JsonResponse({"error": str(error)}, status=400)
    if not name:
        return JsonResponse({"error": "Rasm yo'q"}, status=400)
    old, design.render_guide = design.render_guide, name
    design.save(update_fields=["render_guide"])
    delete_image(old)
    return JsonResponse({"ok": True})


def design_corners(request, public_id: str):
    """Foydalanuvchi surgan orqa devor burchaklarini saqlash (POST JSON {"back": [[x, y] x4]})."""
    if request.method != "POST":
        return JsonResponse({"error": "POST kerak"}, status=405)
    design = _load(public_id)
    if not _can_edit(request, design) or not design.room_geometry:
        return JsonResponse({"error": "Ruxsat yo'q"}, status=403)
    try:
        back = clean_corners(json.loads(request.body or b"{}").get("back"))
    except (ValueError, AttributeError):
        back = None
    if not back:
        return JsonResponse({"error": "Burchaklar noto'g'ri"}, status=400)
    geometry = {**design.room_geometry, "back": back, "auto": False}
    design.geometry = json.dumps(geometry)
    design.save(update_fields=["geometry"])
    return JsonResponse({"ok": True})


def design_status(request, public_id: str):
    design = _load(public_id)
    return JsonResponse({"status": design.status, "error": design.error})
