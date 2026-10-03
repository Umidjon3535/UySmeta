"""
O'zbekiston hududlari. Qaysi hudud saytda ishlashi admin paneldan yoqiladi (settings.regions).
Har bir hududning o'z narxlari bo'ladi (settings.prices:<key>).
districts bo'sh bo'lsa, usta tumanini qo'lda yozadi.
"""

import copy
from dataclasses import dataclass

from .estimate import DEFAULT_PRICES, js_round


@dataclass(frozen=True)
class Region:
    key: str
    name: str  # "Samarqand viloyati"
    short: str  # "Samarqand"
    districts: tuple[str, ...] = ()


REGIONS: tuple[Region, ...] = (
    Region(
        "samarqand",
        "Samarqand viloyati",
        "Samarqand",
        (
            "Samarqand shahri",
            "Kattaqo'rg'on shahri",
            "Bulung'ur tumani",
            "Ishtixon tumani",
            "Jomboy tumani",
            "Kattaqo'rg'on tumani",
            "Narpay tumani",
            "Nurobod tumani",
            "Oqdaryo tumani",
            "Past Darg'om tumani",
            "Paxtachi tumani",
            "Payariq tumani",
            "Qo'shrabot tumani",
            "Samarqand tumani",
            "Toyloq tumani",
            "Urgut tumani",
        ),
    ),
    Region(
        "toshkent-sh",
        "Toshkent shahri",
        "Toshkent",
        (
            "Bektemir",
            "Chilonzor",
            "Mirobod",
            "Mirzo Ulug'bek",
            "Olmazor",
            "Sergeli",
            "Shayxontohur",
            "Uchtepa",
            "Yakkasaroy",
            "Yangihayot",
            "Yashnobod",
            "Yunusobod",
        ),
    ),
    Region("toshkent-v", "Toshkent viloyati", "Toshkent viloyati"),
    Region("andijon", "Andijon viloyati", "Andijon"),
    Region("buxoro", "Buxoro viloyati", "Buxoro"),
    Region("fargona", "Farg'ona viloyati", "Farg'ona"),
    Region("jizzax", "Jizzax viloyati", "Jizzax"),
    Region("xorazm", "Xorazm viloyati", "Xorazm"),
    Region("namangan", "Namangan viloyati", "Namangan"),
    Region("navoiy", "Navoiy viloyati", "Navoiy"),
    Region("qashqadaryo", "Qashqadaryo viloyati", "Qashqadaryo"),
    Region("surxondaryo", "Surxondaryo viloyati", "Surxondaryo"),
    Region("sirdaryo", "Sirdaryo viloyati", "Sirdaryo"),
    Region("qoraqalpogiston", "Qoraqalpog'iston Respublikasi", "Qoraqalpog'iston"),
)

DEFAULT_REGION = "samarqand"
DEFAULT_ENABLED_REGIONS = [DEFAULT_REGION]

_BY_KEY = {r.key: r for r in REGIONS}


def get_region(key) -> Region:
    return _BY_KEY.get(key) or _BY_KEY[DEFAULT_REGION]


def is_region_key(key) -> bool:
    return key in _BY_KEY


def regions_label(keys: list[str]) -> str:
    """"Samarqand" / "Samarqand va Buxoro" / "O'zbekiston" — sarlavhalar uchun."""
    if not keys or len(keys) > 3:
        return "O'zbekiston"
    names = [get_region(k).short for k in keys]
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} va {names[-1]}"


def region_default_prices(key: str) -> dict:
    """
    Hudud uchun boshlang'ich narxlar (admin keyin o'zgartiradi).
    Toshkent shahri — bazaviy narxlar. Boshqa hududlarda materiallar deyarli bir xil,
    usta ish haqi taxminan 15% arzonroq deb olingan.
    """
    prices = copy.deepcopy(DEFAULT_PRICES)
    if key == "toshkent-sh":
        return prices
    labor_factor = 0.85
    for group in ("bathroom", "kitchen", "living", "apartment"):
        target = prices[group]
        for field in target:
            if field.startswith("labor"):
                target[field] = js_round(target[field] * labor_factor / 1000) * 1000
    return prices


def form_regions(keys: list[str]) -> list[dict]:
    """Formalar uchun hudud ro'yxati (kalit, nom, tumanlar)."""
    return [{"key": r.key, "name": r.name, "districts": list(r.districts)} for r in (get_region(k) for k in keys)]
