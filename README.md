# UySmeta — Django versiyasi

Ta'mirlash smetasi xizmati: foydalanuvchi xona o'lchamlarini kiritadi, materiallar, usta ish haqi va muddat mahalliy narxlarda hisoblanadi, keyin tekshirilgan usta topiladi.

Bu — `../web` dagi Next.js ilovasining Python/Django'ga to'liq ko'chirilgan nusxasi. Sahifalar, URL'lar, dizayn, hisob-kitob va baza sxemasi o'zgarmagan.

**Texnologiyalar:** Python 3.12+ · Django 5.2 · PostgreSQL (yoki lokal SQLite) · Tailwind CSS 4 (oldindan yig'ilgan) · Telegram Bot API · Eskiz.uz (SMS, ixtiyoriy) · Gemini / Claude (rasm tahlili, ixtiyoriy)

## Lokal ishga tushirish

```bash
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # DJANGO_DEBUG=true qoldiring
python manage.py migrate        # jadvallar + administrator + namuna ustalar
python manage.py runserver      # http://localhost:8000
```

Hech narsa sozlamasangiz ham ishlaydi: baza — `./data/uysmeta.sqlite3`, rasmlar — `./data/uploads`, tasdiqlash kodi — "test rejimi" (kod ekranda chiqadi). Bazani noldan boshlash: `data/` papkasini o'chirib, `migrate` ni qayta ishga tushiring.

Testlar: `python manage.py test core`

## Xonani jihozlash (`/ai-loyiha`)

Foydalanuvchi xona rasmini yuklaydi, xona turini, aniq pol maydoni (m²), ship balandligi, derazalar va eshiklar sonini kiritadi va nima kerakligini belgilaydi (pol, devorlar, ship, elektr, santexnika, mebel, texnika, dekor, eshiklar). Natijada narsalar ro'yxati chiqadi: rasmi, soni, narxi, qayerga qo'yilishi va umumiy summa.

**Tezkor rejim (sukut bo'yicha, bepul, ~0,2 soniya)** — AI'siz, JSON qoidalar bo'yicha:
- `core/data/catalog.json` — barcha mahsulot va xizmatlar: narx, narx oralig'i, sifat, manba, rasm qidiruv so'zi.
- `core/data/rooms.json` — har xona turi uchun ro'yxat va miqdor formulalari (`floor*1.1`, `ceil(wall*1.2/20)`, `when: floor>=16` ...). Formulalarni `core/planner.py` xavfsiz hisoblaydi.
- `core/data/image_credits.json` + `static/catalog/*.jpg` — mahsulot rasmlari (Wikimedia Commons, erkin litsenziya, muallifi ko'rsatiladi).
- Narx yoki qoida o'zgartirish: JSON'ni tahrirlang va `python manage.py seed` ni ishga tushiring. Admin panelda o'zgartirilgan narxlar JSON bilan ustidan yozilmaydi.
- Yangi rasmlar: `pip install -r requirements-dev.txt`, so'ng `python manage.py fetch_catalog_images` (yoki `--key divan --pick 2` bilan boshqa variantni tanlash).

**AI rejimi (ixtiyoriy)** — formada "AI bilan tahlil" belgilansa: AI rasmga qarab tanlaydi (Gemini bepul yoki Claude). Narxlar baribir faqat bazadan, miqdorlar kiritilgan o'lchamlardan hisoblanadi. Bepul Gemini ko'pincha band bo'lgani uchun 1–3 daqiqa ketishi mumkin. Katalogda yo'q narsa so'ralsa, admin panel → **"Katalog (AI)"** ga tushadi.

Bazadagi ba'zi narxlar "taxminiy" (manbasi aniq topilmagan) — admin panel → "Katalog (AI)" da tekshirib tasdiqlang.

## Real ko'rinish (`/ai-loyiha/<id>/real`)

Loyiha sahifasining yuqorisida foydalanuvchi yuklagan xona rasmi **loyiha bo'yicha jihozlangan holda** ko'rsatiladi ("3D dizayn" tarifida):

1. `core/room_geometry.py` — Gemini tahlil modeli (`gemini-3.5-flash`, bepul tarifda ham ishlaydi) rasmdagi orqa devor burchaklarini, deraza va eshiklarni topadi (fonda, 5–30 soniya).
2. `static/js/room3d.js` — brauzer burchaklardan kamera holatini hisoblaydi va 3D sahnani aynan shu rasm perspektivasida chizadi: loyihadagi pol, devor, ship pardozi eski sirtlarni yopadi, deraza va eshik rasmdagidek qoladi, mebel va texnika soyalari bilan joylashadi. Har bir narsada raqam bor — narx ro'yxatidagi raqam bilan bir xil.
3. Burchaklar aniq tushmasa, foydalanuvchi "Burchaklarni to'g'rilash" bilan 4 nuqtani suradi, natija shu zahoti yangilanadi va saqlanadi.

3D sahifa (`/ai-loyiha/<id>/3d`) ham shu kutubxonadan foydalanadi: xona o'lchami, deraza va eshiklar rasmdagidek.

Qo'shimcha **AI fotorealistik variant** (`core/render.py`) — Gemini rasm modeli, pullik. `AQ.` bilan boshlanadigan Google Cloud kaliti Vertex AI orqali ishlaydi (`GEMINI_BACKEND`): Cloud loyihasida Vertex AI API yoqilgan va billing ulangan bo'lishi shart.

## Hamyon va tariflar (to'lov tizimisiz)

- Ro'yxatdan o'tgan har bir foydalanuvchiga `WALLET_SIGNUP_BONUS` (standart 300 000 so'm) bonus beriladi. Oldin ro'yxatdan o'tganlar ham `migrate` paytida oladi.
- **Tarif balansdan bir zumda sotib olinadi** — buyurtma avtomatik "To'langan", admin tasdiqlashi shart emas. Yuqori tarifga o'tishda faqat farq to'lanadi.
  - **PDF smeta:** har bir smeta va jihozlash loyihasini PDF qilib yuklab olish (to'liq materiallar ro'yxati, bosqichma-bosqich ish rejasi, muddatlar).
  - **3D dizayn:** PDF + xonaning sxematik 3D ko'rinishi (brauzerda aylantiriladi) + dizayner maslahatlari (PDF'da ham).
- **Pul yechish** (`/hamyon`): summa darhol balansdan ushlanadi. Admin → "Hamyon va yechish" bo'limida kartaga o'tkazgach "O'tkazildi" ni bosadi; "Rad etish" — pul balansga qaytadi. Avtomatik o'tkazish uchun Click/Payme kabi pullik to'lov tizimi kerak.
- Har bir kirim-chiqim `wallet_transactions` jadvalida (foydalanuvchi "Tarix" da ko'radi). Balans faqat `core/wallet.py` orqali, qulflangan tranzaksiya ichida o'zgaradi.
- ⚠️ Bonusni yechib olish yoqilgan bo'lsa, ko'p raqam bilan ro'yxatdan o'tib pul chiqarish mumkin. Haqiqiy saytda `WALLET_BONUS_WITHDRAWABLE=false` qiling.

## Next.js versiyasidan nima o'zgardi

| Next.js | Django |
|---|---|
| React server/client komponentlar | Django shablonlari (`templates/`) + kichik vanilla JS (`static/js/`) |
| Server Actions | Oddiy POST formalar (PRG), xato bo'lsa sahifa xatolar bilan qayta chiziladi |
| `src/lib/estimate.ts` (brauzer + server) | `core/estimate.py` — yagona manba. Kalkulyator jonli natijani `/api/hisob` dan oladi |
| PGlite (lokal) | SQLite (lokal). Production'da ikkalasida ham PostgreSQL |
| Vercel Blob | Rasmlar diskda (`DATA_DIR/uploads`). Eski Blob URL'lari o'zgarishsiz ko'rsatiladi |
| `lucide-react` | Inline SVG (`core/icons.py`, `{% icon "nom" 16 %}` tegi) |
| `next/font` | Google Fonts (Inter, Manrope) |
| `npm run bot:dev` | `python manage.py bot_dev` |
| Vercel Analytics | Olib tashlandi (Django'da mavjud emas) |

URL'lar bir xil (`/kirish`, `/ustalar/5`, `/api/telegram/webhook` ...), shuning uchun Telegram xabarlaridagi eski havolalar va ulangan webhook ishlashda davom etadi.

## Mavjud (Next.js) bazani ulash

Jadval va ustun nomlari asl sxema bilan bir xil. Parollar (scrypt) va sessiya cookie'si (`uysmeta_session`) ham mos — foydalanuvchilar qayta kirishi shart emas.

1. **Avval bazaning zaxira nusxasini oling** (Neon: branch yoki `pg_dump`).
2. `.env` da `DATABASE_URL` ni o'sha bazaga yo'naltiring. `OTP_SECRET` va `TELEGRAM_*` qiymatlarini eski saytdagidek qoldiring.
3. Jadvallar allaqachon mavjud — Django ularni qayta yaratmasligi uchun:
   ```bash
   python manage.py migrate --fake-initial
   ```
   Eski `schema_migrations` jadvali endi ishlatilmaydi, uni qoldirish mumkin.

Lokal PGlite bazasini (`web/data/pglite`) Python'dan to'g'ridan-to'g'ri o'qib bo'lmaydi — lokal ma'lumotlar kerak bo'lsa, ularni `pg_dump` orqali PostgreSQL'ga ko'chiring.

## Serverga joylash (Docker)

```bash
cp .env.example .env    # DJANGO_DEBUG=false, DJANGO_SECRET_KEY, SITE_URL=https://..., ADMIN_*, SEED_DEMO_DATA=false
docker compose up -d --build
```

Konteyner ishga tushganda migratsiyalar avtomatik qo'llanadi, sayt `gunicorn` bilan 8000-portda ishlaydi, static fayllarni WhiteNoise beradi. `/app/data` (SQLite va rasmlar) volume'da saqlanadi. HTTPS uchun oldiga nginx yoki Caddy qo'ying.

Keyin admin sifatida kiring → "Tizim holati" → **"Botni saytga ulash"**.

## Telegram orqali tasdiqlash (bepul)

1. Foydalanuvchi saytda «Telegram orqali kod olish» ni bosadi va botni ochadi.
2. Botda «📱 Raqamimni yuborish» tugmasini bosadi. Bot kontakt aynan shu Telegram hisobiniki ekanini va saytda kiritilgan raqamga mosligini tekshiradi.
3. Bot 6 xonali kod yuboradi. Keyingi safar (parolni tiklashda) kod darhol keladi.

Sozlash: `@BotFather` → `/newbot` → token va bot nomini `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME` ga yozing. Lokal sinov uchun alohida test bot oching va sayt ishlab turganda boshqa oynada `python manage.py bot_dev` ni ishga tushiring (webhook o'rniga polling).

## Sozlamalar

| O'zgaruvchi | Vazifasi |
|---|---|
| `DJANGO_DEBUG` | `true` — ishlab chiqish. Production'da `false` |
| `DJANGO_SECRET_KEY` | Production'da majburiy, uzun tasodifiy satr |
| `SITE_URL` | Saytning ommaviy manzili (domen avtomatik `ALLOWED_HOSTS` ga qo'shiladi) |
| `ALLOWED_HOSTS` | Qo'shimcha domenlar, vergul bilan |
| `DATABASE_URL` | PostgreSQL. Bo'sh — lokal SQLite |
| `DATA_DIR` | SQLite va rasmlar papkasi (standart: `./data`) |
| `ADMIN_PHONE`, `ADMIN_PASSWORD` | `migrate` paytida yaratiladigan administrator |
| `SEED_DEMO_DATA` | `false` — namuna ustalar qo'shilmaydi (**haqiqiy saytda majburiy**) |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME` | Telegram bot: kodlar va bildirishnomalar |
| `ESKIZ_EMAIL`, `ESKIZ_PASSWORD`, `ESKIZ_FROM` | Eskiz.uz SMS (ixtiyoriy) |
| `OTP_SECRET` | Kodlarni xeshlash uchun tasodifiy satr |
| `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` | AI rasm tahlili (ixtiyoriy; Gemini ustuvor) |
| `SMS_DEBUG_SHOW_CODE` | Faqat test serverlari: production'da ham kodni ekranda ko'rsatadi. **Haqiqiy saytda yoqmang** |

## Tuzilma

```
config/              Django sozlamalari, URL'lar
core/
  estimate.py        Hisob mantig'i, narxlar, validatsiya — sof funksiyalar
  models.py          Jadvallar (asl sxema bilan bir xil)
  data.py            Bir necha joyda ishlatiladigan so'rovlar
  auth.py            Sessiyalar, urinishlar chegarasi
  otp.py             Tasdiqlash kodlari + Telegram bot mantig'i
  telegram.py, sms.py, notify.py   Tashqi xizmatlar
  uploads.py         Rasmlar (disk)
  ai.py, ai_gemini.py  Xona rasmini AI bilan tahlil qilish
  views/             Sahifalar va API
  templatetags/ui.py Shablon teglari: {% icon %}, |money, {% field %} ...
  tests/             Testlar
templates/           HTML shablonlar
static/
  src/input.css      Tailwind manbasi (dizayn tokenlari)
  css/app.css        Yig'ilgan CSS (repoda saqlanadi)
  js/                app.js (umumiy), calculator.js (kalkulyator)
```

## CSS'ni qayta yig'ish

Shablonlarga yangi Tailwind klass qo'shsangiz, CSS'ni qayta yig'ing (Node.js shart emas):

```bash
pip install -r requirements-dev.txt
tailwindcss -i static/src/input.css -o static/css/app.css --minify
```
