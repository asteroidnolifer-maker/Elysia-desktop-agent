---
name: testdisk
category: forensics
purpose: Recover lost partitions and repair filesystems on disks you own; photorec companion carves deleted files.
package: testdisk
risk: low
aliases: partition recovery, file carving, photorec
---

TestDisk/PhotoRec recover deleted partitions and carve lost files from damaged
or reformatted media. Elysia's relevance: **data-resilience documentation** —
what the recovery path looks like when a workspace disk misbehaves, and why
regular checkpoints (elysia git checkpoint) beat any forensic rescue.

Authorized use:
- your own disk: `testdisk /dev/sdX` (analyze, not write, until sure).
- photorec to carve your own accidentally-deleted workspace files.
- forensic image work on drives you own: always on a *copy*, not the original.

Install: `sudo apt install testdisk`.
