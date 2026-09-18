// Part of place_responder. Licensed under AGPL-3.0.
//
// place_responder: a place search that answers while a person is still typing.
//
// It holds a country's places in memory -- read from an Odoo database with place_graph, or
// from a place bundle on disk -- and ranks them exactly as search_suggest publishes: the
// same folding of Persian text, the same six match kinds, the same weights, over every
// place rather than a shortlist. It reads and never writes: what a person picks goes back
// to the application that owns the data, as an id or a code, and is checked there.
//
//	place_responder -dsn "postgres://ro@db/ikiku"          live from Odoo
//	place_responder -bundle addons/place_ir/data           from a bundle, no database
//	place_responder -bundle base -bundle ./ours            a bundle and a local overlay
//
// Every flag can be given in the environment instead: PLACES_DSN, PLACES_BUNDLE (a list
// separated by ':'), PLACES_LISTEN, PLACES_ADMIN, PLACES_LANG, PLACES_POLL, ...
//
// It is written to run beside the application it serves, on the same small machine, and to
// cost it little: one core is plenty, memory is bounded by GOMEMLIMIT, and at most
// -inflight searches run at once. It is NOT written to be offered to the public as a
// service of its own: it has no accounts, no quotas per caller, and no promise of being up.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"
)

type config struct {
	dsn       string
	bundles   []string
	listen    string
	adminAddr string
	lang      string
	poll      time.Duration
	debounce  time.Duration
	maxWait   time.Duration
	cacheSize int
	inflight  int
	origin    string
	maxAge    time.Duration
}

type listFlag []string

func (l *listFlag) String() string     { return strings.Join(*l, ":") }
func (l *listFlag) Set(v string) error { *l = append(*l, v); return nil }

func env(name, fallback string) string {
	if v := os.Getenv(name); v != "" {
		return v
	}
	return fallback
}

func envDuration(name string, fallback time.Duration) time.Duration {
	if v := os.Getenv(name); v != "" {
		if d, err := time.ParseDuration(v); err == nil {
			return d
		}
	}
	return fallback
}

func parseConfig(args []string) (config, error) {
	var cfg config
	var bundles listFlag
	fs := flag.NewFlagSet("place_responder", flag.ContinueOnError)
	fs.StringVar(&cfg.dsn, "dsn", env("PLACES_DSN", ""), "Postgres connection string of an Odoo database with place_graph (read-only role is enough)")
	dsnFile := fs.String("dsn-file", env("PLACES_DSN_FILE", ""), "read the connection string from this file (keeps the password out of the process list)")
	fs.Var(&bundles, "bundle", "a place bundle directory; repeat for overlays (later wins)")
	fs.StringVar(&cfg.listen, "listen", env("PLACES_LISTEN", "127.0.0.1:8070"), "public address (put a proxy in front)")
	fs.StringVar(&cfg.adminAddr, "admin", env("PLACES_ADMIN", "127.0.0.1:8071"), "admin address: /healthz, POST /reload; empty to disable")
	fs.StringVar(&cfg.lang, "lang", env("PLACES_LANG", "fa_IR"), "language answers are labelled in by default")
	fs.DurationVar(&cfg.poll, "poll", envDuration("PLACES_POLL", 10*time.Minute), "how often to check the source for a change nobody announced")
	fs.DurationVar(&cfg.debounce, "debounce", envDuration("PLACES_DEBOUNCE", 2*time.Second), "quiet time after a notification before reloading")
	fs.DurationVar(&cfg.maxWait, "max-wait", envDuration("PLACES_MAX_WAIT", 30*time.Second), "reload at the latest this long after the first notification of a burst")
	fs.IntVar(&cfg.cacheSize, "cache", 4096, "answers kept in memory (per generation of the data)")
	fs.IntVar(&cfg.inflight, "inflight", 4, "searches run at once; more wait up to 2s")
	fs.StringVar(&cfg.origin, "allow-origin", env("PLACES_ALLOW_ORIGIN", ""), "Access-Control-Allow-Origin, when pages on another origin ask directly")
	fs.DurationVar(&cfg.maxAge, "max-age", envDuration("PLACES_MAX_AGE", time.Minute), "how long a browser may reuse an answer")
	if err := fs.Parse(args); err != nil {
		return cfg, err
	}
	if len(bundles) == 0 {
		if v := os.Getenv("PLACES_BUNDLE"); v != "" {
			bundles = strings.Split(v, ":")
		}
	}
	cfg.bundles = bundles
	if *dsnFile != "" {
		raw, err := os.ReadFile(*dsnFile)
		if err != nil {
			return cfg, err
		}
		cfg.dsn = strings.TrimSpace(string(raw))
	}
	if (cfg.dsn == "") == (len(cfg.bundles) == 0) {
		return cfg, errors.New("give exactly one source: -dsn (Odoo) or -bundle (files)")
	}
	return cfg, nil
}

func main() {
	cfg, err := parseConfig(os.Args[1:])
	if err != nil {
		fmt.Fprintln(os.Stderr, "place_responder:", err)
		os.Exit(2)
	}
	log.SetFlags(log.LstdFlags | log.LUTC)
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	st := newState(cfg)
	hup := make(chan os.Signal, 1)
	signal.Notify(hup, syscall.SIGHUP)
	go func() {
		for range hup {
			st.requestReload("SIGHUP")
		}
	}()
	go st.run(ctx)

	srv := &server{state: st, allowOrigin: cfg.origin, busy: make(chan struct{}, cfg.inflight),
		cache: newLRU(cfg.cacheSize), cacheControl: fmt.Sprintf("public, max-age=%d", int(cfg.maxAge.Seconds()))}
	servers := []*http.Server{{Addr: cfg.listen, Handler: srv.public(), ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout: 10 * time.Second, WriteTimeout: 10 * time.Second, MaxHeaderBytes: 16 << 10}}
	if cfg.adminAddr != "" {
		servers = append(servers, &http.Server{Addr: cfg.adminAddr, Handler: srv.admin(),
			ReadHeaderTimeout: 5 * time.Second})
	}
	for _, s := range servers {
		go func(s *http.Server) {
			log.Printf("listening on %s", s.Addr)
			if err := s.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
				log.Fatalf("%s: %v", s.Addr, err)
			}
		}(s)
	}
	<-ctx.Done()
	shutdown, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	for _, s := range servers {
		s.Shutdown(shutdown)
	}
}
