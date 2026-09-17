/* Part of search_suggest. Licensed under AGPL-3.0.
 *
 * A suggest box over a plain input, as an ARIA combobox. Markup:
 *
 *   <div data-suggest data-suggest-url="/roles/suggest" data-suggest-count="{n} پیشنهاد">
 *     <input type="search" name="q" autocomplete="off"/>
 *   </div>
 *
 * The URL answers GET ?q=… with {"results": [{"id", "label", "detail"?, "url"?}]}, and
 * &quick=1 with the tightest, cheapest search only. The full answer is asked for first; if it
 * has not arrived within QUICK_AFTER milliseconds, the quick one is asked for too and shown
 * in the meantime, so a slow search puts something true on the screen instead of nothing.
 * A search that answers quickly is asked once.
 * Choosing a result fires "search-suggest:choose" on the container with the result as
 * detail; unless a listener calls preventDefault(), a result with a url is opened.
 * Without JavaScript the input is an ordinary field of its form, so nothing is lost.
 */
(function () {
    "use strict";

    const DELAY = 180;
    const QUICK_AFTER = 70;    // ms to wait for the full answer before showing a partial one
    let counter = 0;

    function setup(box) {
        if (box.dataset.suggestReady) {
            return;
        }
        box.dataset.suggestReady = "1";
        const input = box.querySelector("input");
        const url = box.dataset.suggestUrl;
        if (!input || !url) {
            return;
        }
        const id = "search-suggest-" + (++counter);
        const list = document.createElement("ul");
        list.id = id + "-list";
        list.className = "search-suggest__list";
        list.setAttribute("role", "listbox");
        list.hidden = true;
        const status = document.createElement("p");
        status.className = "search-suggest__status";
        status.setAttribute("role", "status");
        status.setAttribute("aria-live", "polite");
        box.classList.add("search-suggest");
        box.append(list, status);
        input.setAttribute("role", "combobox");
        input.setAttribute("aria-autocomplete", "list");
        input.setAttribute("aria-controls", list.id);
        input.setAttribute("aria-expanded", "false");
        input.setAttribute("autocomplete", "off");

        const cache = new Map();
        let results = [];
        let active = -1;
        let timer = null;
        let controllers = [];

        function close() {
            list.hidden = true;
            input.setAttribute("aria-expanded", "false");
            input.removeAttribute("aria-activedescendant");
            active = -1;
        }

        function render(query, items, waiting) {
            const chosen = active >= 0 ? results[active] : null;
            results = items;
            list.replaceChildren();
            items.forEach(function (item, index) {
                const option = document.createElement("li");
                option.id = id + "-" + index;
                option.className = "search-suggest__option";
                option.setAttribute("role", "option");
                option.setAttribute("aria-selected", "false");
                const label = document.createElement("span");
                label.className = "search-suggest__label";
                label.textContent = item.label;
                option.append(label);
                if (item.detail) {
                    const detail = document.createElement("small");
                    detail.className = "search-suggest__detail";
                    detail.textContent = item.detail;
                    option.append(detail);
                }
                option.addEventListener("mousedown", function (event) {
                    event.preventDefault();   // keep focus in the input
                    choose(index);
                });
                list.append(option);
            });
            const template = box.dataset.suggestCount || "{n}";
            const more = box.dataset.suggestWaiting || "…";
            status.textContent = query
                ? template.replace("{n}", String(items.length)) + (waiting ? " " + more : "")
                : "";
            list.hidden = !items.length;
            list.setAttribute("aria-busy", waiting ? "true" : "false");
            input.setAttribute("aria-expanded", items.length ? "true" : "false");
            // Whatever the person had highlighted stays highlighted, wherever it moved to.
            const stillThere = chosen ? items.findIndex(function (item) { return item.id === chosen.id; }) : -1;
            active = -1;
            if (stillThere >= 0) {
                highlight(stillThere);
            }
        }

        function highlight(index) {
            const options = list.querySelectorAll("[role=option]");
            options.forEach(function (option, i) {
                option.setAttribute("aria-selected", i === index ? "true" : "false");
            });
            active = index;
            if (index >= 0 && options[index]) {
                input.setAttribute("aria-activedescendant", options[index].id);
                options[index].scrollIntoView({block: "nearest"});
            } else {
                input.removeAttribute("aria-activedescendant");
            }
        }

        function choose(index) {
            const item = results[index];
            if (!item) {
                return;
            }
            const event = new CustomEvent("search-suggest:choose", {detail: item, bubbles: true, cancelable: true});
            close();
            if (box.dispatchEvent(event) && item.url) {
                window.location.assign(item.url);
            }
        }

        function ask(query, quick) {
            const controller = new AbortController();
            controllers.push(controller);
            const target = url + (url.includes("?") ? "&" : "?") + "q=" + encodeURIComponent(query)
                + (quick ? "&quick=1" : "");
            return fetch(target, {signal: controller.signal, credentials: "same-origin",
                                  headers: {Accept: "application/json"}})
                .then(function (response) { return response.ok ? response.json() : {results: []}; })
                .then(function (data) { return Array.isArray(data.results) ? data.results : []; });
        }

        function fetchResults() {
            const query = input.value.trim();
            if (query.length < Number(box.dataset.suggestMin || 1)) {
                render("", [], false);
                close();
                return;
            }
            if (cache.has(query)) {
                render(query, cache.get(query), false);
                return;
            }
            controllers.forEach(function (controller) { controller.abort(); });
            controllers = [];
            const current = function () { return input.value.trim() === query; };
            let full = false;
            ask(query, false).then(function (items) {
                full = true;
                cache.set(query, items);
                if (current()) {
                    render(query, items, false);
                }
            }).catch(function () { full = true; /* aborted or offline: the form still works */ });
            setTimeout(function () {
                if (full || !current()) {
                    return;             // it was quick enough; one question was enough
                }
                ask(query, true).then(function (items) {
                    if (!full && current()) {
                        render(query, items, true);   // true so far, and still looking
                    }
                }).catch(function () { /* the full answer is on its way regardless */ });
            }, QUICK_AFTER);
        }

        input.addEventListener("input", function () {
            clearTimeout(timer);
            timer = setTimeout(fetchResults, DELAY);
        });
        input.addEventListener("keydown", function (event) {
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                if (list.hidden && results.length) {
                    list.hidden = false;
                    input.setAttribute("aria-expanded", "true");
                }
                const step = event.key === "ArrowDown" ? 1 : -1;
                const count = results.length;
                if (count) {
                    event.preventDefault();
                    highlight((active + step + count) % count);
                }
            } else if (event.key === "Enter" && !list.hidden && active >= 0) {
                event.preventDefault();
                choose(active);
            } else if (event.key === "Escape" && !list.hidden) {
                event.preventDefault();
                close();
            }
        });
        input.addEventListener("blur", function () { setTimeout(close, 120); });
    }

    function init(root) {
        (root || document).querySelectorAll("[data-suggest]").forEach(setup);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () { init(); });
    } else {
        init();
    }
    window.searchSuggest = {init: init};
})();
