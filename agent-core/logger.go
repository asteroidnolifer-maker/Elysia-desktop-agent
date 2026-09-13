package main

import "sync"

var (
	logsMu sync.Mutex
	logs   []string
)

func Log(msg string) {
	logsMu.Lock()
	defer logsMu.Unlock()
	logs = append(logs, msg)
	if len(logs) > 200 {
		logs = logs[len(logs)-200:]
	}
}

func GetLogs() []string {
	logsMu.Lock()
	defer logsMu.Unlock()
	out := make([]string, len(logs))
	copy(out, logs)
	return out
}
