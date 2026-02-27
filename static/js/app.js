(function () {
    // Year
    const yearEl = document.querySelector("[data-year]");
    if (yearEl) yearEl.textContent = new Date().getFullYear();

    // Mobile menu
    const btn = document.querySelector("[data-nav-toggle]");
    const panel = document.querySelector("[data-nav-panel]");
    if (btn && panel) {
        btn.addEventListener("click", () => {
            const isHidden = panel.classList.contains("hidden");
            panel.classList.toggle("hidden", !isHidden);
            btn.setAttribute("aria-expanded", String(isHidden));
        });
    }

    // Optional: exclusive pill group
    document.querySelectorAll("[data-pill-group]").forEach(group => {
        const pills = group.querySelectorAll("[data-pill]");
        pills.forEach(p => {
            p.addEventListener("click", () => {
                pills.forEach(x => x.setAttribute("aria-pressed", "false"));
                p.setAttribute("aria-pressed", "true");
            });
        });
    });
})();
