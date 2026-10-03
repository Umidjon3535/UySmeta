"""
Hamkor do'konlar mahsulotlarini katalogga import qilish (admin panel → Katalog → Import).

Fayl: CSV (UTF-8, ajratkich "," yoki ";"), ixtiyoriy ZIP — rasmlar. Ustunlar (sarlavha qatori majburiy):
  nomi*, tur*, narx*, sifat, birlik, toifa, narx_min, narx_max, dokon, havola, rasm, rang
- tur — catalog.json kaliti (parda, divan, tv-55 ...): 3D shakli va xonaning qaysi qoidasiga tushishi shundan;
- rasm — internet manzili (https://...) yoki ZIP ichidagi fayl nomi;
- toifa va birlik bo'sh bo'lsa — turdan olinadi; sifat: ekonom / orta / premium.

Rasmlar import paytida emas, fon oqimida qayta ishlanadi (ko'p mahsulotda so'rov uzoq cho'zilmasin):
fon olib tashlanadi (real ko'rinish uchun PNG), asosiy rang aniqlanadi (3D uchun), oddiy rasm katalog uchun.
"""

import csv
import io
import ipaddress
import logging
import re
import secrets
import socket
import threading
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import requests
from django.db import transaction
from django.utils import timezone
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from .catalog import CATEGORY_LABELS, catalog_kinds, name_key
from .models import CatalogItem
from .uploads import detect_image_type, photo_url, upload_dir

log = logging.getLogger("uysmeta.catalog_import")

MAX_ROWS = 5000
MAX_CSV_BYTES = 5 * 1024 * 1024
MAX_IMAGE_BYTES = 8 * 1024 * 1024
QUALITIES = {
    "economy": "economy", "ekonom": "economy", "arzon": "economy",
    "standard": "standard", "orta": "standard", "o'rta": "standard", "": "standard",
    "premium": "premium", "qimmat": "premium",
}
# Sarlavhalar: o'zbekcha va inglizcha nomlar bir xil ustunga tushadi
HEADERS = {
    "nomi": "name", "name": "name", "nom": "name",
    "tur": "kind", "kind": "kind",
    "narx": "price", "price": "price",
    "sifat": "quality", "quality": "quality",
    "birlik": "unit", "unit": "unit",
    "toifa": "category", "category": "category", "kategoriya": "category",
    "narx_min": "price_min", "price_min": "price_min",
    "narx_max": "price_max", "price_max": "price_max",
    "dokon": "shop", "do'kon": "shop", "shop": "shop",
    "havola": "url", "url": "url", "link": "url",
    "rasm": "image", "image": "image", "photo": "image",
    "rang": "color", "color": "color",
}
TEMPLATE_CSV = (
    "nomi;tur;narx;sifat;birlik;toifa;narx_min;narx_max;dokon;havola;rasm;rang\n"
    "Parda «Velvet» kulrang, 2 qanot;parda;850000;orta;;;;;Parda Market;https://example.uz/velvet;https://example.uz/img/velvet.jpg;\n"
    "Divan «Oslo» 3 o'rinli;divan;5400000;premium;;;4900000;5900000;Mebel Uz;https://example.uz/oslo;oslo.jpg;#6b7f99\n"
)


class CatalogImportError(Exception):
    pass


def _price(value: str) -> int | None:
    digits = re.sub(r"[^\d]", "", value or "")
    return int(digits) if digits and int(digits) > 0 else None


def _read_csv(data: bytes) -> list[dict]:
    if len(data) > MAX_CSV_BYTES:
        raise CatalogImportError("CSV fayl 5 MB dan oshmasin")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1251", errors="replace")  # Excel'ning eski "CSV" saqlashi
    first = text.split("\n", 1)[0]
    delimiter = max((";", ",", "\t"), key=first.count)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = list(reader)
    if not rows:
        raise CatalogImportError("CSV bo'sh")
    columns = [HEADERS.get(h.strip().lower().replace(" ", "_")) for h in rows[0]]
    if "name" not in columns or "kind" not in columns or "price" not in columns:
        raise CatalogImportError("Sarlavha qatorida «nomi», «tur» va «narx» ustunlari bo'lishi shart")
    out = []
    for cells in rows[1:]:
        if not any(c.strip() for c in cells):
            continue
        out.append({col: cells[i].strip() for i, col in enumerate(columns) if col and i < len(cells)})
    if len(out) > MAX_ROWS:
        raise CatalogImportError(f"Bir martada {MAX_ROWS} tagacha mahsulot")
    return out


def _staging_dir() -> Path:
    folder = upload_dir() / "_import"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def import_catalog(csv_file, zip_file=None) -> dict:
    """Qatorlarni tekshirib, katalogga yozadi. {"created", "updated", "errors": [(qator, matn)], "images"}."""
    rows = _read_csv(csv_file.read())
    archive = None
    if zip_file:
        try:
            archive = zipfile.ZipFile(zip_file)
        except zipfile.BadZipFile as error:
            raise CatalogImportError("ZIP fayl ochilmadi") from error
        zip_names = {Path(n).name.lower(): n for n in archive.namelist() if not n.endswith("/")}

    kinds = catalog_kinds()
    created = updated = images = 0
    errors = []
    with transaction.atomic():
        for number, row in enumerate(rows, start=2):  # 1-qator — sarlavha
            name = (row.get("name") or "")[:160]
            kind = (row.get("kind") or "").lower()
            price = _price(row.get("price"))
            if not name:
                errors.append((number, "nomi bo'sh"))
                continue
            if kind not in kinds:
                errors.append((number, f"«{kind or '—'}» turi yo'q (ro'yxatdagi turlardan birini yozing)"))
                continue
            if not price:
                errors.append((number, "narx noto'g'ri"))
                continue
            quality = QUALITIES.get((row.get("quality") or "").lower().replace("ʻ", "'"))
            if quality is None:
                errors.append((number, "sifat: ekonom, orta yoki premium"))
                continue
            category = (row.get("category") or "").lower() or kinds[kind]["category"]
            if category not in CATEGORY_LABELS:
                errors.append((number, f"«{category}» toifasi yo'q"))
                continue
            unit = (row.get("unit") or kinds[kind]["unit"])[:20]
            color = (row.get("color") or "").lower()
            fields = {
                "name": name,
                "kind": kind,
                "category": category,
                "unit": unit,
                "price": price,
                "price_min": _price(row.get("price_min")),
                "price_max": _price(row.get("price_max")),
                "quality": quality,
                "source_name": (row.get("shop") or "Hamkor do'kon")[:120],
                "source_url": (row.get("url") or "")[:500] if (row.get("url") or "").startswith(("http://", "https://")) else "",
                "verified": True,
                "color": color if re.fullmatch(r"#[0-9a-f]{6}", color) else "",
            }

            # Rasm: ZIP ichidagi fayl — vaqtinchalik papkaga, URL — keyin yuklanadi
            source = ""
            image = (row.get("image") or "").strip()
            if image.startswith(("http://", "https://")):
                source = image
            elif image and archive is not None:
                member = zip_names.get(Path(image).name.lower())
                if member is None:
                    errors.append((number, f"ZIP ichida «{image}» rasmi topilmadi (mahsulot rasmsiz qo'shildi)"))
                else:
                    staged = _staging_dir() / f"{secrets.token_urlsafe(9)}{Path(member).suffix.lower()[:5]}"
                    staged.write_bytes(archive.read(member)[: MAX_IMAGE_BYTES + 1])
                    source = f"file:{staged.name}"
            elif image:
                errors.append((number, "rasm uchun ZIP yuklanmagan (mahsulot rasmsiz qo'shildi)"))

            key = name_key(name, unit)
            item = CatalogItem.objects.filter(name_key=key).first()
            if item and item.origin == "seed":
                errors.append((number, "bu nom boshlang'ich bazada bor — boshqacha nomlang"))
                continue
            if item:
                for k, v in fields.items():
                    setattr(item, k, v)
                if source:
                    item.image_source, item.image_error = source, ""
                item.updated_at = timezone.now()
                item.save()
                updated += 1
            else:
                CatalogItem.objects.create(name_key=key, origin="partner", image_source=source, **fields)
                created += 1
            images += bool(source)
    return {"created": created, "updated": updated, "errors": errors, "images": images}


# ============================ Rasmlarni qayta ishlash (fon oqimi) ============================


def _safe_url(url: str) -> bool:
    """Faqat ochiq internet manzillari (ichki tarmoq va serverning o'ziga so'rov yuborilmasin)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parsed.hostname, None)}
    except socket.gaierror:
        return False
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


def _download(url: str) -> bytes:
    if not _safe_url(url):
        raise ValueError("manzil ruxsat etilmagan")
    with requests.get(url, timeout=20, stream=True, headers={"User-Agent": "UySmeta catalog import"}, allow_redirects=False) as res:
        res.raise_for_status()
        data = b""
        for chunk in res.iter_content(64 * 1024):
            data += chunk
            if len(data) > MAX_IMAGE_BYTES:
                raise ValueError("rasm 8 MB dan katta")
    return data


def remove_background(image: Image.Image) -> Image.Image:
    """
    Mahsulot rasmining bir xil rangli fonini (odatda oq) shaffof qiladi: chetlardan fon rangiga yaqin piksellar to'ldiriladi.
    Rasmda shaffoflik allaqachon bo'lsa yoki fon bir xil bo'lmasa (xona ichidagi surat) — o'zgarmaydi.
    """
    image = image.convert("RGBA")
    alpha = image.getchannel("A")
    if alpha.getextrema()[0] < 250:
        return image  # allaqachon foni yo'q PNG
    rgb = image.convert("RGB")
    w, h = rgb.size
    border = [rgb.getpixel((x, y)) for x in range(0, w, max(1, w // 40)) for y in (0, h - 1)]
    border += [rgb.getpixel((x, y)) for y in range(0, h, max(1, h // 40)) for x in (0, w - 1)]
    avg = tuple(sum(p[i] for p in border) / len(border) for i in range(3))
    spread = max(abs(p[i] - avg[i]) for p in border for i in range(3))
    if spread > 40:
        return image  # fon bir xil emas — kesib bo'lmaydi
    marker = (1, 254, 3)
    filled = rgb.copy()
    for point in [(x, y) for x in range(0, w, max(1, w // 20)) for y in (0, h - 1)] + [(x, y) for y in range(0, h, max(1, h // 20)) for x in (0, w - 1)]:
        if filled.getpixel(point) != marker:
            ImageDraw.floodfill(filled, point, marker, thresh=38)
    diff = ImageChops.difference(filled, Image.new("RGB", (w, h), marker))
    r, g, b = diff.split()
    mask = ImageChops.lighter(ImageChops.lighter(r, g), b).point(lambda v: 255 if v > 0 else 0)
    mask = mask.filter(ImageFilter.GaussianBlur(1))
    image.putalpha(mask)
    return image


def dominant_color(cutout: Image.Image) -> str:
    small = cutout.convert("RGBA").resize((48, 48))
    pixels = [p for p in small.getdata() if p[3] > 128]
    if not pixels:
        return ""
    # Yaltiroq oq va qora soyalar rangni buzmasin
    core = [p for p in pixels if 25 < sum(p[:3]) / 3 < 240] or pixels
    r, g, b = (round(sum(p[i] for p in core) / len(core)) for i in range(3))
    return f"#{r:02x}{g:02x}{b:02x}"


def _save(image: Image.Image, fmt: str) -> str:
    name = f"{secrets.token_urlsafe(12)}.{'png' if fmt == 'PNG' else 'jpg'}"
    folder = upload_dir()
    folder.mkdir(parents=True, exist_ok=True)
    if fmt == "PNG":
        image.save(folder / name, "PNG", optimize=True)
    else:
        image.convert("RGB").save(folder / name, "JPEG", quality=85, optimize=True)
    return name


def process_image(data: bytes) -> tuple[str, str, str]:
    """(katalog rasmi URL, fonsiz PNG fayl nomi, asosiy rang)."""
    if not detect_image_type(data):
        raise ValueError("faqat JPG, PNG yoki WEBP")
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    image.thumbnail((900, 900))
    cutout = remove_background(image)
    box = cutout.getchannel("A").getbbox()
    if box:
        cutout = cutout.crop(box)
    cutout.thumbnail((700, 700))
    flat = Image.new("RGB", image.size, "white")
    rgba = image.convert("RGBA")
    flat.paste(rgba, mask=rgba.getchannel("A"))
    return photo_url(_save(flat, "JPEG")), _save(cutout, "PNG"), dominant_color(cutout)


_worker = threading.Lock()


def process_pending_images() -> int:
    """
    Rasmi kutilayotgan mahsulotlar: yuklab, qayta ishlab, natijani yozadi. Qayta ishlanganlar soni.
    Bir vaqtda bitta oqim ishlaydi; ish paytida qo'shilgan yangi import ham shu aylanishda olinadi.
    """
    if not _worker.acquire(blocking=False):
        return 0
    done = 0
    try:
        while True:
            batch = list(CatalogItem.objects.exclude(image_source="").order_by("id")[:50])
            if not batch:
                return done
            for item in batch:
                _process_item(item)
                done += 1
    finally:
        _worker.release()


def _process_item(item: CatalogItem) -> None:
    source = item.image_source
    try:
        if source.startswith("file:"):
            staged = _staging_dir() / Path(source[5:]).name
            data = staged.read_bytes()
            staged.unlink(missing_ok=True)
        else:
            data = _download(source)
        image, cutout, color = process_image(data)
        item.image, item.cutout, item.image_error = image, cutout, ""
        item.image_credit = item.source_name
        if not item.color:
            item.color = color
    except Exception as error:  # bitta rasm xatosi qolganlarini to'xtatmasin
        log.warning("[catalog-import] %s: %s", item.name, error)
        item.image_error = str(error)[:200] or "rasmni o'qib bo'lmadi"
    item.image_source = ""
    item.save(update_fields=["image", "cutout", "color", "image_credit", "image_error", "image_source"])
