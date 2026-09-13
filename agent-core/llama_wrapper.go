package main

import (
	"bufio"
	"context"
	"io"
	"os/exec"
	"strings"
	"time"
)

type LlamaWrapper struct{ BinaryPath string }

func NewLlamaWrapper(bin string) *LlamaWrapper { return &LlamaWrapper{BinaryPath: bin} }

func (w *LlamaWrapper) RunInference(ctx context.Context, modelPath, prompt string, timeout time.Duration) (string, error) {
	ctx2, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	cmd := exec.CommandContext(ctx2, w.BinaryPath, "--model", modelPath, "--prompt", prompt)
	stdout, _ := cmd.StdoutPipe()
	stderr, _ := cmd.StderrPipe()
	_ = cmd.Start()
	var out strings.Builder
	r := bufio.NewReader(stdout)
	for {
		line, err := r.ReadString('\n')
		if line != "" { out.WriteString(line) }
		if err != nil { break }
	}
	eb, _ := io.ReadAll(stderr)
	if len(eb) > 0 { out.WriteString("\n[stderr] "); out.Write(eb) }
	_ = cmd.Wait()
	return out.String(), nil
}
