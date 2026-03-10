#!/usr/bin/env python3
"""
Chalkboard Decision Engine v2.1 — LLM-powered agent coordination.

Uses an LLM judge to read recent chat messages and decide which agent should act.
Falls back to board TODOs if no LLM is configured.

Flow:
  1. Check for new messages since last run
  2. If new messages → ask LLM judge: "which agent should act?"
  3. If judge says trigger → inject context into agent session → capture reply → forward to group
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

BOARD_DIR = Path(os.environ.get("CHALKBOARD_BOARD_DIR", os.path.expanduser("~/.chalkboard/boards")))
CONTEXT_DIR = Path(os.environ.get("CHALKBOARD_CONTEXT_DIR", os.path.expanduser("~/.chalkboard/context")))
STATE_FILE = Path(os.path.expanduser("~/.chalkboard/decide_state.json"))
MAX_RETRIES = 3


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_messages(group_id: str) -> list:
    safe_id = group_id.replace("/", "_").replace(":", "_")
    path = CONTEXT_DIR / f"group-{safe_id}.jsonl"
    if not path.exists():
        return []
    messages = []
    for line in path.read_text(encoding="utf-8").strip().splitlines():
        try:
            messages.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return messages


def _format_context(messages: list, last_n: int = 15) -> str:
    parts = []
    for msg in messages[-last_n:]:
        name = msg.get("sender_name", "?")
        bot = " [bot]" if msg.get("is_bot") else ""
        text = msg.get("content", "")
        if text and text != "请升级至最新版本客户端，以查看内容":
            parts.append(f"{name}{bot}: {text}")
    return "\n".join(parts)


def _has_new_messages(messages: list, state: dict, group_id: str) -> bool:
    """Check if there are messages newer than last check."""
    last_msg_id = state.get("last_seen_msg_id", {}).get(group_id, "")
    if not last_msg_id:
        return bool(messages)
    for msg in reversed(messages[-5:]):
        if msg.get("msg_id") == last_msg_id:
            return False
    return True


def _find_agent_config(agent_name: str, all_agents: list) -> dict:
    """Find agent config by name or alias."""
    name_lower = agent_name.lower()
    for a in all_agents:
        names = [a["name"].lower()] + [x.lower() for x in a.get("aliases", [])]
        if name_lower in names:
            return a
    return {}


def _get_board_todos(aliases: list) -> list:
    """Fallback: check board TODOs."""
    if not BOARD_DIR.exists():
        return []
    aliases_lower = [a.lower() for a in aliases]
    results = []
    for f in sorted(BOARD_DIR.glob("*.md")):
        try:
            content = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        todos = re.findall(r"^- \[ \] .+$", content, re.MULTILINE)
        my_todos = [t for t in todos if any(f"@{a}" in t.lower() for a in aliases_lower)]
        if my_todos:
            all_pending = re.findall(r"^- \[ \] .+$", content, re.MULTILINE)
            first = all_pending[0] if all_pending else ""
            is_my_turn = any(f"@{a}" in first.lower() for a in aliases_lower)
            if is_my_turn:
                title = "(untitled)"
                for line in content.splitlines():
                    if line.startswith("# Task:"):
                        title = line[7:].strip()
                        break
                results.append({"task_id": f.stem, "title": title, "todos": my_todos})
    return results


def trigger_and_forward(agent_name: str, profile: str, session_id: str,
                        reason: str, task: str, context_str: str,
                        group_id: str, channel: str) -> bool:
    """Trigger agent, capture response, forward to group chat."""

    prompt_parts = []
    if context_str:
        prompt_parts.append(f"[Recent group chat]\n{context_str}")

    prompt_parts.append(
        f"[Action] {reason}\n"
        f"Task: {task}\n\n"
        f"Do the requested work. Read any referenced files or boards if needed.\n\n"
        f"IMPORTANT: Write your response as plain text — a clear summary of your "
        f"findings, review, or analysis. Do NOT use cards, interactive elements, "
        f"or rich formatting. This text will be posted to the group chat."
    )

    message = "\n\n".join(prompt_parts)

    cmd = ["openclaw"]
    if profile and profile != "default":
        cmd.extend(["--profile", profile])
    cmd.extend(["agent", "--session-id", session_id, "--message", message, "--json"])

    agent_reply = ""
    success = False

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0 and result.stdout:
            try:
                json_start = result.stdout.find("{")
                if json_start >= 0:
                    data = json.loads(result.stdout[json_start:])
                    for p in data.get("result", {}).get("payloads", []):
                        text = p.get("text", "")
                        if text:
                            agent_reply += text + "\n"
                    if not agent_reply:
                        summary = data.get("summary", "")
                        if summary and summary != "completed":
                            agent_reply = summary
            except (json.JSONDecodeError, ValueError):
                pass
            success = True
            print(f"  Agent {agent_name} responded ({len(agent_reply)} chars)", file=sys.stderr)
        else:
            print(f"  Agent {agent_name} failed (exit={result.returncode})", file=sys.stderr)
    except subprocess.TimeoutExpired:
        print(f"  Agent {agent_name} timeout", file=sys.stderr)
    except FileNotFoundError:
        print(f"  openclaw not found", file=sys.stderr)

    # Fallback: extract from board work log
    if success and not agent_reply.strip() and BOARD_DIR.exists():
        for f in sorted(BOARD_DIR.glob("*.md"), reverse=True):
            try:
                content = f.read_text(encoding="utf-8")
                entries = re.findall(
                    r"### " + re.escape(agent_name) + r".+?\n(.*?)(?=\n### |\n## |\Z)",
                    content, re.DOTALL,
                )
                if entries and len(entries[-1].strip()) > 20:
                    agent_reply = entries[-1].strip()
                    break
            except OSError:
                continue

    # Forward to group
    if agent_reply and agent_reply.strip():
        forward_msg = agent_reply.strip()
        if len(forward_msg) > 4000:
            forward_msg = forward_msg[:4000] + "\n...(truncated)"

        fwd_cmd = ["openclaw"]
        if profile and profile != "default":
            fwd_cmd.extend(["--profile", profile])
        fwd_cmd.extend([
            "message", "send", "--channel", channel,
            "--account", "main", "--target", group_id,
            "--message", forward_msg,
        ])
        try:
            fwd_result = subprocess.run(fwd_cmd, capture_output=True, text=True, timeout=30)
            if fwd_result.returncode == 0:
                print(f"  Forwarded to {channel}:{group_id}", file=sys.stderr)
            else:
                print(f"  Forward failed: {fwd_result.stderr[:100]}", file=sys.stderr)
        except Exception as e:
            print(f"  Forward error: {e}", file=sys.stderr)
    else:
        print(f"  No reply to forward", file=sys.stderr)

    return success


def run_decisions(config: dict):
    state = _load_state()

    # Import judge
    judge = None
    if config.get("judge"):
        try:
            scripts_dir = Path(__file__).parent
            sys.path.insert(0, str(scripts_dir))
            from judge import create_judge
            judge = create_judge(config)
        except ImportError as e:
            print(f"Judge import failed: {e}", file=sys.stderr)

    for group_id, group_cfg in config.get("groups", {}).items():
        channel = group_cfg.get("provider", "feishu")
        all_agents = group_cfg.get("agents", [])
        messages = _read_messages(group_id)

        if not messages:
            continue

        context_str = _format_context(messages)
        triggered = False

        # Strategy 1: LLM Judge (primary)
        if judge and not triggered:
            recent = messages[-10:]
            decision = judge.decide(recent, all_agents)

            if decision:
                trigger_name = decision["trigger"]
                reason = decision.get("reason", "")
                task = decision.get("task", "")
                agent_cfg = _find_agent_config(trigger_name, all_agents)

                if agent_cfg:
                    trigger_key = f"{group_id}:{agent_cfg['name']}"
                    triggered_for = state.get("triggered_for", {})
                    last_trigger_reason = triggered_for.get(trigger_key, "")

                    if last_trigger_reason != reason:
                        retries = state.get("retry_counts", {}).get(f"{trigger_key}:{reason}", 0)
                        if retries < MAX_RETRIES:
                            print(f"[{agent_cfg['name']}] Judge: {reason}")

                            success = trigger_and_forward(
                                agent_cfg["name"],
                                agent_cfg.get("profile", "default"),
                                agent_cfg.get("session_id", ""),
                                reason, task, context_str,
                                group_id, channel,
                            )

                            if success:
                                if "triggered_for" not in state:
                                    state["triggered_for"] = {}
                                state["triggered_for"][trigger_key] = reason
                                triggered = True
                            else:
                                if "retry_counts" not in state:
                                    state["retry_counts"] = {}
                                state["retry_counts"][f"{trigger_key}:{reason}"] = retries + 1

        # Strategy 2: Board TODO fallback (no LLM configured)
        if not judge and not triggered:
            for agent_cfg in all_agents:
                aliases = [agent_cfg["name"]] + agent_cfg.get("aliases", [])
                todos = _get_board_todos(aliases)
                if todos:
                    trigger_key = f"{group_id}:{agent_cfg['name']}"
                    todo_key = f"board:{todos[0]['task_id']}"
                    triggered_for = state.get("triggered_for", {})

                    if triggered_for.get(trigger_key) != todo_key:
                        todo_text = "\n".join(t for td in todos for t in td["todos"])
                        print(f"[{agent_cfg['name']}] Board TODO pending")

                        success = trigger_and_forward(
                            agent_cfg["name"],
                            agent_cfg.get("profile", "default"),
                            agent_cfg.get("session_id", ""),
                            "You have pending TODOs on the chalkboard",
                            todo_text, context_str,
                            group_id, channel,
                        )

                        if success:
                            if "triggered_for" not in state:
                                state["triggered_for"] = {}
                            state["triggered_for"][trigger_key] = todo_key
                            triggered = True
                            break

    _save_state(state)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Chalkboard Decision Engine v2.1")
    parser.add_argument("--config", required=True, help="Path to config.json")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Config not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    config = json.loads(config_path.read_text(encoding="utf-8"))
    run_decisions(config)


if __name__ == "__main__":
    main()
