# UySmeta'ni serverga joylash

Ikki bepul yo'l:
- **A. PythonAnywhere** — bank kartasi **shart emas**. 15 daqiqada tayyor. Pastda.
- **B. Oracle Cloud Free** — kuchliroq haqiqiy server, lekin ro'yxatdan o'tishda karta so'raladi. Keyingi bo'lim.

---

## A. PythonAnywhere (kartasiz)

Manzil: `https://<login>.pythonanywhere.com` (HTTPS bilan). Baza va rasmlar saqlanadi, sayt uxlamaydi.

**Bepul tarif cheklovlari** (sayt ishlashiga xalaqit bermaydi):
- Disk 512 MB — rasmlar ko'payib ketsa, keyin pullik tarifga yoki Oracle'ga o'tasiz.
- Tashqi internet faqat ruxsat etilgan saytlarga: Telegram, Anthropic, Cloudflare — bor.
- Fon vazifalari so'rov ichida bajariladi (`BACKGROUND_SYNC=true`) — AI tahlil paytida sahifa biroz kutadi.
- **Har oy** Web bo'limida **«Run until … from today»** tugmasini bosing (aks holda sayt to'xtaydi; oldindan email keladi).
- O'z domeningiz (.uz) faqat pullik tarifda ulanadi.

### 1. Hisob ochish
https://www.pythonanywhere.com/registration/register/beginner/ → login, email, parol. Login sayt manzili bo'ladi
(masalan `uysmeta` → `uysmeta.pythonanywhere.com`). Emailni tasdiqlang.

### 2. API token
Yuqori o'ng **Account → API token → Create a new API token**. (Skript shu bilan veb-ilovani o'zi sozlaydi.)

### 3. O'rnatish (bitta buyruq)
**Consoles → Bash** (yangi konsol oching) va kiriting:

```bash
git clone https://github.com/Umidjon3535/UySmeta.git && cd UySmeta && bash deploy/pythonanywhere.sh
```

Skript administrator telefoni, paroli va Telegram bot tokenini so'raydi; qolganini (kutubxonalar, baza, maxfiy kalitlar,
veb-ilova, HTTPS) o'zi qiladi — 5–8 daqiqa. Oxirida sayt manzilini ko'rsatadi.

### 4. Ishga tushgandan keyin
1. Saytni oching → **Kirish** → administrator telefoni va paroli.
2. **Admin panel → Tizim holati → «Botni saytga ulash»** (kompyuterda `bot_dev` ishlayotgan bo'lsa — to'xtating).
3. Telegram'da bir marta **«Telegram orqali kirish»** bilan admin raqamingizdan kiring — xabarlar Telegram'ga keladi.

### Yangilash (kompyuterdan `git push` qilgach)
Bash konsolda: `cd ~/UySmeta && git pull && bash deploy/pythonanywhere.sh`

### Muammo bo'lsa
**Web** bo'limi → *Log files* → **Error log** — oxirgi qatorlarni ko'ring.

---

# B. Oracle Cloud Free (kartali, kuchliroq server)

Natija: sayt `https://...` manzilida 24/7 ishlaydi, baza va yuklangan rasmlar saqlanadi, Telegram bot ulanadi.
Hammasi bepul (Oracle "Always Free"). Taxminiy vaqt: 30–40 daqiqa.

## 1. Oracle Cloud hisobi

1. https://www.oracle.com/cloud/free/ → **Start for free**.
2. Ma'lumotlarni to'ldiring. **Home Region** ni keyin o'zgartirib bo'lmaydi — yaqinrog'ini tanlang
   (masalan *Germany Central (Frankfurt)*).
3. Bank kartasi faqat shaxsni tasdiqlash uchun so'raladi (vaqtincha ~1$ ushlanib, qaytariladi). "Always Free"
   resurslar uchun pul yechilmaydi.

## 2. Server (VM) yaratish

1. Menyu → **Compute → Instances → Create instance**.
2. **Image**: *Canonical Ubuntu 24.04*.
3. **Shape** → *Ampere* → **VM.Standard.A1.Flex**: 2 OCPU, 12 GB RAM (bepul).
   - "Out of capacity" chiqsa: boshqa *Availability Domain* ni tanlang yoki birozdan keyin qayta urining.
   - Bo'lmasa: *AMD* → **VM.Standard.E2.1.Micro** (1 GB, bepul) — skript o'zi swap qo'shadi.
4. **Add SSH keys** → *Generate a key pair for me* → **Save private key** (faylni saqlab qo'ying!).
5. **Create**. Bir necha daqiqadan keyin **Public IP address** ko'rinadi — yozib oling.

## 3. 80 va 443 portlarni ochish (Oracle tarmog'ida)

Instance sahifasi → **Subnet** havolasi → **Security Lists** → *Default Security List* → **Add Ingress Rules**:

| Source CIDR | IP Protocol | Destination Port |
|---|---|---|
| `0.0.0.0/0` | TCP | `80,443` |

(Server ichidagi to'siqni `setup.sh` o'zi ochadi.)

## 4. Serverga ulanish va o'rnatish

Windows PowerShell'da (kalit faylingiz yo'lini yozing):

```powershell
ssh -i C:\Users\Hp\Downloads\ssh-key.key ubuntu@<PUBLIC_IP>
```

Serverda:

```bash
git clone https://github.com/Umidjon3535/UySmeta.git
cd UySmeta
bash deploy/setup.sh
```

Skript so'raydi:
- **Domen** — Enter bosing: `<IP>.sslip.io` bepul domeni ishlatiladi (HTTPS bilan). O'z domeningiz bo'lsa — o'shani yozing
  (oldin domen A-yozuvini server IP'siga yo'naltiring).
- **Administrator telefoni va paroli** — admin panelga kirish uchun.
- **Telegram bot tokeni** — @BotFather'dagi token.

Maxfiy kalitlar (`DJANGO_SECRET_KEY`, `OTP_SECRET`) avtomatik yaratiladi. Sayt **haqiqiy rejimda** ishlaydi:
`DJANGO_DEBUG=false`, tasdiqlash kodlari faqat Telegram (yoki SMS) orqali — ekranda ko'rsatilmaydi.

## 5. Ishga tushgandan keyin

1. `https://<domen>` ni oching (sertifikat 1–2 daqiqada olinadi).
2. **Kirish** → administrator telefoni va paroli.
3. **Admin panel → Tizim holati → «Botni saytga ulash»** — Telegram bot shu saytga ulanadi.
   - Kompyuterda `manage.py bot_dev` ishlab turgan bo'lsa — uni to'xtating (bitta bot ikki joyda ishlamaydi).
4. Telegram'da bir marta **«Telegram orqali kirish»** bilan admin raqamingizdan kiring — shundan keyin yordam chati
   va yangi arizalar haqida xabarlar Telegram'ingizga keladi.
5. AI kalitlari (ixtiyoriy): `nano .env` → `GEMINI_API_KEY=...`, `ANTHROPIC_API_KEY=...` →
   `docker compose -f docker-compose.prod.yml up -d`.

## Kundalik ishlar

| Vazifa | Buyruq (serverda, `~/UySmeta` ichida) |
|---|---|
| Yangi kodni joylash (kompyuterdan `git push` qilgach) | `bash deploy/update.sh` |
| Loglarni ko'rish | `docker compose -f docker-compose.prod.yml logs -f uysmeta` |
| Zaxira nusxa (baza + rasmlar) | `bash deploy/backup.sh` |
| Har kuni avtomatik zaxira | `crontab -e` → `0 3 * * * bash ~/UySmeta/deploy/backup.sh` |
| Sozlamani o'zgartirish | `nano .env` → `docker compose -f docker-compose.prod.yml up -d` |
| Qayta ishga tushirish | `docker compose -f docker-compose.prod.yml restart` |

## Domenni keyin o'zgartirish

`.env` da `DOMAIN` va `SITE_URL` ni yangilang → `docker compose -f docker-compose.prod.yml up -d` →
admin panelda **«Botni saytga ulash»** ni qayta bosing (bot yangi manzilga ulanadi).
