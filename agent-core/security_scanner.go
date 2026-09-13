package main

import (
	"bufio"
	"encoding/json"
	"io"
	"io/ioutil"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

type Vulnerability struct {
	File    string `json:"file"`
	Line    int    `json:"line"`
	Pattern string `json:"pattern"`
	Fix     string `json:"fix,omitempty"`
	Severity string `json:"severity,omitempty"`
}

type ScanReport struct {
	Path           string          `json:"path"`
	Vulnerabilities []Vulnerability `json:"vulnerabilities"`
}

// Patterns to search and simple fixes
var patterns = []struct{
	Re *regexp.Regexp
	Fix string
	Severity string
} {
	{regexp.MustCompile(`(?i)\beval\s*\(`), "/* remove eval; use safe parser */", "high"},
	{regexp.MustCompile(`(?i)system\s*\(|exec\s*\(`), "/* avoid exec; use safer APIs */", "high"},
	{regexp.MustCompile(`(?i)password\s*[:=]\s*\".*\"`), "/* remove hard-coded password; use secure store */", "high"},
	{regexp.MustCompile(`(?i)\bexec\.\w+\s*\(`), "/* avoid exec.*; prefer dedicated APIs */", "high"},
	{regexp.MustCompile(`(?i)\bbase64_decode\b`), "/* suspicious base64 decoding; inspect for hidden payloads */", "medium"},
	{regexp.MustCompile(`(?i)\bSELECT\s+.*FROM\b`), "/* review SQL usage for injection; use parameterized queries */", "medium"},
	{regexp.MustCompile(`(?i)\bhttp\.Get\(|fetch\(`), "/* external network call; verify URL and sanitize input */", "medium"},
	{regexp.MustCompile(`(?i)\bsystemctl\s|/bin/sh\s|-c\s`), "/* shell invocation detected; avoid shell usage */", "high"},
}

// ScanPath scans files recursively under basePath for dangerous patterns
func ScanPath(basePath string) (ScanReport, error) {
	var report ScanReport
	report.Path = basePath
	err := filepath.Walk(basePath, func(path string, info os.FileInfo, err error) error {
		if err != nil { return nil }
		if info.IsDir() { return nil }
		// skip binaries
		if info.Mode()&0111 != 0 { return nil }
		// check file extension
		ext := strings.ToLower(filepath.Ext(path))
		if ext == ".png" || ext == ".jpg" || ext == ".exe" || ext == ".so" { return nil }

		f, err := os.Open(path)
		if err != nil { return nil }
		defer f.Close()
		reader := bufio.NewReader(f)
		lineNo := 0
		for {
			line, err := reader.ReadString('\n')
			lineNo++
			if err != nil && err != io.EOF { break }
			for _, p := range patterns {
				if p.Re.MatchString(line) {
					report.Vulnerabilities = append(report.Vulnerabilities, Vulnerability{File: path, Line: lineNo, Pattern: p.Re.String(), Fix: p.Fix})
				}
			}
			if err == io.EOF { break }
		}
		// additional: if package.json present, inspect dependencies
		if strings.HasSuffix(strings.ToLower(path), "package.json") {
			// try to parse and check via OSV/Google if configured
			b, _ := ioutil.ReadFile(path)
			var pj map[string]map[string]string
			if _ = json.Unmarshal(b, &pj); pj != nil {
				deps := pj["dependencies"]
				if deps == nil {
					deps = map[string]string{}
				}
				for dep, ver := range deps {
					// best-effort: run search (non-blocking)
					go func(d, v, pth string) {
						cfg, _ := LoadConfig("agent_config.json")
						res, _ := SearchVulnerabilities(cfg, "npm", d, v)
						for _, r := range res {
							report.Vulnerabilities = append(report.Vulnerabilities, Vulnerability{File: pth, Line: 0, Pattern: "dependency:" + d, Fix: "see: " + r.URL})
						}
					}(dep, ver, path)
				}
			}
		}
		return nil
	})
	return report, err
}

// ApplyPatches applies simple textual fixes in-place but writes backups with .bak
func ApplyPatches(report ScanReport) error {
	for _, v := range report.Vulnerabilities {
		b, err := ioutil.ReadFile(v.File)
		if err != nil { continue }
		content := string(b)
		for _, p := range patterns {
			if p.Re.String() == v.Pattern {
				// backup
				_ = ioutil.WriteFile(v.File+".bak", b, 0644)
				// prepare replacement but do not overwrite if severity is high without approval
				// here we apply only medium/low automatically; high requires explicit approval
				if p.Severity == "high" {
					// record suggestion only
					continue
				}
				content = p.Re.ReplaceAllString(content, p.Fix)
				_ = ioutil.WriteFile(v.File, []byte(content), 0644)
			}
		}
	}
	return nil
}

// SaveReport writes JSON report to path
func SaveReport(report ScanReport, out string) error {
	b, _ := json.MarshalIndent(report, "", "  ")
	return ioutil.WriteFile(out, b, 0644)
}
