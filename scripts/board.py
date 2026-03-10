#!/usr/bin/env python3
"""
Chalkboard CLI — Multi-agent collaboration through shared Markdown files.

Commands:
  create    Create a new task board
  list      List active tasks
  read      Read a task board
  log       Append a work log entry
  todo      Add or complete TODOs
  complete  Mark a task as done and archive it
  my-todos  Show pending TODOs assigned to a specific agent
  init      Set up Chalkboard for multi-agent collaboration
"""

__version__ = "0.4.0"

import argparse
import datetime
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

# ── Cross-platform file locking ─────────────────────────────────────────

try:
    import fcntl

    def _lock_shared(f):
        fcntl.flock(f, fcntl.LOCK_SH)

    def _lock_exclusive(f):
        fcntl.flock(f, fcntl.LOCK_EX)

    def _unlock(f):
        fcntl.flock(f, fcntl.LOCK_UN)

except ImportError:
    # Windows fallback — lock entire file, not just 1 byte
    try:
        import msvcrt

        def _lock_shared(f):
            f.seek(0, 2)  # seek to end to get size
            size = max(f.tell(), 1)
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, size)

        def _lock_exclusive(f):
            f.seek(0, 2)
            size = max(f.tell(), 1)
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, size)

        def _unlock(f):
            try:
                f.seek(0, 2)
                size = max(f.tell(), 1)
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, size)
            except OSError:
                pass

    except ImportError:
        # No locking available — proceed without
        def _lock_shared(f):
            pass

        def _lock_exclusive(f):
            pass

        def _unlock(f):
            pass


# ── Configuration ────────────────────────────────────────────────────────

DEFAULT_BOARD_DIR = os.path.expanduser("~/.chalkboard/boards")
DEFAULT_ARCHIVE_DIR = os.path.expanduser("~/.chalkboard/archive")


def _board_dir() -> Path:
    """Return the boards directory, creating it if needed."""
    p = Path(os.environ.get("CHALKBOARD_BOARD_DIR", DEFAULT_BOARD_DIR))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _archive_dir() -> Path:
    """Return the archive directory, creating it if needed."""
    p = Path(os.environ.get("CHALKBOARD_ARCHIVE_DIR", DEFAULT_ARCHIVE_DIR))
    p.mkdir(parents=True, exist_ok=True)
    return p


# ── Agent Identity ────────────────────────────────────────────────────────


def _get_agent_id() -> str:
    """Get the current agent's identity from environment."""
    return os.environ.get("CHALKBOARD_AGENT_ID", "")


def _is_my_todo(todo_line: str, agent_id: str) -> bool:
    """Check if a TODO belongs to the given agent (supports aliases)."""
    if not agent_id:
        return True
    aliases = [a.strip().lower() for a in agent_id.split(",") if a.strip()]
    todo_lower = todo_line.lower()
    return any(f"@{alias}" in todo_lower for alias in aliases)


def _extract_current_turn(content: str) -> str:
    """Extract current_turn from YAML frontmatter."""
    m = re.search(r"^current_turn:\s*(.+)$", content, re.MULTILINE)
    return m.group(1).strip() if m else ""


def _is_my_turn(content: str, agent_id: str) -> bool:
    """Check if it's this agent's turn to work."""
    turn = _extract_current_turn(content)
    if not turn:
        return True
    if not agent_id:
        return True
    aliases = [a.strip().lower() for a in agent_id.split(",") if a.strip()]
    return turn.lower() in aliases


# ── Board Templates ──────────────────────────────────────────────────────

TEMPLATES = {
    "research": {
        "goal": "Multi-perspective research: each agent investigates from a different angle, then one agent synthesizes findings.",
        "rounds": [
            ("agent-a", "Research from angle A, write findings to the board"),
            ("agent-b", "Research from angle B, write findings to the board"),
            ("agent-a", "Read all findings, write synthesis and recommendations"),
        ],
    },
    "code-review": {
        "goal": "Multi-perspective code review: security, performance, and style.",
        "rounds": [
            ("reviewer-1", "Security review: auth bypass, injection, token handling"),
            ("reviewer-2", "Performance review: N+1 queries, allocations, caching"),
            ("reviewer-1", "Synthesize all reviews into actionable summary"),
        ],
    },
    "brainstorm": {
        "goal": "Brainstorm session: each agent proposes ideas, then vote and refine.",
        "rounds": [
            ("agent-a", "Propose 5 ideas with brief rationale for each"),
            ("agent-b", "Review ideas, add 3 more, rank all by feasibility"),
            ("agent-a", "Pick top 3, flesh out implementation plan for each"),
        ],
    },
    "content": {
        "goal": "Content pipeline: research, draft, review, finalize.",
        "rounds": [
            ("researcher", "Gather sources and key data points"),
            ("writer", "Draft content based on research"),
            ("reviewer", "Review draft, challenge weak points, suggest edits"),
            ("writer", "Incorporate feedback and finalize"),
        ],
    },
}


# ── Utilities ────────────────────────────────────────────────────────────


def _generate_task_id() -> str:
    """Generate a unique task ID using atomic file creation (O_CREAT|O_EXCL)."""
    now = datetime.datetime.now()
    date_part = now.strftime("%Y%m%d")
    board = _board_dir()
    for seq in range(1, 1000):
        task_id = f"task-{date_part}-{seq:03d}"
        path = board / f"{task_id}.md"
        try:
            # O_CREAT|O_EXCL is atomic — fails if file already exists
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return task_id
        except FileExistsError:
            continue
    raise RuntimeError(f"Could not generate unique task ID for date {date_part}")


def _now_iso() -> str:
    """Return current time in ISO format with timezone."""
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _now_display() -> str:
    """Return current time in human-readable format."""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def _locked_read(path: Path) -> str:
    """Read a file with shared (read) lock."""
    with open(path, "r", encoding="utf-8") as f:
        _lock_shared(f)
        try:
            content = f.read()
        finally:
            _unlock(f)
    return content


def _locked_write(path: Path, content: str):
    """Write a file atomically via temp file + rename (no truncation window)."""
    board = path.parent
    try:
        fd, tmp_path = tempfile.mkstemp(dir=str(board), suffix=".tmp", prefix=".bb_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)  # type: ignore[possibly-undefined]
        except (OSError, UnboundLocalError):
            pass
        raise


def _locked_modify(path: Path, modifier_fn):
    """Read-modify-write a file atomically under an exclusive lock."""
    with open(path, "r+", encoding="utf-8") as f:
        _lock_exclusive(f)
        try:
            content = f.read()
            new_content = modifier_fn(content)
            fd, tmp_path = tempfile.mkstemp(
                dir=str(path.parent), suffix=".tmp", prefix=".bb_"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as tmp_f:
                    tmp_f.write(new_content)
                    tmp_f.flush()
                    os.fsync(tmp_f.fileno())
                os.replace(tmp_path, str(path))
            except Exception:
                try:
                    os.unlink(tmp_path)
                except (OSError, UnboundLocalError):
                    pass
                raise
        finally:
            _unlock(f)


def _find_task(task_id: str) -> Path:
    """Find a task file by ID, with fuzzy matching."""
    board = _board_dir()

    # Exact match
    exact = board / f"{task_id}.md"
    if exact.exists():
        return exact

    # Without extension
    if task_id.endswith(".md"):
        no_ext = board / task_id
        if no_ext.exists():
            return no_ext

    # Partial match
    for f in sorted(board.glob("*.md")):
        if task_id in f.stem:
            return f

    print(f"Error: task '{task_id}' not found in {board}", file=sys.stderr)
    sys.exit(1)


def _extract_title(content: str) -> str:
    """Extract task title from Markdown content."""
    for line in content.splitlines():
        if line.startswith("# Task:"):
            return line[7:].strip()
    return "(untitled)"


def _extract_status(content: str) -> str:
    """Extract task status from YAML frontmatter."""
    m = re.search(r"^status:\s*(.+)$", content, re.MULTILINE)
    return m.group(1).strip() if m else "unknown"


# ── Commands ─────────────────────────────────────────────────────────────


def cmd_create(args):
    """Create a new task board."""
    task_id = _generate_task_id()
    agents = [a.strip() for a in (args.assign or "").split(",") if a.strip()]
    template = TEMPLATES.get(args.template, None) if hasattr(args, "template") and args.template else None

    goal = args.goal
    if template and not goal:
        goal = template["goal"]

    assignment_table = ""
    todos = ""
    first_agent = ""

    if template and agents:
        rounds = template["rounds"]
        todo_lines = []
        for i, (role, desc) in enumerate(rounds):
            agent_idx = i % len(agents)
            agent_name = agents[agent_idx]
            todo_lines.append(f"- [ ] @{agent_name}: [Round {i+1}] {desc}")
        todos = "## TODOs\n" + "\n".join(todo_lines) + "\n"
        first_agent = agents[0]
        rows = "\n".join(f"| {a} | collaborator | pending |" for a in agents)
        assignment_table = f"""## Agent Assignments
| Agent | Role | Status |
|-------|------|--------|
{rows}
"""
    elif agents:
        rows = "\n".join(f"| {a} | (to be defined) | pending |" for a in agents)
        assignment_table = f"""## Agent Assignments
| Agent | Role | Status |
|-------|------|--------|
{rows}
"""
        todo_lines = "\n".join(f"- [ ] @{a}: (define task)" for a in agents)
        todos = f"## TODOs\n{todo_lines}\n"
        first_agent = agents[0]

    parts = [
        "---",
        f"id: {task_id}",
        f"created_by: {args.agent or 'user'}",
        f"created_at: {_now_iso()}",
        "status: in_progress",
        f"priority: {args.priority or 'normal'}",
    ]
    if first_agent:
        parts.append(f"current_turn: {first_agent}")
    parts.extend([
        "---",
        "",
        f"# Task: {args.title}",
        "",
        "## Goal",
        f"{goal or '(describe the goal here)'}",
        "",
        "## Context",
        f"{args.context or '(add relevant context)'}",
        "",
    ])
    if assignment_table:
        parts.append(assignment_table)
    parts.extend([
        "## Work Log",
        "",
        "(No entries yet.)",
        "",
    ])
    if todos:
        parts.append(todos)

    content = "\n".join(parts) + "\n"

    path = _board_dir() / f"{task_id}.md"
    _locked_write(path, content)

    print(f"Created: {path}")
    print(f"Task ID: {task_id}")
    if template:
        print(f"Template: {args.template}")
    if first_agent:
        print(f"Current turn: {first_agent}")
    if agents:
        print(f"Assigned to: {', '.join(agents)}")
        print(f'\nNotify them: "New task on the board: {args.title}. Check {task_id}"')


def cmd_list(args):
    """List all active tasks."""
    board = _board_dir()
    files = sorted(board.glob("*.md"))

    if not files:
        print("No active tasks.")
        return

    print(f"Active tasks ({len(files)}):\n")
    for f in files:
        content = _locked_read(f)
        title = _extract_title(content)
        status = _extract_status(content)
        pending = len(re.findall(r"^- \[ \]", content, re.MULTILINE))
        done = len(re.findall(r"^- \[x\]", content, re.MULTILINE))

        print(f"  {f.stem}")
        print(f"    Title:  {title}")
        print(f"    Status: {status}")
        print(f"    TODOs:  {done} done, {pending} pending")
        print()


def cmd_read(args):
    """Read and display a task board."""
    path = _find_task(args.task_id)
    content = _locked_read(path)
    print(content)


def cmd_log(args):
    """Append a work log entry to a task board."""
    path = _find_task(args.task_id)
    entry = f"\n### {args.agent} — {_now_display()}\n{args.content}\n"

    def _modify(content):
        if "(No entries yet.)" in content:
            return content.replace("(No entries yet.)", entry.strip())
        elif "## TODOs" in content:
            return content.replace("## TODOs", f"{entry}\n## TODOs")
        else:
            return content + entry

    _locked_modify(path, _modify)
    print(f"Logged entry by {args.agent} to {path.stem}")


def cmd_todo(args):
    """Manage TODOs on a task board."""
    path = _find_task(args.task_id)

    if args.add:
        todo_line = args.add if args.add.startswith("- [ ]") else f"- [ ] {args.add}"

        def _add_todo(content):
            if "## TODOs" in content:
                return content.replace("## TODOs", f"## TODOs\n{todo_line}")
            return content + f"\n## TODOs\n{todo_line}\n"

        _locked_modify(path, _add_todo)
        print(f"Added TODO: {todo_line}")

    elif args.done:
        agent_id = _get_agent_id()
        completed_line = [None]

        def _mark_done(content):
            pattern = re.compile(
                r"^- \[ \] (.*" + re.escape(args.done) + r".*)$",
                re.MULTILINE | re.IGNORECASE,
            )
            match = pattern.search(content)
            if not match:
                return None
            old_line = match.group(0)
            if agent_id and not _is_my_todo(old_line, agent_id):
                print(f"Error: This TODO belongs to another agent. You can only mark your own TODOs as done.", file=sys.stderr)
                print(f"  TODO: {old_line}", file=sys.stderr)
                print(f"  Your identity: {agent_id}", file=sys.stderr)
                sys.exit(1)
            new_line = old_line.replace("- [ ]", "- [x]", 1)
            completed_line[0] = new_line
            new_content = content.replace(old_line, new_line, 1)
            remaining = re.findall(r"^- \[ \] .+$", new_content, re.MULTILINE)
            if remaining:
                next_todo = remaining[0]
                next_agent_match = re.search(r"@(\S+)", next_todo)
                if next_agent_match:
                    next_agent = next_agent_match.group(1).rstrip(":")
                    new_content = re.sub(
                        r"^current_turn:\s*.+$",
                        f"current_turn: {next_agent}",
                        new_content, count=1, flags=re.MULTILINE,
                    )
            return new_content

        with open(path, "r+", encoding="utf-8") as f:
            _lock_exclusive(f)
            try:
                content = f.read()
                new_content = _mark_done(content)
                if new_content is None:
                    print(f"TODO not found matching: {args.done}", file=sys.stderr)
                    sys.exit(1)
                f.seek(0)
                f.truncate()
                f.write(new_content)
                f.flush()
            finally:
                _unlock(f)
        print(f"Completed: {completed_line[0]}")

    else:
        # List all TODOs (read-only, shared lock is fine)
        content = _locked_read(path)
        todos = re.findall(r"^- \[[ x]\] .+$", content, re.MULTILINE)
        if todos:
            for t in todos:
                print(t)
        else:
            print("No TODOs found.")


def cmd_complete(args):
    """Mark a task as done and move it to the archive."""
    path = _find_task(args.task_id)

    # Read first to check pending TODOs
    content = _locked_read(path)
    pending = re.findall(r"^- \[ \] .+$", content, re.MULTILINE)
    if pending and not args.force:
        print(f"Warning: {len(pending)} pending TODO(s) remain:", file=sys.stderr)
        for t in pending:
            print(f"  {t}", file=sys.stderr)
        print("Use --force to complete anyway.", file=sys.stderr)
        sys.exit(1)

    # Modify under lock
    def _mark_done(content):
        return re.sub(
            r"^status:\s*.+$", "status: done", content, count=1, flags=re.MULTILINE
        )

    _locked_modify(path, _mark_done)

    archive = _archive_dir() / path.name
    shutil.move(str(path), str(archive))
    print(f"Task {args.task_id} marked as done and archived to {archive}")


def cmd_agents(args):
    """Auto-discover OpenClaw agents and group chats on this machine."""
    home = Path.home()
    found = []

    # Check default profile
    default_id = home / ".openclaw" / "workspace" / "IDENTITY.md"
    if default_id.exists():
        name = _parse_identity_name(default_id)
        found.append(("default", name, str(default_id.parent.parent)))

    # Check named profiles
    for d in sorted(home.glob(".openclaw-*")):
        identity = d / "workspace" / "IDENTITY.md"
        if identity.exists():
            profile = d.name.replace(".openclaw-", "")
            name = _parse_identity_name(identity)
            found.append((profile, name, str(d)))

    if not found:
        print("No OpenClaw agents found on this machine.")
        print("  Expected: ~/.openclaw/workspace/IDENTITY.md")
        return

    print(f"Found {len(found)} agent(s):\n")
    print(f"  {'Profile':<15} {'Name':<20} {'Config Dir'}")
    print(f"  {'-'*15} {'-'*20} {'-'*40}")
    for profile, name, config_dir in found:
        print(f"  {profile:<15} {name:<20} {config_dir}")
    print()

    # Auto-discover group chats via openclaw gateway
    groups = _discover_groups()
    if groups:
        print(f"Found {len(groups)} group chat(s):\n")
        print(f"  {'Channel':<12} {'Chat ID':<45} {'Name'}")
        print(f"  {'-'*12} {'-'*45} {'-'*30}")
        for channel, chat_id, display in groups:
            print(f"  {channel:<12} {chat_id:<45} {display}")
        print()

        latest = groups[0]
        notify_target = latest[1]
        notify_channel = latest[0]
    else:
        print("No group chats found. @ your bot in a group chat first, then re-run.\n")
        notify_target = "<your-group-chat-id>"
        notify_channel = "feishu"

    # Generate suggested init command
    agent_names = [f[1] for f in found]
    profile_names = [f[0] for f in found]
    print("Suggested init command:\n")
    print(f"  bb init \\")
    print(f"    --agents \"{','.join(agent_names)}\" \\")
    print(f"    --profiles \"{','.join(profile_names)}\" \\")
    print(f"    --channel {notify_channel} \\")
    print(f"    --notify-target {notify_target}")


def _discover_groups() -> list:
    """Discover group chats via openclaw gateway call sessions.list."""
    import subprocess as _sp
    try:
        result = _sp.run(
            ["openclaw", "gateway", "call", "sessions.list"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return []
        text = result.stdout
        start = text.find("{")
        if start < 0:
            return []
        import json as _json
        data = _json.loads(text[start:])
        groups = []
        for s in data.get("sessions", []):
            key = s.get("key", "")
            if "group" not in key:
                continue
            channel = s.get("channel", "")
            display = s.get("displayName", "")
            parts = key.split(":")
            chat_id = parts[-1] if len(parts) > 4 else ""
            if chat_id:
                groups.append((channel, chat_id, display))
        return groups
    except Exception:
        return []


def _parse_identity_name(path: Path) -> str:
    """Extract agent name from IDENTITY.md."""
    try:
        content = path.read_text(encoding="utf-8")
        for line in content.splitlines():
            # Match patterns like "Name: xxx" or "**Name:** xxx"
            m = re.match(r"^[-*\s]*(?:\*\*)?Name:?\*?\*?\s*(.+)$", line, re.IGNORECASE)
            if m:
                name = m.group(1).strip().strip("*").strip()
                if name:
                    return name
    except (OSError, UnicodeDecodeError):
        pass
    return "(unknown)"


def _read_openclaw_credentials(channel_type: str) -> dict:
    """Read IM credentials from OpenClaw config files."""
    home = Path.home()
    config_path = home / ".openclaw" / "openclaw.json"
    if not config_path.exists():
        return {}
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        channels = config.get("channels", {})
        ch = channels.get(channel_type, {})
        accounts = ch.get("accounts", {})
        main = accounts.get("main", {})

        if channel_type == "feishu":
            app_id = main.get("appId", "")
            app_secret = main.get("appSecret", "")
            if app_id and app_secret:
                return {"app_id": app_id, "app_secret": app_secret}
        elif channel_type == "telegram":
            bot_token = main.get("botToken", "")
            if bot_token:
                return {"bot_token": bot_token}
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _discover_session_ids(group_id: str) -> dict:
    """Discover session IDs for each profile's group session."""
    import subprocess as _sp
    result_map = {}

    for profile_flag in [[], ["--profile", "alpha"], ["--profile", "alpha2"]]:
        profile_name = profile_flag[1] if len(profile_flag) > 1 else "default"
        try:
            cmd = ["openclaw"] + profile_flag + ["gateway", "call", "sessions.list"]
            result = _sp.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode != 0:
                continue
            text = result.stdout
            start = text.find("{")
            if start < 0:
                continue
            data = json.loads(text[start:])
            for s in data.get("sessions", []):
                key = s.get("key", "")
                if group_id in key and "group" in key:
                    result_map[profile_name] = s.get("sessionId", "")
                    break
        except Exception:
            continue

    return result_map


def cmd_poller(args):
    """Manage the Chalkboard poller daemon."""
    home = Path.home()
    plist = home / "Library" / "LaunchAgents" / "com.chalkboard.daemon.plist"
    import subprocess

    if args.poller_action == "status":
        result = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
        found = [l for l in result.stdout.splitlines() if "chalkboard" in l]
        if found:
            print("Daemon: running")
            for l in found:
                print(f"  {l}")
        else:
            print("Daemon: not running")

        config_path = Path(os.path.expanduser("~/.chalkboard/config.json"))
        if config_path.exists():
            config = json.loads(config_path.read_text())
            for gid, gcfg in config.get("groups", {}).items():
                print(f"  Group: {gcfg.get('provider', '?')} -> {gid}")
                print(f"  Poll interval: {gcfg.get('poll_interval', '?')}s")
                for a in gcfg.get("agents", []):
                    print(f"  Agent: {a['name']} (profile={a.get('profile', '?')}, session={a.get('session_id', '?')[:8]}...)")

        state_file = Path(os.path.expanduser("~/.chalkboard/poller_state.json"))
        if state_file.exists():
            state = json.loads(state_file.read_text())
            last_poll = state.get("last_poll", 0)
            if last_poll:
                ago = int(time.time() - last_poll)
                print(f"  Last poll: {ago}s ago")

    elif args.poller_action == "stop":
        if plist.exists():
            subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
            print("Daemon stopped")
        else:
            print("Daemon not installed")

    elif args.poller_action == "start":
        if plist.exists():
            subprocess.run(["launchctl", "load", str(plist)], capture_output=True)
            print("Daemon started")
        else:
            print("Daemon not installed. Run: bb init --enable-poller")


def cmd_context(args):
    """View recent group chat context collected by the poller."""
    from scripts.poller import read_context, format_context
    try:
        msgs = read_context(args.group, args.last)
    except ImportError:
        context_dir = Path(os.path.expanduser("~/.chalkboard/context"))
        safe_id = args.group.replace("/", "_").replace(":", "_")
        path = context_dir / f"group-{safe_id}.jsonl"
        if not path.exists():
            print(f"No context found for group {args.group}")
            return
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        msgs = []
        for line in lines[-args.last:]:
            try:
                msgs.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not msgs:
        print(f"No messages in group {args.group}")
        return

    for msg in msgs:
        name = msg.get("sender_name", "unknown")
        bot_tag = " [bot]" if msg.get("is_bot") else ""
        text = msg.get("content", "")
        ts = msg.get("ts", 0)
        time_str = datetime.datetime.fromtimestamp(ts).strftime("%H:%M") if ts else "??:??"
        print(f"[{time_str}] {name}{bot_tag}: {text}")


def _parse_aliases(aliases_str: str, agents: list) -> dict:
    """Parse aliases string and map to agent names by position.
    
    Format: "alias1,alias2;alias3,alias4" (semicolon separates groups, matched to agents by position)
    Returns: {agent_name: [all_aliases_including_agent_name]}
    """
    if not aliases_str:
        return {a: [a] for a in agents}

    groups = [g.strip() for g in aliases_str.split(";") if g.strip()]
    result = {}
    for i, agent in enumerate(agents):
        all_names = [agent]
        if i < len(groups):
            extra = [p.strip() for p in groups[i].split(",") if p.strip()]
            all_names.extend(extra)
        result[agent] = list(dict.fromkeys(all_names))
    return result


def cmd_init(args):
    """Initialize Chalkboard for multi-agent collaboration."""
    agents = [a.strip() for a in args.agents.split(",") if a.strip()]
    profiles = [p.strip() for p in (args.profiles or "").split(",") if p.strip()]
    aliases_map = _parse_aliases(args.aliases or "", agents)
    channel = args.channel or ""
    skill_source = Path(args.skill_dir or Path(__file__).resolve().parent.parent)

    if not agents:
        print("Error: --agents is required (comma-separated agent names)", file=sys.stderr)
        sys.exit(1)

    board_dir = _board_dir()
    archive_dir = _archive_dir()
    print(f"Board directory: {board_dir}")
    print(f"Archive directory: {archive_dir}")
    print()

    # Determine OpenClaw workspace directories
    home = Path.home()
    workspaces = []

    if profiles:
        for profile in profiles:
            if profile == "default":
                ws = home / ".openclaw" / "workspace" / "skills" / "chalkboard"
            else:
                ws = home / f".openclaw-{profile}" / "workspace" / "skills" / "chalkboard"
            workspaces.append((profile, ws))
    else:
        default_ws = home / ".openclaw" / "workspace"
        if default_ws.exists():
            workspaces.append(("default", default_ws / "skills" / "chalkboard"))
        for d in sorted(home.glob(".openclaw-*")):
            if (d / "workspace").exists():
                profile_name = d.name.replace(".openclaw-", "")
                workspaces.append((profile_name, d / "workspace" / "skills" / "chalkboard"))

    if not workspaces:
        print("Warning: No OpenClaw workspaces found. Skipping skill installation.", file=sys.stderr)
        print("  Install manually: cp -r <chalkboard-dir> ~/.openclaw/workspace/skills/chalkboard", file=sys.stderr)
    else:
        skill_files = ["SKILL.md"]
        script_files = ["scripts/board.py", "scripts/check_todos.py"]

        print(f"Installing skill to {len(workspaces)} workspace(s)...")
        for profile, ws_path in workspaces:
            scripts_dir = ws_path / "scripts"
            scripts_dir.mkdir(parents=True, exist_ok=True)

            for f in skill_files:
                src = skill_source / f
                if src.exists():
                    shutil.copy2(str(src), str(ws_path / f))
            for f in script_files:
                src = skill_source / f
                if src.exists():
                    shutil.copy2(str(src), str(ws_path / f))

            print(f"  [{profile}] -> {ws_path}")
        print()

    # Set up bb in PATH
    bb_src = skill_source / "bb"
    bb_target = Path("/usr/local/bin/bb")
    if bb_src.exists() and not bb_target.exists():
        try:
            shutil.copy2(str(bb_src), str(bb_target))
            bb_target.chmod(0o755)
            print(f"Installed 'bb' command to {bb_target}")
        except PermissionError:
            print(f"Note: Could not install 'bb' to {bb_target} (permission denied)")
            print(f"  Run manually: sudo cp {bb_src} {bb_target} && sudo chmod +x {bb_target}")
    elif bb_target.exists():
        print(f"'bb' command already exists at {bb_target}")
    print()

    # Generate config.yaml
    notify_target = args.notify_target or ""
    notify_channel = channel or "feishu"
    enable_poller = getattr(args, "enable_poller", False)
    config_dir = board_dir.parent
    config_path = config_dir / "config.json"

    # Discover session IDs for agents
    session_map = _discover_session_ids(notify_target) if notify_target else {}

    # Read feishu/telegram credentials from OpenClaw config
    feishu_creds = _read_openclaw_credentials("feishu")
    telegram_creds = _read_openclaw_credentials("telegram")

    config_data = {
        "version": "0.5.0",
        "groups": {},
    }

    if notify_target:
        agent_configs = []
        for i, agent in enumerate(agents):
            profile = profiles[i] if i < len(profiles) else "default"
            all_names = aliases_map.get(agent, [agent])
            sid = session_map.get(profile, "")
            agent_configs.append({
                "name": agent,
                "profile": profile,
                "session_id": sid,
                "aliases": all_names[1:] if len(all_names) > 1 else [],
            })

        config_data["groups"][notify_target] = {
            "provider": notify_channel,
            "poll_interval": 5,
            "cooldown": 30,
            "agents": agent_configs,
        }

    if feishu_creds:
        config_data["feishu"] = feishu_creds
    if telegram_creds:
        config_data["telegram"] = telegram_creds

    config_path.write_text(json.dumps(config_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Config: {config_path}")

    # Generate daemon.sh
    daemon_sh = config_dir / "daemon.sh"
    home = Path.home()
    script_dir = skill_source / "scripts"

    daemon_lines = [
        "#!/bin/bash",
        f'export HOME="{home}"',
        'export PATH="$([ -s "$HOME/.nvm/nvm.sh" ] && . "$HOME/.nvm/nvm.sh" >/dev/null 2>&1 && dirname "$(nvm which current 2>/dev/null)" 2>/dev/null || echo "$HOME/.nvm/versions/node/current/bin"):$HOME/.local/bin:/usr/local/bin:$PATH"',
        "",
        f'CONFIG="{config_path}"',
        f'SCRIPTS="{script_dir}"',
        "",
    ]

    if enable_poller:
        daemon_lines.extend([
            "# Poll group messages (all users + all bots)",
            f'python3 "$SCRIPTS/poller.py" --config "$CONFIG" 2>/dev/null',
            "",
        ])

    daemon_lines.extend([
        "# Check TODOs and trigger agents",
        f'python3 "$SCRIPTS/decide.py" --config "$CONFIG" 2>/dev/null',
    ])

    daemon_sh.write_text("\n".join(daemon_lines) + "\n", encoding="utf-8")
    daemon_sh.chmod(0o755)
    print(f"Daemon: {daemon_sh}")

    # Install launchd plist
    interval = 5 if enable_poller else 50
    plist_path = home / "Library" / "LaunchAgents" / "com.chalkboard.daemon.plist"
    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.chalkboard.daemon</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>{daemon_sh}</string>
    </array>
    <key>StartInterval</key>
    <integer>{interval}</integer>
    <key>StandardOutPath</key>
    <string>{config_dir}/daemon.log</string>
    <key>StandardErrorPath</key>
    <string>{config_dir}/daemon.err.log</string>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>"""

    import subprocess

    # Unload old daemons
    for old_label in ["com.chalkboard.notify", "com.chalkboard.daemon"]:
        old_plist = home / "Library" / "LaunchAgents" / f"{old_label}.plist"
        if old_plist.exists():
            subprocess.run(["launchctl", "unload", str(old_plist)], capture_output=True)

    plist_path.write_text(plist_content)
    subprocess.run(["launchctl", "load", str(plist_path)], capture_output=True)

    # Clean old crontab entries
    try:
        existing = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
        cleaned = "\n".join(l for l in existing.splitlines() if "chalkboard" not in l and l.strip())
        if cleaned != existing:
            subprocess.run(["crontab", "-"], input=cleaned + "\n", text=True, check=True)
    except Exception:
        pass

    poller_status = "enabled (every 5s)" if enable_poller else "disabled"
    print(f"Daemon: launchd (every {interval}s)")
    print(f"Poller: {poller_status}")

    print()

    # Summary
    print("=" * 60)
    print("Setup complete!")
    print()
    agent_summary = []
    for agent in agents:
        al = aliases_map.get(agent, [])
        if al:
            agent_summary.append(f"{agent} ({', '.join(al)})")
        else:
            agent_summary.append(agent)
    print(f"  Agents:     {', '.join(agent_summary)}")
    print(f"  Boards:     {board_dir}")
    print(f"  Archive:    {archive_dir}")
    if notify_target:
        print(f"  Group:      {notify_channel} -> {notify_target}")
    print(f"  Poller:     {poller_status}")
    print(f"  Daemon:     every {interval}s (launchd)")
    if workspaces:
        print(f"  Workspaces: {len(workspaces)} installed")
    print()
    print("Next steps:")
    print("  1. Send /restart in each bot's chat to load the skill")
    print("  2. Tell any bot: 'Create a task on the chalkboard'")
    if enable_poller:
        print("  3. Poller is active — bots can now see each other's messages")


def cmd_my_todos(args):
    """Show pending TODOs for a specific agent (supports comma-separated aliases)."""
    board = _board_dir()
    files = sorted(board.glob("*.md"))
    aliases = [a.strip().lower() for a in args.agent.split(",") if a.strip()]
    display_name = aliases[0] if aliases else args.agent
    found_any = False

    for f in files:
        content = _locked_read(f)
        title = _extract_title(content)
        todos = re.findall(r"^- \[ \] .+$", content, re.MULTILINE)
        my_todos = [
            t for t in todos
            if any(f"@{alias}" in t.lower() for alias in aliases)
        ]

        if my_todos:
            if not found_any:
                print(f"Pending TODOs for @{display_name}:\n")
                found_any = True
            print(f"  [{f.stem}] {title}")
            for t in my_todos:
                print(f"    {t}")
            print()

    if not found_any:
        print(f"No pending TODOs for @{display_name}.")


# ── Main ─────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        prog="bb",
        description="Chalkboard — Multi-agent collaboration via shared Markdown files",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # create
    p_create = sub.add_parser("create", help="Create a new task board")
    p_create.add_argument("--title", required=True, help="Task title")
    p_create.add_argument("--goal", default="", help="Task goal description")
    p_create.add_argument("--context", default="", help="Relevant context")
    p_create.add_argument("--assign", default="", help="Comma-separated agent names")
    p_create.add_argument("--agent", default="user", help="Who is creating this task")
    p_create.add_argument(
        "--template",
        default="",
        choices=["", "research", "code-review", "brainstorm", "content"],
        help="Board template (auto-generates rounds and TODOs)",
    )
    p_create.add_argument(
        "--priority",
        default="normal",
        choices=["low", "normal", "high", "critical"],
        help="Priority level (default: normal)",
    )

    # list
    sub.add_parser("list", help="List active tasks")

    # read
    p_read = sub.add_parser("read", help="Read a task board")
    p_read.add_argument("task_id", help="Task ID or filename")

    # log
    p_log = sub.add_parser("log", help="Append a work log entry")
    p_log.add_argument("task_id", help="Task ID")
    p_log.add_argument("--agent", required=True, help="Agent name")
    p_log.add_argument("--content", required=True, help="Log entry content")

    # todo
    p_todo = sub.add_parser("todo", help="Manage TODOs on a task")
    p_todo.add_argument("task_id", help="Task ID")
    p_todo.add_argument("--add", default="", help="Add a new TODO item")
    p_todo.add_argument("--done", default="", help="Mark a TODO as done (partial match)")

    # complete
    p_complete = sub.add_parser("complete", help="Mark task as done and archive")
    p_complete.add_argument("task_id", help="Task ID")
    p_complete.add_argument(
        "--force", action="store_true", help="Complete even with pending TODOs"
    )

    # agents
    sub.add_parser("agents", help="Auto-discover OpenClaw agents on this machine")

    # my-todos
    p_mytodos = sub.add_parser("my-todos", help="Show pending TODOs for an agent")
    p_mytodos.add_argument("--agent", required=True, help="Agent name or comma-separated aliases (e.g. agent-a,Alice)")

    # poller
    p_poller = sub.add_parser("poller", help="Manage the Chalkboard poller daemon")
    p_poller.add_argument("poller_action", choices=["start", "stop", "status"], help="Poller action")

    # context
    p_context = sub.add_parser("context", help="View recent group chat context")
    p_context.add_argument("--group", required=True, help="Group chat ID")
    p_context.add_argument("--last", type=int, default=20, help="Number of recent messages (default: 20)")

    # init
    p_init = sub.add_parser("init", help="Initialize Chalkboard for multi-agent collaboration")
    p_init.add_argument("--agents", required=True, help="Comma-separated agent names (e.g. researcher,writer,reviewer)")
    p_init.add_argument("--profiles", default="", help="Comma-separated OpenClaw profiles (e.g. default,alpha,alpha2)")
    p_init.add_argument("--aliases", default="", help='Agent aliases, semicolon-separated groups (e.g. "agent-a,Alice;agent-b,Bob")')
    p_init.add_argument("--channel", default="", help="Notification channel (e.g. feishu, telegram, discord)")
    p_init.add_argument("--notify-target", default="", help="Group chat ID to send notifications to (e.g. oc_xxx for feishu)")
    p_init.add_argument("--enable-poller", action="store_true", help="Enable message polling (bots see all group messages)")
    p_init.add_argument("--skill-dir", default="", help="Path to Chalkboard source directory (auto-detected)")

    args = parser.parse_args()

    commands = {
        "create": cmd_create,
        "list": cmd_list,
        "read": cmd_read,
        "log": cmd_log,
        "todo": cmd_todo,
        "complete": cmd_complete,
        "agents": cmd_agents,
        "my-todos": cmd_my_todos,
        "poller": cmd_poller,
        "context": cmd_context,
        "init": cmd_init,
    }

    try:
        commands[args.command](args)
    except KeyboardInterrupt:
        sys.exit(130)
    except BrokenPipeError:
        sys.exit(0)


if __name__ == "__main__":
    main()
