---
name: chalkboard
description: "Multi-agent collaboration via shared Markdown files. USE WHEN: user asks multiple agents to work together, requests collaboration between bots, mentions 'bulletin board' or 'chalkboard', assigns a complex task that benefits from multiple perspectives, or when you see a cron reminder about pending TODOs. DON'T USE WHEN: simple single-agent tasks, casual chat, or when the user explicitly wants only you to handle something."
user-invocable: true
---

# Chalkboard — Multi-Agent Collaboration

Enables multiple OpenClaw agents to collaborate on tasks through shared Markdown files on the local filesystem. Since IM platforms prevent bots from seeing each other's messages, this skill uses files as the shared communication layer.

## How It Works

1. A task board is created (by user or any agent) as a Markdown file in the boards directory
2. Each agent reads the board, does its assigned work, and appends results to the work log
3. Agents update TODO status when they complete items
4. A cron job checks for pending TODOs and reminds agents periodically

## Commands

All commands use the `bb` CLI wrapper. If `bb` is not in PATH, use:
`python3 <skill-dir>/scripts/board.py <command>`.

### Create a new task

```bash
bb create \
  --title "Task title" \
  --goal "What needs to be accomplished" \
  --context "Relevant background info" \
  --assign agent-a,agent-b \
  --agent YOUR_AGENT_NAME \
  --priority normal
```

### List active tasks

```bash
bb list
```

### Read a task board

```bash
bb read TASK_ID
```

### Append your work to the log

```bash
bb log TASK_ID \
  --agent YOUR_AGENT_NAME \
  --content "Your findings, analysis, or work output here..."
```

### Mark a TODO as done

```bash
bb todo TASK_ID --done "partial match of the TODO description"
```

### Add a new TODO for another agent

```bash
bb todo TASK_ID --add "@agent-name: description of what they need to do"
```

### Check your pending TODOs

```bash
bb my-todos --agent YOUR_AGENT_NAME
```

### Mark task as complete and archive it

```bash
bb complete TASK_ID
```

## Rules (IMPORTANT)

1. **Always read the full task board before working on it** — understand the goal, context, and what others have done
2. **Append only** — never overwrite or edit another agent's work log entries
3. **Update TODOs** — mark your items as done when you complete them
4. **Leave notes for the next agent** — if your work produces insights or dependencies for others, mention it in your log entry
5. **Notify the user** — when you finish your part, tell the user in chat what you did and what's still pending
6. **Don't duplicate work** — if another agent already covered something (check the work log), build on their findings instead of redoing it
7. **When creating a task** — after creating, tell the user the task ID and suggest they notify the other agents

## Cron Integration

A cron job runs periodically to check for pending TODOs. When you receive a cron reminder about pending TODOs:
1. Read the referenced task board
2. Do the work described in your TODO
3. Log your results
4. Mark the TODO as done
5. If all TODOs are complete, mark the task as done

## Example Workflow

User says: "I need agent-a and agent-b to research X competitors, then agent-c synthesizes a strategy."

1. You (any agent) create the task:
   ```bash
   bb create \
     --title "X competitor research and strategy" \
     --goal "Research competitors, synthesize strategy" \
     --assign agent-a,agent-b,agent-c \
     --agent YOUR_NAME
   ```
2. Update the TODOs to be specific:
   ```bash
   bb todo TASK_ID --add "@agent-a: Research competitor market share"
   bb todo TASK_ID --add "@agent-b: Analyze competitor tech stacks"
   bb todo TASK_ID --add "@agent-c: Synthesize findings into strategy doc"
   ```
3. Tell the user: "Task created (TASK_ID). Please tell the other agents to check the board."
4. Each agent reads the board, does their work, logs results, marks TODOs done
5. Final agent marks the task complete
