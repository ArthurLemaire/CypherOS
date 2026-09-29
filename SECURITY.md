# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.4.x   | ✅        |
| 0.3.x   | ✅        |
| < 0.3   | ❌        |

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

Email `security@example.com` with:

- a description of the issue and its impact,
- steps to reproduce (a minimal PoC helps),
- any suggested remediation.

We aim to acknowledge within 48 hours and to ship a fix or mitigation within
14 days for confirmed high-severity issues. We'll credit you in the release
notes unless you prefer to remain anonymous.

## Handling secrets

dots never logs connector tokens or LLM keys. Runtime state written to
`DOTS_STATE_DIR` may contain observations returned by tools — treat that
directory as sensitive and keep it out of version control (it is `.gitignore`d).
