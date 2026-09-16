/* Part of iKiKu. Licensed under AGPL-3.0.
 *
 * The SMS code page. The code is sent in the background, so the page asks for the
 * result every two seconds and shows the answer the moment it arrives. The words
 * come from the server; this file only moves them onto the page. It never submits
 * anything by itself. Without JavaScript the page still works: a refresh shows the
 * same state, with the same buttons.
 *
 *  - "دوباره بفرست" appears only once a resend is allowed, with no ticking clock.
 *  - When sending failed or the code ran out, the code field is hidden and the
 *    resend button is the one thing to do.
 */
(function () {
    "use strict";

    function start() {
        const box = document.getElementById("ikiku-otp");
        if (!box) {
            return;
        }
        const codeForm = document.getElementById("ikiku-otp-code");
        const resendForm = document.getElementById("ikiku-otp-resend");
        let state = box.dataset.state;
        let resendAt = Date.now() + Number(box.dataset.resend || 0) * 1000;
        let asking = false;

        function draw() {
            const failed = state === "failed" || state === "expired";
            if (codeForm) {
                codeForm.hidden = failed;
            }
            if (resendForm) {
                resendForm.hidden = !(failed || Date.now() >= resendAt);
            }
        }

        function apply(payload) {
            if (payload.state === state && !payload.text) {
                return;
            }
            state = payload.state;
            if (payload.text && box.textContent.trim() !== payload.text) {
                box.textContent = payload.text;
            }
            resendAt = Date.now() + Number(payload.resend_in || 0) * 1000;
            box.dataset.state = state;
            draw();
        }

        async function ask() {
            if (asking || state !== "queued") {
                return;
            }
            asking = true;
            try {
                const response = await fetch(box.dataset.stateUrl, {
                    credentials: "same-origin",
                    headers: { Accept: "application/json" },
                });
                if (response.ok) {
                    apply(await response.json());
                }
            } catch {
                // A dropped poll is retried two seconds later.
            } finally {
                asking = false;
            }
        }

        draw();
        setInterval(draw, 1000);
        setInterval(ask, 2000);
        ask();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", start);
    } else {
        start();
    }
})();
