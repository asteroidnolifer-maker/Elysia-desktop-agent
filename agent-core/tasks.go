package main

import (
	"context"
	"time"
	"github.com/google/uuid"
)

type TaskStatus struct{ ID, Model, Prompt, State, Result string }

type TaskQueue struct{ tasks map[string]*TaskStatus; queue chan string; mm *ModelManager; tm *ThermalManager; stopCh chan struct{} }

func NewTaskQueue(mm *ModelManager, tm *ThermalManager) *TaskQueue {
	// limit queue buffer smaller for low-memory devices
	tq := &TaskQueue{tasks: make(map[string]*TaskStatus), queue: make(chan string, 8), mm: mm, tm: tm, stopCh: make(chan struct{})}
	// run single worker to limit concurrent inference
	go func() {
		for i := 0; i < 1; i++ { go tq.worker() }
	}()
	return tq
}

func (tq *TaskQueue) Enqueue(model, prompt string, async bool) string {
	id := uuid.New().String()
	ts := &TaskStatus{ID: id, Model: model, Prompt: prompt, State: "queued"}
	tq.tasks[id] = ts
	tq.queue <- id
	return id
}

func (tq *TaskQueue) Status(id string) *TaskStatus { return tq.tasks[id] }
func (tq *TaskQueue) Len() int { return len(tq.queue) }
func (tq *TaskQueue) Stop() { close(tq.stopCh) }

func (tq *TaskQueue) worker() {
	for {
		select {
		case <-tq.stopCh: return
		case id := <-tq.queue: tq.process(id)
		}
	}
}

func (tq *TaskQueue) process(id string) {
	ts := tq.tasks[id]
	ts.State = "running"
	// backoff loop: wait more aggressively if battery is low or temp high
	for {
		s := tq.tm.Status()
		if s.Ok { break }
		time.Sleep(10 * time.Second)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute); defer cancel()
	out, err := tq.mm.RunModel(ctx, ts.Model, ts.Prompt)
	if err != nil {
		ts.State = "failed"
		ts.Result = err.Error()
		Log("task failed: " + id)
	} else {
		ts.State = "done"
		ts.Result = out
		Log("task done: " + id)
	}
}
