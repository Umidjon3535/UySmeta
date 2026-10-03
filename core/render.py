"""
"Real ko'rinish": foydalanuvchi yuklagan xona rasmining O'ZI loyihadagi narsalar bilan jihozlanadi —
3D ko'rinishning real varianti.

1. Gemini rasm modeli (GEMINI_IMAGE_MODEL) rasmni tahrirlaydi: kamera burchagi, xona shakli, deraza va eshik
   o'rni o'zgarmaydi; loyihadagi pardoz (pol, devor, ship) qo'llanadi, mebel, texnika va yoritgichlar qo'yiladi.
2. So'ng Gemini tahlil modeli tayyor rasmda har bir raqamlangan narsa qayerdaligini topadi — sahifada rasm ustida
   raqamlar chiqadi va ular narx ro'yxatidagi raqamlarga mos keladi.

Internetdan namunaviy rasm olinmaydi: AI ishlamasa, xato ko'rsatiladi. Google kalitida billing yoqilgan
bo'lishi shart (bepul tarifda rasm modellari limiti 0).
"""

import base64
import io
import json
import logging
import os
import secrets
from datetime import timedelta

import requests
from django.utils import timezone

from .ai_gemini import gemini_json, gemini_urls, image_part
from .catalog import load_catalog_json
from .models import RoomDesign
from .planner import group_choices, load_rooms
from .uploads import CONTENT_TYPES, delete_image, detect_image_type, upload_dir

log = logging.getLogger("uysmeta.render")

STALE_AFTER = timedelta(minutes=6)
# AI Studio va Google Cloud (Vertex AI) dagi nomlar biroz farq qiladi — topilmagani (404) o'tkazib yuboriladi
GEMINI_IMAGE_MODELS = ["gemini-3.1-flash-image", "gemini-3.1-flash-image-preview", "gemini-2.5-flash-image", "gemini-3-pro-image", "gemini-3-pro-image-preview"]

ROOM_EN = {
    "living": "living room",
    "bedroom": "bedroom",
    "kitchen": "kitchen",
    "bathroom": "bathroom",
    "children": "children's room",
    "hallway": "entrance hallway",
    "office": "home office",
    "other": "room",
    "auto": "room",
}

# Pardoz materiallari rasmda tayyor sirt sifatida tasvirlanadi
SURFACE_EN = {
    "devor-boyoq": "smooth matte painted walls",
    "oboi": "wallpaper on the walls",
    "kafel-devor": "ceramic wall tiles",
    "laminat-32": "laminate wood floor",
    "laminat-33": "laminate wood floor",
    "laminat-premium": "oak laminate wood floor",
    "keramogranit-60": "60x60 porcelain floor tiles",
    "keramogranit-120": "large format 120x60 porcelain floor tiles",
    "plintus": "skirting boards along the walls",
    "natyajnoy": "white stretch ceiling",
    "eshik": "new interior door in the existing doorway",
    "parda": "curtains on the windows",
}

# Rasmda ko'rinmaydigan narsalar (kley, grunt, kabel, ishlar ...) — raqamlanmaydi, narxi o'z bo'limida ko'rsatiladi
HIDDEN_KEYS = {"kafel-kley", "gidroizolyatsiya", "zatirka", "shpaklyovka", "gruntovka", "gipsokarton", "kabel", "rozetka", "matras"}
MAX_COPIES = 4

# Bo'limi yozilmagan narsalar (AI rejimi) uchun — katalog toifasidan
CATEGORY_GROUP = {"mebel": "mebel", "texnika": "texnika", "santexnika": "santexnika", "yoritish": "elektr", "dekor": "dekor"}
OTHER_GROUP = ("boshqa", "Boshqa materiallar va ishlar")

# Gemini qo'llaydigan tomonlar nisbatlari — natija asl rasm bilan bir xil ramkada bo'lishi uchun
ASPECT_RATIOS = ["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"]

MARKS_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "marks": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {"n": {"type": "INTEGER"}, "found": {"type": "BOOLEAN"}, "x": {"type": "NUMBER"}, "y": {"type": "NUMBER"}},
                "required": ["n", "found", "x", "y"],
            },
        }
    },
    "required": ["marks"],
}


class RenderError(Exception):
    pass


class NothingToFurnish(RenderError):
    """Loyihada rasmda ko'rinadigan narsa yo'q — xabar foydalanuvchiga to'g'ridan-to'g'ri ko'rsatiladi."""


class QuotaExceeded(RenderError):
    """Google kalitida rasm modellari limiti tugagan, billing yoki Cloud API yoqilmagan — xabar foydalanuvchiga ko'rsatiladi."""


def item_kind(item: dict) -> str:
    """Mahsulot turi: hamkor mahsulotida "kind" (parda, divan ...), boshlang'ich bazada — kalitning o'zi."""
    return item.get("kind") or item.get("key") or ""


def render_image_enabled() -> bool:
    """
    Real ko'rinish (AI fotosurat). Hozircha o'chiq: AI xonaning o'zini emas, o'xshash xonani chizyapti — rejim
    yangilanmoqda, foydalanuvchiga faqat 3D ko'rinish. Qayta yoqish: REAL_VIEW=true.
    """
    return os.environ.get("REAL_VIEW", "false").lower() == "true"


def gemini_image_enabled() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY")) and os.environ.get("GEMINI_IMAGE", "true").lower() != "false"


def is_visible(item: dict) -> bool:
    return item_kind(item) not in HIDDEN_KEYS and item.get("category") != "ish"


def plan_sections(plan: dict | None) -> list[dict]:
    """
    Narxlar "nimaga tegishli" bo'yicha: Pol, Devorlar, Ship, Mebel ... Har bo'limda material, buyum va ish narxi.
    Rasmda ko'rinadigan narsalarga tartib raqami (n) beriladi — real ko'rinishdagi raqamlar bilan bir xil.
    """
    labels = group_choices()
    by_key = _rule_groups()
    buckets: dict[str, list[dict]] = {}
    for group in (plan or {}).get("groups", []):
        for item in group.get("items", []):
            key = item.get("group") or by_key.get(item_kind(item)) or CATEGORY_GROUP.get(item.get("category"), OTHER_GROUP[0])
            buckets.setdefault(key if key in labels else OTHER_GROUP[0], []).append(dict(item))
    sections, number = [], 0
    for key in [*labels, OTHER_GROUP[0]]:
        rows = buckets.get(key)
        if not rows:
            continue
        rows.sort(key=lambda r: (r.get("category") == "ish", not is_visible(r)))  # avval ko'rinadigan, oxirida ishlar
        for row in rows:
            if is_visible(row):
                number += 1
                row["n"] = number
        sections.append({"key": key, "label": labels.get(key, OTHER_GROUP[1]), "items": rows, "total": sum(r["total"] for r in rows)})
    return sections


def _rule_groups() -> dict:
    """Katalog kaliti -> bo'lim (pol, devor ...) rooms.json qoidalaridan — AI rejimidagi loyihalarda bo'lim yozilmagan."""
    out = {}
    for room in load_rooms()["rooms"].values():
        for rule in room["rules"]:
            keys = rule["item"].values() if isinstance(rule["item"], dict) else [rule["item"]]
            for key in keys:
                if key:
                    out.setdefault(key, rule["group"])
    return out


def numbered_items(plan: dict | None) -> list[dict]:
    return [row for section in plan_sections(plan) for row in section["items"] if row.get("n")]


def _is_finish(row: dict) -> bool:
    return item_kind(row) in SURFACE_EN or row.get("category") == "material"


def _describe(row: dict, catalog: dict) -> str:
    key = item_kind(row)
    text = SURFACE_EN.get(key) or (catalog.get(key) or {}).get("image_query") or row["name"]
    line = f"#{row['n']} {text} ({row['name']})"
    if row.get("unit") == "dona" and (row.get("quantity") or 0) > 1:
        line += f", {int(min(row['quantity'], MAX_COPIES))} pcs"
    if row.get("placement"):
        line += f" — placement (Uzbek): {row['placement']}"
    return line


def build_prompt(design: RoomDesign) -> str:
    rows = numbered_items(design.plan)
    if not rows:
        raise NothingToFurnish("Loyihada rasmda ko'rsatiladigan narsa yo'q")
    catalog = {i["key"]: i for i in load_catalog_json()["items"]}
    finishes = [_describe(r, catalog) for r in rows if _is_finish(r)]
    objects = [_describe(r, catalog) for r in rows if not _is_finish(r)]
    room = ROOM_EN.get(design.room_type, "room")
    layout = (design.plan or {}).get("layout")
    return (
        f"This is a real photo of a {room} (about {design.area:g} m², ceiling {design.height:g} m). "
        "Redo THIS EXACT room from scratch according to the project below and show it as a real interior photograph.\n"
        "DO IT IN THIS ORDER:\n"
        "1. EMPTY THE ROOM COMPLETELY: remove every existing piece of furniture, appliance, lamp, curtain, rug, picture, "
        "plant, box, clutter, construction mess and person. Only the bare architecture stays: walls, floor, ceiling, "
        "window and door openings, radiators and pipes.\n"
        "2. APPLY THE FINISHES listed below to the floor, walls and ceiling. A surface without a listed finish keeps its "
        "current material, but clean and fresh.\n"
        "3. PLACE ONLY THE OBJECTS listed below, nothing else (no extra plants, pictures, vases, rugs, cushions or decorations).\n"
        "KEEP: exactly the same camera position, angle, lens, framing and crop; the same room shape, wall layout, "
        "window and door openings and natural light direction. It must be recognisably the same room, only emptied and redone.\n"
        "Place objects with correct perspective, real-world scale for this room size and contact shadows. "
        "Do not block doors or windows.\n"
        + ("FINISHES TO APPLY:\n" + "\n".join(finishes) + "\n" if finishes else "")
        + ("OBJECTS TO PLACE:\n" + "\n".join(objects) + "\n" if objects else "")
        + (f"Layout plan (Uzbek): {layout}\n" if layout else "")
        + (f"Customer wishes (Uzbek): {design.wishes}\n" if design.wishes else "")
        + "Photorealistic, no text, no numbers, no watermark, no borders."
    )


def locate_items(image: bytes, design: RoomDesign) -> dict:
    """Tayyor rasmda har bir raqamlangan narsaning markazi: {"n": [x%, y%]}. Topilmasa — bo'sh (rasm baribir ko'rsatiladi)."""
    rows = numbered_items(design.plan)
    listing = "\n".join(f"{r['n']}. {r['name']}" for r in rows)
    ok, result = gemini_json(
        "You locate objects in interior photos. Coordinates are 0-1000: x from the left edge, y from the top edge.",
        [
            image_part(image, CONTENT_TYPES[detect_image_type(image)]),
            {
                "text": "For each numbered item, return the point at the visual centre of that item in this photo "
                "(for a floor, wall or ceiling finish — a clearly visible spot of that surface). "
                "found=false if it is not visible.\n" + listing
            },
        ],
        MARKS_SCHEMA,
        timeout=60,
    )
    if not ok:
        log.warning("[render:marks] %s", result)
        return {}
    numbers = {r["n"] for r in rows}
    marks = {}
    for mark in result.get("marks", []):
        if mark.get("found") and mark.get("n") in numbers:
            marks[str(mark["n"])] = [round(min(max(mark["x"] / 10, 2), 98), 1), round(min(max(mark["y"] / 10, 3), 97), 1)]
    return marks


def _photo_bytes(design: RoomDesign) -> tuple[bytes, str]:
    if design.photo.startswith("https://"):
        data = requests.get(design.photo, timeout=30).content
    else:
        data = (upload_dir() / design.photo).read_bytes()
    kind = detect_image_type(data)
    if not kind:
        raise RenderError("Xona rasmini o'qib bo'lmadi")
    return data, CONTENT_TYPES[kind]


def _image_size(data: bytes) -> tuple[int, int] | None:
    try:
        from PIL import Image, ImageOps

        return ImageOps.exif_transpose(Image.open(io.BytesIO(data))).size
    except Exception:  # noqa: BLE001 — o'lchamsiz ham ishlayveradi
        return None


def _nearest_ratio(size: tuple[int, int]) -> str:
    w, h = size
    return min(ASPECT_RATIOS, key=lambda r: abs(int(r.split(":")[0]) / int(r.split(":")[1]) - w / h))


def _fit_to(data: bytes, size: tuple[int, int] | None) -> bytes:
    """AI natijasini asl rasm o'lchamiga keltiradi — oldin/keyin aniq ustma-ust tushadi."""
    if not size:
        return data
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return data
    img = Image.open(io.BytesIO(data)).convert("RGB")
    if img.size == size:
        return data
    out = io.BytesIO()
    ImageOps.fit(img, size, Image.LANCZOS).save(out, "JPEG", quality=92)
    return out.getvalue()


GUIDE_PROMPT = (
    "Image 1 is a real photo of a room. Image 2 is the exact renovation project for this room, rendered in 3D from the same "
    "camera. Produce ONE photorealistic interior photograph of this room that matches image 2 exactly: the same camera and "
    "framing, the same objects in the same positions and sizes, the same floor, wall and ceiling materials and the same colours. "
    "Make it look like a real professional photo: real material textures, natural daylight from the window, soft realistic "
    "shadows, reflections and ambient occlusion. Keep the view through the window from image 1. Do NOT add, remove, move or "
    "restyle any object. No text, no numbers, no watermark.\n"
)


def render_with_gemini(design: RoomDesign) -> bytes:
    image, media_type = _photo_bytes(design)
    prompt = build_prompt(design)
    extra_parts = []
    if design.render_guide:
        # Brauzerda chizilgan 3D kompozitsiya — AI faqat uni fotorealistik qiladi, narsalar va joylashuv o'zgarmaydi
        guide = (upload_dir() / design.render_guide).read_bytes()
        kind = detect_image_type(guide)
        if kind:
            extra_parts = [{"inlineData": {"mimeType": CONTENT_TYPES[kind], "data": base64.b64encode(guide).decode()}}]
            prompt = GUIDE_PROMPT + "Project items (for reference):\n" + "\n".join(f"- {r['name']}" for r in numbered_items(design.plan))
    size = _image_size(image)
    generation = {"responseModalities": ["IMAGE"], "temperature": 0.4}
    if size:
        generation["imageConfig"] = {"aspectRatio": _nearest_ratio(size)}
    preferred = os.environ.get("GEMINI_IMAGE_MODEL")
    models = list(dict.fromkeys([m for m in [preferred, *GEMINI_IMAGE_MODELS] if m]))
    last_error = "AI rasm modeli javob bermadi"
    quota_hits = cloud_disabled = 0
    for model in models:
        for url in gemini_urls(model):
            try:
                res = requests.post(
                    url,
                    headers={"Content-Type": "application/json", "x-goog-api-key": os.environ["GEMINI_API_KEY"]},
                    json={
                        "contents": [{"role": "user", "parts": [{"inlineData": {"mimeType": media_type, "data": base64.b64encode(image).decode()}}, *extra_parts, {"text": prompt}]}],
                        "generationConfig": generation,
                    },
                    timeout=150,
                )
            except requests.RequestException as error:
                log.warning("[render:gemini] %s ulanish xatosi: %s", url, error)
                continue
            data = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
            if not res.ok:
                message = (data.get("error") or {}).get("message", "") if isinstance(data, dict) else ""
                last_error = message[:200] or f"HTTP {res.status_code}"
                log.warning("[render:gemini] %s -> %s: %s", url, res.status_code, last_error)
                quota_hits += res.status_code == 429
                cloud_disabled += res.status_code == 403 and ("has not been used" in message or "disabled" in message)
                continue
            for part in ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []:
                if "inlineData" in part:
                    return _fit_to(base64.b64decode(part["inlineData"]["data"]), size)
            last_error = "AI rasm qaytarmadi"
    if cloud_disabled:
        raise QuotaExceeded(
            "Google Cloud loyihasida Vertex AI (Agent Platform) API yoqilmagan. Administrator uni Google Cloud Console'da "
            "yoqishi va loyihaga billing ulashi kerak"
        )
    if quota_hits:
        raise QuotaExceeded(
            "AI rasm xizmatining limiti tugagan: Google kalitida billing yoqilmagan. "
            "Administrator Google Cloud yoki AI Studio'da billingni yoqishi kerak"
        )
    raise RenderError(last_error)


def sample_colors(image: bytes, marks: dict) -> dict:
    """Har bir raqamlangan narsaning rangi tayyor rasmdan olinadi — 3D ko'rinish shu ranglar bilan chiziladi."""
    try:
        from PIL import Image, ImageStat
    except ImportError:
        return marks
    img = Image.open(io.BytesIO(image)).convert("RGB")
    w, h = img.size
    r = max(3, int(min(w, h) * 0.015))
    out = {}
    for n, (x, y, *_) in marks.items():
        cx, cy = int(w * x / 100), int(h * y / 100)
        patch = img.crop((max(0, cx - r), max(0, cy - r), min(w, cx + r), min(h, cy + r)))
        red, green, blue = (int(v) for v in ImageStat.Stat(patch).median)
        out[n] = [x, y, f"#{red:02x}{green:02x}{blue:02x}"]
    return out


def _save(data: bytes) -> str:
    kind = detect_image_type(data)
    if not kind:
        raise RenderError("Noma'lum rasm formati")
    name = f"{secrets.token_urlsafe(12)}.{kind}"
    folder = upload_dir()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(data)
    return name


def run_render(design_id: int) -> None:
    """Fon vazifasi: xonaning o'z rasmini loyiha bo'yicha jihozlaydi va narsalarni rasmda raqamlaydi."""
    design = RoomDesign.objects.get(id=design_id)
    try:
        data, source = render_photo(design)
        name = _save(data)
    except (RenderError, OSError) as error:
        log.error("[render] %s", error)
        has_photo = bool(design.render_photo) and design.render_source == "photo"
        # Oldingi rasm bo'lsa — u qoladi, xato faqat izoh sifatida ko'rsatiladi
        design.render_status = "done" if has_photo else "failed"
        shown = isinstance(error, (NothingToFurnish, QuotaExceeded, ShownError))
        design.render_error = str(error) if shown else "Xonangizni jihozlab bo'lmadi. Birozdan keyin qayta urinib ko'ring"
        design.save(update_fields=["render_status", "render_error"])
        return
    try:
        # Namuna (boshqa xona) rasmida raqamlar qo'yilmaydi — narsalar xonangizdagi joyida emas
        marks = sample_colors(data, locate_items(data, design)) if source == "photo" else {}
    except Exception as error:  # noqa: BLE001 — raqamlarsiz ham rasm ko'rsatiladi
        log.warning("[render:marks] %s", error)
        marks = {}
    old = design.render_photo
    design.render_photo, design.render_source, design.render_status, design.render_error = name, source, "done", ""
    design.render_marks = json.dumps(marks)
    design.save(update_fields=["render_photo", "render_source", "render_status", "render_error", "render_marks"])
    if old and old != name:
        delete_image(old)


class ShownError(RenderError):
    """Administratorga aynan ko'rsatiladigan xato (sozlash kerak bo'lgan holatlar)."""


def render_photo(design: RoomDesign) -> tuple[bytes, str]:
    """
    (rasm, manba). Tartib: bepul Cloudflare (xonaning o'z rasmi asosida) → Gemini → Pollinations (kalitsiz, faqat tavsif
    bo'yicha — manba "prompt": xonaning o'zi emas, namuna).
    """
    try:
        return _render_room_photo(design), "photo"
    except RenderError as error:
        if isinstance(error, NothingToFurnish):
            raise
        log.warning("[render] xona rasmi asosida chizib bo'lmadi (%s) — tavsif bo'yicha namuna", error)
        try:
            return _render_sample(design), "prompt"
        except RenderError:
            raise error from None


def _render_sample(design: RoomDesign) -> bytes:
    from .render_cloudflare import CloudflareLimit, render_with_pollinations

    photo, _ = _photo_bytes(design)
    size = _image_size(photo)
    try:
        return _fit_to(render_with_pollinations(design, size), size)
    except CloudflareLimit as limit:
        raise QuotaExceeded(str(limit)) from limit
    except (RuntimeError, requests.RequestException) as failure:
        log.warning("[render:pollinations] %s", failure)
        raise RenderError(str(failure)) from failure


def _render_room_photo(design: RoomDesign) -> bytes:
    from .render_cloudflare import CloudflareLimit, cloudflare_image_enabled, render_with_cloudflare

    if not numbered_items(design.plan):
        raise NothingToFurnish("Loyihada rasmda ko'rsatiladigan narsa yo'q")
    if not (cloudflare_image_enabled() or gemini_image_enabled()):
        raise ShownError("Xonangizning o'zini chizish uchun .env faylida CLOUDFLARE_ACCOUNT_ID va CLOUDFLARE_API_TOKEN (bepul) sozlang")
    error = None
    if cloudflare_image_enabled():
        photo, _ = _photo_bytes(design)
        size = _image_size(photo)
        try:
            return _fit_to(render_with_cloudflare(design, photo, size), size)
        except CloudflareLimit as limit:
            error = QuotaExceeded(str(limit))
        except (RuntimeError, requests.RequestException, OSError) as failure:
            log.warning("[render:cloudflare] %s", failure)
            error = ShownError(str(failure))
        if not gemini_image_enabled():
            raise error
    try:
        return render_with_gemini(design)
    except RenderError:
        if error:
            raise error  # Cloudflare xatosi aniqroq (Gemini odatda billing so'raydi)
        raise


def start_render(design: RoomDesign) -> bool:
    """Tayyorlashni boshlaydi. Allaqachon ketayotgan bo'lsa False."""
    expire_stale(design)
    if design.render_status == "processing":
        return False
    design.render_status, design.render_error, design.render_started_at = "processing", "", timezone.now()
    design.save(update_fields=["render_status", "render_error", "render_started_at"])
    return True


def expire_stale(design: RoomDesign) -> None:
    if design.render_status == "processing" and design.render_started_at and timezone.now() - design.render_started_at > STALE_AFTER:
        design.render_status, design.render_error = "failed", "Tayyorlash juda uzoq cho'zildi. Qayta urinib ko'ring"
        design.save(update_fields=["render_status", "render_error"])
