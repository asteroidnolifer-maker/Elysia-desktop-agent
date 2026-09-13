//go:build linux

package main

import "syscall"

// storageFree returns free and total bytes for the filesystem containing path.
func storageFree(path string) (free, total int64, err error) {
	var st syscall.Statfs_t
	if err = syscall.Statfs(path, &st); err != nil {
		return 0, 0, err
	}
	free = int64(st.Bavail) * int64(st.Bsize)
	total = int64(st.Blocks) * int64(st.Bsize)
	return free, total, nil
}
