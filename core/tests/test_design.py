"""AI jihozlash: o'lchamlar o'zgarmasligi, narxlar faqat katalogdan, yo'q narsalar admin ro'yxatiga tushishi."""

import json
import os
import shutil
import tempfile
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from core.catalog import name_key
from core.design import DesignPlan, MissingItem, PlanItem, room_geometry
from core.models import CatalogItem, CatalogRequest, RoomDesign, User
from core.passwords import hash_password
from core.tests.test_flows import PNG

TMP_UPLOADS = tempfile.mkdtemp(prefix="uysmeta-design-")


def login_client(client, phone="900000077"):
    """AI loyiha faqat ro'yxatdan o'tganlarga — testlar oddiy foydalanuvchi bo'lib kiradi."""
    User.objects.create(phone=f"+998{phone}", name="Test Mijoz", password_hash=hash_password("Parol-12345"))
    client.post("/kirish", {"phone": phone, "password": "Parol-12345"})


def item_id(name: str, unit: str) -> int:
    return CatalogItem.objects.get(name_key=name_key(name, unit)).id


def fake_plan(**overrides) -> DesignPlan:
    data = dict(
        isRoomPhoto=True,
        roomType="bedroom",
        condition="cosmetic",
        summary="Yorug' xona, pol va devorlar tayyor.",
        layout="Krovat chap devorga, shkaf eshik yoniga.",
        items=[
            PlanItem(catalogId=item_id("Laminat 33-klass, 10–12 mm", "m²"), catalogName="Laminat 33-klass, 10–12 mm", basis="floor", quantity=999, placement="Butun pol", reason="O'rta byudjet"),
            PlanItem(catalogId=item_id("Laminat yotqizish ishi", "m²"), catalogName="Laminat yotqizish ishi", basis="floor", quantity=0, placement="", reason=""),
            PlanItem(catalogId=item_id("Plintus PVX", "metr"), catalogName="Plintus PVX", basis="perimeter", quantity=0, placement="", reason=""),
            PlanItem(catalogId=item_id("Bolalar krovati", "dona"), catalogName="Ikki kishilik krovat 160×200", basis="count", quantity=1, placement="Chap devor", reason=""),
            PlanItem(catalogId=item_id("Tumbochka (krovat yoni)", "dona"), catalogName="tumbochka (krovat yoni)", basis="count", quantity=2, placement="Krovat yonlarida", reason=""),
            PlanItem(catalogId=999_999, catalogName="Uchar gilam", basis="count", quantity=1, placement="", reason="mavjud bo'lmagan id"),
        ],
        missing=[MissingItem(name="Ko'zgu shkaf eshigi", category="mebel", unit="dona", quantity=1, reason="So'ralgan")],
        notes=["Parda uchun karniz o'rnating"],
    )
    data.update(overrides)
    return DesignPlan(**data)


@override_settings(UPLOAD_DIR=TMP_UPLOADS)
class DesignTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP_UPLOADS, ignore_errors=True)

    def setUp(self):
        env = mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key", "GEMINI_API_KEY": ""})
        env.start()
        self.addCleanup(env.stop)
        login_client(self.client)

    def post_design(self, **extra):
        data = {"area": "16", "height": "2.7", "roomType": "bedroom", "budget": "standard", "wishes": "Yotoqxona qilib ber", "mode": "ai"}
        data.update(extra)
        data["photo"] = SimpleUploadedFile("room.png", PNG, content_type="image/png")
        # Fon vazifasi tranzaksiya yakunlangach ishga tushadi — testda uni darhol bajaramiz
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post("/ai-loyiha", data)

    def test_other_variant_asks_ai_for_different_items(self):
        with mock.patch("core.design.ask_ai", return_value=fake_plan()):
            self.post_design()
        first = RoomDesign.objects.get()
        page = self.client.get(f"/ai-loyiha/{first.public_id}")
        self.assertContains(page, "Boshqa variant")

        with mock.patch("core.design.ask_ai", return_value=fake_plan()) as ask:
            with self.captureOnCommitCallbacks(execute=True):
                res = self.client.post(f"/ai-loyiha/{first.public_id}", {"_action": "variant"})
        second = RoomDesign.objects.exclude(id=first.id).get()
        self.assertRedirects(res, f"/ai-loyiha/{second.public_id}", fetch_redirect_response=False)
        self.assertEqual((second.variant, second.variant_of_id, second.photo, second.area), (2, first.id, first.photo, first.area))
        self.assertEqual(second.status, "done", second.error)
        # AI ga oldingi variantdagi narsalar va "boshqacha tanla" ko'rsatmasi yuborildi
        user_text = ask.call_args.args[2]
        self.assertIn("2-variant", user_text)
        self.assertIn("Plintus PVX", user_text)
        # Ikkala sahifada ham variantlar paneli
        self.assertContains(self.client.get(f"/ai-loyiha/{first.public_id}"), f'href="/ai-loyiha/{second.public_id}"')

        # Begona foydalanuvchi variant yarata olmaydi
        self.client.post("/chiqish")
        login_client(self.client, phone="900000078")
        self.assertEqual(self.client.post(f"/ai-loyiha/{first.public_id}", {"_action": "variant"}).status_code, 404)

    def test_geometry(self):
        geo = room_geometry(16, 2.7)
        self.assertEqual(geo["perimeter"], 16.0)
        self.assertEqual(geo["wallArea"], 39.8)  # 16 × 2.7 − 1.6 − 1.8

    def test_design_uses_entered_area_and_catalog_prices(self):
        with mock.patch("core.design.ask_ai", return_value=fake_plan()) as ask:
            res = self.post_design()
        design = RoomDesign.objects.get()
        self.assertRedirects(res, f"/ai-loyiha/{design.public_id}", fetch_redirect_response=False)
        self.assertEqual(design.status, "done", design.error)

        # AI'ga yuborilgan matnda foydalanuvchi maydoni va so'rovi bor
        user_text = ask.call_args.args[2]
        self.assertIn("16.0 m²", user_text)
        self.assertIn("Yotoqxona qilib ber", user_text)

        items = {i["name"]: i for g in design.plan["groups"] for i in g["items"]}
        laminat = items["Laminat 33-klass, 10–12 mm"]
        self.assertEqual(laminat["quantity"], 17.6)  # AI 999 desa ham: 16 m² × 1.1 zaxira
        self.assertEqual(laminat["unitPrice"], 150_000)  # narx katalogdan
        self.assertEqual(items["Laminat yotqizish ishi"]["quantity"], 16.0)  # ishga zaxira qo'shilmaydi
        self.assertEqual(items["Plintus PVX"]["quantity"], 16.6)  # (16 − 0.9) × 1.1
        self.assertEqual(items["Tumbochka (krovat yoni)"]["quantity"], 2)
        # id adashgan (bolalar krovati) — nom bo'yicha to'g'ri mahsulot olindi
        self.assertIn("Ikki kishilik krovat 160×200", items)
        self.assertNotIn("Bolalar krovati", items)
        self.assertEqual(len(items), 5)  # mavjud bo'lmagan id tashlab ketildi
        self.assertEqual(design.total, sum(i["total"] for i in items.values()))

        # Katalogda yo'q narsa admin ro'yxatiga tushdi
        self.assertTrue(CatalogRequest.objects.filter(name="Ko'zgu shkaf eshigi").exists())
        self.assertEqual(CatalogItem.objects.get(name="Ikki kishilik krovat 160×200").times_used, 1)

        page = self.client.get(f"/ai-loyiha/{design.public_id}")
        self.assertContains(page, "Loyiha tayyor")
        self.assertContains(page, "Ko&#x27;zgu shkaf eshigi")
        self.assertEqual(self.client.get(f"/api/ai-loyiha/{design.public_id}").json()["status"], "done")

    def test_not_a_room_photo_fails_gracefully(self):
        with mock.patch("core.design.ask_ai", return_value=fake_plan(isRoomPhoto=False, items=[], missing=[])):
            self.post_design()
        design = RoomDesign.objects.get()
        self.assertEqual(design.status, "failed")
        self.assertContains(self.client.get(f"/ai-loyiha/{design.public_id}"), "Rasmda xona aniqlanmadi")

    def test_validation_and_disabled_ai(self):
        res = self.post_design(area="0")
        self.assertIn("area", res.context["state"]["errors"])
        res = self.client.post("/ai-loyiha", {"area": "12", "roomType": "living", "groups": ["mebel"]})
        self.assertIn("photo", res.context["state"]["errors"])
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            res = self.post_design()
            self.assertIn("ulanmagan", res.context["state"]["message"])
        self.assertFalse(RoomDesign.objects.exists())
        # Tezkor rejim AI'siz ham ishlaydi, lekin xona turi va bo'lim shart
        res = self.post_design(mode="", roomType="")
        self.assertIn("roomType", res.context["state"]["errors"])
        self.assertIn("groups", res.context["state"]["errors"])
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "", "GEMINI_API_KEY": "g-key"}):
            self.assertEqual(self.client.get("/ai-loyiha").context["ai_ready"], True)
        self.assertFalse(RoomDesign.objects.exists())

    def test_admin_prices_missing_item(self):
        CatalogRequest.objects.create(name="Ko'zgu", name_key=name_key("Ko'zgu", "dona"), unit="dona", category="dekor")
        User.objects.create(phone="+998900000001", name="Admin", role="admin", password_hash=hash_password("Parol-12345"))
        self.client.post("/kirish", {"phone": "900000001", "password": "Parol-12345"})
        self.assertContains(self.client.get("/admin?tab=katalog"), "Ko&#x27;zgu")
        request = CatalogRequest.objects.get()
        self.client.post(
            "/admin?tab=katalog",
            {"_action": "catalog_add", "request_id": request.id, "name": "Ko'zgu", "unit": "dona", "category": "dekor", "quality": "standard", "price": "450 000"},
        )
        item = CatalogItem.objects.get(name="Ko'zgu")
        self.assertEqual(item.price, 450_000)
        self.assertTrue(item.verified)
        self.assertFalse(CatalogRequest.objects.exists())

        # Taxminiy narxni tasdiqlash
        rough = CatalogItem.objects.filter(verified=False).first()
        self.client.post("/admin?tab=katalog", {"_action": "catalog_save", "id": rough.id, "price": "123000", "quality": "standard"})
        rough.refresh_from_db()
        self.assertEqual((rough.price, rough.verified), (123_000, True))


class GeminiDesignTests(TestCase):
    """Bepul Gemini yo'li: so'rov tuzilishi va javobni DesignPlan'ga o'girish."""

    def test_gemini_request_and_parse(self):
        plan = fake_plan().model_dump()
        response = mock.Mock(status_code=200, ok=True)
        response.json.return_value = {"candidates": [{"content": {"parts": [{"text": json.dumps(plan)}]}, "finishReason": "STOP"}]}
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "g-key"}), mock.patch("core.ai_gemini.requests.post", return_value=response) as post:
            from core.design import ask_ai

            result = ask_ai(PNG, "image/png", "Pol maydoni: 16 m²")
        self.assertEqual(result.roomType, "bedroom")
        body = post.call_args.kwargs["json"]
        self.assertIn("KATALOG", body["systemInstruction"]["parts"][0]["text"])
        self.assertEqual(body["generationConfig"]["responseSchema"]["properties"]["items"]["type"], "ARRAY")
        self.assertEqual(body["contents"][0]["parts"][1]["text"], "Pol maydoni: 16 m²")

    def test_gemini_limit_error(self):
        response = mock.Mock(status_code=429, ok=False)
        response.json.return_value = {"error": {"message": "quota"}}
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "g-key"}), mock.patch("core.ai_gemini.requests.post", return_value=response):
            from core.design import DesignError, ask_ai

            with self.assertRaisesMessage(DesignError, "bepul limiti"):
                ask_ai(PNG, "image/png", "x")


@override_settings(UPLOAD_DIR=TMP_UPLOADS)
class QuickPlanTests(TestCase):
    """Tezkor rejim: rooms.json qoidalari, bir zumda, AI'siz."""

    def setUp(self):
        login_client(self.client)

    def test_guest_is_sent_to_register(self):
        self.client.post("/chiqish")
        res = self.client.post("/ai-loyiha", {"area": "12"})
        self.assertRedirects(res, "/royxat?next=%2Fai-loyiha", fetch_redirect_response=False)
        self.assertContains(self.client.get("/ai-loyiha"), 'href="/royxat?next=/ai-loyiha"')

    def post(self, **extra):
        data = {"area": "20", "height": "2.7", "roomType": "living", "budget": "standard", "windows": "2", "doors": "1",
                "groups": ["pol", "mebel", "texnika", "dekor"]}
        data.update(extra)
        data["photo"] = SimpleUploadedFile("room.png", PNG, content_type="image/png")
        return self.client.post("/ai-loyiha", data)

    def test_quick_plan_is_instant_and_uses_entered_area(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "", "GEMINI_API_KEY": ""}):
            res = self.post()
        design = RoomDesign.objects.get()
        self.assertRedirects(res, f"/ai-loyiha/{design.public_id}", fetch_redirect_response=False)
        self.assertEqual((design.status, design.mode), ("done", "tez"))
        items = {i["key"]: i for g in design.plan["groups"] for i in g["items"]}
        self.assertEqual(items["laminat-33"]["quantity"], 22.0)  # 20 m² × 1.1
        self.assertEqual(items["ish-laminat"]["quantity"], 20.0)
        self.assertEqual(items["parda"]["quantity"], 2)  # derazalar soni
        self.assertIn("burchak-divan", items)  # standard byudjet
        self.assertIn("stelaj", items)  # when: floor>=16
        self.assertIn("konditsioner-12", items)  # when: floor<=20
        self.assertNotIn("konditsioner-18", items)
        # Belgilanmagan bo'limlar kirmaydi
        self.assertNotIn("natyajnoy", items)
        self.assertNotIn("devor-boyoq", items)
        self.assertEqual(design.total, sum(i["total"] for i in items.values()))
        self.assertContains(self.client.get(f"/ai-loyiha/{design.public_id}"), "Burchak divan")

    def test_variant_without_ai_uses_other_seed(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "", "GEMINI_API_KEY": ""}):
            self.post()
            first = RoomDesign.objects.get()
            res = self.client.post(f"/ai-loyiha/{first.public_id}", {"_action": "variant"})
        second = RoomDesign.objects.exclude(id=first.id).get()
        self.assertRedirects(res, f"/ai-loyiha/{second.public_id}", fetch_redirect_response=False)
        self.assertEqual((second.mode, second.status, second.variant, second.variant_of_id), ("tez", "done", 2, first.id))
        self.assertGreater(second.total, 0)

    def test_every_room_template_references_existing_items(self):
        from core.planner import build_quick_plan, group_choices, load_rooms

        keys = set(CatalogItem.objects.values_list("key", flat=True))
        for room_type, room in load_rooms()["rooms"].items():
            for rule in room["rules"]:
                refs = rule["item"].values() if isinstance(rule["item"], dict) else [rule["item"]]
                for ref in refs:
                    self.assertTrue(ref is None or ref in keys, f"{room_type}: {ref}")
            for budget in ("economy", "standard", "premium"):
                for area in (3, 12, 40):
                    plan = build_quick_plan(room_type=room_type, area=area, height=2.7, budget=budget, windows=1, doors=1, groups=list(group_choices()))
                    self.assertGreater(plan["total"], 0, f"{room_type} {budget} {area}")

    def test_formula_evaluator_is_safe(self):
        from core.planner import evaluate

        self.assertEqual(evaluate("ceil(wall*1.2/20)", {"wall": 39.8}), 3)
        self.assertEqual(evaluate("1+(floor>=22)", {"floor": 24}), 2)
        for bad in ("__import__('os')", "floor.__class__", "open('x')", "[1,2]"):
            with self.assertRaises(ValueError):
                evaluate(bad, {"floor": 1})
