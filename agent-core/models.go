package main

import "sort"

// ModelBackend selects the inference engine for a model.
type ModelBackend string

const (
	BackendLlama  ModelBackend = "llama"
	BackendAirLLM ModelBackend = "airllm"
)

// ModelSpec describes a lightweight model appropriate for low-RAM devices.
type ModelSpec struct {
	Name         string       `json:"name"`
	DisplayName  string       `json:"display_name"`
	Backend      ModelBackend `json:"backend"`
	Path         string       `json:"path"`
	SizeMB       int64        `json:"size_mb"`
	MinFreeRAMMB int64        `json:"min_free_ram_mb"`
	Params       string       `json:"params"`
	Quant        string       `json:"quant"`
	SourceRepo   string       `json:"source_repo"`
	Note         string       `json:"note"`
}

// modelSpecs lists models tuned for a ~3GB RAM device (with ~1.5GB free).
var modelSpecs = []ModelSpec{
	{
		Name: "nano", DisplayName: "SmolLM2-135M", Backend: BackendLlama,
		SizeMB: 80, MinFreeRAMMB: 300, Params: "0.1B", Quant: "Q4",
		SourceRepo: "HuggingFaceTB/SmolLM2-135M-Instruct",
		Note:       "Ultra-light; fastest responses, good for macros and short Q&A.",
	},
	{
		Name: "tiny", DisplayName: "Qwen2.5-0.5B", Backend: BackendLlama,
		SizeMB: 400, MinFreeRAMMB: 700, Params: "0.5B", Quant: "Q4_K_M",
		SourceRepo: "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
		Note:       "Recommended default on 3GB devices.",
	},
	{
		Name: "mini", DisplayName: "Qwen2.5-1.5B", Backend: BackendLlama,
		SizeMB: 1000, MinFreeRAMMB: 1500, Params: "1.5B", Quant: "Q4_K_M",
		SourceRepo: "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
		Note:       "Use when more than 1.5GB RAM is free.",
	},
	{
		Name: "medium", DisplayName: "Gemma-2-2B", Backend: BackendLlama,
		SizeMB: 1600, MinFreeRAMMB: 2400, Params: "2B", Quant: "Q4",
		SourceRepo: "google/gemma-2-2b-it",
		Note:       "Only safe with 2.4GB+ free RAM.",
	},
	{
		Name: "airllm-mini", DisplayName: "Phi-3-mini via AirLLM", Backend: BackendAirLLM,
		SizeMB: 600, MinFreeRAMMB: 1200, Params: "3.8B", Quant: "Q4",
		SourceRepo: "microsoft/Phi-3-mini-4k-instruct",
		Note:       "Layer-by-layer CPU inference; slower but lets a 3.8B model fit in low RAM.",
	},
}

// GetModelSpec returns the spec for a model name.
func GetModelSpec(name string) (ModelSpec, bool) {
	for _, m := range modelSpecs {
		if m.Name == name {
			return m, true
		}
	}
	return ModelSpec{}, false
}

// AllModelSpecs returns a copy of the model registry.
func AllModelSpecs() []ModelSpec {
	out := make([]ModelSpec, len(modelSpecs))
	copy(out, modelSpecs)
	return out
}

// SelectModelForRAM returns models that fit in the given free RAM (MB),
// smallest-first so the lightest usable model is listed first.
func SelectModelForRAM(freeMB int64) []ModelSpec {
	cands := []ModelSpec{}
	for _, m := range modelSpecs {
		if freeMB >= m.MinFreeRAMMB {
			cands = append(cands, m)
		}
	}
	sort.Slice(cands, func(i, j int) bool { return cands[i].SizeMB < cands[j].SizeMB })
	return cands
}

// RecommendModel picks the best-fitting model: the largest llama-backend model
// that fits with headroom, falling back to AirLLM, then to the tiny default.
func RecommendModel(freeMB int64) ModelSpec {
	best, found := ModelSpec{}, false
	for _, m := range modelSpecs {
		if m.Backend != BackendLlama || freeMB < m.MinFreeRAMMB {
			continue
		}
		if !found || m.SizeMB > best.SizeMB {
			best, found = m, true
		}
	}
	if found {
		return best
	}
	for _, m := range modelSpecs {
		if freeMB >= m.MinFreeRAMMB {
			return m
		}
	}
	return modelSpecs[1] // tiny
}

// RecommendedModelInfo is returned by the /models/recommend endpoint.
type RecommendedModelInfo struct {
	FreeRAMMB       int64       `json:"free_ram_mb"`
	Recommended     ModelSpec   `json:"recommended"`
	Fits            []ModelSpec `json:"fits"`
	AirLLMAvailable bool        `json:"airllm_available"`
}
