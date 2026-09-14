# Kali / security tooling knowledge base (vendored)

Curated, defensive-first documentation for common security tools. Elysia's
`elysia.core.knowledge` module indexes these files so agents can answer
"which tool does X and how is it used *responsibly*?" from the repo instead
of hallucinating flags.

Scope:
- purpose, authorized-use guidance, install hint, risk class per tool
- **no attack walkthroughs** — that stays out per `docs/security/SECURITY_TOOLING.md`

Current entries: nmap, wireshark, burpsuite, sqlmap, metasploit, ghidra,
john, hydra, aircrack-ng, feroxbuster.

Add one: drop a `.md` with the same front-matter keys
(`name, category, purpose, package, risk, aliases`) in this directory —
`elysia knowledge list|search` picks it up automatically.
