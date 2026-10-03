/* Yordam chati (templates/includes/support_widget.html): oyna, xabar yuborish, menejer javoblarini kutish. */
(() => {
  const root = document.querySelector("[data-support]");
  if (!root || !window.fetch) return;

  const panel = root.querySelector("[data-support-panel]");
  const hint = root.querySelector("[data-support-hint]");
  const list = root.querySelector("[data-support-list]");
  const form = root.querySelector("[data-support-form]");
  const contact = root.querySelector("[data-support-contact]");
  const errorBox = root.querySelector("[data-support-error]");
  const badge = root.querySelector("[data-support-badge]");
  const toggle = root.querySelector("[data-support-toggle]");
  const textarea = form.querySelector("textarea");
  const csrf = root.querySelector("input[name=csrfmiddlewaretoken]").value;
  const greeting = list.innerHTML;

  // Brauzer xotirasi (yopilgan pufak, suhbat borligi) — bloklangan bo'lsa ham widget ishlaydi
  const store = {
    get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* xotira yopiq */ } },
  };

  let open = false;
  let timer = null;
  let lastCount = -1;

  const escape = (s) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  function render(messages) {
    if (messages.length === lastCount) return;
    lastCount = messages.length;
    list.innerHTML =
      greeting +
      messages
        .map((m) => {
          const mine = !m.admin;
          return `<li class="flex ${mine ? "justify-end" : ""}"><div class="max-w-[85%] rounded-2xl px-3.5 py-2 text-[15px] ${
            mine ? "rounded-br-md bg-accent text-on-accent" : "rounded-bl-md bg-bg"
          }"><p class="whitespace-pre-line break-words">${escape(m.text)}</p><p class="mt-0.5 text-right text-[11px] opacity-70">${
            mine ? "" : "Menejer · "
          }${m.time}</p></div></li>`;
        })
        .join("");
    list.scrollTop = list.scrollHeight;
  }

  function setBadge(n) {
    badge.textContent = n;
    badge.classList.toggle("hidden", !n);
    badge.classList.toggle("grid", !!n);
  }

  async function load() {
    try {
      const res = await fetch("/api/yordam" + (open ? "?read=1" : ""), { headers: { Accept: "application/json" }, credentials: "same-origin" });
      const data = await res.json();
      contact.hidden = !data.need_contact;
      if (data.messages.length) store.set("yordam_thread", "1");
      if (open) {
        render(data.messages);
        setBadge(0);
      } else {
        setBadge(data.unread);
      }
    } catch {
      /* tarmoq — keyingi safar */
    }
  }

  function schedule() {
    clearTimeout(timer);
    // Oyna ochiq — tez-tez; yopiq va suhbat bor — kamroq (yangi javob belgisi uchun)
    if (open) timer = setTimeout(() => load().then(schedule), 4000);
    else if (store.get("yordam_thread")) timer = setTimeout(() => load().then(schedule), 30000);
  }

  function setOpen(value) {
    open = value;
    panel.hidden = !open;
    hint.hidden = true;
    toggle.setAttribute("aria-expanded", String(open));
    toggle.setAttribute("aria-label", open ? "Yordam chatini yopish" : "Yordam chatini ochish");
    toggle.querySelector('[data-support-icon="open"]').hidden = open;
    toggle.querySelector('[data-support-icon="close"]').hidden = !open;
    store.set("yordam_hint", "1");
    if (open) {
      lastCount = -1;
      load().then(() => (contact.hidden ? textarea : contact.querySelector("input")).focus());
    }
    schedule();
  }

  toggle.addEventListener("click", () => setOpen(!open));
  root.querySelector("[data-support-close]").addEventListener("click", () => setOpen(false));
  root.querySelector("[data-support-open]").addEventListener("click", () => setOpen(true));
  root.querySelector("[data-support-hint-close]").addEventListener("click", () => {
    hint.hidden = true;
    store.set("yordam_hint", "1");
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && open) setOpen(false);
  });

  // Enter — yuborish, Shift+Enter — yangi qator
  textarea.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit();
    }
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = textarea.value.trim();
    if (!text) return;
    const button = form.querySelector("button[type=submit]");
    button.disabled = true;
    errorBox.classList.add("hidden");
    const body = { text, page: location.pathname };
    if (!contact.hidden) {
      body.name = contact.querySelector("[name=name]").value.trim();
      body.phone = contact.querySelector("[name=phone]").value;
    }
    try {
      const res = await fetch("/api/yordam", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRFToken": csrf },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) {
        errorBox.textContent = Object.values(data.errors || {})[0] || "Yuborib bo'lmadi. Qayta urinib ko'ring";
        errorBox.classList.remove("hidden");
        return;
      }
      textarea.value = "";
      contact.hidden = true;
      store.set("yordam_thread", "1");
      lastCount = -1;
      render(data.messages);
    } catch {
      errorBox.textContent = "Internet aloqasini tekshiring";
      errorBox.classList.remove("hidden");
    } finally {
      button.disabled = false;
    }
  });

  // Pufak: birinchi tashrifda 4 soniyadan keyin bir marta
  if (!store.get("yordam_hint")) setTimeout(() => { if (!open) hint.hidden = false; }, 4000);
  if (store.get("yordam_thread")) load().then(schedule);
})();
