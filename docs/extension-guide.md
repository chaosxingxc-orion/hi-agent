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

Restart `hi-agent serve`. The tool appears at `GET /tools`.

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

Restart hi-agent. The MCP tools appear automatically in `GET /tools`.

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

## Configuring from a custom directory

By default, `hi-agent` reads `tools.json` and `mcp_servers.json` from the `config/` directory
in the source checkout. Wheel-installed deployments (or downstream developers who cannot modify
the source tree) can point to a different directory:

```bash
HI_AGENT_CONFIG_DIR=/my/config python -m hi_agent serve
```

Or pass it explicitly on the CLI:

```bash
python -m hi_agent serve --config-dir /my/config
python -m hi_agent run --local --config-dir /my/config --goal "..."
```

The directory must contain `tools.json` and/or `mcp_servers.json` in the same format documented
above. Files that do not exist are silently ignored — you only need the files you want to
customise.

## JSON profile files

Profiles can be loaded from a directory of JSON files instead of registering them in Python:

```bash
HI_AGENT_PROFILE_DIR=/my/profiles python -m hi_agent serve
```

Each `*.json` file in the directory is loaded as a `ProfileSpec`. Minimal format:

```json
{
  "profile_id": "my_research",
  "display_name": "My Research Profile",
  "stage_actions": {"S1_plan": "search", "S3_synthesize": "synthesize"},
  "required_capabilities": ["web_search"]
}
```

## Opt-in strict mode for `project_id` and `profile_id`

By default, `POST /runs` accepts requests without `project_id` or `profile_id` (and falls back
to unscoped / `"default"` with a warning log and metric counter). For deployments that need to
enforce these fields:

```bash
# Reject POST /runs with no project_id with HTTP 400
HI_AGENT_PROJECT_ID_REQUIRED=1 python -m hi_agent serve

# Reject POST /runs with no profile_id with HTTP 400
HI_AGENT_PROFILE_ID_REQUIRED=1 python -m hi_agent serve
```

When `HI_AGENT_PROJECT_ID_REQUIRED` is not set, the existing `X-Project-Warning: unscoped`
header behaviour is preserved. When `HI_AGENT_PROFILE_ID_REQUIRED` is not set, the existing
`"default"` fallback behaviour is preserved. Existing callers that do not set these env vars
are unaffected.

## Security notes

- **Never commit `config/llm_config.json`** — it contains API keys. Use env vars instead:
  `HI_AGENT_VOLCES_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`
- `config/tools.json` and `config/mcp_servers.json` are safe to commit (no secrets).
- Shell tool handlers run with `shell=False` — only whitelisted `allowed_args` are passed.

## Validating your config

```bash
python scripts/validate_config.py config/tools.json
python scripts/validate_config.py config/mcp_servers.json

---

## Plugging an External Knowledge Graph Backend

hi-agent's knowledge graph tier uses `JsonGraphBackend` (backed by a JSON
file) by default.  Downstream applications can substitute a different backend
— such as Neo4j — by implementing the `KnowledgeGraphBackend` protocol from
`hi_agent.memory.graph_backend`.

### Step 1: Implement the protocol

```python
from hi_agent.memory.graph_backend import (
    ConflictReport,
    Edge,
    KnowledgeGraphBackend,
    Path,
)


class Neo4jGraphBackend:
    def __init__(self, uri: str, auth: tuple) -> None:
        import neo4j
        self._driver = neo4j.GraphDatabase.driver(uri, auth=auth)

    def upsert_node(self, node_id: str, payload: dict) -> None:
        # ... Cypher MERGE
        pass

    def upsert_edge(self, src: str, dst: str, relation: str, payload: dict) -> None:
        # ... Cypher MERGE relationship
        pass

    def query_relation(self, node_id: str, relation: str, direction: str) -> list[Edge]:
        # ... Cypher MATCH
        return []

    def transitive_query(self, start: str, relation: str, max_depth: int) -> list[Path]:
        # ... Cypher variable-length path query
        return []

    def detect_conflict(self, claim_a: str, claim_b: str) -> ConflictReport | None:
        # ... check for 'contradicts' relationship
        return None

    def export_visualization(self, format: str) -> str:
        # ... export GraphML or Cytoscape JSON
        return "{}"
```

### Step 2: Verify the protocol is satisfied

```python
from hi_agent.memory.graph_backend import KnowledgeGraphBackend

backend = Neo4jGraphBackend(uri="bolt://localhost:7687", auth=("neo4j", "password"))
assert isinstance(backend, KnowledgeGraphBackend)  # runtime_checkable Protocol
```

### Step 3: Wire via builder

In your application's startup code, pass the backend instance wherever
`LongTermMemoryGraph` would normally be constructed.  The platform builder
(`hi_agent.config.builder.SystemBuilder`) constructs the default
`LongTermMemoryGraph`; to override, subclass `SystemBuilder` and override
`build_knowledge_manager()`:

```python
from hi_agent.config.builder import SystemBuilder
from hi_agent.memory.long_term import LongTermConsolidator


class CustomSystemBuilder(SystemBuilder):
    def __init__(self, config, kg_backend) -> None:
        super().__init__(config)
        self._kg_backend = kg_backend

    def build_knowledge_manager(self, profile_id: str, workspace_key, **kwargs):
        # Return your custom backend instead of LongTermMemoryGraph
        return self._kg_backend
```

**Note:** The default injection point is
`hi_agent/config/builder.py:build_knowledge_manager()`.  Full builder-level
`graph_backend=` kwarg support is deferred to Wave 9.

### Default backend reference

`JsonGraphBackend` is an alias for
`hi_agent.memory.long_term.LongTermMemoryGraph`.  All existing imports of
`LongTermMemoryGraph` continue to work unchanged.

```python
from hi_agent.memory.long_term import JsonGraphBackend, LongTermMemoryGraph

assert JsonGraphBackend is LongTermMemoryGraph  # True
```
