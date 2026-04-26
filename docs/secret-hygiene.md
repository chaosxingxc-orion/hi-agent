# Secret Hygiene — hi-agent API Key Workflow

## The Problem

`config/llm_config.json` is tracked by git (needed for CI key injection). Real API keys must
never be committed. This document describes the workflow to keep them out of git history.

## Local Development Workflow

1. Copy the example file:
   ```bash
   cp config/llm_config.example.json config/llm_config.json
   ```

2. Fill in your real API key in `config/llm_config.json`.

3. Protect from accidental commits:
   ```bash
   git update-index --skip-worktree config/llm_config.json
   ```
   This tells git to ignore local changes to this file without adding it to .gitignore.

4. To temporarily re-expose for a legitimate config structure change:
   ```bash
   git update-index --no-skip-worktree config/llm_config.json
   # make structural changes (not key values)
   git add config/llm_config.json
   git commit
   git update-index --skip-worktree config/llm_config.json
   ```

## CI Workflow

In CI, `scripts/inject_volces_key.py` reads the key from environment and writes it to
`config/llm_config.json` for the duration of the test run. It restores the file on exit.

```bash
VOLCES_KEY=your_key python scripts/inject_volces_key.py
```

## Pre-commit Hook

Install the hook to automatically block commits with secrets:
```bash
cp scripts/git_hooks/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

## What check_secrets.py Detects

- Non-empty `api_key` fields in `config/llm_config.json`
- UUID-like values in key fields in delivery JSONs
- High-entropy strings in suspicious contexts in delivery docs

Run manually: `python scripts/check_secrets.py`
