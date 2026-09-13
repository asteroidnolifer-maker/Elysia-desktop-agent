package main

import "os"

func envOrDefault(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func fileExists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

func inferenceBinaryPath() string {
	if v := os.Getenv("ELYSIA_INFERENCE_BIN"); v != "" {
		return v
	}
	candidates := []string{
		"/system/bin/inference",
		"/vendor/bin/inference",
		"./inference",
	}
	for _, p := range candidates {
		if fileExists(p) {
			return p
		}
	}
	return "./inference"
}

func socketPath() string {
	return envOrDefault("ELYSIA_SOCKET_PATH", "/data/vendor/elysia/elysia.sock")
}

func httpListenAddr() string {
	return envOrDefault("ELYSIA_HTTP_ADDR", ":8085")
}

func shellPath() string {
	candidates := []string{
		"/system/bin/sh",
		"/bin/sh",
		"sh",
	}
	for _, p := range candidates {
		if p == "sh" || fileExists(p) {
			return p
		}
	}
	return "sh"
}
