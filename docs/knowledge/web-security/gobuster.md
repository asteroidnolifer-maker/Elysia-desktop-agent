---
name: gobuster
category: web-security
purpose: Fast directory/file/DNS/vhost enumeration on web servers you operate, to find what you accidentally exposed.
package: gobuster
risk: low
aliases: dirbuster, content discovery, vhost enum
---

Gobuster brute-forces paths, subdomains and vhosts against a wordlist. For
Elysia it answers: **what did we deploy that we forgot about?** Backup files,
admin panels, staging apps, `.git` directories served publicly.

Authorized use:
- your own origins: `gobuster dir -u https://yourapp.local -w /usr/share/wordlists/dirb/common.txt`
- pre-release audits: does staging expose anything the release notes forgot?
- DNS mode for subdomain takeover hygiene on domains you control.

Rate-limit when scanning production you own (it is noisy). Install:
`sudo apt install gobuster` or `go install github.com/OJ/gobuster/v3@latest`.
