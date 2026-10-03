"""
AI jihozlash: xona rasmi + foydalanuvchi kiritgan aniq maydon -> xonaga mos narsalar ro'yxati va umumiy narx.

Qoidalar:
 - Narxlar FAQAT katalogdan (core/catalog.py) olinadi. AI narx o'ylab topmaydi, internetdan qidirmaydi.
 - Xona o'lchamlari o'zgarmaydi: maydonga bog'liq miqdorlarni (pol, devor, ship, perimetr) server
   foydalanuvchi kiritgan m² va balandlikdan o'zi hisoblaydi; AI faqat qaysi asosda hisoblashni aytadi.
 - AI foydalanuvchi so'raganini bajaradi. Katalogda yo'q narsa kerak bo'lsa — "missing" ro'yxatiga yozadi,
   u admin panelga tushadi va admin narxini kiritgach katalog kengayadi.
"""

import base64
import json
import logging
import math
from typing import Literal

from django.db.models import F, Q
from django.utils import timezone
from pydantic import BaseModel

from .ai import claude_enabled
from .ai_gemini import gemini_enabled, gemini_json, image_part
from .catalog import catalog_for_prompt, record_missing
from .estimate import QUALITY_LABELS
from .models import CatalogItem, RoomDesign
from .planner import group_rows, plan_row
from .regions import get_region
from .styles import style_plan
from .uploads import CONTENT_TYPES, upload_dir

log = logging.getLogger("uysmeta.design")

MODEL = "claude-opus-5"

ROOM_TYPE_LABELS = {
    "auto": "Rasmga qarab aniqlansin",
    "living": "Mehmonxona / yashash xonasi",
    "bedroom": "Yotoqxona",
    "kitchen": "Oshxona",
    "bathroom": "Vannaxona / hojatxona",
    "children": "Bolalar xonasi",
    "hallway": "Dahliz / koridor",
    "office": "Ish xonasi",
    "other": "Boshqa",
}

BASIS_LABELS = {
    "floor": "pol maydoni",
    "wall": "devor maydoni",
    "ceiling": "ship maydoni",
    "perimeter": "xona perimetri",
    "count": "soni",
}

DOOR_AREA = 1.6  # eshik o'rni, m²
WINDOW_AREA = 1.8  # deraza o'rni, m²
DOOR_WIDTH = 0.9  # plintus eshik o'rnida qo'yilmaydi, m
MATERIAL_RESERVE = 1.1  # kesish va zaxira uchun +10%
COUNT_UNITS = {"dona", "to'plam", "xizmat", "nuqta", "qop", "chelak", "rulon", "komplekt"}


# ============================ AI javobi sxemasi ============================


class PlanItem(BaseModel):
    catalogId: int
    catalogName: str  # katalogdagi nom — id adashsa shu bo'yicha tekshiriladi
    basis: Literal["floor", "wall", "ceiling", "perimeter", "count"]
    quantity: float
    placement: str
    reason: str


class MissingItem(BaseModel):
    name: str
    category: Literal["material", "mebel", "texnika", "santexnika", "yoritish", "dekor", "ish"]
    unit: str
    quantity: float
    reason: str


class DesignPlan(BaseModel):
    isRoomPhoto: bool
    roomType: Literal["living", "bedroom", "kitchen", "bathroom", "children", "hallway", "office", "other"]
    condition: Literal["karobka", "worn", "cosmetic", "good"]
    summary: str
    layout: str
    items: list[PlanItem]
    missing: list[MissingItem]
    notes: list[str]


# ============================ Geometriya ============================


def room_geometry(area: float, height: float) -> dict:
    """Foydalanuvchi kiritgan maydon va balandlikdan: perimetr va devor maydoni (xona kvadratga yaqin deb olinadi)."""
    perimeter = 4 * math.sqrt(area)
    wall = max(0.0, perimeter * height - DOOR_AREA - WINDOW_AREA)
    return {
        "area": round(area, 1),
        "height": round(height, 2),
        "perimeter": round(perimeter, 1),
        "wallArea": round(wall, 1),
    }


def compute_quantity(basis: str, ai_quantity: float, item: CatalogItem, geo: dict) -> float:
    """Miqdor: maydonga bog'liq bo'lsa — kiritilgan o'lchamlardan (AI o'zgartira olmaydi), aks holda AI aytgan son."""
    reserve = MATERIAL_RESERVE if item.category == "material" else 1.0
    if basis == "floor":
        qty = geo["area"] * reserve
    elif basis == "wall":
        qty = geo["wallArea"] * reserve
    elif basis == "ceiling":
        qty = geo["area"]
    elif basis == "perimeter":
        qty = max(0.0, geo["perimeter"] - DOOR_WIDTH) * reserve
    else:
        qty = max(0.0, ai_quantity)
        if item.unit == "m²":
            # Sonli asosda ham m² miqdor xonadagi eng katta yuzadan oshmasin
            qty = min(qty, max(geo["area"], geo["wallArea"]) * MATERIAL_RESERVE)
    if item.unit in COUNT_UNITS:
        return max(1, math.ceil(qty - 1e-9))
    return round(qty, 1)


# ============================ Prompt ============================

SYSTEM_PROMPT = """Sen UySmeta xizmatining tajribali interyer dizayneri va smetachisisan (O'zbekiston).
Foydalanuvchi xona rasmini, xonaning ANIQ maydonini va o'z so'rovini yuboradi. Vazifang — xonaga mos narsalarni tanlab, qayerga qo'yilishini aytish.

Qat'iy qoidalar:
1. Faqat quyidagi KATALOGdagi narsalarni tanla: id'sini catalogId ga, nomini katalogdagidek aynan catalogName ga yoz.
   Narx o'ylab topma — narxni server katalogdan oladi. layout va placement'da ham faqat tanlangan narsalarni tilga ol.
2. Xona o'lchamlarini o'zgartirma va o'zing qayta hisoblama. Maydonga bog'liq narsalar uchun basis bering:
   - "floor" — pol qoplamasi, pol ishlari (maydon = kiritilgan m² ning o'zi);
   - "wall" — devor kafeli, shpaklyovka/bo'yash ishi, oboi yopishtirish ishi;
   - "ceiling" — ship (natyajnoy potolok va h.k.);
   - "perimeter" — plintus;
   - "count" — dona bilan sanaladiganlar (mebel, texnika, santexnika, qop/chelak/rulon materiallar, xizmatlar).
   Miqdorni server shu o'lchamlardan hisoblaydi; "count" dan boshqa asoslarda quantity = 0 qo'y.
   "count" materiallar uchun sonini berilgan devor/pol maydonidan me'yor bo'yicha hisobla: kafel kleyi 5 kg/m² (25 kg qop),
   shpaklyovka 1,2 kg/m² (20 kg qop), devor bo'yog'i 0,15 l/m² × 2 qatlam (10 l chelak), gruntovka 0,1 l/m² (10 l),
   flizelin oboi — 1 rulon ≈ 5 m² devor.
3. Foydalanuvchi so'rovini aniq bajar: nima so'rasa shuni tanla, so'ramagan toifalarni qo'shma.
   So'rov bo'sh bo'lsa — xonaning turiga mos to'liq jihozlash (pardozlash, mebel, texnika, yoritish).
4. Mebel va texnika xonaning maydoniga sig'sin. Rasmda allaqachon bor va yaroqli narsalarni takrorlama.
5. Byudjet darajasiga mos sifatdagi (economy / standard / premium) variantni tanla; mos variant bo'lmasa, eng yaqinini ol.
6. Kerakli narsa katalogda umuman bo'lmasa — uni missing ro'yxatiga yoz (nom, toifa, birlik, taxminiy soni). Katalogdagi boshqa narsani uning o'rniga ishlatma.
7. placement — narsa xonaning qayeriga qo'yilishi (rasmga qarab: "deraza yonida", "chap devor bo'ylab" va h.k.); reason — nega aynan shu.
8. summary — xona holati va umumiy g'oya (2–3 gap). layout — joylashtirish rejasi, qisqa va aniq.
9. Rasmda xona bo'lmasa (odam, hujjat va h.k.) isRoomPhoto = false, items va missing bo'sh.
Barcha matnlar o'zbek tilida (lotin alifbosi), oddiy va qisqa."""


def _user_text(design: RoomDesign, geo: dict) -> str:
    wishes = design.wishes.strip() or "Maxsus so'rov yo'q — xonani to'liq jihozlab ber."
    return (
        f"Xona turi: {ROOM_TYPE_LABELS.get(design.room_type, design.room_type)}\n"
        f"Pol maydoni (aniq, o'zgartirilmaydi): {geo['area']} m²\n"
        f"Ship balandligi: {geo['height']} m\n"
        f"Hisoblangan perimetr: {geo['perimeter']} m, devor maydoni (eshik va deraza chegirilgan): {geo['wallArea']} m²\n"
        f"Byudjet: {QUALITY_LABELS.get(design.budget, design.budget)} ({design.budget})\n"
        f"Hudud: {get_region(design.region).name}\n\n"
        f"Foydalanuvchi so'rovi:\n{wishes}"
        f"{_variant_text(design)}"
    )


def _variant_text(design: RoomDesign) -> str:
    """Boshqa variant so'ralganda: oldingi variantlarda tanlangan narsalar — AI boshqacha tanlasin."""
    if design.variant <= 1:
        return ""
    root_id = design.variant_of_id or design.id
    siblings = RoomDesign.objects.filter(Q(id=root_id) | Q(variant_of_id=root_id), status="done").exclude(id=design.id)
    used = []
    for other in siblings:
        for group in (other.plan or {}).get("groups", []):
            used += [item["name"] for item in group.get("items", [])]
    used = list(dict.fromkeys(used))[:120]
    listed = "\n".join(f"- {name}" for name in used) or "- (ma'lumot yo'q)"
    return (
        f"\n\nBu shu xona uchun {design.variant}-variant. Foydalanuvchiga oldingi variant(lar) yoqmadi.\n"
        f"Oldingi variantlarda tanlangan narsalar:\n{listed}\n"
        "Boshqacha uslub va kayfiyat tanla: iloji boricha boshqa mebel, rang, pol va devor materiallari, boshqa joylashtirish. "
        "Faqat katalogda mos boshqa variant bo'lmasa, oldingisini takrorlash mumkin. So'rov va byudjet talablari o'zgarmaydi."
    )


# ============================ Bajarish ============================

_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic(timeout=180.0, max_retries=2)
    return _client


def ask_claude(image: bytes, media_type: str, user_text: str) -> DesignPlan:
    response = _get_client().beta.messages.parse(
        model=MODEL,
        max_tokens=16000,
        # Rad etilgan so'rovni server avtomatik mos zaxira modelda qayta bajaradi
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        thinking={"type": "adaptive"},
        output_config={"effort": "medium"},
        output_format=DesignPlan,
        system=[
            {"type": "text", "text": SYSTEM_PROMPT},
            # Katalog o'zgarmaguncha keshdan o'qiladi (arzonroq va tezroq)
            {"type": "text", "text": f"KATALOG:\n{catalog_for_prompt()}", "cache_control": {"type": "ephemeral"}},
        ],
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": base64.b64encode(image).decode()}},
                    {"type": "text", "text": user_text},
                ],
            }
        ],
    )
    if response.stop_reason == "refusal":
        raise DesignError("Bu rasmni tahlil qilib bo'lmadi. Boshqa rasm yuklang")
    if response.stop_reason == "max_tokens" or response.parsed_output is None:
        raise DesignError("AI javobi to'liq kelmadi. Qayta urinib ko'ring")
    return response.parsed_output


class DesignError(Exception):
    pass


def design_ai_enabled() -> bool:
    return gemini_enabled() or claude_enabled()


def design_ai_provider() -> str | None:
    return "Google Gemini (bepul)" if gemini_enabled() else "Claude" if claude_enabled() else None


def _enum(values):
    return {"type": "STRING", "enum": list(values)}


def _obj(properties: dict) -> dict:
    return {"type": "OBJECT", "properties": properties, "required": list(properties), "propertyOrdering": list(properties)}


# Gemini "responseSchema" (OpenAPI qism-to'plami) — DesignPlan bilan bir xil tuzilma
GEMINI_SCHEMA = _obj(
    {
        "isRoomPhoto": {"type": "BOOLEAN"},
        "roomType": _enum(["living", "bedroom", "kitchen", "bathroom", "children", "hallway", "office", "other"]),
        "condition": _enum(["karobka", "worn", "cosmetic", "good"]),
        "summary": {"type": "STRING"},
        "layout": {"type": "STRING"},
        "items": {
            "type": "ARRAY",
            "items": _obj(
                {
                    "catalogId": {"type": "INTEGER"},
                    "catalogName": {"type": "STRING"},
                    "basis": _enum(["floor", "wall", "ceiling", "perimeter", "count"]),
                    "quantity": {"type": "NUMBER"},
                    "placement": {"type": "STRING"},
                    "reason": {"type": "STRING"},
                }
            ),
        },
        "missing": {
            "type": "ARRAY",
            "items": _obj(
                {
                    "name": {"type": "STRING"},
                    "category": _enum(["material", "mebel", "texnika", "santexnika", "yoritish", "dekor", "ish"]),
                    "unit": {"type": "STRING"},
                    "quantity": {"type": "NUMBER"},
                    "reason": {"type": "STRING"},
                }
            ),
        },
        "notes": {"type": "ARRAY", "items": {"type": "STRING"}},
    }
)


def ask_gemini(image: bytes, media_type: str, user_text: str) -> DesignPlan:
    ok, result = gemini_json(
        f"{SYSTEM_PROMPT}\n\nKATALOG:\n{catalog_for_prompt()}",
        [image_part(image, media_type), {"text": user_text}],
        GEMINI_SCHEMA,
        timeout=60,
    )
    if not ok:
        raise DesignError(result)
    try:
        return DesignPlan.model_validate(result)
    except ValueError as error:
        log.error("[design:gemini] sxemaga mos emas: %s", error)
        raise DesignError("AI javobini o'qib bo'lmadi. Qayta urinib ko'ring") from error


def ask_ai(image: bytes, media_type: str, user_text: str) -> DesignPlan:
    """Bepul Gemini ustuvor; kaliti bo'lmasa — Claude."""
    if gemini_enabled():
        return ask_gemini(image, media_type, user_text)
    return ask_claude(image, media_type, user_text)


def _norm(name: str) -> str:
    return " ".join(name.lower().replace("ʻ", "'").replace("‘", "'").replace("’", "'").split())


def resolve_item(choice: PlanItem, catalog: dict, by_name: dict) -> CatalogItem | None:
    """id va nom mos kelsa — shu mahsulot; id adashgan bo'lsa — nom bo'yicha; ikkalasi ham topilmasa — None."""
    name = _norm(choice.catalogName)
    item = catalog.get(choice.catalogId)
    if item is not None and (not name or _norm(item.name) == name):
        return item
    if name in by_name:
        return by_name[name]
    # Nom biroz boshqacha yozilgan bo'lsa: id'dagi mahsulot nomi AI nomi bilan bir-birining ichida bo'lsa qabul qilamiz
    if item is not None and name and (name in _norm(item.name) or _norm(item.name) in name):
        return item
    return None


def build_plan(ai: DesignPlan, geo: dict) -> dict:
    """AI tanlovini katalog narxlari va kiritilgan o'lchamlar bilan hisob-kitobga aylantiradi."""
    catalog = CatalogItem.objects.in_bulk([i.catalogId for i in ai.items])
    by_name = {_norm(c.name): c for c in CatalogItem.objects.all()}
    items, used = [], []
    for choice in ai.items:
        item = resolve_item(choice, catalog, by_name)
        if item is None:
            log.warning("[design] katalogda topilmadi: %s (%s)", choice.catalogName, choice.catalogId)
            continue
        qty = compute_quantity(choice.basis, choice.quantity, item, geo)
        if qty <= 0:
            continue
        row = plan_row(item, qty, placement=choice.placement, reason=choice.reason)
        row.update(basis=choice.basis, basisLabel=BASIS_LABELS[choice.basis])
        items.append(row)
        used.append(item.id)
    CatalogItem.objects.filter(id__in=used).update(times_used=F("times_used") + 1)

    for missing in ai.missing[:15]:
        record_missing(name=missing.name, category=missing.category, unit=missing.unit)

    groups = group_rows(items)

    return {
        "summary": ai.summary[:800],
        "layout": ai.layout[:1500],
        "roomType": ai.roomType,
        "condition": ai.condition,
        "notes": [n[:200] for n in ai.notes[:8]],
        "geometry": geo,
        "groups": groups,
        "missing": [m.model_dump() for m in ai.missing[:15]],
        "total": sum(i["total"] for i in items),
        "hasUnverified": any(not i["verified"] for i in items),
    }


def run_design(design_id: int) -> None:
    """Fon oqimida bajariladi: natija yoki xato RoomDesign'ga yoziladi."""
    design = RoomDesign.objects.filter(id=design_id, status="processing").first()
    if not design:
        return
    try:
        if not design_ai_enabled():
            raise DesignError("AI ulanmagan: GEMINI_API_KEY (bepul) yoki ANTHROPIC_API_KEY sozlanmagan")
        path = upload_dir() / design.photo
        ext = design.photo.rsplit(".", 1)[-1]
        geo = room_geometry(design.area, design.height)
        ai = ask_ai(path.read_bytes(), CONTENT_TYPES[ext], _user_text(design, geo))
        if not ai.isRoomPhoto:
            raise DesignError("Rasmda xona aniqlanmadi. Xonaning umumiy ko'rinishini suratga olib, qayta yuklang")
        plan = build_plan(ai, geo)
        if not plan["groups"]:
            raise DesignError("So'rovingizga mos narsa katalogda topilmadi. So'rovni boshqacha yozib ko'ring")
        # Har bir narsaning aniq ko'rinishi (parda, eshik, divan ... 100+ variantdan) — AI xonaga mosini tanlaydi
        plan = style_plan(design, plan, use_ai=True)
        design.plan_json = json.dumps(plan, ensure_ascii=False)
        design.total = plan["total"]
        design.status = "done"
    except DesignError as error:
        design.status, design.error = "failed", str(error)
    except Exception as error:
        design.status, design.error = "failed", _friendly_error(error)
        log.exception("[design] xato")
    design.finished_at = timezone.now()
    design.save(update_fields=["plan_json", "total", "status", "error", "finished_at"])


def _friendly_error(error: Exception) -> str:
    try:
        import anthropic
    except ImportError:
        return "AI xizmati vaqtincha ishlamayapti"
    if isinstance(error, anthropic.RateLimitError):
        return "AI xizmati band. Bir daqiqadan keyin qayta urinib ko'ring"
    if isinstance(error, anthropic.AuthenticationError):
        return "AI kaliti noto'g'ri (ANTHROPIC_API_KEY). Administratorga murojaat qiling"
    if isinstance(error, anthropic.BadRequestError) and "credit balance" in str(error.message).lower():
        return "AI xizmati hisobida mablag' tugagan. Administrator Anthropic balansini to'ldirishi kerak"
    if isinstance(error, anthropic.APIConnectionError):
        return "AI xizmatiga ulanib bo'lmadi. Qayta urinib ko'ring"
    return "AI xizmati vaqtincha ishlamayapti"
