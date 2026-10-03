"""Jihozlash variantlari (styles.json): 100+ variant, loyihaga tanlash, «Boshqa variant» takrorlamasligi, AI tanlovi."""

import json
import os
from unittest import mock

from django.test import TestCase

from core.catalog import catalog_kinds
from core.models import RoomDesign, User
from core.planner import build_quick_plan
from core.scene3d import build_scene
from core.styles import load_styles, pick_with_ai, style_plan


class StylesLibraryTests(TestCase):
    def test_every_family_has_100_plus_unique_variants(self):
        data = load_styles()
        ids = [i["id"] for i in data["items"]]
        self.assertEqual(len(ids), len(set(ids)))
        for family, info in data["families"].items():
            items = [i for i in data["items"] if i["family"] == family]
            self.assertGreaterEqual(len(items), 100, family)
            self.assertEqual(len({i["name"] for i in items}), len(items), f"{family}: takroriy nom")
            for kind in info["kinds"]:
                self.assertIn(kind, catalog_kinds(), f"{family}: {kind} katalogda yo'q")
            for item in items:
                self.assertIn(item["quality"], ("economy", "standard", "premium"))
                self.assertRegex(item["params"]["color"], r"^#[0-9a-f]{6}$")


class StylePlanTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(phone="+998900000066", name="Test", password_hash="!")

    def design(self, public_id, **extra):
        fields = dict(public_id=public_id, user=self.user, photo="p.jpg", area=18, room_type="living", budget="standard", status="done")
        fields.update(extra)
        return RoomDesign(**fields)

    def quick_plan(self, seed):
        return build_quick_plan(room_type="living", area=18, height=2.7, budget="standard", windows=1, doors=1,
                                groups=["pol", "devor", "mebel", "dekor", "eshik"], seed=seed)

    def test_plan_gets_exact_variant_for_each_item_and_scene_uses_it(self):
        design = self.design("s1")
        plan = style_plan(design, self.quick_plan("s1"), use_ai=False)
        self.assertIn("parda", plan["styles"])
        self.assertIn("yumshoq", plan["styles"])
        rows = {r.get("kind"): r for g in plan["groups"] for r in g["items"]}
        self.assertTrue(rows["parda"]["styleName"])
        design.plan_json = json.dumps(plan)
        design.save()
        scene, legend, _ = build_scene(design)
        curtain = load_styles()["items"][[i["id"] for i in load_styles()["items"]].index(plan["styles"]["parda"])]
        self.assertEqual(scene["parda"]["style"], curtain["params"])
        self.assertEqual(scene["parda"]["color"], curtain["params"]["color"])
        self.assertTrue(any(n["name"] == curtain["name"] for n in legend))

    def test_variant_never_repeats_previous_choices(self):
        root = self.design("v1")
        root.plan_json = json.dumps(style_plan(root, self.quick_plan("v1"), use_ai=False))
        root.save()
        seen = {fam: {sid} for fam, sid in root.plan["styles"].items()}
        for n in range(2, 6):
            variant = self.design(f"v{n}", variant_of=root, variant=n)
            plan = style_plan(variant, self.quick_plan(f"v{n}"), use_ai=False)
            for fam, sid in plan["styles"].items():
                self.assertNotIn(sid, seen.setdefault(fam, set()), f"{fam} takrorlandi")
                seen[fam].add(sid)
            variant.plan_json = json.dumps(plan)
            variant.save()

    def test_ai_choice_is_used_and_unknown_ids_are_ignored(self):
        design = self.design("a1")
        plan = self.quick_plan("a1")
        families = ["parda", "eshik"]
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}), mock.patch("core.ai_gemini.gemini_json") as ask:
            def answer(prompt, parts, schema, **kw):
                text = parts[-1]["text"]
                curtain = next(line.split(" | ")[0] for line in text.splitlines() if line.startswith("parda-"))
                return True, {"choices": [{"family": "parda", "id": curtain}, {"family": "eshik", "id": "eshik-999"}]}
            ask.side_effect = answer
            chosen = pick_with_ai(design, plan, families, "a1", {})
        text = ask.call_args.args[1][-1]["text"]
        self.assertIn(chosen["parda"], text)  # AI ro'yxatdagisini tanladi
        self.assertTrue(chosen["eshik"].startswith("eshik-"))  # noto'g'ri id — tasodifiy zaxira
        self.assertNotEqual(chosen["eshik"], "eshik-999")
