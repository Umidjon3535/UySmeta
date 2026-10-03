/*
 * UySmeta — sahifalardagi kichik interaktiv qismlar (kutubxonasiz).
 * Hammasi data-* atributlar orqali ulanadi, JS o'chiq bo'lsa ham formalar oddiy POST sifatida ishlaydi.
 */
(function () {
  "use strict";

  /* ---------- Rasmni brauzerda kichraytirish (calculator.js ham ishlatadi) ---------- */
  // Uzun tomoni maxSide px gacha, JPEG. Telefon rasmlari (8–12 MB) tez yuklanadi. Kichraytirib bo'lmasa — asl fayl.
  async function resizeImage(file, maxSide = 1600, quality = 0.85) {
    try {
      const bitmap = await createImageBitmap(file);
      const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
      if (scale === 1 && file.size < 1.5 * 1024 * 1024) {
        bitmap.close();
        return file;
      }
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(bitmap.width * scale);
      canvas.height = Math.round(bitmap.height * scale);
      canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      bitmap.close();
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", quality));
      if (!blob) return file;
      return new File([blob], file.name.replace(/\.[^.]+$/, "") + ".jpg", { type: "image/jpeg" });
    } catch {
      return file;
    }
  }

  /** Formadagi fayl maydonini boshqa fayl bilan almashtirish. */
  function setInputFile(input, file) {
    const transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Zaxira usul (eski brauzerlar / http)
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.setAttribute("readonly", "");
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      const ok = document.execCommand("copy");
      textarea.remove();
      return ok;
    }
  }

  window.UySmeta = { resizeImage, setInputFile, copyText };

  /* ---------- Mobil menyu ---------- */
  const menuButton = document.querySelector("[data-menu-toggle]");
  const menu = document.getElementById("mobile-menu");
  function setMenu(open) {
    if (!menuButton || !menu) return;
    menu.hidden = !open;
    menuButton.setAttribute("aria-expanded", String(open));
    menuButton.setAttribute("aria-label", open ? "Menyuni yopish" : "Menyuni ochish");
    menuButton.querySelector('[data-menu-icon="open"]').hidden = open;
    menuButton.querySelector('[data-menu-icon="close"]').hidden = !open;
  }
  if (menuButton && menu) {
    menuButton.addEventListener("click", () => setMenu(menu.hidden));
    menu.addEventListener("click", (e) => {
      if (e.target.closest("a")) setMenu(false);
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !menu.hidden) {
        setMenu(false);
        menuButton.focus();
      }
    });
  }

  /* ---------- Bosishlar ---------- */
  document.addEventListener("click", async (e) => {
    const target = e.target instanceof Element ? e.target : null;
    if (!target) return;

    // Qaytarib bo'lmaydigan amallar uchun tasdiq
    const confirmBtn = target.closest("[data-confirm]");
    if (confirmBtn && !window.confirm(confirmBtn.dataset.confirm)) {
      e.preventDefault();
      return;
    }

    const copyBtn = target.closest("[data-copy]");
    if (copyBtn) {
      const label = copyBtn.querySelector("[aria-live]") || copyBtn;
      const ok = await copyText(copyBtn.dataset.copy);
      label.textContent = ok ? "Nusxalandi" : "Nusxalab bo'lmadi";
      clearTimeout(copyBtn._timer);
      copyBtn._timer = setTimeout(() => (label.textContent = copyBtn.dataset.copyLabel || "Nusxalash"), 2200);
      return;
    }

    if (target.closest("[data-print]")) {
      window.print();
      return;
    }

    const shareBtn = target.closest("[data-share]");
    if (shareBtn && navigator.share) {
      navigator.share({ title: "UySmeta smetasi", url: window.location.origin + shareBtn.dataset.share }).catch(() => {});
    }
  });

  // "Ulashish" faqat qo'llab-quvvatlaydigan brauzerlarda (odatda telefonda) ko'rinadi
  if (navigator.share) document.querySelectorAll("[data-share]").forEach((b) => (b.hidden = false));

  /* ---------- Yuborish paytida tugmani band qilish ---------- */
  document.addEventListener("submit", (e) => {
    if (e.defaultPrevented) return;
    const button = e.submitter;
    if (!button || !button.dataset.pending) return;
    // Tugma nomi/qiymati formaga qo'shilib bo'lgach o'chiriladi
    setTimeout(() => {
      button.disabled = true;
      button.dataset.originalHtml = button.innerHTML;
      button.innerHTML =
        '<span class="bar-loader bar-loader-sm" aria-hidden="true"><span></span></span>' +
        button.dataset.pending;
    }, 0);
  });
  // "Orqaga" bosilganda sahifa keshdan qaytsa, tugmalar yana ishlasin
  window.addEventListener("pageshow", (e) => {
    if (!e.persisted) return;
    document.querySelectorAll("button[data-original-html]").forEach((b) => {
      b.disabled = false;
      b.innerHTML = b.dataset.originalHtml;
      delete b.dataset.originalHtml;
    });
  });

  /* ---------- Kunduzgi / tungi rejim (tanlov localStorage'da, base.html <head> uni darhol qo'yadi) ---------- */
  document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const root = document.documentElement;
      const current = root.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
      const next = current === "dark" ? "light" : "dark";
      const apply = () => {
        root.dataset.theme = next;
        try {
          localStorage.setItem("theme", next);
        } catch {}
      };
      if (matchMedia("(prefers-reduced-motion: reduce)").matches) return apply();

      // Yangi mavzu tugmadan boshlab doira bo'lib butun ekranga yoyiladi (~0.9 s)
      if (document.startViewTransition) {
        const rect = button.getBoundingClientRect();
        const x = rect.left + rect.width / 2;
        const y = rect.top + rect.height / 2;
        const radius = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
        document.startViewTransition(apply).ready.then(() => {
          root.animate(
            { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`] },
            { duration: 900, easing: "cubic-bezier(.4, 0, .2, 1)", pseudoElement: "::view-transition-new(root)" }
          );
        });
        return;
      }
      // Eski brauzerlar: ranglar asta-sekin almashadi
      root.classList.add("theme-fade");
      apply();
      setTimeout(() => root.classList.remove("theme-fade"), 800);
    });
  });

  /* ---------- Fayl yuklash maydoni ([data-upload]): tanlangan fayl nomi yoki soni ko'rinadi ---------- */
  document.querySelectorAll("[data-upload]").forEach((box) => {
    const input = box.querySelector('input[type="file"]');
    const label = box.querySelector("[data-upload-label]");
    if (!input || !label) return;
    const initial = label.textContent;
    input.addEventListener("change", () => {
      const n = input.files.length;
      label.textContent = n === 0 ? initial : n === 1 ? input.files[0].name : `${n} ta fayl tanlandi`;
    });
  });

  /* ---------- Telegram orqali kirish ([data-tg-login]): botni ochadi va tasdiqni kutib, o'zi kiritadi ---------- */
  document.querySelectorAll("[data-tg-login]").forEach((box) => {
    const form = box.querySelector("[data-tg-start]");
    const status = box.querySelector("[data-tg-status]");
    const errorBox = box.querySelector("[data-tg-error]");
    const openLink = box.querySelector("[data-tg-open]");
    if (!form || !status) return;
    const step = (name) => box.querySelectorAll("[data-tg-step]").forEach((s) => (s.hidden = s.dataset.tgStep !== name));
    const showError = (text) => {
      errorBox.textContent = text || "";
      errorBox.classList.toggle("hidden", !text);
    };
    let timer = null;
    const poll = (token) => {
      clearTimeout(timer);
      const started = Date.now();
      const tick = async () => {
        try {
          const res = await fetch(`/api/telegram-kirish/${encodeURIComponent(token)}`, { headers: { Accept: "application/json" }, credentials: "same-origin" });
          const data = await res.json();
          if (data.status === "ok") {
            status.textContent = data.new ? "Ro'yxatdan o'tdingiz! Kirilmoqda…" : "Tasdiqlandi! Kirilmoqda…";
            window.location.href = data.redirect;
            return;
          }
          if (data.status === "expired") {
            step("start");
            showError("Kutish vaqti tugadi. «Telegram orqali kirish» ni qayta bosing.");
            return;
          }
          if (data.opened) status.textContent = "Bot ochildi — «📱 Raqamimni yuborish» tugmasini bosing…";
        } catch {
          /* tarmoq uzilishi — keyingi urinishda qayta so'raladi */
        }
        if (Date.now() - started < 10 * 60 * 1000) timer = setTimeout(tick, 2000);
      };
      timer = setTimeout(tick, 1500);
    };
    if (box.dataset.token) poll(box.dataset.token);

    form.addEventListener("submit", async (e) => {
      if (!window.fetch) return;
      e.preventDefault();
      showError("");
      const button = form.querySelector("button[type=submit]");
      const html = button.innerHTML;
      button.disabled = true;
      button.innerHTML = '<span class="bar-loader bar-loader-sm" aria-hidden="true"><span></span></span>' + button.dataset.pending;
      // Oyna bosish paytida ochiladi — aks holda brauzer uni "popup" deb bloklaydi
      const win = window.open("", "_blank");
      try {
        const res = await fetch(form.action, { method: "POST", body: new FormData(form), headers: { Accept: "application/json" }, credentials: "same-origin" });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Xatolik yuz berdi. Qayta urinib ko'ring");
        openLink.href = data.url;
        step("wait");
        if (win) win.location.href = data.url;
        poll(data.token);
      } catch (error) {
        if (win) win.close();
        showError(error.message);
      } finally {
        button.disabled = false;
        button.innerHTML = html;
      }
    });

    box.querySelector("[data-tg-restart]")?.addEventListener("click", () => {
      clearTimeout(timer);
      showError("");
      step("start");
    });
  });

  /* ---------- Toast: ekran tepasida qisqa xabar, bir necha soniyadan keyin yo'qoladi ---------- */
  let toastTimer;
  function showToast(text, ms = 2500) {
    let toast = document.getElementById("toast");
    if (!toast) {
      toast = document.createElement("div");
      toast.id = "toast";
      toast.className = "toast";
      toast.setAttribute("role", "alert");
      document.body.appendChild(toast);
    }
    toast.textContent = text;
    toast.classList.add("is-visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove("is-visible"), ms);
  }
  window.showToast = showToast;

  /* ---------- Ism / familiya: faqat harflar (o', g' apostroflari, bo'sh joy, chiziqcha) ---------- */
  document.querySelectorAll("input[data-name-input]").forEach((input) => {
    input.addEventListener("input", () => {
      const clean = input.value.replace(/[^\p{L} '\-ʻʼ‘’`]/gu, "");
      if (clean === input.value) return;
      const pos = Math.max(0, input.selectionStart - (input.value.length - clean.length));
      input.value = clean;
      input.setSelectionRange(pos, pos);
      showToast("Faqat harf kiriting");
    });
  });

  /* ---------- #item-N havolasi yopiq <details> ichida bo'lsa — ochib, o'sha joyga o'tamiz ---------- */
  function revealTarget(hash) {
    if (!hash || hash.length < 2) return;
    const target = document.getElementById(decodeURIComponent(hash.slice(1)));
    const details = target && target.closest("details");
    if (details && !details.open) {
      details.open = true;
      target.scrollIntoView({ block: "center" });
    }
  }
  document.addEventListener("click", (e) => {
    const link = e.target instanceof Element ? e.target.closest('a[href^="#"]') : null;
    if (link) revealTarget(link.getAttribute("href"));
  });
  window.addEventListener("hashchange", () => revealTarget(location.hash));
  revealTarget(location.hash);

  // Chop etishda yopiq bo'limlar ham to'liq chiqsin, keyin avvalgi holatiga qaytadi
  let closedForPrint = [];
  window.addEventListener("beforeprint", () => {
    closedForPrint = [...document.querySelectorAll("details:not([open])")];
    closedForPrint.forEach((d) => (d.open = true));
  });
  window.addEventListener("afterprint", () => {
    closedForPrint.forEach((d) => (d.open = false));
    closedForPrint = [];
  });

  /* ---------- Telefon raqam: +998 dan keyin faqat 9 ta raqam, "(90)-123-45-67" ko'rinishida ---------- */
  // Ajratkich faqat undan keyin raqam bo'lsa qo'shiladi — shunda Backspace "(95)-" da tiqilib qolmaydi
  function phoneDigits(value) {
    let digits = value.replace(/\D/g, "");
    if (digits.length > 9 && digits.startsWith("998")) digits = digits.slice(3); // +998... joylashtirilganda
    return digits.slice(0, 9);
  }
  // Operator kodi (dastlabki 2 raqam) ruxsat etilganlardan biriga mos kelmasa — mos qismigacha qisqartiramiz
  function allowedPrefix(digits, codes) {
    if (!codes.length || !digits) return digits;
    if (!codes.some((code) => code[0] === digits[0])) return "";
    if (digits.length >= 2 && !codes.includes(digits.slice(0, 2))) return digits[0];
    return digits;
  }
  function formatPhone(digits) {
    if (!digits) return "";
    let out = "(" + digits.slice(0, 2);
    if (digits.length > 2) out += ")-" + digits.slice(2, 5);
    if (digits.length > 5) out += "-" + digits.slice(5, 7);
    if (digits.length > 7) out += "-" + digits.slice(7, 9);
    return out;
  }
  document.querySelectorAll(".phone-input input[name=phone]").forEach((input) => {
    const codes = (input.dataset.phoneCodes || "").split(",").filter(Boolean);
    let previous = phoneDigits(input.value);
    input.value = formatPhone(previous);
    input.addEventListener("input", (e) => {
      let digitsBefore = input.value.slice(0, input.selectionStart).replace(/\D/g, "").length;
      let digits = phoneDigits(input.value);
      // Faqat ajratkich ( ) - o'chirilgan bo'lsa — undan oldingi raqamni o'chiramiz
      if (e.inputType && e.inputType.startsWith("delete") && digits === previous && digitsBefore > 0) {
        if (e.inputType === "deleteContentBackward") {
          digits = digits.slice(0, digitsBefore - 1) + digits.slice(digitsBefore);
          digitsBefore -= 1;
        } else {
          digits = digits.slice(0, digitsBefore) + digits.slice(digitsBefore + 1);
        }
      }
      // Ruxsat etilmagan kod raqami yozilmaydi, toast ogohlantiradi
      const allowed = allowedPrefix(digits, codes);
      if (allowed !== digits) {
        digitsBefore = Math.min(digitsBefore, allowed.length);
        digits = allowed;
        showToast("Noto'g'ri raqam kiritayapsiz");
      }
      previous = digits;
      input.value = formatPhone(digits);
      // Kursorni o'sha raqamdan keyinga qaytarish (o'rtada tahrirlaganda sakramasin)
      let pos = 0;
      for (let seen = 0; pos < input.value.length && seen < digitsBefore; pos++) {
        if (/\d/.test(input.value[pos])) seen++;
      }
      if (digitsBefore === 0) pos = input.value ? 1 : 0;
      input.setSelectionRange(pos, pos);
    });
  });

  /* ---------- Holat tanlanganda darhol saqlash ---------- */
  document.addEventListener("change", (e) => {
    const select = e.target instanceof Element ? e.target.closest("[data-autosubmit]") : null;
    if (select && select.form) {
      select.form.requestSubmit();
      select.disabled = true;
    }
  });

  /* ---------- Sharh yulduzchalari ---------- */
  document.querySelectorAll("[data-stars]").forEach((group) => {
    const paint = () => {
      const checked = group.querySelector("input:checked");
      const value = checked ? Number(checked.value) : 0;
      group.querySelectorAll("label").forEach((label, i) => {
        const svg = label.querySelector("svg");
        svg.classList.toggle("fill-star", i < value);
        svg.classList.toggle("text-star", i < value);
        svg.classList.toggle("text-line", i >= value);
      });
    };
    group.addEventListener("change", paint);
    paint();
  });

  /* ---------- Rasm tanlash (to'lov cheki) ---------- */
  document.querySelectorAll("[data-image-picker]").forEach((form) => {
    const input = form.querySelector("[data-picker-input]");
    const preview = form.querySelector("[data-picker-preview]");
    const dropzone = form.querySelector("[data-picker-dropzone]");
    const error = form.querySelector("[data-picker-error]");
    const img = preview.querySelector("img");
    const maxSide = Number(form.dataset.maxSide) || 1600;
    const quality = Number(form.dataset.quality) || 0.85;

    const showError = (text) => {
      error.textContent = text || "";
      error.hidden = !text;
    };
    const reset = () => {
      if (img.src.startsWith("blob:")) URL.revokeObjectURL(img.src);
      img.src = "";
      preview.hidden = true;
      dropzone.hidden = false;
      input.value = "";
    };

    input.addEventListener("change", async () => {
      const original = input.files[0];
      if (!original) return;
      if (!original.type.startsWith("image/")) {
        showError("Chek rasmini (skrinshot) tanlang");
        input.value = "";
        return;
      }
      const file = await resizeImage(original, maxSide, quality);
      if (file !== original) setInputFile(input, file);
      showError("");
      if (img.src.startsWith("blob:")) URL.revokeObjectURL(img.src);
      img.src = URL.createObjectURL(file);
      preview.hidden = false;
      dropzone.hidden = true;
    });
    form.querySelector("[data-picker-clear]").addEventListener("click", () => {
      reset();
      input.focus();
    });
  });

  /* ---------- Usta formasi: hudud tanlanganda tumanlar ro'yxati almashadi ---------- */
  document.querySelectorAll("[data-master-form]").forEach((form) => {
    const select = form.querySelector("[data-region-select]");
    if (!select) return;
    select.addEventListener("change", () => {
      form.querySelectorAll("[data-district-for]").forEach((box) => {
        const active = box.dataset.districtFor === select.value;
        box.hidden = !active;
        box.querySelectorAll("select, input").forEach((el) => {
          el.disabled = !active;
          el.id = active ? "f-district" : "";
        });
      });
    });
  });

  /* ---------- Kirish / ro'yxat: tablar, kirish usuli (parol | Telegram), parolni ko'rsatish ---------- */
  const firstInput = (root) => root && root.querySelector("input:not([type=hidden]):not(.sr-only)");

  function showAuthTab(box, tab) {
    box.querySelectorAll('[role="tab"]').forEach((t) => t.setAttribute("aria-selected", String(t.dataset.authTo === tab)));
    box.querySelectorAll("[data-panel]").forEach((panel) => (panel.hidden = panel.dataset.panel !== tab));
    const panel = box.querySelector(`[data-panel="${tab}"]`);
    panel.classList.remove("animate-result");
    void panel.offsetWidth; // animatsiyani qayta ishga tushirish
    panel.classList.add("animate-result");
  }

  document.addEventListener("click", (e) => {
    const el = e.target instanceof Element ? e.target.closest("[data-auth-to], [data-auth-mode], [data-password-toggle]") : null;
    if (!el) return;

    if (el.matches("[data-password-toggle]")) {
      const input = el.parentElement.querySelector("input");
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      el.setAttribute("aria-pressed", String(show));
      el.setAttribute("aria-label", show ? "Parolni yashirish" : "Parolni ko'rsatish");
      el.querySelector('[data-eye="show"]').hidden = show;
      el.querySelector('[data-eye="hide"]').hidden = !show;
      return;
    }

    if (el.matches("[data-auth-mode]")) {
      const panel = el.closest("[data-panel]");
      if (!panel) return; // tablarsiz sahifada oddiy havola
      e.preventDefault();
      panel.querySelectorAll("[data-mode]").forEach((box) => (box.hidden = box.dataset.mode !== el.dataset.authMode));
      const input = firstInput(panel.querySelector(`[data-mode="${el.dataset.authMode}"]`));
      if (input) input.focus();
      return;
    }

    const box = el.closest("[data-auth-tabs]") || document.querySelector("[data-auth-tabs]");
    if (!box) return;
    e.preventDefault();
    showAuthTab(box, el.dataset.authTo);
    if (!box.contains(el)) box.scrollIntoView({ behavior: "smooth", block: "center" });
  });

  // Tablar orasida chap/o'ng strelkalar bilan yurish
  document.addEventListener("keydown", (e) => {
    const tab = e.target instanceof Element ? e.target.closest('[data-auth-tabs] [role="tab"]') : null;
    if (!tab || (e.key !== "ArrowLeft" && e.key !== "ArrowRight")) return;
    const tabs = [...tab.parentElement.querySelectorAll('[role="tab"]')];
    const next = tabs[(tabs.indexOf(tab) + (e.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length];
    next.focus();
    next.click();
  });

  /* ---------- Kirish / ro'yxat formalari: sahifani yangilamasdan yuborish ---------- */
  document.addEventListener("submit", async (e) => {
    const form = e.target;
    if (!(form instanceof HTMLFormElement) || !form.matches("[data-auth-form]") || !window.fetch) return;
    e.preventDefault();
    const data = new FormData(form);
    if (e.submitter && e.submitter.name) data.append(e.submitter.name, e.submitter.value);
    try {
      const res = await fetch(form.action, {
        method: "POST",
        body: data,
        headers: { "X-Auth-Partial": "1" },
        credentials: "same-origin",
      });
      if ((res.headers.get("Content-Type") || "").includes("application/json")) {
        const json = await res.json();
        if (json.redirect) return window.location.assign(json.redirect);
      }
      const tpl = document.createElement("template");
      tpl.innerHTML = await res.text();
      const fresh = tpl.content.querySelector("form[data-auth-form]");
      if (!fresh) throw new Error("bad response");
      form.replaceWith(fresh);
      const focus = fresh.querySelector('[aria-invalid="true"], input[name="code"]');
      if (focus) focus.focus();
    } catch {
      // Tarmoq xatosi va h.k. — oddiy yuborishga qaytamiz
      if (e.submitter && e.submitter.name) {
        const hidden = document.createElement("input");
        hidden.type = "hidden";
        hidden.name = e.submitter.name;
        hidden.value = e.submitter.value;
        form.append(hidden);
      }
      HTMLFormElement.prototype.submit.call(form);
    }
  });
})();
