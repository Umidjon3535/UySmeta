"""
styles.json generatori — jihozlash variantlari kutubxonasi (har oilada 100+ variant).

Har bir variant: aniq nom va tavsif (AI nimani qo'yayotganini bilsin), sifat darajasi (narx katalogdagi shu tur va
daraja narxidan olinadi — variantga alohida "do'kon narxi" o'ylab topilmaydi) va 3D chizish parametrlari (room3d.js).
Qayta yaratish: python core/data/build_styles.py
"""

import itertools
import json
from pathlib import Path

OUT = Path(__file__).with_name("styles.json")

# Ranglar: (kalit, nom, hex)
COLORS = [
    ("oq", "oq", "#f4f2ee"), ("krem", "krem", "#ece3d0"), ("bej", "bej", "#d9c7a7"), ("qum", "qum rang", "#c8b08a"),
    ("kulrang", "kulrang", "#9a9a98"), ("och-kulrang", "och kulrang", "#c9c9c6"), ("grafit", "grafit", "#4a4c50"),
    ("qora", "qora", "#26272a"), ("jigarrang", "jigarrang", "#6b4a33"), ("shokolad", "shokolad", "#4b3021"),
    ("terrakota", "terrakota", "#b5603e"), ("bordo", "bordo", "#7a2233"), ("qizil", "qizil", "#a8322d"),
    ("pushti", "chang-pushti", "#d4a5a0"), ("xantal", "xantal", "#c99a2e"), ("oltin", "oltin", "#c8a14a"),
    ("zaytun", "zaytun", "#7a7a45"), ("shalfey", "shalfey yashil", "#9cae94"), ("zumrad", "zumrad", "#1f6b52"),
    ("to'q-yashil", "to'q yashil", "#24473a"), ("feruza", "feruza", "#3f8f8c"), ("havorang", "havorang", "#a9c6dc"),
    ("ko'k", "ko'k", "#3c5f8a"), ("to'q-ko'k", "to'q ko'k", "#22324f"), ("lavanda", "lavanda", "#a99cc2"),
]
C = {k: (name, hx) for k, name, hx in COLORS}
NEUTRAL = ["oq", "krem", "bej", "qum", "kulrang", "och-kulrang", "grafit", "qora", "jigarrang"]

# Yog'och tuslari
WOODS = [
    ("dub-natural", "tabiiy dub", "#b48a5c"), ("dub-oq", "oqartirilgan dub", "#d8c7ad"), ("dub-kulrang", "kulrang dub", "#a59a8c"),
    ("dub-tutun", "tutunli dub", "#7d6450"), ("yong'oq", "yong'oq", "#6e4b33"), ("venge", "venge", "#3d2b22"),
    ("olxa", "olxa", "#9a5a3c"), ("kul", "kul daraxti", "#cdb48f"), ("qayin", "qayin", "#dcc49a"), ("tik", "tik", "#8c6239"),
]
W = {k: (name, hx) for k, name, hx in WOODS}


def entry(family, idx, name, description, quality, params):
    return {"id": f"{family}-{idx:03d}", "family": family, "name": name, "description": description, "quality": quality, "params": params}


def take(combos, n, step=7):
    """Kombinatsiyalardan bir tekis tarqalgan n tasi (ketma-ket bir xillari emas)."""
    combos = list(combos)
    out, i, used = [], 0, set()
    while len(out) < min(n, len(combos)):
        j = (i * step) % len(combos)
        while j in used:
            j = (j + 1) % len(combos)
        used.add(j)
        out.append(combos[j])
        i += 1
    return out


def curtains():
    types = [("classic", "klassik, ikki qanot"), ("tulle", "tyul va qalin parda"), ("roman", "rim pardasi"), ("roller", "rulonli parda")]
    fabrics = [("velvet", "baxmal"), ("linen", "zig'ir"), ("satin", "atlas"), ("blackout", "blekaut (yorug'lik o'tkazmaydi)"), ("cotton", "paxta")]
    patterns = [("plain", "bir xil rangli"), ("stripes", "tik chiziqli"), ("check", "katakli"), ("floral", "gulli"), ("geometric", "geometrik naqshli"), ("ombre", "ombre (rang o'tishli)")]
    colors = [k for k, *_ in COLORS]
    items = []
    for i, (t, f, p, c) in enumerate(take(itertools.product(types, fabrics, patterns, colors), 130, step=37)):
        accent = "oq" if c != "oq" else "grafit"
        quality = "premium" if f[0] in ("velvet", "satin") else "economy" if t[0] == "roller" or f[0] == "cotton" else "standard"
        name = f"{f[1].split(' ')[0].capitalize()} parda, {C[c][0]}, {p[1]} — {t[1]}"
        desc = f"Parda: {t[1]}; mato — {f[1]}; rang — {C[c][0]}; naqsh — {p[1]}."
        items.append(entry("parda", i + 1, name, desc, quality, {"type": t[0], "fabric": f[0], "pattern": p[0], "color": C[c][1], "color2": C[accent][1]}))
    return items


def doors():
    styles = [("flat", "silliq"), ("panel2", "2 panelli"), ("panel4", "4 panelli"), ("glass-strip", "tik shisha chiziqli"),
              ("glass-big", "katta shishali"), ("classic", "klassik, frezerli"), ("loft", "loft, qora ramka va shisha katakli"), ("grooves", "gorizontal chiziqli")]
    finishes = [("paint", k) for k in ("oq", "krem", "kulrang", "grafit", "qora", "havorang", "shalfey")] + [("wood", k) for k, *_ in WOODS]
    handles = [("chrome", "xrom tutqich"), ("black", "qora tutqich"), ("gold", "oltin rang tutqich")]
    items = []
    for i, (s, (finish, color), h) in enumerate(take(itertools.product(styles, finishes, handles), 130, step=29)):
        cname, chex = (W[color] if finish == "wood" else C[color])
        surface = f"{cname} yog'och teksturali" if finish == "wood" else f"{cname} bo'yalgan"
        quality = ("premium" if s[0] in ("classic", "loft", "glass-big") or color in ("yong'oq", "venge", "tik")
                   else "economy" if s[0] in ("flat", "grooves", "panel2") and (finish == "paint" or color in ("qayin", "dub-oq", "kul")) else "standard")
        name = f"Eshik: {s[1]}, {surface}, {h[1]}"
        desc = f"Ichki eshik; uslubi — {s[1]}; sirti — {surface}; {h[1]}."
        items.append(entry("eshik", i + 1, name, desc, quality, {"style": s[0], "finish": finish, "color": chex, "handle": h[0]}))
    return items


def upholstered():
    fabrics = [("velour", "velur"), ("rogojka", "rogojka"), ("chenille", "shenill"), ("ecoleather", "ekokozha"), ("leather", "charm"), ("boucle", "bukle")]
    legs = [("wood", "yog'och oyoqli"), ("black", "qora metall oyoqli"), ("gold", "oltin rang metall oyoqli"), ("hidden", "oyog'i ko'rinmaydigan")]
    arms = [("wide", "keng suyanchiqli"), ("thin", "ingichka suyanchiqli")]
    colors = [k for k, *_ in COLORS]
    items = []
    for i, (f, l, a, c) in enumerate(take(itertools.product(fabrics, legs, arms, colors), 130, step=41)):
        quality = "premium" if f[0] in ("leather", "boucle", "velour") else "economy" if f[0] == "rogojka" else "standard"
        name = f"{f[1].capitalize()}, {C[c][0]}, {l[1]}, {a[1]}"
        desc = f"Yumshoq mebel qoplamasi — {f[1]}, rangi {C[c][0]}; {l[1]}; {a[1]}."
        items.append(entry("yumshoq", i + 1, name, desc, quality, {"fabric": f[0], "color": C[c][1], "legs": l[0], "arms": a[0]}))
    return items


def beds():
    heads = [("tufted", "kvadrat tikuvli yumshoq bosh qism"), ("vertical", "tik tikuvli yumshoq bosh qism"), ("flat", "silliq yumshoq bosh qism"), ("wood", "yog'och bosh qism")]
    colors = [k for k, *_ in COLORS]
    frames = [k for k, *_ in WOODS[:6]]
    items = []
    for i, (hd, c, fr) in enumerate(take(itertools.product(heads, colors, frames), 120, step=31)):
        quality = "premium" if hd[0] == "tufted" else "economy" if hd[0] == "wood" or (hd[0] == "flat" and fr in ("dub-oq", "dub-natural")) else "standard"
        name = f"Krovat: {hd[1]}, {C[c][0]}, ramka — {W[fr][0]}"
        desc = f"Krovat; {hd[1]} ({C[c][0]}); ramka {W[fr][0]} rangida."
        items.append(entry("krovat", i + 1, name, desc, quality, {"head": hd[0], "color": C[c][1], "frame": W[fr][1]}))
    return items


def cabinets():
    finishes = [("wood", k, W[k][0], W[k][1]) for k, *_ in WOODS] + [("matte", k, C[k][0], C[k][1]) for k in ("oq", "krem", "kulrang", "grafit", "qora", "shalfey", "havorang", "bej")] + \
               [("gloss", k, C[k][0], C[k][1]) for k in ("oq", "krem", "grafit", "qora", "bordo")]
    fronts = [("flat", "silliq fasad"), ("milled", "frezerli fasad"), ("ribbed", "reykali fasad")]
    handles = [("chrome", "xrom tutqich"), ("black", "qora tutqich"), ("gold", "oltin rang tutqich"), ("none", "tutqichsiz (bosib ochiladi)")]
    items = []
    for i, (f, fr, h) in enumerate(take(itertools.product(finishes, fronts, handles), 130, step=23)):
        kind, _, cname, chex = f
        surface = {"wood": f"{cname} yog'och teksturali", "matte": f"{cname} matoviy", "gloss": f"{cname} yaltiroq"}[kind]
        quality = "premium" if kind == "gloss" or fr[0] == "ribbed" else "economy" if kind == "wood" and fr[0] == "flat" else "standard"
        name = f"Korpus mebel: {surface}, {fr[1]}, {h[1]}"
        desc = f"Shkaf, komod, tumba va stollar uchun pardoz: {surface}; {fr[1]}; {h[1]}."
        items.append(entry("korpus", i + 1, name, desc, quality, {"finish": kind, "color": chex, "front": fr[0], "handle": h[0]}))
    return items


def rugs():
    patterns = [("medallion", "markazida medalyonli klassik"), ("oriental", "sharqona naqshli"), ("geometric", "geometrik"), ("stripes", "chiziqli"),
                ("plain", "bir xil rangli, tukli"), ("abstract", "abstrakt"), ("border", "hoshiyali")]
    pairs = [(a, b) for a in ("krem", "bej", "kulrang", "grafit", "bordo", "to'q-ko'k", "terrakota", "zumrad", "havorang", "xantal", "qora", "och-kulrang")
             for b in ("oq", "oltin", "krem", "grafit", "qum") if a != b]
    items = []
    for i, (p, (a, b)) in enumerate(take(itertools.product(patterns, pairs), 130, step=19)):
        quality = "premium" if p[0] in ("oriental", "medallion") else "economy" if p[0] == "plain" else "standard"
        name = f"Gilam: {p[1]}, {C[a][0]} va {C[b][0]}"
        desc = f"Gilam; naqshi — {p[1]}; asosiy rangi {C[a][0]}, ikkinchi rangi {C[b][0]}."
        items.append(entry("gilam", i + 1, name, desc, quality, {"pattern": p[0], "color": C[a][1], "color2": C[b][1]}))
    return items


def wallpapers():
    patterns = [("texture", "faktura (mayda relyef)"), ("stripes", "tik chiziqli"), ("damask", "damask naqshli"), ("geometric", "geometrik"),
                ("floral", "gulli"), ("concrete", "beton ko'rinishli"), ("linen", "mato ko'rinishli")]
    colors = [k for k, *_ in COLORS]
    items = []
    for i, (p, c) in enumerate(take(itertools.product(patterns, colors), 130, step=11)):
        accent = "oltin" if p[0] == "damask" else "oq"
        quality = "premium" if p[0] in ("damask", "linen") else "economy" if p[0] == "texture" else "standard"
        name = f"Oboi: {p[1]}, {C[c][0]}"
        desc = f"Flizelin oboi; naqshi — {p[1]}; rangi {C[c][0]}."
        items.append(entry("oboi", i + 1, name, desc, quality, {"pattern": p[0], "color": C[c][1], "color2": C[accent][1]}))
    return items


def paints():
    items = []
    shades = [("och", 1.18), ("", 1.0), ("to'q", 0.78)]
    finishes = [("matt", "matt"), ("satin", "yarim matt")]
    combos = [(c, s, f) for c, s, f in itertools.product(COLORS, shades, finishes)
              # "och och kulrang", "to'q qora" kabi ma'nosiz nomlar bo'lmasin
              if not (s[0] and (c[1].startswith(("och", "to'q")) or c[0] in ("oq", "qora")))]
    for i, ((k, cname, chex), (sh, factor), (fin, fname)) in enumerate(combos):
        r, g, b = (int(chex[j:j + 2], 16) for j in (1, 3, 5))
        mix = (lambda v: min(255, round(v + (255 - v) * (factor - 1) * 2))) if factor > 1 else (lambda v: round(v * factor))
        hx = "#" + "".join(f"{mix(v):02x}" for v in (r, g, b))
        label = f"{sh} {cname}".strip()
        quality = "premium" if fin == "satin" and sh == "to'q" else "economy" if fin == "matt" and sh == "och" else "standard"
        name = f"Devor bo'yog'i: {label}, {fname}"
        if any(item["name"] == name for item in items):
            continue  # "och" + "kulrang" = tayyor "och kulrang" — takrorlanmasin
        items.append(entry("boyoq", len(items) + 1, name, f"Devor bo'yog'i; rangi {label}; {fname} sirt.", quality, {"color": hx, "finish": fin}))
    return items


def laminates():
    planks = [("narrow", "tor taxtali"), ("wide", "keng taxtali"), ("long", "uzun taxtali")]
    finishes = [("matte", "matt"), ("textured", "yog'och relyefli"), ("satin", "yarim yaltiroq")]
    extra = [("dub-qora", "qora dub", "#3a332e"), ("dub-sariq", "asal dub", "#c4914f"), ("dub-qumli", "qumli dub", "#bfa07a"), ("kul-kulrang", "kulrang kul", "#b7b2a8")]
    woods = WOODS + extra
    items = []
    for i, ((k, cname, chex), pl, fn) in enumerate(itertools.product(woods, planks, finishes)):
        quality = "premium" if fn[0] == "textured" or pl[0] == "long" else "economy" if pl[0] == "narrow" and fn[0] == "matte" else "standard"
        items.append(entry("laminat", i + 1, f"Laminat: {cname}, {pl[1]}, {fn[1]}", f"Pol: laminat; rangi {cname}; {pl[1]}; {fn[1]} sirt.", quality,
                           {"color": chex, "plank": pl[0], "finish": fn[0]}))
    return items


def tiles():
    looks = [("marble", "marmar ko'rinishli", ["oq", "krem", "kulrang", "qora", "bej"]), ("concrete", "beton ko'rinishli", ["och-kulrang", "kulrang", "grafit", "bej"]),
             ("stone", "tosh ko'rinishli", ["qum", "bej", "kulrang", "jigarrang"]), ("plain", "bir xil rangli", ["oq", "krem", "och-kulrang", "grafit", "qora", "terrakota"]),
             ("wood", "yog'och ko'rinishli", [])]
    sizes = [("60", "60×60 sm"), ("120", "60×120 sm"), ("80", "80×80 sm")]
    finishes = [("polished", "yaltiroq"), ("matte", "matt")]
    combos = []
    for look, lname, colors in looks:
        palette = [(k, C[k][0], C[k][1]) for k in colors] or [(k, n, h) for k, n, h in WOODS]
        for (k, cname, chex), sz, fn in itertools.product(palette, sizes, finishes):
            combos.append((look, lname, cname, chex, sz, fn))
    items = []
    for i, (look, lname, cname, chex, sz, fn) in enumerate(take(combos, 130, step=17)):
        quality = "premium" if look == "marble" or sz[0] == "120" else "economy" if look == "plain" and sz[0] == "60" else "standard"
        items.append(entry("keramogranit", i + 1, f"Keramogranit: {lname}, {cname}, {sz[1]}, {fn[1]}",
                           f"Pol: keramogranit; {lname}; rangi {cname}; o'lchami {sz[1]}; {fn[1]}.", quality,
                           {"look": look, "color": chex, "size": sz[0], "finish": fn[0]}))
    return items


def lamps():
    shapes = [("balls", "shar plafonli"), ("drum", "baraban abajurli"), ("ring", "halqa shaklidagi LED"), ("branches", "shoxli"), ("cone", "konus plafonli")]
    metals = [("gold", "oltin rang"), ("black", "qora"), ("chrome", "xrom"), ("bronze", "bronza")]
    shades = ["oq", "krem", "bej", "grafit", "oltin", "havorang"]
    items = []
    for i, (s, m, c) in enumerate(take(itertools.product(shapes, metals, shades), 110, step=13)):
        quality = "premium" if m[0] in ("gold", "bronze") else "economy" if s[0] == "drum" else "standard"
        items.append(entry("chiroq", i + 1, f"Chiroq: {s[1]}, {m[1]} metall, plafon {C[c][0]}",
                           f"Shift chirog'i yoki torsher; shakli — {s[1]}; metall qismi {m[1]}; plafon rangi {C[c][0]}.", quality,
                           {"shape": s[0], "metal": m[0], "color": C[c][1]}))
    return items


FAMILIES = {
    "parda": {"label": "Pardalar", "kinds": ["parda"], "build": curtains},
    "eshik": {"label": "Eshiklar", "kinds": ["eshik"], "build": doors},
    "yumshoq": {"label": "Yumshoq mebel", "kinds": ["divan", "burchak-divan", "kreslo"], "build": upholstered},
    "krovat": {"label": "Krovatlar", "kinds": ["krovat", "yotoqxona-toplam", "bolalar-krovati"], "build": beds},
    "korpus": {"label": "Korpus mebel", "kinds": ["shkaf-kupe", "komod", "tumbochka", "tv-tumba", "dahliz-shkaf", "stelaj", "jurnal-stoli",
                                                  "ish-stoli", "oshxona-stol", "oshxona-ldsp", "oshxona-mdf", "oshxona-akril", "vanna-tumba"], "build": cabinets},
    "gilam": {"label": "Gilamlar", "kinds": ["gilam"], "build": rugs},
    "oboi": {"label": "Oboilar", "kinds": ["oboi"], "build": wallpapers},
    "boyoq": {"label": "Devor bo'yoqlari", "kinds": ["devor-boyoq"], "build": paints},
    "laminat": {"label": "Laminat", "kinds": ["laminat-32", "laminat-33", "laminat-premium"], "build": laminates},
    "keramogranit": {"label": "Keramogranit", "kinds": ["keramogranit-60", "keramogranit-120"], "build": tiles},
    "chiroq": {"label": "Chiroqlar", "kinds": ["lyustra", "torsher"], "build": lamps},
}


def main():
    data = {
        "version": 1,
        "note": "Jihozlash variantlari (core/data/build_styles.py yaratadi). Narx — katalogdagi shu tur va sifat darajasining narxi.",
        "families": {k: {"label": v["label"], "kinds": v["kinds"]} for k, v in FAMILIES.items()},
        "items": [item for v in FAMILIES.values() for item in v["build"]()],
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    counts = {}
    for item in data["items"]:
        counts[item["family"]] = counts.get(item["family"], 0) + 1
    print(counts, "jami:", len(data["items"]))


if __name__ == "__main__":
    main()
