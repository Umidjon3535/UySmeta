"""
Formalar uchun umumiy holat (asl versiyadagi FormState):
  {"ok": bool, "message": str, "errors": {maydon: xato}, "values": {maydon: qiymat}, "data": {...}}
View xatoli POST'da sahifani shu holat bilan qayta chizadi, muvaffaqiyatda esa redirect qiladi.
"""

SKIP_VALUES = {"password", "passwordConfirm", "currentPassword", "photo", "csrfmiddlewaretoken", "_action"}


def state(ok=None, message=None, errors=None, values=None, data=None) -> dict:
    return {"ok": ok, "message": message, "errors": errors or {}, "values": values or {}, "data": data or {}}


EMPTY = state()


def text(post, key: str) -> str:
    return str(post.get(key, "") or "").strip()


def form_values(post, skip=SKIP_VALUES) -> dict:
    """Formadagi matn qiymatlarini qayta to'ldirish uchun (parol va fayllardan tashqari)."""
    return {key: post.get(key) for key in post.keys() if key not in skip}
