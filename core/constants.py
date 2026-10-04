"""Umumiy o'zgarmaslar va formatlash yordamchilari."""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

SPECIALTIES = [
    "Kafelchi",
    "Santexnik",
    "Elektrik",
    "Suvoqchi",
    "Bo'yoqchi",
    "Laminat ustasi",
    "Universal usta",
]

PLANS = {
    "pdf": {
        "key": "pdf",
        "title": "PDF smeta",
        "price": 49_000,
        "description": "Ustaga yoki do'konga ko'rsatish uchun",
        "features": ["Batafsil PDF smeta", "Bosqichma-bosqich ish rejasi", "To'liq materiallar ro'yxati"],
    },
    "design3d": {
        "key": "design3d",
        "title": "3D dizayn",
        "price": 199_000,
        "description": "Ta'mirdan oldin natijani ko'ring",
        "features": ["3D vizualizatsiya", "Dizayner maslahati", "PDF smeta ichida"],
    },
}

# Ustalar tariflari — oylik obuna (MASTER_PLAN_DAYS kun), mijoz tariflaridan alohida. photos — portfolio chegarasi,
# level — ustalar ro'yxatidagi o'rni (yuqori daraja oldinda), badge — kartochka va sahifadagi belgi.
MASTER_PLAN_DAYS = 30
MASTER_FREE_PLAN = {
    "key": "",
    "title": "Start",
    "price": 0,
    "description": "Platformaga qo'shilish uchun",
    "features": ["Ommaviy profil va «Tekshirilgan» belgisi", "Mijozlardan so'rovlar — komissiyasiz", "Portfolioda 5 ta rasm"],
    "photos": 5,
    "level": 0,
    "badge": "",
}
MASTER_PLANS = {
    "usta_pro": {
        "key": "usta_pro",
        "title": "Pro usta",
        "price": 99_000,
        "description": "Ko'proq mijoz va ishonch",
        "features": ["Portfolioda 20 ta rasm", "«Pro» belgisi profil va kartochkada", "Ro'yxatda bepul ustalardan oldin"],
        "photos": 20,
        "level": 1,
        "badge": "Pro",
    },
    "usta_top": {
        "key": "usta_top",
        "title": "Top usta",
        "price": 249_000,
        "description": "Hududingizda birinchi bo'lib ko'rining",
        "features": ["Portfolioda 50 ta rasm", "«Top usta» belgisi", "Ro'yxatda eng yuqorida", "Pro tarifidagi hamma narsa"],
        "photos": 50,
        "level": 2,
        "badge": "Top usta",
    },
}


# Do'kon toifalari (Shop.categories kalitlari)
SHOP_CATEGORIES = {
    "material": "Qurilish materiallari",
    "kafel": "Kafel va keramika",
    "pol": "Pol qoplamalari",
    "boyoq": "Bo'yoq va lak",
    "santexnika": "Santexnika",
    "elektr": "Elektr va yoritish",
    "eshik": "Eshik va derazalar",
    "mebel": "Mebel",
    "texnika": "Maishiy texnika",
    "asbob": "Asbob-uskunalar",
}


def plan_info(key: str) -> dict:
    """Mijoz yoki usta tarifi ma'lumoti (buyurtmalar ikkalasidan ham bo'lishi mumkin)."""
    return PLANS.get(key) or MASTER_PLANS.get(key) or MASTER_FREE_PLAN


REQUEST_STATUS_LABELS = {
    "new": "Yangi",
    "contacted": "Bog'lanildi",
    "done": "Bajarildi",
    "cancelled": "Bekor qilindi",
}

ORDER_STATUS_LABELS = {
    "new": "Yangi",
    "paid": "To'langan",
    "done": "Bajarildi",
    "cancelled": "Bekor qilindi",
}

MASTER_STATUS_LABELS = {
    "pending": "Tekshiruvda",
    "approved": "Tasdiqlangan",
    "rejected": "Rad etilgan",
}

ROLE_LABELS = {
    "user": "Mijoz",
    "master": "Usta",
    "admin": "Administrator",
}

TASHKENT = ZoneInfo("Asia/Tashkent")


def format_card(number: str) -> str:
    """8600123456789012 -> "8600 1234 5678 9012"."""
    digits = re.sub(r"\D", "", number or "")
    return " ".join(digits[i : i + 4] for i in range(0, len(digits), 4))


def format_phone(phone: str) -> str:
    """+998901234567 -> "+998 90 123 45 67"."""
    m = re.fullmatch(r"\+998(\d{2})(\d{3})(\d{2})(\d{2})", phone or "")
    return f"+998 {m[1]} {m[2]} {m[3]} {m[4]}" if m else (phone or "")


# Yangi parol uzunligi (aynan shuncha belgi) va ism/familiya cheklovlari — shablonlar ham shulardan oladi
PASSWORD_LENGTH = 8
NAME_MAX = 30
# Harflar (lotin/kirill, o', g' uchun apostroflar), so'zlar orasida bo'sh joy yoki chiziqcha
_NAME_RE = re.compile(r"[^\W\d_]+(?:[ '\-ʻʼ‘’`]+[^\W\d_]*)*")


def valid_person_name(value: str) -> bool:
    return 2 <= len(value) <= NAME_MAX and bool(_NAME_RE.fullmatch(value))


# Qabul qilinadigan operator kodlari (+998 dan keyingi 2 raqam). phone_field orqali brauzerga ham uzatiladi
PHONE_CODES = ("33", "50", "77", "88", "90", "91", "93", "94", "95", "97", "99")
PHONE_CODE_ERROR = "Operator kodi noto'g'ri. Raqam " + ", ".join(PHONE_CODES) + " bilan boshlanishi kerak"


def has_valid_phone_code(phone: str | None) -> bool:
    """+998XXXXXXXXX ko'rinishidagi raqam ruxsat etilgan operator kodi bilan boshlanadimi."""
    return bool(phone) and phone[4:6] in PHONE_CODES


def normalize_phone(raw) -> str | None:
    """Har qanday yozuvdan +998XXXXXXXXX formatini olish; noto'g'ri bo'lsa None."""
    digits = re.sub(r"\D", "", str(raw if raw is not None else ""))
    local = digits[3:] if len(digits) == 12 and digits.startswith("998") else digits
    return f"+998{local}" if re.fullmatch(r"\d{9}", local) else None


def initials(name: str) -> str:
    return "".join(part[0].upper() for part in (name or "").split()[:2])


def format_date(value: datetime) -> str:
    """Sana Toshkent vaqtida: "26.09.2026" (server qaysi mintaqada bo'lishidan qat'i nazar)."""
    if value is None:
        return ""
    if value.tzinfo is not None:
        value = value.astimezone(TASHKENT)
    return value.strftime("%d.%m.%Y")


VALID_PUBLIC_ID = re.compile(r"^[A-Za-z0-9_-]{8,20}$")


def valid_public_id(value) -> str | None:
    value = str(value or "")
    return value if VALID_PUBLIC_ID.match(value) else None
