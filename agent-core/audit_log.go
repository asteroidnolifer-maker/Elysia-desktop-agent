package main

import (
	"encoding/json"
	"io/ioutil"
	"sync"
	"time"
)

type AuditEntry struct {
	Time    time.Time       `json:"time"`
	Action  string          `json:"action"`
	Details json.RawMessage `json:"details"`
}

type AuditLog struct {
	mu      sync.Mutex
	entries []AuditEntry
	path    string
}

func NewAuditLog(path string) *AuditLog {
	a := &AuditLog{path: path}
	_ = a.load()
	return a
}

// defaultAudit is the shared audit trail used by the auth guard.
var defaultAudit = NewAuditLog("agent_audit.json")

// Audit returns the shared audit log.
func Audit() *AuditLog { return defaultAudit }

func (a *AuditLog) load() error {
	a.mu.Lock()
	defer a.mu.Unlock()
	b, err := ioutil.ReadFile(a.path)
	if err != nil {
		return err
	}
	_ = json.Unmarshal(b, &a.entries)
	return nil
}

func (a *AuditLog) Save() error {
	a.mu.Lock()
	defer a.mu.Unlock()
	b, _ := json.MarshalIndent(a.entries, "", "  ")
	return ioutil.WriteFile(a.path, b, 0644)
}

func (a *AuditLog) Add(action string, details any) {
	a.mu.Lock()
	d, _ := json.Marshal(details)
	a.entries = append(a.entries, AuditEntry{Time: time.Now(), Action: action, Details: d})
	b, _ := json.MarshalIndent(a.entries, "", "  ")
	a.mu.Unlock()
	_ = ioutil.WriteFile(a.path, b, 0644)
}
