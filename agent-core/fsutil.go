package main

import (
	"io/ioutil"
	"path/filepath"
	"strings"
)

func writeTextFile(path, content string) error {
	return ioutil.WriteFile(path, []byte(content), 0644)
}

func readTextFile(path string) (string, error) {
	b, err := ioutil.ReadFile(path)
	if err != nil {
		return "", err
	}
	return string(b), nil
}

func listDir(dir string) ([]string, error) {
	entries, err := ioutil.ReadDir(dir)
	if err != nil {
		return nil, err
	}
	out := make([]string, 0, len(entries))
	for _, e := range entries {
		name := e.Name()
		if e.IsDir() {
			name += "/"
		}
		out = append(out, name)
	}
	return out, nil
}

// safeJoin keeps a path under root, returning an error on escapes.
func safeJoin(root, sub string) (string, error) {
	abs := sub
	if !filepath.IsAbs(abs) {
		abs = filepath.Join(root, sub)
	}
	abs = filepath.Clean(abs)
	rel, err := filepath.Rel(root, abs)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return "", err
	}
	return abs, nil
}
