package main

import (
	"bufio"
	"context"
	"encoding/json"
	"net"
	"os"
	"strings"
	"time"
)

// StartSocketServer starts a unix domain socket server to receive simple JSON commands
// Commands: {"action":"load", "name":"m","path":"/..."}
//           {"action":"unload","name":"m"}
//           {"action":"run","name":"m","prompt":"..."}
func StartSocketServer(mm *ModelManager, sockPath string) error {
	if sockPath == "" {
		sockPath = socketPath()
	}
	// remove existing
	_ = os.Remove(sockPath)
	l, err := net.Listen("unix", sockPath)
	if err != nil {
		// fallback to /tmp
		sockPath = "/tmp/elysia.sock"
		_ = os.Remove(sockPath)
		l, err = net.Listen("unix", sockPath)
		if err != nil {
			return err
		}
	}
	go func() {
		for {
			conn, err := l.Accept()
			if err != nil { continue }
			go handleConn(mm, conn)
		}
	}()
	return nil
}

func handleConn(mm *ModelManager, conn net.Conn) {
	defer conn.Close()
	r := bufio.NewReader(conn)
	line, err := r.ReadString('\n')
	if err != nil {
		return
	}
	line = strings.TrimSpace(line)
	var cmd map[string]any
	_ = json.Unmarshal([]byte(line), &cmd)
	action, _ := cmd["action"].(string)
	switch action {
	case "load":
		name, _ := cmd["name"].(string)
		path, _ := cmd["path"].(string)
		mm.Register(name, path)
		// also start persistent inference process
		_ = GlobalInference.LoadModel(name, path)
		resp := map[string]any{"ok": true}
		b, _ := json.Marshal(resp)
		conn.Write(append(b, '\n'))
	case "unload":
		name, _ := cmd["name"].(string)
		GlobalInference.UnloadModel(name)
		mm.UnloadModel(name)
		resp := map[string]any{"ok": true}
		b, _ := json.Marshal(resp)
		conn.Write(append(b, '\n'))
	case "run":
		name, _ := cmd["name"].(string)
		prompt, _ := cmd["prompt"].(string)
		ctx := context.Background()
		out, _ := GlobalInference.Run(ctx, name, "", prompt, 2*time.Minute)
		resp := map[string]any{"output": out}
		b, _ := json.Marshal(resp)
		conn.Write(append(b, '\n'))
	default:
		resp := map[string]any{"error": "unknown action"}
		b, _ := json.Marshal(resp)
		conn.Write(append(b, '\n'))
	}
}
