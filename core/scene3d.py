"""
3D ko'rinish sahnasi: loyihadagi narsalar real o'lchamlari, materiallari va ranglari bilan.

- Raqamlar real ko'rinish va narx ro'yxatidagi raqamlar bilan bir xil (render.plan_sections).
- Real ko'rinish tayyor bo'lsa, har bir narsaning rangi o'sha rasmdan olinadi (render.sample_colors) —
  3D va real rasm bir-biriga mos keladi. Bo'lmasa — material/mebelning standart rangi.
- Pol, devor va ship loyihadagi pardoz turiga qarab chiziladi (laminat, keramogranit, oboi, bo'yoq, kafel).
"""

from .models import RoomDesign
from .planner import load_rooms, room_variables
from .render import numbered_items
from .styles import get_style

MAX_COPIES = 4

FLOOR = {
    "laminat-32": ("wood", "#b48a5c"),
    "laminat-33": ("wood", "#a77d52"),
    "laminat-premium": ("wood", "#9a6b43"),
    "keramogranit-60": ("tile60", "#d8d4cc"),
    "keramogranit-120": ("tile120", "#cfcac2"),
}
WALL = {
    "devor-boyoq": ("paint", "#eee8dc"),
    "oboi": ("wallpaper", "#e4d9c6"),
    "kafel-devor": ("tile", "#f0efea"),
}
CEILING = {"natyajnoy": "#ffffff"}
DEFAULT_FLOOR = ("concrete", "#bdb6aa")
DEFAULT_WALL = ("paint", "#e6e2da")
DEFAULT_CEILING = "#efede8"

# Rasmda alohida narsa sifatida chiziladiganlar (o'lchami rooms.json "dims" da yo'q)
SPECIAL = {"plintus": "#f4f1ea", "eshik": "#8b6f5a", "parda": "#d8cbb5", "led-spot": "#fff7d6"}


def build_scene(design: RoomDesign) -> tuple[dict, list[dict], bool]:
    """(sahna ma'lumoti JS uchun, raqamli ro'yxat, ranglar real rasmdan olinganmi)."""
    dims = load_rooms()["dims"]
    variables = room_variables(design.area, design.height, design.windows, design.doors)
    marks = design.marks if design.render_source == "photo" and design.render_photo else {}
    from_photo = any(len(m) > 2 for m in marks.values())

    def color(n: int, default: str) -> str:
        mark = marks.get(str(n)) or []
        return mark[2] if len(mark) > 2 else default

    scene = {
        "side": round(variables["perimeter"] / 4, 2),
        "height": design.height,
        "area": design.area,
        "windows": design.windows,
        "doors": design.doors,
        "floor": {"kind": DEFAULT_FLOOR[0], "color": DEFAULT_FLOOR[1]},
        "wall": {"kind": DEFAULT_WALL[0], "color": DEFAULT_WALL[1]},
        "ceiling": {"color": DEFAULT_CEILING},
        "objects": [],
    }
    legend = []
    for row in numbered_items(design.plan):
        # Hamkor mahsulotining shakli turidan (parda, divan ...), rangi va fotosi — mahsulotning o'zidan
        key, n = row.get("kind") or row.get("key") or "", row["n"]
        # Tanlangan variant (styles.json): aniq rang, material va naqsh — 3D aynan shu bilan chiziladi
        style = (get_style(row.get("style") or "") or {}).get("params") or {}
        own = style.get("color") or row.get("color") or ""
        photo = row.get("cutout") or ""
        copies = int(min(row.get("quantity") or 1, MAX_COPIES)) if row.get("unit") == "dona" else 1
        if key in FLOOR:
            kind, default = FLOOR[key]
            scene["floor"] = {"kind": kind, "color": own or color(n, default), "n": n, "style": style}
        elif key in WALL:
            kind, default = WALL[key]
            scene["wall"] = {"kind": kind, "color": own or color(n, default), "n": n, "style": style}
        elif key in CEILING:
            scene["ceiling"] = {"color": color(n, own or CEILING[key]), "n": n}
        elif key in SPECIAL:
            scene[key.replace("-", "_")] = {"color": own or color(n, SPECIAL[key]), "n": n, "count": copies, "photo": photo, "style": style}
        elif key in dims:
            spec = dims[key]
            size = [variables["kitchen"] if v == "kitchen" else v for v in spec["size"]]
            scene["objects"].append(
                {
                    "n": n,
                    "key": key,
                    "name": row["name"],
                    "size": size,
                    "place": spec["place"],
                    "elevation": spec.get("elevation", 0),
                    "color": own or color(n, spec["color"]),
                    "copies": copies,
                    "photo": photo,
                    "style": style,
                }
            )
        else:
            continue  # 3D'da shakli yo'q narsa — ro'yxatga ham qo'shilmaydi
        legend.append({"n": n, "name": row.get("styleName") or row["name"], "placement": row.get("placement", ""), "color": own or color(n, _default_color(key, dims))})
    return scene, legend, from_photo


def _default_color(key: str, dims: dict) -> str:
    if key in FLOOR:
        return FLOOR[key][1]
    if key in WALL:
        return WALL[key][1]
    return CEILING.get(key) or SPECIAL.get(key) or dims.get(key, {}).get("color", "#999999")
