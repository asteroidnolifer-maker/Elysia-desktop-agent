---
name: aircrack-ng
category: wireless
purpose: Wi-Fi security auditing for networks you own — verifies WPA2/WPA3 passphrase strength and detects rogue access points.
package: aircrack-ng
risk: high
aliases: wifi auditing, wep, wpa
---

aircrack-ng tests the real-world strength of your own wireless setup:
capture a handshake on YOUR AP and measure how long a passphrase survives a
dictionary attack — the evidence that moves homes/offices to long passphrases.

Authorized use (defensive-first):
- audit your own AP's passphrase strength (with a client you control).
- rogue-AP detection on your premises (`airodump-ng` survey of your space).

Monitor-mode captures are legal only on networks/channels you are authorized
to test; intercepting others' traffic is illegal in most jurisdictions. The
repo's skill gate quarantines wireless-attack skills by default. Install:
`sudo apt install aircrack-ng` (Kali).
