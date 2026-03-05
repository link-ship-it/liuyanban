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
"""

import argparse
import datetime
import os
import re
import shutil
import sys
import tempfile
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
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _locked_modify(path: Path, modifier_fn):
    """Read-modify-write a file under a single exclusive lock (prevents TOCTOU).
    
    modifier_fn receives the current content string and must return the new content.
    """
    with open(path, "r+", encoding="utf-8") as f:
        _lock_exclusive(f)
        try:
            content = f.read()
            new_content = modifier_fn(content)
            f.seek(0)
            f.truncate()
            f.write(new_content)
            f.flush()
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

    assignment_table = ""
    todos = ""
    if agents:
        rows = "\n".join(f"| {a} | (to be defined) | pending |" for a in agents)
        assignment_table = f"""## Agent Assignments
| Agent | Role | Status |
|-------|------|--------|
{rows}
"""
        todo_lines = "\n".join(f"- [ ] @{a}: (define task)" for a in agents)
        todos = f"## TODOs\n{todo_lines}\n"

    parts = [
        f"---",
        f"id: {task_id}",
        f"created_by: {args.agent or 'user'}",
        f"created_at: {_now_iso()}",
        f"status: in_progress",
        f"priority: {args.priority or 'normal'}",
        f"---",
        f"",
        f"# Task: {args.title}",
        f"",
        f"## Goal",
        f"{args.goal or '(describe the goal here)'}",
        f"",
        f"## Context",
        f"{args.context or '(add relevant context)'}",
        f"",
    ]
    if assignment_table:
        parts.append(assignment_table)
    parts.extend([
        f"## Work Log",
        f"",
        f"(No entries yet.)",
        f"",
    ])
    if todos:
        parts.append(todos)

    content = "\n".join(parts) + "\n"

    path = _board_dir() / f"{task_id}.md"
    _locked_write(path, content)

    print(f"Created: {path}")
    print(f"Task ID: {task_id}")

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
        completed_line = [None]

        def _mark_done(content):
            pattern = re.compile(
                r"^- \[ \] (.*" + re.escape(args.done) + r".*)$",
                re.MULTILINE | re.IGNORECASE,
            )
            match = pattern.search(content)
            if not match:
                return None  # signal not found
            old_line = match.group(0)
            new_line = old_line.replace("- [ ]", "- [x]", 1)
            completed_line[0] = new_line
            return content.replace(old_line, new_line, 1)

        # Use read+lock manually since we need to handle "not found"
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


def cmd_init(args):
    """Initialize chalkboard for multi-agent collaboration."""
    agents = [a.strip() for a in args.agents.split(",") if a.strip()]
    profiles = [p.strip() for p in (args.profiles or "").split(",") if p.strip()]
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
        # Auto-detect: look for existing .openclaw* directories
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

    # Print cron setup instructions
    print("Cron setup (run for each OpenClaw instance):")
    print("=" * 60)
    for i, agent in enumerate(agents):
        profile_flag = ""
        if i < len(profiles) and profiles[i] != "default":
            profile_flag = f" --profile {profiles[i]}"
        elif i > 0 and not profiles:
            profile_flag = f" --profile <profile-name>"

        print(f"  openclaw{profile_flag} cron add \\")
        print(f'    --name "board-check" --every 2m \\')
        print(f'    --message "Check the bulletin board for pending TODOs assigned to you. Run: bb my-todos --agent {agent}" \\')
        print(f"    --announce")
        print()

    # Print summary
    print("=" * 60)
    print("Setup complete!")
    print()
    print(f"  Agents:     {', '.join(agents)}")
    print(f"  Boards:     {board_dir}")
    print(f"  Archive:    {archive_dir}")
    if workspaces:
        print(f"  Workspaces: {len(workspaces)} installed")
    print()
    print("Next steps:")
    print("  1. Run the cron commands above for each instance")
    print("  2. Send /restart in each bot's chat to load the skill")
    print("  3. Tell any bot: 'Create a task on the bulletin board'")


def cmd_my_todos(args):
    """Show pending TODOs for a specific agent."""
    board = _board_dir()
    files = sorted(board.glob("*.md"))
    agent = args.agent.lower()
    found_any = False

    for f in files:
        content = _locked_read(f)
        title = _extract_title(content)
        todos = re.findall(r"^- \[ \] .+$", content, re.MULTILINE)
        my_todos = [t for t in todos if f"@{agent}" in t.lower()]

        if my_todos:
            if not found_any:
                print(f"Pending TODOs for @{args.agent}:\n")
                found_any = True
            print(f"  [{f.stem}] {title}")
            for t in my_todos:
                print(f"    {t}")
            print()

    if not found_any:
        print(f"No pending TODOs for @{args.agent}.")


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

    # my-todos
    p_mytodos = sub.add_parser("my-todos", help="Show pending TODOs for an agent")
    p_mytodos.add_argument("--agent", required=True, help="Agent name")

    # init
    p_init = sub.add_parser("init", help="Initialize chalkboard for multi-agent collaboration")
    p_init.add_argument("--agents", required=True, help="Comma-separated agent names (e.g. researcher,writer,reviewer)")
    p_init.add_argument("--profiles", default="", help="Comma-separated OpenClaw profiles (e.g. default,alpha,alpha2)")
    p_init.add_argument("--skill-dir", default="", help="Path to chalkboard source directory (auto-detected)")

    args = parser.parse_args()

    commands = {
        "create": cmd_create,
        "list": cmd_list,
        "read": cmd_read,
        "log": cmd_log,
        "todo": cmd_todo,
        "complete": cmd_complete,
        "my-todos": cmd_my_todos,
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
