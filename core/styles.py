"""
Jihozlash variantlari (core/data/styles.json): parda, eshik, divan, gilam, oboi, pol ... — har oilada 100+ variant.

- Loyihadagi har bir narsa turi (parda, divan, laminat-33 ...) bitta oilaga tegishli; loyiha har oiladan aniq bitta
  variantni oladi — AI xona rasmiga va so'rovga qarab tanlaydi (bo'lmasa — byudjetga mos variantlardan tasodifiy).
- «Boshqa variant» oldingi variantlarda tanlanganlarini takrorlamaydi.
- Narx o'zgarmaydi: katalogdagi shu tur va sifat darajasining narxi. Variant — ko'rinish (rang, material, naqsh),
  3D va real ko'rinish aynan shu parametrlar bilan chiziladi (room3d.js).
"""

import json
import logging
import random
from functools import lru_cache

from .catalog import DATA_DIR
from .models import RoomDesign

log = logging.getLogger("uysmeta.styles")

AI_OPTIONS = 40  # AI'ga har oiladan nechta variant ko'rsatiladi (so'rov ixcham bo'lsin)


@lru_cache(maxsize=1)
def load_styles() -> dict:
    return json.loads((DATA_DIR / "styles.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _indexes() -> tuple[dict, dict, dict]:
    data = load_styles()
    by_id = {item["id"]: item for item in data["items"]}
    by_family: dict[str, list] = {}
    for item in data["items"]:
        by_family.setdefault(item["family"], []).append(item)
    kind_family = {kind: fam for fam, info in data["families"].items() for kind in info["kinds"]}
    return by_id, by_family, kind_family


def get_style(style_id: str) -> dict | None:
    return _indexes()[0].get(style_id)


def family_of(kind: str) -> str | None:
    return _indexes()[2].get(kind)


def _rows(plan: dict) -> list[dict]:
    return [row for group in (plan or {}).get("groups", []) for row in group.get("items", [])]


def needed_families(plan: dict) -> list[str]:
    families = []
    for row in _rows(plan):
        fam = family_of(row.get("kind") or row.get("key") or "")
        if fam and fam not in families:
            families.append(fam)
    return families


def used_before(design: RoomDesign) -> dict[str, set]:
    """Shu xonaning boshqa variantlarida tanlangan variantlar: {oila: {id, ...}}."""
    root_id = design.variant_of_id or design.id
    if not root_id:
        return {}
    used: dict[str, set] = {}
    others = RoomDesign.objects.filter(variant_of_id=root_id) | RoomDesign.objects.filter(id=root_id)
    if design.id:
        others = others.exclude(id=design.id)
    for other in others:
        for fam, style_id in ((other.plan or {}).get("styles") or {}).items():
            used.setdefault(fam, set()).add(style_id)
    return used


def _candidates(family: str, budget: str, exclude: set) -> list[dict]:
    pool = [s for s in _indexes()[1].get(family, []) if s["id"] not in exclude]
    same = [s for s in pool if s["quality"] == budget]
    return same or pool or _indexes()[1].get(family, [])


def pick_random(families: list[str], budget: str, seed: str, exclude: dict[str, set] | None = None) -> dict[str, str]:
    rng = random.Random(seed)
    chosen = {}
    for fam in families:
        pool = _candidates(fam, budget, (exclude or {}).get(fam, set()))
        if pool:
            chosen[fam] = rng.choice(pool)["id"]
    return chosen


STYLE_PROMPT = """Sen interyer dizaynerisan. Foydalanuvchining xonasi (rasm) jihozlanmoqda.
Har bir oila uchun berilgan ro'yxatdan aynan BITTA variantni tanla (faqat ro'yxatdagi id).
Qoidalar:
1. Hammasi bir-biriga mos bo'lsin: bitta uslub va rang palitrasi (masalan, iliq neytral + bitta urg'u rang).
2. Xonaning turi, yorug'ligi va foydalanuvchi so'roviga mos bo'lsin. So'rovda rang yoki uslub aytilgan bo'lsa — shuni bajar.
3. Pol, devor va mebel ranglari kontrast bo'lsin (hammasi bir xil tusda emas).
4. reason — o'zbek tilida qisqa izoh (nega shu variant).
Javob faqat JSON."""

STYLE_SCHEMA = {
    "type": "object",
    "properties": {
        "choices": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"family": {"type": "string"}, "id": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["family", "id"],
            },
        },
        "palette": {"type": "string"},
    },
    "required": ["choices"],
}


def pick_with_ai(design: RoomDesign, plan: dict, families: list[str], seed: str, exclude: dict[str, set]) -> dict[str, str]:
    """AI xona rasmi va so'rovga qarab tanlaydi. Ishlamasa yoki noto'g'ri id qaytarsa — o'sha oila tasodifiy."""
    fallback = pick_random(families, design.budget, seed, exclude)
    from .ai_gemini import gemini_enabled, gemini_json, image_part
    from .uploads import CONTENT_TYPES, upload_dir

    if not families or not gemini_enabled():
        return fallback
    rng = random.Random(seed)
    options, allowed = [], {}
    for fam in families:
        pool = _candidates(fam, design.budget, exclude.get(fam, set()))
        pool = rng.sample(pool, min(AI_OPTIONS, len(pool)))
        allowed[fam] = {s["id"] for s in pool}
        label = load_styles()["families"][fam]["label"]
        options.append(f"## {fam} — {label}\n" + "\n".join(f"{s['id']} | {s['description']}" for s in pool))
    text = (
        f"Xona turi: {plan.get('roomType') or design.room_type}. Byudjet: {design.budget}.\n"
        f"Foydalanuvchi so'rovi: {design.wishes.strip() or 'yo`q'}\n"
        f"Loyiha g'oyasi: {plan.get('summary', '')}\n\n" + "\n\n".join(options)
    )
    parts = [{"text": text}]
    try:
        path = upload_dir() / design.photo
        parts.insert(0, image_part(path.read_bytes(), CONTENT_TYPES[design.photo.rsplit(".", 1)[-1]]))
    except (OSError, KeyError):
        pass
    ok, result = gemini_json(STYLE_PROMPT, parts, STYLE_SCHEMA, timeout=60, temperature=0.9)
    if not ok or not isinstance(result, dict):
        log.warning("[styles] AI tanlay olmadi: %s", result)
        return fallback
    chosen = dict(fallback)
    for choice in result.get("choices", []):
        fam, style_id = choice.get("family"), choice.get("id")
        if fam in allowed and style_id in allowed[fam]:
            chosen[fam] = style_id
    return chosen


def apply_styles(plan: dict, chosen: dict[str, str]) -> dict:
    """Tanlangan variantlar loyihaga yoziladi: plan["styles"] va har bir mos qatorga "style" / "styleName"."""
    plan["styles"] = chosen
    for row in _rows(plan):
        fam = family_of(row.get("kind") or row.get("key") or "")
        style = get_style(chosen.get(fam, "")) if fam else None
        if style:
            row["style"], row["styleName"] = style["id"], style["name"]
    return plan


def style_plan(design: RoomDesign, plan: dict, *, use_ai: bool) -> dict:
    """Loyihaga variantlarni tanlab qo'yadi (AI yoki tasodifiy). Xato bo'lsa ham loyiha buzilmaydi."""
    families = needed_families(plan)
    exclude = used_before(design)
    seed = design.public_id
    try:
        chosen = pick_with_ai(design, plan, families, seed, exclude) if use_ai else pick_random(families, design.budget, seed, exclude)
    except Exception:
        log.exception("[styles] tanlashda xato")
        chosen = pick_random(families, design.budget, seed, exclude)
    return apply_styles(plan, chosen)
