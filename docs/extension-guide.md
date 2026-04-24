# hi-agent Extension Guide

This guide shows how to extend hi-agent by editing config files — no Python code required for HTTP tools and MCP servers.

## Adding a custom HTTP tool

Edit `config/tools.json`:

```json
{
  "version": "1.0",
  "tools": [
    {
      "name": "my_echo_tool",
      "description": "Echoes the input back",
      "timeout_s": 10,
      "handler": {
        "type": "http",
        "url": "http://localhost:9000/echo",
        "method": "POST"
      },
      "input_schema": {
        "type": "object",
        "properties": {
          "message": {"type": "string"}
        }
      }
    }
  ]
}
```

Restart `hi-agent serve`. The tool appears at `GET /capabilities`.

## Registering an MCP server

Edit `config/mcp_servers.json`:

```json
{
  "version": "1.0",
  "servers": [
    {
      "name": "my_filesystem_mcp",
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp/data"],
      "health_check": {"interval_s": 60, "timeout_s": 5}
    }
  ]
}
```

Restart hi-agent. The MCP tools appear automatically in `GET /capabilities`.

**HTTP/SSE transport:**
```json
{
  "name": "my_remote_mcp",
  "transport": "http",
  "endpoint": "http://my-mcp-host:3000/mcp"
}
```

## Adding a skill (markdown)

Place a `SKILL.md` file anywhere under `~/.hi_agent/skills/`:

```
~/.hi_agent/skills/my_skill/SKILL.md
```

Minimal format:
```markdown
# My Skill Name
A short description.

## Usage
Explain when to use this skill.

## Steps
1. Step one
2. Step two
```

Skills are auto-discovered at startup — no config file needed.

## Configuring high-concurrency deployments

In `hi_agent_config.json` (or `HI_AGENT_*` env vars):

```json
{
  "run_manager": {
    "max_concurrent": 16,
    "queue_size": 64
  }
}
```

## Security notes

- **Never commit `config/llm_config.json`** — it contains API keys. Use env vars instead:
  `HI_AGENT_VOLCES_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`
- `config/tools.json` and `config/mcp_servers.json` are safe to commit (no secrets).
- Shell tool handlers run with `shell=False` — only whitelisted `allowed_args` are passed.

## Validating your config

```bash
python scripts/validate_config.py config/tools.json
python scripts/validate_config.py config/mcp_servers.json
```
