from django.conf import settings

from .constants import PLANS
from .models import ContactRequest, Master
from .telegram import telegram_configured

FREE_PLAN = {
    "key": "free",
    "title": "Bepul",
    "price": 0,
    "description": "Tez taxminiy hisob uchun",
    "features": ["Oddiy smeta", "3 ta xona turi va butun kvartira", "Hududingiz bozor narxlari", "Smetani saqlash va chop etish"],
}
ALL_PLANS = [FREE_PLAN, *PLANS.values()]

FAQ_ITEMS = [
    {
        "q": "Smeta qanchalik aniq?",
        "a": "Standart xonalar uchun hisob real narxdan odatda ±10% farq qiladi. Aniqlik xona shakli, devorlarning holati va tanlangan brendlarga bog'liq — yakuniy narxni usta joyida ko'rib tasdiqlaydi.",
    },
    {
        "q": "Narxlar qayerdan olinadi?",
        "a": "Material narxlarini har bir hududning o'z qurilish bozorlari va hamkor do'konlaridan, ish haqini esa platformadagi ustalarning buyurtmalaridan olamiz. Narxlar muntazam yangilanadi.",
    },
    {
        "q": "Ustalar qanday tekshiriladi?",
        "a": "Har bir usta ariza topshiradi, shaxsi va oldingi ishlari tekshiriladi, shundan keyingina ro'yxatda ko'rinadi. Sharhni faqat ustaga so'rov yuborgan mijozlar qoldira oladi.",
    },
    {
        "q": "Xizmat pullimi?",
        "a": "Oddiy smeta, uni saqlash va chop etish butunlay bepul. Batafsil PDF smeta (49 000 so'm) va 3D dizayn (199 000 so'm) — ixtiyoriy pullik xizmatlar. Ustalar bilan bog'lanish bepul.",
    },
]

# match — qaysi bo'limlarda menyu bandi faol (ichki sahifalar ham: /ustalar/5, /dokonlar/3 ...)
NAV_LINKS = [
    {"href": "/ai-loyiha", "label": "Xonani jihozlash", "match": ("/ai-loyiha",)},
    {"href": "/ustalar", "label": "Ustalar", "match": ("/ustalar",)},
    {"href": "/narxlar", "label": "Narxlar", "match": ("/narxlar", "/buyurtma")},
    {"href": "/dokonlar", "label": "Do'konlar", "match": ("/dokonlar",)},
]


def is_active(path: str, prefixes) -> bool:
    """Bo'lim faolmi: "/" — faqat bosh sahifa; boshqalari — o'zi yoki ichki sahifalari (/ustalar → /ustalar/5)."""
    return any(path == p if p == "/" else path == p or path.startswith(p + "/") for p in prefixes)


def with_active(links: list[dict], path: str) -> list[dict]:
    return [{**link, "active": is_active(path, link.get("match") or (link["href"].split("#")[0],))} for link in links]


def master_nav(master: dict, path: str) -> tuple[list, list]:
    """Usta hisobi uchun menyu: mijoz bo'limlari o'rniga usta ishi (so'rovlar, portfolio, ommaviy sahifa) + Do'konlar."""
    approved = master["status"] == "approved"
    new = ContactRequest.objects.filter(master_id=master["id"], status="new").count() if approved else 0
    # Ommaviy sahifa va boshqa sozlamalar — Kabinet (/) ichida
    links = [
        {"href": "/", "label": "Kabinet"},
        {"href": "/usta/sorovlar", "label": "Kelgan so'rovlar", "badge": new} if approved
        else {"href": "/profil#usta", "label": "Ariza holati", "match": ("/usta-bolish",)},
        {"href": "/usta/portfolio", "label": "Portfolio"},
        {"href": "/narxlar", "label": "Tariflar", "match": ("/narxlar", "/buyurtma")},
        {"href": "/dokonlar", "label": "Do'konlar"},
    ]
    bottom = [
        {"href": "/", "label": "Kabinet", "icon": "house", "active": path == "/"},
        {"href": "/usta/sorovlar", "label": "So'rovlar", "icon": "message-square", "active": is_active(path, ("/usta/sorovlar",)), "badge": new},
        {"href": "/usta/portfolio", "label": "Portfolio", "icon": "image-icon", "active": is_active(path, ("/usta/portfolio",))},
        {"href": "/profil", "label": "Profil", "icon": "user-round", "active": is_active(path, ("/profil", "/hamyon", "/usta-bolish"))},
    ]
    return with_active(links, path), bottom


def site(request):
    path = request.path
    user = getattr(request, "current_user", None)
    # Usta (tasdiqlangan yoki tekshiruvdagi) — usta menyusi
    master = Master.objects.filter(user_id=user.id).exclude(status="rejected").values("id", "status").first() if user else None
    if master:
        nav_links, bottom_nav = master_nav(master, path)
    else:
        nav_links = with_active(NAV_LINKS, path)
        bottom_nav = [
            {"href": "/", "label": "Asosiy", "icon": "house", "active": path == "/"},
            {"href": "/smetalar", "label": "Smetalar", "icon": "file-text", "active": is_active(path, ("/smetalar", "/smeta"))},
            {"href": "/ustalar", "label": "Ustalar", "icon": "users", "active": is_active(path, ("/ustalar",))},
            {
                "href": "/profil" if user else "/kirish",
                "label": "Profil",
                "icon": "user-round",
                "active": is_active(path, ("/profil", "/hamyon", "/kirish", "/royxat", "/usta-bolish")),
            },
        ]
    return {
        "SITE_URL": settings.SITE_URL,
        "contact_phone": settings.CONTACT_PHONE,
        "contact_telegram": settings.CONTACT_TELEGRAM,
        "telegram_ready": telegram_configured(),
        "SITE_HOST": settings.SITE_URL.split("://", 1)[-1],
        "current_user": user,
        "nav_links": nav_links,
        "wallet_active": is_active(path, ("/hamyon",)),
        "profile_active": is_active(path, ("/profil",)),
        "bottom_nav": bottom_nav,
        "plans": ALL_PLANS,
        "faq_items": FAQ_ITEMS,
    }
