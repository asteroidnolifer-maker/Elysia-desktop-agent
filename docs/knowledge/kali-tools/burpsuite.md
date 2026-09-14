---
name: burpsuite
category: web
purpose: Web-proxy toolkit for testing your own web apps: intercept requests, replay with modifications, and verify input handling during authorized assessments.
package: burpsuite
risk: moderate
aliases: burp, web proxy, http interceptor
---

Burp Suite sits between your browser and your own web application so you can
see and replay exactly what is sent. It is the standard workbench for
authorized web-app assessments (finding SQLi, XSS, broken auth in YOUR app
before someone else does).

Authorized use (defensive-first):
- test your local Elysia HUD/API: point the proxy at
  `http://127.0.0.1:8087` and inspect each endpoint's input validation.
- verify the rate limiting (`rate_limit_per_min` in `agent_config.json`)
  actually rejects floods.
- replay authenticated requests to confirm session handling on apps you own.

Only test applications you own or have written permission to assess.
Install: download from PortSwigger (`https://portswigger.net/burp`) or
`sudo apt install burpsuite` on Kali.
