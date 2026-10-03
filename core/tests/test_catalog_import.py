"""Hamkor do'konlar katalogi: import, rasmlarni qayta ishlash, bir turdagi ko'p mahsulotdan har loyihada boshqasi."""

import io
import json
import shutil
import tempfile
import zipfile
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from core.catalog import name_key
from core.catalog_import import dominant_color, import_catalog, process_pending_images, remove_background
from core.models import CatalogItem, RoomDesign, User
from core.passwords import hash_password
from core.planner import build_quick_plan
from core.scene3d import build_scene

TMP = tempfile.mkdtemp(prefix="uysmeta-catalog-")


def product_png(color=(200, 30, 30), background=(255, 255, 255)) -> bytes:
    """Oq fonda rangli "mahsulot" (o'rtadagi to'rtburchak)."""
    image = Image.new("RGB", (120, 80), background)
    image.paste(Image.new("RGB", (60, 40), color), (30, 20))
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def near(hex_color: str, rgb: tuple) -> bool:
    """Rang taxminan shu (chetlardagi yumshatish 1–2 birlik farq beradi)."""
    return all(abs(int(hex_color[1 + 2 * i : 3 + 2 * i], 16) - rgb[i]) <= 6 for i in range(3))


def csv_file(text: str) -> SimpleUploadedFile:
    return SimpleUploadedFile("katalog.csv", text.encode("utf-8"), content_type="text/csv")


@override_settings(UPLOAD_DIR=TMP)
class CatalogImportTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP, ignore_errors=True)

    def test_remove_background_and_color(self):
        image = Image.open(io.BytesIO(product_png()))
        cutout = remove_background(image)
        self.assertEqual(cutout.getpixel((2, 2))[3], 0)  # fon shaffof
        self.assertEqual(cutout.getpixel((60, 40))[3], 255)  # mahsulot qoladi
        self.assertTrue(near(dominant_color(cutout), (200, 30, 30)))

    def test_import_rows_zip_and_errors(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("rasmlar/divan-oslo.png", product_png((90, 110, 150)))
        archive.seek(0)
        text = (
            "nomi;tur;narx;sifat;dokon;havola;rasm\n"
            "Parda Velvet kulrang;parda;850 000;orta;Parda Market;https://example.uz/velvet;https://example.uz/velvet.png\n"
            "Divan Oslo;divan;5400000;premium;Mebel Uz;;divan-oslo.png\n"
            "Noma'lum narsa;uchar-gilam;100000;;;;\n"
            "Narxsiz parda;parda;;;;;\n"
        )
        result = import_catalog(csv_file(text), SimpleUploadedFile("r.zip", archive.getvalue()))
        self.assertEqual((result["created"], result["updated"], result["images"]), (2, 0, 2))
        self.assertEqual([n for n, _ in result["errors"]], [4, 5])

        curtain = CatalogItem.objects.get(name="Parda Velvet kulrang")
        self.assertEqual((curtain.kind, curtain.category, curtain.unit, curtain.origin), ("parda", "dekor", "to'plam", "partner"))
        self.assertEqual((curtain.price, curtain.quality, curtain.source_name), (850_000, "standard", "Parda Market"))

        # Rasmlar: URL yuklanadi (bu yerda soxta), ZIP'dagisi vaqtinchalik fayldan
        with mock.patch("core.catalog_import._download", return_value=product_png((30, 160, 60))):
            self.assertEqual(process_pending_images(), 2)
        curtain.refresh_from_db()
        sofa = CatalogItem.objects.get(name="Divan Oslo")
        self.assertTrue(curtain.cutout.endswith(".png") and curtain.image.startswith("/api/uploads/"))
        self.assertTrue(near(curtain.color, (30, 160, 60)))
        self.assertTrue(near(sofa.color, (90, 110, 150)))
        self.assertEqual(CatalogItem.objects.exclude(image_source="").count(), 0)

        # Qayta import — yangilanadi, takrorlanmaydi
        again = import_catalog(csv_file("nomi;tur;narx\nParda Velvet kulrang;parda;900000\n"))
        self.assertEqual((again["created"], again["updated"]), (0, 1))
        self.assertEqual(CatalogItem.objects.get(name="Parda Velvet kulrang").price, 900_000)

    def test_private_urls_are_not_downloaded(self):
        import_catalog(csv_file("nomi;tur;narx;rasm\nParda X;parda;500000;http://127.0.0.1/admin.png\n"))
        process_pending_images()
        item = CatalogItem.objects.get(name="Parda X")
        self.assertIn("ruxsat etilmagan", item.image_error)
        self.assertEqual(item.cutout, "")

    def test_each_variant_picks_other_curtain_and_scene_uses_its_photo(self):
        for i in range(12):
            CatalogItem.objects.create(
                name=f"Parda {i}", name_key=name_key(f"Parda {i}", "to'plam"), kind="parda", category="dekor", unit="to'plam",
                price=500_000 + i, quality="standard", origin="partner", color=f"#1{i:x}2030", cutout=f"cutout{i:02d}abcdefghijk.png",
            )
        args = dict(room_type="bedroom", area=16, height=2.7, budget="standard", windows=1, doors=1, groups=["dekor"])
        curtain = lambda plan: next(i for g in plan["groups"] for i in g["items"] if i["kind"] == "parda")
        picks = {curtain(build_quick_plan(**args, seed=f"loyiha-{n}"))["name"] for n in range(8)}
        self.assertGreater(len(picks), 3)  # har loyihada boshqa parda
        self.assertEqual(curtain(build_quick_plan(**args, seed="a"))["name"], curtain(build_quick_plan(**args, seed="a"))["name"])

        plan = build_quick_plan(**args, seed="loyiha-1")
        chosen = curtain(plan)
        user = User.objects.create(phone="+998900000055", name="Test", password_hash="!")
        design = RoomDesign.objects.create(public_id="x1", user=user, photo="p.jpg", area=16, status="done", plan_json=json.dumps(plan))
        scene, _, _ = build_scene(design)
        self.assertEqual(scene["parda"]["photo"], chosen["cutout"])
        self.assertEqual(scene["parda"]["color"], chosen["color"])

    def test_admin_import_page(self):
        User.objects.create(phone="+998900000001", name="Admin", role="admin", password_hash=hash_password("Parol-12"))
        self.client.post("/kirish", {"phone": "900000001", "password": "Parol-12"})
        page = self.client.get("/admin?tab=katalog")
        self.assertContains(page, "Hamkor do'kon mahsulotlarini import qilish")
        self.assertContains(page, "parda")
        template = self.client.get("/admin?tab=katalog&shablon=1")
        self.assertIn("nomi;tur;narx", template.content.decode("utf-8"))
        res = self.client.post("/admin?tab=katalog", {"_action": "catalog_import", "csv": csv_file("nomi;tur;narx\nDivan Milano;divan;4200000\n")})
        self.assertContains(res, "1 ta yangi")
        self.assertTrue(CatalogItem.objects.filter(name="Divan Milano", kind="divan").exists())


PAGE = """<html><script type="application/ld+json">[{"@context":"https://schema.org","@type":"ItemList","itemListElement":[
{"@type":"ListItem","position":1,"item":{"@type":"Product","name":"Artel UA43H3502 Smart Televizori","offers":{"@type":"Offer","price":5292000,"url":"https://shop/1"}}},
{"@type":"ListItem","position":2,"item":{"@type":"Product","name":"LG OLED65C6RLA Smart televizori","offers":{"@type":"Offer","price":26499000,"url":"https://shop/2"}}},
{"@type":"ListItem","position":3,"item":{"@type":"Product","name":"Samsung UE55U8000F Smart Televizori","offers":{"@type":"Offer","price":9877000,"url":"https://shop/3"}}},
{"@type":"ListItem","position":4,"item":{"@type":"Product","name":"Pult","offers":{"@type":"Offer","price":50000}}}
]}]</script></html>"""


class MarketPricesTests(TestCase):
    def test_collect_from_json_ld(self):
        from core import market_prices

        def fake_get(url, **kwargs):
            ok = "televizory" in url and "page=1" in url
            return mock.Mock(status_code=200 if ok else 404, text=PAGE if ok else "")

        CatalogItem.objects.create(name="LG OLED65C6RLA Smart televizori", name_key=name_key("LG OLED65C6RLA Smart televizori", "dona"),
                                   kind="tv-55", category="texnika", unit="dona", price=1, origin="partner")
        with mock.patch.object(market_prices.requests, "get", side_effect=fake_get), mock.patch.object(market_prices.time, "sleep"):
            result = market_prices.collect(max_pages=3)
        self.assertEqual((result["created"], result["skipped"]), (2, 1))  # pult (arzon) olinmaydi, hamkor narxi ustun
        tv = CatalogItem.objects.get(name="Artel UA43H3502 Smart Televizori")
        self.assertEqual((tv.kind, tv.price, tv.origin, tv.image), ("tv-43", 5_292_000, "market", ""))
        self.assertEqual(CatalogItem.objects.get(name="Samsung UE55U8000F Smart Televizori").kind, "tv-55")
        self.assertEqual(CatalogItem.objects.get(name__startswith="LG OLED65").price, 1)

    def test_washer_and_boiler_kinds(self):
        from core.market_prices import SOURCES, ac_kind, washer_kind

        self.assertEqual(washer_kind("Samsung WW80AGAS26AXLD Kir yuvish mashinasi"), "kir-mashina-10")
        self.assertEqual(washer_kind("Artel 6 kg kir yuvish"), "kir-mashina-7")
        self.assertEqual(ac_kind("LG B18TS Konditsioneri"), "konditsioner-18")
        self.assertIsNone(dict(SOURCES)["vodonagrevateli"]("Navien Deluxe S 13K Gaz koteli"))
