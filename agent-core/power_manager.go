package main

import (
	"fmt"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

// BatteryStatus describes the current battery state as read from sysfs.
type BatteryStatus struct {
	Present  bool    `json:"present"`
	Capacity int     `json:"capacity"`
	TempC    float64 `json:"temp_c"`
	Voltage  int     `json:"voltage"`
	Current  int     `json:"current"`
	Status   string  `json:"status"`
}

// PowerManager polls the battery sensors so the agent can make power-aware
// decisions (charging-only maintenance, low-battery throttling).
type PowerManager struct {
	mu     sync.RWMutex
	bat    BatteryStatus
	ticker *time.Ticker
	quit   chan struct{}
}

func NewPowerManager() *PowerManager {
	pm := &PowerManager{ticker: time.NewTicker(15 * time.Second), quit: make(chan struct{})}
	pm.read()
	go pm.loop()
	return pm
}

func (p *PowerManager) loop() {
	for {
		select {
		case <-p.quit:
			return
		case <-p.ticker.C:
			p.read()
		}
	}
}

func (p *PowerManager) Stop() {
	select {
	case <-p.quit:
	default:
		close(p.quit)
	}
}

func (p *PowerManager) read() {
	base := envOrDefault("ELYSIA_POWER_PATH", "/sys/class/power_supply")
	dirs, _ := filepath.Glob(filepath.Join(base, "battery*"))
	b := BatteryStatus{Present: len(dirs) > 0, Status: "unknown"}
	if len(dirs) > 0 {
		dir := dirs[0]
		b.Capacity = int(readInt(filepath.Join(dir, "capacity")))
		if s := readString(filepath.Join(dir, "status")); s != "" {
			b.Status = s
		}
		b.Voltage = int(readInt(filepath.Join(dir, "voltage_now")))
		b.Current = int(readInt(filepath.Join(dir, "current_now")))
		if v := readInt(filepath.Join(dir, "temp")); v != 0 {
			switch {
			case v >= 1000: // millidegrees
				b.TempC = float64(v) / 1000
			case v >= 100: // tenths of a degree
				b.TempC = float64(v) / 10
			default:
				b.TempC = float64(v)
			}
		}
	}
	// Sysfs battery files are often unreadable by the shell user (SELinux);
	// fall back to dumpsys battery which is permitted.
	if b.Capacity == 0 {
		p.readFromDumpsys(&b)
	}
	p.mu.Lock()
	p.bat = b
	p.mu.Unlock()
}

// readFromDumpsys parses `dumpsys battery` output when sysfs reads fail.
func (p *PowerManager) readFromDumpsys(b *BatteryStatus) {
	out, err := exec.Command(shellPath(), "-c", "dumpsys battery").Output()
	if err != nil {
		return
	}
	for _, line := range strings.Split(string(out), "\n") {
		fields := strings.Fields(line)
		if len(fields) < 2 {
			continue
		}
		key := strings.TrimSuffix(fields[0], ":")
		val := strings.Join(fields[1:], " ")
		switch key {
		case "status":
			switch val {
			case "1":
				b.Status = "unknown"
			case "2":
				b.Status = "Charging"
			case "3":
				b.Status = "Discharging"
			case "4":
				b.Status = "Not charging"
			case "5":
				b.Status = "Full"
			}
			b.Present = true
		case "level":
			fmt.Sscanf(val, "%d", &b.Capacity)
		case "temperature":
			var t int
			if _, err := fmt.Sscanf(val, "%d", &t); err == nil {
				b.TempC = float64(t) / 10
			}
		case "voltage":
			fmt.Sscanf(val, "%d", &b.Voltage)
		}
	}
}

// Status returns the latest battery snapshot.
func (p *PowerManager) Status() BatteryStatus {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.bat
}

// LowBattery reports whether the device is running low on charge.
func (p *PowerManager) LowBattery() bool {
	s := p.Status()
	return s.Present && s.Capacity > 0 && s.Capacity <= 20
}

// Charging reports whether the device is plugged in.
func (p *PowerManager) Charging() bool {
	s := p.Status()
	return s.Present && strings.Contains(s.Status, "harg")
}
