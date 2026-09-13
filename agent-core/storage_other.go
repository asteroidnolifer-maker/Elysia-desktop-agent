//go:build !linux

package main

import "errors"

// storageFree is unsupported on non-Linux builds (agent targets Android/Linux).
func storageFree(path string) (free, total int64, err error) {
	return 0, 0, errors.New("storage stats not supported on this OS")
}
