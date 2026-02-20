// File: /assets/js/tsrc-ui.js
(() => {
  // Respect reduced motion automatically (CSS already does; this just avoids JS effects)
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Add a tiny class on body when user is tabbing (better focus-visible styling patterns)
  let usingKeyboard = false;
  window.addEventListener("keydown", (e) => {
    if (e.key === "Tab") {
      usingKeyboard = true;
      document.documentElement.classList.add("tsrc-kb");
    }
  }, { passive: true });

  window.addEventListener("mousedown", () => {
    if (usingKeyboard) {
      usingKeyboard = false;
      document.documentElement.classList.remove("tsrc-kb");
    }
  }, { passive: true });

  // Micro interaction: add a short glow flash to primary buttons on click (subtle)
  if (!reduceMotion) {
    document.addEventListener("click", (e) => {
      const btn = e.target.closest(".btn-primary");
      if (!btn) return;
      btn.animate(
        [{ boxShadow: getComputedStyle(btn).boxShadow }, { boxShadow: "0 0 0 1px rgba(252,61,33,0.40), 0 0 18px rgba(252,61,33,0.22)" }, { boxShadow: getComputedStyle(btn).boxShadow }],
        { duration: 220, easing: "cubic-bezier(.2,.8,.2,1)" }
      );
    });
  }
})();
