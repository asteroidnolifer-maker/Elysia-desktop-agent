package main

import (
	"context"
	"fmt"
	"os/exec"
	"strings"
	"time"
)

// OptimizeAction records one optimization command execution.
type OptimizeAction struct {
	Name    string `json:"name"`
	Command string `json:"command"`
	Applied bool   `json:"applied"`
	Output  string `json:"output"`
	Err     string `json:"error,omitempty"`
}

// OptimizeReport summarizes a device optimization pass.
type OptimizeReport struct {
	Timestamp        string           `json:"timestamp"`
	FreeRAMMB        int64            `json:"free_ram_mb"`
	RecommendedModel string           `json:"recommended_model"`
	Actions          []OptimizeAction `json:"actions"`
}

var safeActions = []struct {
	name    string
	command string
	timeout time.Duration
}{
	{"disable window animations", `settings put global window_animation_scale 0`, 15 * time.Second},
	{"disable transition animations", `settings put global transition_animation_scale 0`, 15 * time.Second},
	{"disable animator duration scale", `settings put global animator_duration_scale 0`, 15 * time.Second},
	{"trim app caches", `cmd package trim-caches 256M`, 60 * time.Second},
	{"drop page caches", `echo 3 > /proc/sys/vm/drop_caches`, 10 * time.Second},
}

// DeviceOptimizer applies safe, reversible device tuning and recommends models
// based on live memory pressure.
type DeviceOptimizer struct {
	si *SysInfo
	pm *PowerManager
	tm *ThermalManager
}

func NewDeviceOptimizer(si *SysInfo, pm *PowerManager, tm *ThermalManager) *DeviceOptimizer {
	return &DeviceOptimizer{si: si, pm: pm, tm: tm}
}

// runShell executes a command via the device shell with a timeout.
func (o *DeviceOptimizer) runShell(cmdStr string, timeout time.Duration) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, shellPath(), "-c", cmdStr)
	out, err := cmd.CombinedOutput()
	return strings.TrimSpace(string(out)), err
}

// RunSafeActions applies the safe action set and records results.
func (o *DeviceOptimizer) RunSafeActions() OptimizeReport {
	_, _, free := o.si.MemInfo()
	rec := RecommendModel(free)
	rep := OptimizeReport{Timestamp: time.Now().Format(time.RFC3339), FreeRAMMB: free, RecommendedModel: rec.Name}
	for _, a := range safeActions {
		out, err := o.runShell(a.command, a.timeout)
		act := OptimizeAction{Name: a.name, Command: a.command, Applied: err == nil, Output: out}
		if err != nil {
			act.Err = err.Error()
		}
		rep.Actions = append(rep.Actions, act)
		Log("optimizer: " + a.name + statusWord(err == nil))
	}
	return rep
}

// ApplyCPUGovernor sets the CPU governor on all cores (best effort).
func (o *DeviceOptimizer) ApplyCPUGovernor(governor string) (string, error) {
	return o.runShell(
		fmt.Sprintf("for g in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do echo %s > $g 2>/dev/null; done", governor),
		10*time.Second,
	)
}

// SetSwappiness adjusts the kernel vm.swappiness value.
func (o *DeviceOptimizer) SetSwappiness(value int) (string, error) {
	return o.runShell(fmt.Sprintf("echo %d > /proc/sys/vm/swappiness", value), 10*time.Second)
}

// Recommendations returns the current model recommendation given free RAM.
func (o *DeviceOptimizer) Recommendations() RecommendedModelInfo {
	_, _, free := o.si.MemInfo()
	avail, errAir := AirLLMAvailable()
	return RecommendedModelInfo{
		FreeRAMMB:       free,
		Recommended:     RecommendModel(free),
		Fits:            SelectModelForRAM(free),
		AirLLMAvailable: avail && errAir == "",
	}
}

func statusWord(ok bool) string {
	if ok {
		return " ok"
	}
	return " failed"
}
