"""
Internetdagi rasmiy do'konlardan joriy narxlar (hamkor do'konlar ulanguncha).

Manba: do'kon kategoriya sahifalaridagi schema.org JSON-LD ("ItemList" → Product: nom, narx) — sahifa ichidagi
standart ma'lumot, AI "o'qib bergan" taxmin emas. E'lon saytlari (OLX, prom, ustabor) ishlatilmaydi.
Do'kon rasmlari olinmaydi (mualliflik huquqi) — xonadagi haqiqiy ko'rinishni AI rasm modeli chizadi.
Manba nomi bazada ichki ma'lumot sifatida saqlanadi (admin uchun), foydalanuvchiga ko'rsatilmaydi.

Ishga tushirish: `python manage.py collect_prices` yoki admin panel → Katalog → «Narxlarni yangilash».
"""

import json
import logging
import re
import time

import requests
from django.utils import timezone

from .catalog import catalog_kinds, name_key
from .models import CatalogItem

log = logging.getLogger("uysmeta.market_prices")

TEXNOMART = "https://texnomart.uz/katalog/{slug}/?page={page}"
HEADERS = {"User-Agent": "Mozilla/5.0 (UySmeta narxlar bazasi)"}
LD_JSON = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S)
MIN_PRICE = 100_000


def _number(pattern: str, name: str) -> float | None:
    match = re.search(pattern, name, re.I)
    return float(match.group(1).replace(",", ".")) if match else None


def tv_kind(name: str) -> str | None:
    # Model kodidagi diagonal: UA43H3502, 55PRM2020, OLED83G5, 50QNED80 ...
    inch = _number(r"(?<!\d)(2[4-9]|[3-9]\d|1[01]\d)(?=[A-Z]{1,6}\d|\"|\s*(?:dyuym|inch|''))", name)
    if inch is None:
        return None
    return "tv-43" if inch <= 50 else "tv-55"


def washer_kind(name: str) -> str:
    kg = _number(r"(\d+(?:[.,]\d)?)\s*kg", name)
    if kg is None:
        # Sig'im model kodida: WW80… — 8 kg, PRM10… — 10 kg, PRM70… — 7 kg
        code = _number(r"\b(?:WW|WD|WF|PRM)(\d{2})", name)
        kg = code / 10 if code and code >= 20 else code
    return "kir-mashina-7" if kg is None or kg <= 7 else "kir-mashina-10"


def ac_kind(name: str) -> str:
    btu = _number(r"(?<!\d)(07|09|12|18|24|30|36)(?!\d)", name)
    return "konditsioner-12" if btu is None or btu <= 12 else "konditsioner-18"


SOURCES = [
    # (do'kon kategoriyasi, turni nomdan aniqlash)
    ("televizory", tv_kind),
    ("holodilniki", lambda n: "muzlatgich-artel" if re.search(r"artel", n, re.I) else "muzlatgich-samsung"),
    ("stiralnye-mashinki", washer_kind),
    ("vse-kondicionery-5", ac_kind),
    ("gazovye-plity", lambda n: "gaz-plita-gefest" if re.search(r"gefest", n, re.I) else "gaz-plita-artel"),
    ("vytyazhki", lambda n: "vytyajka"),
    ("vodonagrevateli", lambda n: None if re.search(r"kotel|qozon", n, re.I) else "boyler"),  # isitish qozoni — boyler emas
]


def parse_products(html: str) -> list[tuple[str, int, str]]:
    """Sahifadagi JSON-LD mahsulotlari: [(nom, narx, havola)]."""
    out = []
    for block in LD_JSON.findall(html):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        lists = data if isinstance(data, list) else [data]
        for entry in lists:
            if not isinstance(entry, dict) or entry.get("@type") != "ItemList":
                continue
            for element in entry.get("itemListElement", []):
                item = element.get("item") or {}
                offer = item.get("offers") or {}
                try:
                    price = int(float(offer.get("price") or 0))
                except (TypeError, ValueError):
                    continue
                name = " ".join(str(item.get("name") or "").split())
                if name and price >= MIN_PRICE:
                    out.append((name, price, str(item.get("url") or offer.get("url") or "")))
    return out


def fetch_category(slug: str, max_pages: int, pause: float) -> list[tuple[str, int, str]]:
    products, seen = [], set()
    for page in range(1, max_pages + 1):
        res = requests.get(TEXNOMART.format(slug=slug, page=page), headers=HEADERS, timeout=30)
        if res.status_code != 200:
            break
        batch = [p for p in parse_products(res.text) if p[0] not in seen]
        if not batch:
            break
        seen.update(p[0] for p in batch)
        products += batch
        time.sleep(pause)  # do'kon serveriga yuklama bermaslik uchun
    return products


def _qualities(prices: list[int]) -> list[str]:
    """Tur ichida narx bo'yicha: arzon uchdan biri — ekonom, o'rtasi — o'rta, qimmati — premium."""
    order = sorted(prices)
    low, high = order[len(order) // 3], order[(2 * len(order)) // 3]
    return ["economy" if p < low else "premium" if p > high else "standard" for p in prices]


def collect(max_pages: int = 8, pause: float = 1.0) -> dict:
    """Barcha manbalardan narxlarni yig'ib, katalogga yozadi. {"created", "updated", "skipped", "kinds": {tur: soni}}."""
    kinds = catalog_kinds()
    by_kind: dict[str, list[tuple[str, int, str]]] = {}
    for slug, classify in SOURCES:
        try:
            products = fetch_category(slug, max_pages, pause)
        except requests.RequestException as error:
            log.warning("[narxlar] %s: %s", slug, error)
            continue
        for name, price, url in products:
            kind = classify(name)
            if kind in kinds:
                by_kind.setdefault(kind, []).append((name, price, url))

    created = updated = skipped = 0
    now = timezone.now()
    for kind, rows in by_kind.items():
        info = kinds[kind]
        for (name, price, url), quality in zip(rows, _qualities([r[1] for r in rows])):
            key = name_key(name, info["unit"])
            item = CatalogItem.objects.filter(name_key=key).first()
            fields = {
                "name": name[:160], "kind": kind, "category": info["category"], "unit": info["unit"],
                "price": price, "price_min": None, "price_max": None, "quality": quality,
                "source_name": "texnomart.uz", "source_url": url[:500], "verified": True, "updated_at": now,
            }
            if item is None:
                CatalogItem.objects.create(name_key=key, origin="market", **fields)
                created += 1
            elif item.origin == "market":
                CatalogItem.objects.filter(id=item.id).update(**fields)
                updated += 1
            else:
                skipped += 1  # hamkor yoki administrator kiritgan narx ustun
    return {"created": created, "updated": updated, "skipped": skipped, "kinds": {k: len(v) for k, v in by_kind.items()}}
