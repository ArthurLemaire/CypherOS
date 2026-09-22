# Security

OpenMuse runs an agent that executes shell commands, code, network requests and email on your behalf, gated by a Sentinel. Where the line between "gated" and "not gated" sits is written down in [docs/sentinel.md](docs/sentinel.md#what-this-does-and-does-not-protect-against); please read it before reporting, and before deploying.

## Reporting a vulnerability

Please do not open a public issue for anything that lets the model or a third party get around the Sentinel, read a vault secret, reach the API without the token, or escape the workspace where the docs say it cannot.

Use GitHub's private reporting: **Security → Report a vulnerability** on [github.com/OpenMuseAgent/OpenMuse](https://github.com/OpenMuseAgent/OpenMuse/security/advisories/new). Include the version (`openmuse version`), your config with secrets removed, and the steps or prompt that reproduce it. You will get an acknowledgement within a week; fixes ship as a patch release with a note in the changelog and credit if you want it.

Things that are documented as out of scope — a command you approved doing damage, the vault key being readable by your own user, an exposed port on the public internet — are not vulnerabilities in OpenMuse, but if the documentation left you with the wrong impression, that is a bug too: open an issue.

## Supported versions

The latest minor release receives security fixes. Older versions do not.

## Good practice for operators

- Keep `server.auth = true`, do not expose the port beyond your own network, put TLS in front if you must.
- Run under a dedicated user account or in the Docker image if the machine holds things you care about.
- Prefer `{{vault:NAME}}` over environment variables for anything a tool needs; subprocesses do not see credential-looking environment variables, but they also do not need to.
- Read approval cards. Scope grants to what you mean; revoke them from the Permissions view when you are done.
- Leave `taint_tracking = true` and keep `egress_allowlist` short.
