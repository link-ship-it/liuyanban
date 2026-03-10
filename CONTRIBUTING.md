# Contributing to Chalkboard

Thanks for your interest in contributing! Here's how to get started.

## Development Setup

```bash
git clone https://github.com/link-ship-it/chalkboard.git
cd chalkboard
# No dependencies to install — pure Python 3.8+ stdlib
python3 scripts/board.py --help
```

## How to Contribute

### Bug Reports

Open an [issue](https://github.com/link-ship-it/chalkboard/issues) with:
- What you expected to happen
- What actually happened
- Steps to reproduce
- Your environment (OS, Python version, OpenClaw version)

### Feature Requests

Describe your use case in an issue. We're especially interested in:
- New IM platform providers (Discord, Slack, WhatsApp)
- New board templates
- Better LLM judge prompts
- Cross-machine collaboration (Git-backed boards)

### Pull Requests

1. Fork the repo
2. Create a feature branch (`git checkout -b feat/my-feature`)
3. Make your changes
4. Test manually with `python3 scripts/board.py`
5. Commit with a clear message (`feat: add Discord provider`)
6. Push and open a PR

### Code Style

- Python 3.8+ compatible (no walrus operator, no match/case)
- Zero external dependencies (stdlib only for core scripts)
- Functions and variables in `snake_case`
- Clear docstrings for public functions

### Adding a New IM Provider

To add support for a new platform (e.g., Discord):

1. Add a new class in `scripts/poller.py` following `FeishuProvider` / `TelegramProvider` pattern
2. Implement `poll(group_id, since_ts)` that returns a list of message dicts
3. Add the provider to the factory in `poll_group()`
4. Update `config.example.yaml` with the new provider's config

### Adding a New LLM Provider

To add a new model provider for the judge:

1. Add a new class in `scripts/judge.py` following `AnthropicJudge` / `OpenAIJudge` pattern
2. Implement `decide(messages, agents)` that returns `{"trigger": "name", "reason": "...", "task": "..."}`
3. Add the provider to `create_judge()`

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
