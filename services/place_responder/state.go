// Part of place_responder. Licensed under AGPL-3.0.
//
// Keeping the index current.
//
// A reload reads the whole source and builds a new index beside the old one; searches keep
// using the old one until the new one is complete, and then it is swapped in with a single
// pointer store. Nobody ever waits for a reload and nobody ever sees half of one.
//
// What asks for a reload:
//   - Odoo: NOTIFY place_graph_changed, which place_graph's triggers send on COMMIT of any
//     statement that changed a place table. Several arriving together are one reload
//     (debounce), and a stream that never stops is still reloaded every maxWait.
//   - Odoo, as a safety net: a poll of the statistics counters every `poll` (odooStamp), for
//     the notification that was sent while the connection was down.
//   - a bundle: its manifest's checksums, polled.
//   - a person: POST /reload on the admin listener, or SIGHUP.
package main

import (
	"context"
	"log"
	"runtime/debug"
	"sync"
	"sync/atomic"
	"time"

	"github.com/jackc/pgx/v5"
)

type state struct {
	cfg        config
	current    atomic.Pointer[map[string]*Index]
	fallback   atomic.Pointer[string] // the language answered in when the one asked for is not built
	generation atomic.Uint64
	requests   chan string

	mu         sync.Mutex
	loadedAt   time.Time
	loadTime   time.Duration
	lastError  string
	lastReason string
	stamp      string
	origin     string
	counts     map[string]int
	specNote   string
}

func newState(cfg config) *state {
	return &state{cfg: cfg, requests: make(chan string, 16)}
}

// index for a language: the one asked for, else the default.
func (s *state) index(lang string) *Index {
	m := s.current.Load()
	if m == nil {
		return nil
	}
	if ix, ok := (*m)[lang]; ok {
		return ix
	}
	if f := s.fallback.Load(); f != nil {
		return (*m)[*f]
	}
	return nil
}

func (s *state) requestReload(reason string) {
	select {
	case s.requests <- reason:
	default: // one is already queued; it will read everything anyway
	}
}

// load reads a bundle and swaps the new index in.
func (s *state) load(ctx context.Context, _ *pgx.Conn) error {
	started := time.Now()
	d, err := loadBundle(s.cfg.bundles)
	return s.install(d, err, started)
}

// install builds the index from what was read and swaps it in. Nothing here holds the
// source: for Odoo, the read transaction is over before the (long) build begins.
func (s *state) install(d *Dataset, err error, started time.Time) error {
	if err != nil {
		s.mu.Lock()
		s.lastError = err.Error()
		s.mu.Unlock()
		return err
	}
	read := time.Since(started)
	generation := s.generation.Add(1)
	// One index per language the source has installed -- each is ~110 MiB for Iran, so a
	// language nobody installed is not built. A bundle has no languages: one index.
	langs := d.Langs
	if len(langs) == 0 {
		langs = []string{s.cfg.lang}
	}
	main := langs[0]
	for _, l := range langs {
		if l == s.cfg.lang {
			main = l
		}
	}
	built := map[string]*Index{}
	for _, lang := range langs {
		built[lang] = buildIndex(d, lang, generation)
	}
	s.fallback.Store(&main)
	s.current.Store(&built)
	ix := built[main]
	s.mu.Lock()
	s.loadedAt = time.Now()
	s.loadTime = time.Since(started)
	s.lastError = ""
	s.stamp = d.Stamp
	s.origin = d.Origin
	s.counts = map[string]int{"places": len(d.Places), "searchable": len(ix.docs), "aliases": len(d.Aliases),
		"links": len(d.Links) / 2, "postcodes": len(d.Postcodes), "texts": len(ix.texts), "words": len(ix.vocab)}
	switch {
	case d.SpecErr != nil:
		s.specNote = "published spec unreadable, defaults in use: " + d.SpecErr.Error()
	case !d.Spec.fromSource:
		s.specNote = "no spec published by the source; defaults in use"
	default:
		s.specNote = "from the source"
	}
	s.mu.Unlock()
	// The build's scratch and the previous index are garbage now. Hand the memory back to the
	// machine at once rather than whenever the runtime gets round to it: Odoo and Postgres
	// share it.
	d.Aliases, d.Links = nil, nil
	debug.FreeOSMemory()
	log.Printf("loaded generation %d from %s in %s (read %s, index %s): %d places (%d searchable), %d texts",
		generation, d.Origin, time.Since(started).Round(time.Millisecond), read.Round(time.Millisecond),
		ix.BuildTime.Round(time.Millisecond), len(d.Places), len(ix.docs), len(ix.texts))
	return nil
}

func (s *state) report() map[string]any {
	s.mu.Lock()
	defer s.mu.Unlock()
	return map[string]any{
		"ready":       s.current.Load() != nil,
		"generation":  s.serving(),
		"origin":      s.origin,
		"loaded_at":   s.loadedAt.UTC().Format(time.RFC3339),
		"load_ms":     s.loadTime.Milliseconds(),
		"last_error":  s.lastError,
		"last_reason": s.lastReason,
		"counts":      s.counts,
		"spec":        s.specNote,
		"lang":        s.cfg.lang,
	}
}

// run keeps the index current until ctx ends.
func (s *state) run(ctx context.Context) {
	if len(s.cfg.bundles) > 0 {
		s.runBundle(ctx)
		return
	}
	s.runOdoo(ctx)
}

func (s *state) runBundle(ctx context.Context) {
	if err := s.load(ctx, nil); err != nil {
		log.Printf("bundle: %v", err)
	}
	ticker := time.NewTicker(s.cfg.poll)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case reason := <-s.requests:
			s.setReason(reason)
			if err := s.load(ctx, nil); err != nil {
				log.Printf("bundle: %v", err)
			}
		case <-ticker.C:
			d, err := loadBundleStamp(s.cfg.bundles)
			if err == nil && d != s.currentStamp() {
				s.setReason("bundle changed")
				if err := s.load(ctx, nil); err != nil {
					log.Printf("bundle: %v", err)
				}
			}
		}
	}
}

// runOdoo keeps one connection LISTENing and reconnects when it drops. A reconnect always
// reloads: a notification sent while nobody listened is gone. Loading and polling use a
// connection of their own for as long as they need it -- they are rare, and a listening
// connection cannot run a query while it waits.
func (s *state) runOdoo(ctx context.Context) {
	backoff := time.Second
	for ctx.Err() == nil {
		err := s.session(ctx)
		if ctx.Err() != nil {
			return
		}
		s.mu.Lock()
		s.lastError = err.Error()
		s.mu.Unlock()
		log.Printf("database: %v; again in %s", err, backoff)
		select {
		case <-ctx.Done():
			return
		case <-time.After(backoff):
		}
		backoff = min(backoff*2, time.Minute)
	}
}

func (s *state) session(ctx context.Context) error {
	listener, err := pgx.Connect(ctx, s.cfg.dsn)
	if err != nil {
		return err
	}
	defer listener.Close(context.Background())
	if _, err := listener.Exec(ctx, "LISTEN place_graph_changed"); err != nil {
		return err
	}
	if err := s.loadOdooOnce(ctx); err != nil {
		return err
	}
	notified := make(chan string, 1)
	failed := make(chan error, 1)
	go func() {
		for {
			n, err := listener.WaitForNotification(ctx)
			if err != nil {
				failed <- err
				return
			}
			select {
			case notified <- n.Payload:
			default: // one is already waiting to be acted on
			}
		}
	}()

	poll := time.NewTicker(s.cfg.poll)
	defer poll.Stop()
	var debounce <-chan time.Time
	var pendingSince time.Time
	var pendingWhy string
	for {
		select {
		case <-ctx.Done():
			return nil
		case err := <-failed:
			return err
		case table := <-notified:
			// Wait for the burst to end: a bundle load is dozens of statements.
			if pendingSince.IsZero() {
				pendingSince = time.Now()
				pendingWhy = "notified (" + table + ")"
			}
			if time.Since(pendingSince) >= s.cfg.maxWait {
				debounce = time.After(0)
			} else {
				debounce = time.After(s.cfg.debounce)
			}
		case <-debounce:
			debounce = nil
			pendingSince = time.Time{}
			s.setReason(pendingWhy)
			if err := s.loadOdooOnce(ctx); err != nil {
				log.Printf("reload: %v", err)
			}
		case reason := <-s.requests:
			s.setReason(reason)
			if err := s.loadOdooOnce(ctx); err != nil {
				log.Printf("reload: %v", err)
			}
		case <-poll.C:
			stamp, err := s.odooStampOnce(ctx)
			if err != nil {
				log.Printf("poll: %v", err)
				continue
			}
			if stamp != s.currentStamp() {
				s.setReason("poll found a change")
				if err := s.loadOdooOnce(ctx); err != nil {
					log.Printf("reload: %v", err)
				}
			}
		}
	}
}

func (s *state) loadOdooOnce(ctx context.Context) error {
	conn, err := pgx.Connect(ctx, s.cfg.dsn)
	if err != nil {
		return err
	}
	defer conn.Close(context.Background())
	// One consistent picture: every table read from the same snapshot -- and the snapshot let
	// go of the moment the rows are in memory. Building the index takes seconds (tens on the
	// production VM), and a transaction held open that long holds read locks an Odoo update
	// needs: on 2026-09-18 it made a deploy fail on a lock timeout.
	started := time.Now()
	tx, err := conn.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.RepeatableRead, AccessMode: pgx.ReadOnly})
	if err != nil {
		return err
	}
	d, readErr := loadOdoo(ctx, tx.Conn())
	tx.Rollback(context.Background())
	conn.Close(context.Background())
	return s.install(d, readErr, started)
}

func (s *state) odooStampOnce(ctx context.Context) (string, error) {
	conn, err := pgx.Connect(ctx, s.cfg.dsn)
	if err != nil {
		return "", err
	}
	defer conn.Close(context.Background())
	return odooStamp(ctx, conn)
}

func (s *state) setReason(reason string) {
	s.mu.Lock()
	s.lastReason = reason + " at " + time.Now().UTC().Format(time.RFC3339)
	s.mu.Unlock()
}

func (s *state) currentStamp() string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.stamp
}

// serving is the generation answers come from right now; a reload in progress is not it.
func (s *state) serving() uint64 {
	if ix := s.index(""); ix != nil {
		return ix.Generation
	}
	return 0
}
