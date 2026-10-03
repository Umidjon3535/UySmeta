"""
Katalog rasmlarini Wikimedia Commons'dan (erkin litsenziyali) yuklash: static/catalog/<kalit>.jpg + core/data/image_credits.json.
Ishlatish:  python manage.py fetch_catalog_images            (faqat rasmi yo'qlarini)
            python manage.py fetch_catalog_images --key divan --pick 2   (boshqa natijani tanlash)
Pillow kerak: pip install -r requirements-dev.txt
"""

import html
import io
import json
import re
import time

import requests
from django.core.management.base import BaseCommand, CommandError

from core.catalog import DATA_DIR, IMAGE_DIR, load_catalog_json, seed_catalog

API = "https://commons.wikimedia.org/w/api.php"
HEADERS = {"User-Agent": "UySmetaCatalog/1.0 (https://uysmeta.uz; catalog thumbnails)"}
SIZE = 400


def search(query: str) -> list[dict]:
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f"{query} filetype:bitmap",
        "gsrnamespace": 6,
        "gsrlimit": 12,
        "prop": "imageinfo",
        "iiprop": "url|mime|extmetadata|size",
        "iiurlwidth": 600,
    }
    data = requests.get(API, params=params, headers=HEADERS, timeout=30).json()
    pages = sorted((data.get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 0))
    results = []
    for page in pages:
        info = (page.get("imageinfo") or [{}])[0]
        if info.get("mime") not in ("image/jpeg", "image/png") or info.get("width", 0) < 300:
            continue
        meta = info.get("extmetadata") or {}
        artist = re.sub(r"<[^>]+>", "", html.unescape((meta.get("Artist") or {}).get("value", ""))).strip()
        license_name = (meta.get("LicenseShortName") or {}).get("value", "")
        results.append({"thumb": info.get("thumburl"), "page": info.get("descriptionurl"), "artist": artist[:80], "license": license_name})
    return results


def square_jpeg(content: bytes) -> bytes:
    from PIL import Image, ImageOps

    image = Image.open(io.BytesIO(content)).convert("RGB")
    image = ImageOps.fit(image, (SIZE, SIZE), Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, "JPEG", quality=82, optimize=True, progressive=True)
    return out.getvalue()


class Command(BaseCommand):
    help = "Katalog rasmlarini Wikimedia Commons'dan yuklash"

    def add_arguments(self, parser):
        parser.add_argument("--key", help="faqat shu kalit")
        parser.add_argument("--pick", type=int, default=1, help="nechanchi qidiruv natijasi (1 dan)")
        parser.add_argument("--query", help="qidiruv so'zini almashtirish")
        parser.add_argument("--force", action="store_true", help="bor rasmlarni ham qayta yuklash")

    def handle(self, *args, **opts):
        try:
            import PIL  # noqa: F401
        except ImportError as error:
            raise CommandError("Pillow o'rnatilmagan: pip install -r requirements-dev.txt") from error

        IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        credits_path = DATA_DIR / "image_credits.json"
        credits = json.loads(credits_path.read_text(encoding="utf-8")) if credits_path.is_file() else {}
        items = [i for i in load_catalog_json()["items"] if not opts["key"] or i["key"] == opts["key"]]
        if not items:
            raise CommandError("Bunday kalit topilmadi")

        for item in items:
            target = IMAGE_DIR / f"{item['key']}.jpg"
            if target.exists() and not opts["force"] and not opts["key"]:
                continue
            query = opts["query"] or item.get("image_query") or item["name"]
            try:
                results = search(query)
                if len(results) < opts["pick"]:
                    self.stderr.write(f"{item['key']}: topilmadi ({query})")
                    continue
                chosen = results[opts["pick"] - 1]
                content = requests.get(chosen["thumb"], headers=HEADERS, timeout=60).content
                target.write_bytes(square_jpeg(content))
            except Exception as error:  # bitta rasm xatosi qolganlarini to'xtatmasin
                self.stderr.write(f"{item['key']}: xato — {error}")
                continue
            author = chosen["artist"] or "Noma'lum muallif"
            credits[item["key"]] = {
                "credit": f"{author}, {chosen['license'] or 'erkin litsenziya'} — Wikimedia Commons",
                "url": chosen["page"],
                "query": query,
            }
            self.stdout.write(f"{item['key']}: ok ({query})")
            time.sleep(0.5)  # Wikimedia serverlarini hurmat qilamiz

        credits_path.write_text(json.dumps(credits, ensure_ascii=False, indent=1), encoding="utf-8")
        from core.catalog import load_image_credits

        load_image_credits.cache_clear()
        seed_catalog()
        self.stdout.write(self.style.SUCCESS(f"Tayyor: {len(list(IMAGE_DIR.glob('*.jpg')))} ta rasm"))
