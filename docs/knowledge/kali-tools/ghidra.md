---
name: ghidra
category: reverse-engineering
purpose: Open-source disassembler/decompiler for analyzing binaries you own: malware triage in a lab, verifying supply-chain binaries, and security research.
package: ghidra
risk: moderate
aliases: reverse engineering, decompiler, disassembler, nsa
---

Ghidra (NSA, open source) decompiles compiled binaries into readable
pseudocode. Defensive teams use it to understand what a suspicious binary
actually does — without running it.

Authorized use (defensive-first):
- supply-chain check: inspect a vendor-updated binary before it ships to your
  fleet; look for unexpected network or credential APIs.
- malware triage in an isolated lab VM (never on your daily machine).
- understand the Go `agent-core` binary you built (`go build` output) when
  auditing what it links.

Install: `sudo apt install ghidra` (Kali) or download from
`https://ghidra-sre.org` (needs JDK 17+).
