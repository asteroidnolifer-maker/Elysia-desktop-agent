package main

import (
	"context"
	"os"
	"os/exec"
	"sync"
	"time"
)

type ModelInfo struct{ Name, Path, UnloadCmd string }

type ModelManager struct {
	mu     sync.RWMutex
	models map[string]ModelInfo
	mem    *ModelMemoryManager
}

func NewModelManager() *ModelManager {
	limit := Config().MemoryLimitMB
	if limit <= 0 {
		limit = 512
	}
	mem := NewModelMemoryManager(limit * 1024 * 1024)
	return &ModelManager{models: map[string]ModelInfo{}, mem: mem}
}

func (m *ModelManager) ListModels() []ModelInfo {
	m.mu.RLock()
	defer m.mu.RUnlock()
	out := make([]ModelInfo, 0, len(m.models))
	for _, mi := range m.models {
		out = append(out, mi)
	}
	return out
}

func (m *ModelManager) Register(name, path string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.models[name] = ModelInfo{Name: name, Path: path}
	if fi, err := os.Stat(path); err == nil {
		m.mem.RegisterModel(name, path, fi.Size())
	}
}

func (m *ModelManager) UnloadModel(name string) {
	m.mu.Lock()
	mi, ok := m.models[name]
	m.mu.Unlock()
	if !ok {
		return
	}
	if mi.UnloadCmd != "" {
		// best-effort exec of unload command
		_ = exec.Command(shellPath(), "-c", mi.UnloadCmd).Run()
		Log("unloaded model: " + name)
	}
}

func (m *ModelManager) RunModel(ctx context.Context, modelName, prompt string) (string, error) {
	m.mu.RLock()
	mi, ok := m.models[modelName]
	m.mu.RUnlock()
	if !ok {
		return "", nil
	}
	if ent, ok := m.mem.GetModel(modelName); ok {
		_ = ent
	}
	// prefer persistent inference manager
	out, err := GlobalInference.Run(ctx, modelName, mi.Path, prompt, 2*time.Minute)
	if err == nil && out != "" {
		return out, nil
	}
	lw := NewLlamaWrapper(inferenceBinaryPath())
	return lw.RunInference(ctx, mi.Path, prompt, 2*time.Minute)
}
