---
name: john
category: passwords
purpose: Offline password-hash auditing to prove your own users' passwords (or your service's stored hashes) meet policy.
package: john
risk: high
aliases: john the ripper, jtr, hash cracking
---

John the Ripper audits password hashes *you are responsible for*: after an
incident, or as a periodic policy check, it shows how quickly current hashes
fall to dictionary attacks — the numbers that justify passphrases/argon2id.

Authorized use (defensive-first):
- audit your own app's dumped test hashes in a lab to validate hashing
  parameters (work factors) are strong enough.
- verify a locked-down system image's shadow file resists a realistic
  wordlist before deployment.

Cracking hashes you are not authorized to audit is a crime. The repo's skill
gate quarantines hash-auditing skills by default. Install:
`sudo apt install john` (Kali).
