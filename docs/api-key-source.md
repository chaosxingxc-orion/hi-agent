# API Key Source

All LLM API keys are read from `config/llm_config.json`. Environment variables
(including `VOLCE_API_KEY`) are no longer consulted by hi-agent runtime.

## For developers

Populate `config/llm_config.json` with your API key:

```json
{
  "providers": {
    "volces": {
      "api_key": "your-key-here"
    }
  }
}
```

## For CI

The CI workflow injects the key into `config/llm_config.json` at job start
using `scripts/inject_provider_key.py --provider volces`. No `VOLCE_API_KEY` env var is needed
in application code.
