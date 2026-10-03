"""
Google Gemini orqali xona rasmini tahlil qilish (REST API).
Kalit: https://aistudio.google.com/apikey — bepul tarif (kunlik cheklov bilan).
GEMINI_MODEL bilan modelni almashtirish mumkin.
"""

import base64
import json
import logging
import os
import re
import time

import requests
from pydantic import ValidationError

from .room_analysis import RoomAnalysis

log = logging.getLogger("uysmeta.ai")


STUDIO_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
VERTEX_URL = "https://aiplatform.googleapis.com/v1/publishers/google/models/{model}:generateContent"


def gemini_urls(model: str) -> list[str]:
    """
    Qaysi manzil(lar)ga so'rov yuboriladi. GEMINI_BACKEND: auto (sukut) | vertex | studio.
    auto: "AQ." bilan boshlanadigan kalit — Google Cloud (Vertex AI) kaliti: avval Cloud, keyin AI Studio.
    """
    backend = os.environ.get("GEMINI_BACKEND", "auto").lower()
    vertex = backend == "vertex" or (backend == "auto" and os.environ.get("GEMINI_API_KEY", "").startswith("AQ."))
    urls = [VERTEX_URL.format(model=model)] if vertex else []
    if backend != "vertex":
        urls.append(STUDIO_URL.format(model=model))
    return urls


def gemini_enabled() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


# Oxirgi ishlagan model birinchi sinaladi; yaqinda band bo'lgan modellar bir necha daqiqa o'tkazib yuboriladi
_last_ok: str | None = None
_busy_until: dict[str, float] = {}
BUSY_PAUSE = 180  # soniya


def _models() -> list[str]:
    """Asosiy model band yoki limit tugagan bo'lsa (404/429/5xx), keyingisi sinab ko'riladi (bepul tarifda tez-tez bo'ladi)."""
    preferred = os.environ.get("GEMINI_MODEL") or "gemini-3.8-flash"
    order = list(dict.fromkeys([m for m in [_last_ok, preferred, "gemini-2.5-flash", "gemini-3.5-flash", "gemini-flash-latest", "gemini-3.7-flash"] if m]))
    now = time.monotonic()
    free = [m for m in order if _busy_until.get(m, 0) <= now]
    return free or order


_FIELDS = [
    "isRoomPhoto",
    "roomType",
    "condition",
    "estimatedFloorArea",
    "visibleIssues",
    "recommendations",
    "suggestedQuality",
    "summary",
]

# Gemini "responseSchema" (OpenAPI qism-to'plami) — RoomAnalysis bilan bir xil tuzilma
RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "isRoomPhoto": {"type": "BOOLEAN"},
        "roomType": {"type": "STRING", "enum": ["bathroom", "kitchen", "living", "other"]},
        "condition": {"type": "STRING", "enum": ["karobka", "worn", "cosmetic", "good"]},
        "estimatedFloorArea": {"type": "NUMBER", "nullable": True},
        "visibleIssues": {"type": "ARRAY", "items": {"type": "STRING"}},
        "recommendations": {"type": "ARRAY", "items": {"type": "STRING"}},
        "suggestedQuality": {"type": "STRING", "enum": ["economy", "standard", "premium"]},
        "summary": {"type": "STRING"},
    },
    "required": _FIELDS,
    "propertyOrdering": _FIELDS,
}


def gemini_json(system_prompt: str, parts: list, schema: dict, timeout: int = 45, models: list[str] | None = None, temperature: float = 0.2) -> tuple[bool, object]:
    """
    Gemini'dan sxemaga mos JSON olish. (True, dict) yoki (False, foydalanuvchiga ko'rsatiladigan xato).
    Asosiy model band, limit tugagan yoki topilmasa (404/429/5xx) — keyingi model sinab ko'riladi.
    """
    body = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"responseMimeType": "application/json", "responseSchema": schema, "temperature": temperature},
    }

    global _last_ok
    res = None
    data: dict = {}
    models = models or _models()
    # Hamma model band bo'lsa — biroz kutib, ro'yxatni yana bir marta aylanamiz
    for attempt, model in enumerate(models * 2):
        if attempt == len(models):
            time.sleep(4)
        try:
            res = requests.post(
                STUDIO_URL.format(model=model),
                headers={"Content-Type": "application/json", "x-goog-api-key": os.environ["GEMINI_API_KEY"]},
                json=body,
                timeout=timeout,
            )
        except requests.RequestException as error:
            log.error("[ai:gemini] %s ulanish xatosi: %s", model, error)
            _busy_until[model] = time.monotonic() + BUSY_PAUSE
            res = None
            continue
        try:
            data = res.json()
        except ValueError:
            data = {}
        if res.status_code in (404, 429) or res.status_code >= 500:
            log.warning("[ai:gemini] %s -> %s: %s", model, res.status_code, (data.get("error") or {}).get("message", ""))
            _busy_until[model] = time.monotonic() + BUSY_PAUSE
            continue
        _last_ok = model
        break

    if res is None:
        return False, "AI xizmatiga ulanib bo'lmadi. Qayta urinib ko'ring"
    error_message = (data.get("error") or {}).get("message") or ""
    if not res.ok:
        log.error("[ai:gemini] %s: %s", res.status_code, error_message)
        if res.status_code == 429:
            return False, "AI xizmatining bepul limiti tugadi. Birozdan keyin urinib ko'ring"
        if res.status_code >= 500:
            return False, "AI xizmati hozir juda band. Bir-ikki daqiqadan keyin qayta urinib ko'ring"
        if res.status_code in (400, 403) and re.search(r"api key|API_KEY", error_message, re.I):
            return False, "Gemini kaliti noto'g'ri (GEMINI_API_KEY). Administratorga murojaat qiling"
        if res.status_code == 400 and re.search(r"image|mime|inline", error_message, re.I):
            return False, "Rasmni tahlil qilib bo'lmadi. Boshqa rasm yuklang"
        return False, "AI xizmati vaqtincha ishlamayapti"
    if (data.get("promptFeedback") or {}).get("blockReason"):
        return False, "Bu rasmni tahlil qilib bo'lmadi. Boshqa rasm yuklang"

    candidate = (data.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in (candidate.get("content") or {}).get("parts") or [])
    if candidate.get("finishReason") and candidate["finishReason"] != "STOP":
        log.warning("[ai:gemini] finishReason: %s", candidate["finishReason"])
    try:
        return True, json.loads(text)
    except ValueError:
        log.error("[ai:gemini] JSON emas: %s", text[:200])
        return False, "AI javobini o'qib bo'lmadi. Qayta urinib ko'ring"


def image_part(image: bytes, media_type: str) -> dict:
    return {"inlineData": {"mimeType": media_type, "data": base64.b64encode(image).decode()}}


def analyze_with_gemini(image: bytes, media_type: str, system_prompt: str) -> dict:
    ok, result = gemini_json(
        system_prompt,
        [image_part(image, media_type), {"text": "Mana ta'mir qilinadigan xona rasmi. Baholab ber."}],
        RESPONSE_SCHEMA,
    )
    if not ok:
        return {"ok": False, "error": result}
    try:
        return {"ok": True, "analysis": RoomAnalysis.model_validate(result).model_dump()}
    except ValidationError as error:
        log.error("[ai:gemini] sxemaga mos emas: %s", error)
        return {"ok": False, "error": "AI javobini o'qib bo'lmadi. Qayta urinib ko'ring"}
