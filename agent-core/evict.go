package main

// EvictionHandler is called when ModelMemoryManager evicts a model name.
// Set this to a function that will unload models from the inference process as needed.
var EvictionHandler func(name string)
