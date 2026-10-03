"""Do'konlar katalogi: ro'yxat (filtr + sahifalash), do'kon sahifasi va administrator uchun qo'shish/tahrirlash."""

import re

from django.core.paginator import Paginator
from django.db.models import Count, Min, Q
from django.http import Http404
from django.shortcuts import render

from ..constants import SHOP_CATEGORIES, has_valid_phone_code, normalize_phone
from ..data import get_enabled_regions
from ..forms import form_values, state, text
from ..models import Shop, ShopProduct
from ..regions import get_region, is_region_key, regions_label
from ..uploads import ImageError, delete_image, save_image

SHOPS_PER_PAGE = 12
PARTNER_POINTS = [
    {"icon": "package-check", "title": "Tayyor ro'yxat bilan mijoz", "text": "Mijoz smetadagi materiallar ro'yxati bilan keladi — sotuv tezlashadi."},
    {"icon": "bar-chart3", "title": "Narxlaringiz smetada", "text": "Hamkor do'kon narxlari kalkulyatorda hisobga olinadi va nomingiz ko'rsatiladi."},
    {"icon": "store", "title": "Hududingiz bo'ylab", "text": "Mijozlar tumaniga yaqin hamkor do'konlarni ko'radi."},
]


def shops_list(request):
    params = request.GET
    enabled = get_enabled_regions()
    # "joy" = "hudud|tuman" (tuman bo'sh bo'lsa — butun hudud), ustalar ro'yxatidagidek
    joy_region, _, joy_district = text(params, "joy").partition("|")
    region = joy_region if joy_region in enabled else ""
    district = joy_district if region and joy_district in get_region(region).districts else ""
    category = text(params, "toifa") if text(params, "toifa") in SHOP_CATEGORIES else ""
    q = text(params, "q")[:60]

    qs = Shop.objects.filter(is_active=True)
    if region:
        qs = qs.filter(region=region)
    if district:
        qs = qs.filter(district=district)
    if category:
        qs = qs.filter(categories__contains=f"|{category}|")
    if q:
        # Mahsulot nomi bo'yicha ham: "laminat" yozilsa, laminat sotadigan do'konlar chiqadi
        matching = ShopProduct.objects.filter(name__icontains=q).values("shop_id")
        qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q) | Q(address__icontains=q) | Q(id__in=matching))
    qs = qs.annotate(product_count=Count("products"), price_from=Min("products__price"))
    page = Paginator(qs.order_by("name", "id"), SHOPS_PER_PAGE).get_page(params.get("sahifa"))
    shops = list(page.object_list)
    # Kartochkada 3 ta mahsulot rasmi
    previews = {}
    for product in ShopProduct.objects.filter(shop__in=shops).exclude(image="").order_by("shop_id", "id"):
        items = previews.setdefault(product.shop_id, [])
        if len(items) < 3:
            items.append(product)
    for shop in shops:
        shop.previews = previews.get(shop.id, [])
    keep = params.copy()
    keep.pop("sahifa", None)
    return render(
        request,
        "pages/shops.html",
        {
            "shops": shops,
            "page": page,
            "page_numbers": page.paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1),
            "page_query": keep.urlencode(),
            "categories": SHOP_CATEGORIES,
            "category": category,
            "regions": [get_region(k) for k in enabled],
            "joy": f"{region}|{district}" if region else "",
            "q": q,
            "has_filters": bool(region or category or q),
            "place": regions_label(enabled),
            "points": PARTNER_POINTS,
        },
    )


PRODUCTS_PER_PAGE = 24


def shop_detail(request, shop_id: int):
    shop = Shop.objects.filter(id=shop_id, is_active=True).first()
    if not shop:
        raise Http404
    params = request.GET
    all_products = ShopProduct.objects.filter(shop=shop)
    # Toifa tugmalari — faqat mahsuloti bor toifalar
    present = set(all_products.values_list("category", flat=True))
    product_categories = {k: v for k, v in SHOP_CATEGORIES.items() if k in present}
    category = text(params, "toifa") if text(params, "toifa") in product_categories else ""
    q = text(params, "q")[:60]
    products = all_products
    if category:
        products = products.filter(category=category)
    if q:
        products = products.filter(name__icontains=q)
    page = Paginator(products.order_by("-in_stock", "category", "price", "id"), PRODUCTS_PER_PAGE).get_page(params.get("sahifa"))
    keep = params.copy()
    keep.pop("sahifa", None)

    nearby = Shop.objects.filter(is_active=True, region=shop.region).exclude(id=shop.id)
    nearby = list(nearby.filter(district=shop.district)[:4]) or list(nearby[:4])
    return render(
        request,
        "pages/shop.html",
        {
            "shop": shop,
            "products": list(page.object_list),
            "products_total": all_products.count(),
            "page": page,
            "page_numbers": page.paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1),
            "page_query": keep.urlencode(),
            "product_categories": product_categories,
            "product_category": category,
            "product_q": q,
            "nearby": nearby,
            "categories": SHOP_CATEGORIES,
            "region": get_region(shop.region),
            "page_title": f"{shop.name} — {shop.district or get_region(shop.region).short}",
            "page_description": (shop.description or ", ".join(SHOP_CATEGORIES[c] for c in shop.category_keys))[:160],
        },
    )


# ============================ ADMIN ============================


def read_shop_form(request, shop: Shop | None = None) -> dict:
    """Admin panelda do'kon qo'shish (shop=None) yoki tahrirlash. Natija — forma holati."""
    post = request.POST
    name = text(post, "name")[:80]
    region = text(post, "region")
    district = text(post, "district")[:60]
    raw_phone = text(post, "phone")
    phone = normalize_phone(raw_phone) if raw_phone else ""
    telegram = re.sub(r"^(https?://)?(t\.me/)?@?", "", text(post, "telegram"))[:40]
    map_url = text(post, "map_url")[:500]
    categories = [c for c in post.getlist("categories") if c in SHOP_CATEGORIES]
    errors = {}
    if len(name) < 2:
        errors["name"] = "Do'kon nomini kiriting"
    if not is_region_key(region):
        errors["region"] = "Hududni tanlang"
    if raw_phone and not (phone and has_valid_phone_code(phone)):
        errors["phone"] = "Telefon raqam noto'g'ri"
    if telegram and not re.fullmatch(r"[A-Za-z0-9_]{4,40}", telegram):
        errors["telegram"] = "Telegram nomi noto'g'ri (masalan: uysmeta)"
    if map_url and not map_url.startswith("https://"):
        errors["map_url"] = "Xarita havolasi https:// bilan boshlansin"
    if not categories:
        errors["categories"] = "Kamida bitta toifani belgilang"
    try:
        logo = save_image(request.FILES.get("logo")) if not errors else None
    except ImageError as error:
        errors["logo"] = str(error)
        logo = None
    if errors:
        return state(errors=errors, values={**form_values(post), "categories": categories})

    shop = shop or Shop()
    old_logo = shop.logo
    shop.name, shop.region, shop.district, shop.phone, shop.telegram, shop.map_url = name, region, district, phone, telegram, map_url
    shop.address = text(post, "address")[:200]
    shop.work_hours = text(post, "work_hours")[:80]
    shop.description = text(post, "description")[:1000]
    shop.categories = f"|{'|'.join(categories)}|"
    shop.is_active = bool(post.get("is_active"))
    if logo:
        shop.logo = logo
    shop.save()
    if logo and old_logo:
        delete_image(old_logo)
    return state(ok=True, message=f"«{shop.name}» saqlandi")


def _shop_values(shop: Shop) -> dict:
    return {
        "name": shop.name, "region": shop.region, "district": shop.district, "address": shop.address, "phone": shop.phone,
        "telegram": shop.telegram, "map_url": shop.map_url, "work_hours": shop.work_hours, "description": shop.description,
        "categories": shop.category_keys, "is_active": "1" if shop.is_active else "",
    }


def admin_shops_context(request, states: dict) -> dict:
    """Do'konlar bo'limi. Xato bo'lgan forma (yangi yoki tahrirlangan do'kon) kiritilgan qiymatlari bilan qayta ochiladi."""
    q = text(request.GET, "q")
    shops = Shop.objects.all()
    if q:
        shops = shops.filter(Q(name__icontains=q) | Q(district__icontains=q) | Q(phone__icontains=q))
    regions = [get_region(k) for k in get_enabled_regions()]
    failed = states.get("shop") if states.get("shop") and not states["shop"].get("ok") else None
    failed_id = states.get("shop_id", 0) if failed else None
    rows = []
    product_state = states.get("product")
    product_shop = _int(product_state["values"].get("shop")) if product_state and not product_state.get("ok") else 0
    for shop in shops.prefetch_related("products").order_by("-is_active", "name")[:300]:
        mine = failed_id == shop.id
        default_product = state(values={"unit": "dona", "in_stock": "1", "category": (shop.category_keys or [""])[0]})
        rows.append({
            "shop": shop,
            "form": failed if mine else state(values=_shop_values(shop)),
            "open": mine,
            "products": sorted(shop.products.all(), key=lambda p: (p.category, p.name)),
            "product_form": product_state if product_shop == shop.id else default_product,
            "products_open": product_shop == shop.id or str(shop.id) == request.GET.get("mahsulot"),
        })
    return {
        "shop_rows": rows,
        "new_shop_form": failed if failed_id == 0 else state(values={"region": regions[0].key if regions else "", "is_active": "1"}),
        "new_shop_open": failed_id == 0,
        "shop_q": q,
        "shop_categories": SHOP_CATEGORIES,
        "shop_regions": regions,
        "shop_districts": sorted({d for r in regions for d in r.districts}),
        "shops_total": Shop.objects.count(),
    }


def read_product_form(request) -> dict:
    """Admin: do'konga mahsulot qo'shish. Rasm ixtiyoriy, narx — so'mda."""
    post = request.POST
    shop = Shop.objects.filter(id=_int(post.get("shop"))).first()
    name = text(post, "name")[:120]
    price = _int(re.sub(r"\D", "", text(post, "price")))
    category = text(post, "category")
    errors = {}
    if not shop:
        errors["name"] = "Do'kon topilmadi"
    if len(name) < 2:
        errors["name"] = "Mahsulot nomini kiriting"
    if not 0 < price <= 1_000_000_000:
        errors["price"] = "Narxni so'mda kiriting"
    if category not in SHOP_CATEGORIES:
        errors["category"] = "Toifani tanlang"
    try:
        image = save_image(request.FILES.get("image")) if not errors else None
    except ImageError as error:
        errors["image"] = str(error)
        image = None
    if errors:
        return state(errors=errors, values=form_values(post))
    ShopProduct.objects.create(
        shop=shop,
        name=name,
        price=price,
        unit=text(post, "unit")[:20] or "dona",
        category=category,
        image=image or "",
        in_stock=bool(post.get("in_stock")),
    )
    return state(ok=True, message=f"«{name}» qo'shildi")


def product_action(post) -> None:
    """Admin: mahsulotni o'chirish yoki "mavjud / tugagan" holatini almashtirish."""
    product = ShopProduct.objects.filter(id=_int(post.get("id"))).first()
    if not product:
        return
    if post.get("_action") == "product_delete":
        product.delete()
        if not product.image.startswith("/"):
            delete_image(product.image)
    else:
        ShopProduct.objects.filter(id=product.id).update(in_stock=not product.in_stock)


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def delete_shop(shop_id: int) -> None:
    shop = Shop.objects.filter(id=shop_id).first()
    if shop:
        images = [i for i in shop.products.values_list("image", flat=True) if i and not i.startswith("/")]
        shop.delete()
        for name in [shop.logo, *images]:
            delete_image(name)
