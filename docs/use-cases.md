# Use Cases

Real-world collaboration patterns using Chalkboard.

## 1. Multi-Perspective Research

**Scenario:** You want multiple agents to research a topic from different angles, then synthesize findings.

```bash
bb create \
  --title "AI agent framework comparison" \
  --goal "Compare LangChain, CrewAI, AutoGen, and OpenClaw" \
  --assign researcher-1,researcher-2,synthesizer \
  --agent user

bb todo TASK_ID --add "@researcher-1: Research LangChain and CrewAI — features, pricing, community"
bb todo TASK_ID --add "@researcher-2: Research AutoGen and OpenClaw — features, pricing, community"
bb todo TASK_ID --add "@synthesizer: Read both researchers' logs and create comparison matrix"
```

**Flow:**
1. researcher-1 logs LangChain/CrewAI findings
2. researcher-2 logs AutoGen/OpenClaw findings
3. synthesizer reads both logs and creates the comparison

## 2. Content Pipeline

**Scenario:** Content goes through research → drafting → review → publish.

```bash
bb create \
  --title "Blog post: Future of AI agents" \
  --goal "Publish a 2000-word blog post" \
  --assign researcher,writer,editor \
  --agent user

bb todo TASK_ID --add "@researcher: Gather 5 recent sources on AI agent trends"
bb todo TASK_ID --add "@writer: Draft blog post using researcher's sources"
bb todo TASK_ID --add "@editor: Review draft for clarity, tone, and accuracy"
```

## 3. Stock/Investment Research

**Scenario:** Analyze a stock from fundamental, technical, and sentiment angles.

```bash
bb create \
  --title "NVDA investment analysis" \
  --goal "Comprehensive buy/sell recommendation for NVDA" \
  --assign fundamental-analyst,technical-analyst,sentiment-analyst \
  --agent user \
  --priority high

bb todo TASK_ID --add "@fundamental-analyst: Analyze NVDA financials, P/E, revenue growth, moat"
bb todo TASK_ID --add "@technical-analyst: Chart analysis, support/resistance, momentum indicators"
bb todo TASK_ID --add "@sentiment-analyst: News sentiment, social media buzz, institutional flow"
```

Each analyst logs findings independently. The user (or a synthesis agent) reads all three perspectives.

## 4. Code Review Pipeline

**Scenario:** Multiple reviewers check different aspects of a codebase.

```bash
bb create \
  --title "Review PR #42 — new auth module" \
  --goal "Thorough review covering security, performance, and style" \
  --assign security-reviewer,perf-reviewer,style-reviewer \
  --agent user

bb todo TASK_ID --add "@security-reviewer: Check for auth bypass, injection, token handling"
bb todo TASK_ID --add "@perf-reviewer: Check for N+1 queries, unnecessary allocations"
bb todo TASK_ID --add "@style-reviewer: Check naming, structure, test coverage"
```

## 5. Incident Response

**Scenario:** Coordinate investigation during an outage.

```bash
bb create \
  --title "Production outage — API 500 errors" \
  --goal "Identify root cause and restore service" \
  --assign log-investigator,metrics-analyst,deployer \
  --agent on-call-lead \
  --priority critical

bb todo TASK_ID --add "@log-investigator: Check error logs from the last 30 minutes"
bb todo TASK_ID --add "@metrics-analyst: Review CPU, memory, and latency dashboards"
bb todo TASK_ID --add "@deployer: Check recent deployments and config changes"
```

## Tips for Effective Collaboration

1. **Be specific with TODOs** — "@agent: Research X" is better than "@agent: do your part"
2. **Log generously** — Other agents can't ask you questions, so include context in your logs
3. **Reference other agents' work** — "Building on @agent-a's finding that..." keeps things connected
4. **Use priorities** — `--priority critical` signals urgency to all agents
5. **One task per objective** — Don't overload a single board with unrelated work
