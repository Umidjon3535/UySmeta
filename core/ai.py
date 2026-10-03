"""
Xona rasmini AI bilan tahlil qilish. Provayder kalitga qarab tanlanadi:
 - GEMINI_API_KEY — Google Gemini (bepul tarif mavjud), ustuvor;
 - ANTHROPIC_API_KEY — Claude (pullik).
Hech biri berilmagan bo'lsa funksiya o'chiq (ai_enabled() = False) va UI tugmani ko'rsatmaydi.
"""

import base64
import logging
import os

from .ai_gemini import analyze_with_gemini, gemini_enabled
from .room_analysis import RoomAnalysis

log = logging.getLogger("uysmeta.ai")

MODEL = "claude-opus-5"

SYSTEM_PROMPT = """Sen O'zbekistondagi ta'mirlash smetasi xizmati UySmeta uchun xona rasmlarini baholaydigan tajribali prorab-smetachisan.
Foydalanuvchi ta'mir qilmoqchi bo'lgan xona rasmini yuboradi. Rasmda ko'ringan narsalarga asoslanib baho ber:
- xona turi (vannaxona, oshxona, yashash xonasi yoki boshqa);
- holati: "karobka" (qurilishdan keyin bo'sh beton/suvoq, ta'mirsiz), eskirgan (to'liq ta'mir kerak), kosmetik ta'mir yetarli, yoki yaxshi holatda;
- ko'ringan muammolar (namlik, yoriqlar, notekis devor, eski quvurlar va h.k.) — faqat rasmda haqiqatan ko'ringanlarini yoz;
- amaliy tavsiyalar (3–5 ta, qisqa);
- tavsiya etiladigan sifat darajasi: economy, standard yoki premium — xona holati va ko'rinishiga qarab.
Agar pol maydonini rasmdan ishonchli taxmin qila olmasang, estimatedFloorArea ni null qoldir.
Rasmda xona bo'lmasa (odam, hujjat, boshqa narsa), isRoomPhoto = false qilib, qolgan maydonlarni minimal to'ldir.
Barcha matnlarni o'zbek tilida (lotin alifbosi), oddiy va qisqa yoz."""


def claude_enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def ai_enabled() -> bool:
    return gemini_enabled() or claude_enabled()


def ai_provider_name() -> str | None:
    if gemini_enabled():
        return "Google Gemini"
    if claude_enabled():
        return "Claude"
    return None


_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic(timeout=90.0, max_retries=2)
    return _client


def analyze_room_photo(image: bytes, media_type: str) -> dict:
    """{"ok": True, "analysis": dict} yoki {"ok": False, "error": str}."""
    if gemini_enabled():
        return analyze_with_gemini(image, media_type, SYSTEM_PROMPT)
    if not claude_enabled():
        return {"ok": False, "error": "AI tahlil hozircha yoqilmagan"}

    import anthropic

    try:
        response = _get_client().beta.messages.parse(
            model=MODEL,
            max_tokens=16000,
            # Rad etilgan so'rovni server avtomatik mos zaxira modelda qayta bajaradi
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            output_format=RoomAnalysis,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": media_type, "data": base64.b64encode(image).decode()},
                        },
                        {"type": "text", "text": "Mana ta'mir qilinadigan xona rasmi. Baholab ber."},
                    ],
                }
            ],
        )
    except anthropic.RateLimitError:
        return {"ok": False, "error": "AI xizmati band. Bir daqiqadan keyin urinib ko'ring"}
    except anthropic.AuthenticationError:
        log.error("[ai] ANTHROPIC_API_KEY noto'g'ri")
        return {"ok": False, "error": "AI xizmati vaqtincha ishlamayapti"}
    except anthropic.BadRequestError as error:
        log.error("[ai] so'rov xatosi: %s", error.message)
        return {"ok": False, "error": "Rasmni tahlil qilib bo'lmadi. Boshqa rasm yuklang"}
    except anthropic.APIStatusError as error:
        log.error("[ai] API xatosi %s: %s", error.status_code, error.message)
        return {"ok": False, "error": "AI xizmati vaqtincha ishlamayapti"}
    except anthropic.APIConnectionError:
        log.exception("[ai] ulanish xatosi")
        return {"ok": False, "error": "AI xizmatiga ulanib bo'lmadi"}
    except Exception:
        log.exception("[ai]")
        return {"ok": False, "error": "AI javobini o'qib bo'lmadi. Qayta urinib ko'ring"}

    if response.stop_reason == "refusal":
        return {"ok": False, "error": "Bu rasmni tahlil qilib bo'lmadi. Boshqa rasm yuklang"}
    if response.stop_reason == "max_tokens" or response.parsed_output is None:
        return {"ok": False, "error": "AI javobi to'liq kelmadi. Qayta urinib ko'ring"}
    return {"ok": True, "analysis": response.parsed_output.model_dump()}
