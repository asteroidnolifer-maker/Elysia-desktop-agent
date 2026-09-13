package main

import (
	"bytes"
	"encoding/json"
	"io/ioutil"
	"net/http"
	"net/url"
	"sync"
	"time"
)

type ResearchResult struct{ Source, Summary, URL string }

var (
	researchCache = map[string]struct {
		results []ResearchResult
		expires time.Time
	}{}
	researchCacheMu sync.Mutex
	tokens          = make(chan struct{}, 4)
)

func init() {
	// fill tokens
	for i := 0; i < cap(tokens); i++ {
		tokens <- struct{}{}
	}
	// refill goroutine
	go func() {
		ticker := time.NewTicker(time.Second)
		for range ticker.C {
			select {
			case tokens <- struct{}{}:
			default:
			}
		}
	}()
}

func cacheGet(key string) ([]ResearchResult, bool) {
	researchCacheMu.Lock()
	defer researchCacheMu.Unlock()
	if e, ok := researchCache[key]; ok {
		if time.Now().Before(e.expires) {
			return e.results, true
		}
		delete(researchCache, key)
	}
	return nil, false
}

func cacheSet(key string, res []ResearchResult, d time.Duration) {
	researchCacheMu.Lock()
	defer researchCacheMu.Unlock()
	researchCache[key] = struct {
		results []ResearchResult
		expires time.Time
	}{results: res, expires: time.Now().Add(d)}
}

func QueryOSV(ecosystem, name, version string) ([]ResearchResult, error) {
	key := "osv:" + ecosystem + ":" + name + ":" + version
	if v, ok := cacheGet(key); ok {
		return v, nil
	}
	// rate limit
	<-tokens
	endpoint := "https://api.osv.dev/v1/query"
	reqBody := map[string]any{"version": version, "package": map[string]string{"name": name, "ecosystem": ecosystem}}
	b, _ := json.Marshal(reqBody)
	client := &http.Client{Timeout: 6 * time.Second}
	resp, err := client.Post(endpoint, "application/json", bytes.NewReader(b))
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, _ := ioutil.ReadAll(resp.Body)
	var data map[string]any
	_ = json.Unmarshal(body, &data)
	var out []ResearchResult
	if vulns, ok := data["vulns"].([]any); ok {
		for _, v := range vulns {
			if m, ok := v.(map[string]any); ok {
				title, _ := m["summary"].(string)
				url := ""
				if refs, ok := m["references"].([]any); ok && len(refs) > 0 {
					if r0, ok := refs[0].(map[string]any); ok {
						url, _ = r0["url"].(string)
					}
				}
				out = append(out, ResearchResult{Source: "osv", Summary: title, URL: url})
			}
		}
	}
	cacheSet(key, out, 6*time.Hour)
	return out, nil
}

func QueryGoogleCSE(apiKey, cx, query string) ([]ResearchResult, error) {
	if apiKey == "" || cx == "" {
		return nil, nil
	}
	key := "google:" + query
	if v, ok := cacheGet(key); ok {
		return v, nil
	}
	<-tokens
	url := "https://www.googleapis.com/customsearch/v1?key=" + url.QueryEscape(apiKey) + "&cx=" + url.QueryEscape(cx) + "&q=" + url.QueryEscape(query)
	client := &http.Client{Timeout: 6 * time.Second}
	resp, err := client.Get(url)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, _ := ioutil.ReadAll(resp.Body)
	var res struct {
		Items []struct{ Title, Link, Snippet string }
	}
	_ = json.Unmarshal(body, &res)
	out := []ResearchResult{}
	for _, it := range res.Items {
		out = append(out, ResearchResult{Source: "google", Summary: it.Snippet, URL: it.Link})
	}
	cacheSet(key, out, 24*time.Hour)
	return out, nil
}

func SearchVulnerabilities(cfg AgentConfig, ecosystem, name, version string) ([]ResearchResult, error) {
	res, _ := QueryOSV(ecosystem, name, version)
	if len(res) > 0 {
		return res, nil
	}
	if cfg.GoogleAPIKey != "" && cfg.GoogleCX != "" {
		return QueryGoogleCSE(cfg.GoogleAPIKey, cfg.GoogleCX, name+" "+version)
	}
	return res, nil
}
