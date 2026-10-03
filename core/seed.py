"""
Boshlang'ich ma'lumotlar. `migrate` dan keyin avtomatik ishlaydi (takrorlansa ham xavfsiz).
 - Yoqilgan hududlar (settings.regions)
 - Administrator (ADMIN_PHONE / ADMIN_PASSWORD muhit o'zgaruvchilaridan)
 - Namuna ustalar va sharhlar (SEED_DEMO_DATA=false bo'lsa qo'shilmaydi; faqat ustalar jadvali bo'sh bo'lsa)
 - Namuna do'konlar (shu shart bilan; faqat do'konlar jadvali bo'sh bo'lsa) va ularning mahsulotlari
   (narxlar katalogidagi rasm va narxlardan; faqat mahsulotlar jadvali bo'sh bo'lsa)
"""

import json

from django.conf import settings
from django.db import transaction

from .catalog import seed_catalog
from .wallet import grant_missing_bonuses
from .constants import normalize_phone
from .models import CatalogItem, Master, Review, Setting, Shop, ShopProduct, User
from .passwords import hash_password
from .regions import DEFAULT_ENABLED_REGIONS

DEMO_MASTERS = [
    ("Aziz Karimov", "Kafelchi", "Samarqand shahri", 9, 142, [5, 5, 5, 4, 5],
     "Vannaxona va oshxonalarda kafel, keramogranit yotqizish. Tekis chok va toza ish kafolati."),
    ("Bobur Rahimov", "Santexnik", "Samarqand shahri", 7, 98, [5, 5, 4, 5],
     "Quvur almashtirish, unitaz, vanna va dush kabina o'rnatish. Polipropilen quvurlar bilan ishlayman."),
    ("Sardor Tursunov", "Elektrik", "Urgut tumani", 11, 121, [5, 4, 5, 5, 4],
     "Yangi kvartiralarda to'liq elektr montaj, shit yig'ish, rozetka va chiroqlar o'rnatish."),
    ("Jamshid Aliyev", "Suvoqchi", "Samarqand shahri", 8, 87, [5, 5, 4, 5],
     "Mayoqlar bo'yicha shtukaturka, shpaklyovka va devorlarni bo'yashga tayyorlash."),
    ("Otabek Yusupov", "Bo'yoqchi", "Kattaqo'rg'on shahri", 6, 64, [4, 5, 5],
     "Devor va shiplarni bo'yash, dekorativ shtukaturka, gulqog'oz yopishtirish."),
    ("Dilshod Nazarov", "Laminat ustasi", "Samarqand tumani", 5, 73, [5, 4, 5],
     "Laminat, parket va plintus yotqizish. Pol tekislash (styajka) ham qilaman."),
    ("Rustam Ergashev", "Universal usta", "Samarqand shahri", 12, 156, [5, 5, 5, 4, 5],
     "Kvartirani kalit topshirishgacha kompleks ta'mirlash. O'z brigadam bor."),
    ("Farrux Qodirov", "Kafelchi", "Payariq tumani", 4, 41, [4, 5, 4],
     "Fartuk, pol va vannaxona kafeli. Katta formatli plitalar bilan ishlash tajribasi."),
]

# Namuna do'konlar: (nomi, tuman, manzil, ish vaqti, toifalar, tavsif)
DEMO_SHOPS = [
    ("Qurilish Markazi", "Samarqand shahri", "Rudakiy ko'chasi 112, «Qurilish bozori» yonida", "Har kuni 8:00–19:00",
     ["material", "boyoq", "asbob"], "Sement, gips, shtukaturka aralashmalari, gipsokarton va profil. Shahar ichida yetkazib berish."),
    ("Kafel Olami", "Samarqand shahri", "Mirzo Ulug'bek ko'chasi 45", "Du–Sha 9:00–18:00",
     ["kafel", "pol"], "O'zbekiston, Turkiya va Ispaniya kafeli, keramogranit, mozaika. Katta formatli plitalar."),
    ("Santex Plus", "Samarqand shahri", "Dagbitskaya ko'chasi 27", "Har kuni 9:00–20:00",
     ["santexnika"], "Unitaz, vanna, dush kabina, smesitel, polipropilen quvurlar va fitinglar."),
    ("Nur Elektr", "Samarqand shahri", "Gagarin ko'chasi 8", "Du–Sha 8:30–18:30",
     ["elektr", "asbob"], "Kabel, avtomat, rozetka va o'chirgichlar, LED chiroqlar va lyustralar."),
    ("Laminat House", "Samarqand tumani", "Gulobod MFY, katta yo'l bo'yi", "Du–Sha 9:00–18:00",
     ["pol", "eshik"], "Laminat, parket taxta, linoleum, plintus. Ichki eshiklar o'rnatish bilan."),
    ("Rang-Barang", "Kattaqo'rg'on shahri", "Mustaqillik ko'chasi 19", "Har kuni 8:00–18:00",
     ["boyoq", "material"], "Ichki va tashqi bo'yoqlar, rang tanlash xizmati, dekorativ shtukaturka."),
    ("Urgut Qurilish", "Urgut tumani", "Markaziy bozor, 3-qator", "Du–Sha 7:30–17:00",
     ["material", "kafel", "santexnika"], "Qurilish materiallari, kafel va santexnika bir joyda. Ulgurji narxlar."),
    ("Uy Jihoz", "Samarqand shahri", "Amir Temur ko'chasi 60, «Savdo markazi» 2-qavat", "Har kuni 10:00–21:00",
     ["mebel", "texnika"], "Oshxona mebeli, shkaflar, divanlar va maishiy texnika. Muddatli to'lov."),
    ("Eshik-Rom", "Payariq tumani", "Payariq shahri, Navoiy ko'chasi 3", "Du–Sha 9:00–18:00",
     ["eshik"], "Plastik va alyumin derazalar, metall va ichki eshiklar — o'lchab, o'rnatib beramiz."),
]

# Namuna do'kon mahsulotlari: katalog kaliti → do'kon toifasi. Rasm va o'rtacha narx katalogdan olinadi.
DEMO_SHOP_PRODUCTS = {
    "Qurilish Markazi": {"shpaklyovka": "material", "gruntovka": "material", "gipsokarton": "material", "zatirka": "material",
                         "devor-boyoq": "boyoq", "kabel": "elektr"},
    "Kafel Olami": {"kafel-devor": "kafel", "keramogranit-60": "kafel", "keramogranit-120": "kafel", "zatirka": "kafel",
                    "laminat-33": "pol", "plintus": "pol"},
    "Santex Plus": {"rakovina": "santexnika", "vanna-tumba": "santexnika", "unitaz": "santexnika", "dush-kabina": "santexnika",
                    "vanna": "santexnika", "moyka": "santexnika", "polotensesushitel": "santexnika", "boyler": "santexnika"},
    "Nur Elektr": {"lyustra": "elektr", "led-spot": "elektr", "torsher": "elektr", "rozetka": "elektr", "kabel": "elektr"},
    "Laminat House": {"laminat-32": "pol", "laminat-33": "pol", "laminat-premium": "pol", "plintus": "pol", "eshik": "eshik"},
    "Rang-Barang": {"devor-boyoq": "boyoq", "gruntovka": "boyoq", "shpaklyovka": "boyoq", "oboi": "boyoq"},
    "Urgut Qurilish": {"kafel-devor": "kafel", "keramogranit-60": "kafel", "unitaz": "santexnika", "rakovina": "santexnika",
                       "shpaklyovka": "material", "gipsokarton": "material"},
    "Uy Jihoz": {"divan": "mebel", "burchak-divan": "mebel", "oshxona-ldsp": "mebel", "krovat": "mebel", "shkaf-kupe": "mebel",
                 "kreslo": "mebel", "muzlatgich-artel": "texnika", "kir-mashina-7": "texnika", "tv-43": "texnika",
                 "konditsioner-12": "texnika", "gaz-plita-artel": "texnika", "mikrotolqin": "texnika"},
    "Eshik-Rom": {"eshik": "eshik", "jalyuzi": "eshik"},
}

DEMO_COMMENTS = [
    "Ishni o'z vaqtida tugatdi, juda toza ishladi.",
    "Narxi kelishilganidek bo'ldi, tavsiya qilaman.",
    "Maslahatlari foydali bo'ldi, material tanlashda yordam berdi.",
    "Sifatli ish, lekin bir kun kechikdi.",
    "Hammasi a'lo, yana murojaat qilaman.",
]


@transaction.atomic
def seed_database() -> None:
    # 1. Yoqilgan hududlar (narxlar hudud bo'yicha, kerak bo'lganda standartdan olinadi)
    Setting.objects.get_or_create(key="regions", defaults={"value": json.dumps(DEFAULT_ENABLED_REGIONS)})

    # 2. Administrator
    admin_phone = normalize_phone(settings.ADMIN_PHONE)
    admin_password = settings.ADMIN_PASSWORD
    if admin_phone and admin_password and len(admin_password) >= 8:
        existing = User.objects.filter(phone=admin_phone).first()
        if not existing:
            User.objects.create(phone=admin_phone, name="Administrator", password_hash=hash_password(admin_password), role="admin")
        elif existing.role != "admin":
            User.objects.filter(id=existing.id).update(role="admin")

    # 3. Narxlar katalogi (AI jihozlash uchun)
    seed_catalog()

    # Hamyon paydo bo'lishidan oldin ro'yxatdan o'tganlarga ham bonus
    grant_missing_bonuses()

    if not settings.SEED_DEMO_DATA:
        return

    # 4. Namuna do'konlar (faqat do'konlar jadvali bo'sh bo'lsa)
    if not Shop.objects.exists():
        for index, (name, district, address, hours, categories, description) in enumerate(DEMO_SHOPS):
            Shop.objects.create(
                name=name,
                district=district,
                address=address,
                work_hours=hours,
                phone=f"+9989000020{index:02d}",
                categories=f"|{'|'.join(categories)}|",
                description=description,
            )

    # 4b. Namuna do'konlar mahsulotlari (faqat mahsulotlar jadvali bo'sh bo'lsa)
    if not ShopProduct.objects.exists():
        seed_demo_products()

    # 5. Namuna ustalar (faqat ustalar jadvali bo'sh bo'lsa)
    if Master.objects.exists():
        return

    # Sharh qoldiradigan namuna mijozlar (kirib bo'lmaydigan parol bilan)
    customers = []
    for i, name in enumerate(["Nodira", "Sherzod", "Malika", "Akmal", "Gulnora"]):
        user, _ = User.objects.update_or_create(phone=f"+99899000000{i}", defaults={"name": name, "password_hash": "!disabled"})
        customers.append(user)

    for index, (name, specialty, district, exp, jobs, ratings, bio) in enumerate(DEMO_MASTERS):
        master = Master.objects.create(
            name=name,
            phone=f"+9989000011{index:02d}",
            specialty=specialty,
            district=district,
            experience_years=exp,
            bio=bio,
            jobs_done=jobs,
            status="approved",
        )
        for j, rating in enumerate(ratings):
            Review.objects.create(
                master=master, user=customers[j], rating=rating, comment=DEMO_COMMENTS[(index + j) % len(DEMO_COMMENTS)]
            )


def seed_demo_products() -> int:
    """Namuna do'konlarga katalogdagi rasmli mahsulotlar. Narx har do'konda biroz farq qiladi (bozordagidek)."""
    catalog = {c.key: c for c in CatalogItem.objects.exclude(image="").filter(key__isnull=False)}
    count = 0
    for shop_index, shop in enumerate(Shop.objects.filter(name__in=DEMO_SHOP_PRODUCTS)):
        for item_index, (key, category) in enumerate(DEMO_SHOP_PRODUCTS[shop.name].items()):
            item = catalog.get(key)
            if not item:
                continue
            # -6% ... +6%, 1000 so'mga yaxlitlangan
            factor = 1 + ((shop_index * 7 + item_index * 3) % 13 - 6) / 100
            ShopProduct.objects.create(
                shop=shop,
                name=item.name,
                price=max(1000, round(item.price * factor / 1000) * 1000),
                unit=item.unit,
                category=category,
                image=item.image,
                in_stock=(shop_index + item_index) % 9 != 4,
            )
            count += 1
    return count
