"""
PDF hujjatlar ("PDF smeta" va "3D dizayn" tariflari): batafsil smeta, bosqichma-bosqich ish rejasi, to'liq materiallar ro'yxati.
reportlab + DejaVu shrifti (o'zbek lotin harflari: o', g', sh ... to'g'ri chiqadi).
"""

import io
from functools import lru_cache

from django.conf import settings
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .catalog import DATA_DIR
from .constants import format_date
from .estimate import QUALITY_LABELS, describe_room, format_money, format_qty
from .planner import evaluate, load_rooms, room_variables
from .regions import get_region
from .uploads import upload_dir

ACCENT = colors.HexColor("#0e7490")
MUTED = colors.HexColor("#6b7280")
LINE = colors.HexColor("#e5e7eb")
SOFT = colors.HexColor("#e8f1fc")


@lru_cache(maxsize=1)
def _fonts() -> tuple[str, str]:
    pdfmetrics.registerFont(TTFont("DejaVu", str(DATA_DIR / "fonts" / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(DATA_DIR / "fonts" / "DejaVuSans-Bold.ttf")))
    return "DejaVu", "DejaVu-Bold"


def _styles() -> dict:
    regular, bold = _fonts()
    return {
        "brand": ParagraphStyle("brand", fontName=bold, fontSize=15, textColor=ACCENT),
        "title": ParagraphStyle("title", fontName=bold, fontSize=18, leading=22, spaceBefore=4, spaceAfter=4),
        "h2": ParagraphStyle("h2", fontName=bold, fontSize=12.5, leading=16, spaceBefore=12, spaceAfter=6),
        "body": ParagraphStyle("body", fontName=regular, fontSize=9.5, leading=13),
        "muted": ParagraphStyle("muted", fontName=regular, fontSize=8.5, leading=11, textColor=MUTED),
        "cell": ParagraphStyle("cell", fontName=regular, fontSize=8.5, leading=11),
        "cellb": ParagraphStyle("cellb", fontName=bold, fontSize=8.5, leading=11),
        "num": ParagraphStyle("num", fontName=regular, fontSize=8.5, leading=11, alignment=TA_RIGHT),
        "numb": ParagraphStyle("numb", fontName=bold, fontSize=9.5, leading=12, alignment=TA_RIGHT),
        "total": ParagraphStyle("total", fontName=bold, fontSize=13, leading=16, textColor=ACCENT, alignment=TA_RIGHT),
    }


def _money(value) -> str:
    # Uzilmas bo'shliq qoldiriladi — summa jadvalda ikki qatorga bo'linmaydi
    return format_money(value)


def _table(rows: list[list], widths: list[float], header: bool = True) -> Table:
    table = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), SOFT)]
    table.setStyle(TableStyle(style))
    return table


def _header(story: list, s: dict, title: str, subtitle: str):
    story.append(Paragraph("UySmeta", s["brand"]))
    story.append(Paragraph(title, s["title"]))
    story.append(Paragraph(subtitle, s["muted"]))
    story.append(Spacer(1, 4 * mm))


def _stages(story: list, s: dict, groups: list[str], variables: dict):
    """Bosqichma-bosqich ish rejasi: faqat loyihada bor bo'limlar, to'g'ri tartibda."""
    rows = [[Paragraph("№", s["cellb"]), Paragraph("Bosqich", s["cellb"]), Paragraph("Nima qilinadi", s["cellb"]), Paragraph("Muddat", s["cellb"])]]
    total_days = 0
    number = 0
    for stage in load_rooms()["stages"]:
        if stage["group"] not in groups:
            continue
        days = max(1, int(evaluate(stage["days"], variables)))
        total_days += days
        number += 1
        rows.append([
            Paragraph(str(number), s["cell"]),
            Paragraph(stage["title"], s["cellb"]),
            Paragraph(stage["text"], s["cell"]),
            Paragraph(f"~{days} kun", s["num"]),
        ])
    if number == 0:
        return
    story.append(Paragraph("Bosqichma-bosqich ish rejasi", s["h2"]))
    story.append(_table(rows, [10 * mm, 38 * mm, 100 * mm, 22 * mm]))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(f"Taxminiy umumiy muddat: {total_days} ish kuni (ba'zi ishlar parallel bajarilsa qisqaradi).", s["muted"]))


def _footer(canvas, doc):
    regular, _ = _fonts()
    canvas.saveState()
    canvas.setFont(regular, 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 10 * mm, f"UySmeta · {settings.SITE_URL.split('://', 1)[-1]} · Narxlar taxminiy, real narx ±10% farq qilishi mumkin")
    canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"{doc.page}-bet")
    canvas.restoreState()


def _photo_flowable(path, width=80 * mm):
    """Rasmni Pillow bilan tekshirib JPEG'ga o'giradi (WEBP va buzilgan fayllar ham PDF'ni to'xtatmasin)."""
    if not path.is_file():
        return None
    try:
        from PIL import Image as PILImage

        with PILImage.open(path) as source:
            source.load()
            rgb = source.convert("RGB")
            rgb.thumbnail((1200, 1200))
            data = io.BytesIO()
            rgb.save(data, "JPEG", quality=82)
            data.seek(0)
            ratio = rgb.height / rgb.width
        return Image(data, width=width, height=width * ratio)
    except Exception:
        return None  # rasm o'qilmasa hujjat rasmsiz chiqadi


def _build(story: list) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm, title="UySmeta")
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()


# ============================ Smeta ============================

ESTIMATE_GROUPS = {
    "bathroom": ["elektr", "santexnika", "devor", "pol"],
    "kitchen": ["elektr", "devor", "pol"],
    "living": ["elektr", "devor", "ship", "pol"],
    "apartment": ["elektr", "santexnika", "devor", "ship", "pol", "eshik"],
}


def estimate_pdf(estimate) -> bytes:
    s = _styles()
    r = estimate.result
    story: list = []
    _header(
        story,
        s,
        estimate.title or "Ta'mirlash smetasi",
        f"{describe_room(r)} · Sifat: {QUALITY_LABELS[r['quality']]} · {get_region(estimate.region).name} narxlarida · {format_date(estimate.created_at)}",
    )

    def lines(title: str, rows_data: list, total: int, total_label: str):
        story.append(Paragraph(title, s["h2"]))
        rows = [[Paragraph("Nomi", s["cellb"]), Paragraph("Miqdori", s["cellb"]), Paragraph("Narxi", s["cellb"])]]
        for row in rows_data:
            rows.append([Paragraph(row["name"], s["cell"]), Paragraph(format_qty(row["qty"], row["unit"]).replace(" ", " "), s["cell"]), Paragraph(_money(row["cost"]), s["num"])])
        rows.append([Paragraph(total_label, s["cellb"]), "", Paragraph(_money(total), s["numb"])])
        story.append(_table(rows, [100 * mm, 35 * mm, 39 * mm]))

    lines("To'liq materiallar ro'yxati", r["materials"], r["materialsTotal"], "Materiallar jami")
    lines("Usta ish haqi", r["labor"], r["laborTotal"], "Ish haqi jami")
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(f"TAXMINIY JAMI: {_money(r['total'])}", s["total"]))
    story.append(Paragraph(f"Muddat: {r['duration']}", s["muted"]))

    area = r["floorArea"] or r["dimensions"].get("area") or 10
    variables = {"floor": area, "wall": r["wallArea"] or area * 2.5}
    _stages(story, s, ESTIMATE_GROUPS.get(r["roomType"], ESTIMATE_GROUPS["apartment"]), variables)
    return _build(story)


# ============================ Jihozlash loyihasi ============================


def design_pdf(design, *, with_tips: bool) -> bytes:
    s = _styles()
    plan = design.plan
    room = load_rooms()["rooms"].get(design.room_type, {})
    story: list = []
    _header(
        story,
        s,
        f"Jihozlash loyihasi — {room.get('label', 'xona')}",
        f"Pol {design.area:g} m² · Ship {design.height:g} m · Derazalar {design.windows} · Eshiklar {design.doors} · "
        f"{QUALITY_LABELS.get(design.budget, design.budget)} byudjet · {get_region(design.region).name} · {format_date(design.created_at)}",
    )

    image = _photo_flowable(upload_dir() / design.photo)
    if image is not None:
        story.append(image)
        story.append(Spacer(1, 3 * mm))

    story.append(Paragraph(plan["summary"], s["body"]))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(f"<b>Joylashtirish:</b> {plan['layout']}", s["body"]))

    for group in plan["groups"]:
        rows = [[Paragraph(h, s["cellb"]) for h in ("Nomi", "Soni", "Narxi", "Jami", "Qayerga")]]
        for item in group["items"]:
            rows.append([
                Paragraph(item["name"], s["cell"]),
                Paragraph(f"{item['quantity']:g} {item['unit']}", s["cell"]),
                Paragraph(_money(item["unitPrice"]), s["num"]),
                Paragraph(_money(item["total"]), s["num"]),
                Paragraph(item.get("placement", ""), s["muted"]),
            ])
        # Guruh jami "Narxi"dan "Qayerga"gacha yoyiladi — katta summa bo'linib ketmasin
        rows.append([Paragraph(f"{group['label']} jami", s["cellb"]), "", Paragraph(_money(group["total"]), s["numb"]), "", ""])
        table = _table(rows, [50 * mm, 19 * mm, 29 * mm, 33 * mm, 43 * mm])
        table.setStyle(TableStyle([("SPAN", (2, -1), (4, -1))]))
        story.append(KeepTogether([Paragraph(group["label"], s["h2"]), table]))

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(f"UMUMIY JAMI: {_money(plan['total'])}", s["total"]))

    variables = room_variables(design.area, design.height, design.windows, design.doors)
    groups = [g for g in (design.groups.split(",") if design.groups else []) if g] or sorted({i.get("group") for g in plan["groups"] for i in g["items"]} - {None, ""})
    _stages(story, s, groups or [st["group"] for st in load_rooms()["stages"]], variables)

    if with_tips:
        tips = room.get("tips", []) + [load_rooms()["budget_tips"].get(design.budget, "")]
        story.append(Paragraph("Dizayner maslahatlari", s["h2"]))
        for tip in filter(None, tips):
            story.append(Paragraph(f"• {tip}", s["body"]))
    return _build(story)
