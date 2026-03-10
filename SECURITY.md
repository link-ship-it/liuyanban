# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in Chalkboard, please report it responsibly.

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, email: **link@mainfunc.ai**

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

We will acknowledge your report within 48 hours and aim to release a fix within 7 days for critical issues.

## Security Design

Chalkboard is designed with security in mind:

- **No hardcoded secrets** — API keys are loaded from environment variables via `.env` files
- **File permissions** — `.env` files should be `chmod 600` (owner-only read/write)
- **Local-only** — Chalkboard runs entirely on your machine; no data is sent to external servers (except LLM API calls for the judge)
- **No dependencies** — Zero external Python packages reduces supply chain risk

## Best Practices

1. **Never commit `.env` or `config.json`** — they contain API keys and credentials
2. **Use `api_key_env`** — point to environment variable names, not raw keys
3. **Restrict file permissions**: `chmod 600 ~/.chalkboard/.env`
4. **Review `config.json`** before sharing — it may contain app secrets

## Supported Versions

| Version | Supported |
|---------|-----------|
| 2.x     | Yes       |
| < 2.0   | No        |
