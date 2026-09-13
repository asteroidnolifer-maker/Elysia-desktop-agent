package main

import (
	"bufio"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
)

// SysInfo reads device resource information from /proc and /sys.
type SysInfo struct {
	mu    sync.RWMutex
	cores int
}

func NewSysInfo() *SysInfo {
	return &SysInfo{cores: cpuCores()}
}

// cpuCores counts online CPUs via /sys/devices/system/cpu.
func cpuCores() int {
	entries, err := filepath.Glob("/sys/devices/system/cpu/cpu[0-9]*")
	if err != nil || len(entries) == 0 {
		return 2
	}
	return len(entries)
}

// InferenceThreads picks a thread count that leaves headroom on low-RAM devices.
func InferenceThreads() int {
	n := cpuCores()
	if n <= 1 {
		return 1
	}
	t := n - 1
	if t > 4 {
		return 4
	}
	return t
}

func (s *SysInfo) Cores() int {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.cores
}

// MemInfo parses /proc/meminfo into (total, free, available) in MB.
func (s *SysInfo) MemInfo() (totalMB, freeMB, availMB int64) {
	f, err := os.Open("/proc/meminfo")
	if err != nil {
		return 0, 0, 0
	}
	defer f.Close()
	vals := map[string]int64{}
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		parts := strings.Fields(sc.Text())
		if len(parts) < 2 {
			continue
		}
		key := strings.TrimSuffix(parts[0], ":")
		v, err := strconv.ParseInt(parts[1], 10, 64)
		if err != nil {
			continue
		}
		vals[key] = v // kB
	}
	toMB := func(kb int64) int64 { return kb / 1024 }
	return toMB(vals["MemTotal"]), toMB(vals["MemFree"]), toMB(vals["MemAvailable"])
}

// LoadAvg reads the 1/5/15 minute load averages.
func (s *SysInfo) LoadAvg() (l1, l5, l15 float64) {
	b := readString("/proc/loadavg")
	parts := strings.Fields(b)
	if len(parts) >= 3 {
		l1, _ = strconv.ParseFloat(parts[0], 64)
		l5, _ = strconv.ParseFloat(parts[1], 64)
		l15, _ = strconv.ParseFloat(parts[2], 64)
	}
	return
}

// Uptime returns system uptime in seconds.
func (s *SysInfo) Uptime() float64 {
	b := readString("/proc/uptime")
	parts := strings.Fields(b)
	if len(parts) >= 1 {
		if v, err := strconv.ParseFloat(parts[0], 64); err == nil {
			return v
		}
	}
	return 0
}

// Snapshot returns a JSON-friendly view of device resources.
func (s *SysInfo) Snapshot() map[string]any {
	total, free, avail := s.MemInfo()
	l1, l5, l15 := s.LoadAvg()
	freeDisk, totalDisk, _ := storageFree("/data")
	const mb = 1024 * 1024
	return map[string]any{
		"cores":            s.Cores(),
		"mem_total_mb":     total,
		"mem_free_mb":      free,
		"mem_available_mb": avail,
		"load1":            l1,
		"load5":            l5,
		"load15":           l15,
		"uptime_sec":       s.Uptime(),
		"storage_free_mb":  freeDisk / mb,
		"storage_total_mb": totalDisk / mb,
		"inference_threads": InferenceThreads(),
	}
}

// readInt reads an integer from a sysfs/proc file, returning 0 on failure.
func readInt(path string) int64 {
	b := readString(path)
	b = strings.TrimSpace(b)
	if i := strings.IndexByte(b, ' '); i >= 0 {
		b = b[:i]
	}
	v, err := strconv.ParseInt(b, 10, 64)
	if err != nil {
		return 0
	}
	return v
}

// readString reads a file, trimming whitespace, returning "" on failure.
func readString(path string) string {
	b, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(b))
}
