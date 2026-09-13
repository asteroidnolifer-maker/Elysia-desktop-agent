package main

import (
	"net"
	"net/http"
	"strings"
	"sync"
	"time"
)

// requestKey returns the client identity: the X-Forwarded-For first hop when
// present, otherwise the remote address host.
func requestKey(r *http.Request) string {
	if f := r.Header.Get("X-Forwarded-For"); f != "" {
		first := strings.SplitN(f, ",", 2)[0]
		if first = strings.TrimSpace(first); first != "" {
			return first
		}
	}
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}

func isLoopback(host string) bool {
	ip := net.ParseIP(host)
	return ip != nil && (ip.IsLoopback() || ip.IsLinkLocalUnicast() && strings.HasPrefix(host, "fe80:"))
}

// guard wraps a mutating handler with API-key auth, per-IP rate limiting and
// audit logging so the open HTTP surface cannot be abused.
func guard(h http.HandlerFunc, action string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !authorize(w, r, action) {
			return
		}
		h(w, r)
	}
}

// guardMiddleware protects every non-GET request router-wide.
func guardMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodGet || r.Method == http.MethodHead {
			next.ServeHTTP(w, r)
			return
		}
		if !authorize(w, r, r.Method+" "+r.URL.Path) {
			return
		}
		next.ServeHTTP(w, r)
	})
}

// authorize enforces API-key auth and rate limiting. Returns false after it
// has written the error response.
func authorize(w http.ResponseWriter, r *http.Request, action string) bool {
	cfg := Config()
	key := requestKey(r)
	if cfg.APIKey != "" {
		got := r.Header.Get("Authorization")
		if got == "" {
			got = r.Header.Get("X-Api-Key")
		}
		got = strings.TrimSpace(strings.TrimPrefix(strings.TrimPrefix(got, "Bearer"), "bearer"))
		if got != cfg.APIKey {
			http.Error(w, `{"error":"unauthorized"}`, http.StatusUnauthorized)
			return false
		}
	} else if !isLoopback(key) {
		// No API key configured: refuse non-loopback mutating traffic.
		http.Error(w, `{"error":"set api_key in agent_config.json to allow remote access"}`, http.StatusForbidden)
		return false
	}
	if !rateAllow(key) {
		http.Error(w, `{"error":"rate limit exceeded"}`, http.StatusTooManyRequests)
		return false
	}
	Audit().Add(action, map[string]any{"ip": key, "path": r.URL.Path})
	return true
}

// ---- per-IP token bucket rate limiter ----

type bucket struct {
	tokens float64
	last   time.Time
}

var (
	rlMu   sync.Mutex
	rlBkts = map[string]*bucket{}
)

// rateAllow enforces RateLimitPerMin tokens per client.
func rateAllow(key string) bool {
	perMin := Config().RateLimitPerMin
	if perMin <= 0 {
		perMin = DefaultConfig.RateLimitPerMin
	}
	rlMu.Lock()
	defer rlMu.Unlock()
	now := time.Now()
	b, ok := rlBkts[key]
	if !ok {
		b = &bucket{tokens: float64(perMin), last: now}
		rlBkts[key] = b
	}
	elapsed := now.Sub(b.last).Seconds()
	b.tokens += elapsed * (float64(perMin) / 60.0)
	if b.tokens > float64(perMin) {
		b.tokens = float64(perMin)
	}
	b.last = now
	if b.tokens < 1 {
		return false
	}
	b.tokens--
	return true
}
