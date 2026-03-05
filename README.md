<p align="center">
  <h1 align="center">Chalkboard</h1>
  <p align="center">Multi-agent collaboration through shared Markdown files</p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.8%2B-blue" alt="Python 3.8+">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License"></a>
  <img src="https://img.shields.io/badge/dependencies-zero-brightgreen" alt="Zero Dependencies">
  <img src="https://img.shields.io/github/stars/link-ship-it/chalkboard?style=social" alt="Stars">
</p>

<p align="center">
  <a href="docs/quickstart.md">Quick Start</a> ·
  <a href="docs/architecture.md">Architecture</a> ·
  <a href="docs/use-cases.md">Use Cases</a>
</p>

---

## The Problem

IM platforms (Telegram, Discord, Slack) **don't let bots read each other's messages**. If you run multiple AI agents in a group chat, they're completely blind to one another — no shared context, no coordination, no collaboration.

## The Solution

**Chalkboard** uses the local filesystem as a shared communication layer. Agents read and write structured Markdown files with file-level locking, TODO tracking, and append-only work logs.

No database. No server. No network. Just files.

```
User says in group chat: "Research NVDA, Potato does analysis, Snorlax reviews"
       │
       ├──→ Agent A (Potato) sees the message
       │    └→ bb create    → creates ~/.chalkboard/boards/task-001.md
       │    └→ bb log       → writes research findings to the board
       │
       └──→ Agent B (Snorlax) sees the message
            └→ bb read      → reads the board, sees Potato's work
            └→ bb log       → adds review and challenges
            └→ bb todo --done → marks task complete
```

Agents exchange information through the `.md` file, not through IM messages.

## How It Works

Each task is a Markdown file with YAML frontmatter, structured sections, and append-only logs:

```markdown
---
id: task-20260304-001
status: in_progress
priority: normal
---

# Task: NVDA Deep Dive

## Goal
5-round research method, produce a target price

## Agent Assignments
| Agent   | Role       | Status      |
|---------|------------|-------------|
| potato  | researcher | in_progress |
| snorlax | reviewer   | pending     |

## Work Log

### potato — 2026-03-04 14:30
FY2026 revenue $216B, gross margin 71%, target price $252...

### snorlax — 2026-03-04 15:00
Challenge: Q1 margin dip to 60% needs explanation. $252 too aggressive?

### potato — 2026-03-04 15:30
Revised target $245. Margin recovers to 75% by Q4...

## TODOs
- [x] @potato: Complete 5-round research
- [x] @snorlax: Review and challenge findings
- [ ] @potato: Publish final report
```

Key design choices:
- **Append-only work logs** — agents never overwrite each other's entries
- **File locking** — shared locks for reads, exclusive locks for writes (`fcntl` on Unix, `msvcrt` on Windows)
- **TODO tracking** — `@agent` mentions with checkbox status
- **Task lifecycle** — create → in_progress → done → archived

## Quick Start (5 minutes)

**Requirements:** Python 3.8+ (no external dependencies)

### 1. Install (one command)

```bash
git clone https://github.com/link-ship-it/chalkboard.git
cd chalkboard
python3 scripts/board.py init \
  --agents "agent-a,agent-b" \
  --profiles "default,alpha"
```

That's it. The `init` command automatically:
- Creates `~/.chalkboard/boards/` and `archive/` directories
- Installs the skill to all matching [OpenClaw](https://github.com/openclaw/openclaw) profiles
- Installs the `bb` CLI to `~/.local/bin`
- Configures cron jobs so agents automatically check for pending TODOs
- Restarts the OpenClaw gateway

After init, just add your bots to a group chat and start assigning tasks.

### 2. Create a task

```bash
bb create \
  --title "Research AI frameworks" \
  --goal "Compare top 5 frameworks" \
  --assign agent-a,agent-b \
  --agent agent-a
```

### 3. Collaborate

```bash
# Agent A does research, writes findings
bb log task-20260305-001 --agent agent-a \
  --content "Found 3 key competitors: X, Y, Z..."

# Agent B reads the board, sees what A wrote
bb read task-20260305-001

# Agent B adds analysis
bb log task-20260305-001 --agent agent-b \
  --content "Agent A missed competitor W, which has 40% market share..."

# Mark your TODO as done
bb todo task-20260305-001 --done "Research competitors"

# Check what's still pending
bb my-todos --agent agent-b
```

### 4. Complete and archive

```bash
bb complete task-20260305-001
# File moves from boards/ to archive/
```

### 5. (Optional) Cron reminders

Set up periodic TODO checks so agents don't forget pending work:

```yaml
# In your OpenClaw config
cron:
  - schedule: "*/2 * * * *"
    command: "python3 ~/.openclaw-shared/skills/chalkboard/scripts/check_todos.py agent-a"
    announce: true
```

## CLI Reference

| Command | Description |
|---------|-------------|
| `bb create` | Create a new task board |
| `bb list` | List all active tasks |
| `bb read <task-id>` | Read a task board |
| `bb log <task-id>` | Append a work log entry |
| `bb todo <task-id> --add` | Add a TODO for an agent |
| `bb todo <task-id> --done` | Mark a TODO as complete |
| `bb my-todos --agent <name>` | Show your pending TODOs |
| `bb complete <task-id>` | Archive a completed task |

## Use Cases

### Stock Research (Researcher + Reviewer)

Two agents analyze a stock from different angles. One does deep research, the other pokes holes.

```bash
bb create --title "NVDA analysis" \
  --goal "Buy/sell recommendation with target price" \
  --assign analyst,reviewer --agent analyst --priority high

bb todo TASK_ID --add "@analyst: Financials, P/E, revenue growth, moat analysis"
bb todo TASK_ID --add "@reviewer: Challenge assumptions, check risk factors"
```

### Content Pipeline (Research → Draft → Edit)

```bash
bb create --title "Blog: Future of AI agents" \
  --goal "Publish a 2000-word post" \
  --assign researcher,writer,editor --agent user

bb todo TASK_ID --add "@researcher: Gather 5 recent sources on AI agent trends"
bb todo TASK_ID --add "@writer: Draft post using researcher's sources"
bb todo TASK_ID --add "@editor: Review for clarity, tone, and accuracy"
```

### Code Review (Multi-perspective)

```bash
bb create --title "Review PR #42 — auth module" \
  --goal "Security + performance + style review" \
  --assign sec-reviewer,perf-reviewer,style-reviewer --agent user

bb todo TASK_ID --add "@sec-reviewer: Check auth bypass, injection, token handling"
bb todo TASK_ID --add "@perf-reviewer: Check N+1 queries, unnecessary allocations"
bb todo TASK_ID --add "@style-reviewer: Check naming, structure, test coverage"
```

### Multi-Perspective Research

```bash
bb create --title "AI framework comparison" \
  --goal "Compare LangChain, CrewAI, AutoGen, OpenClaw" \
  --assign researcher-1,researcher-2,synthesizer --agent user

bb todo TASK_ID --add "@researcher-1: Research LangChain and CrewAI"
bb todo TASK_ID --add "@researcher-2: Research AutoGen and OpenClaw"
bb todo TASK_ID --add "@synthesizer: Read both logs and create comparison matrix"
```

> More examples in [examples/](examples/) and [Use Cases](docs/use-cases.md).

## Architecture

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
│  ~/.chalkboard/boards/     (active tasks)        │
│  ~/.chalkboard/archive/    (completed tasks)     │
│                                                  │
│  File locking: fcntl (Unix) / msvcrt (Windows)   │
└─────────────────────────────────────────────────┘
```

- **Zero dependencies** — pure Python 3.8+ standard library
- **Cross-platform file locking** — prevents concurrent write conflicts
- **Git-friendly** — plain Markdown files, easy to version control and diff
- **Works with any agent platform** — anything that can run a shell command works. First-class [OpenClaw](https://github.com/openclaw/openclaw) integration included (skill auto-install, cron reminders), but Chalkboard is fully standalone.

> Deep dive: [Architecture docs](docs/architecture.md)

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CHALKBOARD_BOARD_DIR` | `~/.chalkboard/boards` | Active task boards |
| `CHALKBOARD_ARCHIVE_DIR` | `~/.chalkboard/archive` | Completed tasks |

## License

[MIT](LICENSE)
