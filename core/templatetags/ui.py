"""Shablonlar uchun teglar va filtrlar (barcha shablonlarda avtomatik mavjud — settings.TEMPLATES builtins)."""

import json
import os

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe

from .. import constants, estimate
from ..icons import ICONS
from ..regions import get_region
from ..room_analysis import CONDITION_LABELS
from ..uploads import photo_url as _photo_url

register = template.Library()


# ---------------- Ikonkalar ----------------


@register.simple_tag
def icon(name, size=16, cls="", label=None, stroke=2):
    """{% icon "check" 16 "text-success" %} — lucide ikonkasi inline SVG sifatida."""
    body = ICONS.get(name)
    if body is None:
        raise template.TemplateSyntaxError(f"Ikonka topilmadi: {name}")
    a11y = f'role="img" aria-label="{escape(label)}"' if label else 'aria-hidden="true"'
    return mark_safe(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round" '
        f'class="lucide lucide-{name} {escape(cls)}" {a11y}>{body}</svg>'
    )


@register.simple_tag
def asset(path):
    """{% asset 'js/app.js' %} — static manzil + ?v=<o'zgargan vaqti>: fayl yangilansa brauzer eski keshni ishlatmaydi."""
    found = finders.find(path)
    version = int(os.path.getmtime(found)) if found else 0
    return f"{static(path)}?v={version}"


# ---------------- Formatlash ----------------


@register.filter
def money(value):
    return estimate.format_money(value or 0)


@register.filter
def number(value):
    return estimate.format_number(value or 0)


@register.filter
def qty(row):
    return estimate.format_qty(row["qty"], row["unit"])


@register.filter
def phone(value):
    return constants.format_phone(value)


@register.filter
def uzdate(value):
    return constants.format_date(value)


@register.filter
def initials(value):
    return constants.initials(value)


@register.filter
def card(value):
    return constants.format_card(value)


@register.filter
def room_label(value):
    return estimate.ROOM_LABELS.get(value, value)


@register.filter
def quality_label(value):
    return estimate.QUALITY_LABELS.get(value, value)


@register.filter
def condition_label(value):
    return CONDITION_LABELS.get(value, value)


@register.filter
def describe_room(result):
    return estimate.describe_room(result)


@register.filter
def region_name(key):
    return get_region(key).name


@register.filter
def region_short(key):
    return get_region(key).short


@register.filter
def photo_url(value):
    return _photo_url(value) if value else ""


@register.filter
def master_badge(key):
    """Usta tarifi belgisi: "Pro" / "Top usta" (bepul tarifda bo'sh)."""
    return constants.MASTER_PLANS.get(key, {}).get("badge", "")


@register.filter
def plan_title(key):
    return constants.plan_info(key)["title"] if key else ""


@register.filter
def order_status(value):
    return constants.ORDER_STATUS_LABELS.get(value, value)


@register.filter
def request_status(value):
    return constants.REQUEST_STATUS_LABELS.get(value, value)


@register.filter
def master_status(value):
    return constants.MASTER_STATUS_LABELS.get(value, value)


@register.filter
def role_label(value):
    return constants.ROLE_LABELS.get(value, value)


@register.filter
def rating(value):
    """4.8 -> "4.8"; None -> "—"."""
    return "—" if value is None else f"{float(value):.1f}"


@register.filter
def first_word(value):
    return (str(value or "").split() or [""])[0]


@register.filter
def get(mapping, key):
    """{{ state.errors|get:"phone" }}"""
    if not mapping:
        return None
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.filter
def to_json(value):
    return json.dumps(value, ensure_ascii=False)


@register.filter
def status_badge(value):
    """Holat bo'yicha badge rangi (profil sahifasi)."""
    if value in ("done", "paid", "approved"):
        return "badge-success"
    if value in ("cancelled", "rejected"):
        return "badge-danger"
    if value in ("new", "pending"):
        return "badge-warning"
    return "badge-muted"


# ---------------- Forma maydonlari ----------------


def _attrs(extra: dict) -> str:
    parts = []
    for key, value in extra.items():
        if value is None or value is False:
            continue
        name = key.replace("_", "-") if key.startswith(("aria_", "data_")) else key
        parts.append(name if value is True else format_html('{}="{}"', name, value))
    return mark_safe(" ".join(parts))


@register.inclusion_tag("includes/field.html")
def field(state, name, label, type="text", value=None, hint=None, prefix="", **extra):
    """{% field state "name" "Ismingiz" autocomplete="name" %} — label + input + xato matni.
    prefix — bitta sahifada bir xil forma ikki marta bo'lsa, id'lar takrorlanmasin."""
    values = (state or {}).get("values") or {}
    error = ((state or {}).get("errors") or {}).get(name)
    shown = values.get(name, value) if type != "password" else None
    return {
        "id": f"{prefix}f-{name}",
        "name": name,
        "label": label,
        "type": type,
        "value": "" if shown is None else shown,
        "hint": hint,
        "error": error,
        "attrs": _attrs(extra),
    }


@register.inclusion_tag("includes/phone_field.html")
def phone_field(state, value=None, label="Telefon raqam", hint=None, required=True, prefix=""):
    values = (state or {}).get("values") or {}
    raw = values.get("phone", value) or ""
    return {
        "id": f"{prefix}f-phone",
        "label": label,
        "value": raw.removeprefix("+998"),
        "error": ((state or {}).get("errors") or {}).get("phone"),
        "hint": hint,
        "required": required,
        "codes": ",".join(constants.PHONE_CODES),
    }


@register.inclusion_tag("includes/select_field.html")
def select_field(state, name, label, options, value=None, placeholder="Tanlang"):
    values = (state or {}).get("values") or {}
    return {
        "id": f"f-{name}",
        "name": name,
        "label": label,
        "options": options,
        "value": values.get(name, value) or "",
        "placeholder": placeholder,
        "error": ((state or {}).get("errors") or {}).get(name),
    }


@register.inclusion_tag("includes/textarea_field.html")
def textarea_field(state, name, label, value=None, **extra):
    values = (state or {}).get("values") or {}
    return {
        "id": f"f-{name}",
        "name": name,
        "label": label,
        "value": values.get(name, value) or "",
        "error": ((state or {}).get("errors") or {}).get(name),
        "attrs": _attrs(extra),
    }


@register.inclusion_tag("includes/form_message.html")
def form_message(state):
    return {"state": state or {}}
