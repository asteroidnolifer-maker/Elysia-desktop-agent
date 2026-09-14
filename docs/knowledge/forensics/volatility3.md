---
name: volatility3
category: forensics
purpose: Memory-forensics analysis of RAM captures — process/port/injection inspection for incident response on machines you defend.
package: volatility3
risk: low
aliases: memory forensics, ram analysis, incident response
---

Volatility 3 parses raw memory dumps to surface running processes, network
artifacts, injected code and rootkit traces **after** an incident, from a
capture you already took. This is pure defense/IR: it never touches a live
third-party system.

Authorized use:
- your own incident: capture RAM (e.g. `avml`/`winpmem`) then
  `vol -f memory.raw windows.pslist` to reconstruct what ran.
- malware triage on isolated lab machines you control.
- hunt: `windows.malfind` for injection patterns in your own fleet's captures.

Chain of custody matters for real IR: hash the capture, work on copies.
Install: `pipx install volatility3`.
