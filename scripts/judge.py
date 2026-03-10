#!/usr/bin/env python3
"""
Chalkboard Judge — LLM-powered decision engine for multi-agent coordination.

Reads recent chat messages and decides which agent (if any) should be triggered.
Pluggable provider design: Anthropic, OpenAI, or any OpenAI-compatible endpoint.

Usage:
    from judge import create_judge
    judge = create_judge(config)
    result = judge.decide(messages, agents)
    # result = {"trigger": "agent-b", "reason": "...", "task": "review research"}
"""

import json
import os
import urllib.error
import urllib.request
from typing import Optional

SYSTEM_PROMPT = """You are a coordinator for a group of AI agents in a chat room.
Your job is to read the recent chat messages and decide if any agent needs to be triggered to act NOW.

RULES:
1. Only trigger an agent if another agent or human EXPLICITLY asked it to do something (review, research, check, etc.)
2. Do NOT trigger if the request is old — look at timestamps, only act on the MOST RECENT conversation
3. Do NOT trigger if the agent already responded to this specific request (check if there's a reply after the request)
4. If multiple agents are mentioned, only trigger the one that should act NEXT (not all of them)
5. If no action is needed, return null

Respond with ONLY valid JSON, no markdown, no explanation:
{"trigger": "agent_name_or_null", "reason": "one sentence why", "task": "what the agent should do"}

If no agent needs to act:
{"trigger": null, "reason": "no action needed", "task": null}"""


def _build_prompt(messages: list, agents: list) -> str:
    """Build the user prompt with agent list and recent messages."""
    parts = ["Agents in this group:"]
    for a in agents:
        aliases = ", ".join(a.get("aliases", []))
        alias_str = f" (aliases: {aliases})" if aliases else ""
        parts.append(f"- {a['name']}{alias_str}")

    parts.append("\nRecent messages (newest last):")
    for msg in messages:
        ts = msg.get("ts", 0)
        from datetime import datetime
        time_str = datetime.fromtimestamp(ts).strftime("%H:%M") if ts else "??:??"
        name = msg.get("sender_name", "?")
        bot = " [bot]" if msg.get("is_bot") else ""
        text = msg.get("content", "")
        if text == "请升级至最新版本客户端，以查看内容":
            text = "(card message — content not available via API)"
        if len(text) > 300:
            text = text[:300] + "..."
        parts.append(f"[{time_str}] {name}{bot}: {text}")

    parts.append("\nWhich agent (if any) should be triggered to act NOW?")
    return "\n".join(parts)


class AnthropicJudge:
    """Judge using Anthropic Messages API."""

    API_URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, model: str = "claude-opus-4-6", api_key: str = ""):
        self.model = model
        self.api_key = api_key

    def decide(self, messages: list, agents: list) -> Optional[dict]:
        if not self.api_key:
            return None

        user_prompt = _build_prompt(messages, agents)
        payload = json.dumps({
            "model": self.model,
            "max_tokens": 200,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_prompt}],
        }).encode()

        req = urllib.request.Request(
            self.API_URL,
            data=payload,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )

        try:
            resp = json.loads(urllib.request.urlopen(req, timeout=30).read())
            text = resp.get("content", [{}])[0].get("text", "")
            return _parse_response(text)
        except (urllib.error.URLError, json.JSONDecodeError, KeyError, IndexError) as e:
            print(f"Judge error (anthropic): {e}", file=__import__("sys").stderr)
            return None


class OpenAIJudge:
    """Judge using OpenAI Chat Completions API (also works with compatible endpoints)."""

    def __init__(self, model: str = "gpt-4o-mini", api_key: str = "",
                 base_url: str = "https://api.openai.com/v1"):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def decide(self, messages: list, agents: list) -> Optional[dict]:
        if not self.api_key:
            return None

        user_prompt = _build_prompt(messages, agents)
        payload = json.dumps({
            "model": self.model,
            "max_tokens": 200,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        }).encode()

        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

        try:
            resp = json.loads(urllib.request.urlopen(req, timeout=30).read())
            text = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
            return _parse_response(text)
        except (urllib.error.URLError, json.JSONDecodeError, KeyError, IndexError) as e:
            print(f"Judge error (openai): {e}", file=__import__("sys").stderr)
            return None


def _parse_response(text: str) -> Optional[dict]:
    """Parse LLM JSON response, handling markdown code blocks."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(l for l in lines if not l.startswith("```"))
    try:
        result = json.loads(text)
        trigger = result.get("trigger")
        if trigger and trigger != "null":
            return {
                "trigger": trigger,
                "reason": result.get("reason", ""),
                "task": result.get("task", ""),
            }
        return None
    except json.JSONDecodeError:
        return None


def create_judge(config: dict):
    """Create a judge instance from config.
    
    Config format:
    {
        "judge": {
            "provider": "anthropic" | "openai",
            "model": "claude-opus-4-6" | "gpt-4o-mini" | ...,
            "api_key_env": "ANTHROPIC_API_KEY" | "OPENAI_API_KEY",
            "base_url": "https://..." (optional, for OpenAI-compatible endpoints)
        }
    }
    """
    judge_cfg = config.get("judge", {})
    provider = judge_cfg.get("provider", "anthropic")
    model = judge_cfg.get("model", "claude-opus-4-6")
    api_key_env = judge_cfg.get("api_key_env", "ANTHROPIC_API_KEY")
    api_key = os.environ.get(api_key_env, "")

    if provider == "anthropic":
        return AnthropicJudge(model=model, api_key=api_key)
    elif provider == "openai":
        base_url = judge_cfg.get("base_url", "https://api.openai.com/v1")
        return OpenAIJudge(model=model, api_key=api_key, base_url=base_url)
    else:
        return AnthropicJudge(model=model, api_key=api_key)
