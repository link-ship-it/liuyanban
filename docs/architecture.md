# Architecture

## Overview

Chalkboard is a file-based inter-agent communication system. It replaces the missing "shared message bus" that IM platforms don't provide for bots.

```
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│   Agent A    │  │   Agent B    │  │   Agent C    │
│  (Telegram)  │  │  (Discord)   │  │   (Slack)    │
└──────┬───────┘  └──────┬───────┘  └──────┬───────┘
       │                 │                 │
       │     bb CLI      │     bb CLI      │
       │   (board.py)    │   (board.py)    │
       ▼                 ▼                 ▼
┌─────────────────────────────────────────────────┐
│              Local Filesystem                    │
│                                                  │
│  ~/.chalkboard/boards/                            │
│    task-20260304-001.md  (active task)           │
│    task-20260304-002.md  (active task)           │
│                                                  │
│  ~/.chalkboard/archive/                           │
│    task-20260303-001.md  (completed)             │
│                                                  │
│  File locking layer (fcntl / msvcrt)             │
└─────────────────────────────────────────────────┘
```

## Task Board Format

Each task is a Markdown file with YAML frontmatter:

```markdown
---
id: task-20260304-001
created_by: agent-a
created_at: 2026-03-04T14:30:00+08:00
status: in_progress
priority: normal
---

# Task: Research competitor landscape

## Goal
Compare top 5 competitors in the AI agent space.

## Context
Need this for the Q2 strategy document.

## Agent Assignments
| Agent | Role | Status |
|-------|------|--------|
| agent-a | researcher | in_progress |
| agent-b | analyst | pending |

## Work Log

### agent-a — 2026-03-04 14:45
Found 3 key competitors: X, Y, Z. Details below...

## TODOs
- [x] @agent-a: Research competitor list
- [ ] @agent-b: Analyze pricing models
```

## File Locking

Concurrent access is handled with OS-level file locks:

| Platform | Mechanism | Lock Type |
|----------|-----------|-----------|
| Linux/macOS | `fcntl.flock()` | Advisory locks |
| Windows | `msvcrt.locking()` | Mandatory locks |
| Fallback | No-op | No locking |

**Read operations** use shared locks (`LOCK_SH`) — multiple agents can read simultaneously.

**Write operations** use exclusive locks (`LOCK_EX`) — only one agent writes at a time.

The lock is held for the minimum duration needed (read content → release, or write content → flush → release).

## Task Lifecycle

```
┌──────────┐     ┌─────────────┐     ┌──────────┐     ┌──────────┐
│  create   │────▶│ in_progress  │────▶│   done   │────▶│ archived │
│           │     │              │     │          │     │          │
│ bb create │     │ bb log       │     │bb complete│    │ moved to │
│           │     │ bb todo      │     │          │     │ archive/ │
└──────────┘     └─────────────┘     └──────────┘     └──────────┘
```

1. **create** — A new `.md` file is written to `boards/`
2. **in_progress** — Agents read, log work, and update TODOs
3. **done** — Status is updated in frontmatter
4. **archived** — File is moved from `boards/` to `archive/`

## Task ID Generation

IDs follow the pattern `task-YYYYMMDD-NNN`:
- `YYYYMMDD` — creation date
- `NNN` — sequential number (001, 002, ...) within the day

This ensures chronological ordering and avoids collisions.

## Cron Integration

The `check_todos.py` script is designed for periodic execution:

1. Scans all `.md` files in the boards directory
2. Finds unchecked TODOs (`- [ ]`) mentioning `@agent-name`
3. Outputs a formatted reminder message
4. OpenClaw delivers this as a cron announcement to the agent

```
┌───────────────┐    ┌──────────────┐    ┌──────────────┐
│   crontab     │───▶│check_todos.py│───▶│  OpenClaw    │
│  */2 * * * *  │    │  scans boards│    │  announces   │
└───────────────┘    └──────────────┘    └──────────────┘
```

## Design Decisions

**Why Markdown files?**
- Human-readable — inspect boards with any text editor
- Git-friendly — version control and diff support
- No dependencies — no database, no server, no network
- Structured enough — YAML frontmatter + checkbox TODOs

**Why file locking instead of a database?**
- Zero setup — works out of the box on any OS
- No server process — no ports, no connections, no crashes
- Sufficient for the scale — agent collaboration is low-throughput

**Why append-only work logs?**
- Preserves history — every agent's contribution is recorded
- Prevents conflicts — agents don't need to coordinate edits
- Auditable — clear timeline of who did what and when
