/* Part of iKiKu. Licensed under AGPL-3.0.
 *
 * The OTP page. The code is sent in the background, so the page asks for the
 * result every two seconds, counts down the wait (the server gives up after two
 * minutes), and shows the answer the moment it arrives. The words come from the
 * server; this file only moves them onto the page. Without JavaScript the page
 * still works: a refresh shows the same state.
 */
(function () {
    "use strict";

    const PERSIAN = "۰۱۲۳۴۵۶۷۸۹";

    function fa(value) {
        return String(value).replace(/\d/g, (d) => PERSIAN[d]);
    }

    function clock(seconds) {
        const s = Math.max(0, Math.ceil(seconds));
        return fa(Math.floor(s / 60)) + ":" + fa(String(s % 60).padStart(2, "0"));
    }

    function start() {
        const box = document.getElementById("ikiku-otp");
        if (!box) {
            return;
        }
        const resend = document.querySelector("[data-otp-resend]");
        const resendLabel = resend ? resend.textContent.trim() : "";
        let state = box.dataset.state;
        let text = box.textContent.trim();
        let waitEnd = Date.now() + Number(box.dataset.wait || 0) * 1000;
        let resendAt = Date.now() + Number(box.dataset.resend || 0) * 1000;
        let asking = false;

        function apply(payload) {
            state = payload.state;
            text = payload.text || text;
            waitEnd = Date.now() + Number(payload.wait_left || 0) * 1000;
            resendAt = Date.now() + Number(payload.resend_in || 0) * 1000;
            box.dataset.state = state;
            draw();
        }

        function draw() {
            const now = Date.now();
            box.textContent = state === "queued" ? text + " " + clock((waitEnd - now) / 1000) : text;
            if (resend) {
                const waiting = now < resendAt;
                resend.disabled = waiting;
                resend.textContent = waiting ? resendLabel + " (" + clock((resendAt - now) / 1000) + ")" : resendLabel;
            }
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
        setInterval(draw, 250);
        setInterval(ask, 2000);
        ask();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", start);
    } else {
        start();
    }
})();
