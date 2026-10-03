"""Statik sahifalar va texnik manzillar: do'konlar, sitemap, robots, manifest, rasmlar, Telegram webhook."""

import json
import logging

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from ..constants import PLANS
from ..data import get_public_stats, list_approved_masters
from ..estimate import format_number
from ..models import Shop
from ..templatetags.ui import asset
from ..otp import handle_telegram_update
from ..telegram import telegram_configured, webhook_secret
from ..uploads import CONTENT_TYPES, UPLOAD_NAME_PATTERN, upload_dir

log = logging.getLogger("uysmeta.pages")


def about(request):
    stats = get_public_stats()
    return render(
        request,
        "pages/about.html",
        {
            "stats": [
                {"value": format_number(stats["estimates"]) if stats["estimates"] >= 100 else "Bepul", "label": "tuzilgan smeta" if stats["estimates"] >= 100 else "oddiy smeta har doim"},
                {"value": format_number(stats["masters"]), "label": "tekshirilgan usta"},
                {"value": "±10%", "label": "smeta aniqligi"},
            ],
            "audiences": [
                {"icon": "house", "title": "Uy egalari", "text": "Ta'mir qancha turishini oldindan biling, smetani saqlang va ustaga ko'rsating.", "href": "/", "cta": "Smeta hisoblash"},
                {"icon": "hard-hat", "title": "Ustalar", "text": "Smetasi tayyor, byudjetini biladigan mijozlardan komissiyasiz buyurtma oling.", "href": "/usta-bolish", "cta": "Usta bo'lish"},
                {"icon": "store", "title": "Do'konlar", "text": "Mahsulot va narxlaringizni ta'mir rejalashtirayotgan xaridorlarga ko'rsating.", "href": "/dokonlar#hamkorlik", "cta": "Hamkorlik"},
            ],
            "steps": [
                {"title": "Hisoblang", "text": "Xona turi va o'lchamini kiriting — material, usta haqi va muddat bozor narxlarida chiqadi."},
                {"title": "Usta tanlang", "text": "Reyting, sharhlar va portfolio bo'yicha tekshirilgan ustani tanlab, so'rov yuboring."},
                {"title": "Materialni oling", "text": "Smetadagi materiallarni yaqin atrofdagi do'konlardan narxini solishtirib xarid qiling."},
            ],
        },
    )


def oferta(request):
    """Ommaviy oferta: tarif narxlari va hamyon shartlari sozlamalardan olinadi (o'zgarsa matn ham yangilanadi)."""
    return render(
        request,
        "pages/oferta.html",
        {
            "plans": list(PLANS.values()),
            "signup_bonus": settings.WALLET_SIGNUP_BONUS,
            "bonus_withdrawable": settings.WALLET_BONUS_WITHDRAWABLE,
            "min_withdraw": settings.WALLET_MIN_WITHDRAW,
        },
    )


def sitemap(request):
    """Ommaviy sahifalar + tasdiqlangan ustalar profillari. So'rov vaqtida bazadan olinadi."""
    site = settings.SITE_URL
    entries = [(f"{site}{path}", "weekly", "1" if path == "" else "0.7") for path in ("", "/ustalar", "/narxlar", "/dokonlar", "/usta-bolish", "/biz-haqimizda", "/oferta")]
    entries += [(f"{site}/ustalar/{m.id}", "weekly", "0.5") for m in list_approved_masters(limit=1000)]
    entries += [(f"{site}/dokonlar/{i}", "weekly", "0.5") for i in Shop.objects.filter(is_active=True).values_list("id", flat=True)]
    body = "".join(
        f"<url><loc>{loc}</loc><changefreq>{freq}</changefreq><priority>{prio}</priority></url>" for loc, freq, prio in entries
    )
    xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>'
    return HttpResponse(xml, content_type="application/xml")


def robots(request):
    # Shaxsiy va xizmat sahifalari indekslanmaydi
    disallow = ["/profil", "/smetalar", "/smeta/", "/buyurtma/", "/kirish", "/royxat", "/parolni-tiklash", "/api/", "/admin"]
    lines = ["User-Agent: *", "Allow: /", *[f"Disallow: {p}" for p in disallow], "", f"Sitemap: {settings.SITE_URL}/sitemap.xml"]
    return HttpResponse("\n".join(lines) + "\n", content_type="text/plain")


def manifest(request):
    """PWA: telefonga ilova sifatida o'rnatish (Android/Chrome — tugma, iPhone — "Bosh ekranga qo'shish")."""
    icon = lambda name, size, purpose="any": {"src": static(f"pwa/{name}"), "sizes": size, "type": "image/png", "purpose": purpose}  # noqa: E731
    return JsonResponse(
        {
            "id": "/",
            "name": "UySmeta — ta'mirlash smetasi",
            "short_name": "UySmeta",
            "description": "Ta'mir qanchaga tushishini 2 daqiqada biling, tekshirilgan usta va yaqin do'konni toping.",
            "lang": "uz",
            "dir": "ltr",
            "start_url": "/?source=pwa",
            "scope": "/",
            "display": "standalone",
            "orientation": "portrait",
            "background_color": "#071110",
            "theme_color": "#0F766E",
            "categories": ["business", "lifestyle", "utilities"],
            "icons": [
                icon("icon-192.png", "192x192"),
                icon("icon-512.png", "512x512"),
                icon("icon-maskable-512.png", "512x512", "maskable"),
            ],
            "shortcuts": [
                {"name": "Smeta hisoblash", "url": "/#kalkulyator", "icons": [icon("icon-192.png", "192x192")]},
                {"name": "Ustalar", "url": "/ustalar", "icons": [icon("icon-192.png", "192x192")]},
                {"name": "Do'konlar", "url": "/dokonlar", "icons": [icon("icon-192.png", "192x192")]},
            ],
        },
        content_type="application/manifest+json",
        json_dumps_params={"ensure_ascii": False},
    )


def service_worker(request):
    """/sw.js — ildizdan beriladi (butun saytni qamrashi uchun). Versiya static fayllar o'zgarganda yangilanadi."""
    response = render(
        request,
        "pwa/sw.js",
        {"precache": [asset("css/app.css"), asset("js/app.js"), static("pwa/icon-192.png"), "/offline"], "version": asset("css/app.css").split("v=")[-1]},
        content_type="application/javascript",
    )
    response["Cache-Control"] = "no-cache"
    response["Service-Worker-Allowed"] = "/"
    return response


def offline(request):
    """Internet yo'q paytida ko'rsatiladigan sahifa (service worker keshida saqlanadi, foydalanuvchiga bog'liq emas)."""
    return render(request, "pwa/offline.html")


def uploaded_file(request, name: str):
    """Yuklangan rasmlarni berish. Nom qat'iy shablonga mos kelishi shart (papkadan chiqib ketishning oldini oladi)."""
    if not UPLOAD_NAME_PATTERN.match(name):
        raise Http404
    path = upload_dir() / name
    if not path.is_file():
        raise Http404
    response = FileResponse(path.open("rb"), content_type=CONTENT_TYPES[name.rsplit(".", 1)[1]])
    response["Cache-Control"] = "public, max-age=31536000, immutable"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@csrf_exempt
@require_POST
def telegram_webhook(request):
    """Telegram webhook. So'rov haqiqatan Telegram'dan kelganini maxfiy sarlavha orqali tekshiramiz."""
    if not telegram_configured():
        return HttpResponse("Not configured", status=404)
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != webhook_secret():
        return HttpResponseForbidden("Forbidden")
    try:
        handle_telegram_update(json.loads(request.body))
    except Exception:
        # Telegram xato javobda qayta-qayta yuboradi — xatoni log qilib, 200 qaytaramiz
        log.exception("[telegram] update xatosi")
    return JsonResponse({"ok": True})


def csrf_failure(request, reason=""):
    return render(request, "403_csrf.html", status=403)


def page_not_found(request, exception=None):
    return render(request, "404.html", status=404)


def server_error(request):
    return render(request, "500.html", status=500)
