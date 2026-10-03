"""
Narxlar katalogi. Yagona manba — core/data/catalog.json (narxlar, manbalar, rasmlar).
 - `migrate` (yoki `python manage.py seed`) JSON'ni bazaga yozadi: yangi mahsulotlar qo'shiladi,
   JSON'dan kelgan (origin="seed") narxlar yangilanadi. Admin o'zgartirgan narxlar (origin="admin") saqlanib qoladi.
 - source=null — manbasi aniq topilmagan, bozor o'rtachasi bo'yicha baholangan narx (verified=False, "taxminiy").
 - Foydalanuvchi so'ragan, lekin bazada yo'q narsalar CatalogRequest'ga yoziladi; admin narxini kiritgach katalogga qo'shiladi.
"""

import json
import re
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.db.models import F
from django.utils import timezone

from .models import CatalogItem, CatalogRequest

DATA_DIR = Path(__file__).resolve().parent / "data"
IMAGE_DIR = Path(settings.BASE_DIR) / "static" / "catalog"

CATEGORY_LABELS = dict(CatalogItem.CATEGORY_CHOICES)
CATEGORIES = list(CATEGORY_LABELS)


@lru_cache(maxsize=1)
def load_catalog_json() -> dict:
    return json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_image_credits() -> dict:
    path = DATA_DIR / "image_credits.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def name_key(name: str, unit: str) -> str:
    """Takrorlanishni aniqlash uchun: kichik harf, tinish belgilarisiz, birlik bilan."""
    text = f"{name} {unit}".lower().replace("ʻ", "'").replace("‘", "'").replace("’", "'")
    text = re.sub(r"[^\w²×]+", " ", text)
    return " ".join(text.split())


def image_for(key: str) -> tuple[str, str]:
    """static/catalog/<kalit>.jpg bo'lsa — (URL, muallif/litsenziya)."""
    if key and (IMAGE_DIR / f"{key}.jpg").is_file():
        return f"/static/catalog/{key}.jpg", load_image_credits().get(key, {}).get("credit", "")
    return "", ""


def seed_catalog() -> int:
    """catalog.json'ni bazaga yozadi. Qo'shilgan yoki yangilanganlar sonini qaytaradi."""
    data = load_catalog_json()
    sources = data["sources"]
    changed = 0
    for row in data["items"]:
        source = sources.get(row["source"]) if row.get("source") else None
        image, credit = image_for(row["key"])
        fields = {
            "name": row["name"],
            "name_key": name_key(row["name"], row["unit"]),
            "category": row["category"],
            "unit": row["unit"],
            "price": row["price"],
            "price_min": row.get("price_min"),
            "price_max": row.get("price_max"),
            "quality": row.get("quality", "standard"),
            "source_name": source["name"] if source else "UySmeta bahosi (bozor o'rtachasi)",
            "source_url": source["url"] if source else "",
            "verified": bool(source),
            "image": image,
            "image_credit": credit,
            "kind": row["key"],
        }
        item = CatalogItem.objects.filter(key=row["key"]).first() or CatalogItem.objects.filter(name_key=fields["name_key"]).first()
        if item is None:
            CatalogItem.objects.create(key=row["key"], origin="seed", **fields)
            changed += 1
        elif item.origin == "seed":
            # JSON'dagi yangi narx va rasmlar bazaga o'tadi
            updates = {k: v for k, v in fields.items() if getattr(item, k) != v}
            if item.key != row["key"]:
                updates["key"] = row["key"]
            if updates:
                CatalogItem.objects.filter(id=item.id).update(updated_at=timezone.now(), **updates)
                changed += 1
        else:
            # Admin narxini o'zgartirgan — faqat kalit va rasm bog'lanadi
            CatalogItem.objects.filter(id=item.id).update(
                key=row["key"], image=item.image or image, image_credit=item.image_credit or credit
            )
    return changed


@lru_cache(maxsize=1)
def catalog_kinds() -> dict:
    """Mahsulot turlari (catalog.json kalitlari): {"parda": {"label", "category", "unit"}} — import va admin uchun."""
    return {
        row["key"]: {"label": row["name"], "category": row["category"], "unit": row["unit"]}
        for row in load_catalog_json()["items"]
    }


def catalog_for_prompt() -> str:
    """AI uchun katalog: "id | kategoriya | tur | nom | birlik | narx (min–max) | sifat"."""
    lines = ["id | kategoriya | tur | nom | birlik | narx so'm (oraliq) | sifat"]
    for item in CatalogItem.objects.order_by("category", "kind", "quality", "name"):
        band = f" ({item.price_min}–{item.price_max})" if item.price_min and item.price_max else ""
        lines.append(f"{item.id} | {item.category} | {item.kind or '-'} | {item.name} | {item.unit} | {item.price}{band} | {item.quality}")
    return "\n".join(lines)


def record_missing(*, name: str, category: str, unit: str) -> None:
    """Foydalanuvchi so'ragan, lekin katalogda yo'q narsa — admin narxini kiritishi uchun ro'yxatga yoziladi."""
    name = name.strip()[:120]
    unit = (unit.strip() or "dona")[:20]
    if not name:
        return
    key = name_key(name, unit)
    if CatalogItem.objects.filter(name_key=key).exists():
        return
    updated = CatalogRequest.objects.filter(name_key=key).update(
        times_requested=F("times_requested") + 1, last_requested_at=timezone.now()
    )
    if not updated:
        CatalogRequest.objects.create(
            name=name, name_key=key, category=category if category in CATEGORY_LABELS else "dekor", unit=unit
        )
