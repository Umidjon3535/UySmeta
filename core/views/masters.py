"""Ustalar ro'yxati, usta sahifasi (bog'lanish, sharh) va usta arizasi."""

from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import prefetch_related_objects
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.utils import timezone

from ..auth import login_redirect
from ..background import run_after
from ..constants import PHONE_CODE_ERROR, SPECIALTIES, has_valid_phone_code, normalize_phone, valid_public_id
from ..data import (
    approved_masters_qs,
    count_recent_requests_by_phone,
    get_enabled_regions,
    get_master,
    get_master_by_user,
    has_contacted_master,
)
from ..forms import EMPTY, form_values, state, text
from ..models import ContactRequest, Estimate, Master, PortfolioWork, Review
from ..notify import escape_html, notify_admins, notify_phone, request_message, request_status_message
from ..regions import form_regions, get_region, regions_label
from ..uploads import ImageError, delete_image, photo_url, read_image, save_document, save_image
from ..wallet import master_plan_info


MASTERS_PER_PAGE = 12


def masters_list(request):
    params = request.GET
    specialty = text(params, "specialty")
    enabled = get_enabled_regions()
    # "joy" = "hudud|tuman" (tuman bo'sh bo'lsa — butun hudud)
    joy_region, _, joy_district = text(params, "joy").partition("|")
    region = joy_region if joy_region in enabled else ""
    district = joy_district if region and joy_district in get_region(region).districts else ""
    joy = f"{region}|{district}" if region else ""
    q = text(params, "q")[:60]
    sort = text(params, "sort") if text(params, "sort") in ("rating", "jobs", "new") else "rating"
    smeta = valid_public_id(text(params, "smeta"))

    qs = approved_masters_qs(
        specialty=specialty if specialty in SPECIALTIES else "",
        region=region,
        district=district,
        q=q,
        sort=sort,
    )
    page = Paginator(qs, MASTERS_PER_PAGE).get_page(params.get("sahifa"))
    masters = list(page.object_list)
    prefetch_related_objects(masters, "portfolio")  # kartochkada ish rasmlari
    # Sahifa havolalari filtrlarni saqlaydi
    keep = params.copy()
    keep.pop("sahifa", None)
    return render(
        request,
        "pages/masters.html",
        {
            "masters": masters,
            "page": page,
            "page_numbers": page.paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1),
            "page_query": keep.urlencode(),
            "specialties": SPECIALTIES,
            "specialty": specialty,
            "regions": [get_region(k) for k in enabled],
            "joy": joy,
            "q": q,
            "sort": sort,
            "smeta": smeta,
            "has_filters": bool(specialty or region or q),
            "place": regions_label(enabled),
        },
    )


def _load_master(master_id: int) -> Master | None:
    master = get_master(master_id)
    return master if master and master.status == "approved" else None


def master_detail(request, master_id: int):
    master = _load_master(master_id)
    if not master:
        raise Http404
    user = request.current_user
    source = request.POST if request.method == "POST" else request.GET
    estimate_id = valid_public_id(source.get("smeta") or source.get("estimate"))
    contact_state = review_state = EMPTY

    if request.method == "POST":
        action = request.POST.get("_action")
        if not user:
            return login_redirect(f"/ustalar/{master.id}")
        if action == "contact":
            contact_state = _contact(request, master, estimate_id)
        elif action == "review":
            review_state = _review(request, master)

    portfolio = list(master.portfolio.all())
    reviews = list(Review.objects.filter(master=master).select_related("user").order_by("-created_at", "-id"))
    can_review = bool(user and master.user_id != user.id and has_contacted_master(user.id, master.id))
    # Sharh saqlangach reyting yangilansin
    if review_state.get("ok"):
        master = get_master(master.id)
    return render(
        request,
        "pages/master.html",
        {
            "master": master,
            "reviews": reviews,
            "portfolio": portfolio,
            "portfolio_data": [{"src": photo_url(w.image), "title": w.title} for w in portfolio],
            "can_review": can_review,
            "estimate_id": estimate_id,
            "contact_state": contact_state,
            "review_state": review_state,
            "page_title": f"{master.name} — {master.specialty}",
            "page_description": f"{master.specialty}, {master.district}. {master.bio[:140]}",
        },
    )


def _contact(request, master: Master, estimate_id: str | None) -> dict:
    """Ustaga bog'lanish so'rovi. Kirmagan foydalanuvchi ham yubora oladi (ism + telefon)."""
    user = request.current_user
    post = request.POST
    name = text(post, "name") or (user.name if user else "")
    phone = normalize_phone(post.get("phone") or (user.phone if user else ""))
    message = text(post, "message")[:1000]
    errors = {}
    if len(name) < 2 or len(name) > 60:
        errors["name"] = "Ismingizni kiriting"
    if not phone:
        errors["phone"] = "Telefon raqamni to'liq kiriting"
    elif not has_valid_phone_code(phone):
        errors["phone"] = PHONE_CODE_ERROR
    if errors:
        return state(errors=errors, values=form_values(post))

    # Spamdan himoya: bir raqamdan soatiga 10 tagacha so'rov
    if count_recent_requests_by_phone(phone) >= 10:
        return state(message="Juda ko'p so'rov yuborildi. Birozdan keyin urinib ko'ring", values=form_values(post))

    ContactRequest.objects.create(
        master=master,
        user=user,
        estimate=Estimate.objects.filter(public_id=estimate_id).first() if estimate_id else None,
        name=name,
        phone=phone,
        message=message,
    )
    # Ustaga Telegram'da darhol xabar (javob kutilmaydi — foydalanuvchi uchun tezlik)
    run_after(notify_phone, phone, request_status_message(master.name, master.id, "new"))
    run_after(notify_phone, master.phone, request_message(name, phone, message, estimate_id))
    return state(ok=True, message=f"So'rovingiz yuborildi. {master.name} tez orada siz bilan bog'lanadi.")


def _review(request, master: Master) -> dict:
    user = request.current_user
    if not user:
        return state(message="Sharh qoldirish uchun tizimga kiring")
    if master.user_id == user.id:
        return state(message="O'zingizga sharh qoldira olmaysiz")
    if not has_contacted_master(user.id, master.id):
        return state(message="Sharhni faqat shu usta bilan ishlagan (so'rov yuborgan) mijozlar qoldira oladi")

    try:
        rating = int(request.POST.get("rating", ""))
    except ValueError:
        rating = 0
    comment = text(request.POST, "comment")[:1000]
    if not 1 <= rating <= 5:
        return state(errors={"rating": "Baho tanlang (1–5)"}, values=form_values(request.POST))
    if len(comment) < 5:
        return state(errors={"comment": "Qisqacha fikringizni yozing"}, values=form_values(request.POST))

    Review.objects.update_or_create(
        master=master, user=user, defaults={"rating": rating, "comment": comment, "created_at": timezone.now()}
    )
    return state(ok=True, message="Rahmat! Sharhingiz saqlandi")


def portfolio_limit(master: Master) -> int:
    """Portfolio rasmlari chegarasi — usta tarifiga bog'liq (Start 5, Pro 20, Top 50)."""
    return master_plan_info(master)["photos"]


def portfolio_action(request, master: Master) -> dict:
    """Profildagi portfolio: "portfolio_add" — rasm(lar) + izoh, "portfolio_delete" — bitta ishni o'chirish."""
    post = request.POST
    if post.get("_action") == "portfolio_delete":
        work_id = text(post, "id")
        work = PortfolioWork.objects.filter(master=master, id=int(work_id)).first() if work_id.isdigit() else None
        if work:
            work.delete()
            delete_image(work.image)
        return state(ok=True, message="Rasm o'chirildi")

    files = request.FILES.getlist("images")
    title = text(post, "title")[:120]
    if not files:
        return state(errors={"images": "Ish rasmini tanlang"}, values=form_values(post))
    limit = portfolio_limit(master)
    free = limit - PortfolioWork.objects.filter(master=master).count()
    if len(files) > free:
        message = f"«{master_plan_info(master)['title']}» tarifida portfolioda {limit} ta rasm. Yana {max(free, 0)} ta qo'sha olasiz — ko'proq uchun tarifni oshiring"
        return state(errors={"images": message}, values=form_values(post))
    try:
        images = [read_image(f) for f in files]  # avval hammasi tekshiriladi, keyin saqlanadi
    except ImageError as error:
        return state(errors={"images": str(error)}, values=form_values(post))
    for f, image in zip(files, images):
        if image:
            f.seek(0)
            PortfolioWork.objects.create(master=master, image=save_image(f), title=title)
    return state(ok=True, message="Portfolio yangilandi")


def read_master_form(post) -> tuple[dict, dict]:
    """Usta arizasi / profil formasi. Qaytaradi: (xatolar, model maydonlari)."""
    specialty = text(post, "specialty")
    region_key = text(post, "region")
    district = text(post, "district")[:60]
    try:
        experience_years = int(text(post, "experienceYears"))
    except ValueError:
        experience_years = -1
    bio = text(post, "bio")[:600]
    phone = normalize_phone(post.get("phone"))
    errors = {}
    if specialty not in SPECIALTIES:
        errors["specialty"] = "Mutaxassislikni tanlang"
    if region_key not in get_enabled_regions():
        errors["region"] = "Hududni tanlang"
    else:
        districts = get_region(region_key).districts
        # Tumanlar ro'yxati bor hududda — faqat ro'yxatdan; yo'q bo'lsa — qo'lda yoziladi
        if (district not in districts) if districts else len(district) < 2:
            errors["district"] = "Tuman yoki shaharni tanlang"
    if not 0 <= experience_years <= 60:
        errors["experienceYears"] = "Tajribani yillarda kiriting"
    # Bio ixtiyoriy (arizada o'rniga portfolio hujjati yuklanadi); yozilsa — mazmunli bo'lsin
    if bio and len(bio) < 20:
        errors["bio"] = "Kamida 20 belgi yozing yoki bo'sh qoldiring"
    if not phone:
        errors["phone"] = "Telefon raqamni to'liq kiriting"
    elif not has_valid_phone_code(phone):
        errors["phone"] = PHONE_CODE_ERROR
    data = {
        "specialty": specialty,
        "region": region_key,
        "district": district,
        "experience_years": experience_years,
        "bio": bio,
        "phone": phone or "",
    }
    return errors, data


def read_master_document(request, errors: dict, *, required: bool) -> tuple[str, str] | None:
    """Portfolio hujjati (PDF/DOCX). Boshqa xatolar bo'lsa saqlanmaydi (diskda ortiqcha fayl qolmasin)."""
    file = request.FILES.get("document")
    if not file:
        if required:
            errors["document"] = "Portfolio hujjatini yuklang (PDF yoki DOCX)"
        return None
    if errors:
        return None
    try:
        return save_document(file)
    except ImageError as error:
        errors["document"] = str(error)
        return None


def become_master(request):
    user = request.current_user
    existing = get_master_by_user(user.id) if user else None
    form_state = EMPTY

    if request.method == "POST":
        if not user:
            return login_redirect("/usta-bolish")
        if existing:
            form_state = state(message="Siz allaqachon ariza yuborgansiz")
        else:
            errors, data = read_master_form(request.POST)
            if not request.POST.get("oferta"):
                errors["oferta"] = "Ariza topshirish uchun oferta shartlarini qabul qiling"
            document = read_master_document(request, errors, required=True)
            if errors:
                form_state = state(errors=errors, values=form_values(request.POST))
            else:
                name, original = document
                Master.objects.create(
                    user=user, name=user.name, status="pending", document=name, document_name=original,
                    offer_accepted_at=timezone.now(), **data,
                )
                run_after(
                    notify_admins,
                    f"🧰 <b>Yangi usta arizasi</b>\n\n{escape_html(user.name)} — {data['specialty']}, "
                    f"{get_region(data['region']).short}, {escape_html(data['district'])}\n📞 {data['phone']}\n"
                    f"📎 Portfolio: {escape_html(original)}\n\n"
                    f"Tekshirish: {settings.SITE_URL}/admin?tab=ustalar",
                )
                return HttpResponseRedirect("/profil?ariza=1")

    return render(
        request,
        "pages/become_master.html",
        {
            "existing": existing,
            "state": form_state,
            "master_regions": form_regions(get_enabled_regions()),
            "specialties": SPECIALTIES,
            # Shablon defaults.region / district / ... so'raydi — filtr argumenti topilmasa Django xato beradi
            "apply_defaults": {"phone": user.phone if user else "", "region": "", "district": "", "specialty": "", "experience_years": "", "bio": ""},
            "steps": [
                {"title": "Ariza va portfolio", "text": "Mutaxassislik, ish joyi va bajargan ishlaringiz yozilgan PDF yoki Word hujjatni yuklaysiz."},
                {"title": "Administrator tekshiradi", "text": "Hujjatingiz ko'rib chiqiladi, kerak bo'lsa siz bilan bog'lanamiz."},
                {"title": "Buyurtmalar", "text": "Tasdiqlangach profilingiz ro'yxatda chiqadi, so'rovlar Telegram va profilga keladi."},
            ],
            "benefits": [
                {"icon": "users", "title": "Tayyor mijozlar", "text": "Sizga smetasi tayyor, byudjetini biladigan mijozlar murojaat qiladi."},
                {"icon": "wallet", "title": "Komissiyasiz", "text": "Bog'lanish so'rovlari uchun hech qanday to'lov olinmaydi."},
                {"icon": "badge-check", "title": "Ishonch belgisi", "text": "Tekshiruvdan o'tgan ustalar \"Tekshirilgan\" belgisini oladi."},
            ],
        },
    )
