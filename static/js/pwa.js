/* Telefonga o'rnatish (PWA): service worker + "Ilovani o'rnatish" taklifi (templates/pwa/install_banner.html). */
(() => {
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
  }

  const standalone = window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
  const banner = document.querySelector("[data-install-banner]");
  const help = document.querySelector("[data-install-help]");
  const buttons = () => document.querySelectorAll("[data-install]");
  if (standalone || !banner) return; // allaqachon ilova sifatida ochilgan

  const ua = navigator.userAgent;
  const isIOS = /iphone|ipad|ipod/i.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const isMobile = isIOS || /android/i.test(ua);
  const store = {
    get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* xotira yopiq */ } },
  };
  const dismissedRecently = () => Date.now() - Number(store.get("install_dismissed") || 0) < 7 * 24 * 3600 * 1000;

  let deferred = null;
  const showButtons = () => buttons().forEach((b) => (b.hidden = false));
  const showBanner = () => {
    if (!dismissedRecently() && !document.querySelector("[data-support-panel]:not([hidden])")) banner.hidden = false;
  };

  // Android / Chrome / Edge: brauzer o'rnatishga tayyor
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferred = e;
    showButtons();
    if (isMobile) setTimeout(showBanner, 6000);
  });

  // iPhone (Safari) — avtomatik oyna yo'q: tugma yo'riqnomani ochadi
  if (isIOS) {
    showButtons();
    setTimeout(showBanner, 6000);
  }

  document.addEventListener("click", async (e) => {
    const target = e.target instanceof Element ? e.target : null;
    if (!target) return;
    if (target.closest("[data-install-dismiss]")) {
      banner.hidden = true;
      store.set("install_dismissed", String(Date.now()));
      return;
    }
    if (!target.closest("[data-install]")) return;
    if (deferred) {
      deferred.prompt();
      const choice = await deferred.userChoice.catch(() => null);
      deferred = null;
      if (choice && choice.outcome === "accepted") {
        banner.hidden = true;
        buttons().forEach((b) => (b.hidden = true));
      }
      return;
    }
    if (help && help.showModal) {
      help.querySelector('[data-install-steps="ios"]').hidden = !isIOS;
      help.querySelector('[data-install-steps="other"]').hidden = isIOS;
      help.showModal();
    }
  });

  window.addEventListener("appinstalled", () => {
    banner.hidden = true;
    buttons().forEach((b) => (b.hidden = true));
    if (window.showToast) window.showToast("UySmeta telefoningizga o'rnatildi", 3500);
  });
})();
