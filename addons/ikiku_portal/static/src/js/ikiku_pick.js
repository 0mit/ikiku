/* Part of iKiKu. Licensed under AGPL-3.0.
 *
 * The search box above the tiles (/join/skills, /business/need/who). Choosing a suggestion
 * ticks that role's tile in the form below instead of opening its page, opens «کارهای دیگه»
 * when the tile waits there, and says what was ticked. The box is hidden until this runs,
 * so without JavaScript the page keeps its own «بنویسید» path.
 */
(function () {
    "use strict";

    document.querySelectorAll("[data-ikiku-pick]").forEach(function (box) {
        box.hidden = false;
    });

    document.addEventListener("search-suggest:choose", function (event) {
        const pick = event.target.closest("[data-ikiku-pick]");
        if (!pick) {
            return;
        }
        event.preventDefault();
        const item = event.detail;
        const input = document.querySelector('input[name="node_id"][value="' + String(item.id).replace(/"/g, "") + '"]');
        const note = pick.querySelector("[data-ikiku-pick-note]");
        if (!input) {
            if (note) {
                note.textContent = "«" + item.label + "» اینجا نیست.";
            }
            return;
        }
        const more = input.closest("details");
        if (more) {
            more.open = true;
        }
        if (!input.disabled) {
            input.checked = true;
        }
        input.closest("label").scrollIntoView({block: "center", behavior: "smooth"});
        if (note) {
            note.textContent = input.disabled ? "«" + item.label + "» قبلاً ثبت شده." : "«" + item.label + "» زده شد.";
        }
        const field = pick.querySelector("input[type=search]");
        if (field) {
            field.value = "";
        }
    });
})();
