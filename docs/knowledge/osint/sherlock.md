---
name: sherlock
category: osint
purpose: Find a username's accounts across hundreds of social networks for authorized investigations of your own brand or consented subjects.
package: sherlock
risk: low
aliases: username search, account discovery, social media footprint
---

Sherlock checks a username against hundreds of social platforms and reports
where it exists. For Elysia, it is documentation for **defensive OSINT**:
knowing your own organization's username footprint (brand protection,
impersonation detection) or assessing exposure with the subject's consent.

Authorized use:
- brand defense: check whether `yourcompany-dev` is being impersonated.
- consented assessments: a client documents, in writing, that you may profile
  their public exposure.
- your own footprint: what does an attacker learn from your handle alone?

Never target private individuals without consent — profiling people is a
privacy violation and often illegal. Install (your own machine):
`pipx install sherlock-project` or `sudo apt install sherlock`.
