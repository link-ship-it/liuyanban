# Changelog

All notable changes to Chalkboard are documented here.

## [2.2] - 2026-03-09

### Added
- Feishu community group QR code in README
- Production-ready open source packaging

### Fixed
- Atomic file writes in `_locked_modify` to prevent data loss
- Dynamic Node.js path detection (no more hardcoded version)
- `_locked_write` exception handling for uninitialized temp path

## [2.1] - 2026-03-08

### Added
- LLM-powered decision engine (`judge.py`) with pluggable providers (Anthropic, OpenAI)
- Two-step trigger + forward: captures agent response and posts to group chat
- Structured JSON output from LLM judge with trigger/reason/task fields

### Changed
- Decision engine no longer depends on board files — works purely from chat context

## [2.0] - 2026-03-07

### Added
- Chat-first decision engine (`decide.py`) — trigger agents based on group conversation
- Message poller (`poller.py`) — fetches ALL group messages via Feishu/Telegram API
- Agent auto-discovery (`bb agents`) — scans OpenClaw profiles and group chats
- `bb init` with `--enable-poller` flag for full daemon setup
- launchd daemon integration (runs every 5 seconds)

### Changed
- Architecture shift from board-centric to conversation-centric collaboration

## [0.5.1] - 2026-03-06

### Added
- Auto-detect multi-agent tasks and create boards automatically

## [0.5.0] - 2026-03-06

### Added
- Poller + Decision Engine for full auto-pilot multi-agent collaboration

## [0.3.0] - 2026-03-05

### Added
- `--aliases` flag for agent name aliases (supports multiple names per agent)
- `--channel` flag to specify cron notification channel
- Duplicate task prevention
- Naming convention rules for agents

## [0.2.1] - 2026-03-05

### Added
- Fully automated `bb init` — one command setup with auto cron and gateway restart

## [0.2.0] - 2026-03-04

### Fixed
- Windows file locking compatibility
- Atomic writes to prevent corruption
- Fuzzy match safety improvements

### Added
- `--version` flag

## [0.1.0] - 2026-03-04

### Added
- Initial release
- Core CLI: `create`, `list`, `read`, `log`, `todo`, `my-todos`, `complete`
- File-based task boards with Markdown format
- Cross-platform file locking (fcntl / msvcrt)
- Board templates: research, code-review, brainstorm, content
- OpenClaw skill integration (`SKILL.md`)
- Zero external dependencies (Python 3.8+ stdlib only)
