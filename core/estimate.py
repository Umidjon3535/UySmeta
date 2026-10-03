"""
Smeta hisoblash mantig'i — sof funksiyalar.
Kalkulyator jonli natijasi ham, saqlashdagi qayta hisob ham shu yerda (yagona manba).
Narxlar bazada saqlanadi va admin paneldan o'zgartiriladi; DEFAULT_PRICES — boshlang'ich qiymatlar.

Natija lug'ati kalitlari (roomType, materialsTotal ...) asl JS versiyadagidek camelCase —
bazadagi eski smetalar (result_json) bilan mos bo'lishi uchun.
"""

import copy
import math

ROOM_TYPES = ["bathroom", "kitchen", "living", "apartment"]
QUALITIES = ["economy", "standard", "premium"]

ROOM_LABELS = {
    "bathroom": "Vannaxona",
    "kitchen": "Oshxona",
    "living": "Yashash xonasi",
    "apartment": "Butun kvartira",
}

QUALITY_LABELS = {
    "economy": "Ekonom",
    "standard": "O'rta",
    "premium": "Premium",
}

DEFAULT_PRICES = {
    "quality": {
        "economy": {"material": 0.75, "labor": 0.85},
        "standard": {"material": 1.0, "labor": 1.0},
        "premium": {"material": 1.6, "labor": 1.3},
    },
    "bathroom": {
        "tilePerM2": 120_000,
        "tileAdhesiveBag": 70_000,
        "waterproofingBucket": 260_000,
        "groutKit": 250_000,
        "plumbingKit": 1_200_000,
        "laborTilePerM2": 100_000,
        "laborWaterproofing": 400_000,
        "laborPlumbing": 1_500_000,
    },
    "kitchen": {
        "apronTilePerM2": 120_000,
        "puttyBag": 90_000,
        "paintBucket": 350_000,
        "floorTilePerM2": 110_000,
        "laborPuttyPaintPerM2": 45_000,
        "laborTilePerM2": 100_000,
    },
    "living": {
        "puttyBag": 90_000,
        "paintBucket": 350_000,
        "laminatePerM2": 95_000,
        "plinthPerM": 25_000,
        "ceilingPaintBucket": 300_000,
        "laborPuttyPaintPerM2": 45_000,
        "laborLaminatePerM2": 35_000,
    },
    "apartment": {
        "materialsPerM2": 1_100_000,
        "laborPerM2": 650_000,
    },
}

# Admin panelda ko'rsatiladigan narx nomlari (tartib muhim)
PRICE_LABELS = {
    "bathroom": {
        "title": "Vannaxona",
        "fields": {
            "tilePerM2": "Kafel, so'm/m²",
            "tileAdhesiveBag": "Kafel kleyi, so'm/qop (25 kg)",
            "waterproofingBucket": "Gidroizolyatsiya, so'm/chelak (15 kg)",
            "groutKit": "Zatirka va aksessuarlar, to'plam",
            "plumbingKit": "Quvurlar va santexnika, to'plam",
            "laborTilePerM2": "Ish: kafel yotqizish, so'm/m²",
            "laborWaterproofing": "Ish: gidroizolyatsiya",
            "laborPlumbing": "Ish: santexnika o'rnatish",
        },
    },
    "kitchen": {
        "title": "Oshxona",
        "fields": {
            "apronTilePerM2": "Fartuk kafeli, so'm/m²",
            "puttyBag": "Shpaklyovka, so'm/qop (20 kg)",
            "paintBucket": "Devor bo'yog'i, so'm/chelak (10 l)",
            "floorTilePerM2": "Pol kafeli, so'm/m²",
            "laborPuttyPaintPerM2": "Ish: shpaklyovka + bo'yoq, so'm/m²",
            "laborTilePerM2": "Ish: kafel, so'm/m²",
        },
    },
    "living": {
        "title": "Yashash xonasi",
        "fields": {
            "puttyBag": "Shpaklyovka, so'm/qop (20 kg)",
            "paintBucket": "Devor bo'yog'i, so'm/chelak (10 l)",
            "laminatePerM2": "Laminat, so'm/m²",
            "plinthPerM": "Plintus, so'm/metr",
            "ceilingPaintBucket": "Ship bo'yog'i, so'm/chelak",
            "laborPuttyPaintPerM2": "Ish: shpaklyovka + bo'yoq, so'm/m²",
            "laborLaminatePerM2": "Ish: laminat, so'm/m²",
        },
    },
    "apartment": {
        "title": "Butun kvartira",
        "fields": {
            "materialsPerM2": "Materiallar, so'm/m²",
            "laborPerM2": "Ish haqi, so'm/m²",
        },
    },
}

# Sarf me'yorlari (texnik normalar) — narxdan alohida
NORMS = {
    "doorArea": 1.6,  # eshik o'rni, m²
    "tileReserve": 1.1,  # kafel zaxirasi +10%
    "laminateReserve": 1.07,  # laminat zaxirasi +7%
    "tileAdhesiveKgPerM2": 5,
    "tileAdhesiveBagKg": 25,
    "waterproofKgPerM2": 1.5,
    "waterproofBucketKg": 15,
    "waterproofWallStrip": 0.3,
    "puttyKgPerM2": 1.2,
    "puttyBagKg": 20,
    "paintLPerM2": 0.15,
    "paintCoats": 2,
    "paintBucketL": 10,
    "apronHeight": 0.6,
    "apartmentM2PerDay": 1.2,
}

DURATIONS = {
    "bathroom": "10–14 kun",
    "kitchen": "7–10 kun",
    "living": "5–8 kun",
}

# O'lchamlar uchun ruxsat etilgan chegaralar
LIMITS = {
    "dimension": {"min": 0.1, "max": 50},
    "height": {"min": 1.5, "max": 6},
    "area": {"min": 5, "max": 1000},
}

NBSP = " "


def js_round(value: float) -> int:
    """JavaScript Math.round: .5 har doim yuqoriga (Python round() "bank" usulida yaxlitlaydi)."""
    return math.floor(value + 0.5)


def _num(value):
    """Butun qiymatli float'ni int ko'rinishida saqlash (JSON va matnda "5" bo'lsin, "5.0" emas)."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def round1(value: float):
    return _num(js_round(value * 10) / 10)


def ceil_units(value: float) -> int:
    return max(1, math.ceil(value - 1e-9))


def round_money(value: float) -> int:
    return js_round(value / 1000) * 1000


def calculate_estimate(inp: dict, prices: dict | None = None) -> dict:
    prices = prices or DEFAULT_PRICES
    room_type, quality = inp["roomType"], inp["quality"]
    length, width, height, area = inp["length"], inp["width"], inp["height"], inp["area"]
    q = prices["quality"][quality]
    materials: list[dict] = []
    labor: list[dict] = []

    def add_material(name, qty, unit, unit_price):
        materials.append({"name": name, "qty": _num(qty), "unit": unit, "cost": round_money(qty * unit_price * q["material"])})

    def add_labor(name, qty, unit, unit_price):
        labor.append({"name": name, "qty": _num(qty), "unit": unit, "cost": round_money(qty * unit_price * q["labor"])})

    floor_area = 0
    wall_area = 0
    perimeter = 0

    if room_type == "apartment":
        p = prices["apartment"]
        floor_area = round1(area)
        add_material("Qurilish materiallari (kompleks)", floor_area, "m²", p["materialsPerM2"])
        add_labor("Kompleks ta'mirlash ishlari", floor_area, "m²", p["laborPerM2"])
        duration = f"taxminan {max(1, js_round(floor_area / NORMS['apartmentM2PerDay']))} kun"
    else:
        floor_area = round1(length * width)
        perimeter = round1(2 * (length + width))
        wall_area = round1(max(0, perimeter * height - NORMS["doorArea"]))

        putty_bags = ceil_units((wall_area * NORMS["puttyKgPerM2"]) / NORMS["puttyBagKg"])
        paint_buckets = ceil_units((wall_area * NORMS["paintLPerM2"] * NORMS["paintCoats"]) / NORMS["paintBucketL"])

        if room_type == "bathroom":
            p = prices["bathroom"]
            tile_area = round1((wall_area + floor_area) * NORMS["tileReserve"])
            adhesive_bags = ceil_units((tile_area * NORMS["tileAdhesiveKgPerM2"]) / NORMS["tileAdhesiveBagKg"])
            waterproof_area = floor_area + perimeter * NORMS["waterproofWallStrip"]
            waterproof_buckets = ceil_units((waterproof_area * NORMS["waterproofKgPerM2"]) / NORMS["waterproofBucketKg"])

            add_material("Kafel (devor + pol)", tile_area, "m²", p["tilePerM2"])
            add_material("Kafel kleyi (25 kg)", adhesive_bags, "qop", p["tileAdhesiveBag"])
            add_material("Gidroizolyatsiya (15 kg)", waterproof_buckets, "chelak", p["waterproofingBucket"])
            add_material("Zatirka va aksessuarlar", 1, "to'plam", p["groutKit"])
            add_material("Quvurlar va santexnika materiallari", 1, "to'plam", p["plumbingKit"])

            add_labor("Kafel yotqizish", tile_area, "m²", p["laborTilePerM2"])
            add_labor("Gidroizolyatsiya", 1, "xizmat", p["laborWaterproofing"])
            add_labor("Santexnika o'rnatish", 1, "xizmat", p["laborPlumbing"])
        elif room_type == "kitchen":
            p = prices["kitchen"]
            apron_area = round1(length * NORMS["apronHeight"] * NORMS["tileReserve"])
            floor_tile_area = round1(floor_area * NORMS["tileReserve"])

            add_material("Fartuk kafeli", apron_area, "m²", p["apronTilePerM2"])
            add_material("Shpaklyovka (20 kg)", putty_bags, "qop", p["puttyBag"])
            add_material("Devor bo'yog'i (10 l)", paint_buckets, "chelak", p["paintBucket"])
            add_material("Pol kafeli", floor_tile_area, "m²", p["floorTilePerM2"])

            add_labor("Shpaklyovka va bo'yash", wall_area, "m²", p["laborPuttyPaintPerM2"])
            add_labor("Kafel yotqizish", round1(apron_area + floor_tile_area), "m²", p["laborTilePerM2"])
        else:
            p = prices["living"]
            laminate_area = round1(floor_area * NORMS["laminateReserve"])
            ceiling_buckets = ceil_units((floor_area * NORMS["paintLPerM2"] * NORMS["paintCoats"]) / NORMS["paintBucketL"])

            add_material("Shpaklyovka (20 kg)", putty_bags, "qop", p["puttyBag"])
            add_material("Devor bo'yog'i (10 l)", paint_buckets, "chelak", p["paintBucket"])
            add_material("Laminat", laminate_area, "m²", p["laminatePerM2"])
            add_material("Plintus", perimeter, "m", p["plinthPerM"])
            add_material("Ship (potolok) bo'yog'i", ceiling_buckets, "chelak", p["ceilingPaintBucket"])

            add_labor("Shpaklyovka va bo'yash (devor + ship)", round1(wall_area + floor_area), "m²", p["laborPuttyPaintPerM2"])
            add_labor("Laminat yotqizish", floor_area, "m²", p["laborLaminatePerM2"])

        duration = DURATIONS[room_type]

    materials_total = sum(row["cost"] for row in materials)
    labor_total = sum(row["cost"] for row in labor)

    return {
        "roomType": room_type,
        "quality": quality,
        "dimensions": {"length": _num(length), "width": _num(width), "height": _num(height), "area": _num(area)},
        "floorArea": floor_area,
        "wallArea": wall_area,
        "perimeter": perimeter,
        "materials": materials,
        "labor": labor,
        "materialsTotal": materials_total,
        "laborTotal": labor_total,
        "total": materials_total + labor_total,
        "duration": duration,
    }


# ---------------- Formatlash ----------------


def js_str(value) -> str:
    """JS String(number) ga o'xshash: 5.0 -> "5", 2.5 -> "2.5"."""
    value = _num(value)
    if isinstance(value, float):
        return repr(value)
    return str(value)


def format_number(value) -> str:
    """11020000 -> "11 020 000" (bo'shliq — uzilmas bo'shliq)."""
    text = js_str(value)
    sign = ""
    if text.startswith("-"):
        sign, text = "-", text[1:]
    int_part, _, frac_part = text.partition(".")
    groups = []
    while len(int_part) > 3:
        groups.insert(0, int_part[-3:])
        int_part = int_part[:-3]
    groups.insert(0, int_part)
    grouped = NBSP.join(groups)
    return f"{sign}{grouped}.{frac_part}" if frac_part else f"{sign}{grouped}"


def format_money(value) -> str:
    return f"{format_number(value)}{NBSP}so'm"


def format_qty(value, unit: str) -> str:
    value = _num(value)
    shown = value if isinstance(value, int) else _num(float(f"{value:.1f}"))
    return f"{format_number(shown)}{NBSP}{unit}"


def describe_room(result: dict) -> str:
    d = result["dimensions"]
    if result["roomType"] == "apartment":
        return f"{ROOM_LABELS['apartment']} · {format_number(d['area'])} m²"
    return f"{ROOM_LABELS[result['roomType']]} · {js_str(d['length'])} × {js_str(d['width'])} × {js_str(d['height'])} m"


def estimate_to_text(result: dict, link: str | None = None) -> str:
    def line(row):
        return f"• {row['name']}: {format_qty(row['qty'], row['unit'])} — {format_money(row['cost'])}"

    lines = [
        "UySmeta — ta'mirlash smetasi",
        describe_room(result),
        f"Sifat: {QUALITY_LABELS[result['quality']]}",
        f"Muddat: {result['duration']}",
        "",
        "MATERIALLAR",
        *[line(r) for r in result["materials"]],
        f"Materiallar jami: {format_money(result['materialsTotal'])}",
        "",
        "USTA ISH HAQI",
        *[line(r) for r in result["labor"]],
        f"Ish haqi jami: {format_money(result['laborTotal'])}",
        "",
        f"TAXMINIY JAMI: {format_money(result['total'])}",
        "Hisob taxminiy, real narx ±10% farq qilishi mumkin.",
        *(["", link] if link else []),
    ]
    return "\n".join(lines).replace(NBSP, " ")


def parse_decimal(raw) -> float:
    """"2,5" va "2.5" ikkalasini ham qabul qiladi. Noto'g'ri bo'lsa NaN."""
    cleaned = str("" if raw is None else raw).strip().replace(",", ".", 1)
    if cleaned == "":
        return math.nan
    try:
        return float(cleaned)
    except ValueError:
        return math.nan


def validate_input(raw: dict) -> tuple[bool, dict]:
    """(True, input) yoki (False, errors). Xatolar maydon nomi bo'yicha."""
    errors: dict[str, str] = {}
    room_type = raw.get("roomType") if raw.get("roomType") in ROOM_TYPES else None
    quality = raw.get("quality") if raw.get("quality") in QUALITIES else None
    if not room_type:
        errors["roomType"] = "Xona turini tanlang"
    if not quality:
        errors["quality"] = "Sifat darajasini tanlang"

    inp = {"roomType": room_type or "bathroom", "quality": quality or "standard", "length": 0, "width": 0, "height": 0, "area": 0}

    if room_type == "apartment":
        area = parse_decimal(raw.get("area"))
        if not math.isfinite(area) or area <= 0:
            errors["area"] = "Maydonni m² da kiriting, masalan 65"
        elif area < LIMITS["area"]["min"] or area > LIMITS["area"]["max"]:
            errors["area"] = f"Maydon {LIMITS['area']['min']}–{LIMITS['area']['max']} m² oralig'ida bo'lsin"
        else:
            inp["area"] = _num(area)
    else:
        for name in ("length", "width", "height"):
            value = parse_decimal(raw.get(name))
            limits = LIMITS["height"] if name == "height" else LIMITS["dimension"]
            if not math.isfinite(value) or value <= 0:
                errors[name] = "O'lchamni metrda kiriting, masalan 2.5"
            elif value < limits["min"] or value > limits["max"]:
                errors[name] = f"{js_str(limits['min'])}–{js_str(limits['max'])} m oralig'ida kiriting"
            else:
                inp[name] = _num(value)

    return (False, errors) if errors else (True, inp)


def normalize_prices(value) -> dict:
    """Bazadan kelgan narx obyektini tekshirib, yetishmagan kalitlarni standart bilan to'ldiradi."""
    source = value if isinstance(value, dict) else {}
    result = copy.deepcopy(DEFAULT_PRICES)
    for group, fields in result.items():
        incoming_group = source.get(group) if isinstance(source.get(group), dict) else {}
        for key in fields:
            incoming = incoming_group.get(key)
            if group == "quality":
                if isinstance(incoming, dict):
                    for kind in ("material", "labor"):
                        number = _to_number(incoming.get(kind))
                        if number is not None and number > 0:
                            fields[key][kind] = number
            else:
                number = _to_number(incoming)
                if number is not None and number >= 0:
                    fields[key] = _num(number)
    return result


def _to_number(value):
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
