---
name: theHarvester
category: osint
purpose: Gather public emails, subdomains, hosts and names from public sources for your own domain's attack-surface inventory.
package: theharvester
risk: low
aliases: email harvest, subdomain enumeration, surface inventory
---

theHarvester aggregates passive public-source data (certificates, search
engines, key repositories) about a domain. Elysia treats it as **your-surface
documentation**: which emails/subdomains does the public internet associate
with your organization?

Authorized use:
- your own domains: find forgotten subdomains before attackers do.
- phishing-surface audits: which `@yourcompany.com` patterns are public?
- consented engagements with written scope.

Typical benign form: `theHarvester -d yourcompany.com -b crtsh` (certificate
transparency only). Never harvest third parties without authorization.
Install: `sudo apt install theharvester` or `pipx install theHarvester`.
