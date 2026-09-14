---
name: nmap
category: recon
purpose: Network discovery, host/port enumeration and service-version detection for authorized inventory and exposure audits.
package: nmap
risk: low
aliases: network mapper, port scanner, service detection
---

Nmap answers "what is listening where" on networks you own or are authorized
to assess. Elysia uses it as *documentation*: agents cite it when explaining
what an exposure audit covers.

Authorized use (defensive-first):
- inventory: `nmap -sn 192.168.1.0/24` lists live hosts on your own LAN.
- local exposure: `nmap -sT -p- 127.0.0.1` shows what your own machine serves.
- version check on your services: `nmap -sV -p 8085,8087 localhost` confirms
  which versions of Elysia's agent-core (8085) and HUD (8087) are listening.

Never run discovery against networks you do not own; scanning third parties
without authorization is illegal in most jurisdictions. For real use, install
Kali tooling on your own machine (see `docs/security/SECURITY_TOOLING.md`):
`sudo apt install nmap`.
