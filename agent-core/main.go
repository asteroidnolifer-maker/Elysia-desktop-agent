package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"
)

func main() {
	cfg := InitConfig("agent_config.json")
	Log("loaded config: memory_limit_mb=" + fmt.Sprint(cfg.MemoryLimitMB) + " google_search=" + fmt.Sprint(cfg.GoogleAPIKey != "" && cfg.GoogleCX != "") + " llm=" + cfg.LLM.Backend)
	mm := NewModelManager()
	tm := NewThermalManager()
	pm := NewPowerManager()
	si := NewSysInfo()
	tq := NewTaskQueue(mm, tm)
	opt := NewDeviceOptimizer(si, pm, tm)
	mr := NewMacroRunner(opt, mm, tm)
	EvictionHandler = func(name string) { mm.UnloadModel(name) }

	// Desktop agent: LLM client (llama/openai/nim) + sandbox guardrails.
	ag := NewAgent(NewLLMClient(cfg.LLM, mm), NewSandbox(cfg), mr)

	// start socket server for IPC
	if err := StartSocketServer(mm, ""); err != nil {
		log.Println("socket server failed, continuing without it:", err)
	}

	addr := cfg.BindAddr
	if addr == "" {
		addr = httpListenAddr()
	}
	r := NewRouter(tq, mm, tm, pm, opt, mr, si, ag)
	srv := &http.Server{Addr: addr, Handler: r}
	go func() { _ = srv.ListenAndServe() }()

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	<-stop

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_ = srv.Shutdown(ctx)
	tq.Stop()
	tm.Stop()
	pm.Stop()
}
