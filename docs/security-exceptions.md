# Security exceptions

## CVE-2026-37737 — Sanic-Cors

Rasa SDK 3.6 requires Sanic-Cors. Version 2.2.0 is the newest upstream
release and remains affected by CVE-2026-37737, which can bypass a CORS origin
allowlist when an attacker can reach the service from a browser origin.

The Action Server is a Rasa-to-backend service endpoint, not a browser API. Its
Compose port is bound to `127.0.0.1`, and Rasa reaches it over the private
Compose network. It must not be published through an ingress or a public host
interface. CI audits both the declared requirements and the complete built
image, explicitly retaining this single upstream-unfixed finding.

Remove the audit exception when a fixed upstream release is available or Rasa
SDK supports a fixed CORS implementation.
