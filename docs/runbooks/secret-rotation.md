# Secret Rotation Runbook

## When to rotate

- Immediately after T3 live gate run (Volces API key)
- After any accidental commit that might have included a key
- On schedule: every 90 days for production keys

## Volces API Key

1. Go to the Volces console (contact team for URL)
2. Generate a new API key under your project
3. Update the environment variable `OPENAI_API_KEY` (pointed at Volces endpoint)
4. Verify T3 gate: `python scripts/run_t3_gate.py --provider volces --runs 1`
5. Revoke the old key in Volces console
6. Note: never commit this key to the repository

Affected endpoints: all LLM calls via `hi_agent/llm/http_gateway.py`

## Anthropic API Key

1. Go to console.anthropic.com
2. Generate a new API key
3. Update `ANTHROPIC_API_KEY` environment variable
4. Verify: `python -c "import anthropic; c=anthropic.Anthropic(); print('ok')"`
5. Revoke the old key

Affected endpoints: Claude models used in `hi_agent/llm/http_gateway.py` when provider=anthropic

## OpenAI API Key

Similar process — rotate at platform.openai.com.

## Verification after rotation

Run the T3 gate to confirm the new key works:
```bash
OPENAI_API_KEY=$NEW_KEY python scripts/run_t3_gate.py --provider volces --runs 1
```

Never store keys in:
- Repository files (even in comments)
- Docker images
- CI logs
- CLAUDE.md or any documentation
