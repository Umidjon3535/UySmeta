"""Ichki hamyon: bonus, tarif xaridi, pul yechish, tarif imkoniyatlari (PDF, 3D)."""

import json
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from core.models import Estimate, PlanOrder, RoomDesign, User, WalletTransaction, WithdrawRequest
from core.passwords import hash_password
from core.tests.test_flows import PNG

TMP = tempfile.mkdtemp(prefix="uysmeta-wallet-")


@override_settings(UPLOAD_DIR=TMP, WALLET_SIGNUP_BONUS=300_000)
class WalletTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP, ignore_errors=True)

    def register(self, phone="901112233"):
        form = {"name": "Dilnoza", "surname": "Karimova", "phone": phone, "password": "Parol-12", "passwordConfirm": "Parol-12", "oferta": "1"}
        code = self.client.post("/royxat", {**form, "channel": "dev"}).context["state"]["data"]["devCode"]
        self.client.post("/royxat", {**form, "codeSent": "1", "channel": "dev", "code": code})
        return User.objects.get(phone=f"+998{phone}")

    def test_signup_bonus_once(self):
        user = self.register()
        self.assertEqual(user.balance, 300_000)
        self.assertEqual(WalletTransaction.objects.filter(user=user, kind="bonus").count(), 1)
        from core.wallet import grant_signup_bonus

        self.assertFalse(grant_signup_bonus(user))  # ikkinchi marta berilmaydi
        user.refresh_from_db()
        self.assertEqual(user.balance, 300_000)
        self.assertContains(self.client.get("/hamyon"), "Ro&#x27;yxatdan o&#x27;tish bonusi")

    def test_buy_plan_from_balance_is_instant_and_unlocks_features(self):
        user = self.register()
        Estimate.objects.create(
            public_id="abcdefgh12", user=user, room_type="bathroom", quality="standard",
            input_json="{}", result_json=json.dumps(self.sample_result()), total=10_810_000,
        )
        # Tarifsiz — PDF narxlar sahifasiga yo'naltiradi
        self.assertRedirects(self.client.get("/smeta/abcdefgh12/pdf"), "/narxlar?kerak=pdf", fetch_redirect_response=False)

        res = self.client.post("/narxlar", {"plan": "pdf"})
        order = PlanOrder.objects.get(user=user)
        self.assertRedirects(res, f"/buyurtma/{order.id}?yangi=1", fetch_redirect_response=False)
        self.assertEqual(order.status, "paid")  # admin tasdiqlashi shart emas
        user.refresh_from_db()
        self.assertEqual((user.balance, user.plan), (251_000, "pdf"))
        self.assertContains(self.client.get(f"/buyurtma/{order.id}"), "tarif faol")

        pdf = self.client.get("/smeta/abcdefgh12/pdf")
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))

        # Qayta sotib olib bo'lmaydi; 3D'ga o'tishda faqat farq to'lanadi
        res = self.client.post("/narxlar", {"plan": "pdf"})
        self.assertIn("allaqachon", res.context["buy_state"]["message"])
        self.client.post("/narxlar", {"plan": "design3d"})
        user.refresh_from_db()
        self.assertEqual((user.balance, user.plan), (251_000 - 150_000, "design3d"))

    def test_insufficient_balance(self):
        user = self.register()
        User.objects.filter(id=user.id).update(balance=10_000)
        res = self.client.post("/narxlar", {"plan": "design3d"})
        self.assertIn("yetarli emas", res.context["buy_state"]["message"])
        self.assertFalse(PlanOrder.objects.exists())

    def test_withdraw_hold_reject_refund_and_done(self):
        user = self.register()
        res = self.client.post("/hamyon", {"amount": "999 999", "card": "8600 1234 5678 9012", "holder": "Dilnoza K"})
        self.assertIn("amount", res.context["state"]["errors"])
        res = self.client.post("/hamyon", {"amount": "100 000", "card": "1234", "holder": "D"})
        self.assertIn("card", res.context["state"]["errors"])

        self.client.post("/hamyon", {"amount": "100 000", "card": "8600 1234 5678 9012", "holder": "Dilnoza K"})
        first = WithdrawRequest.objects.get()
        user.refresh_from_db()
        self.assertEqual((first.status, user.balance), ("pending", 200_000))

        User.objects.create(phone="+998900000001", name="Admin", role="admin", password_hash=hash_password("Parol-12"))
        self.client.post("/chiqish")
        self.client.post("/kirish", {"phone": "900000001", "password": "Parol-12"})
        self.assertContains(self.client.get("/admin?tab=hamyon"), "8600 1234 5678 9012")
        self.client.post("/admin?tab=hamyon", {"_action": "withdraw_reject", "id": first.id, "note": "Karta egasi mos emas"})
        first.refresh_from_db()
        user.refresh_from_db()
        self.assertEqual((first.status, user.balance), ("rejected", 300_000))  # pul qaytdi

        second = WithdrawRequest.objects.create(user=user, amount=50_000, card_number="8600123456789012", card_holder="D")
        self.client.post("/admin?tab=hamyon", {"_action": "withdraw_done", "id": second.id})
        second.refresh_from_db()
        self.assertEqual(second.status, "done")
        # Takror bosish hech narsani o'zgartirmaydi
        self.client.post("/admin?tab=hamyon", {"_action": "withdraw_reject", "id": second.id})
        user.refresh_from_db()
        self.assertEqual(user.balance, 300_000)

    @override_settings(WALLET_BONUS_WITHDRAWABLE=False)
    def test_bonus_not_withdrawable_when_disabled(self):
        self.register()
        res = self.client.post("/hamyon", {"amount": "50000", "card": "8600123456789012", "holder": "Dilnoza"})
        self.assertIn("amount", res.context["state"]["errors"])

    def test_design_pdf_and_3d(self):
        user = self.register()
        data = {
            "area": "16", "height": "2.7", "roomType": "bedroom", "budget": "standard", "windows": "1", "doors": "1",
            "groups": ["pol", "mebel", "texnika", "dekor"], "photo": SimpleUploadedFile("r.png", PNG, content_type="image/png"),
        }
        self.client.post("/ai-loyiha", data)
        design = RoomDesign.objects.get()
        self.assertRedirects(self.client.get(f"/ai-loyiha/{design.public_id}/3d"), "/narxlar?kerak=design3d", fetch_redirect_response=False)
        self.client.post("/narxlar", {"plan": "design3d"})
        page = self.client.get(f"/ai-loyiha/{design.public_id}/3d")
        self.assertContains(page, "Ikki kishilik krovat")
        self.assertContains(page, "Dizayner maslahatlari")
        pdf = self.client.get(f"/ai-loyiha/{design.public_id}/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        user.refresh_from_db()
        self.assertEqual(user.balance, 101_000)

    @staticmethod
    def sample_result():
        from core.estimate import calculate_estimate

        return calculate_estimate({"roomType": "bathroom", "quality": "standard", "length": 2.5, "width": 2, "height": 2.7, "area": 0})
