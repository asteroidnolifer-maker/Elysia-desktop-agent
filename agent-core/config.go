package main

import (
	"bytes"
	"encoding/json"
	"io/ioutil"
	"os"
	"path/filepath"
)

type LLMConfig struct {
	// Backend: "llama" (local), "openai" (OpenAI-compatible), or "nim" (NVIDIA NIM).
	Backend string `json:"backend"`
	// OpenAI-compatible endpoint (e.g. Ollama http://127.0.0.1:11434/v1).
	OpenAIBaseURL string `json:"openai_base_url,omitempty"`
	OpenAIKey     string `json:"openai_api_key,omitempty"`
	OpenAIModel   string `json:"openai_model,omitempty"`
	// NVIDIA NIM (OpenAI-compatible format).
	NIMBaseURL string `json:"nim_base_url,omitempty"`
	NIMKey     string `json:"nim_api_key,omitempty"`
	NIMModel   string `json:"nim_model,omitempty"`
	// Local llama.cpp backend: registered model name (or GGUF path).
	LlamaModel string `json:"llama_model,omitempty"`
	// Sampling temperature for chat completions (0 = unset / default).
	Temperature float64 `json:"temperature,omitempty"`
	// Maximum tokens per chat reply.
	MaxTokens int `json:"max_tokens"`
}

type AgentConfig struct {
	AutoApplyPatches bool   `json:"auto_apply_patches"`
	GoogleAPIKey     string `json:"google_api_key,omitempty"`
	GoogleCX         string `json:"google_cx,omitempty"`
	OSVEndpoint      string `json:"osv_endpoint,omitempty"`
	MemoryLimitMB    int64  `json:"memory_limit_mb"`
	// APIKey, when set, is required as "Authorization: Bearer <key>" or
	// "X-Api-Key" on every mutating endpoint. When empty, mutating endpoints
	// are only reachable from 127.0.0.1.
	APIKey string `json:"api_key,omitempty"`
	// BindAddr overrides the HTTP listen address (default ":8085").
	BindAddr string `json:"bind_addr,omitempty"`
	// LLM holds the chat/code-generation backend settings.
	LLM LLMConfig `json:"llm"`
	// WorkspaceDir is the sandbox root for generated projects, downloads and
	// file tools. Everything the agent writes lives under this directory.
	WorkspaceDir string `json:"workspace_dir,omitempty"`
	// SandboxAllowCommands whitelists executables the sandbox may run.
	SandboxAllowCommands []string `json:"sandbox_allow_commands,omitempty"`
	// SandboxUseWSL runs sandboxed test commands through WSL when available.
	SandboxUseWSL bool `json:"sandbox_use_wsl,omitempty"`
	// SandboxTimeoutSec bounds every sandboxed command.
	SandboxTimeoutSec int `json:"sandbox_timeout_sec"`
	// RateLimitPerMin caps mutating requests per client IP.
	RateLimitPerMin int `json:"rate_limit_per_min"`
}

var DefaultConfig = AgentConfig{
	AutoApplyPatches: false,
	OSVEndpoint:      "https://api.osv.dev/v1",
	MemoryLimitMB:    512,
	LLM: LLMConfig{
		Backend:       "llama",
		OpenAIBaseURL: "http://127.0.0.1:11434/v1",
		OpenAIModel:   "qwen2.5-coder:1.5b",
		NIMBaseURL:    "https://integrate.api.nvidia.com/v1",
		NIMModel:      "meta/llama-3.1-8b-instruct",
		LlamaModel:    "tiny",
		Temperature:   0.3,
		MaxTokens:     1024,
	},
	SandboxAllowCommands: []string{
		"go", "python", "python3", "py", "node", "npm", "npx", "bun",
		"git", "cargo", "rustc", "dotnet", "gcc", "g++", "clang",
		"make", "cmake", "pytest", "java", "javac", "mvn", "gradle",
		"curl", "wget", "tar", "unzip", "zip",
		"mkdir", "cp", "mv", "cat", "echo", "grep", "find",
		"ls", "dir", "cd", "where", "pwd",
	},
	SandboxTimeoutSec: 120,
	RateLimitPerMin:   60,
}

var activeConfig = DefaultConfig
var configPath = "agent_config.json"

// ConfigPath returns the path of the config file the agent loaded.
func ConfigPath() string { return configPath }

// InitConfig loads agent_config.json (creating it with defaults when missing)
// so operators can drop in an API key, LLM backend settings, etc.
func InitConfig(path string) AgentConfig {
	configPath = path
	activeConfig = applyConfigDefaults(DefaultConfig)
	if c, err := LoadConfig(path); err == nil {
		activeConfig = applyConfigDefaults(c)
	}
	if !fileExists(path) {
		_ = SaveConfig(path, activeConfig)
	}
	return activeConfig
}

func applyConfigDefaults(c AgentConfig) AgentConfig {
	if c.MemoryLimitMB <= 0 {
		c.MemoryLimitMB = DefaultConfig.MemoryLimitMB
	}
	if c.OSVEndpoint == "" {
		c.OSVEndpoint = DefaultConfig.OSVEndpoint
	}
	if c.LLM.Backend == "" {
		c.LLM.Backend = DefaultConfig.LLM.Backend
	}
	if c.LLM.OpenAIBaseURL == "" {
		c.LLM.OpenAIBaseURL = DefaultConfig.LLM.OpenAIBaseURL
	}
	if c.LLM.OpenAIModel == "" {
		c.LLM.OpenAIModel = DefaultConfig.LLM.OpenAIModel
	}
	if c.LLM.NIMBaseURL == "" {
		c.LLM.NIMBaseURL = DefaultConfig.LLM.NIMBaseURL
	}
	if c.LLM.NIMModel == "" {
		c.LLM.NIMModel = DefaultConfig.LLM.NIMModel
	}
	if c.LLM.LlamaModel == "" {
		c.LLM.LlamaModel = DefaultConfig.LLM.LlamaModel
	}
	if c.LLM.MaxTokens <= 0 {
		c.LLM.MaxTokens = DefaultConfig.LLM.MaxTokens
	}
	if c.LLM.Temperature == 0 {
		c.LLM.Temperature = DefaultConfig.LLM.Temperature
	}
	if len(c.SandboxAllowCommands) == 0 {
		c.SandboxAllowCommands = DefaultConfig.SandboxAllowCommands
	}
	if c.SandboxTimeoutSec <= 0 {
		c.SandboxTimeoutSec = DefaultConfig.SandboxTimeoutSec
	}
	if c.RateLimitPerMin <= 0 {
		c.RateLimitPerMin = DefaultConfig.RateLimitPerMin
	}
	if c.WorkspaceDir == "" {
		if dir, err := os.Getwd(); err == nil {
			c.WorkspaceDir = filepath.Join(dir, "workspace")
		} else {
			c.WorkspaceDir = "workspace"
		}
	} else if !filepath.IsAbs(c.WorkspaceDir) {
		// resolve relative workspace_dir against the executable's directory,
		// so launching from anywhere uses the same repo-relative location
		if exe, err := os.Executable(); err == nil {
			c.WorkspaceDir = filepath.Join(filepath.Dir(exe), c.WorkspaceDir)
		}
	}
	return c
}

// Config returns the currently active configuration.
func Config() AgentConfig { return activeConfig }

func LoadConfig(path string) (AgentConfig, error) {
	var cfg AgentConfig
	if _, err := os.Stat(path); os.IsNotExist(err) {
		return DefaultConfig, nil
	}
	b, err := ioutil.ReadFile(path)
	if err != nil {
		return cfg, err
	}
	// Tolerate a UTF-8 BOM (Notepad / PowerShell "UTF8" saves).
	b = bytes.TrimPrefix(b, []byte("\xef\xbb\xbf"))
	if err := json.Unmarshal(b, &cfg); err != nil {
		return cfg, err
	}
	return cfg, nil
}

func SaveConfig(path string, cfg AgentConfig) error {
	b, err := json.MarshalIndent(cfg, "", "  ")
	if err != nil {
		return err
	}
	return ioutil.WriteFile(path, b, 0644)
}
