/* Part of iKiKu. Licensed under AGPL-3.0.
 *
 * The «کجا؟» field. The suggest box (search_suggest) offers places; choosing one writes its
 * id into the hidden field the form posts, and its name into the box, instead of opening a
 * page. The path of what was chosen is shown underneath, so «فلسطین» is confirmed as the one
 * in Tehran and not the one in Rasht.
 *
 * Without JavaScript nothing here runs and nothing is lost: the box is an ordinary text
 * field, the server matches what was typed, and asks which one when a name fits several.
 */
(function () {
    "use strict";

    document.addEventListener("search-suggest:choose", function (event) {
        const box = event.target.closest("[data-suggest-target]");
        if (!box) {
            return;
        }
        event.preventDefault();
        const item = event.detail;
        const hidden = box.parentElement.querySelector('input[name="' + box.dataset.suggestTarget + '"]');
        const input = box.querySelector("input");
        if (hidden) {
            hidden.value = item.id;
        }
        if (input) {
            input.value = item.label;
        }
        // The radio buttons the server offers when a name fits several places are answered
        // now, so a stale pick cannot be posted with a new choice.
        const chooser = box.parentElement.querySelectorAll('input[type="radio"][name="place_id"]');
        chooser.forEach(function (radio) { radio.checked = false; });
        let path = box.parentElement.querySelector("[data-ikiku-place-path]");
        if (!path) {
            path = document.createElement("p");
            path.className = "ikiku__hint";
            path.setAttribute("data-ikiku-place-path", "1");
            box.insertAdjacentElement("afterend", path);
        }
        path.textContent = item.detail ? "الان: " + item.detail : "";
    });

    // A parameter is added to the responder's URL and to the fallback's alike: whichever of
    // the two answers, it answers the same question.
    function addParameter(box, name, value) {
        ["suggestUrl", "suggestFallback"].forEach(function (key) {
            const url = box.dataset[key];
            if (url) {
                box.dataset[key] = url + (url.includes("?") ? "&" : "?") + name + "=" + encodeURIComponent(value);
            }
        });
    }

    // A place is asked for inside a city the person already named: the box says which.
    document.querySelectorAll("[data-suggest-within]").forEach(function (box) {
        addParameter(box, "within", box.dataset.suggestWithin);
    });

    // The kinds a form may offer travel the same way, so the endpoint decides nothing on its own.
    document.querySelectorAll("[data-suggest-kinds]").forEach(function (box) {
        addParameter(box, "kinds", box.dataset.suggestKinds);
    });
})();
