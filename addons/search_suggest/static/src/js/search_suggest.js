/* Part of search_suggest. Licensed under AGPL-3.0.
 *
 * A suggest box over a plain input, as an ARIA combobox. Markup:
 *
 *   <div data-suggest data-suggest-url="/roles/suggest" data-suggest-count="{n} پیشنهاد">
 *     <input type="search" name="q" autocomplete="off"/>
 *   </div>
 *
 * The URL answers GET ?q=… with {"results": [{"id", "label", "detail"?, "url"?}]}.
 * Choosing a result fires "search-suggest:choose" on the container with the result as
 * detail; unless a listener calls preventDefault(), a result with a url is opened.
 * Without JavaScript the input is an ordinary field of its form, so nothing is lost.
 */
(function () {
    "use strict";

    const DELAY = 180;
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
        let controller = null;

        function close() {
            list.hidden = true;
            input.setAttribute("aria-expanded", "false");
            input.removeAttribute("aria-activedescendant");
            active = -1;
        }

        function render(query, items) {
            results = items;
            active = -1;
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
            status.textContent = query ? template.replace("{n}", String(items.length)) : "";
            list.hidden = !items.length;
            input.setAttribute("aria-expanded", items.length ? "true" : "false");
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

        function fetchResults() {
            const query = input.value.trim();
            if (query.length < Number(box.dataset.suggestMin || 1)) {
                render("", []);
                close();
                return;
            }
            if (cache.has(query)) {
                render(query, cache.get(query));
                return;
            }
            if (controller) {
                controller.abort();
            }
            controller = new AbortController();
            const target = url + (url.includes("?") ? "&" : "?") + "q=" + encodeURIComponent(query);
            fetch(target, {signal: controller.signal, credentials: "same-origin", headers: {Accept: "application/json"}})
                .then(function (response) { return response.ok ? response.json() : {results: []}; })
                .then(function (data) {
                    const items = Array.isArray(data.results) ? data.results : [];
                    cache.set(query, items);
                    if (input.value.trim() === query) {
                        render(query, items);
                    }
                })
                .catch(function () { /* aborted or offline: the form still works */ });
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
