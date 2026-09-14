---
name: metasploit
category: exploitation
purpose: Exploit framework used by authorized red teams to prove a vulnerability is exploitable and to validate detection controls.
package: metasploit-framework
risk: high
aliases: msfconsole, msf, framework
---

Metasploit turns a known CVE into a repeatable, controlled test — the red-team
way to answer "would this actually hurt us, and would our alerts fire?"

Authorized use (defensive-first):
- validate that a patched host in YOUR lab is no longer exploitable.
- verify SOC detection: run a controlled module against a deliberately
  vulnerable VM you own and confirm the alert fires.
- training: Metasploitable-style lab VMs exist purely to be attacked legally.

The repo's skill gate marks exploitation tooling high-risk; any skill
referencing msf stays quarantined by default. Use only inside isolated lab
environments you own. Install: `curl https://raw.githubusercontent.com/rapid7/metasploit-omnibus/master/config/templates/metasploit-framework-wrappers/msfupdate.erb | bash`
or `sudo apt install metasploit-framework` on Kali.
