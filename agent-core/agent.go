package main

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"sync"
)

// Agent is the Jarvis-style conversational brain: it routes user messages to
// tools (search, shell, files, macros, games, projects) and lets the LLM
// decide what to do, all behind the sandbox guardrails.
type Agent struct {
	llm      *LLMClient
	sb       *Sandbox
	mr       *MacroRunner
	games    *GameRegistry
	projects *Projects

	mu       sync.Mutex
	sessions map[string][]ChatMsg
}

func NewAgent(llm *LLMClient, sb *Sandbox, mr *MacroRunner) *Agent {
	return &Agent{
		llm:      llm,
		sb:       sb,
		mr:       mr,
		games:    NewGameRegistry(),
		projects: NewProjects(sb, llm),
		sessions: map[string][]ChatMsg{},
	}
}

const agentSystem = `You are JARVIS, a helpful AI assistant running on the user's own computer.
You can use tools. To use a tool, output ONLY a single JSON object on one line with no other text, one of:
{"tool":"search","query":"..."}                    web research
{"tool":"shell","command":"..."}                   run an allowlisted command in the sandbox (downloads/builds/tests)
{"tool":"read_file","path":"..."}                  read a file in the workspace
{"tool":"write_file","path":"...","content":"..."} write a file in the workspace
{"tool":"list_macros"}                             list optimization macros
{"tool":"run_macro","name":"..."}                  run a macro
{"tool":"list_games"}                              list playable games
{"tool":"new_game","game":"tic-tac-toe"}           start a game
{"tool":"move_game","id":"g1","action":"0"}        make a move in a game
{"tool":"autoplay","game":"blackjack","rounds":1}  play a full game by yourself, no human needed (rounds 1-5)
{"tool":"make_project","name":"...","language":"go","description":"..."} generate a complete project
{"tool":"test_project","name":"..."}               auto-test a generated project in the sandbox
{"tool":"done","answer":"..."}                     your final reply to the user
Rules:
- ACT, do not explain: when the user's request maps to a tool, output ONLY that tool's JSON and nothing else. Never describe the tool format, never paste example JSON, never use markdown.
- The workspace jail is %WORKSPACE%. Everything you write goes there. Never touch system files.
- The sandbox only allows safe commands (go, python, node, npm, git, cargo, curl, etc.) with no shell metacharacters.
- When you receive a message starting with "[tool result]", it is the OUTPUT of the tool you just ran. You must then give your final reply using {"tool":"done","answer":"..."} unless another tool is genuinely needed.
- Be concise and helpful. If you do not know something, say so.
`

// toolCall is the JSON shape the LLM emits to request a tool.
type toolCall struct {
	Tool        string `json:"tool"`
	Query       string `json:"query"`
	Command     string `json:"command"`
	Path        string `json:"path"`
	Content     string `json:"content"`
	Name        string `json:"name"`
	Game        string `json:"game"`
	ID          string `json:"id"`
	Action      string `json:"action"`
	Answer      string `json:"answer"`
	Language    string `json:"language"`
	Description string `json:"description"`
	Rounds      int    `json:"rounds"`
}

// Handle processes one user message and returns the assistant reply.
func (a *Agent) Handle(ctx context.Context, sessionID, message string) (string, error) {
	if sessionID == "" {
		sessionID = "default"
	}
	a.mu.Lock()
	hist := a.sessions[sessionID]
	if hist == nil {
		hist = []ChatMsg{}
	}
	hist = append(hist, ChatMsg{Role: "user", Content: message})
	a.sessions[sessionID] = hist
	a.mu.Unlock()

	// Hard cap history size.
	if len(hist) > 12 {
		hist = hist[len(hist)-12:]
	}

	reply, usedTool := a.runLoop(ctx, sessionID, hist)
	a.mu.Lock()
	hist = a.sessions[sessionID]
	hist = append(hist, ChatMsg{Role: "assistant", Content: reply})
	if len(hist) > 16 {
		hist = hist[len(hist)-16:]
	}
	a.sessions[sessionID] = hist
	a.mu.Unlock()
	Log(fmt.Sprintf("chat[%s] user=%q used_tool=%v", sessionID, truncate(message, 80), usedTool))
	return reply, nil
}

// parseToolCalls extracts the tool calls an LLM reply contains. Small models
// sometimes emit several JSON tool calls (or wrap them in fences), so we accept
// a single whole-object call or scan for any balanced JSON tool objects.
func parseToolCalls(s string) []toolCall {
	s = stripFences(s)
	var single toolCall
	if json.Unmarshal([]byte(s), &single) == nil && single.Tool != "" {
		return []toolCall{single}
	}
	var out []toolCall
	for i := 0; i < len(s); {
		j := strings.IndexByte(s[i:], '{')
		if j < 0 {
			break
		}
		j += i
		depth := 0
		k := j
		for k < len(s) {
			switch s[k] {
			case '{':
				depth++
			case '}':
				depth--
			}
			if depth == 0 {
				break
			}
			k++
		}
		block := s[j : k+1]
		var c toolCall
		if json.Unmarshal([]byte(block), &c) == nil && c.Tool != "" {
			out = append(out, c)
		}
		i = k + 1
	}
	return out
}

// runLoop iterates up to maxIter times, letting the LLM call tools until it
// emits a final answer. Falls back to deterministic intents when the LLM is
// unavailable or the reply is not a tool call.
func (a *Agent) runLoop(ctx context.Context, sessionID string, hist []ChatMsg) (string, bool) {
	sys := strings.ReplaceAll(agentSystem, "%WORKSPACE%", a.sb.Workspace())
	seen := map[string]bool{}
	for i := 0; i < 6; i++ {
		out, err := a.llm.Chat(ctx, append([]ChatMsg{{Role: "system", Content: sys}}, hist...))
		if err != nil || strings.TrimSpace(out) == "" {
			return a.fallback(hist[len(hist)-1].Content), false
		}
		out = strings.TrimSpace(out)
		calls := parseToolCalls(out)
		if len(calls) == 0 {
			return out, false
		}
		// Anti-loop: if the model repeats the exact same reply, stop and
		// surface the last tool result instead of spinning forever.
		sig := stripFences(out)
		if seen[sig] {
			if last, ok := strings.CutPrefix(hist[len(hist)-1].Content, "[tool result] "); ok {
				return last, true
			}
			return "I don't have more to add for that request.", true
		}
		seen[sig] = true
		// Record the assistant's own tool call(s) so the model sees its full
		// action -> result trail and converges on a final answer.
		hist = append(hist, ChatMsg{Role: "assistant", Content: out})
		for _, call := range calls {
			if call.Tool == "done" {
				return call.Answer, true
			}
			result := a.execTool(ctx, call)
			hist = append(hist, ChatMsg{Role: "user", Content: "[tool result] " + truncate(result, 3000)})
		}
	}
	return "I reached my step limit. Try again or ask a more specific question.", true
}

// execTool dispatches a parsed tool call and returns the result text.
func (a *Agent) execTool(ctx context.Context, call toolCall) string {
	switch call.Tool {
	case "search":
		cfg := Config()
		res, _ := QueryGoogleCSE(cfg.GoogleAPIKey, cfg.GoogleCX, call.Query)
		if len(res) == 0 {
			return "no results (google search not configured, or nothing found)"
		}
		var b strings.Builder
		for i, r := range res {
			if i >= 5 {
				break
			}
			fmt.Fprintf(&b, "%d. %s\n   %s\n", i+1, r.URL, truncate(r.Summary, 200))
		}
		return b.String()
	case "shell":
		out, err := a.sb.Run(call.Command, "", 0)
		if err != nil {
			return "command error: " + err.Error() + "\n" + out
		}
		return out
	case "read_file":
		out, err := a.sb.ReadFile(call.Path)
		if err != nil {
			return "read error: " + err.Error()
		}
		return out
	case "write_file":
		abs, err := a.sb.WriteFile(call.Path, call.Content)
		if err != nil {
			return "write error: " + err.Error()
		}
		return "wrote " + abs
	case "list_macros":
		names := []string{}
		for _, m := range ListMacros() {
			names = append(names, m.Name)
		}
		return "macros: " + strings.Join(names, ", ")
	case "run_macro":
		res, ok := a.mr.Run(call.Name)
		if !ok {
			return "macro not found"
		}
		return "macro " + call.Name + " ok=" + fmt.Sprint(res.Ok)
	case "list_games":
		return "games: " + strings.Join(a.games.List(), ", ")
	case "new_game":
		id, g, err := a.games.New(call.Game)
		if err != nil {
			return "error: " + err.Error()
		}
		b, _ := json.Marshal(g.State())
		return fmt.Sprintf("game %s started: %s", id, string(b))
	case "move_game":
		g, ok := a.games.Get(call.ID)
		if !ok {
			return "no such game id"
		}
		msg, err := g.Move(call.Action)
		if err != nil {
			return "move error: " + err.Error()
		}
		return msg
	case "autoplay":
		rounds := call.Rounds
		if rounds <= 0 {
			rounds = 1
		}
		if rounds > 5 {
			rounds = 5
		}
		var b strings.Builder
		for i := 0; i < rounds; i++ {
			out, err := a.games.AutoPlay(call.Game)
			if err != nil {
				return "autoplay error: " + err.Error()
			}
			if i > 0 {
				b.WriteString("\n--- round done ---\n")
			}
			b.WriteString(out)
		}
		return b.String()
	case "make_project":
		if call.Language == "" {
			call.Language = "go"
		}
		prj, err := a.projects.Generate(ctx, call.Name, call.Language, call.Description)
		if err != nil {
			return "project error: " + err.Error()
		}
		b, _ := json.Marshal(prj)
		return "project generated: " + string(b)
	case "test_project":
		prj, err := a.projects.Test(ctx, call.Name)
		if err != nil {
			return "test error: " + err.Error()
		}
		return fmt.Sprintf("project %s status=%s cmd=%s\n%s", prj.Name, prj.Status, prj.TestCmd, prj.LastTest)
	default:
		return "unknown tool " + call.Tool
	}
}

// fallback handles common intents when no LLM backend is available.
func (a *Agent) fallback(msg string) string {
	m := strings.ToLower(msg)
	switch {
	case strings.Contains(m, "search") || strings.Contains(m, "google") || strings.Contains(m, "research"):
		return "Research needs the google_api_key / google_cx set in agent_config.json. Then I can search the web."
	case strings.Contains(m, "game") || strings.Contains(m, "play"):
		return "I can host games: " + strings.Join(a.games.List(), ", ") + ". Say a game and I will start it."
	case strings.Contains(m, "macro") || strings.Contains(m, "optimize"):
		names := []string{}
		for _, mm := range ListMacros() {
			names = append(names, mm.Name)
		}
		return "Available macros: " + strings.Join(names, ", ")
	case strings.Contains(m, "project") || strings.Contains(m, "write") || strings.Contains(m, "code"):
		return "Tell me what project to build and I will generate it, then auto-test it in the sandbox."
	case strings.Contains(m, "help") || strings.Contains(m, "what can you"):
		return "I can search the web, run sandboxed commands, write projects, auto-test them, host games, and run optimization macros."
	default:
		return fmt.Sprintf("I'm running with the %s backend, but it could not produce a reply. Check agent_config.json LLM settings. (workspace: %s)", a.llm.Backend(), a.sb.Workspace())
	}
}
