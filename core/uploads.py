"""
Xona rasmlari va to'lov cheklarini diskka saqlash. Fayl turi kengaytmaga emas, fayl ichidagi "sehrli baytlar"ga qarab aniqlanadi.
Papka: UPLOAD_DIR yoki ./data/uploads (static ichida emas — faqat /api/uploads/<nom> orqali beriladi).
Eski (Vercel Blob) yozuvlari — to'liq https URL — o'zgarishsiz ko'rsatiladi.
"""

import re
import secrets
from pathlib import Path

from django.conf import settings

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
UPLOAD_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,40}\.(jpg|png|webp)$")

CONTENT_TYPES = {
    "jpg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}


def upload_dir() -> Path:
    return Path(settings.UPLOAD_DIR)


def detect_image_type(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:4] == b"\x89PNG":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


class ImageError(Exception):
    pass


def read_image(file) -> tuple[bytes, str] | None:
    """Formadagi faylni o'qib, hajmi va haqiqiy turini tekshiradi. Fayl yo'q bo'lsa None, xato bo'lsa ImageError."""
    if not file or not getattr(file, "size", 0):
        return None
    if file.size > MAX_UPLOAD_BYTES:
        raise ImageError("Rasm hajmi 5 MB dan oshmasin")
    data = file.read()
    kind = detect_image_type(data)
    if not kind:
        raise ImageError("Faqat JPG, PNG yoki WEBP rasm yuklang")
    return data, kind


def save_image(file) -> str | None:
    """Rasmni saqlab, bazaga yoziladigan fayl nomini qaytaradi. Fayl bo'sh bo'lsa None (rasm ixtiyoriy)."""
    image = read_image(file)
    if image is None:
        return None
    data, kind = image
    name = f"{secrets.token_urlsafe(12)}.{kind}"
    folder = upload_dir()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(data)
    return name


def delete_image(name: str | None) -> None:
    if not name or not UPLOAD_NAME_PATTERN.match(name):
        return  # eski Blob URL'lar yoki noto'g'ri nom — diskda o'chiriladigan narsa yo'q
    (upload_dir() / name).unlink(missing_ok=True)


# ---------------- Hujjatlar (usta portfoliosi: PDF / DOCX) ----------------
# Ommaga ochiq emas: data/uploads/docs ichida, faqat administrator /admin/hujjat/<nom> orqali yuklab oladi.

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
DOCUMENT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,40}\.(pdf|docx)$")
DOCUMENT_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def document_dir() -> Path:
    return upload_dir() / "docs"


def detect_document_type(data: bytes) -> str | None:
    if data[:5] == b"%PDF-":
        return "pdf"
    # DOCX — ZIP arxiv, ichida word/ papkasi bor (fayl nomlari arxivda ochiq yoziladi)
    if data[:4] == b"PK\x03\x04" and b"word/" in data:
        return "docx"
    return None


def save_document(file) -> tuple[str, str] | None:
    """(saqlangan nom, asl fayl nomi). Fayl yo'q bo'lsa None, noto'g'ri bo'lsa ImageError."""
    if not file or not getattr(file, "size", 0):
        return None
    if file.size > MAX_DOCUMENT_BYTES:
        raise ImageError("Hujjat hajmi 10 MB dan oshmasin")
    data = file.read()
    kind = detect_document_type(data)
    if not kind:
        raise ImageError("Faqat PDF yoki Word (DOCX) fayl yuklang")
    name = f"{secrets.token_urlsafe(12)}.{kind}"
    folder = document_dir()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(data)
    original = Path(getattr(file, "name", "") or f"portfolio.{kind}").name[:120]
    return name, original


def delete_document(name: str | None) -> None:
    if name and DOCUMENT_NAME_PATTERN.match(name):
        (document_dir() / name).unlink(missing_ok=True)


def photo_url(photo: str) -> str:
    """Bazadagi qiymatdan brauzer uchun manzil."""
    return photo if photo.startswith("https://") else f"/api/uploads/{photo}"
