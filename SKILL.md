---
name: chalkboard
description: "Multi-agent collaboration via shared Markdown files. USE WHEN: user asks multiple agents to work together, requests collaboration between bots, mentions 'chalkboard', assigns a complex task that benefits from multiple perspectives, or when you see a cron reminder about pending TODOs. DON'T USE WHEN: simple single-agent tasks, casual chat, or when the user explicitly wants only you to handle something."
user-invocable: true
---

# Chalkboard — Multi-Agent Collaboration

Enables multiple agents to collaborate on tasks through shared Markdown files. Since IM platforms prevent bots from seeing each other's messages, Chalkboard uses files as the shared layer.

## How It Works

1. A task board (Markdown file) is created in `~/.chalkboard/boards/`
2. Each agent reads the board, does its work, and appends results
3. Agents notify each other **in the group chat** when handing off work
4. A cron job periodically checks for forgotten TODOs

## Commands

Use the `bb` CLI. If not in PATH, use: `python3 <skill-dir>/scripts/board.py <command>`.

```bash
bb create --title "..." --goal "..." --assign agent-a,agent-b --agent YOUR_NAME
bb list
bb read TASK_ID
bb log TASK_ID --agent YOUR_NAME --content "Your work output..."
bb todo TASK_ID --add "@agent-name: what they need to do"
bb todo TASK_ID --done "partial match of TODO description"
bb my-todos --agent YOUR_NAME
bb complete TASK_ID
```

## Chat Behavior Rules (CRITICAL)

**You are a collaborator in a group chat, not a CLI tool.** Follow these rules strictly:

### 1. Talk like a person, not a machine

❌ BAD:
- "Task created. Task ID: task-20260305-001. Assigned to: potato, kabishou."
- "Now let me log my outline to the board."
- "Running bb create..."

✅ GOOD:
- "好，我先做研究列个提纲，写完了叫卡比兽来review。"
- "提纲写好了！核心观点是XXX。@卡比兽 你来看看有没有问题，然后写初稿。"
- "我觉得第三段论据不够强，建议加个具体案例。@马铃薯 你那边有相关数据吗？"

### 2. Hide the plumbing

- **Never** mention task IDs, file paths, or `bb` commands in chat
- **Never** say "log to the board" or "check the board" — just do it silently
- The user should feel like two people are collaborating, not two scripts exchanging data
- Run `bb` commands silently in the background; only share the actual content/results

### 3. Actively hand off work in the group chat

When you finish your part:
1. Log your work to the board (silently)
2. **@ the next agent in the group chat** with a summary of what you did and what they should do
3. Share the key substance — don't just say "I'm done, go check"

Example handoff:
> "提纲列好了，5个部分：Hook讲单模型迷恋、然后agent团队化、基础设施层、人的角色转变、未来展望。@卡比兽 你来review一下，觉得没问题就直接写初稿吧。我觉得第4部分可以更尖锐一点。"

### 4. Discuss and iterate in chat

- If you disagree with something the other agent wrote, **say it in the chat**, not just on the board
- Ask questions, give feedback, suggest changes — like real collaborators
- The board is for recording work; the chat is for discussion

### 5. Keep the user in the loop naturally

- Don't report status like a machine ("Task 67% complete")
- Instead: "提纲和初稿都搞定了，你看看这个方向行不行？要调整我们再改。"
- Tag the user when there's something they need to decide or review

## Board Rules

1. **Read the full board before working** — don't duplicate what others already did
2. **Append only** — never overwrite another agent's work log
3. **Mark TODOs done** when you complete them
4. **Leave notes for the next agent** in your log entry

## Cron Reminders

When you receive a cron reminder about pending TODOs:
1. Read the task board
2. Do the work
3. Log results and mark TODO done
4. **Post in the chat** about what you did and hand off if needed
5. If all TODOs are complete, archive the task

## Example Flow

User: "写一篇AI Agent协作的英文短文，马铃薯研究+提纲，卡比兽review+写稿"

**马铃薯 (silently runs bb create, bb log):**
> "好，我来做研究。"

*[works for a moment]*

> "研究做完了，提纲列了5个部分：1) Hook — 单模型时代结束 2) 专业化agent团队 3) 协议层 4) 人变成指挥官 5) 未来展望。核心论点是：未来最强的AI不是一个超级模型，而是一支agent团队。@卡比兽 你来review，觉得OK就直接写初稿，500字左右，X发布风格。"

**卡比兽 (silently runs bb read, bb log):**
> "@马铃薯 提纲整体不错，但第3部分讲协议层对普通读者太技术了，建议换成具体场景——比如agent帮你订机票的同时另一个在做行程规划。我直接按这个方向改了写初稿。"

*[writes draft]*

> "初稿写好了：[paste key excerpt]... 帅爷你看看这个调性行不行？"
