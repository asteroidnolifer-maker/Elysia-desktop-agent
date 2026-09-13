package main

import (
	"bufio"
	"context"
	"os/exec"
	"strings"
	"sync"
	"time"
)

var (
	airllmDetect sync.Once
	airllmOK     bool
	airllmErr    string
)

// python3Path finds a python3 interpreter on the device.
func python3Path() string {
	for _, c := range []string{"python3", "python", "python3.11", "python3.10"} {
		if _, err := exec.LookPath(c); err == nil {
			return c
		}
	}
	return "python3"
}

func detectAirLLM() {
	cmd := exec.Command(python3Path(), "-c", "import airllm")
	if err := cmd.Run(); err != nil {
		airllmErr = err.Error()
		return
	}
	airllmOK = true
}

// AirLLMAvailable reports whether python3 + the airllm module are installed.
func AirLLMAvailable() (bool, string) {
	airllmDetect.Do(detectAirLLM)
	return airllmOK, airllmErr
}

// RunAirLLM runs inference through AirLLM. AirLLM executes large models
// layer-by-layer on CPU so they fit in low RAM, at reduced throughput.
func RunAirLLM(ctx context.Context, modelPath, prompt string, timeout time.Duration) (string, error) {
	ctx2, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	script := ""
	for _, c := range []string{
		"/system/bin/airllm_wrapper.py",
		"/data/vendor/elysia/airllm_wrapper.py",
		"./airllm_wrapper.py",
	} {
		if fileExists(c) {
			script = c
			break
		}
	}

	var cmd *exec.Cmd
	if script != "" {
		cmd = exec.CommandContext(ctx2, python3Path(), script, "--model", modelPath, "--prompt", prompt)
	} else {
		cmd = exec.CommandContext(ctx2, python3Path(), "-m", "airllm", "--model", modelPath, "--prompt", prompt)
	}
	stdout, _ := cmd.StdoutPipe()
	if err := cmd.Start(); err != nil {
		return "", err
	}
	var out strings.Builder
	r := bufio.NewReader(stdout)
	for {
		line, err := r.ReadString('\n')
		if line != "" {
			out.WriteString(line)
		}
		if err != nil {
			break
		}
	}
	_ = cmd.Wait()
	return strings.TrimSpace(out.String()), nil
}
