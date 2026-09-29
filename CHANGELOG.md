# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Distributed runtime spike (multiple dots over a shared event bus).

## [0.4.0] - 2026-09-20

### Added
- `VectorMemory` backend with cosine recall (`pip install dots-runtime[vector]`).
- `require_approval()` gate for human-in-the-loop actions.
- `dots diary` CLI command with `--tail` and `--since`.

### Changed
- Planner now caps action lists via `Goal.max_actions` (default 5).
- Event log switched to append-only JSONL for easier replay.

### Fixed
- Scheduler drift on long intervals when the host clock jumped.

## [0.3.1] - 2026-08-02

### Fixed
- `SqliteMemory` connection leak under high step frequency.

## [0.3.0] - 2026-07-15

### Added
- GitHub, Slack, and Gmail connectors.
- Deterministic replay via `Runtime.replay(log)`.

## [0.2.0] - 2026-06-10

### Added
- Pluggable memory protocol + in-memory and SQLite backends.
- `Goal` model and the plan → act → learn step loop.

## [0.1.0] - 2026-05-01

### Added
- Initial `Dot` and `Runtime` skeleton.

[Unreleased]: https://github.com/MuseTeaParty/Tea-Party/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/MuseTeaParty/Tea-Party/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/MuseTeaParty/Tea-Party/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/MuseTeaParty/Tea-Party/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/MuseTeaParty/Tea-Party/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/MuseTeaParty/Tea-Party/releases/tag/v0.1.0
