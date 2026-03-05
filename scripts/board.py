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

__version__ = "0.2.0"

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
    # Windows fallback — msvcrt only supports exclusive locks.
    # Both shared and exclusive acquire LK_LOCK (exclusive).
    # This is safe (no data corruption) but slightly less concurrent for reads.
    try:
        import msvcrt

        def _lock_shared(f):
            """Windows: no true shared lock, falls back to exclusive."""
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)

        def _lock_exclusive(f):
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)

        def _unlock(f):
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
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


def _atomic_write(path: Path, content: str):
    """Write a file atomically via temp file + rename (no truncation window)."""
    board = path.parent
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=str(board), suffix=".tmp", prefix=".bb_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(path))
        tmp_path = None  # successfully replaced, don't clean up
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _locked_modify(path: Path, modifier_fn):
    """Read-modify-write a file safely.

    Reads under exclusive lock, applies modifier_fn, then writes atomically.
    modifier_fn receives the current content and returns new content (or None to abort).
    Returns the new content, or None if modifier_fn returned None.
    """
    with open(path, "r", encoding="utf-8") as f:
        _lock_exclusive(f)
        try:
            content = f.read()
        finally:
            _unlock(f)

    new_content = modifier_fn(content)
    if new_content is None:
        return None

    _atomic_write(path, new_content)
    return new_content


def _find_task(task_id: str) -> Path:
    """Find a task file by ID, with fuzzy matching."""
    board = _board_dir()

    # Exact match
    exact = board / f"{task_id}.md"
    if exact.exists():
        return exact

    # Strip .md if user passed it
    if task_id.endswith(".md"):
        stripped = board / task_id
        if stripped.exists():
            return stripped
        task_id = task_id[:-3]

    # Exact stem match (prevents 001 matching 0011)
    for f in sorted(board.glob("*.md")):
        if f.stem == task_id:
            return f

    # Substring match (only if no exact stem match found)
    candidates = [f for f in sorted(board.glob("*.md")) if task_id in f.stem]
    if len(candidates) == 1:
        return candidates[0]
    elif len(candidates) > 1:
        print(f"Error: ambiguous task ID '{task_id}', matches:", file=sys.stderr)
        for c in candidates:
            print(f"  {c.stem}", file=sys.stderr)
        sys.exit(1)

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
    _atomic_write(path, content)

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
            return content.replace(old_line, new_line, 1)

        result = _locked_modify(path, _mark_done)
        if result is None:
            print(f"TODO not found matching: {args.done}", file=sys.stderr)
            sys.exit(1)
        print(f"Marked done: {args.done}")

    else:
        # List all TODOs
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

    content = _locked_read(path)
    pending = re.findall(r"^- \[ \] .+$", content, re.MULTILINE)
    if pending and not args.force:
        print(f"Warning: {len(pending)} pending TODO(s) remain:", file=sys.stderr)
        for t in pending:
            print(f"  {t}", file=sys.stderr)
        print("Use --force to complete anyway.", file=sys.stderr)
        sys.exit(1)

    def _mark_done(content):
        return re.sub(
            r"^status:\s*.+$", "status: done", content, count=1, flags=re.MULTILINE
        )

    _locked_modify(path, _mark_done)

    archive = _archive_dir() / path.name
    shutil.move(str(path), str(archive))
    print(f"Task {args.task_id} marked as done and archived to {archive}")


def _run_cmd(cmd: list, check: bool = True) -> tuple:
    """Run a subprocess command, return (returncode, stdout, stderr)."""
    import subprocess
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if check and result.returncode != 0:
            return (result.returncode, result.stdout, result.stderr)
        return (result.returncode, result.stdout, result.stderr)
    except FileNotFoundError:
        return (-1, "", f"Command not found: {cmd[0]}")
    except subprocess.TimeoutExpired:
        return (-1, "", "Command timed out")


def cmd_init(args):
    """Initialize Chalkboard for multi-agent collaboration.

    This command does everything needed in one shot:
    1. Creates board directories
    2. Installs the skill to all OpenClaw profiles
    3. Installs the `bb` CLI to PATH
    4. Configures cron jobs for automatic TODO checking
    5. Restarts the OpenClaw gateway

    After running init, just add bots to a group chat and start assigning tasks.
    """
    agents = [a.strip() for a in args.agents.split(",") if a.strip()]
    profiles = [p.strip() for p in (args.profiles or "").split(",") if p.strip()]
    skill_source = Path(args.skill_dir or Path(__file__).resolve().parent.parent)
    check_interval = args.interval or "2m"

    if not agents:
        print("Error: --agents is required (comma-separated agent names)", file=sys.stderr)
        sys.exit(1)

    if profiles and len(profiles) != len(agents):
        print("Error: --profiles must have the same number of entries as --agents", file=sys.stderr)
        print(f"  Got {len(agents)} agent(s) but {len(profiles)} profile(s)", file=sys.stderr)
        sys.exit(1)

    print("=" * 60)
    print("  Chalkboard Setup")
    print("=" * 60)
    print()

    # ── Step 1: Create directories ──
    board_dir = _board_dir()
    archive_dir = _archive_dir()
    print(f"[1/5] Directories")
    print(f"  Boards:  {board_dir}")
    print(f"  Archive: {archive_dir}")
    print()

    # ── Step 2: Install skill to OpenClaw workspaces ──
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
        # Auto-detect all .openclaw* directories
        default_ws = home / ".openclaw" / "workspace"
        if default_ws.exists():
            workspaces.append(("default", default_ws / "skills" / "chalkboard"))
        for d in sorted(home.glob(".openclaw-*")):
            if (d / "workspace").exists():
                profile_name = d.name.replace(".openclaw-", "")
                workspaces.append((profile_name, d / "workspace" / "skills" / "chalkboard"))

    print(f"[2/5] Installing skill to {len(workspaces)} workspace(s)")
    if not workspaces:
        print("  Warning: No OpenClaw workspaces found.", file=sys.stderr)
        print("  Install manually: cp -r <chalkboard-dir> ~/.openclaw/workspace/skills/chalkboard", file=sys.stderr)
    else:
        skill_files = ["SKILL.md"]
        script_files = ["scripts/board.py", "scripts/check_todos.py"]
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
            print(f"  ✓ [{profile}] -> {ws_path}")
    print()

    # ── Step 3: Install bb to PATH ──
    print(f"[3/5] Installing 'bb' CLI")
    bb_src = skill_source / "bb"
    local_bin = Path.home() / ".local" / "bin"
    bb_target = local_bin / "bb"

    if bb_src.exists() and not bb_target.exists():
        try:
            local_bin.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(bb_src), str(bb_target))
            bb_target.chmod(0o755)
            print(f"  ✓ Installed to {bb_target}")
            path_dirs = os.environ.get("PATH", "").split(os.pathsep)
            if str(local_bin) not in path_dirs:
                print(f"  ⚠ Add to your shell profile:")
                print(f'    export PATH="$HOME/.local/bin:$PATH"')
        except OSError as e:
            print(f"  ✗ Could not install: {e}")
            print(f"    Run manually: cp {bb_src} {bb_target} && chmod +x {bb_target}")
    elif bb_target.exists():
        print(f"  ✓ Already installed at {bb_target}")
    else:
        print(f"  - Skipped (bb script not found in source)")
    print()

    # ── Step 4: Configure cron jobs ──
    print(f"[4/5] Configuring cron jobs (check every {check_interval})")

    # Check if openclaw CLI is available
    rc, _, _ = _run_cmd(["openclaw", "--version"], check=False)
    if rc != 0:
        print("  ⚠ 'openclaw' CLI not found. Skipping cron setup.")
        print("  You can add cron jobs manually later:")
        for i, agent in enumerate(agents):
            profile = profiles[i] if i < len(profiles) else "default"
            pflag = "" if profile == "default" else f" --profile {profile}"
            print(f'    openclaw{pflag} cron add --name "chalkboard-{agent}" --every {check_interval} \\')
            print(f'      --message "Check Chalkboard for pending TODOs assigned to you. Run: python3 {skill_source}/scripts/check_todos.py {agent}" \\')
            print(f'      --announce')
    else:
        for i, agent in enumerate(agents):
            profile = profiles[i] if i < len(profiles) else "default"
            pflag = [] if profile == "default" else ["--profile", profile]
            cron_name = f"chalkboard-{agent}"

            # Check if cron already exists
            rc, stdout, _ = _run_cmd(["openclaw"] + pflag + ["cron", "list"], check=False)
            if cron_name in stdout:
                print(f"  ✓ [{profile}/{agent}] Cron '{cron_name}' already exists")
                continue

            # Add cron job
            check_script = str(skill_source / "scripts" / "check_todos.py")
            message = (
                f"You have a Chalkboard cron check. "
                f"Run this to see your pending TODOs: "
                f"python3 {check_script} {agent}\n"
                f"If there are pending TODOs, read the task board with bb read <task-id>, "
                f"do the work, log your results with bb log, and mark TODOs done. "
                f"If no pending TODOs, reply HEARTBEAT_OK."
            )

            cmd = (
                ["openclaw"] + pflag +
                [
                    "cron", "add",
                    "--name", cron_name,
                    "--every", check_interval,
                    "--message", message,
                    "--announce",
                ]
            )

            rc, stdout, stderr = _run_cmd(cmd, check=False)
            if rc == 0:
                print(f"  ✓ [{profile}/{agent}] Cron '{cron_name}' added (every {check_interval})")
            else:
                print(f"  ✗ [{profile}/{agent}] Failed to add cron: {stderr.strip()}")
    print()

    # ── Step 5: Restart gateway ──
    print(f"[5/5] Restarting OpenClaw gateway")
    rc, stdout, stderr = _run_cmd(["openclaw", "gateway", "restart"], check=False)
    if rc == 0:
        print(f"  ✓ Gateway restarted")
    elif rc == -1:
        print(f"  ⚠ Could not restart: {stderr.strip()}")
        print(f"    Run manually: openclaw gateway restart")
    else:
        # Might just need a moment
        print(f"  ⚠ {stderr.strip() or stdout.strip()}")
        print(f"    You may need to run: openclaw gateway restart")
    print()

    # ── Summary ──
    print("=" * 60)
    print("  Setup complete!")
    print("=" * 60)
    print()
    print(f"  Agents:     {', '.join(f'{a} ({profiles[i] if i < len(profiles) else 'auto'})' for i, a in enumerate(agents))}")
    print(f"  Boards:     {board_dir}")
    print(f"  Archive:    {archive_dir}")
    print(f"  Cron:       every {check_interval}")
    if workspaces:
        print(f"  Workspaces: {len(workspaces)} installed")
    print()
    print("  What to do now:")
    print("  1. Add your bots to a group chat")
    print("  2. Tell them: \"Research X — agent-a does research, agent-b reviews\"")
    print("  3. They'll coordinate automatically through Chalkboard")
    print()
    print("  That's it. No further setup needed.")


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
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
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
    p_init = sub.add_parser("init", help="Set up Chalkboard (one command, fully automatic)")
    p_init.add_argument("--agents", required=True, help="Comma-separated agent names (e.g. potato,kabishou)")
    p_init.add_argument("--profiles", default="", help="Comma-separated OpenClaw profiles matching agents (e.g. alpha2,default)")
    p_init.add_argument("--interval", default="2m", help="Cron check interval (default: 2m)")
    p_init.add_argument("--skill-dir", default="", help="Path to Chalkboard source directory (auto-detected)")

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
