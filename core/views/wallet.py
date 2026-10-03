"""Hamyon (/hamyon), tarif imkoniyatlari: PDF yuklab olish, 3D va real ko'rinish."""

from django.conf import settings
from django.http import Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render

from ..auth import check_rate_limit, login_redirect, require_user
from ..background import run_after
from ..forms import EMPTY, form_values, state
from ..models import Estimate, RoomDesign, WalletTransaction, WithdrawRequest
from ..pdf import design_pdf, estimate_pdf
from ..planner import load_rooms
from ..render import expire_stale, render_image_enabled, run_render, start_render
from ..room_geometry import expire_stale as expire_geometry
from ..scene3d import build_scene
from ..wallet import has_plan, request_withdraw, withdrawable_amount


@require_user
def wallet_view(request):
    user = request.current_user
    form_state = EMPTY
    if request.method == "POST":
        withdrawal, errors = request_withdraw(user, request.POST.get("amount"), request.POST.get("card"), request.POST.get("holder"))
        if errors:
            form_state = state(errors=errors, message="Ma'lumotlarni tekshiring", values=form_values(request.POST))
        else:
            return HttpResponseRedirect(f"/hamyon?yechish={withdrawal.id}")
        user.refresh_from_db()

    return render(
        request,
        "pages/wallet.html",
        {
            "state": form_state,
            "balance": user.balance,
            "withdrawable": withdrawable_amount(user),
            "min_withdraw": settings.WALLET_MIN_WITHDRAW,
            "bonus_withdrawable": settings.WALLET_BONUS_WITHDRAWABLE,
            "transactions": list(WalletTransaction.objects.filter(user=user).order_by("-created_at", "-id")[:100]),
            "withdrawals": list(WithdrawRequest.objects.filter(user=user).order_by("-created_at")[:20]),
            "new_withdrawal": request.GET.get("yechish"),
        },
    )


def _require_plan(request, plan: str, next_path: str):
    """Tarif yo'q bo'lsa — kirish yoki narxlar sahifasiga yo'naltirish."""
    if not request.current_user:
        return login_redirect(next_path)
    if not has_plan(request.current_user, plan):
        return HttpResponseRedirect(f"/narxlar?kerak={plan}")
    return None


def _pdf_response(content: bytes, filename: str) -> HttpResponse:
    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def estimate_pdf_view(request, public_id: str):
    estimate = Estimate.objects.filter(public_id=public_id).first()
    if not estimate:
        raise Http404
    redirect = _require_plan(request, "pdf", f"/smeta/{public_id}/pdf")
    if redirect:
        return redirect
    return _pdf_response(estimate_pdf(estimate), f"uysmeta-smeta-{public_id}.pdf")


def design_pdf_view(request, public_id: str):
    design = RoomDesign.objects.filter(public_id=public_id, status="done").first()
    if not design:
        raise Http404
    redirect = _require_plan(request, "pdf", f"/ai-loyiha/{public_id}/pdf")
    if redirect:
        return redirect
    # Dizayner maslahatlari — "3D dizayn" tarifida
    content = design_pdf(design, with_tips=has_plan(request.current_user, "design3d"))
    return _pdf_response(content, f"uysmeta-loyiha-{public_id}.pdf")


def design_3d_view(request, public_id: str):
    design = RoomDesign.objects.filter(public_id=public_id, status="done").first()
    if not design:
        raise Http404
    redirect = _require_plan(request, "design3d", f"/ai-loyiha/{public_id}/3d")
    if redirect:
        return redirect

    rooms = load_rooms()
    scene, legend, from_photo = build_scene(design)
    room = rooms["rooms"].get(design.room_type, {})
    return render(
        request,
        "pages/design_3d.html",
        {
            "design": design,
            "room": room,
            "tips": [t for t in room.get("tips", []) + [rooms["budget_tips"].get(design.budget, "")] if t],
            "scene": scene,
            "geometry": design.room_geometry,
            "legend": legend,
            "from_photo": from_photo,
        },
    )


def design_real_view(request, public_id: str):
    """Real ko'rinish loyiha sahifasining o'zida. POST — qayta yaratish (boshqa variant)."""
    design = RoomDesign.objects.filter(public_id=public_id, status="done").first()
    if not design:
        raise Http404
    redirect = _require_plan(request, "design3d", f"/ai-loyiha/{public_id}#real")
    if redirect:
        return redirect
    if request.method == "POST" and render_image_enabled():
        if not check_rate_limit(f"render:user:{request.current_user.id}", 10, 60 * 60):
            return HttpResponseRedirect(f"/ai-loyiha/{public_id}?limit=1#real")
        if start_render(design):
            run_after(run_render, design.id)
    return HttpResponseRedirect(f"/ai-loyiha/{public_id}#real")


def design_real_status(request, public_id: str):
    design = RoomDesign.objects.filter(public_id=public_id).first()
    if not design:
        raise Http404
    expire_stale(design)
    expire_geometry(design)
    return JsonResponse({"status": design.render_status, "error": design.render_error, "geometry": design.geometry_status})
