---
name: wireshark
category: analysis
purpose: Capture and inspect network traffic to debug protocols and verify what an application actually sends.
package: wireshark
risk: low
aliases: packet capture, tshark, protocol analyzer
---

Wireshark (and its terminal sibling `tshark`) shows the bytes on the wire so
you can verify claims: is Elysia's `agent-core` really talking only to
`127.0.0.1`? Is that provider call leaking an API key in a URL?

Authorized use (defensive-first):
- local loopback debugging: capture on `lo` and filter
  `tcp.port == 8085 || tcp.port == 8087 || tcp.port == 11434` to watch
  Elysia's internal traffic.
- header hygiene: filter `http.request` and inspect Authorization headers on
  your own calls to confirm redaction works.
- education: reading real handshakes teaches more than diagrams.

Only capture traffic on networks you own or are explicitly authorized to
monitor. Install: `sudo apt install wireshark` (add yourself to the
`wireshark` group for non-root captures).
