#!/usr/bin/env python3
"""
Cron script for Chalkboard.
Checks for pending TODOs assigned to a specific agent.
Outputs a message suitable for OpenClaw cron --announce delivery.
"""

import os
import re
import sys
from pathlib import Path

BOARD_DIR = Path(
    os.environ.get("CHALKBOARD_BOARD_DIR", os.path.expanduser("~/.chalkboard/boards"))
)


def check(agent: str) -> str:
    """Check all boards for pending TODOs assigned to the given agent."""
    if not BOARD_DIR.exists():
        return ""

    files = sorted(BOARD_DIR.glob("*.md"))
    results = []

    for f in files:
        try:
            content = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        title = "(untitled)"
        for line in content.splitlines():
            if line.startswith("# Task:"):
                title = line[7:].strip()
                break

        todos = re.findall(r"^- \[ \] .+$", content, re.MULTILINE)
        my_todos = [t for t in todos if f"@{agent.lower()}" in t.lower()]

        if my_todos:
            items = "\n".join(f"  {t}" for t in my_todos)
            results.append(f"[{f.stem}] {title}\n{items}")

    if not results:
        return ""

    header = "You have pending TODOs on the board:\n\n"
    body = "\n\n".join(results)
    footer = (
        "\n\nRead the task: bb read <task-id>"
        '\nUpdate when done: bb todo <task-id> --done "<description>"'
    )
    return header + body + footer


def main():
    if len(sys.argv) < 2:
        print("Usage: check_todos.py <agent_name>", file=sys.stderr)
        sys.exit(1)

    agent = sys.argv[1]
    msg = check(agent)

    if msg:
        print(msg)

    sys.exit(0)


if __name__ == "__main__":
    main()
