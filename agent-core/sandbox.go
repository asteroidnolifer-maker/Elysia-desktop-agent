package main

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"time"
)

// Sandbox executes commands with hard guardrails: an executable allowlist, a
// working-directory jail, a destructive-pattern filter, a timeout and an
// output cap. It exists so the agent and its tools can download, build and
// test things without being able to damage the host.
type Sandbox struct {
	workspace string
	allow     map[string]bool
	timeout   time.Duration
	useWSL    bool
}

func NewSandbox(cfg AgentConfig) *Sandbox {
	allow := map[string]bool{}
	for _, c := range cfg.SandboxAllowCommands {
		allow[strings.ToLower(c)] = true
	}
	return &Sandbox{
		workspace: cfg.WorkspaceDir,
		allow:     allow,
		timeout:   time.Duration(cfg.SandboxTimeoutSec) * time.Second,
		useWSL:    cfg.SandboxUseWSL,
	}
}

// Workspace returns the jail root.
func (s *Sandbox) Workspace() string { return s.workspace }

// jailPath resolves a relative or absolute path inside the workspace,
// refusing to escape it.
func (s *Sandbox) jailPath(p string) (string, error) {
	if p == "" {
		return s.workspace, nil
	}
	abs := p
	if !filepath.IsAbs(abs) {
		abs = filepath.Join(s.workspace, p)
	}
	abs = filepath.Clean(abs)
	rel, err := filepath.Rel(s.workspace, abs)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return "", fmt.Errorf("path escapes workspace jail: %s", p)
	}
	return abs, nil
}

// BlockedDestructive reports whether a command line is too dangerous to run.
func blockedDestructive(cmdline string) bool {
	low := strings.ToLower(strings.TrimSpace(cmdline))
	patterns := []string{
		"rm -rf /", "rm -fr /", "rmdir /s", "rd /s", "format ",
		"diskpart", "del /s", "del /f /s", "rd /q /s",
		"remove-item -recurse", "remove-item -force", "rm -rf *",
		"shutdown", "restart-computer", "stop-computer",
		"reg delete", "reg add hk", "diskpart",
		":(){", "mkfs.", "dd if=", "> /dev/sd", "fdisk",
		"taskkill /f /im", "kill -9 1", "kill -9 0",
		"powershell -enc", "pwsh -enc", "-encod",
	}
	for _, p := range patterns {
		if strings.Contains(low, p) {
			return true
		}
	}
	return false
}

// blockedMeta reports whether the command uses shell metacharacters that could
// chain, redirect or inject additional commands.
func blockedMeta(cmdline string) bool {
	for _, c := range []string{";", "&&", "||", "|", "`", "$(", "\n"} {
		if strings.Contains(cmdline, c) {
			return true
		}
	}
	return false
}

// Check verifies a command line against the guardrails without running it.
func (s *Sandbox) Check(cmdline string) error {
	if blockedDestructive(cmdline) {
		return fmt.Errorf("blocked: destructive command pattern")
	}
	if blockedMeta(cmdline) {
		return fmt.Errorf("blocked: shell metacharacters not allowed in the sandbox")
	}
	bin := commandBase(cmdline)
	if !s.allow[strings.ToLower(bin)] {
		return fmt.Errorf("blocked: %q is not in sandbox_allow_commands", bin)
	}
	return nil
}

// commandBase extracts the executable name from a command line, handling
// Windows and POSIX forms (quotes, path prefixes).
func commandBase(cmdline string) string {
	t := strings.TrimSpace(cmdline)
	t = strings.TrimPrefix(t, `"`)
	if i := strings.IndexAny(t, " \t"); i > 0 {
		t = t[:i]
	}
	t = strings.Trim(t, `"`)
	t = filepath.Base(t)
	return t
}

// Run executes an allowlisted command inside the workspace jail and returns
// combined output (capped). dir may be a workspace-relative subdirectory.
func (s *Sandbox) Run(cmdline, dir string, timeout time.Duration) (string, error) {
	if err := s.Check(cmdline); err != nil {
		return "", err
	}
	cwd, err := s.jailPath(dir)
	if err != nil {
		return "", err
	}
	if timeout <= 0 {
		timeout = s.timeout
	}
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()

	var cmd *exec.Cmd
	if s.useWSL && runtime.GOOS == "windows" {
		// Run under WSL so Linux toolchains can be exercised; the workspace is
		// reachable through /mnt/c.
		cmd = exec.CommandContext(ctx, "wsl.exe", "-u", "root", "-e", "bash", "-lc", "cd \"$1\" && "+cmdline, "elysia", wslPath(cwd))
	} else if runtime.GOOS == "windows" {
		cmd = exec.CommandContext(ctx, "cmd", "/C", cmdline)
		cmd.Dir = cwd
	} else {
		cmd = exec.CommandContext(ctx, "/bin/sh", "-c", cmdline)
		cmd.Dir = cwd
	}
	out, err := cmd.CombinedOutput()
	return capOutput(string(out)), err
}

// wslPath converts a Windows path like C:\... to /mnt/c/...
func wslPath(p string) string {
	vol := strings.ToLower(p[:1])
	rest := strings.TrimLeft(p[2:], `\`)
	return "/mnt/" + vol + "/" + strings.ReplaceAll(rest, `\`, "/")
}

// capOutput limits the returned output to keep responses small.
func capOutput(s string) string {
	const max = 1 << 15
	if len(s) <= max {
		return s
	}
	return s[len(s)-max:]
}

// WriteFile writes a file inside the workspace jail.
func (s *Sandbox) WriteFile(path, content string) (string, error) {
	abs, err := s.jailPath(path)
	if err != nil {
		return "", err
	}
	if err := ensureDir(filepath.Dir(abs)); err != nil {
		return "", err
	}
	return abs, writeTextFile(abs, content)
}

// ReadFile reads a file from inside the workspace jail.
func (s *Sandbox) ReadFile(path string) (string, error) {
	abs, err := s.jailPath(path)
	if err != nil {
		return "", err
	}
	return readTextFile(abs)
}

// List lists a workspace-relative directory.
func (s *Sandbox) List(path string) ([]string, error) {
	abs, err := s.jailPath(path)
	if err != nil {
		return nil, err
	}
	return listDir(abs)
}

func ensureDir(dir string) error {
	return os.MkdirAll(dir, 0755)
}
