/* Part of iKiKu. Licensed under AGPL-3.0.
 *
 * One tap, one submission. On a slow phone a second tap would send the same answer
 * twice, so the pressed button says it is working until the page changes. The browser
 * restores a page from its back cache with the button still disabled, so pageshow
 * turns it back on. Nothing is blocked: the first submission always goes out.
 */
(function () {
    "use strict";

    document.addEventListener("submit", function (event) {
        const form = event.target;
        if (!form.matches("[data-ikiku-form]")) {
            return;
        }
        const button = event.submitter || form.querySelector("button[type=submit]");
        if (!button || button.getAttribute("aria-busy") === "true") {
            return;
        }
        button.setAttribute("aria-busy", "true");
        if (button.dataset.label === undefined) {
            button.dataset.label = button.textContent;
        }
        button.textContent = "داره ثبت میشه…";
        // Disabled after this tick, so the button's own name/value still goes with the form.
        setTimeout(function () { button.disabled = true; }, 0);
    });

    window.addEventListener("pageshow", function () {
        document.querySelectorAll("[data-ikiku-form] button[aria-busy=true]").forEach(function (button) {
            button.disabled = false;
            button.removeAttribute("aria-busy");
            if (button.dataset.label !== undefined) {
                button.textContent = button.dataset.label;
            }
        });
    });
})();
