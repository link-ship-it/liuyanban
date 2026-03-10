#!/usr/bin/env python3
"""
Chalkboard Poller — Fetches group chat messages from IM platforms.

Supports Feishu and Telegram. Stores messages in append-only JSONL files
so all agents can see the full conversation (including other bots' messages).

Usage:
  python3 poller.py --config ~/.chalkboard/config.json
  python3 poller.py --provider feishu --group oc_xxx --app-id cli_xxx --app-secret xxx
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CONTEXT_DIR = Path(os.environ.get("CHALKBOARD_CONTEXT_DIR", os.path.expanduser("~/.chalkboard/context")))
STATE_FILE = Path(os.environ.get("CHALKBOARD_STATE_DIR", os.path.expanduser("~/.chalkboard"))) / "poller_state.json"


def _ensure_dirs():
    CONTEXT_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _context_file(group_id: str) -> Path:
    safe_id = group_id.replace("/", "_").replace(":", "_")
    return CONTEXT_DIR / f"group-{safe_id}.jsonl"


def _load_seen_ids(group_id: str) -> set:
    state = _load_state()
    return set(state.get("seen_ids", {}).get(group_id, []))


def _save_seen_id(group_id: str, msg_id: str):
    state = _load_state()
    if "seen_ids" not in state:
        state["seen_ids"] = {}
    if group_id not in state["seen_ids"]:
        state["seen_ids"][group_id] = []
    ids = state["seen_ids"][group_id]
    if msg_id not in ids:
        ids.append(msg_id)
    if len(ids) > 200:
        state["seen_ids"][group_id] = ids[-200:]
    state["last_poll"] = time.time()
    _save_state(state)


def _append_message(group_id: str, msg: dict):
    path = _context_file(group_id)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(msg, ensure_ascii=False) + "\n")


def _trim_context(group_id: str, max_lines: int = 100):
    """Keep only the last N lines in the context file."""
    path = _context_file(group_id)
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    if len(lines) > max_lines:
        path.write_text("\n".join(lines[-max_lines:]) + "\n", encoding="utf-8")


# ── Feishu Provider ──────────────────────────────────────────────────────


class FeishuProvider:
    """Polls messages from a Feishu group chat using the Open API."""

    TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    MESSAGES_URL = "https://open.feishu.cn/open-apis/im/v1/messages"

    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self._token = ""
        self._token_expires = 0

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expires - 60:
            return self._token

        payload = json.dumps({"app_id": self.app_id, "app_secret": self.app_secret}).encode()
        req = urllib.request.Request(
            self.TOKEN_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
            self._token = resp.get("tenant_access_token", "")
            self._token_expires = time.time() + resp.get("expire", 7200)
            return self._token
        except (urllib.error.URLError, json.JSONDecodeError, KeyError) as e:
            print(f"Feishu token error: {e}", file=sys.stderr)
            return ""

    def poll(self, group_id: str, since_ts: int = 0) -> list:
        """Fetch recent messages from a Feishu group chat."""
        token = self._get_token()
        if not token:
            return []

        params = f"?container_id_type=chat&container_id={group_id}&page_size=20"
        if since_ts:
            params += f"&start_time={since_ts}"

        req = urllib.request.Request(
            self.MESSAGES_URL + params,
            headers={"Authorization": f"Bearer {token}"},
        )
        try:
            resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
        except (urllib.error.URLError, json.JSONDecodeError) as e:
            print(f"Feishu poll error: {e}", file=sys.stderr)
            return []

        if resp.get("code") != 0:
            print(f"Feishu API error: {resp.get('msg', 'unknown')}", file=sys.stderr)
            return []

        messages = []
        for item in resp.get("data", {}).get("items", []):
            msg_id = item.get("message_id", "")
            sender_info = item.get("sender", {})
            sender_id = sender_info.get("id", "")
            sender_type = sender_info.get("sender_type", "user")
            is_bot = sender_type == "app"

            body = item.get("body", {})
            content_raw = body.get("content", "{}")
            try:
                content_obj = json.loads(content_raw)
                text = content_obj.get("text", content_raw)
            except json.JSONDecodeError:
                text = content_raw

            create_time = item.get("create_time", "0")
            try:
                ts = int(create_time) // 1000 if len(create_time) > 10 else int(create_time)
            except (ValueError, TypeError):
                ts = int(time.time())

            messages.append({
                "ts": ts,
                "sender": f"{'bot' if is_bot else 'user'}:{sender_id}",
                "sender_name": sender_id,
                "is_bot": is_bot,
                "content": text,
                "msg_id": msg_id,
                "provider": "feishu",
            })

        return messages


# ── Telegram Provider ────────────────────────────────────────────────────


class TelegramProvider:
    """Polls messages from a Telegram group chat using getUpdates."""

    API_BASE = "https://api.telegram.org"

    def __init__(self, bot_token: str):
        self.bot_token = bot_token
        self._offset = 0

    def poll(self, group_id: str, since_ts: int = 0) -> list:
        """Fetch recent messages from a Telegram group."""
        url = f"{self.API_BASE}/bot{self.bot_token}/getUpdates?timeout=1&allowed_updates=[\"message\"]"
        if self._offset:
            url += f"&offset={self._offset}"

        try:
            resp = json.loads(urllib.request.urlopen(url, timeout=5).read())
        except (urllib.error.URLError, json.JSONDecodeError) as e:
            print(f"Telegram poll error: {e}", file=sys.stderr)
            return []

        if not resp.get("ok"):
            return []

        messages = []
        target_id = str(group_id)

        for update in resp.get("result", []):
            self._offset = update.get("update_id", 0) + 1
            msg = update.get("message", {})
            chat = msg.get("chat", {})
            chat_id = str(chat.get("id", ""))

            if chat_id != target_id:
                continue

            from_user = msg.get("from", {})
            is_bot = from_user.get("is_bot", False)
            sender_name = from_user.get("first_name", "") or from_user.get("username", "")
            text = msg.get("text", "")

            if not text:
                continue

            messages.append({
                "ts": msg.get("date", int(time.time())),
                "sender": f"{'bot' if is_bot else 'user'}:{from_user.get('id', '')}",
                "sender_name": sender_name,
                "is_bot": is_bot,
                "content": text,
                "msg_id": str(msg.get("message_id", "")),
                "provider": "telegram",
            })

        return messages


# ── Main ─────────────────────────────────────────────────────────────────


def poll_group(provider, group_id: str) -> int:
    """Poll a group and store new messages. Returns count of new messages."""
    _ensure_dirs()
    seen = _load_seen_ids(group_id)
    state = _load_state()
    last_ts = int(state.get("last_ts", {}).get(group_id, 0))

    messages = provider.poll(group_id, since_ts=last_ts)
    new_count = 0

    for msg in messages:
        msg_id = msg.get("msg_id", "")
        if msg_id in seen:
            continue
        _append_message(group_id, msg)
        _save_seen_id(group_id, msg_id)
        new_count += 1

        msg_ts = msg.get("ts", 0)
        if msg_ts > last_ts:
            last_ts = msg_ts

    if last_ts:
        state = _load_state()
        if "last_ts" not in state:
            state["last_ts"] = {}
        state["last_ts"][group_id] = last_ts
        _save_state(state)

    _trim_context(group_id, max_lines=100)
    return new_count


def read_context(group_id: str, last_n: int = 20) -> list:
    """Read the last N messages from a group's context file."""
    path = _context_file(group_id)
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    messages = []
    for line in lines[-last_n:]:
        try:
            messages.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return messages


def format_context(messages: list) -> str:
    """Format context messages into a human-readable string for agent injection."""
    lines = []
    for msg in messages:
        name = msg.get("sender_name", "unknown")
        bot_tag = " [bot]" if msg.get("is_bot") else ""
        text = msg.get("content", "")
        lines.append(f"{name}{bot_tag}: {text}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Chalkboard Poller — fetch group chat messages")
    parser.add_argument("--config", default="", help="Path to chalkboard config.yaml")
    parser.add_argument("--provider", choices=["feishu", "telegram"], help="IM provider")
    parser.add_argument("--group", default="", help="Group chat ID")
    parser.add_argument("--app-id", default="", help="Feishu App ID")
    parser.add_argument("--app-secret", default="", help="Feishu App Secret")
    parser.add_argument("--bot-token", default="", help="Telegram bot token")
    parser.add_argument("--context", action="store_true", help="Print recent context and exit")
    parser.add_argument("--last", type=int, default=20, help="Number of recent messages to show")

    args = parser.parse_args()

    if args.context and args.group:
        msgs = read_context(args.group, args.last)
        print(format_context(msgs))
        return

    if args.config:
        try:
            import yaml
            cfg = yaml.safe_load(Path(args.config).read_text())
        except ImportError:
            cfg = json.loads(Path(args.config).read_text())
        for gid, gcfg in cfg.get("groups", {}).items():
            prov = gcfg.get("provider", "feishu")
            if prov == "feishu":
                feishu_cfg = cfg.get("feishu", {})
                provider = FeishuProvider(feishu_cfg["app_id"], feishu_cfg["app_secret"])
            elif prov == "telegram":
                tg_cfg = cfg.get("telegram", {})
                provider = TelegramProvider(tg_cfg["bot_token"])
            else:
                continue
            n = poll_group(provider, gid)
            if n > 0:
                print(f"[{prov}:{gid}] {n} new message(s)")
        return

    if not args.provider or not args.group:
        parser.print_help()
        sys.exit(1)

    if args.provider == "feishu":
        if not args.app_id or not args.app_secret:
            print("Error: --app-id and --app-secret required for feishu", file=sys.stderr)
            sys.exit(1)
        provider = FeishuProvider(args.app_id, args.app_secret)
    elif args.provider == "telegram":
        if not args.bot_token:
            print("Error: --bot-token required for telegram", file=sys.stderr)
            sys.exit(1)
        provider = TelegramProvider(args.bot_token)
    else:
        sys.exit(1)

    n = poll_group(provider, args.group)
    if n > 0:
        print(f"{n} new message(s)")


if __name__ == "__main__":
    main()
