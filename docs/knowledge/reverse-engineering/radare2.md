---
name: radare2
category: reverse-engineering
purpose: Interactive disassembler/patcher for binaries you own — malware triage in a lab, CTF, or auditing the firmware you ship.
package: radare2
risk: low
aliases: r2, disassembler, binary analysis, firmware audit
---

Radare2 disassembles, decompiles (with r2dec/r2ghidra) and patches binaries.
Elysia's framing: **audit what you ship or must defend against** — inspecting
your own release binaries, analyzing malware samples safely in an isolated lab,
or vendored-dependency due diligence.

Authorized use:
- your own artifacts: `r2 -A ./yourapp` then `pdf @ main` to review codegen.
- lab malware triage: **never execute** samples on your host; use a disposable
  VM, analyze statically with `r2 -n` and strings first.
- CTF/practice images you downloaded for learning.

License note: check each binary's license before redistributing derived work.
Install: `git clone https://github.com/radareorg/radare2 && sys/install.sh`
or `sudo apt install radare2`.
