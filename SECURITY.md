# Security Policy

## About this project

NAAS (Normalized Adaptive Access System) is a **demonstration project** built to explore identity-normalization and risk-based access-control patterns. It is **not a production system** and is not intended to be deployed as one. Only the `event-ingestion` and `identity-normalization` services (plus the shared library, demo script, and infrastructure config) are currently implemented; the remaining services are design stubs.

The bundled configuration uses **well-known development credentials** (see `.env.example`) purely so the stack runs with a single `docker compose up`. These are deliberately insecure defaults for local demonstration — never reuse them anywhere real.

## Reporting a vulnerability

Even though this is a demo, reports are welcome — finding and fixing issues is part of the exercise.

- **Preferred:** open a private report via GitHub's **"Report a vulnerability"** button under the repository's **Security** tab (GitHub Security Advisories).
- **Alternative:** email `tony.offer@gmail.com` with a description and reproduction steps.

Please do not open a public issue for a suspected vulnerability until it has been triaged. As a personal demo project, this repository has no formal SLA; reports are addressed on a best-effort basis.
