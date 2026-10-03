"""
Xona rasmining geometriyasi — "3D rasm ustida" (real ko'rinish) uchun.

Gemini tahlil modeli (bepul tarifda ham ishlaydi) rasmda topadi:
- orqa devorning 4 burchagi (shift va pol bilan, yon devorlar bilan tutashgan joylar);
- deraza va eshiklar: qaysi devorda va rasmdagi to'rtburchagi.
Brauzer (static/js/room3d.js) shu burchaklardan kamera holatini hisoblaydi va loyihadagi 3D sahnani aynan shu
rasm perspektivasida chizadi. AI topa olmasa — taxminiy burchaklar qo'yiladi, foydalanuvchi ularni sahifada suradi.

Koordinatalar rasm o'lchamiga nisbatan 0..1 (rasm tashqarisidagi burchak uchun <0 yoki >1 bo'lishi mumkin).
"""

import io
import json
import logging
from datetime import timedelta

from django.utils import timezone

from .ai_gemini import gemini_enabled, gemini_json, image_part
from .models import RoomDesign
from .render import RenderError, _photo_bytes

log = logging.getLogger("uysmeta.geometry")

STALE_AFTER = timedelta(minutes=3)
# Sinovda orqa devorni eng aniq topgan modellar (xato ~1%); ular band bo'lsa — umumiy ro'yxat
GEOMETRY_MODELS = ["gemini-3.5-flash", "gemini-robotics-er-2-preview", "gemini-3.5-flash-lite", "gemini-2.5-flash"]
DEFAULT_BACK = [[0.3, 0.27], [0.7, 0.27], [0.7, 0.7], [0.3, 0.7]]  # chap-yuqori, o'ng-yuqori, o'ng-past, chap-past

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "label": {"type": "STRING", "enum": ["back_wall", "window", "door"]},
                    "wall": {"type": "STRING", "enum": ["back", "left", "right"]},
                    "box_2d": {"type": "ARRAY", "items": {"type": "INTEGER"}},
                },
                "required": ["label", "wall", "box_2d"],
            },
        }
    },
    "required": ["items"],
}

PROMPT = "You are a precise object detector for interior photos."
# Gemini obyektlarni [ymin, xmin, ymax, xmax] (0-1000) formatida eng aniq topadi
QUESTION = (
    "Detect in this room photo: (1) back_wall — the far wall that faces the camera, bounded by the ceiling line, the floor "
    "line and the two corners where the side walls meet it; it does NOT include the side walls, floor or ceiling, so it is "
    "usually much smaller than the image. (2) every window and (3) every door or open doorway, with the wall it is on. "
    "Return box_2d as [ymin, xmin, ymax, xmax] normalized to 0-1000."
)


def _prepared(design: RoomDesign) -> tuple[bytes, tuple[int, int]]:
    """EXIF burilishini qo'llab, kichraytirilgan JPEG — brauzer ko'rsatgan rasm bilan bir xil yo'nalishda."""
    from PIL import Image, ImageOps

    data, _ = _photo_bytes(design)
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    size = img.size
    img.thumbnail((1280, 1280))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=88)
    return out.getvalue(), size


def default_geometry(size: tuple[int, int] | None) -> dict:
    return {"img": list(size or (1600, 1200)), "back": DEFAULT_BACK, "openings": [], "auto": False}


def detect(design: RoomDesign) -> dict:
    image, size = _prepared(design)
    if not gemini_enabled():
        return default_geometry(size)
    ok, result = gemini_json(PROMPT, [image_part(image, "image/jpeg"), {"text": QUESTION}], SCHEMA, timeout=90, models=GEOMETRY_MODELS, temperature=0)
    if not ok or not isinstance(result, dict):
        log.warning("[geometry] AI javob bermadi: %s", result)
        return default_geometry(size)

    back, openings = None, []
    for item in result.get("items") or []:
        box = item.get("box_2d") or []
        if len(box) != 4:
            continue
        y1, y2 = sorted([box[0] / 1000, box[2] / 1000])
        x1, x2 = sorted([box[1] / 1000, box[3] / 1000])
        if x2 - x1 < 0.01 or y2 - y1 < 0.01:
            continue
        if item["label"] == "back_wall" and back is None:
            back = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
        elif item["label"] in ("window", "door"):
            openings.append({"kind": item["label"], "wall": item["wall"], "box": [round(v, 4) for v in (x1, y1, x2, y2)]})
    if not back or not _plausible(back) or (back[1][0] - back[0][0]) * (back[2][1] - back[1][1]) > 0.8:
        log.warning("[geometry] orqa devor topilmadi yoki butun kadr: %s", back)
        return {**default_geometry(size), "openings": openings[:8]}
    return {"img": list(size), "back": [[round(x, 4), round(y, 4)] for x, y in back], "openings": openings[:8], "auto": True}


def _plausible(back: list) -> bool:
    (tlx, tly), (trx, try_), (brx, bry), (blx, bly) = back
    return trx - tlx > 0.05 and brx - blx > 0.05 and bly - tly > 0.05 and bry - try_ > 0.05


def clean_corners(raw) -> list | None:
    """Foydalanuvchi surgan burchaklar (sahifadan): 4 ta [x, y], -1..2 oralig'ida."""
    try:
        back = [[round(min(2.0, max(-1.0, float(x))), 4), round(min(2.0, max(-1.0, float(y))), 4)] for x, y in raw]
    except (TypeError, ValueError):
        return None
    return back if len(back) == 4 and _plausible(back) else None


def run_geometry(design_id: int) -> None:
    """Fon vazifasi. Hech qachon xato bilan tugamaydi — eng yomon holatda taxminiy burchaklar."""
    design = RoomDesign.objects.get(id=design_id)
    try:
        geometry = detect(design)
    except (RenderError, OSError, ValueError, KeyError, TypeError) as error:
        log.error("[geometry] %s", error)
        geometry = default_geometry(None)
    design.geometry, design.geometry_status = json.dumps(geometry), "done"
    design.save(update_fields=["geometry", "geometry_status"])


def start_geometry(design: RoomDesign) -> bool:
    expire_stale(design)
    if design.geometry_status in ("processing", "done"):
        return False
    design.geometry_status, design.geometry_started_at = "processing", timezone.now()
    design.save(update_fields=["geometry_status", "geometry_started_at"])
    return True


def expire_stale(design: RoomDesign) -> None:
    if design.geometry_status == "processing" and design.geometry_started_at and timezone.now() - design.geometry_started_at > STALE_AFTER:
        design.geometry, design.geometry_status = json.dumps(default_geometry(None)), "done"
        design.save(update_fields=["geometry", "geometry_status"])
