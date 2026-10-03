"""
Ma'lumotlar modeli. Jadval va ustun nomlari asl (Next.js) versiyadagi PostgreSQL sxemasi bilan bir xil —
mavjud bazani ulab, `migrate --fake-initial` bilan davom ettirish mumkin (README ga qarang).
Foydalanuvchi va sessiyalar o'zimizniki (django.contrib.auth emas): parollar scrypt, sessiya tokeni SHA-256 xeshi.
"""

import json
from functools import cached_property

from django.db import models
from django.utils import timezone

from .room_analysis import sanitize_analysis


class User(models.Model):
    ROLE_CHOICES = [("user", "Mijoz"), ("master", "Usta"), ("admin", "Administrator")]

    phone = models.TextField(unique=True)
    name = models.TextField()
    password_hash = models.TextField()
    role = models.TextField(choices=ROLE_CHOICES, default="user")
    created_at = models.DateTimeField(default=timezone.now)
    balance = models.BigIntegerField(default=0)  # ichki hamyon, so'm (faqat core/wallet.py orqali o'zgaradi)
    plan = models.TextField(default="")  # sotib olingan tarif: "" | pdf | design3d
    plan_since = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "users"
        constraints = [models.CheckConstraint(condition=models.Q(role__in=["user", "master", "admin"]), name="users_role_check")]

    def __str__(self):
        return f"{self.name} ({self.phone})"

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def first_name(self) -> str:
        return (self.name.split() or [""])[0]


class Session(models.Model):
    # Cookie'da tasodifiy token, bazada esa uning SHA-256 xeshi — baza sizib chiqsa ham tokenlarni tiklab bo'lmaydi
    id = models.TextField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sessions")
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "sessions"
        indexes = [models.Index(fields=["user"], name="idx_sessions_user")]


class Setting(models.Model):
    """Kalit-qiymat sozlamalar: prices:<hudud>, regions, payment_cards."""

    key = models.TextField(primary_key=True)
    value = models.TextField()
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "settings"


class Estimate(models.Model):
    public_id = models.TextField(unique=True)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="estimates")
    title = models.TextField(null=True, blank=True)
    room_type = models.TextField()
    quality = models.TextField()
    input_json = models.TextField()
    result_json = models.TextField()
    total = models.FloatField()
    photo = models.TextField(null=True, blank=True)
    ai_json = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    region = models.TextField(default="samarqand")

    class Meta:
        db_table = "estimates"
        indexes = [models.Index(fields=["user", "-created_at"], name="idx_estimates_user")]

    @cached_property
    def input(self) -> dict:
        return json.loads(self.input_json)

    @cached_property
    def result(self) -> dict:
        return json.loads(self.result_json)

    @cached_property
    def analysis(self) -> dict | None:
        if not self.ai_json:
            return None
        try:
            return sanitize_analysis(json.loads(self.ai_json))
        except ValueError:
            return None


class Master(models.Model):
    STATUS_CHOICES = [("pending", "Tekshiruvda"), ("approved", "Tasdiqlangan"), ("rejected", "Rad etilgan")]

    user = models.OneToOneField(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="master")
    name = models.TextField()
    phone = models.TextField()
    specialty = models.TextField()
    district = models.TextField()
    experience_years = models.IntegerField(default=0)
    bio = models.TextField(default="")
    jobs_done = models.IntegerField(default=0)
    status = models.TextField(choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(default=timezone.now)
    region = models.TextField(default="samarqand")
    plan = models.TextField(default="")  # usta tarifi: "" (Start) | usta_pro | usta_top — plan_until gacha amal qiladi
    plan_until = models.DateTimeField(null=True, blank=True)
    # Arizadagi portfolio hujjati (PDF/DOCX) — faqat administrator ko'radi (uploads.save_document)
    document = models.TextField(default="")
    document_name = models.TextField(default="")
    offer_accepted_at = models.DateTimeField(null=True, blank=True)

    @property
    def active_plan(self) -> str:
        return self.plan if self.plan and self.plan_until and self.plan_until > timezone.now() else ""

    class Meta:
        db_table = "masters"
        indexes = [
            models.Index(fields=["status", "specialty", "district"], name="idx_masters_status"),
            models.Index(fields=["region", "status"], name="idx_masters_region"),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(status__in=["pending", "approved", "rejected"]), name="masters_status_check")
        ]

    def __str__(self):
        return self.name


class PortfolioWork(models.Model):
    """Usta portfoliosi: bajargan ishlari rasmi va qisqa izoh (usta sahifasida galereya)."""

    master = models.ForeignKey(Master, on_delete=models.CASCADE, related_name="portfolio")
    image = models.TextField()  # uploads.save_image nomi
    title = models.TextField(default="")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "portfolio_works"
        ordering = ["-created_at", "-id"]


class Shop(models.Model):
    """Qurilish do'konlari katalogi (/dokonlar). Do'konlarni administrator qo'shadi va tahrirlaydi."""

    name = models.TextField()
    region = models.TextField(default="samarqand")
    district = models.TextField(default="")
    address = models.TextField(default="")
    phone = models.TextField(default="")
    telegram = models.TextField(default="")  # foydalanuvchi nomi, @ siz
    categories = models.TextField(default="")  # "|kafel|santexnika|" — constants.SHOP_CATEGORIES kalitlari
    description = models.TextField(default="")
    work_hours = models.TextField(default="")
    map_url = models.TextField(default="")
    logo = models.TextField(default="")  # uploads.save_image nomi
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "shops"
        indexes = [models.Index(fields=["is_active", "region", "district"], name="idx_shops_place")]

    def __str__(self):
        return self.name

    @property
    def category_keys(self) -> list[str]:
        return [c for c in self.categories.split("|") if c]


class ShopProduct(models.Model):
    """Do'kon mahsuloti: rasm, narx (so'm, unit uchun). Administrator qo'shadi."""

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="products")
    name = models.TextField()
    price = models.IntegerField()
    unit = models.TextField(default="dona")
    category = models.TextField(default="")  # constants.SHOP_CATEGORIES kaliti
    image = models.TextField(default="")  # uploads.save_image nomi yoki /static/... (namuna mahsulotlar)
    in_stock = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "shop_products"
        indexes = [models.Index(fields=["shop", "category"], name="idx_shop_products")]

    @property
    def image_url(self) -> str:
        from .uploads import photo_url

        if not self.image:
            return ""
        return self.image if self.image.startswith("/") else photo_url(self.image)


class Review(models.Model):
    master = models.ForeignKey(Master, on_delete=models.CASCADE, related_name="reviews")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="reviews")
    rating = models.IntegerField()
    comment = models.TextField(default="")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "reviews"
        constraints = [
            models.UniqueConstraint(fields=["master", "user"], name="reviews_master_id_user_id_key"),
            models.CheckConstraint(condition=models.Q(rating__gte=1, rating__lte=5), name="reviews_rating_check"),
        ]


class ContactRequest(models.Model):
    STATUS_CHOICES = [("new", "Yangi"), ("contacted", "Bog'lanildi"), ("done", "Bajarildi"), ("cancelled", "Bekor qilindi")]

    master = models.ForeignKey(Master, on_delete=models.CASCADE, related_name="requests")
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="contact_requests")
    estimate = models.ForeignKey(Estimate, null=True, blank=True, on_delete=models.SET_NULL, related_name="contact_requests")
    name = models.TextField()
    phone = models.TextField()
    message = models.TextField(default="")
    status = models.TextField(choices=STATUS_CHOICES, default="new")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "contact_requests"
        indexes = [
            models.Index(fields=["master", "-created_at"], name="idx_requests_master"),
            models.Index(fields=["phone", "-created_at"], name="idx_requests_phone"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=["new", "contacted", "done", "cancelled"]), name="contact_requests_status_check"
            )
        ]


class PlanOrder(models.Model):
    STATUS_CHOICES = [("new", "Yangi"), ("paid", "To'langan"), ("done", "Bajarildi"), ("cancelled", "Bekor qilindi")]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="orders")
    plan = models.TextField()
    estimate = models.ForeignKey(Estimate, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders")
    amount = models.IntegerField()
    comment = models.TextField(default="")
    status = models.TextField(choices=STATUS_CHOICES, default="new")
    created_at = models.DateTimeField(default=timezone.now)
    receipt = models.TextField(null=True, blank=True)
    receipt_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "plan_orders"
        constraints = [
            models.CheckConstraint(condition=models.Q(plan__in=["pdf", "design3d", "usta_pro", "usta_top"]), name="plan_orders_plan_check"),
            models.CheckConstraint(
                condition=models.Q(status__in=["new", "paid", "done", "cancelled"]), name="plan_orders_status_check"
            ),
        ]


class OtpCode(models.Model):
    """Tasdiqlash kodlari: SMS yoki Telegram orqali. Bazada faqat kod xeshi saqlanadi."""

    phone = models.TextField()
    purpose = models.TextField()  # register | reset | login
    channel = models.TextField(default="sms")  # sms | telegram | dev
    code_hash = models.TextField(null=True, blank=True)  # Telegram'da kod kontakt tasdiqlangandan keyin yaratiladi
    start_token = models.TextField(null=True, blank=True, unique=True)  # t.me/bot?start=<token>
    tg_chat_id = models.TextField(null=True, blank=True)
    attempts = models.IntegerField(default=0)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "otp_codes"
        indexes = [models.Index(fields=["phone", "purpose", "-created_at"], name="idx_otp_phone")]
        constraints = [
            models.CheckConstraint(condition=models.Q(purpose__in=["register", "reset", "login"]), name="otp_codes_purpose_check"),
            models.CheckConstraint(condition=models.Q(channel__in=["sms", "telegram", "dev"]), name="otp_codes_channel_check"),
        ]


class TelegramLink(models.Model):
    """Telegram'da tasdiqlangan raqamlar (keyingi safar kod darhol yuboriladi, bildirishnomalar ham shu orqali)."""

    phone = models.TextField(primary_key=True)
    chat_id = models.TextField()
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "telegram_links"


class TelegramLogin(models.Model):
    """
    Telegram bot orqali kirish/ro'yxatdan o'tish: sayt token yaratadi → t.me/<bot>?start=login_<token> →
    foydalanuvchi botda raqamini yuboradi → "confirmed" (user) → sayt sessiya ochadi va "used" qiladi.
    """

    STATUS_CHOICES = [("pending", "Kutilmoqda"), ("confirmed", "Tasdiqlandi"), ("used", "Ishlatildi")]

    token = models.TextField(unique=True)
    status = models.TextField(choices=STATUS_CHOICES, default="pending")
    chat_id = models.TextField(null=True, blank=True)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.CASCADE, related_name="telegram_logins")
    is_new_user = models.BooleanField(default=False)
    next_path = models.TextField(default="")
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "telegram_logins"


class SupportThread(models.Model):
    """Saytdagi yordam chati (o'ng pastki burchak): mehmon (cookie kaliti) yoki foydalanuvchi bilan suhbat."""

    STATUS_CHOICES = [("open", "Ochiq"), ("closed", "Yopilgan")]

    key = models.TextField(unique=True)  # brauzer cookie'si (yordam_chat)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="support_threads")
    name = models.TextField(default="")
    phone = models.TextField(default="")
    page = models.TextField(default="")  # birinchi xabar yozilgan sahifa
    status = models.TextField(choices=STATUS_CHOICES, default="open")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "support_threads"
        indexes = [models.Index(fields=["status", "-updated_at"], name="idx_support_status")]


class SupportMessage(models.Model):
    thread = models.ForeignKey(SupportThread, on_delete=models.CASCADE, related_name="messages")
    from_admin = models.BooleanField(default=False)
    text = models.TextField()
    is_read = models.BooleanField(default=False)  # qabul qiluvchi (admin yoki mijoz) o'qiganmi
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "support_messages"
        ordering = ["created_at", "id"]


class RateLimit(models.Model):
    """Urinishlar chegarasi (bir nechta server jarayonida ham to'g'ri ishlashi uchun bazada)."""

    key = models.TextField(primary_key=True)
    count = models.IntegerField()
    reset_at = models.DateTimeField()

    class Meta:
        db_table = "rate_limits"


class CatalogItem(models.Model):
    """
    Narxlar katalogi: materiallar, mebel, texnika, santexnika, yoritish va ish haqi.
    Boshlang'ich narxlar bozordan yig'ilgan; AI internetdan topgan yangi narxlar ham shu yerga qo'shilib boradi.
    """

    CATEGORY_CHOICES = [
        ("material", "Qurilish materiali"),
        ("mebel", "Mebel"),
        ("texnika", "Maishiy texnika"),
        ("santexnika", "Santexnika"),
        ("yoritish", "Yoritish va elektr"),
        ("dekor", "Dekor va to'qimachilik"),
        ("ish", "Usta ishi"),
    ]
    ORIGIN_CHOICES = [("seed", "Boshlang'ich baza"), ("ai", "AI qidiruvi"), ("admin", "Administrator"), ("partner", "Hamkor do'kon"), ("market", "Do'kon narxi (internet)")]

    key = models.TextField(unique=True, null=True, blank=True)  # catalog.json dagi kalit (rooms.json shu bilan murojaat qiladi)
    name = models.TextField()
    name_key = models.TextField(unique=True)  # qidirish va takrorlanishni oldini olish uchun normallashgan nom
    category = models.TextField(choices=CATEGORY_CHOICES)
    unit = models.TextField()  # dona, m², metr, to'plam, xizmat ...
    price = models.IntegerField()  # so'm, o'rtacha bozor narxi
    price_min = models.IntegerField(null=True, blank=True)
    price_max = models.IntegerField(null=True, blank=True)
    quality = models.TextField(default="standard")  # economy | standard | premium
    source_name = models.TextField(default="")
    source_url = models.TextField(default="")
    image = models.TextField(default="")  # /static/catalog/<kalit>.jpg
    image_credit = models.TextField(default="")  # rasm muallifi va litsenziyasi
    # Turi — 3D shakl va xona qoidasidagi o'rni (catalog.json kaliti: "parda", "divan", "laminat-33" ...).
    # Bir turdagi ko'p mahsulot bo'lsa, har loyiha va variant ulardan boshqasini tanlaydi
    kind = models.TextField(default="", db_index=True)
    color = models.TextField(default="")  # asosiy rang (#rrggbb) — rasmdan avtomatik, 3D shu rang bilan chiziladi
    cutout = models.TextField(default="")  # foni olib tashlangan PNG (uploads) — real ko'rinishda mahsulotning haqiqiy fotosi
    image_source = models.TextField(default="")  # import: rasm hali yuklanmagan (URL yoki vaqtinchalik fayl)
    image_error = models.TextField(default="")
    origin = models.TextField(choices=ORIGIN_CHOICES, default="seed")
    verified = models.BooleanField(default=True)  # manbasiz AI bahosi — admin tasdiqlaguncha False
    times_used = models.IntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "catalog_items"
        indexes = [models.Index(fields=["category", "quality"], name="idx_catalog_category")]

    def __str__(self):
        return f"{self.name} — {self.price} so'm/{self.unit}"


class RoomDesign(models.Model):
    """AI jihozlash loyihasi: xona rasmi + aniq maydon -> mos narsalar ro'yxati va umumiy narx."""

    STATUS_CHOICES = [("processing", "Tayyorlanmoqda"), ("done", "Tayyor"), ("failed", "Xato")]

    public_id = models.TextField(unique=True)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="designs")
    photo = models.TextField()
    area = models.FloatField()
    height = models.FloatField(default=2.7)
    room_type = models.TextField(default="auto")
    budget = models.TextField(default="standard")  # economy | standard | premium
    region = models.TextField(default="samarqand")
    wishes = models.TextField(default="")
    windows = models.IntegerField(default=1)
    doors = models.IntegerField(default=1)
    groups = models.TextField(default="")  # tanlangan bo'limlar, vergul bilan: pol,devor,mebel...
    mode = models.TextField(default="tez")  # tez — JSON qoidalar (bir zumda) | ai — AI tahlili
    status = models.TextField(choices=STATUS_CHOICES, default="processing")
    error = models.TextField(default="")
    plan_json = models.TextField(null=True, blank=True)
    total = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    # "Real ko'rinish" — ta'mirdan keyingi fotorealistik rasm (core/render.py)
    # «Boshqa variant»: shu xona uchun qayta jihozlash. variant_of — birinchi (asosiy) loyiha, variant — tartib raqami
    variant_of = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="variants")
    variant = models.PositiveSmallIntegerField(default=1)
    render_status = models.TextField(default="")  # "" | processing | done | failed
    render_photo = models.TextField(default="")  # uploads papkasidagi fayl nomi
    render_source = models.TextField(default="")  # photo — xona rasmi asosida | prompt — loyiha tavsifi asosida
    render_error = models.TextField(default="")
    render_started_at = models.DateTimeField(null=True, blank=True)
    render_marks = models.TextField(default="")  # JSON {"raqam": [x%, y%]} — rasmda narsa qayerda
    # Rasmdagi xona geometriyasi (core/room_geometry.py): orqa devor burchaklari, deraza va eshiklar
    geometry = models.TextField(default="")
    render_guide = models.TextField(default="")  # 3D kompozitsiya rasmi — AI fotorealistik ishlov uchun yo'naltiruvchi
    geometry_status = models.TextField(default="")  # "" | processing | done
    geometry_started_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "room_designs"
        indexes = [models.Index(fields=["user", "-created_at"], name="idx_designs_user")]

    @cached_property
    def plan(self) -> dict | None:
        return json.loads(self.plan_json) if self.plan_json else None

    @cached_property
    def room_geometry(self) -> dict | None:
        return json.loads(self.geometry) if self.geometry else None

    @cached_property
    def marks(self) -> dict:
        return json.loads(self.render_marks) if self.render_marks else {}


class CatalogRequest(models.Model):
    """Foydalanuvchilar so'ragan, lekin katalogda narxi yo'q narsalar (admin narx kiritishi uchun)."""

    name = models.TextField()
    name_key = models.TextField(unique=True)
    category = models.TextField(default="dekor")
    unit = models.TextField(default="dona")
    times_requested = models.IntegerField(default=1)
    created_at = models.DateTimeField(default=timezone.now)
    last_requested_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "catalog_requests"


class WalletTransaction(models.Model):
    """Hamyon tarixi: har bir kirim (+) va chiqim (−). Balans o'zgarishi faqat shu yozuv bilan birga bo'ladi."""

    KIND_CHOICES = [
        ("bonus", "Ro'yxatdan o'tish bonusi"),
        ("purchase", "Tarif xaridi"),
        ("withdraw", "Pul yechish"),
        ("refund", "Qaytarildi"),
        ("admin", "Administrator"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="transactions")
    amount = models.BigIntegerField()
    kind = models.TextField(choices=KIND_CHOICES)
    description = models.TextField(default="")
    balance_after = models.BigIntegerField()
    order = models.ForeignKey(PlanOrder, null=True, blank=True, on_delete=models.SET_NULL, related_name="transactions")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "wallet_transactions"
        indexes = [models.Index(fields=["user", "-created_at"], name="idx_wallet_user")]


class WithdrawRequest(models.Model):
    """Pul yechish so'rovi: summa darhol balansdan ushlanadi; admin kartaga o'tkazgach "done", rad etilsa qaytariladi."""

    STATUS_CHOICES = [("pending", "Ko'rib chiqilmoqda"), ("done", "O'tkazildi"), ("rejected", "Rad etildi")]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="withdrawals")
    amount = models.BigIntegerField()
    card_number = models.TextField()
    card_holder = models.TextField()
    status = models.TextField(choices=STATUS_CHOICES, default="pending")
    note = models.TextField(default="")
    created_at = models.DateTimeField(default=timezone.now)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "withdraw_requests"
        indexes = [models.Index(fields=["status", "-created_at"], name="idx_withdraw_status")]
