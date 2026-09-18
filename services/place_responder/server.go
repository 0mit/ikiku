// Part of place_responder. Licensed under AGPL-3.0.
//
// HTTP. One public route, and a private one for whoever runs it.
//
//	GET /places/suggest?q=&kinds=&within=&limit=&lang=     (also /suggest)
//	  {"results": [{"id", "code", "label", "detail", "kind", "score", "field", "match",
//	                "boost"?, "point"?: [lat, lon]}], "generation": n}
//
//	  The same shape as Odoo's own /places/suggest, so a page can ask either and read the
//	  answer the same way; the extra keys say WHY each place was found, because the ranking
//	  is published and a caller is entitled to check it.
//
//	  kinds   a named set from the spec (city, area, all) or a comma list of kinds
//	  within  a place id or code: places inside it are lifted by the spec's within_boost
//	  quick   accepted and ignored -- every answer here is the full one
//
//	On the admin listener only (loopback by default, never proxied):
//	  GET  /healthz   what is loaded, from where, how old, how long it took
//	  POST /reload    load again now
//
// The responder never logs a query: people type their street into it, and some type their
// post code.
package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"
)

const (
	maxQueryRunes = 80
	defaultLimit  = 8
	maxLimit      = 25
)

type server struct {
	state        *state
	allowOrigin  string
	cacheControl string
	busy         chan struct{} // at most cap(busy) searches at once; the rest wait briefly
	cache        *lru
}

type answer struct {
	ID     int64       `json:"id"`
	Code   string      `json:"code"`
	Label  string      `json:"label"`
	Detail string      `json:"detail"`
	Kind   string      `json:"kind"`
	Score  float64     `json:"score"`
	Field  string      `json:"field"`
	Match  string      `json:"match"`
	Boost  float64     `json:"boost,omitempty"`
	Via    string      `json:"via,omitempty"` // the name of the finer place that matched
	Point  *[2]float64 `json:"point,omitempty"`
}

type reply struct {
	Results    []answer `json:"results"`
	Generation uint64   `json:"generation"`
}

func (s *server) public() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/places/suggest", s.suggest)
	mux.HandleFunc("/suggest", s.suggest)
	return mux
}

func (s *server) admin() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", s.health)
	mux.HandleFunc("/reload", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "POST", http.StatusMethodNotAllowed)
			return
		}
		s.state.requestReload("admin")
		w.WriteHeader(http.StatusAccepted)
		fmt.Fprintln(w, "reload requested")
	})
	mux.HandleFunc("/places/suggest", s.suggest) // so it can be tried without the proxy
	return mux
}

func (s *server) suggest(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		http.Error(w, "GET", http.StatusMethodNotAllowed)
		return
	}
	if s.allowOrigin != "" {
		w.Header().Set("Access-Control-Allow-Origin", s.allowOrigin)
		w.Header().Set("Vary", "Origin")
	}
	params := r.URL.Query()
	lang := params.Get("lang")
	ix := s.state.index(lang)
	if ix == nil {
		// Nothing loaded yet (or the source is gone): say so, and a page falls back to Odoo.
		w.Header().Set("Retry-After", "5")
		http.Error(w, "not ready", http.StatusServiceUnavailable)
		return
	}
	q := []rune(strings.TrimSpace(params.Get("q")))
	if len(q) > maxQueryRunes {
		q = q[:maxQueryRunes]
	}
	query := string(q)
	limit := defaultLimit
	if n, err := strconv.Atoi(params.Get("limit")); err == nil && n > 0 {
		limit = min(n, maxLimit)
	}
	kindsName := params.Get("kinds")
	kinds := ix.kindSet(kindsName)
	within := ix.resolve(params.Get("within"))

	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Cache-Control", s.cacheControl)
	w.Header().Set("X-Places-Generation", strconv.FormatUint(ix.Generation, 10))

	key := fmt.Sprintf("%d\x00%s\x00%s\x00%d\x00%d\x00%s", ix.Generation, ix.Lang, kindsName, within, limit, spaced(query))
	if body, ok := s.cache.get(key); ok {
		w.Write(body)
		return
	}
	select {
	case s.busy <- struct{}{}:
		defer func() { <-s.busy }()
	case <-time.After(2 * time.Second):
		http.Error(w, "busy", http.StatusServiceUnavailable)
		return
	case <-r.Context().Done():
		return
	}
	out := reply{Results: []answer{}, Generation: ix.Generation}
	for _, found := range ix.Search(query, Options{Kinds: kinds, Within: within, Limit: limit}) {
		p := found.Place
		a := answer{ID: p.ID, Code: p.Code, Label: name(p.Names, ix.Lang), Detail: p.Path, Kind: p.Kind,
			Score: found.Score, Field: found.Field, Match: found.Match}
		if found.Boost != 1 {
			a.Boost = found.Boost
		}
		if found.Via != nil {
			a.Via = name(found.Via.Names, ix.Lang)
		}
		if p.HasPoint {
			a.Point = &[2]float64{p.Lat, p.Lon}
		}
		out.Results = append(out.Results, a)
	}
	body, _ := json.Marshal(out)
	s.cache.put(key, body)
	w.Write(body)
}

func (s *server) health(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	report := s.state.report()
	status := http.StatusOK
	if report["ready"] != true {
		status = http.StatusServiceUnavailable
	}
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(report)
}

// kindSet: a named set from the spec, a comma list of kinds, or nil for the spec's default.
func (ix *Index) kindSet(value string) map[string]bool {
	if value == "" {
		value = ix.Spec.PickerDefault
	}
	list, named := ix.Spec.PickerKinds[value]
	if !named {
		list = strings.Split(value, ",")
	}
	set := map[string]bool{}
	for _, kind := range list {
		if kind = strings.TrimSpace(kind); kind != "" {
			set[kind] = true
		}
	}
	if len(set) == 0 {
		return nil
	}
	return set
}

// resolve a place given by id or by code; 0 when it is neither.
func (ix *Index) resolve(value string) int64 {
	if value == "" {
		return 0
	}
	if id, err := strconv.ParseInt(value, 10, 64); err == nil {
		if _, ok := ix.byID[id]; ok {
			return id
		}
		return 0
	}
	if p, ok := ix.byCode[value]; ok {
		return p.ID
	}
	return 0
}
