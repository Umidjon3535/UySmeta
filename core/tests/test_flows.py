"""Asosiy foydalanuvchi oqimlari: ro'yxat, kirish, smeta, ustalar, buyurtma va to'lov, admin panel, Telegram bot."""

import json
import os
import shutil
import tempfile
from unittest import mock

from django.test import TestCase, override_settings

from core.auth import COOKIE_NAME
from core.models import ContactRequest, Estimate, Master, OtpCode, PlanOrder, Review, TelegramLink, User
from core.otp import handle_telegram_update, send_otp, verify_otp
from core.passwords import hash_password

# Eng kichik to'g'ri PNG (1×1)
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63f8ffff3f0005fe02fea7d6a4b30000000049454e44ae426082"
)

TMP_UPLOADS = tempfile.mkdtemp(prefix="uysmeta-test-")


@override_settings(UPLOAD_DIR=TMP_UPLOADS)
class FlowTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP_UPLOADS, ignore_errors=True)

    def make_user(self, phone="+998901112233", name="Dilnoza Karimova", role="user", password="Parol-12"):
        return User.objects.create(phone=phone, name=name, role=role, password_hash=hash_password(password))

    def login(self, phone="+998901112233", password="Parol-12"):
        return self.client.post("/kirish", {"phone": phone, "password": password})

    def make_master(self, **extra):
        data = {
            "name": "Aziz Karimov",
            "phone": "+998900001199",
            "specialty": "Kafelchi",
            "district": "Samarqand shahri",
            "region": "samarqand",
            "bio": "Vannaxona va oshxonalarda kafel yotqizish.",
            "status": "approved",
        }
        data.update(extra)
        return Master.objects.create(**data)

    # ---------------- Ro'yxat va kirish ----------------

    def test_register_with_dev_code_then_login(self):
        form = {"name": "Dilnoza", "surname": "Karimova", "phone": "90 111 22 33", "password": "Parol-12", "passwordConfirm": "Parol-12", "oferta": "1"}
        res = self.client.post("/royxat", {**form, "channel": "dev"})
        self.assertEqual(res.status_code, 200)
        state = res.context["state"]
        self.assertTrue(state["ok"])
        code = state["data"]["devCode"]
        self.assertContains(res, "Test rejimi")

        wrong = self.client.post("/royxat", {**form, "codeSent": "1", "channel": "dev", "code": "000000" if code != "000000" else "111111"})
        self.assertIn("Kod noto'g'ri", wrong.context["state"]["errors"]["code"])

        res = self.client.post("/royxat", {**form, "codeSent": "1", "channel": "dev", "step": "confirm", "code": code})
        self.assertRedirects(res, "/smetalar?xush=1", fetch_redirect_response=False)
        self.assertIn(COOKIE_NAME, res.cookies)
        self.assertTrue(User.objects.filter(phone="+998901112233", name="Dilnoza Karimova").exists())

        # Chiqib, parol bilan qayta kirish
        self.client.post("/chiqish")
        self.assertEqual(self.client.get("/profil").status_code, 302)
        res = self.login()
        self.assertRedirects(res, "/smetalar", fetch_redirect_response=False)
        self.assertEqual(self.client.get("/profil").status_code, 200)

    def test_register_rejects_existing_phone_and_bad_password(self):
        self.make_user()
        res = self.client.post("/royxat", {"name": "A", "surname": "", "phone": "901112233", "password": "123", "passwordConfirm": "321", "channel": "dev"})
        errors = res.context["state"]["errors"]
        self.assertIn("name", errors)
        self.assertIn("allaqachon", errors["phone"])
        self.assertIn("aynan 8", errors["password"])
        self.assertIn("passwordConfirm", errors)
        self.assertIn("surname", errors)
        self.assertIn("oferta", errors)

    def test_register_rejects_digits_in_name(self):
        form = {"name": "Dil1", "surname": "Karimova", "phone": "901112233", "password": "Parol-12", "passwordConfirm": "Parol-12", "oferta": "1", "channel": "dev"}
        errors = self.client.post("/royxat", form).context["state"]["errors"]
        self.assertIn("harflarda", errors["name"])
        self.assertNotIn("surname", errors)
        page = self.client.get("/royxat")
        self.assertContains(page, 'maxlength="30" data-name-input')
        self.assertContains(page, 'maxlength="8"')

    def test_register_rejects_unknown_operator_code(self):
        form = {"name": "Dilnoza", "surname": "Karimova", "phone": "971112233", "password": "Parol-12", "passwordConfirm": "Parol-12", "oferta": "1", "channel": "dev"}
        res = self.client.post("/royxat", form)
        self.assertIn("Operator kodi", res.context["state"]["errors"]["phone"])
        self.assertContains(self.client.get("/royxat"), 'data-phone-codes="33,50,77,88,90,91,93,94,95,99"')

    def test_oferta_page_shows_live_prices(self):
        res = self.client.get("/oferta")
        self.assertContains(res, "Ommaviy oferta")
        self.assertContains(res, "«PDF smeta»")
        self.assertContains(self.client.get("/royxat"), "href=\"/oferta\"")


    def test_login_errors_and_rate_limit(self):
        self.make_user()
        res = self.login(password="notogri-parol")
        self.assertEqual(res.context["state"]["message"], "Telefon raqam yoki parol noto'g'ri")
        for _ in range(5):
            res = self.login(password="notogri-parol")
        self.assertIn("Juda ko'p", res.context["state"]["message"])

    def test_login_safe_next(self):
        self.make_user()
        res = self.client.post("/kirish", {"phone": "901112233", "password": "Parol-12", "next": "//evil.com"})
        self.assertEqual(res["Location"], "/smetalar")

    def test_reset_password_same_answer_for_unknown_phone(self):
        res = self.client.post("/parolni-tiklash", {"phone": "909999999", "channel": "dev"})
        self.assertTrue(res.context["state"]["ok"])
        self.assertNotIn("devCode", res.context["state"]["data"])
        self.assertFalse(OtpCode.objects.exists())

    def test_reset_password_flow(self):
        user = self.make_user()
        res = self.client.post("/parolni-tiklash", {"phone": "901112233", "channel": "dev"})
        code = res.context["state"]["data"]["devCode"]
        res = self.client.post(
            "/parolni-tiklash",
            {"phone": "901112233", "codeSent": "1", "channel": "dev", "code": code, "password": "Yangi-12", "passwordConfirm": "Yangi-12"},
        )
        self.assertRedirects(res, "/profil?parol=1", fetch_redirect_response=False)
        user.refresh_from_db()
        self.client.post("/chiqish")
        self.assertRedirects(self.login(password="Yangi-12"), "/smetalar", fetch_redirect_response=False)

    # ---------------- Smeta ----------------

    def test_guest_sees_auth_card_instead_of_calculator(self):
        page = self.client.get("/")
        self.assertContains(page, "Hisobingizga kiring")
        self.assertNotContains(page, "calc-form")
        self.assertEqual(self.client.post("/api/hisob", {"roomType": "bathroom"}).status_code, 401)
        res = self.client.post("/", {"roomType": "kitchen", "quality": "premium", "length": "3", "width": "2.5", "height": "2.7"})
        self.assertRedirects(res, "/royxat", fetch_redirect_response=False)
        self.assertFalse(Estimate.objects.exists())

    def test_home_auth_card_partial_login_and_register(self):
        page = self.client.get("/")
        self.assertContains(page, "data-auth-tabs")
        self.assertContains(page, "Telegram orqali kirish")
        for prefix in ("l-", "r-"):
            self.assertContains(page, f'id="{prefix}f-phone"')
        self.assertContains(page, "data-tg-login")  # Telegram orqali — raqam yozilmaydi, bot ochiladi

        # Xato bo'lsa — faqat forma qismi, id prefiksi saqlanadi
        res = self.client.post("/kirish", {"phone": "", "password": "", "_p": "l-"}, HTTP_X_AUTH_PARTIAL="1")
        self.assertNotContains(res, "<html", status_code=400)
        self.assertContains(res, 'id="l-f-phone"', status_code=400)

        self.make_user()
        res = self.client.post("/kirish", {"phone": "901112233", "password": "Parol-12", "next": "/"}, HTTP_X_AUTH_PARTIAL="1")
        self.assertEqual(res.json(), {"redirect": "/"})
        self.assertContains(self.client.get("/"), "calc-form")

    def test_telegram_login_needs_bot(self):
        # Bot ulanmagan — tugma o'rniga ogohlantirish, POST rad etiladi
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_BOT_USERNAME": ""}):
            self.assertContains(self.client.get("/kirish/telegram"), "Telegram bot hozircha ulanmagan")
            res = self.client.post("/kirish/telegram", HTTP_ACCEPT="application/json")
            self.assertEqual(res.status_code, 503)

    def test_auth_pages_share_tabs(self):
        for url, selected in (("/kirish", "tab-login"), ("/royxat", "tab-register"), ("/kirish/telegram", "tab-login")):
            page = self.client.get(url)
            self.assertContains(page, "data-auth-tabs")
            self.assertRegex(page.content.decode(), rf'id="{selected}"[^>]*aria-selected="true"')

    def test_short_registration_without_password_confirm(self):
        data = {"name": "Aziz", "surname": "Karimov", "phone": "935556677", "password": "Parol-12", "passwordConfirm": "Parol-12", "oferta": "1", "channel": "dev", "_p": "r-"}
        res = self.client.post("/royxat", data, HTTP_X_AUTH_PARTIAL="1")
        self.assertNotContains(res, "<html")
        code = res.context["state"]["data"]["devCode"]
        res = self.client.post("/royxat", {**data, "codeSent": "1", "code": code, "step": "confirm"}, HTTP_X_AUTH_PARTIAL="1")
        self.assertEqual(res.json(), {"redirect": "/smetalar?xush=1"})
        self.assertTrue(User.objects.filter(phone="+998935556677").exists())

    def test_live_calculation_api(self):
        self.make_user()
        self.login()
        res = self.client.post("/api/hisob", {"roomType": "bathroom", "quality": "standard", "length": "2.5", "width": "2.0", "height": "2.7", "region": "toshkent-sh"})
        data = res.json()
        self.assertTrue(data["ok"])
        self.assertIn("Namuna hisob", data["html"])
        self.assertIn("Taxminiy jami", data["html"])

        # «Hisoblash» bosilgan — standart o'lchamlar ham "Sizning smetangiz"
        res = self.client.post("/api/hisob", {"roomType": "bathroom", "quality": "standard", "length": "2.5", "width": "2.0", "height": "2.7", "explicit": "1"})
        self.assertIn("Sizning smetangiz", res.json()["html"])
        self.assertNotIn("Namuna hisob", res.json()["html"])

        res = self.client.post("/api/hisob", {"roomType": "bathroom", "quality": "standard", "length": "abc", "width": "2", "height": "2.7"})
        self.assertFalse(res.json()["ok"])
        self.assertIn("length", res.json()["errors"])

    def test_save_estimate_logged_in(self):
        self.make_user()
        self.login()
        res = self.client.post("/", {"roomType": "kitchen", "quality": "premium", "length": "3", "width": "2.5", "height": "2.7", "region": "samarqand", "title": "Oshxona"})
        self.assertEqual(res.status_code, 302)
        estimate = Estimate.objects.get()
        self.assertTrue(res["Location"].startswith(f"/smeta/{estimate.public_id}"))
        self.assertIsNotNone(estimate.user_id)
        self.assertEqual(estimate.result["roomType"], "kitchen")
        self.assertContains(self.client.get(f"/smeta/{estimate.public_id}?saqlandi=1"), "Smeta saqlandi")
        self.assertContains(self.client.get("/smetalar"), "Oshxona")

    def test_save_estimate_validation_and_photo(self):
        self.make_user()
        self.login()
        res = self.client.post("/", {"roomType": "bathroom", "quality": "standard", "length": "0", "width": "2", "height": "2.7"})
        self.assertEqual(res.status_code, 400)
        self.assertContains(res, "O&#x27;lchamni metrda kiriting", status_code=400)
        self.assertFalse(Estimate.objects.exists())

        from django.core.files.uploadedfile import SimpleUploadedFile

        photo = SimpleUploadedFile("room.png", PNG, content_type="image/png")
        analysis = {
            "isRoomPhoto": True, "roomType": "bathroom", "condition": "worn", "estimatedFloorArea": 5,
            "visibleIssues": ["Namlik"], "recommendations": ["Gidroizolyatsiya"], "suggestedQuality": "standard", "summary": "Eski vannaxona",
        }
        res = self.client.post(
            "/",
            {"roomType": "bathroom", "quality": "standard", "length": "2", "width": "2", "height": "2.7", "photo": photo, "analysis": json.dumps(analysis)},
        )
        estimate = Estimate.objects.get()
        self.assertTrue(estimate.photo.endswith(".png"))
        self.assertEqual(estimate.analysis["summary"], "Eski vannaxona")
        image = self.client.get(f"/api/uploads/{estimate.photo}")
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image["Content-Type"], "image/png")
        self.assertEqual(self.client.get("/api/uploads/..%2F..%2Fsettings.py").status_code, 404)
        self.assertContains(self.client.get(f"/smeta/{estimate.public_id}"), "AI tahlili")

    def test_owner_can_rename_and_delete(self):
        user = self.make_user()
        self.login()
        self.client.post("/", {"roomType": "living", "quality": "economy", "length": "4", "width": "3", "height": "2.7"})
        estimate = Estimate.objects.get(user=user)
        path = f"/smeta/{estimate.public_id}"
        res = self.client.post(path, {"_action": "rename", "title": "Yotoqxona"})
        self.assertContains(res, "Nom saqlandi")
        # Boshqa foydalanuvchi o'chira olmaydi
        self.client.post("/chiqish")
        self.make_user(phone="+998907778899")
        self.login(phone="907778899")
        self.client.post(path, {"_action": "delete"})
        self.assertTrue(Estimate.objects.filter(id=estimate.id).exists())
        self.client.post("/chiqish")
        self.login()
        self.assertRedirects(self.client.post(path, {"_action": "delete"}), "/smetalar", fetch_redirect_response=False)
        self.assertFalse(Estimate.objects.filter(id=estimate.id).exists())

    # ---------------- Ustalar ----------------

    def test_contact_and_review_master(self):
        master = self.make_master()
        page = self.client.get(f"/ustalar/{master.id}")
        self.assertContains(page, master.name)

        # Sharh faqat so'rov yuborgandan keyin
        self.make_user()
        self.login()
        res = self.client.post(f"/ustalar/{master.id}", {"_action": "review", "rating": "5", "comment": "Zo'r usta!"})
        self.assertIn("faqat", res.context["review_state"]["message"])

        res = self.client.post(f"/ustalar/{master.id}", {"_action": "contact", "message": "Vannaxona"})
        self.assertTrue(res.context["contact_state"]["ok"])
        self.assertEqual(ContactRequest.objects.get().phone, "+998901112233")

        res = self.client.post(f"/ustalar/{master.id}", {"_action": "review", "rating": "4", "comment": "Juda toza ishladi"})
        self.assertTrue(res.context["review_state"]["ok"])
        self.assertEqual(Review.objects.get(master=master).rating, 4)
        self.assertContains(self.client.get("/ustalar"), master.name)

    def test_masters_filters(self):
        self.make_master(name="Kafelchi Aka")
        self.make_master(name="Elektrik Uka", specialty="Elektrik", district="Urgut tumani", phone="+998900001198")
        res = self.client.get("/ustalar", {"specialty": "Elektrik"})
        names = [m.name for m in res.context["masters"]]
        self.assertIn("Elektrik Uka", names)
        self.assertNotIn("Kafelchi Aka", names)
        res = self.client.get("/ustalar", {"joy": "samarqand|Urgut tumani"})
        self.assertTrue(all(m.district == "Urgut tumani" for m in res.context["masters"]))

    def test_apply_master_and_admin_approves(self):
        user = self.make_user()
        self.login()
        from django.core.files.uploadedfile import SimpleUploadedFile

        form = {"specialty": "Santexnik", "region": "samarqand", "district": "Urgut tumani", "experienceYears": "7", "phone": "901112233"}
        pdf = lambda: SimpleUploadedFile("Portfolio Aziz.pdf", b"%PDF-1.4\n%test\n", content_type="application/pdf")  # noqa: E731

        # Hujjat va oferta majburiy; rasm yoki boshqa fayl qabul qilinmaydi
        errors = self.client.post("/usta-bolish", form).context["state"]["errors"]
        self.assertIn("document", errors)
        self.assertIn("oferta", errors)
        bad = SimpleUploadedFile("x.pdf", PNG, content_type="application/pdf")
        res = self.client.post("/usta-bolish", {**form, "oferta": "1", "document": bad})
        self.assertIn("PDF yoki Word", res.context["state"]["errors"]["document"])
        self.assertFalse(Master.objects.filter(user=user).exists())

        res = self.client.post("/usta-bolish", {**form, "oferta": "1", "document": pdf()})
        self.assertRedirects(res, "/profil?ariza=1", fetch_redirect_response=False)
        master = Master.objects.get(user=user)
        self.assertEqual((master.status, master.document_name, master.bio), ("pending", "Portfolio Aziz.pdf", ""))
        self.assertIsNotNone(master.offer_accepted_at)
        self.assertTrue(os.path.exists(os.path.join(TMP_UPLOADS, "docs", master.document)))
        # Hujjat ommaga ochiq emas
        self.assertEqual(self.client.get(f"/api/uploads/{master.document}").status_code, 404)
        self.assertEqual(self.client.get(f"/admin/hujjat/{master.document}").status_code, 404)

        self.client.post("/chiqish")
        self.make_user(phone="+998900000001", role="admin")
        self.login(phone="900000001")
        page = self.client.get("/admin?tab=ustalar")
        self.assertContains(page, "Portfolio Aziz.pdf")
        doc = self.client.get(f"/admin/hujjat/{master.document}")
        self.assertEqual((doc.status_code, doc["Content-Type"]), (200, "application/pdf"))
        self.client.post("/admin?tab=ustalar", {"_action": "master_status", "id": master.id, "status": "approved"})
        master.refresh_from_db()
        user.refresh_from_db()
        self.assertEqual(master.status, "approved")
        self.assertEqual(user.role, "master")

    # ---------------- Buyurtma va to'lov ----------------

    def test_legacy_card_order_receipt_flow(self):
        """Eski (karta orqali) buyurtmalar uchun chek yuklash va admin tasdig'i hali ham ishlaydi."""
        from django.core.files.uploadedfile import SimpleUploadedFile

        user = self.make_user()
        order = PlanOrder.objects.create(user=user, plan="pdf", amount=49_000)
        self.make_user(phone="+998900000001", role="admin")
        self.login(phone="900000001")
        res = self.client.post("/admin?tab=tolov", {"_action": "payment_cards", "uzcardNumber": "8600 1234 5678 9012", "uzcardHolder": "Umid N"})
        self.assertTrue(res.context["states"]["payment_cards"]["ok"])
        res = self.client.post("/admin?tab=tolov", {"_action": "payment_cards", "humoNumber": "1234", "humoHolder": "X"})
        self.assertIn("humoNumber", res.context["states"]["payment_cards"]["errors"])

        self.client.post("/chiqish")
        self.login()
        self.assertContains(self.client.get(f"/buyurtma/{order.id}"), "8600 1234 5678 9012")
        res = self.client.post(f"/buyurtma/{order.id}", {"receipt": SimpleUploadedFile("chek.png", PNG, content_type="image/png")})
        self.assertTrue(res.context["receipt_state"]["ok"])

        # Begona foydalanuvchi buyurtmani ko'ra olmaydi
        self.client.post("/chiqish")
        self.make_user(phone="+998907778899")
        self.login(phone="907778899")
        self.assertEqual(self.client.get(f"/buyurtma/{order.id}").status_code, 404)

        self.client.post("/chiqish")
        self.login(phone="900000001")
        self.assertContains(self.client.get("/admin?tab=buyurtmalar"), "Chek yuklangan")
        self.client.post("/admin?tab=buyurtmalar", {"_action": "order_status", "id": order.id, "status": "paid"})
        order.refresh_from_db()
        self.assertEqual(order.status, "paid")


    # ---------------- Admin ----------------

    def test_admin_hidden_for_others_and_tabs_render(self):
        self.assertEqual(self.client.get("/admin").status_code, 404)
        self.make_user()
        self.login()
        self.assertEqual(self.client.get("/admin").status_code, 404)
        self.client.post("/chiqish")
        self.make_user(phone="+998900000001", role="admin")
        self.login(phone="900000001")
        for tab in ["bosh", "buyurtmalar", "sorovlar", "ustalar", "foydalanuvchilar", "tolov", "narxlar", "hududlar", "tizim"]:
            self.assertEqual(self.client.get(f"/admin?tab={tab}").status_code, 200, tab)

    def test_admin_prices_change_calculation(self):
        self.make_user(phone="+998900000001", role="admin")
        self.login(phone="900000001")
        page = self.client.get("/admin?tab=narxlar&hudud=toshkent-sh")
        form = {"_action": "prices", "region": "toshkent-sh"}
        for row in page.context["quality_rows"]:
            for cell in row["cells"]:
                form[cell["key"]] = str(cell["value"])
        for group in page.context["price_groups"]:
            for field in group["fields"]:
                form[field["key"]] = str(field["value"])
        form["apartment.materialsPerM2"] = "2 000 000"
        res = self.client.post("/admin?tab=narxlar&hudud=toshkent-sh", form)
        self.assertTrue(res.context["states"]["prices"]["ok"], res.context["states"]["prices"])

        # Toshkent shahrini yoqib, kalkulyatorda yangi narxni tekshiramiz
        self.client.post("/admin?tab=hududlar", {"_action": "toggle_region", "region": "toshkent-sh"})
        data = self.client.post("/api/hisob", {"roomType": "apartment", "quality": "standard", "area": "10", "region": "toshkent-sh"}).json()
        self.assertIn("20 000 000", data["html"])

        form["quality.premium.material"] = "0"
        res = self.client.post("/admin?tab=narxlar&hudud=toshkent-sh", form)
        self.assertIn("quality.premium.material", res.context["states"]["prices"]["errors"])

    def test_register_has_no_account_type_choice(self):
        from django.test import Client

        self.assertNotContains(Client().get("/royxat"), "Kim sifatida")

    def test_master_gets_master_menu(self):
        user = self.make_user()
        self.login()
        labels = lambda: [l["label"] for l in self.client.get("/dokonlar").context["nav_links"]]  # noqa: E731
        self.assertIn("Xonani jihozlash", labels())

        master = self.make_master(user=user, status="pending")
        self.assertEqual(labels(), ["Kabinet", "Ariza holati", "Portfolio", "Tariflar", "Do'konlar"])

        master.status = "approved"
        master.save()
        ContactRequest.objects.create(master=master, name="Mijoz", phone="+998901112244")
        res = self.client.get("/dokonlar")
        self.assertEqual([l["label"] for l in res.context["nav_links"]], ["Kabinet", "Kelgan so'rovlar", "Portfolio", "Tariflar", "Do'konlar"])
        self.assertEqual(res.context["nav_links"][1]["badge"], 1)

        # Bosh sahifa — usta kabineti (mijoz kalkulyatori emas)
        home = self.client.get("/")
        self.assertTemplateUsed(home, "pages/master_home.html")
        self.assertNotContains(home, "Smeta kalkulyatori")
        self.assertContains(home, f"/ustalar/{master.id}")
        self.assertEqual(home.context["new_count"], 1)

    def test_master_plans(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        user = self.make_user()
        User.objects.filter(id=user.id).update(balance=1_000_000)
        master = self.make_master(user=user)
        rival = self.make_master(phone="+998900001198", name="Boshqa Usta")
        Review.objects.create(master=rival, user=self.make_user(phone="+998901112299"), rating=5, comment="Zo'r usta")
        self.login()

        # Usta /narxlar da o'z tariflarini ko'radi, mijoz tariflari — ?mijoz=1
        page = self.client.get("/narxlar")
        self.assertTemplateUsed(page, "pages/pricing_master.html")
        self.assertContains(page, "Top usta")
        self.assertTemplateUsed(self.client.get("/narxlar?mijoz=1"), "pages/pricing.html")

        # Start: 5 ta rasmdan ortig'i rad etiladi
        png = lambda n: SimpleUploadedFile(n, PNG, content_type="image/png")  # noqa: E731
        res = self.client.post("/usta/portfolio", {"_action": "portfolio_add", "images": [png(f"{i}.png") for i in range(6)]})
        self.assertIn("Start", res.context["portfolio_state"]["errors"]["images"])

        # Reytingi past bo'lsa ham, Pro usta ro'yxatda oldinda
        order = lambda: [m.id for m in self.client.get("/ustalar").context["masters"] if m.id in (master.id, rival.id)]  # noqa: E731
        self.assertEqual(order(), [rival.id, master.id])
        res = self.client.post("/narxlar", {"plan": "usta_pro"})
        self.assertEqual(res.status_code, 302)
        master.refresh_from_db()
        self.assertEqual(master.active_plan, "usta_pro")
        self.assertEqual(User.objects.get(id=user.id).balance, 1_000_000 - 99_000)
        self.assertEqual(order(), [master.id, rival.id])
        self.assertEqual(self.client.get("/ustalar").context["masters"][0].id, master.id)
        self.assertContains(self.client.get(f"/ustalar/{master.id}"), "Pro")
        res = self.client.post("/usta/portfolio", {"_action": "portfolio_add", "images": [png(f"{i}.png") for i in range(6)]})
        self.assertRedirects(res, "/usta/portfolio?ok=1", fetch_redirect_response=False)

        # Uzaytirish kunlarni qo'shadi; Top'dan keyin Pro olib bo'lmaydi
        until = master.plan_until
        self.client.post("/narxlar", {"plan": "usta_pro"})
        master.refresh_from_db()
        self.assertEqual((master.plan_until - until).days, 30)
        self.client.post("/narxlar", {"plan": "usta_top"})
        res = self.client.post("/narxlar", {"plan": "usta_pro"})
        self.assertIn("Top usta", res.context["buy_state"]["message"])

        # Muddati o'tsa — yana Start
        Master.objects.filter(id=master.id).update(plan_until=master.plan_until.replace(year=2020))
        master.refresh_from_db()
        self.assertEqual(master.active_plan, "")

    def test_masters_best_first_and_paginated(self):
        Master.objects.all().delete()
        reviewers = [self.make_user(phone=f"+9989011100{i:02d}") for i in range(40)]
        newbie = self.make_master(phone="+998900000001", name="Yangi Usta")  # 1 ta 5★
        veteran = self.make_master(phone="+998900000002", name="Tajribali Usta")  # 40 ta, o'rtacha ~4.9
        Review.objects.create(master=newbie, user=reviewers[0], rating=5)
        for i, u in enumerate(reviewers):
            Review.objects.create(master=veteran, user=u, rating=4 if i < 4 else 5)
        for i in range(20):
            self.make_master(phone=f"+9989000010{i:02d}", name=f"Usta {i}")

        res = self.client.get("/ustalar")
        masters = res.context["masters"]
        self.assertEqual(len(masters), 12)
        self.assertEqual([masters[0].id, masters[1].id], [veteran.id, newbie.id])
        self.assertEqual(res.context["page"].paginator.count, 22)

        res = self.client.get("/ustalar?specialty=Kafelchi&sahifa=2")
        self.assertEqual(len(res.context["masters"]), 10)
        self.assertContains(res, "?specialty=Kafelchi&sahifa=1")
        self.assertEqual(self.client.get("/ustalar?sahifa=99").context["page"].number, 2)

    # ---------------- Do'konlar katalogi ----------------

    def test_shops_catalog_admin_and_public(self):
        from core.models import Shop

        self.assertGreater(Shop.objects.count(), 5)  # namuna do'konlar (seed)
        self.assertNotContains(self.client.get("/dokonlar"), "Do'koningizni qo'shing")
        Shop.objects.all().delete()
        self.assertContains(self.client.get("/dokonlar"), "tez orada qo'shiladi")
        self.make_user(phone="+998901112200", role="admin")
        self.login(phone="+998901112200")

        # Xato forma: nom va toifa yo'q
        res = self.client.post("/admin?tab=dokonlar", {"_action": "shop_add", "region": "samarqand"})
        self.assertIn("categories", res.context["states"]["shop"]["errors"])
        self.assertFalse(Shop.objects.exists())

        form = {"_action": "shop_add", "name": "Kafel Olami", "region": "samarqand", "district": "Samarqand shahri", "address": "Registon ko'chasi 5",
                "phone": "90 123 45 67", "telegram": "@kafel_olami", "categories": ["kafel", "santexnika"], "is_active": "1"}
        self.client.post("/admin?tab=dokonlar", form)
        shop = Shop.objects.get(name="Kafel Olami")
        self.assertEqual((shop.phone, shop.telegram, shop.category_keys), ("+998901234567", "kafel_olami", ["kafel", "santexnika"]))
        self.client.post("/admin?tab=dokonlar", {**form, "name": "Yashirin", "is_active": ""})
        for i in range(13):
            Shop.objects.create(name=f"Do'kon {i:02d}", categories="|material|")

        res = self.client.get("/dokonlar")
        self.assertEqual(res.context["page"].paginator.count, 14)  # yashirini ko'rinmaydi
        self.assertEqual(len(res.context["shops"]), 12)
        self.assertEqual([s.name for s in self.client.get("/dokonlar?toifa=kafel").context["shops"]], ["Kafel Olami"])
        page = self.client.get(f"/dokonlar/{shop.id}")
        self.assertContains(page, "https://t.me/kafel_olami")
        self.assertContains(page, "Kafel va keramika")
        self.assertEqual(self.client.get(f"/dokonlar/{Shop.objects.get(name='Yashirin').id}").status_code, 404)

        # Tahrirlash va o'chirish
        self.client.post("/admin?tab=dokonlar", {**form, "_action": "shop_save", "id": shop.id, "name": "Kafel Olami Plus"})
        shop.refresh_from_db()
        self.assertEqual(shop.name, "Kafel Olami Plus")
        self.client.post("/admin?tab=dokonlar", {"_action": "shop_delete", "id": shop.id})
        self.assertFalse(Shop.objects.filter(id=shop.id).exists())
        self.assertEqual(self.client.get("/admin?tab=dokonlar").status_code, 200)

    def test_shop_products(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from core.models import Shop, ShopProduct

        # Namuna do'konlarda katalog rasmli mahsulotlar bor
        demo = Shop.objects.get(name="Kafel Olami")
        self.assertTrue(demo.products.exclude(image="").exists())
        page = self.client.get(f"/dokonlar/{demo.id}")
        self.assertContains(page, "/static/catalog/")
        self.assertContains(page, "Kafel va keramika")
        self.assertIn(demo, [s for s in self.client.get("/dokonlar?q=keramogranit").context["shops"]])

        self.make_user(phone="+998901112200", role="admin")
        self.login(phone="+998901112200")
        shop = Shop.objects.create(name="Test Do'kon", categories="|pol|")
        res = self.client.post("/admin?tab=dokonlar", {"_action": "product_add", "shop": shop.id, "name": "Laminat", "price": "", "category": "pol"})
        self.assertIn("price", res.context["states"]["product"]["errors"])
        image = SimpleUploadedFile("l.png", PNG, content_type="image/png")
        res = self.client.post("/admin?tab=dokonlar", {"_action": "product_add", "shop": shop.id, "name": "Laminat 33", "price": "150 000",
                                                       "unit": "m²", "category": "pol", "in_stock": "1", "image": image})
        self.assertEqual(res.status_code, 302)
        product = ShopProduct.objects.get(shop=shop)
        self.assertEqual((product.price, product.unit, product.in_stock), (150000, "m²", True))
        self.assertTrue(product.image_url.startswith("/api/uploads/"))

        listing = self.client.get("/dokonlar?q=Test")
        card = [s for s in listing.context["shops"] if s.id == shop.id][0]
        self.assertEqual((card.product_count, card.price_from), (1, 150000))

        self.client.post("/admin?tab=dokonlar", {"_action": "product_stock", "id": product.id, "shop": shop.id})
        product.refresh_from_db()
        self.assertFalse(product.in_stock)
        self.assertContains(self.client.get(f"/dokonlar/{shop.id}"), "Tugagan")
        self.client.post("/admin?tab=dokonlar", {"_action": "product_delete", "id": product.id, "shop": shop.id})
        self.assertFalse(ShopProduct.objects.filter(id=product.id).exists())
        self.assertFalse(os.path.exists(os.path.join(TMP_UPLOADS, product.image)))

    def test_master_cabinet_pages(self):
        user = self.make_user()
        self.login()
        # Usta bo'lmagan — arizaga yo'naltiriladi
        self.assertRedirects(self.client.get("/usta/sorovlar"), "/usta-bolish", fetch_redirect_response=False)
        master = self.make_master(user=user)
        ContactRequest.objects.create(master=master, name="Mijoz Bir", phone="+998901112244", message="Vannaxona")
        done = ContactRequest.objects.create(master=master, name="Mijoz Ikki", phone="+998901112255", status="done")

        page = self.client.get("/usta/sorovlar")
        self.assertContains(page, "Mijoz Bir")
        self.assertContains(page, "Mijoz Ikki")
        self.assertEqual([r.id for r in self.client.get("/usta/sorovlar?holat=done").context["incoming"]], [done.id])
        new = ContactRequest.objects.get(name="Mijoz Bir")
        self.client.post("/usta/sorovlar", {"_action": "request_status", "id": new.id, "status": "contacted"})
        self.assertEqual(ContactRequest.objects.get(id=new.id).status, "contacted")

        self.assertEqual(self.client.get("/usta/portfolio").status_code, 200)
        nav = [l["href"] for l in self.client.get("/dokonlar").context["nav_links"]]
        self.assertIn("/usta/sorovlar", nav)
        self.assertIn("/usta/portfolio", nav)
        self.assertContains(self.client.get("/profil"), 'href="/usta/sorovlar"')

    def test_menu_active_on_section_and_subpages(self):
        from core.models import Shop

        active = lambda url: [l["label"] for l in self.client.get(url).context["nav_links"] if l["active"]]  # noqa: E731
        master = Master.objects.filter(status="approved").first()
        shop = Shop.objects.first()
        self.assertEqual(active("/ustalar"), ["Ustalar"])
        self.assertEqual(active(f"/ustalar/{master.id}"), ["Ustalar"])
        self.assertEqual(active(f"/dokonlar/{shop.id}"), ["Do'konlar"])
        self.assertEqual(active("/narxlar"), ["Narxlar"])
        self.assertEqual(active("/"), [])
        self.assertContains(self.client.get("/dokonlar"), 'aria-current="page"')

        user = self.make_user()
        self.make_master(user=user)
        self.login()
        self.assertEqual(active("/"), ["Kabinet"])
        self.assertEqual(active("/usta/portfolio"), ["Portfolio"])
        self.assertEqual(active("/narxlar"), ["Tariflar"])
        bottom = [b["label"] for b in self.client.get("/usta/sorovlar").context["bottom_nav"] if b["active"]]
        self.assertEqual(bottom, ["So'rovlar"])
        self.assertTrue(self.client.get("/profil").context["profile_active"])

    def test_footer_contacts_and_about_page(self):
        page = self.client.get("/ustalar")
        self.assertContains(page, 'href="tel:+998954825335"')
        self.assertContains(page, "+998 95 482 53 35")
        self.assertContains(page, 'href="https://t.me/uysmetabot"')
        self.assertNotContains(page, "90 000 00 00")
        # Footerdagi barcha ichki havolalar ishlaydi
        for url in ("/ai-loyiha", "/smetalar", "/ustalar", "/dokonlar", "/narxlar", "/biz-haqimizda", "/usta-bolish", "/oferta"):
            self.assertContains(page, f'href="{url}')
            self.assertIn(self.client.get(url).status_code, (200, 302), url)
        about = self.client.get("/biz-haqimizda")
        self.assertContains(about, 'id="aloqa"')
        self.assertContains(about, "@uysmetabot")
        self.assertContains(self.client.get("/oferta"), "+998 95 482 53 35")

    # ---------------- PWA (telefonga o'rnatish) ----------------

    def test_pwa_manifest_service_worker_and_offline(self):
        manifest = self.client.get("/manifest.webmanifest").json()
        self.assertEqual(manifest["display"], "standalone")
        sizes = {(i["sizes"], i.get("purpose", "any")) for i in manifest["icons"]}
        self.assertTrue({("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")} <= sizes)
        for icon in manifest["icons"]:
            self.assertEqual(self.client.get(icon["src"]).status_code, 200, icon["src"])

        sw = self.client.get("/sw.js")
        self.assertEqual(sw["Content-Type"], "application/javascript")
        self.assertEqual(sw["Service-Worker-Allowed"], "/")
        body = sw.content.decode()
        self.assertIn('"/offline"', body)
        self.assertIn("/static/css/app.css?v=", body)
        self.assertNotIn("&quot;", body)

        offline = self.client.get("/offline")
        self.assertContains(offline, "Internet yo")
        page = self.client.get("/")
        self.assertContains(page, 'rel="apple-touch-icon"')
        self.assertContains(page, "data-install-banner")
        self.assertContains(page, "js/pwa.js")

    # ---------------- Yordam chati ----------------

    def test_support_chat_guest_admin_reply(self):
        from core.models import SupportMessage, SupportThread

        page = self.client.get("/ustalar")
        self.assertContains(page, "data-support")
        self.assertContains(page, "jonli menejerlar")
        post = lambda body, client=self.client: client.post("/api/yordam", data=json.dumps(body), content_type="application/json")  # noqa: E731

        self.assertEqual(self.client.get("/api/yordam").json(), {"messages": [], "need_contact": True, "unread": 0})
        # Mehmon: birinchi xabarda ism va telefon majburiy
        res = post({"text": "Vannaxona smetasi qancha?"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("phone", res.json()["errors"])
        with mock.patch("core.support.notify_admins") as notify:
            with self.captureOnCommitCallbacks(execute=True):
                res = post({"text": "Vannaxona smetasi qancha?", "name": "Dilnoza", "phone": "90 111 22 33", "page": "/ustalar"})
            self.assertEqual(res.status_code, 200)
            self.assertIn("Yordam chat #", notify.call_args[0][0])
            self.assertIn("Dilnoza", notify.call_args[0][0])
        thread = SupportThread.objects.get()
        self.assertEqual((thread.name, thread.phone, thread.page), ("Dilnoza", "+998901112233", "/ustalar"))
        # Ikkinchi xabar — kontakt so'ralmaydi
        self.assertEqual(post({"text": "Ertaga ham bo'ladimi?"}).status_code, 200)
        self.assertFalse(self.client.get("/api/yordam").json()["need_contact"])

        # Admin panelda ko'rinadi va javob beradi
        admin = self.client_class()
        self.make_user(phone="+998900000009", role="admin")
        admin.post("/kirish", {"phone": "900000009", "password": "Parol-12"})
        tabs = {t["key"]: t for t in admin.get("/admin").context["tabs"]}
        self.assertEqual(tabs["yordam"]["badge"], 1)
        tab = admin.get(f"/admin?tab=yordam&chat={thread.id}")
        self.assertContains(tab, "Vannaxona smetasi qancha?")
        admin.post("/admin?tab=yordam", {"_action": "support_reply", "chat": thread.id, "text": "Taxminan 8 mln so'm"})
        self.assertTrue(SupportMessage.objects.filter(thread=thread, from_admin=True).exists())

        # Mijoz javobni ko'radi (o'qilmagan belgisi), oyna ochilganda o'qiladi
        data = self.client.get("/api/yordam").json()
        self.assertEqual(data["unread"], 1)
        self.assertEqual(data["messages"][-1], {**data["messages"][-1], "admin": True, "text": "Taxminan 8 mln so'm"})
        self.client.get("/api/yordam?read=1")
        self.assertEqual(self.client.get("/api/yordam").json()["unread"], 0)

        # Admin sahifalarida vidjet yo'q
        self.assertNotContains(admin.get("/admin"), "data-support-toggle")

    def test_support_reply_from_telegram(self):
        from core.models import SupportMessage, SupportThread
        from core.support import handle_admin_telegram_reply

        thread = SupportThread.objects.create(key="k1", name="Akmal", phone="+998901112233")
        self.make_user(phone="+998900000009", role="admin")
        TelegramLink.objects.create(phone="+998900000009", chat_id="42")
        TelegramLink.objects.create(phone="+998901112233", chat_id="43")
        msg = {"text": "Ertaga keling", "reply_to_message": {"text": f"💬 Yordam chat #{thread.id} — Akmal"}}
        with mock.patch("core.telegram.send_telegram_message"), mock.patch("core.support.notify_phone") as to_client:
            self.assertFalse(handle_admin_telegram_reply("43", msg))  # admin emas
            self.assertTrue(handle_admin_telegram_reply("42", msg))
            to_client.assert_called_once()
        self.assertEqual(SupportMessage.objects.get(thread=thread).text, "Ertaga keling")

    # ---------------- Usta portfoliosi ----------------

    def test_master_portfolio_add_show_delete(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from core.models import PortfolioWork

        user = self.make_user()
        master = self.make_master(user=user)
        other = self.make_master(phone="+998900001198", name="Boshqa Usta")
        self.login()

        png = lambda n: SimpleUploadedFile(n, PNG, content_type="image/png")  # noqa: E731
        res = self.client.post("/usta/portfolio", {"_action": "portfolio_add", "title": "Vannaxona, Yunusobod", "images": [png("a.png"), png("b.png")]})
        self.assertRedirects(res, "/usta/portfolio?ok=1", fetch_redirect_response=False)
        works = list(PortfolioWork.objects.filter(master=master))
        self.assertEqual(len(works), 2)
        self.assertTrue(all(os.path.exists(os.path.join(TMP_UPLOADS, w.image)) for w in works))

        # Rasm bo'lmagan fayl rad etiladi, hech narsa saqlanmaydi
        res = self.client.post("/usta/portfolio", {"_action": "portfolio_add", "images": [SimpleUploadedFile("x.png", b"not an image")]})
        self.assertIn("images", res.context["portfolio_state"]["errors"])
        self.assertEqual(PortfolioWork.objects.filter(master=master).count(), 2)

        page = self.client.get(f"/ustalar/{master.id}")
        self.assertContains(page, "Vannaxona, Yunusobod")
        self.assertEqual(len(page.context["portfolio_data"]), 2)
        self.assertContains(self.client.get("/ustalar"), works[0].image)

        # Boshqa ustaning ishini o'chira olmaydi
        foreign = PortfolioWork.objects.create(master=other, image="x" * 16 + ".png")
        self.client.post("/usta/portfolio", {"_action": "portfolio_delete", "id": foreign.id})
        self.assertTrue(PortfolioWork.objects.filter(id=foreign.id).exists())

        self.client.post("/usta/portfolio", {"_action": "portfolio_delete", "id": works[0].id})
        self.assertFalse(PortfolioWork.objects.filter(id=works[0].id).exists())
        self.assertFalse(os.path.exists(os.path.join(TMP_UPLOADS, works[0].image)))


class TelegramOtpTests(TestCase):
    """Telegram orqali tasdiqlash: /start <token> -> kontakt -> kod."""

    env = {"TELEGRAM_BOT_TOKEN": "123:abc", "TELEGRAM_BOT_USERNAME": "uysmeta_bot"}

    def setUp(self):
        patcher = mock.patch.dict(os.environ, self.env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.sent = []
        send = mock.patch("core.otp.send_telegram_message", side_effect=lambda chat, text, extra=None: self.sent.append((chat, text)))
        send.start()
        self.addCleanup(send.stop)

    def test_contact_flow(self):
        result = send_otp("+998901112233", "register", "telegram")
        self.assertTrue(result["ok"])
        self.assertFalse(result["delivered"])
        token = result["telegram_url"].split("start=")[1]

        handle_telegram_update({"update_id": 1, "message": {"message_id": 1, "chat": {"id": 555, "type": "private"}, "text": f"/start {token}"}})
        self.assertIn("Raqamimni yuborish", self.sent[-1][1])

        # Boshqa odamning kontakti rad etiladi
        handle_telegram_update(
            {"update_id": 2, "message": {"message_id": 2, "chat": {"id": 555, "type": "private"}, "from": {"id": 7}, "contact": {"phone_number": "998901112233", "user_id": 8}}}
        )
        self.assertIn("o'z", self.sent[-1][1])

        handle_telegram_update(
            {"update_id": 3, "message": {"message_id": 3, "chat": {"id": 555, "type": "private"}, "from": {"id": 7}, "contact": {"phone_number": "+998901112233", "user_id": 7}}}
        )
        code = self.sent[-1][1].split("<b>")[1].split("</b>")[0]
        self.assertTrue(TelegramLink.objects.filter(phone="+998901112233", chat_id="555").exists())
        self.assertEqual(verify_otp("+998901112233", "register", code), (True, ""))

    def _bot(self, update_id, chat=555, **message):
        handle_telegram_update({"update_id": update_id, "message": {"message_id": update_id, "chat": {"id": chat, "type": "private"}, **message}})

    def _start_login(self, client, next_path=""):
        res = client.post("/kirish/telegram", {"next": next_path} if next_path else {}, HTTP_ACCEPT="application/json")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["url"].startswith("https://t.me/uysmeta_bot?start=login_"))
        return data["token"]

    def test_bot_registers_new_user_and_site_logs_in(self):
        from django.test import Client

        from core.models import TelegramLogin, User

        sent = []
        with mock.patch("core.tg_login.send_telegram_message", side_effect=lambda chat, text, extra=None: sent.append((chat, text, extra))):
            browser = Client()
            token = self._start_login(browser)
            self.assertEqual(browser.get(f"/api/telegram-kirish/{token}").json(), {"status": "pending", "opened": False})

            self._bot(1, text=f"/start login_{token}")
            self.assertIn("Raqamimni yuborish", sent[-1][1])
            self.assertEqual(browser.get(f"/api/telegram-kirish/{token}").json()["opened"], True)

            # Boshqa odamning kontakti — rad etiladi (core.otp tekshiradi)
            self._bot(2, **{"from": {"id": 7}, "contact": {"phone_number": "998901112233", "user_id": 8}})
            self.assertFalse(User.objects.filter(phone="+998901112233").exists())

            self._bot(3, **{"from": {"id": 7, "first_name": "Akmal"}, "contact": {"phone_number": "+998901112233", "user_id": 7, "first_name": "Akmal", "last_name": "Karimov"}})
            user = User.objects.get(phone="+998901112233")
            self.assertEqual((user.name, user.password_hash), ("Akmal Karimov", "!telegram"))
            self.assertTrue(TelegramLink.objects.filter(phone="+998901112233", chat_id="555").exists())
            self.assertIn("Xush kelibsiz", sent[-2][1])
            self.assertIn(f"/kirish/telegram/{token}", sent[-1][2]["reply_markup"]["inline_keyboard"][0][0]["url"])

            # Boshqa brauzer (token cookie'si yo'q) — kira olmaydi
            stranger = Client()
            self.assertEqual(stranger.get(f"/api/telegram-kirish/{token}").json(), {"status": "expired"})
            self.assertEqual(stranger.get(f"/kirish/telegram/{token}").status_code, 200)
            self.assertEqual(stranger.get("/profil").status_code, 302)

            # Boshlagan brauzer — kiradi (bir marta)
            status = browser.get(f"/api/telegram-kirish/{token}").json()
            self.assertEqual(status, {"status": "ok", "redirect": "/smetalar?xush=1", "new": True})
            self.assertEqual(browser.get("/profil").status_code, 200)
            self.assertEqual(TelegramLogin.objects.get(token=token).status, "used")

            # Parol bilan kirmoqchi bo'lsa — tushunarli xabar
            res = Client().post("/kirish", {"phone": "901112233", "password": "Parol-12"})
            self.assertIn("Telegram orqali ro", res.context["state"]["message"])

    def test_bot_logs_in_existing_user_via_return_button(self):
        from django.test import Client

        from core.models import User
        from core.passwords import hash_password

        User.objects.create(phone="+998935556677", name="Dilnoza", password_hash=hash_password("Parol-12"))
        with mock.patch("core.tg_login.send_telegram_message"):
            browser = Client()
            token = self._start_login(browser, next_path="/ustalar")
            self._bot(1, chat=777, text=f"/start login_{token}")
            self._bot(2, chat=777, **{"from": {"id": 9}, "contact": {"phone_number": "998935556677", "user_id": 9}})
            self.assertEqual(User.objects.filter(phone="+998935556677").count(), 1)
            res = browser.get(f"/kirish/telegram/{token}")
            self.assertRedirects(res, "/ustalar", fetch_redirect_response=False)
            self.assertEqual(browser.get("/profil").status_code, 200)
            # Token ikkinchi marta ishlamaydi
            self.assertEqual(Client().get(f"/api/telegram-kirish/{token}").json(), {"status": "expired"})

    def test_expired_login_link(self):
        with mock.patch("core.tg_login.send_telegram_message") as send:
            handle_telegram_update({"update_id": 2, "message": {"message_id": 2, "chat": {"id": 1, "type": "private"}, "text": "/start login_nope"}})
            self.assertIn("eskirgan", send.call_args[0][1])

    def test_webhook_checks_secret(self):
        res = self.client.post("/api/telegram/webhook", data="{}", content_type="application/json")
        self.assertEqual(res.status_code, 403)
        from core.telegram import webhook_secret

        res = self.client.post(
            "/api/telegram/webhook",
            data=json.dumps({"update_id": 1, "message": {"message_id": 1, "chat": {"id": 1, "type": "private"}, "text": "/start"}}),
            content_type="application/json",
            headers={"X-Telegram-Bot-Api-Secret-Token": webhook_secret()},
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("UySmeta", self.sent[-1][1])
