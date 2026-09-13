package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io/ioutil"
	"net/http"
	"strings"
	"sync"
	"time"
)

// ChatMsg is a single chat message in OpenAI-compatible format.
type ChatMsg struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

// LLMClient dispatches chat completions to the configured backend:
// local llama.cpp, any OpenAI-compatible API, or NVIDIA NIM.
type LLMClient struct {
	cfg LLMConfig
	mm  *ModelManager
	cli *http.Client
	mu  sync.Mutex
}

func NewLLMClient(cfg LLMConfig, mm *ModelManager) *LLMClient {
	if mm == nil {
		mm = NewModelManager()
	}
	return &LLMClient{cfg: cfg, mm: mm, cli: &http.Client{Timeout: 180 * time.Second}}
}

// Backend returns the active backend name.
func (l *LLMClient) Backend() string {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.cfg.Backend
}

// Update swaps the LLM backend configuration at runtime.
func (l *LLMClient) Update(cfg LLMConfig) {
	l.mu.Lock()
	l.cfg = cfg
	l.mu.Unlock()
}

// Configured reports whether the active backend has the secrets it needs.
func (l *LLMClient) Configured() bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	switch l.cfg.Backend {
	case "openai":
		return l.cfg.OpenAIBaseURL != ""
	case "nim":
		return l.cfg.NIMKey != ""
	case "llama":
		return l.mm != nil
	default:
		return false
	}
}

// Chat runs a chat completion and returns the assistant text.
func (l *LLMClient) Chat(ctx context.Context, msgs []ChatMsg) (string, error) {
	l.mu.Lock()
	cfg := l.cfg
	l.mu.Unlock()
	switch cfg.Backend {
	case "openai":
		return l.chatOpenAI(ctx, cfg.OpenAIBaseURL, cfg.OpenAIKey, cfg.OpenAIModel, msgs)
	case "nim":
		return l.chatOpenAI(ctx, cfg.NIMBaseURL, cfg.NIMKey, cfg.NIMModel, msgs)
	default:
		return l.chatLlama(ctx, msgs)
	}
}

// chatOpenAI implements the OpenAI /chat/completions wire format. NVIDIA NIM
// uses the same format, so it shares this implementation.
func (l *LLMClient) chatOpenAI(ctx context.Context, baseURL, apiKey, model string, msgs []ChatMsg) (string, error) {
	if baseURL == "" {
		return "", fmt.Errorf("llm backend %s: empty base url", l.cfg.Backend)
	}
	url := strings.TrimRight(baseURL, "/") + "/chat/completions"
	body := map[string]any{
		"model":      model,
		"messages":   msgs,
		"max_tokens": l.cfg.MaxTokens,
	}
	if l.cfg.Temperature > 0 {
		body["temperature"] = l.cfg.Temperature
	}
	if l.cfg.MaxTokens <= 0 {
		body["max_tokens"] = 1024
	}
	b, _ := json.Marshal(body)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(b))
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", "application/json")
	if apiKey != "" {
		req.Header.Set("Authorization", "Bearer "+apiKey)
	}
	resp, err := l.cli.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	raw, _ := ioutil.ReadAll(resp.Body)
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("llm api %s: status %d: %s", l.cfg.Backend, resp.StatusCode, truncate(string(raw), 300))
	}
	var out struct {
		Choices []struct {
			Message struct {
				Content string `json:"content"`
			} `json:"message"`
		} `json:"choices"`
	}
	if err := json.Unmarshal(raw, &out); err != nil {
		return "", fmt.Errorf("llm api parse: %v", err)
	}
	if len(out.Choices) == 0 {
		return "", fmt.Errorf("llm api returned no choices")
	}
	return out.Choices[0].Message.Content, nil
}

// chatLlama runs the bundled llama.cpp inference backend.
func (l *LLMClient) chatLlama(ctx context.Context, msgs []ChatMsg) (string, error) {
	var b strings.Builder
	for _, m := range msgs {
		role := m.Role
		if role == "" {
			role = "user"
		}
		b.WriteString(role + ": " + m.Content + "\n")
	}
	b.WriteString("assistant: ")
	prompt := b.String()
	if len(prompt) > 12000 {
		prompt = prompt[len(prompt)-12000:]
	}
	ctx2, cancel := context.WithTimeout(ctx, 3*time.Minute)
	defer cancel()
	return l.mm.RunModel(ctx2, l.cfg.LlamaModel, prompt)
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n]
}
