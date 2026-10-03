"""
Tezkor jihozlash (AI'siz, bir zumda): core/data/rooms.json qoidalari + katalog narxlari.
Miqdorlar foydalanuvchi kiritgan pol maydoni, ship balandligi, derazalar va eshiklar sonidan formula bilan hisoblanadi.
"""

import ast
import json
import math
import operator
import random
from functools import lru_cache

from django.db.models import F

from .catalog import CATEGORIES, CATEGORY_LABELS, DATA_DIR
from .estimate import js_round
from .models import CatalogItem
from .uploads import photo_url

DOOR_AREA = 1.6  # eshik o'rni, m²
WINDOW_AREA = 1.8  # deraza o'rni, m²
COUNT_UNITS = {"dona", "to'plam", "xizmat", "nuqta", "qop", "chelak", "rulon", "komplekt"}


@lru_cache(maxsize=1)
def load_rooms() -> dict:
    return json.loads((DATA_DIR / "rooms.json").read_text(encoding="utf-8"))


def room_choices() -> dict:
    return {key: room["label"] for key, room in load_rooms()["rooms"].items()}


def group_choices() -> dict:
    return load_rooms()["groups"]


# ---------------- Xavfsiz formula hisoblagich ----------------

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Eq: operator.eq,
}
_FUNCS = {"ceil": math.ceil, "round": lambda x: js_round(x), "max": max, "min": min}


def evaluate(expr: str, variables: dict) -> float:
    """rooms.json formulalari: sonlar, o'zgaruvchilar, + - * /, taqqoslash va ceil/round/max/min. Boshqa hech narsa."""

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.Name) and node.id in variables:
            return variables[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -ev(node.operand)
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in _OPS:
            return float(_OPS[type(node.ops[0])](ev(node.left), ev(node.comparators[0])))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and not node.keywords:
            return _FUNCS[node.func.id](*[ev(a) for a in node.args])
        raise ValueError(f"Ruxsat etilmagan ifoda: {ast.dump(node)}")

    return float(ev(ast.parse(expr, mode="eval")))


# ---------------- Geometriya ----------------


def room_variables(area: float, height: float, windows: int, doors: int) -> dict:
    """Foydalanuvchi kiritgan qiymatlardan formulalar uchun o'zgaruvchilar (xona kvadratga yaqin deb olinadi)."""
    perimeter = 4 * math.sqrt(area)
    wall = max(0.0, perimeter * height - DOOR_AREA * doors - WINDOW_AREA * windows)
    # Oshxona mebeli uzunligi: xona tomonining ~80% i, 2–4,2 m (18 m² oshxona -> ~3,4 m)
    kitchen = min(4.2, max(2.0, round(math.sqrt(area) * 0.8, 1)))
    return {
        "floor": round(area, 1),
        "ceiling": round(area, 1),
        "height": round(height, 2),
        "perimeter": round(perimeter, 1),
        "wall": round(wall, 1),
        "kitchen": kitchen,
        "windows": windows,
        "doors": doors,
    }


# ---------------- Hisob ----------------


def pick_items(wanted_keys: list[str], budget: str, seed: str | None) -> dict:
    """
    Har bir qoida kaliti (= mahsulot turi) uchun katalogdan bitta mahsulot: {kalit: CatalogItem}.
    seed bo'lmasa — boshlang'ich mahsulotning o'zi; bo'lsa — shu turdagi barcha mahsulotlar ichidan
    (avval byudjetga mos sifatdagilar) tasodifiy, lekin bir xil seed — bir xil natija.
    """
    keys = set(wanted_keys)
    base = {c.key: c for c in CatalogItem.objects.filter(key__in=keys)}
    if not seed:
        return base
    rng = random.Random(seed)
    by_kind = {}
    for item in CatalogItem.objects.filter(kind__in=keys).order_by("id"):
        by_kind.setdefault(item.kind, []).append(item)
    chosen = {}
    for key in wanted_keys:
        pool = by_kind.get(key) or []
        same = [c for c in pool if c.quality == budget]
        pool = same or pool
        chosen[key] = rng.choice(pool) if pool else base.get(key)
    return chosen


def build_quick_plan(*, room_type: str, area: float, height: float, budget: str, windows: int, doors: int, groups: list[str], seed: str | None = None) -> dict:
    rooms = load_rooms()
    room = rooms["rooms"][room_type]
    variables = room_variables(area, height, windows, doors)
    selected = set(groups) or set(rooms["groups"])

    wanted = []  # (qoida, katalog kaliti)
    for rule in room["rules"]:
        if rule["group"] not in selected:
            continue
        if rule.get("when") and not evaluate(rule["when"], variables):
            continue
        key = rule["item"].get(budget) if isinstance(rule["item"], dict) else rule["item"]
        if key:
            wanted.append((rule, key))

    catalog = pick_items([k for _, k in wanted], budget, seed)
    items, used = [], []
    for rule, key in wanted:
        item = catalog.get(key)
        if item is None:
            continue  # katalogdan o'chirilgan bo'lsa
        qty = evaluate(rule["qty"], variables)
        qty = max(1, math.ceil(qty - 1e-9)) if item.unit in COUNT_UNITS else round(qty, 1)
        if qty <= 0:
            continue
        items.append(plan_row(item, qty, placement=rule.get("placement", ""), group=rule["group"]))
        used.append(item.id)
    CatalogItem.objects.filter(id__in=used).update(times_used=F("times_used") + 1)

    return {
        "mode": "tez",
        "summary": room["summary"],
        "layout": room["layout"],
        "roomType": room_type,
        "notes": [],
        "geometry": {k: variables[k] for k in ("floor", "height", "perimeter", "wall", "windows", "doors")},
        "groups": group_rows(items),
        "missing": [],
        "total": sum(i["total"] for i in items),
        "hasUnverified": any(not i["verified"] for i in items),
    }


def plan_row(item: CatalogItem, qty: float, *, placement: str = "", reason: str = "", group: str = "") -> dict:
    return {
        "catalogId": item.id,
        "key": item.key or "",
        "name": item.name,
        "category": item.category,
        "group": group,
        "unit": item.unit,
        "quantity": qty,
        "unitPrice": item.price,
        "priceMin": item.price_min,
        "priceMax": item.price_max,
        "total": js_round(qty * item.price),
        "placement": placement[:200],
        "reason": reason[:200],
        "verified": item.verified,
        "sourceName": item.source_name,
        "sourceUrl": item.source_url,
        "image": item.image,
        "imageCredit": item.image_credit,
        # 3D va real ko'rinish uchun: shakl turi, mahsulot rangi va foni olib tashlangan fotosi
        "kind": item.kind or item.key or "",
        "color": item.color,
        "cutout": photo_url(item.cutout) if item.cutout else "",
    }


def group_rows(items: list[dict]) -> list[dict]:
    """Natijani toifalar bo'yicha guruhlash (mebel, texnika, materiallar...)."""
    groups = []
    for category in CATEGORIES:
        rows = [i for i in items if i["category"] == category]
        if rows:
            groups.append({"category": category, "label": CATEGORY_LABELS[category], "items": rows, "total": sum(r["total"] for r in rows)})
    return groups
