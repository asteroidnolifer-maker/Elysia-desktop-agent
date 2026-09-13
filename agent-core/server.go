package main

import (
	"encoding/json"
	"net/http"
	"strings"

	"github.com/gorilla/mux"
)

func NewRouter(tq *TaskQueue, mm *ModelManager, tm *ThermalManager, pm *PowerManager, opt *DeviceOptimizer, mr *MacroRunner, si *SysInfo, ag *Agent) http.Handler {
	r := mux.NewRouter()
	r.Use(guardMiddleware)

	r.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		_, _ = w.Write([]byte(indexPage(ag, mm)))
	}).Methods("GET")

	r.HandleFunc("/status", func(w http.ResponseWriter, r *http.Request) {
		s := map[string]any{"models": mm.ListModels(), "thermal": tm.Status(), "queue_len": tq.Len(), "health": "ok", "llm_backend": ag.llm.Backend()}
		_ = json.NewEncoder(w).Encode(s)
	}).Methods("GET")

	r.HandleFunc("/models", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(mm.ListModels())
	}).Methods("GET")

	r.HandleFunc("/models/register", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Name      string `json:"name"`
			Path      string `json:"path"`
			UnloadCmd string `json:"unload_cmd"`
		}
		_ = json.NewDecoder(r.Body).Decode(&req)
		mm.Register(req.Name, req.Path)
		// store unload command if provided
		mm.mu.Lock()
		if mi, ok := mm.models[req.Name]; ok {
			mi.UnloadCmd = req.UnloadCmd
			mm.models[req.Name] = mi
		}
		mm.mu.Unlock()
		Log("registered model: " + req.Name)
		_ = json.NewEncoder(w).Encode(map[string]any{"ok": true})
	}).Methods("POST")

	r.HandleFunc("/memory", func(w http.ResponseWriter, r *http.Request) {
		limit, used, count := mm.mem.Status()
		_ = json.NewEncoder(w).Encode(map[string]any{"limit": limit, "used": used, "count": count})
	}).Methods("GET")

	r.HandleFunc("/memory/set", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			LimitMB int64 `json:"limit_mb"`
		}
		_ = json.NewDecoder(r.Body).Decode(&req)
		mm.mem.SetLimit(req.LimitMB * 1024 * 1024)
		_ = json.NewEncoder(w).Encode(map[string]any{"ok": true})
	}).Methods("POST")

	r.HandleFunc("/task", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Prompt, Model string
			Async         bool
		}
		_ = json.NewDecoder(r.Body).Decode(&req)
		id := tq.Enqueue(req.Model, req.Prompt, req.Async)
		_ = json.NewEncoder(w).Encode(map[string]any{"task_id": id})
	}).Methods("POST")

	r.HandleFunc("/task/{id}", func(w http.ResponseWriter, r *http.Request) {
		vars := mux.Vars(r)
		id := vars["id"]
		st := tq.Status(id)
		_ = json.NewEncoder(w).Encode(st)
	}).Methods("GET")
	r.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{"status": "ok"})
	}).Methods("GET")

	r.HandleFunc("/logs", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(GetLogs())
	}).Methods("GET")

	r.HandleFunc("/scan", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Path  string `json:"path"`
			Apply bool   `json:"apply"`
		}
		_ = json.NewDecoder(r.Body).Decode(&req)
		rep, _ := ScanPath(req.Path)
		// Log scan request
		Audit().Add("scan", map[string]any{"path": req.Path, "apply": req.Apply})
		if req.Apply {
			// apply only medium/low automatically
			_ = ApplyPatches(rep)
			Audit().Add("apply_patches", map[string]any{"path": req.Path})
		}
		out := req.Path + "_security_report.json"
		_ = SaveReport(rep, out)
		_ = json.NewEncoder(w).Encode(rep)
	}).Methods("POST")

	r.HandleFunc("/infer/load", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Name string `json:"name"`
			Path string `json:"path"`
		}
		_ = json.NewDecoder(r.Body).Decode(&req)
		mm.Register(req.Name, req.Path)
		_ = json.NewEncoder(w).Encode(map[string]any{"ok": true})
	}).Methods("POST")

	r.HandleFunc("/infer/unload", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Name string `json:"name"`
		}
		_ = json.NewDecoder(r.Body).Decode(&req)
		mm.UnloadModel(req.Name)
		_ = json.NewEncoder(w).Encode(map[string]any{"ok": true})
	}).Methods("POST")

	r.HandleFunc("/infer/run", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Name   string `json:"name"`
			Prompt string `json:"prompt"`
		}
		_ = json.NewDecoder(r.Body).Decode(&req)
		ctx := r.Context()
		out, _ := mm.RunModel(ctx, req.Name, req.Prompt)
		_ = json.NewEncoder(w).Encode(map[string]any{"output": out})
	}).Methods("POST")

	r.HandleFunc("/api/link/status", func(w http.ResponseWriter, r *http.Request) {
		limit, used, count := mm.mem.Status()
		_ = json.NewEncoder(w).Encode(map[string]any{
			"thermal":   tm.Status(),
			"sysinfo":   si.Snapshot(),
			"memory":    map[string]any{"limit": limit, "used": used, "count": count},
			"queue_len": tq.Len(),
			"health":    "ok",
		})
	}).Methods("GET")

	r.HandleFunc("/sysinfo", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(si.Snapshot())
	}).Methods("GET")

	r.HandleFunc("/thermal", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(tm.Status())
	}).Methods("GET")

	r.HandleFunc("/power", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(pm.Status())
	}).Methods("GET")

	r.HandleFunc("/optimize", func(w http.ResponseWriter, r *http.Request) {
		rep := opt.RunSafeActions()
		_ = json.NewEncoder(w).Encode(rep)
	}).Methods("POST")

	r.HandleFunc("/optimize/governor", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Governor string `json:"governor"`
		}
		_ = json.NewDecoder(r.Body).Decode(&req)
		out, err := opt.ApplyCPUGovernor(req.Governor)
		_ = json.NewEncoder(w).Encode(map[string]any{"output": out, "error": errStr(err)})
	}).Methods("POST")

	r.HandleFunc("/macros", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(ListMacros())
	}).Methods("GET")

	r.HandleFunc("/macros/run", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Name string `json:"name"`
		}
		_ = json.NewDecoder(r.Body).Decode(&req)
		res, ok := mr.Run(req.Name)
		if !ok {
			w.WriteHeader(http.StatusNotFound)
			_ = json.NewEncoder(w).Encode(map[string]any{"error": "macro not found"})
			return
		}
		_ = json.NewEncoder(w).Encode(res)
	}).Methods("POST")

	r.HandleFunc("/models/catalog", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(AllModelSpecs())
	}).Methods("GET")

	r.HandleFunc("/models/recommend", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(opt.Recommendations())
	}).Methods("GET")

	r.HandleFunc("/research", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Query     string `json:"query"`
			Ecosystem string `json:"ecosystem,omitempty"`
			Name      string `json:"name,omitempty"`
			Version   string `json:"version,omitempty"`
		}
		_ = json.NewDecoder(r.Body).Decode(&req)
		cfg := Config()
		var results []ResearchResult
		if req.Ecosystem != "" {
			results, _ = SearchVulnerabilities(cfg, req.Ecosystem, req.Name, req.Version)
		} else if req.Query != "" {
			results, _ = QueryGoogleCSE(cfg.GoogleAPIKey, cfg.GoogleCX, req.Query)
		}
		_ = json.NewEncoder(w).Encode(map[string]any{
			"results":        results,
			"google_enabled": cfg.GoogleAPIKey != "" && cfg.GoogleCX != "",
		})
	}).Methods("POST")

	r.HandleFunc("/config", func(w http.ResponseWriter, r *http.Request) {
		cfg := Config()
		_ = json.NewEncoder(w).Encode(map[string]any{
			"google_api_key_set": cfg.GoogleAPIKey != "",
			"google_cx_set":      cfg.GoogleCX != "",
			"google_enabled":     cfg.GoogleAPIKey != "" && cfg.GoogleCX != "",
			"auto_apply_patches": cfg.AutoApplyPatches,
			"memory_limit_mb":    cfg.MemoryLimitMB,
			"osv_endpoint":       cfg.OSVEndpoint,
			"api_key_set":        cfg.APIKey != "",
			"llm_backend":        cfg.LLM.Backend,
			"llm_base_url":       cfg.LLM.OpenAIBaseURL,
			"llm_model":          cfg.LLM.OpenAIModel,
			"llm_temperature":    cfg.LLM.Temperature,
			"llm_max_tokens":     cfg.LLM.MaxTokens,
			"nim_base_url":       cfg.LLM.NIMBaseURL,
			"nim_model":          cfg.LLM.NIMModel,
			"llm_configured":     ag.llm.Configured(),
			"workspace_dir":      ag.sb.Workspace(),
			"rate_limit_per_min": cfg.RateLimitPerMin,
			"config_path":        ConfigPath(),
		})
	}).Methods("GET")

	r.HandleFunc("/config/update", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			LLMBackend   string  `json:"llm_backend"`
			LLMBaseURL   string  `json:"llm_base_url"`
			LLMModel     string  `json:"llm_model"`
			LLMKey       string  `json:"llm_api_key"`
			Temperature  float64 `json:"llm_temperature"`
			MaxTokens    int     `json:"llm_max_tokens"`
			MemoryLimit  int64   `json:"memory_limit_mb"`
			RateLimit    int     `json:"rate_limit_per_min"`
			WorkspaceDir string  `json:"workspace_dir"`
			BindAddr     string  `json:"bind_addr"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, `{"error":"bad json"}`, http.StatusBadRequest)
			return
		}
		cfg := Config()
		cfgPath := ConfigPath()
		cfg.LLM.Backend = req.LLMBackend
		cfg.LLM.OpenAIBaseURL = req.LLMBaseURL
		cfg.LLM.OpenAIModel = req.LLMModel
		if req.LLMKey != "" {
			cfg.LLM.OpenAIKey = req.LLMKey
		}
		if req.Temperature > 0 {
			cfg.LLM.Temperature = req.Temperature
		}
		if req.MaxTokens > 0 {
			cfg.LLM.MaxTokens = req.MaxTokens
		}
		if req.MemoryLimit > 0 {
			cfg.MemoryLimitMB = req.MemoryLimit
			mm.mem.SetLimit(req.MemoryLimit * 1024 * 1024)
		}
		if req.RateLimit > 0 {
			cfg.RateLimitPerMin = req.RateLimit
		}
		if req.WorkspaceDir != "" {
			cfg.WorkspaceDir = req.WorkspaceDir
		}
		if req.BindAddr != "" {
			cfg.BindAddr = req.BindAddr
		}
		activeConfig = applyConfigDefaults(cfg)
		ag.llm.Update(activeConfig.LLM)
		if err := SaveConfig(cfgPath, activeConfig); err != nil {
			http.Error(w, `{"error":"`+err.Error()+`"}`, http.StatusInternalServerError)
			return
		}
		Log("config updated via /config/update: backend=" + activeConfig.LLM.Backend)
		_ = json.NewEncoder(w).Encode(map[string]any{"ok": true, "llm_backend": activeConfig.LLM.Backend, "llm_configured": ag.llm.Configured()})
	}).Methods("POST")

	// ---- Jarvis: chat, tools, games, projects ----

	r.HandleFunc("/chat", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Message   string `json:"message"`
			SessionID string `json:"session_id,omitempty"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Message == "" {
			http.Error(w, `{"error":"message is required"}`, http.StatusBadRequest)
			return
		}
		reply, err := ag.Handle(r.Context(), req.SessionID, req.Message)
		_ = json.NewEncoder(w).Encode(map[string]any{"reply": reply, "error": errStr(err)})
	}).Methods("POST")

	r.HandleFunc("/tools/run", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Command string `json:"command"`
			Dir     string `json:"dir,omitempty"`
		}
		_ = json.NewDecoder(r.Body).Decode(&req)
		out, err := ag.sb.Run(req.Command, req.Dir, 0)
		_ = json.NewEncoder(w).Encode(map[string]any{"output": out, "error": errStr(err)})
	}).Methods("POST")

	r.HandleFunc("/tools/check", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Command string `json:"command"`
		}
		_ = json.NewDecoder(r.Body).Decode(&req)
		err := ag.sb.Check(req.Command)
		_ = json.NewEncoder(w).Encode(map[string]any{"allowed": err == nil, "error": errStr(err)})
	}).Methods("POST")

	r.HandleFunc("/games", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{"games": ag.games.List()})
	}).Methods("GET")

	r.HandleFunc("/games/{kind}/new", func(w http.ResponseWriter, r *http.Request) {
		kind := mux.Vars(r)["kind"]
		id, g, err := ag.games.New(kind)
		if err != nil {
			http.Error(w, errStr(err), http.StatusBadRequest)
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"id": id, "state": g.State()})
	}).Methods("POST")

	r.HandleFunc("/games/{kind}/{id}/move", func(w http.ResponseWriter, r *http.Request) {
		vars := mux.Vars(r)
		g, ok := ag.games.Get(vars["id"])
		if !ok {
			http.Error(w, `{"error":"no such game"}`, http.StatusNotFound)
			return
		}
		var req struct {
			Action string `json:"action"`
		}
		_ = json.NewDecoder(r.Body).Decode(&req)
		msg, err := g.Move(req.Action)
		if err != nil {
			_ = json.NewEncoder(w).Encode(map[string]any{"error": err.Error(), "state": g.State()})
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"message": msg, "state": g.State()})
	}).Methods("POST")

	r.HandleFunc("/games/{kind}/{id}/bot", func(w http.ResponseWriter, r *http.Request) {
		vars := mux.Vars(r)
		g, ok := ag.games.Get(vars["id"])
		if !ok {
			http.Error(w, `{"error":"no such game"}`, http.StatusNotFound)
			return
		}
		msg, err := g.Bot()
		_ = json.NewEncoder(w).Encode(map[string]any{"message": msg, "error": errStr(err), "state": g.State()})
	}).Methods("POST")

	r.HandleFunc("/games/{kind}/autoplay", func(w http.ResponseWriter, r *http.Request) {
		kind := mux.Vars(r)["kind"]
		var req struct {
			Rounds int `json:"rounds"`
		}
		_ = json.NewDecoder(r.Body).Decode(&req)
		if req.Rounds <= 0 {
			req.Rounds = 1
		}
		if req.Rounds > 5 {
			req.Rounds = 5
		}
		var results []string
		for i := 0; i < req.Rounds; i++ {
			out, err := ag.games.AutoPlay(kind)
			if err != nil {
				http.Error(w, errStr(err), http.StatusBadRequest)
				return
			}
			results = append(results, out)
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"rounds": req.Rounds, "results": results, "error": ""})
	}).Methods("POST")

	r.HandleFunc("/projects/list", func(w http.ResponseWriter, r *http.Request) {
		projects, err := ag.projects.List()
		_ = json.NewEncoder(w).Encode(map[string]any{"projects": projects, "error": errStr(err)})
	}).Methods("GET")

	r.HandleFunc("/projects/new", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Name        string `json:"name"`
			Language    string `json:"language"`
			Description string `json:"description"`
		}
		_ = json.NewDecoder(r.Body).Decode(&req)
		prj, err := ag.projects.Generate(r.Context(), req.Name, req.Language, req.Description)
		if err != nil {
			http.Error(w, errStr(err), http.StatusBadRequest)
			return
		}
		_ = json.NewEncoder(w).Encode(prj)
	}).Methods("POST")

	r.HandleFunc("/projects/test", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Name string `json:"name"`
		}
		_ = json.NewDecoder(r.Body).Decode(&req)
		prj, err := ag.projects.Test(r.Context(), req.Name)
		if err != nil {
			http.Error(w, errStr(err), http.StatusBadRequest)
			return
		}
		_ = json.NewEncoder(w).Encode(prj)
	}).Methods("POST")

	return r
}

func errStr(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}

func indexPage(ag *Agent, mm *ModelManager) string {
	cfg := Config()
	backend := ag.llm.Backend()
	configured := map[bool]string{true: "configured", false: "not configured"}[ag.llm.Configured()]
	workspace := ag.sb.Workspace()
	auth := map[bool]string{true: "requires API key", false: "localhost only"}[cfg.APIKey != ""]

	return `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Elysia JARVIS</title>
<style>
:root{--bg:#0b0e14;--panel:#12161f;--line:#1e2430;--text:#dbe2ea;--muted:#8a94a6;--accent:#5b8cff;--ok:#3ecf8e;--warn:#e5b567}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Inter,-apple-system,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.5;padding:2rem 1rem}
main{max-width:720px;margin:0 auto;display:flex;flex-direction:column;gap:1.25rem}
h1{font-size:1.25rem;font-weight:600;letter-spacing:.02em}
h2{font-size:.72rem;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:.5rem}
.pill{display:inline-block;font-size:.72rem;padding:.15rem .55rem;border-radius:99px;border:1px solid var(--line);color:var(--muted)}
.pill.ok{color:var(--ok);border-color:rgba(62,207,142,.4)}
section{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:1rem 1.1rem}
.meta{display:flex;flex-wrap:wrap;gap:.5rem;margin-top:.6rem}
pre{font-family:'SF Mono',Consolas,Menlo,monospace;font-size:.8rem;background:#0d1117;border:1px solid var(--line);border-radius:8px;padding:.7rem .8rem;white-space:pre-wrap;word-break:break-word;max-height:320px;overflow:auto}
input[type=text]{width:100%;background:#0d1117;border:1px solid var(--line);border-radius:8px;color:var(--text);padding:.55rem .7rem;font-size:.85rem}
button{background:var(--accent);border:none;color:#fff;border-radius:8px;padding:.5rem .9rem;font-size:.8rem;font-weight:600;cursor:pointer}
button:hover{opacity:.88}
button.ghost{background:transparent;border:1px solid var(--line);color:var(--muted)}
.row{display:flex;gap:.5rem}
.games{display:flex;flex-wrap:wrap;gap:.5rem;margin-top:.5rem}
.games button{background:transparent;border:1px solid var(--line);color:var(--text)}
.games button:disabled{opacity:.4;cursor:default}
.games button.busy{border-color:var(--accent)}
code{font-family:Consolas,Menlo,monospace;font-size:.78rem;background:#0d1117;padding:.1rem .4rem;border-radius:4px;color:#9fb6ff}
a{color:var(--accent);text-decoration:none}
.tabs{display:flex;gap:.25rem;border-bottom:1px solid var(--line);margin-bottom:.75rem}
.tabs button{background:none;border:none;color:var(--muted);font-size:.8rem;padding:.35rem .7rem;border-bottom:2px solid transparent;border-radius:0}
.tabs button.active{color:var(--text);border-bottom-color:var(--accent)}
.hidden{display:none}
.muted{color:var(--muted);font-size:.8rem}
.status{display:flex;align-items:center;gap:.4rem;font-size:.8rem;color:var(--muted)}
.dot{width:8px;height:8px;border-radius:50%;background:var(--ok)}
</style></head><body>
<main>
<section>
  <div style="display:flex;align-items:center;justify-content:space-between">
    <h1>Elysia JARVIS</h1>
    <span class="status"><span class="dot"></span>online</span>
  </div>
  <div class="meta">
    <span class="pill">` + backend + `</span>
    <span class="pill ok">` + configured + `</span>
    <span class="pill">` + auth + `</span>
    <span class="pill">` + workspace + `</span>
  </div>
</section>

<section>
  <div class="tabs">
    <button class="active" data-tab="chat">Chat</button>
    <button data-tab="games">Games</button>
    <button data-tab="settings">Settings</button>
  </div>

  <div id="tab-chat">
    <div class="row">
      <input type="text" id="msg" placeholder="Talk to JARVIS...">
      <button id="send">Send</button>
    </div>
    <div style="height:.6rem"></div>
    <pre id="chat-out">Say hello, or ask me to play a game on my own.</pre>
  </div>

  <div id="tab-games" class="hidden">
    <p class="muted">I play these by myself, no input needed.</p>
    <div class="games" id="games"></div>
    <div style="height:.6rem"></div>
    <pre id="game-out"></pre>
  </div>

  <div id="tab-settings" class="hidden">
    <p class="muted">Config file: <code id="cfg-path"></code></p>
    <div style="height:.75rem"></div>
    <label class="muted" for="s-backend">LLM backend</label>
    <div class="row" style="margin-top:.25rem">
      <select id="s-backend" style="flex:1;background:#0d1117;border:1px solid var(--line);border-radius:8px;color:var(--text);padding:.55rem .7rem;font-size:.85rem">
        <option value="openai">openai (OpenAI-compatible)</option>
        <option value="llama">llama (local llama.cpp)</option>
        <option value="nim">nim (NVIDIA NIM)</option>
      </select>
    </div>
    <div style="height:.75rem"></div>
    <label class="muted" for="s-url">Base URL</label>
    <input type="text" id="s-url" style="margin-top:.25rem" placeholder="http://127.0.0.1:11434/v1">
    <div style="height:.75rem"></div>
    <label class="muted" for="s-model">Model</label>
    <input type="text" id="s-model" style="margin-top:.25rem" placeholder="qwen2.5-coder:1.5b">
    <div style="height:.75rem"></div>
    <label class="muted" for="s-key">API key (leave blank to keep current)</label>
    <input type="text" id="s-key" style="margin-top:.25rem" placeholder="sk-...">
    <div style="height:.75rem"></div>
    <div class="row" style="gap:.75rem">
      <div style="flex:1"><label class="muted" for="s-temp">Temperature</label><input type="text" id="s-temp" style="margin-top:.25rem" placeholder="0.3"></div>
      <div style="flex:1"><label class="muted" for="s-tokens">Max tokens</label><input type="text" id="s-tokens" style="margin-top:.25rem" placeholder="1024"></div>
      <div style="flex:1"><label class="muted" for="s-mem">Memory limit MB</label><input type="text" id="s-mem" style="margin-top:.25rem" placeholder="512"></div>
    </div>
    <div style="height:.75rem"></div>
    <div class="row">
      <button id="savecfg">Save config</button>
      <button class="ghost" id="reloadcfg">Reload</button>
    </div>
    <div style="height:.75rem"></div>
    <p class="muted" id="cfg-out">Load settings to edit them.</p>
  </div>
</section>
</main>
<script>
const out = (el, s)=>{document.getElementById(el).textContent = s||''};
const tab = n => {
  document.querySelectorAll('.tabs button').forEach(b=>b.classList.toggle('active', b.dataset.tab===n));
  ['chat','games','settings'].forEach(t=>document.getElementById('tab-'+t).classList.toggle('hidden', t!==n));
};
document.querySelectorAll('.tabs button').forEach(b=>b.addEventListener('click',()=>tab(b.dataset.tab)));

const games = [` + strings.Join([]string{"tic-tac-toe", "rps", "hangman", "number-guess", "blackjack", "memory", "idle-miner"}, "\", \"") + `];
const gw = document.getElementById('games');
games.forEach(g=>{
  const b = document.createElement('button');
  b.textContent = g;
  b.onclick = async ()=>{
    b.disabled = true; b.classList.add('busy');
    out('game-out', 'playing '+g+'...');
    try{
      const r = await fetch('/games/'+g+'/autoplay',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
      const d = await r.json();
      out('game-out', (d.results||[]).join('\n---\n'));
    }catch(e){ out('game-out','error: '+e) }
    b.disabled = false; b.classList.remove('busy');
  };
  gw.appendChild(b);
});

document.getElementById('send').onclick = async ()=>{
  const msg = document.getElementById('msg').value.trim();
  if(!msg) return;
  out('chat-out','...');
  try{
    const r = await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:msg})});
    const d = await r.json();
    out('chat-out', d.reply || d.error);
  }catch(e){ out('chat-out','error: '+e) }
};
document.getElementById('msg').addEventListener('keydown',e=>{ if(e.key==='Enter') document.getElementById('send').click() });

const loadCfg = async ()=>{
  try{
    const r = await fetch('/config');
    const d = await r.json();
    document.getElementById('cfg-path').textContent = d.config_path || '';
    document.getElementById('s-backend').value = d.llm_backend || 'openai';
    document.getElementById('s-url').value = d.llm_base_url || '';
    document.getElementById('s-model').value = d.llm_model || '';
    document.getElementById('s-temp').value = d.llm_temperature || '';
    document.getElementById('s-tokens').value = d.llm_max_tokens || '';
    document.getElementById('s-mem').value = d.memory_limit_mb || '';
    document.getElementById('cfg-out').textContent = 'backend '+d.llm_backend+' ('+(d.llm_configured?'configured':'not configured')+')';
  }catch(e){ document.getElementById('cfg-out').textContent = 'error: '+e }
};
document.getElementById('reloadcfg').onclick = loadCfg;
document.getElementById('savecfg').onclick = async ()=>{
  const v = id => document.getElementById(id).value.trim();
  const body = {
    llm_backend: v('s-backend'),
    llm_base_url: v('s-url'),
    llm_model: v('s-model'),
    llm_api_key: v('s-key'),
    llm_temperature: parseFloat(v('s-temp')) || 0,
    llm_max_tokens: parseInt(v('s-tokens')) || 0,
    memory_limit_mb: parseInt(v('s-mem')) || 0
  };
  document.getElementById('cfg-out').textContent = 'saving...';
  try{
    const r = await fetch('/config/update',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const d = await r.json();
    document.getElementById('cfg-out').textContent = (d.ok?'saved: backend '+d.llm_backend+' ('+(d.llm_configured?'configured':'not configured')+')':'error: '+(d.error||JSON.stringify(d)));
  }catch(e){ document.getElementById('cfg-out').textContent = 'error: '+e }
};
loadCfg();
</script></body></html>`
}
