# Contributing

Use nanoMuse for a real task, report what broke, then pick something focused. Issues and pull requests are welcome; for anything larger than a fix, open an issue first so we can agree on the shape.

## Two trees

- **`android/`** — the app. A modified copy of [OpenMinis](https://github.com/OpenMinis/OpenMinis) 1.13 imported with `git subtree` (GPL-3.0). This is where the work happens now; see [docs/roadmap.md](docs/roadmap.md) for the six versions of Phase 1.
- **`nanomuse/`, `web/`, `demo/`, `site/`** — the Python line (agent, Sentinel, web app, showcase). Frozen at tag `pre-openminis`; kept as the base of the web and desktop phases. Fixes are welcome, features wait.

## Licence and sign-off

nanoMuse is **GPL-3.0-or-later** ([LICENSE](LICENSE), [NOTICE](NOTICE)). By contributing you agree that your contribution is licensed the same way. Every commit must carry a [Developer Certificate of Origin](https://developercertificate.org) sign-off — `git commit -s` adds the line:

```
Signed-off-by: Your Name <you@example.com>
```

CI checks it. Not accepted, ever:

- code under a licence that cannot be combined with GPL-3.0 (GPL-2.0-*only*, SSPL, BUSL, "source-available", proprietary SDKs);
- anything obtained by decompiling, unpacking or scraping the Meta Muse app, or the OpenMinis binaries beyond what their source already shows;
- the OpenMinis or Meta Muse names and logos as part of nanoMuse's own identity (attribution in the About screen and NOTICE is required and stays).

## Working in `android/`

Upstream is a mirror of a private tree, squashed roughly monthly, and does not take pull requests. We have to be able to `git subtree pull` each release, so:

1. **Do not rename the Kotlin package** `com.openminis.app` or the Gradle `namespace`. Only the `applicationId` (`io.github.nanomuse.app`) is ours.
2. **Do not rename sandbox paths or CLI names** inside the root file system (`/var/minis`, `minis-global`, `minis-open`, `minis-mcp-cli`, `android-*`). They are upstream's contract with itself.
3. **New code goes in new files** — package `io.github.nanomuse.*` or a new file next to the upstream one. When an upstream file must change, add a `// nanoMuse:` comment at the spot, and make one change per spot.
4. **Rebranding is a script, not hand edits.** `scripts/rebrand.py` (names, ids, colours, links) and `scripts/gen-android-icons.py` (launcher icons) are idempotent; run them after every upstream pull. Do not fix a rebranding miss by hand — fix the script.
5. **Binary resources** (icon PNGs) are overwritten under the upstream name; on a pull conflict take ours (`git checkout --ours`).

Build steps are in [android/BUILDING.md](android/BUILDING.md) (upstream) and, for the toolchain this repository is built with, in `scripts/android/` — JDK 21, SDK CMake 3.22.1, NDK r27c, Go 1.25+, `gomobile`; `deps/build_proot.sh` builds proot from the `android/deps/proot` submodule (our fork; portable `awk`, no gawk needed) and must run before `scripts/prepare_android_sandbox.sh`.

### Pulling an upstream release

```bash
git fetch openminis --tags
git subtree pull --prefix=android openminis 1.14 -m "Merge OpenMinis 1.14"
git rm -r -q android/src/ios android/deps/ish ...        # modify/delete conflicts: iOS is gone here
git checkout --ours -- 'android/src/android/app/src/main/res/mipmap-*'
python scripts/rebrand.py && python scripts/gen-android-icons.py
# resolve the remaining conflicts at the `// nanoMuse:` marks, build, run the smoke list
```

## Working in the Python line

```bash
git clone https://github.com/nano-muse/nanoMuse.git && cd nanoMuse
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"            # add ",browser" for the Playwright tool
nanomuse config init                  # config/config.toml is git-ignored
```

Before you push:

```bash
ruff check nanomuse tests scripts && ruff format nanomuse tests scripts
mypy                                           # types; config in pyproject.toml
python -m pytest -q                            # MockLLM only, no network
cd web && npm run check && npm run build       # if you touched web/; commit the build
```

Guidelines that still apply there: everything that acts goes through the Sentinel with an honest `risk`; secrets never reach the model (`{{vault:NAME}}`); test with `MockLLM`; no internal endpoints or keys in the repo; Ruff, line length 100, type hints; docs are part of the change.

## Commits and pull requests

- [Conventional Commits](https://www.conventionalcommits.org) prefixes are welcome but not required; the first line says what changed and why in plain words.
- One pull request, one topic. Screenshots for anything visible in the app.
- Say which device and Android version you tested on. Phone-side features are tested on real hardware; the emulator is x86_64 and cannot run the arm64 APK.

## Releasing (maintainers)

Every stage of Phase 1 is a version — `0.1.1`, `0.1.2`, … `0.1.6`, then `0.2.0`. Version names stay plain numbers (the in-app update check compares them). `scripts/release-apk.sh <version>` builds the release APK, verifies the signature, writes the sha256 and creates the GitHub pre-release; `docs/release-notes-template.md` is the shape of the notes. The signing key is one key for every version so an update installs over the previous one; it is not in the repository and not in CI.

## Security issues

Open a private security advisory on GitHub rather than a public issue.
