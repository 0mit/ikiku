/* Part of search_suggest. Licensed under AGPL-3.0.
 *
 * A suggest box over a plain input, as an ARIA combobox. Markup:
 *
 *   <div data-suggest data-suggest-url="/roles/suggest" data-suggest-count="{n} پیشنهاد">
 *     <input type="search" name="q" autocomplete="off"/>
 *   </div>
 *
 * The URL answers GET ?q=… with {"results": [{"id", "label", "detail"?, "via"?, "url"?}]}, and
 * &quick=1 with the tightest, cheapest search only. The full answer is asked for first; if it
 * has not arrived within QUICK_AFTER milliseconds, the quick one is asked for too and shown
 * in the meantime, so a slow search puts something true on the screen instead of nothing.
 * A search that answers quickly is asked once.
 * Choosing a result fires "search-suggest:choose" on the container with the result as
 * detail; unless a listener calls preventDefault(), a result with a url is opened.
 * Every full answer fires "search-suggest:results" with {query, count}, so a page can tell
 * a search that found nothing from one that has not answered yet.
 *
 * data-suggest-fallback="/other/url" is asked instead when data-suggest-url does not answer
 * (a network error, or anything but 200) -- for a fast search service in front of a slower
 * one that answers the same question. Once the first has failed, the page stays on the
 * second: a service that is down is not asked again on every key.
 *
 * While an answer is slower than BUSY_AFTER, the container carries search-suggest--busy
 * and aria-busy="true", and any child marked data-suggest-busy is shown: a page brings its
 * own sign of waiting. An answer faster than that shows nothing, so nothing flickers.
 * Without JavaScript the input is an ordinary field of its form, so nothing is lost.
 */
(function () {
    "use strict";

    const DELAY = 180;
    const QUICK_AFTER = 70;    // ms to wait for the full answer before showing a partial one
    const BUSY_AFTER = 150;    // ms before an answer that has not come counts as "fetching"
    let counter = 0;

    function setup(box) {
        if (box.dataset.suggestReady) {
            return;
        }
        box.dataset.suggestReady = "1";
        const input = box.querySelector("input");
        if (!input || !box.dataset.suggestUrl) {
            return;
        }
        // Read on every question, not once: a page may add parameters (a city, the kinds of
        // place on offer) after this runs, and the fallback replaces the first for good.
        let usingFallback = false;
        const endpoint = function () {
            return usingFallback ? box.dataset.suggestFallback : box.dataset.suggestUrl;
        };
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
        let busyTimer = null;

        function busy(on) {
            clearTimeout(busyTimer);
            if (on) {
                busyTimer = setTimeout(function () {
                    box.classList.add("search-suggest--busy");
                    box.setAttribute("aria-busy", "true");
                }, BUSY_AFTER);
            } else {
                box.classList.remove("search-suggest--busy");
                box.removeAttribute("aria-busy");
            }
        }

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
                // Found through something finer than the page offers («کرشته» for شهریار):
                // data-suggest-via="… {via} …" says so, so nobody wonders why this answered.
                if (item.via && box.dataset.suggestVia) {
                    const via = document.createElement("small");
                    via.className = "search-suggest__via";
                    via.textContent = box.dataset.suggestVia.replace("{via}", item.via);
                    option.append(via);
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
            const once = function () {
                const url = endpoint();
                const target = url + (url.includes("?") ? "&" : "?") + "q=" + encodeURIComponent(query)
                    + (quick ? "&quick=1" : "");
                return fetch(target, {signal: controller.signal, credentials: "same-origin",
                                      headers: {Accept: "application/json"}})
                    .then(function (response) {
                        if (!response.ok) {
                            throw new Error("HTTP " + response.status);
                        }
                        return response.json();
                    })
                    .then(function (data) { return Array.isArray(data.results) ? data.results : []; });
            };
            return once().catch(function (error) {
                // Aborted because the person typed on: not a failure of anybody's.
                if (error.name === "AbortError" || usingFallback || !box.dataset.suggestFallback) {
                    throw error;
                }
                usingFallback = true;
                return once();
            });
        }

        function fetchResults() {
            const query = input.value.trim();
            if (query.length < Number(box.dataset.suggestMin || 1)) {
                busy(false);
                render("", [], false);
                close();
                return;
            }
            if (cache.has(query)) {
                busy(false);
                render(query, cache.get(query), false);
                return;
            }
            controllers.forEach(function (controller) { controller.abort(); });
            controllers = [];
            const current = function () { return input.value.trim() === query; };
            let full = false;
            busy(true);
            ask(query, false).then(function (items) {
                full = true;
                cache.set(query, items);
                if (current()) {
                    busy(false);
                    render(query, items, false);
                    box.dispatchEvent(new CustomEvent("search-suggest:results",
                        {detail: {query: query, count: items.length}, bubbles: true}));
                }
            }).catch(function () {
                full = true;
                if (current()) {
                    busy(false);   // aborted or offline: the form still works without us
                }
            });
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
