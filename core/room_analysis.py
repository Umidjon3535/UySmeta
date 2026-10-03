"""AI rasm tahlili natijasi sxemasi (Claude va Gemini uchun umumiy)."""

from typing import Literal

from pydantic import BaseModel, ValidationError


class RoomAnalysis(BaseModel):
    isRoomPhoto: bool
    roomType: Literal["bathroom", "kitchen", "living", "other"]
    condition: Literal["karobka", "worn", "cosmetic", "good"]
    estimatedFloorArea: float | None
    visibleIssues: list[str]
    recommendations: list[str]
    suggestedQuality: Literal["economy", "standard", "premium"]
    summary: str


CONDITION_LABELS = {
    "karobka": "Karobka (ta'mirsiz)",
    "worn": "Eskirgan — to'liq ta'mir kerak",
    "cosmetic": "Kosmetik ta'mir yetarli",
    "good": "Yaxshi holatda",
}


def sanitize_analysis(value) -> dict | None:
    """Bazaga yozishdan oldin: sxemaga mos va uzunliklari cheklangan bo'lsin."""
    try:
        a = RoomAnalysis.model_validate(value)
    except ValidationError:
        return None
    area = a.estimatedFloorArea
    return {
        **a.model_dump(),
        "estimatedFloorArea": area if area and 0 < area < 1000 else None,
        "visibleIssues": [s[:200] for s in a.visibleIssues[:8]],
        "recommendations": [s[:200] for s in a.recommendations[:8]],
        "summary": a.summary[:600],
    }
