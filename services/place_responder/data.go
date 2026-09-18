// Part of place_responder. Licensed under AGPL-3.0.
//
// Where the places come from. Two sources, one shape:
//
//   - an Odoo database with place_graph installed (live: it is what the forms write, and it
//     tells the responder when it changed, see state.go);
//   - a place bundle on disk (place_graph/tools/bundle.py) -- for anybody who has no Odoo at
//     all and only wants the places searched, and for a test that needs no database.
//
// Either way the responder READS. It never writes a place, a suggestion or anything else:
// what a person picks goes back to whoever owns the data, as an id or a code.
package main

import (
	"context"
	"encoding/csv"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"

	"github.com/jackc/pgx/v5"
)

type Place struct {
	ID       int64
	Code     string
	Names    names // per language; "" holds the source value
	NameEn   string
	Kind     string
	Parent   int64
	InPath   bool
	Active   bool
	Sequence int
	Path     string // as the source stored it; computed for a bundle
	Lat, Lon float64
	HasPoint bool
}

type Alias struct {
	Place int64
	Names names
	Kind  string
}

// names is a translated value: (language, text) pairs. A slice, not a map: a hundred
// thousand places with one or two languages each cost a map apiece otherwise, which was
// the largest thing the responder held.
type names []langName

type langName struct{ lang, value string }

func namesOf(values map[string]string) names {
	out := make(names, 0, len(values))
	for lang, value := range values {
		out = append(out, langName{lang, value})
	}
	return out
}

func source(value string) names { return names{{"", value}} }

type Link struct {
	Place, Other int64
	Relation     string
}

type Postcode struct {
	Prefix string
	Place  int64
	Source string
	Hits   int
}

type Dataset struct {
	Places    []Place
	Aliases   []Alias
	Links     []Link // one row per direction, as the table holds them
	Postcodes []Postcode
	Langs     []string // installed languages; empty for a bundle
	Spec      Spec
	SpecErr   error
	Origin    string // "odoo" or "bundle:<dir>"
	Stamp     string // what changed means: a fingerprint of the source
}

// name reads a translated value the way Odoo does: the language asked for, else the source.
func name(values names, lang string) string {
	fallback, source := "", ""
	for _, v := range values {
		switch v.lang {
		case lang:
			return v.value
		case "en_US":
			fallback = v.value
		case "":
			source = v.value
		}
	}
	if fallback != "" {
		return fallback
	}
	return source
}

// ------------------------------------------------------------------------------ Odoo

// loadOdoo reads the place tables. Every row, active or not: an archived place can still be
// above an active one, and its name is still how people find what is inside it.
func loadOdoo(ctx context.Context, conn *pgx.Conn) (*Dataset, error) {
	d := &Dataset{Origin: "odoo"}
	rows, err := conn.Query(ctx, `SELECT code FROM res_lang WHERE active ORDER BY id`)
	if err != nil {
		return nil, fmt.Errorf("languages: %w", err)
	}
	for rows.Next() {
		var code string
		if err := rows.Scan(&code); err != nil {
			return nil, err
		}
		d.Langs = append(d.Langs, code)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}

	var specRaw []byte
	// A one-row view place_graph keeps: the role this runs as may read the spec and not the
	// rest of ir_config_parameter, which holds secrets.
	err = conn.QueryRow(ctx, `SELECT value FROM place_responder_spec`).Scan(&specRaw)
	if err != nil && err != pgx.ErrNoRows {
		return nil, fmt.Errorf("spec: %w", err)
	}
	d.Spec, d.SpecErr = parseSpec(specRaw)

	rows, err = conn.Query(ctx, `
		SELECT id, code, name, COALESCE(name_en, ''), kind, COALESCE(parent_id, 0), COALESCE(in_path, true),
		       COALESCE(active, true), COALESCE(sequence, 100), COALESCE(path, ''),
		       latitude::float8, longitude::float8
		  FROM place_node`)
	if err != nil {
		return nil, fmt.Errorf("places: %w", err)
	}
	for rows.Next() {
		var p Place
		var raw []byte
		var lat, lon *float64
		if err := rows.Scan(&p.ID, &p.Code, &raw, &p.NameEn, &p.Kind, &p.Parent, &p.InPath, &p.Active,
			&p.Sequence, &p.Path, &lat, &lon); err != nil {
			return nil, err
		}
		var values map[string]string
		if err := json.Unmarshal(raw, &values); err != nil {
			return nil, fmt.Errorf("place %d: name is not a translated value: %w", p.ID, err)
		}
		p.Names = namesOf(values)
		if lat != nil && lon != nil && (*lat != 0 || *lon != 0) {
			p.Lat, p.Lon, p.HasPoint = *lat, *lon, true
		}
		d.Places = append(d.Places, p)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}

	rows, err = conn.Query(ctx, `SELECT place_id, name, kind FROM place_alias WHERE COALESCE(active, true) ORDER BY place_id, id`)
	if err != nil {
		return nil, fmt.Errorf("aliases: %w", err)
	}
	for rows.Next() {
		var a Alias
		var raw []byte
		if err := rows.Scan(&a.Place, &raw, &a.Kind); err != nil {
			return nil, err
		}
		var values map[string]string
		if err := json.Unmarshal(raw, &values); err != nil {
			return nil, err
		}
		a.Names = namesOf(values)
		d.Aliases = append(d.Aliases, a)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}

	rows, err = conn.Query(ctx, `SELECT place_id, other_id, relation FROM place_link WHERE COALESCE(active, true) ORDER BY place_id, relation, id`)
	if err != nil {
		return nil, fmt.Errorf("links: %w", err)
	}
	for rows.Next() {
		var l Link
		if err := rows.Scan(&l.Place, &l.Other, &l.Relation); err != nil {
			return nil, err
		}
		d.Links = append(d.Links, l)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}

	rows, err = conn.Query(ctx, `SELECT prefix, place_id, source, COALESCE(hits, 0) FROM place_postcode`)
	if err != nil {
		return nil, fmt.Errorf("postcodes: %w", err)
	}
	for rows.Next() {
		var pc Postcode
		if err := rows.Scan(&pc.Prefix, &pc.Place, &pc.Source, &pc.Hits); err != nil {
			return nil, err
		}
		d.Postcodes = append(d.Postcodes, pc)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	d.Stamp, err = odooStamp(ctx, conn)
	return d, err
}

// odooStamp is a cheap "did anything change": the statistics collector's counts of rows
// written to each place table, the spec and the languages. Reading it costs nothing -- no
// table is scanned -- which is what lets the responder ask every few minutes as a safety net
// under LISTEN/NOTIFY. It can say "changed" when nothing did (a rolled-back transaction
// still counts); the price of that is one reload, never a stale answer.
func odooStamp(ctx context.Context, conn *pgx.Conn) (string, error) {
	var stamp string
	err := conn.QueryRow(ctx, `
		SELECT COALESCE(string_agg(relname || ':' || (n_tup_ins + n_tup_upd + n_tup_del)::text, ',' ORDER BY relname), '')
		       || '|' || COALESCE((SELECT md5(value) FROM place_responder_spec), '')
		       || '|' || COALESCE((SELECT string_agg(code, ',' ORDER BY code) FROM res_lang WHERE active), '')
		  FROM pg_stat_user_tables
		 WHERE relname IN ('place_node', 'place_alias', 'place_link', 'place_postcode')`).Scan(&stamp)
	return stamp, err
}

// ---------------------------------------------------------------------------- bundle

// loadBundle reads a place bundle. A bundle has no database ids, so places are numbered in
// file order; a caller that needs a key that survives the next bundle uses `code`, which
// every answer carries. Later directories are overlays: a row with a code already seen
// replaces it, so a site can keep its own decisions in a small bundle beside the big one.
func loadBundle(dirs []string) (*Dataset, error) {
	d := &Dataset{Origin: "bundle:" + strings.Join(dirs, "+")}
	idOf := map[string]int64{}
	var stamps []string
	specSet := false
	for _, dir := range dirs {
		manifestRaw, err := os.ReadFile(filepath.Join(dir, "manifest.json"))
		if err != nil {
			return nil, fmt.Errorf("%s: not a bundle: %w", dir, err)
		}
		var manifest struct {
			Format string          `json:"format"`
			Spec   json.RawMessage `json:"spec"`
			Files  map[string]struct {
				Sha256 string `json:"sha256"`
			} `json:"files"`
		}
		if err := json.Unmarshal(manifestRaw, &manifest); err != nil {
			return nil, fmt.Errorf("%s/manifest.json: %w", dir, err)
		}
		if manifest.Format != "place-bundle/1" {
			return nil, fmt.Errorf("%s: format %q, this responder reads place-bundle/1", dir, manifest.Format)
		}
		if !specSet {
			d.Spec, d.SpecErr = parseSpec(manifest.Spec)
			specSet = true
		}
		names := make([]string, 0, len(manifest.Files))
		for name := range manifest.Files {
			names = append(names, name)
		}
		sort.Strings(names)
		for _, name := range names {
			stamps = append(stamps, name+":"+manifest.Files[name].Sha256)
		}

		index := map[string]int{}
		for i, p := range d.Places {
			index[p.Code] = i
		}
		err = readCSV(filepath.Join(dir, "places.csv"), true, func(r map[string]string) error {
			// Cloned and interned: a field of a CSV record is a slice of the whole line, and
			// keeping one small field would keep every line of the file alive.
			code := strings.Clone(r["code"])
			p := Place{Code: code, Names: source(strings.Clone(r["name"])), NameEn: strings.Clone(r["name_en"]),
				Kind:   intern(r["kind"]),
				InPath: r["in_path"] != "False", Active: true, Sequence: 100}
			if r["parent"] != "" {
				parent, ok := idOf[r["parent"]]
				if !ok {
					return fmt.Errorf("places.csv: %s: parent %s is not above it", code, r["parent"])
				}
				p.Parent = parent
			}
			if lat, err := strconv.ParseFloat(r["latitude"], 64); err == nil {
				if lon, err := strconv.ParseFloat(r["longitude"], 64); err == nil {
					p.Lat, p.Lon, p.HasPoint = lat, lon, true
				}
			}
			if i, seen := index[code]; seen {
				p.ID = d.Places[i].ID
				d.Places[i] = p
				return nil
			}
			p.ID = int64(len(d.Places) + 1)
			idOf[code] = p.ID
			index[code] = len(d.Places)
			d.Places = append(d.Places, p)
			return nil
		})
		if err != nil {
			return nil, err
		}
		err = readCSV(filepath.Join(dir, "aliases.csv"), false, func(r map[string]string) error {
			id, ok := idOf[r["place"]]
			if !ok {
				return fmt.Errorf("aliases.csv: place %s is not in places.csv", r["place"])
			}
			d.Aliases = append(d.Aliases, Alias{Place: id, Names: source(strings.Clone(r["name"])), Kind: intern(r["kind"])})
			return nil
		})
		if err != nil {
			return nil, err
		}
		err = readCSV(filepath.Join(dir, "links.csv"), false, func(r map[string]string) error {
			a, okA := idOf[r["place"]]
			b, okB := idOf[r["other"]]
			if !okA || !okB {
				return fmt.Errorf("links.csv: %s-%s names a place that is not in places.csv", r["place"], r["other"])
			}
			relation := intern(r["relation"])
			d.Links = append(d.Links, Link{a, b, relation}, Link{b, a, relation})
			return nil
		})
		if err != nil {
			return nil, err
		}
		err = readCSV(filepath.Join(dir, "postcodes.csv"), false, func(r map[string]string) error {
			id, ok := idOf[r["place"]]
			if !ok {
				return fmt.Errorf("postcodes.csv: place %s is not in places.csv", r["place"])
			}
			hits, _ := strconv.Atoi(r["hits"])
			d.Postcodes = append(d.Postcodes, Postcode{strings.Clone(r["prefix"]), id, intern(r["source"]), hits})
			return nil
		})
		if err != nil {
			return nil, err
		}
	}
	if !specSet {
		d.Spec, _ = parseSpec(nil)
	}
	// A bundle stores no path; it is worked out exactly as place_graph's tree.read_path does.
	byID := make(map[int64]*Place, len(d.Places))
	for i := range d.Places {
		byID[d.Places[i].ID] = &d.Places[i]
	}
	for i := range d.Places {
		d.Places[i].Path = readPath(&d.Places[i], byID, "", d.Spec.PathSeparator)
	}
	d.Stamp = strings.Join(stamps, ",")
	return d, nil
}

// loadBundleStamp is what the poll compares: the checksums in every manifest, nothing more.
func loadBundleStamp(dirs []string) (string, error) {
	var stamps []string
	for _, dir := range dirs {
		raw, err := os.ReadFile(filepath.Join(dir, "manifest.json"))
		if err != nil {
			return "", err
		}
		var manifest struct {
			Files map[string]struct {
				Sha256 string `json:"sha256"`
			} `json:"files"`
		}
		if err := json.Unmarshal(raw, &manifest); err != nil {
			return "", err
		}
		names := make([]string, 0, len(manifest.Files))
		for name := range manifest.Files {
			names = append(names, name)
		}
		sort.Strings(names)
		for _, name := range names {
			stamps = append(stamps, name+":"+manifest.Files[name].Sha256)
		}
	}
	return strings.Join(stamps, ","), nil
}

var interned sync.Map

// intern keeps one copy of a string that repeats: a kind, a relation, a source.
func intern(s string) string {
	if v, ok := interned.Load(s); ok {
		return v.(string)
	}
	s = strings.Clone(s)
	interned.Store(s, s)
	return s
}

func readCSV(path string, required bool, row func(map[string]string) error) error {
	handle, err := os.Open(path)
	if err != nil {
		if os.IsNotExist(err) && !required {
			return nil
		}
		return err
	}
	defer handle.Close()
	reader := csv.NewReader(handle)
	reader.FieldsPerRecord = -1
	header, err := reader.Read()
	if err != nil {
		return fmt.Errorf("%s: %w", filepath.Base(path), err)
	}
	for {
		record, err := reader.Read()
		if err == io.EOF {
			return nil
		}
		if err != nil {
			return fmt.Errorf("%s: %w", filepath.Base(path), err)
		}
		values := make(map[string]string, len(header))
		for i, column := range header {
			if i < len(record) {
				values[column] = record[i]
			}
		}
		if err := row(values); err != nil {
			return err
		}
	}
}

// --------------------------------------------------------------------------- the tree

var fineness = map[string]int{"country": 0, "province": 1, "county": 2, "city": 3, "village": 3,
	"district": 4, "neighbourhood": 5, "street": 6, "other": 4}

func finenessOf(kind string) int {
	if f, ok := fineness[kind]; ok {
		return f
	}
	return 4
}

// ancestors is tree.chain: the places above, nearest first, safe against a cycle.
func ancestors(p *Place, byID map[int64]*Place) []*Place {
	var out []*Place
	seen := map[int64]bool{p.ID: true}
	for parent := p.Parent; parent != 0 && !seen[parent] && len(out) < 48; {
		above, ok := byID[parent]
		if !ok {
			break
		}
		out = append(out, above)
		seen[parent] = true
		parent = above.Parent
	}
	return out
}

// readPath is tree.read_path, for a bundle, which stores no path.
func readPath(p *Place, byID map[int64]*Place, lang, separator string) string {
	var parts []string
	if p.InPath {
		parts = append(parts, name(p.Names, lang))
	}
	fine := finenessOf(p.Kind)
	var shown []*Place
	for _, a := range ancestors(p, byID) {
		if a.InPath {
			shown = append(shown, a)
		}
	}
	groups := [][]string{{"neighbourhood", "district"}, {"city", "village"}, {"province"}}
	for g, kinds := range groups {
		if len(parts) >= 3 {
			break
		}
		for _, a := range shown {
			if contains(kinds, a.Kind) && finenessOf(a.Kind) < fine {
				n := name(a.Names, lang)
				if !contains(parts, n) {
					parts = append(parts, n)
					if g == 1 {
						goto done
					}
				}
				break
			}
		}
	}
done:
	if len(parts) > 3 {
		parts = parts[:3]
	}
	return strings.Join(parts, separator)
}

func contains(list []string, value string) bool {
	for _, item := range list {
		if item == value {
			return true
		}
	}
	return false
}
