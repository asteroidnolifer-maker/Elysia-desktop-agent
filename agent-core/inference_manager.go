package main

import (
	"bufio"
	"context"
	"os/exec"
	"sync"
	"time"
	"strings"
)

type inferenceProc struct {
	cmd    *exec.Cmd
	stdin  *bufio.Writer
	stdout *bufio.Reader
	mu     sync.Mutex
}

type InferenceManager struct {
	mu    sync.Mutex
	procs map[string]*inferenceProc
}

var GlobalInference = NewInferenceManager()

func NewInferenceManager() *InferenceManager {
	return &InferenceManager{procs: map[string]*inferenceProc{}}
}

// LoadModel starts a persistent inference process for the model if not already running.
func (im *InferenceManager) LoadModel(name, path string) error {
	im.mu.Lock()
	defer im.mu.Unlock()
	if _, ok := im.procs[name]; ok { return nil }
	// Try persistent mode; many mobile builds support "-i" or "--interactive"
	cmd := exec.Command(inferenceBinaryPath(), "--model", path, "-i")
	stdout, _ := cmd.StdoutPipe()
	stdin, _ := cmd.StdinPipe()
	if err := cmd.Start(); err != nil { return err }
	p := &inferenceProc{cmd: cmd, stdin: bufio.NewWriter(stdin), stdout: bufio.NewReader(stdout)}
	im.procs[name] = p
	return nil
}

// UnloadModel stops the persistent process if present.
func (im *InferenceManager) UnloadModel(name string) {
	im.mu.Lock()
	p, ok := im.procs[name]
	if ok {
		delete(im.procs, name)
	}
	im.mu.Unlock()
	if ok {
		_ = p.cmd.Process.Kill()
		go p.cmd.Wait()
	}
}

// Run runs inference. If a persistent process exists, send prompt to it; otherwise spawn a short-lived process.
func (im *InferenceManager) Run(ctx context.Context, name, path, prompt string, timeout time.Duration) (string, error) {
	im.mu.Lock()
	p, ok := im.procs[name]
	im.mu.Unlock()
	if ok {
		p.mu.Lock()
		defer p.mu.Unlock()
		// write prompt
		_, _ = p.stdin.WriteString(prompt + "\n")
		_ = p.stdin.Flush()
		// read until timeout
		out := make([]byte, 0)
		done := make(chan struct{})
		go func() {
			for {
				line, err := p.stdout.ReadString('\n')
				if err != nil { break }
				out = append(out, []byte(line)...)
				if strings.TrimSpace(line) == "" { break }
			}
			close(done)
		}()
		select {
		case <-done:
		case <-time.After(timeout):
		}
		return string(out), nil
	}
	// fallback: spawn process
	lw := NewLlamaWrapper(inferenceBinaryPath())
	return lw.RunInference(ctx, path, prompt, timeout)
}
