"""Real ko'rinish — bepul Cloudflare Workers AI (FLUX.2): so'rov tarkibi, natijani saqlash, kunlik limit."""

import base64
import io
import json
import os
import shutil
import tempfile
from unittest import mock

from django.test import TestCase, override_settings
from PIL import Image

from core.models import RoomDesign, User
from core.planner import build_quick_plan
from core.render import run_render
from core.render_cloudflare import color_name, style_en
from core.styles import style_plan

TMP = tempfile.mkdtemp(prefix="uysmeta-cf-")
ENV = {"CLOUDFLARE_ACCOUNT_ID": "acc1", "CLOUDFLARE_API_TOKEN": "tok", "GEMINI_API_KEY": ""}


def jpeg(size=(800, 600), color=(180, 170, 160)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "JPEG")
    return out.getvalue()


@override_settings(UPLOAD_DIR=TMP)
class CloudflareRenderTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP, ignore_errors=True)

    def setUp(self):
        os.makedirs(TMP, exist_ok=True)
        (open(os.path.join(TMP, "roomphoto1234567.jpg"), "wb")).write(jpeg())
        (open(os.path.join(TMP, "guidephoto123456.jpg"), "wb")).write(jpeg((1600, 1200), (90, 120, 150)))
        user = User.objects.create(phone="+998900000077", name="Test", password_hash="!")
        plan = build_quick_plan(room_type="living", area=18, height=2.7, budget="standard", windows=1, doors=1, groups=["mebel", "dekor"], seed="cf")
        self.design = RoomDesign(public_id="cf1", user=user, photo="roomphoto1234567.jpg", area=18, room_type="living", budget="standard",
                                 status="done", render_guide="guidephoto123456.jpg", render_status="processing")
        self.design.plan_json = json.dumps(style_plan(self.design, plan, use_ai=False))
        self.design.save()

    def test_style_descriptions_in_english(self):
        self.assertEqual(color_name("#24473a"), "dark green")
        text = style_en("parda", {"type": "tulle", "fabric": "velvet", "pattern": "floral", "color": "#7a2233"})
        self.assertIn("tulle", text)
        self.assertIn("burgundy velvet", text)

    def test_render_sends_guide_and_room_and_saves_photo(self):
        result = jpeg((1024, 768), (200, 190, 180))
        response = mock.Mock(status_code=200, ok=True)
        response.json.return_value = {"success": True, "result": {"image": base64.b64encode(result).decode()}}
        with mock.patch.dict(os.environ, ENV), mock.patch("core.render_cloudflare.requests.post", return_value=response) as post, \
                mock.patch("core.render.locate_items", return_value={}):
            run_render(self.design.id)
        args, kwargs = post.call_args
        self.assertIn("/accounts/acc1/ai/run/@cf/black-forest-labs/flux-2-klein-9b", args[0])
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer tok")
        self.assertEqual(set(kwargs["files"]), {"input_image_0", "input_image_1"})
        guide = Image.open(io.BytesIO(kwargs["files"]["input_image_0"][1]))
        self.assertLess(max(guide.size), 512)  # kirish rasmlari 512 dan kichik
        self.assertEqual((kwargs["data"]["width"], kwargs["data"]["height"]), ("1024", "768"))
        self.assertIn("curtain", kwargs["data"]["prompt"].lower())
        self.design.refresh_from_db()
        self.assertEqual((self.design.render_status, self.design.render_source), ("done", "photo"))
        saved = Image.open(os.path.join(TMP, self.design.render_photo))
        self.assertEqual(saved.size, (800, 600))  # asl rasm o'lchamiga keltirildi

    def test_daily_limit_is_reported(self):
        response = mock.Mock(status_code=429, ok=False)
        response.json.return_value = {"success": False, "errors": [{"message": "daily free allocation limit"}]}
        busy = mock.Mock(status_code=429, ok=False, headers={})
        with mock.patch.dict(os.environ, ENV), mock.patch("core.render_cloudflare.requests.post", return_value=response),                 mock.patch("core.render_cloudflare.requests.get", return_value=busy):
            run_render(self.design.id)
        self.design.refresh_from_db()
        self.assertEqual(self.design.render_status, "failed")
        self.assertIn("bepul AI rasm limiti", self.design.render_error)

    def test_without_any_key_falls_back_to_keyless_sample(self):
        sample = mock.Mock(status_code=200, ok=True, headers={"content-type": "image/jpeg"}, content=jpeg((1024, 768), (120, 140, 120)))
        env = {"CLOUDFLARE_ACCOUNT_ID": "", "CLOUDFLARE_API_TOKEN": "", "GEMINI_API_KEY": ""}
        with mock.patch.dict(os.environ, env), mock.patch("core.render_cloudflare.requests.get", return_value=sample) as get:
            run_render(self.design.id)
        prompt = get.call_args.args[0]
        self.assertIn("image.pollinations.ai/prompt/", prompt)
        self.assertIn("curtains", prompt)
        self.design.refresh_from_db()
        self.assertEqual((self.design.render_status, self.design.render_source, self.design.render_marks), ("done", "prompt", "{}"))
