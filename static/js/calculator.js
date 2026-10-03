/*
 * Smeta kalkulyatori: forma o'zgarganda natija serverda (yagona hisob mantig'i — core/estimate.py) qayta hisoblanib,
 * sahifaga qo'yiladi. "Saqlash" bosilganda forma oddiy POST sifatida yuboriladi va server bazadagi narxlar bilan saqlaydi.
 */
(function () {
  "use strict";

  const form = document.querySelector("[data-calc]");
  if (!form) return;
  const resultBody = document.querySelector("[data-result-body]");
  const resultCard = document.querySelector("[data-result]");
  const copyBtn = document.querySelector("[data-result-copy]");

  const DIM_FIELDS = ["length", "width", "height", "area"];
  let lastErrors = {};
  let pending = null;
  let timer = null;
  let seq = 0;
  let calculated = false; // «Hisoblash» bosilgandan keyin natija "namuna" emas, foydalanuvchiniki

  const prefersReducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const roomType = () => form.querySelector('input[name="roomType"]:checked')?.value;

  /* ---------- Xatolarni ko'rsatish ---------- */
  function setFieldError(name, text) {
    const input = form.querySelector(`[name="${name}"]`);
    const error = form.querySelector(`#${name}-error`);
    if (!input || !error) return;
    error.textContent = text || "";
    error.hidden = !text;
    if (text) {
      input.setAttribute("aria-invalid", "true");
      input.setAttribute("aria-describedby", `${name}-error`);
    } else {
      input.removeAttribute("aria-invalid");
      input.removeAttribute("aria-describedby");
    }
  }

  function showErrors(errors) {
    DIM_FIELDS.forEach((name) => setFieldError(name, errors[name]));
    const first = DIM_FIELDS.find((name) => errors[name]);
    if (first) form.querySelector(`[name="${first}"]`)?.focus();
  }

  /* ---------- Jonli hisob ---------- */
  function recalculate() {
    clearTimeout(timer);
    const id = ++seq;
    const body = new FormData(form);
    if (calculated) body.set("explicit", "1");
    pending = fetch(form.dataset.calcUrl, { method: "POST", body, headers: { "X-Requested-With": "fetch" } })
      .then((res) => res.json())
      .then((data) => {
        if (id !== seq) return; // eskirgan javob
        if (data.ok) {
          lastErrors = {};
          resultBody.innerHTML = data.html;
          if (copyBtn) copyBtn.dataset.copy = data.text;
        } else {
          // Noto'g'ri kiritishda oxirgi to'g'ri natija qoladi
          lastErrors = data.errors || {};
        }
      })
      .catch(() => {})
      .finally(() => {
        if (id === seq) pending = null;
      });
    return pending;
  }

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(recalculate, 150);
  }

  async function flush() {
    if (timer) {
      clearTimeout(timer);
      timer = null;
      await recalculate();
    } else if (pending) {
      await pending;
    }
  }

  function toggleDims() {
    const apartment = roomType() === "apartment";
    form.querySelector('[data-dims="room"]').hidden = apartment;
    form.querySelector('[data-dims="apartment"]').hidden = !apartment;
    form.querySelector("[data-dims-legend]").textContent = apartment ? "Kvartira maydoni" : "Xona o'lchamlari";
  }

  form.addEventListener("input", (e) => {
    const name = e.target.name;
    if (DIM_FIELDS.includes(name)) {
      setFieldError(name, ""); // tahrirlanayotgan maydonning xatosi yashiriladi
      schedule();
    }
  });
  form.addEventListener("change", (e) => {
    const name = e.target.name;
    if (name === "roomType") toggleDims();
    if (name === "roomType" || name === "quality" || name === "region") schedule();
  });

  /* ---------- "Hisoblash" va "Saqlash" ---------- */
  form.querySelector("[data-calc-run]").addEventListener("click", async () => {
    // Har doim joriy qiymatlar bilan yangidan hisoblaymiz (standart o'lchamlar bo'lsa ham)
    calculated = true;
    clearTimeout(timer);
    timer = null;
    await recalculate();
    if (Object.keys(lastErrors).length) {
      showErrors(lastErrors);
      return;
    }
    showErrors({});
    resultCard.classList.remove("animate-result");
    void resultCard.offsetWidth; // animatsiyani qayta ishga tushirish
    resultCard.classList.add("animate-result");
    const section = document.getElementById("natija");
    section.hidden = false; // natija birinchi «Hisoblash» dan keyin ochiladi
    section.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" });
  });

  form.addEventListener("submit", async (e) => {
    if (timer || pending) {
      // Oxirgi hisob tugashini kutib, keyin qayta yuboramiz
      e.preventDefault();
      const submitter = e.submitter;
      await flush();
      if (!Object.keys(lastErrors).length) form.requestSubmit(submitter && submitter.form === form ? submitter : undefined);
      else showErrors(lastErrors);
      return;
    }
    if (Object.keys(lastErrors).length) {
      e.preventDefault();
      showErrors(lastErrors);
    }
  });

  // Saqlashda xato bilan qaytgan sahifa: joriy qiymatlar holatini aniqlab olamiz
  if (form.querySelector(".field-error:not([hidden])")) recalculate();
})();
