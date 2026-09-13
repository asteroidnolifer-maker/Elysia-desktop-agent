package main

import (
	"context"
	"time"
)

// MacroStep is a single step in a macro: a shell command or an inference call.
type MacroStep struct {
	Type       string `json:"type"` // shell | infer
	Name       string `json:"name"`
	Command    string `json:"command,omitempty"`
	Model      string `json:"model,omitempty"`
	Prompt     string `json:"prompt,omitempty"`
	TimeoutSec int    `json:"timeout_sec,omitempty"`
	SkipIfHot  bool   `json:"skip_if_hot,omitempty"`
}

// Macro is a named, ordered list of optimization steps.
type Macro struct {
	Name        string      `json:"name"`
	Description string      `json:"description"`
	Steps       []MacroStep `json:"steps"`
}

// StepResult records the outcome of one macro step.
type StepResult struct {
	Type    string `json:"type"`
	Name    string `json:"name"`
	Output  string `json:"output"`
	Error   string `json:"error,omitempty"`
	Skipped bool   `json:"skipped,omitempty"`
}

// MacroResult is the full execution report for a macro run.
type MacroResult struct {
	Name         string       `json:"name"`
	StartedAt    string       `json:"started_at"`
	FinishedAt   string       `json:"finished_at"`
	ThermalLevel string       `json:"thermal_level"`
	StepResults  []StepResult `json:"steps"`
	Ok           bool         `json:"ok"`
}

var macros = []Macro{
	{
		Name:        "quick-optimize",
		Description: "Disable animations, trim caches, drop page caches, and get AI tuning advice.",
		Steps: []MacroStep{
			{Type: "shell", Name: "disable animations", Command: `settings put global window_animation_scale 0 && settings put global transition_animation_scale 0 && settings put global animator_duration_scale 0`, TimeoutSec: 20},
			{Type: "shell", Name: "trim caches", Command: `cmd package trim-caches 256M`, TimeoutSec: 60},
			{Type: "shell", Name: "drop page caches", Command: `echo 3 > /proc/sys/vm/drop_caches`, TimeoutSec: 10},
			{Type: "infer", Name: "AI tuning advice", Model: "tiny", Prompt: `Act as a device optimizer for a low-RAM Android phone. List 3 specific settings or habits that most improve smoothness on a 3GB RAM phone. Keep it to 3 short bullet points.`, TimeoutSec: 90},
		},
	},
	{
		Name:        "battery-saver",
		Description: "Enable battery saver, adaptive battery, and AI battery tips.",
		Steps: []MacroStep{
			{Type: "shell", Name: "enable battery saver", Command: `cmd power set-mode 1`, TimeoutSec: 15},
			{Type: "shell", Name: "enable adaptive battery", Command: `settings put global adaptive_battery_management_enabled 1`, TimeoutSec: 15},
			{Type: "infer", Name: "AI battery tips", Model: "tiny", Prompt: `Act as a battery optimization expert for Android. Give 3 short practical tips to extend battery life. Use plain text, no markdown.`, TimeoutSec: 90},
		},
	},
	{
		Name:        "ram-boost",
		Description: "Free memory: kill background apps, trim caches, drop page caches.",
		Steps: []MacroStep{
			{Type: "shell", Name: "kill background apps", Command: `am kill-all`, TimeoutSec: 20, SkipIfHot: true},
			{Type: "shell", Name: "trim caches", Command: `cmd package trim-caches 512M`, TimeoutSec: 60},
			{Type: "shell", Name: "drop page caches", Command: `echo 3 > /proc/sys/vm/drop_caches`, TimeoutSec: 10},
		},
	},
	{
		Name:        "storage-clean",
		Description: "Trim system and user caches to reclaim storage.",
		Steps: []MacroStep{
			{Type: "shell", Name: "trim system caches", Command: `cmd package trim-caches disk`, TimeoutSec: 90},
			{Type: "infer", Name: "AI storage tips", Model: "tiny", Prompt: `Act as an Android storage advisor. Give 3 short tips to free storage without losing important data. Plain text.`, TimeoutSec: 90},
		},
	},
	{
		Name:        "gaming-mode",
		Description: "Lower animation overhead and report thermal state for a gaming session.",
		Steps: []MacroStep{
			{Type: "shell", Name: "reduce animations", Command: `settings put global window_animation_scale 0.5 && settings put global transition_animation_scale 0.5 && settings put global animator_duration_scale 0.5`, TimeoutSec: 20},
			{Type: "shell", Name: "drop caches", Command: `echo 3 > /proc/sys/vm/drop_caches`, TimeoutSec: 10},
			{Type: "infer", Name: "AI gaming tips", Model: "tiny", Prompt: `Act as a mobile gaming performance expert. Give 3 short tips to reduce jank on a low-RAM phone. Plain text.`, TimeoutSec: 90},
		},
	},
	{
		Name:        "thermal-fix",
		Description: "Switch to a power-saving governor and get thermal guidance.",
		Steps: []MacroStep{
			{Type: "shell", Name: "apply powersave governor", Command: `for g in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do echo powersave > $g 2>/dev/null; done`, TimeoutSec: 10},
			{Type: "infer", Name: "AI thermal advice", Model: "tiny", Prompt: `Act as a hardware thermal expert. Give 3 short practical tips to cool down an Android phone. Plain text.`, TimeoutSec: 90},
		},
	},
}

// ListMacros returns a copy of the macro registry.
func ListMacros() []Macro {
	out := make([]Macro, len(macros))
	copy(out, macros)
	return out
}

// GetMacro finds a macro by name.
func GetMacro(name string) (Macro, bool) {
	for _, m := range macros {
		if m.Name == name {
			return m, true
		}
	}
	return Macro{}, false
}

// MacroRunner executes macros with thermal gating.
type MacroRunner struct {
	opt *DeviceOptimizer
	mm  *ModelManager
	tm  *ThermalManager
}

func NewMacroRunner(opt *DeviceOptimizer, mm *ModelManager, tm *ThermalManager) *MacroRunner {
	return &MacroRunner{opt: opt, mm: mm, tm: tm}
}

// Run executes the named macro. Returns ok=false if the macro does not exist.
func (mr *MacroRunner) Run(name string) (MacroResult, bool) {
	m, ok := GetMacro(name)
	if !ok {
		return MacroResult{}, false
	}
	res := MacroResult{Name: name, StartedAt: time.Now().Format(time.RFC3339)}
	lvl := mr.tm.Level()
	res.ThermalLevel = thermalLevelName(lvl)

	for _, step := range m.Steps {
		sr := StepResult{Type: step.Type, Name: step.Name}
		if step.SkipIfHot && lvl >= ThermalHot {
			sr.Skipped = true
			sr.Output = "skipped (thermal level: " + res.ThermalLevel + ")"
			res.StepResults = append(res.StepResults, sr)
			continue
		}
		timeout := time.Duration(step.TimeoutSec) * time.Second
		if timeout <= 0 {
			timeout = 30 * time.Second
		}
		switch step.Type {
		case "shell":
			out, err := mr.opt.runShell(step.Command, timeout)
			sr.Output = out
			if err != nil {
				sr.Error = err.Error()
			}
		case "infer":
			ctx, cancel := context.WithTimeout(context.Background(), timeout)
			out, err := mr.mm.RunModel(ctx, step.Model, step.Prompt)
			cancel()
			sr.Output = out
			if err != nil {
				sr.Error = err.Error()
			}
		}
		res.StepResults = append(res.StepResults, sr)
		Log("macro " + name + ": step " + step.Name + statusWord(sr.Error == ""))
	}

	res.FinishedAt = time.Now().Format(time.RFC3339)
	res.Ok = true
	return res, true
}
