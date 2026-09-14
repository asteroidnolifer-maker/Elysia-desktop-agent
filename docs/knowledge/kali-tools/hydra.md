---
name: hydra
category: passwords
purpose: Parallelized login auditing for services you own — verifies account lockout, rate limiting, and MFA actually stop credential-guessing.
package: hydra
risk: high
aliases: thc-hydra, login auditing
---

Hydra proves your defenses work: point it at YOUR service with a tiny test
wordlist and confirm lockouts trigger, rate limits hold, and alerts fire.

Authorized use (defensive-first):
- verify `agent-core`'s `rate_limit_per_min` (default 60) actually rejects a
  burst of bad token attempts against your own deployment.
- confirm your SSH/FTP test box enforces lockout after N failures.

Attacking accounts or services you do not own is illegal. The repo's skill
gate quarantines brute-force skills by default. Install:
`sudo apt install hydra` (Kali).
