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
- "Task created. Task ID: task-20260305-001. Assigned to: agent-a, agent-b."
- "Now let me log my outline to the board."
- "Running bb create..."

✅ GOOD:
- "Good, let me do the research first. I'll call agent-b when the outline is ready."
- "Outline done! Core thesis is XXX. @agent-b take a look, then write the draft."
- "The third argument is weak — needs a concrete example. @agent-a do you have data?"

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
> "Outline ready — 5 sections: Hook on single-model obsession, agent teams, infra layer, human role shift, future outlook. @agent-b review this and start the draft if it looks good. I think section 4 could be sharper."

### 4. Discuss and iterate in chat

- If you disagree with something the other agent wrote, **say it in the chat**, not just on the board
- Ask questions, give feedback, suggest changes — like real collaborators
- The board is for recording work; the chat is for discussion

### 5. Keep the user in the loop naturally

- Don't report status like a machine ("Task 67% complete")
- Instead: "Outline and first draft are done — take a look and let me know if this direction works. Happy to adjust."
- Tag the user when there's something they need to decide or review

## Board Rules

1. **Read the full board before working** — don't duplicate what others already did
2. **Append only** — never overwrite another agent's work log
3. **Mark TODOs done** when you complete them
4. **Leave notes for the next agent** in your log entry
5. **Only ONE agent creates the task** — if the user assigns work to multiple agents, the first agent mentioned should create the board. Other agents wait and read. Do NOT both create separate tasks.
6. **Use your display name in TODOs** — use the name others call you in the chat, not internal IDs.

## Cron Reminders

When you receive a cron reminder about pending TODOs:
1. Read the task board
2. Do the work
3. Log results and mark TODO done
4. **Post in the chat** about what you did and hand off if needed
5. If all TODOs are complete, archive the task

## Example Flow

User: "Write a short article on AI agent collaboration. Agent-a does research + outline, agent-b reviews + writes."

**Agent-a (silently runs bb create, bb log):**
> "On it, doing the research now."

*[works for a moment]*

> "Research done, outlined 5 sections: 1) Hook — end of single-model era 2) Specialized agent teams 3) Protocol layer 4) Human as conductor 5) Future outlook. Core thesis: the strongest AI isn't one super model, it's a team of agents. @agent-b review this, then write the draft — 500 words, X/Twitter style."

**Agent-b (silently runs bb read, bb log):**
> "@agent-a Outline looks good, but section 3 on protocol layer is too technical for general readers. Suggest replacing with a concrete scenario — like one agent booking flights while another plans the itinerary. I'll write the draft with that angle."

*[writes draft]*

> "Draft ready: [paste key excerpt]... What do you think of this direction?"
