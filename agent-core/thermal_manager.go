package main

import (
	"path/filepath"
	"strings"
	"sync"
	"time"
)

// ThermalLevel classifies device thermal state for throttling decisions.
type ThermalLevel int

const (
	ThermalOK ThermalLevel = iota
	ThermalWarm
	ThermalHot
	ThermalCritical
)

// ThermalStatus is the JSON view returned to callers.
type ThermalStatus struct {
	TempC        float64 `json:"temp_c"`
	Ok           bool    `json:"ok"`
	Level        string  `json:"level"`
	BatteryTempC float64 `json:"battery_temp_c"`
	Zones        int     `json:"zones"`
}

func thermalLevelName(l ThermalLevel) string {
	switch l {
	case ThermalWarm:
		return "warm"
	case ThermalHot:
		return "hot"
	case ThermalCritical:
		return "critical"
	default:
		return "ok"
	}
}

// ThermalManager periodically samples /sys/class/thermal sensors (and the
// battery temperature) and exposes a throttle level for the task scheduler.
type ThermalManager struct {
	mu          sync.RWMutex
	tempC       float64
	batteryTemp float64
	zones       int
	threshold   float64
	ticker      *time.Ticker
	quit        chan struct{}
}

func NewThermalManager() *ThermalManager {
	tm := &ThermalManager{threshold: 75.0, ticker: time.NewTicker(5 * time.Second), quit: make(chan struct{})}
	tm.sample()
	go tm.loop()
	return tm
}

func (t *ThermalManager) loop() {
	for {
		select {
		case <-t.quit:
			return
		case <-t.ticker.C:
			t.sample()
		}
	}
}

func (t *ThermalManager) sample() {
	c, n := t.readCPU()
	b := t.readBattery()
	t.mu.Lock()
	t.tempC = c
	t.zones = n
	t.batteryTemp = b
	t.mu.Unlock()
}

func (t *ThermalManager) Stop() {
	select {
	case <-t.quit:
	default:
		close(t.quit)
	}
}

// Status returns the current thermal snapshot.
func (t *ThermalManager) Status() ThermalStatus {
	t.mu.RLock()
	defer t.mu.RUnlock()
	return ThermalStatus{
		TempC:        t.tempC,
		Ok:           t.tempC <= t.threshold,
		Level:        thermalLevelName(t.levelLocked()),
		BatteryTempC: t.batteryTemp,
		Zones:        t.zones,
	}
}

// Level returns the current throttle level.
func (t *ThermalManager) Level() ThermalLevel {
	t.mu.RLock()
	defer t.mu.RUnlock()
	return t.levelLocked()
}

func (t *ThermalManager) levelLocked() ThermalLevel {
	c := t.tempC
	switch {
	case c >= t.threshold+10:
		return ThermalCritical
	case c >= t.threshold:
		return ThermalHot
	case c >= t.threshold-15:
		return ThermalWarm
	default:
		return ThermalOK
	}
}

// readCPU scans thermal zones, preferring CPU-related zones, and returns the
// maximum temperature plus the number of readable zones.
func (t *ThermalManager) readCPU() (float64, int) {
	base := envOrDefault("ELYSIA_THERMAL_PATH", "/sys/class/thermal")
	zones, _ := filepath.Glob(filepath.Join(base, "thermal_zone*"))
	var cpuMax, otherMax float64
	cpuFound, anyFound := false, false
	for _, d := range zones {
		typ := strings.ToLower(readString(filepath.Join(d, "type")))
		v := readInt(filepath.Join(d, "temp"))
		if v == 0 {
			continue
		}
		c := normalizeTemp(v)
		anyFound = true
		if strings.Contains(typ, "cpu") {
			if !cpuFound || c > cpuMax {
				cpuMax = c
				cpuFound = true
			}
		} else if c > otherMax {
			otherMax = c
		}
	}
	if cpuFound {
		return cpuMax, zonesLen(zones)
	}
	if anyFound {
		return otherMax, zonesLen(zones)
	}
	return 0, 0
}

func normalizeTemp(v int64) float64 {
	switch {
	case v >= 1000: // millidegrees
		return float64(v) / 1000
	case v >= 100: // tenths of a degree
		return float64(v) / 10
	default:
		return float64(v)
	}
}

func zonesLen(zones []string) int {
	n := 0
	for _, d := range zones {
		if readInt(filepath.Join(d, "temp")) != 0 {
			n++
		}
	}
	return n
}

// readBattery returns the battery temperature in Celsius, 0 if unavailable.
func (t *ThermalManager) readBattery() float64 {
	v := readInt(filepath.Join(envOrDefault("ELYSIA_THERMAL_PATH", "/sys/class/thermal"), "..", "power_supply", "battery", "temp"))
	if v == 0 {
		return 0
	}
	return normalizeTemp(v)
}
