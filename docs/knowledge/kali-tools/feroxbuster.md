---
name: feroxbuster
category: web
purpose: Recursive content discovery on web apps you own — finds forgotten admin panels, backups, and debug endpoints before attackers do.
package: feroxbuster
risk: moderate
aliases: content discovery, directory brute force, ffuf alternative
---

feroxbuster enumerates hidden paths on YOUR web app (staging copies, `.git/`
leftovers, `/debug`, old backups). Every hit is cleanup work for you.

Authorized use (defensive-first):
- sweep your local HUD (`http://127.0.0.1:8087`) and any dev deployment for
  endpoints that should not be public.
- verify your 404/403 handling does not leak directory listings.

Keep request rates polite against shared infrastructure; target only systems
you own. Install: `sudo apt install feroxbuster` (Kali) or grab a release
binary from `https://github.com/epi052/feroxbuster`.
