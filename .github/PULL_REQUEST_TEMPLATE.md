<!-- Thanks. Keep it small; one change per PR lands faster than three. -->

## What

<!-- One or two sentences. Link the issue if there is one: Fixes #123 -->

## Why

<!-- The problem this solves, or the Muse behaviour it brings in. -->

## Checks

- [ ] `ruff check openmuse tests && ruff format --check openmuse tests && mypy` pass
- [ ] `python -m pytest -q` passes; new behaviour has a test
- [ ] If the web app changed: `cd web && npm run check && npm run build`, and the result under `openmuse/server/static` is committed
- [ ] If a tool or the Sentinel changed: risk level, `assess()` summary and `docs/sentinel.md` are up to date
- [ ] If the API changed: `docs/app.md` is up to date
- [ ] No secrets, internal hostnames or personal data in the diff

## Screenshots

<!-- For anything visible in the app: before / after, phone-sized. Delete this section otherwise. -->
