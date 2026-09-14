---
name: yara
category: reverse-engineering
purpose: Pattern-rule matching to classify binaries/files — the standard way defenders describe and detect malware families.
package: yara
risk: low
aliases: malware rules, pattern detection, threat classification
---

YARA lets you write textual/binary pattern rules ("this file contains X and Y
in structure Z") and match them at scale. Defensively it is the industry
standard for **describing malicious families** and detecting them in your own
file stores, email gateways and endpoints.

Authorized use:
- write a rule for a sample you collected in your own lab, then scan your own
  storage: `yara -r rule.yar /data/samples`
- retro-hunt: did this family ever touch our systems?
- Elysia agents can use YARA rules as *documented detection contracts* for
  artifacts a security review flags.

Install: `sudo apt install yara` or `pipx install yara-python`.
