"""Hisob mantig'i testlari — asl tests/estimate.test.ts bilan bir xil qiymatlar."""

from django.test import SimpleTestCase

from core.estimate import (
    DEFAULT_PRICES,
    calculate_estimate,
    estimate_to_text,
    format_money,
    format_qty,
    normalize_prices,
    validate_input,
)
from core.regions import region_default_prices

ROOM = {"length": 2.5, "width": 2, "height": 2.7, "area": 0}


class EstimateTests(SimpleTestCase):
    def test_bathroom_standard(self):
        r = calculate_estimate({"roomType": "bathroom", "quality": "standard", **ROOM})
        self.assertEqual(r["floorArea"], 5)
        self.assertEqual(r["perimeter"], 9)
        self.assertEqual(r["wallArea"], 22.7)
        self.assertEqual(r["materials"][0]["qty"], 30.5)  # kafel (22.7 + 5) × 1.1
        self.assertEqual(r["materials"][1]["qty"], 7)  # klej: 30.5 × 5 / 25 = 6.1 -> 7 qop
        self.assertEqual(r["materials"][2]["qty"], 1)  # gidroizolyatsiya: 7.7 × 1.5 / 15 -> 1 chelak
        self.assertEqual(r["materialsTotal"], 5_860_000)
        self.assertEqual(r["laborTotal"], 4_950_000)
        self.assertEqual(r["total"], 10_810_000)
        self.assertEqual(r["duration"], "10–14 kun")

    def test_kitchen_and_living(self):
        self.assertEqual(calculate_estimate({"roomType": "kitchen", "quality": "standard", **ROOM})["total"], 3_081_000)
        self.assertEqual(calculate_estimate({"roomType": "living", "quality": "standard", **ROOM})["total"], 2_990_000)

    def test_quality_factors_apply_separately(self):
        r = calculate_estimate({"roomType": "apartment", "quality": "premium", "length": 0, "width": 0, "height": 0, "area": 65})
        self.assertEqual(r["materialsTotal"], 114_400_000)  # 65 × 1 100 000 × 1.6
        self.assertEqual(r["laborTotal"], 54_925_000)  # 65 × 650 000 × 1.3
        self.assertEqual(r["duration"], "taxminan 54 kun")

    def test_validation(self):
        ok, errors = validate_input({"roomType": "bathroom", "quality": "standard", "length": "", "width": "0", "height": "-1"})
        self.assertFalse(ok)
        self.assertEqual(errors["length"], "O'lchamni metrda kiriting, masalan 2.5")
        self.assertIn("width", errors)
        self.assertIn("height", errors)

        ok, inp = validate_input({"roomType": "bathroom", "quality": "economy", "length": "2,5", "width": "2", "height": "2.7"})
        self.assertTrue(ok)
        self.assertEqual(inp["length"], 2.5)
        self.assertFalse(validate_input({"roomType": "hack", "quality": "standard"})[0])

        ok, errors = validate_input({"roomType": "bathroom", "quality": "standard", "length": "60", "width": "2", "height": "10"})
        self.assertEqual(errors["length"], "0.1–50 m oralig'ida kiriting")
        self.assertEqual(errors["height"], "1.5–6 m oralig'ida kiriting")

    def test_formatting_and_normalize(self):
        self.assertEqual(format_money(11_020_000).replace(" ", " "), "11 020 000 so'm")
        self.assertEqual(format_qty(30.5, "m²").replace(" ", " "), "30.5 m²")
        self.assertEqual(format_qty(7, "qop").replace(" ", " "), "7 qop")
        p = normalize_prices({"bathroom": {"tilePerM2": "150000", "groutKit": -5}, "quality": {"premium": {"material": 2}}})
        self.assertEqual(p["bathroom"]["tilePerM2"], 150_000)
        self.assertEqual(p["bathroom"]["groutKit"], DEFAULT_PRICES["bathroom"]["groutKit"])  # manfiy qiymat rad etiladi
        self.assertEqual(p["quality"]["premium"]["material"], 2)
        self.assertEqual(p["quality"]["premium"]["labor"], 1.3)

    def test_text_export(self):
        r = calculate_estimate({"roomType": "bathroom", "quality": "standard", **ROOM})
        text = estimate_to_text(r, "https://uysmeta.uz/smeta/abc")
        self.assertIn("Vannaxona · 2.5 × 2 × 2.7 m", text)
        self.assertIn("TAXMINIY JAMI: 10 810 000 so'm", text)
        self.assertTrue(text.endswith("https://uysmeta.uz/smeta/abc"))
        self.assertNotIn(" ", text)

    def test_region_defaults(self):
        self.assertEqual(region_default_prices("toshkent-sh"), DEFAULT_PRICES)
        samarqand = region_default_prices("samarqand")
        self.assertEqual(samarqand["bathroom"]["laborTilePerM2"], 85_000)
        self.assertEqual(samarqand["bathroom"]["tilePerM2"], 120_000)  # material o'zgarmaydi
