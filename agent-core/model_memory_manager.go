package main

import (
	"container/list"
	"sync"
)

// ModelCacheEntry holds information about a loaded model
type ModelCacheEntry struct {
	Name      string
	Path      string
	SizeBytes int64
	// pointer to list element for LRU
	elem *list.Element
}

// ModelMemoryManager manages loaded models and evicts using LRU to respect a memory limit
type ModelMemoryManager struct {
	mu        sync.Mutex
	limit     int64
	used      int64
	items     map[string]*ModelCacheEntry
	lru       *list.List // list of model names, front=most recent
}

func NewModelMemoryManager(limitBytes int64) *ModelMemoryManager {
	return &ModelMemoryManager{limit: limitBytes, items: map[string]*ModelCacheEntry{}, lru: list.New()}
}

func (m *ModelMemoryManager) RegisterModel(name, path string, size int64) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if e, ok := m.items[name]; ok {
		// update
		m.used -= e.SizeBytes
		e.Path = path
		e.SizeBytes = size
		m.used += size
		m.touch(e)
		return
	}
	e := &ModelCacheEntry{Name: name, Path: path, SizeBytes: size}
	e.elem = m.lru.PushFront(name)
	m.items[name] = e
	m.used += size
	m.ensureLimit()
}

func (m *ModelMemoryManager) touch(e *ModelCacheEntry) {
	if e.elem != nil {
		m.lru.MoveToFront(e.elem)
	}
}

func (m *ModelMemoryManager) ensureLimit() {
	for m.used > m.limit {
		// evict least recently used (back)
		be := m.lru.Back()
		if be == nil { break }
		name := be.Value.(string)
		if ent, ok := m.items[name]; ok {
			m.used -= ent.SizeBytes
			delete(m.items, name)
			// notify eviction handler if set
			if EvictionHandler != nil {
				go EvictionHandler(name)
			}
		}
		m.lru.Remove(be)
		// Note: actual unloading of model in inference binary may require IPC; here we just evict from bookkeeping
	}
}

func (m *ModelMemoryManager) GetModel(name string) (*ModelCacheEntry, bool) {
	m.mu.Lock()
	defer m.mu.Unlock()
	e, ok := m.items[name]
	if ok { m.touch(e) }
	return e, ok
}

func (m *ModelMemoryManager) SetLimit(bytes int64) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.limit = bytes
	m.ensureLimit()
}

func (m *ModelMemoryManager) Status() (limit, used int64, count int) {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.limit, m.used, len(m.items)
}
