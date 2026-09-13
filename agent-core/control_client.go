package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"net"
	"os"
)

func SocketCmd(cmd map[string]any) (map[string]any, error) {
	socket := socketPath()
	conn, err := net.Dial("unix", socket)
	if err != nil {
		return nil, err
	}
	defer conn.Close()
	b, _ := json.Marshal(cmd)
	conn.Write(append(b, '\n'))
	r := bufio.NewReader(conn)
	line, err := r.ReadString('\n')
	if err != nil {
		return nil, err
	}
	var resp map[string]any
	_ = json.Unmarshal([]byte(line), &resp)
	return resp, nil
}

func mainControl() {
	if len(os.Args) < 2 {
		fmt.Println("usage: control_client load|unload|run args...")
		return
	}
	a := os.Args[1]
	switch a {
	case "load":
		if len(os.Args) < 4 { fmt.Println("load <name> <path>"); return }
		resp, err := SocketCmd(map[string]any{"action":"load","name":os.Args[2],"path":os.Args[3]})
		fmt.Println(resp, err)
	case "unload":
		if len(os.Args) < 3 { fmt.Println("unload <name>"); return }
		resp, err := SocketCmd(map[string]any{"action":"unload","name":os.Args[2]})
		fmt.Println(resp, err)
	case "run":
		if len(os.Args) < 4 { fmt.Println("run <name> <prompt>"); return }
		resp, err := SocketCmd(map[string]any{"action":"run","name":os.Args[2],"prompt":os.Args[3]})
		fmt.Println(resp, err)
	default:
		fmt.Println("unknown command")
	}
}
