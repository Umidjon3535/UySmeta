"""
Real ko'rinish — bepul yo'l: Cloudflare Workers AI, FLUX.2 [klein] (rasmni tahrirlash, bir nechta namunaviy rasm bilan).

Bepul Cloudflare akkaunti (karta shart emas) har kuni ma'lum hajmda bepul hisoblash beradi — yuzlab rasm.
Sozlash (.env): CLOUDFLARE_ACCOUNT_ID va CLOUDFLARE_API_TOKEN ("Workers AI" ruxsati bilan token).
Ixtiyoriy: CLOUDFLARE_IMAGE_MODEL (sukut: @cf/black-forest-labs/flux-2-klein-9b).

AI'ga ikki rasm beriladi: 1) brauzerda chizilgan 3D kompozitsiya (narsalar aynan qayerda va qanday — styles.json
variantlari bilan), 2) xonaning asl rasmi. AI 1-rasmni xonaning haqiqiy fotosuratiga aylantiradi.
"""

import base64
import io
import logging
import os

import requests

from .models import RoomDesign
from .styles import get_style
from .uploads import upload_dir

log = logging.getLogger("uysmeta.render")

API = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}"
DEFAULT_MODEL = "@cf/black-forest-labs/flux-2-klein-9b"
INPUT_MAX = 511  # kirish rasmlari 512×512 dan kichik bo'lishi shart
OUTPUT_LONG = 1024

# Variant parametrlarini AI tushunadigan inglizcha so'zlarga
FABRIC_EN = {"velvet": "velvet", "linen": "linen", "satin": "satin", "blackout": "thick blackout fabric", "cotton": "cotton",
             "velour": "velour", "rogojka": "woven matting fabric", "chenille": "chenille", "ecoleather": "faux leather",
             "leather": "genuine leather", "boucle": "boucle"}
PATTERN_EN = {"plain": "solid colour", "stripes": "vertical stripes", "check": "check pattern", "floral": "floral pattern",
              "geometric": "geometric pattern", "ombre": "ombre gradient", "damask": "damask pattern", "texture": "subtle texture",
              "concrete": "concrete look", "linen": "linen texture", "medallion": "classic medallion", "oriental": "oriental ornament",
              "abstract": "abstract pattern", "border": "wide border"}
CURTAIN_EN = {"classic": "floor-length two-panel curtains", "tulle": "sheer white tulle with floor-length side curtains",
              "roman": "roman blind", "roller": "roller blind"}
DOOR_EN = {"flat": "flat flush", "panel2": "two-panel", "panel4": "four-panel", "glass-strip": "with a vertical glass strip",
           "glass-big": "with a large glass panel", "classic": "classic moulded", "loft": "loft style black-framed glazed",
           "grooves": "with horizontal grooves"}
NAMED = {
    "white": (244, 242, 238), "cream": (236, 227, 208), "beige": (217, 199, 167), "sand": (200, 176, 138), "light grey": (201, 201, 198),
    "grey": (154, 154, 152), "graphite": (74, 76, 80), "black": (38, 39, 42), "brown": (107, 74, 51), "chocolate": (75, 48, 33),
    "terracotta": (181, 96, 62), "burgundy": (122, 34, 51), "red": (168, 50, 45), "dusty pink": (212, 165, 160), "mustard": (201, 154, 46),
    "gold": (200, 161, 74), "olive": (122, 122, 69), "sage green": (156, 174, 148), "emerald": (31, 107, 82), "dark green": (36, 71, 58),
    "teal": (63, 143, 140), "light blue": (169, 198, 220), "blue": (60, 95, 138), "navy": (34, 50, 79), "lavender": (169, 156, 194),
    "natural oak": (180, 138, 92), "walnut": (110, 75, 51), "wenge": (61, 43, 34),
}


def cloudflare_image_enabled() -> bool:
    return bool(os.environ.get("CLOUDFLARE_ACCOUNT_ID") and os.environ.get("CLOUDFLARE_API_TOKEN"))


def color_name(hex_color: str) -> str:
    try:
        rgb = tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    except (TypeError, ValueError):
        return ""
    return min(NAMED, key=lambda n: sum((a - b) ** 2 for a, b in zip(NAMED[n], rgb)))


def style_en(kind: str, params: dict) -> str:
    """Tanlangan variant — inglizcha qisqa tavsif (AI aniq nimani chizayotganini bilsin)."""
    color = color_name(params.get("color", ""))
    second = color_name(params.get("color2", "")) if params.get("color2") else ""
    fabric = FABRIC_EN.get(params.get("fabric", ""), "")
    pattern = PATTERN_EN.get(params.get("pattern", ""), "")
    if kind == "parda":
        return f"{CURTAIN_EN.get(params.get('type'), 'curtains')}, {color} {fabric}, {pattern}".strip(", ")
    if kind == "eshik":
        finish = f"{color} wood" if params.get("finish") == "wood" else f"{color} painted"
        return f"{DOOR_EN.get(params.get('style'), '')} interior door, {finish}, {params.get('handle', 'chrome')} handle"
    if params.get("fabric"):
        return f"{color} {fabric} upholstery, {params.get('legs', '')} legs".replace(" , ", " ")
    if "head" in params:
        return f"bed with {color} upholstered headboard, {color_name(params.get('frame', ''))} wooden frame"
    if "front" in params:
        return f"{color} {params.get('finish', '')} finish, {params.get('front')} fronts"
    if "plank" in params:
        return f"{color} laminate flooring, {params.get('plank')} planks"
    if "look" in params:
        return f"{color} {params.get('look')}-look porcelain floor tiles {params.get('size')} cm, {params.get('finish')}"
    if "shape" in params:
        return f"{params.get('shape')} ceiling lamp, {params.get('metal')} metal, {color} shades"
    if params.get("pattern"):
        return f"{color} wallpaper with {pattern}" + (f" in {second}" if second else "")
    return f"{color} {params.get('finish', '')} paint".strip()


def build_prompt(design: RoomDesign) -> str:
    from .render import ROOM_EN, numbered_items

    lines = []
    for row in numbered_items(design.plan):
        style = get_style(row.get("style") or "")
        kind = row.get("kind") or row.get("key") or ""
        detail = style_en(kind, style["params"]) if style else ""
        lines.append(f"- {detail or row['name']}")
    room = ROOM_EN.get((design.plan or {}).get("roomType") or design.room_type, "room")
    return (
        f"Image 1 is a 3D render of a finished renovation of a {room}. Image 2 is a real photo of the same room from the same camera. "
        "Turn image 1 into ONE photorealistic professional interior photograph: keep exactly the same camera, framing, room shape, "
        "every object in the same position and size, the same floor, wall and ceiling materials and colours. Replace the 3D look "
        "with real materials: real fabric, wood grain, reflections, soft daylight from the window, natural shadows. "
        "Keep the window view from image 2. Do not add, remove or move objects. No text, no numbers, no watermark.\n"
        "Items in the room:\n" + "\n".join(lines)
    )


def _shrink(data: bytes, side: int = INPUT_MAX) -> bytes:
    from PIL import Image, ImageOps

    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    img.thumbnail((side, side))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90)
    return out.getvalue()


def _output_size(size: tuple[int, int] | None) -> tuple[int, int]:
    w, h = size or (4, 3)
    scale = OUTPUT_LONG / max(w, h)
    return max(256, round(w * scale / 16) * 16), max(256, round(h * scale / 16) * 16)


class CloudflareLimit(Exception):
    pass


def render_with_cloudflare(design: RoomDesign, photo: bytes, size: tuple[int, int] | None) -> bytes:
    """Fotorealistik rasm (JPEG/PNG baytlari). Xato — CloudflareLimit (kunlik bepul limit) yoki RuntimeError."""
    files = {}
    if design.render_guide:
        files["input_image_0"] = ("guide.jpg", _shrink((upload_dir() / design.render_guide).read_bytes()), "image/jpeg")
        files["input_image_1"] = ("room.jpg", _shrink(photo), "image/jpeg")
    else:
        files["input_image_0"] = ("room.jpg", _shrink(photo), "image/jpeg")
    width, height = _output_size(size)
    prompt = build_prompt(design)
    if not design.render_guide:
        prompt = prompt.replace("Image 1 is a 3D render of a finished renovation", "Image 1 is a real photo, redo it as a finished renovation")
    res = requests.post(
        API.format(account=os.environ["CLOUDFLARE_ACCOUNT_ID"], model=os.environ.get("CLOUDFLARE_IMAGE_MODEL") or DEFAULT_MODEL),
        headers={"Authorization": f"Bearer {os.environ['CLOUDFLARE_API_TOKEN']}"},
        data={"prompt": prompt[:2000], "width": str(width), "height": str(height)},
        files=files,
        timeout=180,
    )
    try:
        body = res.json()
    except ValueError:
        body = {}
    if res.status_code == 429 or any("limit" in str(e.get("message", "")).lower() for e in body.get("errors", []) or []):
        raise CloudflareLimit("Bugungi bepul AI rasm limiti tugadi. Ertaga qayta urinib ko'ring")
    if res.status_code in (401, 403):
        raise RuntimeError("Cloudflare tokeni noto'g'ri yoki unda «Workers AI» ruxsati yo'q")
    if not res.ok or not body.get("success", True):
        message = "; ".join(str(e.get("message", "")) for e in body.get("errors", []) or []) or f"HTTP {res.status_code}"
        raise RuntimeError(f"Cloudflare AI: {message[:200]}")
    image = (body.get("result") or {}).get("image") or body.get("image")
    if not image:
        raise RuntimeError("Cloudflare AI rasm qaytarmadi")
    return base64.b64decode(image)


# ============================ Zaxira: Pollinations.ai (kalitsiz, ro'yxatdan o'tishsiz) ============================
# Xona rasmini qabul qilmaydi — loyiha tavsifi (xona turi, o'lchami, tanlangan variantlar) bo'yicha o'xshash xonani chizadi.
# Shuning uchun natija "namuna" deb belgilanadi (render_source="prompt"), xonaning o'zi emas.

POLLINATIONS = "https://image.pollinations.ai/prompt/{prompt}"


def sample_prompt(design: RoomDesign) -> str:
    from .render import ROOM_EN, numbered_items

    items = []
    for row in numbered_items(design.plan):
        style = get_style(row.get("style") or "")
        kind = row.get("kind") or row.get("key") or ""
        if style:
            items.append(style_en(kind, style["params"]))
    room = ROOM_EN.get((design.plan or {}).get("roomType") or design.room_type, "room")
    return (
        f"photorealistic professional interior photograph of a renovated {room}, about {design.area:g} square meters, "
        f"ceiling {design.height:g} m, {design.windows} window, natural daylight, eye-level wide angle, "
        + ", ".join(items[:14])
        + ", no people, no text"
    )


def render_with_pollinations(design: RoomDesign, size: tuple[int, int] | None) -> bytes:
    from urllib.parse import quote

    width, height = _output_size(size)
    res = requests.get(
        POLLINATIONS.format(prompt=quote(sample_prompt(design)[:900])),
        params={"width": width, "height": height, "model": "flux", "nologo": "true", "seed": design.id or 1},
        headers={"User-Agent": "UySmeta"},
        timeout=120,
    )
    if res.status_code == 429:
        raise CloudflareLimit("AI rasm xizmati band. Bir daqiqadan keyin qayta urinib ko'ring")
    if not res.ok or not res.headers.get("content-type", "").startswith("image/"):
        raise RuntimeError(f"Pollinations: HTTP {res.status_code}")
    return res.content
