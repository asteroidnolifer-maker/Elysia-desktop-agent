package main

import (
	"context"
	"encoding/json"
	"fmt"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

// Project describes a generated project on disk.
type Project struct {
	Name        string   `json:"name"`
	Language    string   `json:"language"`
	Description string   `json:"description"`
	Dir         string   `json:"dir"`
	Files       []string `json:"files"`
	TestCmd     string   `json:"test_cmd"`
	Status      string   `json:"status"`
	LastTest    string   `json:"last_test,omitempty"`
}

// Projects manages generated projects inside the sandbox workspace.
type Projects struct {
	sb  *Sandbox
	llm *LLMClient
}

func NewProjects(sb *Sandbox, llm *LLMClient) *Projects {
	return &Projects{sb: sb, llm: llm}
}

// root returns workspace/projects, creating it if needed.
func (p *Projects) root() (string, error) {
	root := filepath.Join(p.sb.Workspace(), "projects")
	if err := ensureDir(root); err != nil {
		return "", err
	}
	return root, nil
}

func (p *Projects) dir(name string) (string, error) {
	if _, err := p.root(); err != nil {
		return "", err
	}
	return p.sb.jailPath(filepath.Join("projects", name))
}

// Generate asks the LLM for a complete, working project and writes it into the
// workspace. On LLM failure it still scaffolds a minimal project so the flow
// works offline.
func (p *Projects) Generate(ctx context.Context, name, language, description string) (*Project, error) {
	name = sanitizeName(name)
	if name == "" {
		return nil, fmt.Errorf("project name is required")
	}
	dir, err := p.dir(name)
	if err != nil {
		return nil, err
	}
	files := map[string]string{}
	status := "generated-by-llm"

	sys := "You are a senior software engineer. Generate a complete, working project the user asked for. Output ONLY one JSON object with no markdown fences: {\"files\":{\"relative/path\":\"file content\",\"path/README.md\":\"...\"}}. Include every file needed to build and test it, and a README.md explaining how to run and test it. Make code correct and self-contained; prefer standard libraries."
	user := fmt.Sprintf("Project name: %s\nLanguage: %s\nDescription: %s\n", name, language, description)
	out, lerr := p.llm.Chat(ctx, []ChatMsg{{Role: "system", Content: sys}, {Role: "user", Content: user}})
	if lerr == nil {
		var parsed map[string]map[string]string
		trimmed := stripFences(out)
		if jerr := json.Unmarshal([]byte(trimmed), &parsed); jerr == nil {
			for path, content := range parsed["files"] {
				files[path] = content
			}
		}
		if len(files) == 0 {
			status = "llm-output-not-json"
			files = scaffoldProject(name, language, description)
		}
	} else {
		status = "scaffold-llm-unavailable:" + lerr.Error()
		files = scaffoldProject(name, language, description)
	}

	var written []string
	for path, content := range files {
		abs, err := p.sb.WriteFile(filepath.Join("projects", name, path), content)
		if err != nil {
			return nil, err
		}
		written = append(written, relTo(dir, abs))
	}
	sort.Strings(written)

	prj := &Project{
		Name:        name,
		Language:    language,
		Description: description,
		Dir:         dir,
		Files:       written,
		TestCmd:     testCommand(language),
		Status:      status,
	}
	return prj, nil
}

// List returns the projects currently in the workspace.
func (p *Projects) List() ([]*Project, error) {
	root, err := p.root()
	if err != nil {
		return nil, err
	}
	entries, err := listDir(root)
	if err != nil {
		return nil, err
	}
	var out []*Project
	for _, e := range entries {
		if !strings.HasSuffix(e, "/") {
			continue
		}
		n := strings.TrimSuffix(e, "/")
		dir := filepath.Join(root, n)
		files, _ := listDir(dir)
		out = append(out, &Project{
			Name: n, Dir: dir, Files: files, Status: "present", TestCmd: testCandidatesForDir(dir)[0],
		})
	}
	return out, nil
}

// Test runs the project's test command inside the sandbox and records output,
// falling back to alternative commands (e.g. unittest when pytest is missing).
func (p *Projects) Test(ctx context.Context, name string) (*Project, error) {
	dir, err := p.dir(name)
	if err != nil {
		return nil, err
	}
	if _, err := listDir(dir); err != nil {
		return nil, fmt.Errorf("project %q not found", name)
	}
	candidates := testCandidatesForDir(dir)
	timeout := time.Duration(Config().SandboxTimeoutSec) * time.Second
	if timeout <= 0 {
		timeout = 120 * time.Second
	}
	last := ""
	for i, cmd := range candidates {
		out, runErr := p.sb.Run(cmd, filepath.Join("projects", name), timeout)
		last = out
		if runErr == nil {
			return &Project{Name: name, Dir: dir, TestCmd: cmd, Status: "test-passed", LastTest: capOutput(out)}, nil
		}
		if i == len(candidates)-1 {
			Log(fmt.Sprintf("project %s: all test commands failed (%d tried): %s", name, len(candidates), runErr))
		}
	}
	return &Project{Name: name, Dir: dir, TestCmd: candidates[len(candidates)-1], Status: "test-failed", LastTest: capOutput(last)}, nil
}

func relTo(base, target string) string {
	r, err := filepath.Rel(base, target)
	if err != nil {
		return target
	}
	return r
}

func sanitizeName(name string) string {
	name = strings.TrimSpace(name)
	var b strings.Builder
	for _, r := range name {
		switch {
		case r >= 'a' && r <= 'z', r >= 'A' && r <= 'Z', r >= '0' && r <= '9', r == '-', r == '_':
			b.WriteRune(r)
		}
	}
	return b.String()
}

// stripFences removes ```json ... ``` fences if the model wrapped its output.
func stripFences(s string) string {
	s = strings.TrimSpace(s)
	s = strings.TrimPrefix(s, "```json")
	s = strings.TrimPrefix(s, "```")
	s = strings.TrimSuffix(s, "```")
	return strings.TrimSpace(s)
}

func testCommand(language string) string {
	return testCandidatesForLanguage(language)[0]
}

// testCandidatesForLanguage returns ordered test commands for a language.
func testCandidatesForLanguage(language string) []string {
	switch strings.ToLower(language) {
	case "go":
		return []string{"go test ./..."}
	case "python", "py":
		return []string{"python -m pytest -q", "python -m unittest discover -q"}
	case "node", "javascript", "typescript", "js", "ts":
		return []string{"npm test", "node test.js"}
	case "rust":
		return []string{"cargo test"}
	case "c", "c++", "cpp":
		return []string{"make test"}
	default:
		return []string{"go test ./..."}
	}
}

func testCandidatesForDir(dir string) []string {
	entries, err := listDir(dir)
	if err != nil {
		return testCandidatesForLanguage("go")
	}
	for _, e := range entries {
		switch {
		case e == "go.mod" || e == "go.sum":
			return testCandidatesForLanguage("go")
		case strings.HasSuffix(e, ".py") || strings.Contains(e, "pytest") || e == "requirements.txt" || e == "pyproject.toml":
			return testCandidatesForLanguage("python")
		case e == "package.json":
			return testCandidatesForLanguage("node")
		case e == "Cargo.toml":
			return testCandidatesForLanguage("rust")
		case e == "Makefile" || e == "makefile":
			return []string{"make test"}
		}
	}
	return testCandidatesForLanguage("go")
}

// scaffoldProject provides a minimal but complete, tested project when the
// LLM backend is unavailable. Each scaffold includes a test that passes.
func scaffoldProject(name, language, description string) map[string]string {
	if description == "" {
		description = "a small starter project"
	}
	switch strings.ToLower(language) {
	case "python", "py":
		return map[string]string{
			"main.py":         "# " + name + "\n# " + description + "\n\ndef hello():\n    return \"hello from " + name + "\"\n\nif __name__ == \"__main__\":\n    print(hello())\n",
			"test_main.py":    "import unittest\nimport main\n\n\nclass TestMain(unittest.TestCase):\n    def test_hello(self):\n        self.assertEqual(main.hello(), \"hello from " + name + "\")\n\n\nif __name__ == \"__main__\":\n    unittest.main()\n",
			"README.md":       "# " + name + "\n\n" + description + "\n\nRun tests: `python -m pytest -q` or `python -m unittest`\n",
			".elysia-project": "1",
		}
	case "node", "javascript", "typescript", "js", "ts":
		return map[string]string{
			"index.js":        "// " + name + "\n// " + description + "\nfunction hello() { return 'hello from " + name + "'; }\nmodule.exports = { hello };\nif (require.main === module) console.log(hello());\n",
			"test.js":         "const assert = require('assert');\nconst { hello } = require('./index');\nassert.strictEqual(hello(), 'hello from " + name + "');\nconsole.log('tests passed');\n",
			"package.json":    "{\"name\":\"" + name + "\",\"version\":\"1.0.0\",\"main\":\"index.js\",\"scripts\":{\"test\":\"node test.js\"}}\n",
			"README.md":       "# " + name + "\n\n" + description + "\n\nRun tests: `npm test`\n",
			".elysia-project": "1",
		}
	case "rust":
		return map[string]string{
			"src/main.rs":     "fn main() {\n    println!(\"hello from " + name + "\");\n}\n",
			"src/lib.rs":      "pub fn hello() -> &'static str {\n    \"hello from " + name + "\"\n}\n",
			"tests/smoke.rs":  "use " + name + "::hello;\n\n#[test]\nfn smoke() {\n    assert_eq!(hello(), \"hello from " + name + "\");\n}\n",
			"Cargo.toml":      "[package]\nname = \"" + name + "\"\nversion = \"0.1.0\"\nedition = \"2021\"\n",
			"README.md":       "# " + name + "\n\n" + description + "\n\nRun tests: `cargo test`\n",
			".elysia-project": "1",
		}
	default: // go
		goName := strings.ReplaceAll(name, "-", "")
		if goName == "" {
			goName = "app"
		}
		return map[string]string{
			"main.go":         "// Package main: " + name + "\n" + "// " + description + "\npackage main\n\nimport \"fmt\"\n\nfunc hello() string { return \"hello from " + name + "\" }\n\nfunc main() { fmt.Println(hello()) }\n",
			"main_test.go":    "package main\n\nimport \"testing\"\n\nfunc TestHello(t *testing.T) {\n\tif got := hello(); got != \"hello from " + name + "\" {\n\t\tt.Fatalf(\"hello() = %q\", got)\n\t}\n}\n",
			"go.mod":          "module " + goName + "\n\ngo 1.21\n",
			"README.md":       "# " + name + "\n\n" + description + "\n\nRun tests: `go test ./...`\n",
			".elysia-project": "1",
		}
	}
}
