# Posture Reference

hi-agent supports three deployment postures that control enforcement strictness,
backend durability, and schema validation behavior. Choose your posture based
on the lifecycle stage of your deployment.

---

## The Three Postures

### dev

**Purpose**: Local development and smoke testing. Enforces nothing strictly.
Missing `project_id`, `profile_id`, or durable backends produce warnings
(logged and counted) but do not block requests.

Use when: iterating on the platform locally, running CI smoke tests, or
exploring capabilities without a full operator setup.

### research

**Purpose**: Multi-user research environments where reproducibility and
auditability matter. `project_id` and `profile_id` are enforced;
run history and artifacts persist across server restarts.

Use when: a research team is running experiments and needs to correlate
runs to projects, retrieve past artifacts, and share results.

### prod

**Purpose**: Production deployments. Identical enforcement to research,
with stricter defaults: evolve mode off, real LLM required, kernel URL required.

Use when: the platform is serving production traffic or downstream research
pipelines that depend on stable, authenticated, auditable runs.

---

## Feature Table

| Feature / Capability | `dev` default | `research` default | `prod` default |
|----------------------|--------------|-------------------|----------------|
| `project_id` enforcement | warn + `X-Project-Warning` header | **required** (400 if missing) | **required** (400 if missing) |
| `profile_id` enforcement | warn + fallback to `"default"` | **required** (400 if missing) | **required** (400 if missing) |
| Run queue backend | in-memory | durable SQLite | durable SQLite |
| Artifact ledger | in-memory | durable file | durable file |
| Team run registry | in-memory | durable SQLite | durable SQLite |
| Profile schema validation | warn + skip | fail-closed (400) | fail-closed (400) |
| Idempotency scope | body `tenant_id` | auth `tenant_id` | auth `tenant_id` |
| LLM mode | heuristic fallback allowed | real LLM recommended | real LLM required |
| Evolve mode default | `auto` | `auto` | `off` |
| `HI_AGENT_DATA_DIR` required | no | **yes** (doctor blocking check) | **yes** (doctor blocking check) |

---

## How to Set Posture

```bash
export HI_AGENT_POSTURE=research
```

Valid values: `dev`, `research`, `prod`. The server and CLI both read
`HI_AGENT_POSTURE` at startup. Invalid values are rejected with a clear
error message.

To verify the active posture:

```bash
hi-agent doctor --json | python -m json.tool | grep -A3 '"posture"'
```

---

## How to Set the Data Directory

```bash
export HI_AGENT_DATA_DIR=/var/hi_agent
```

Under `research` and `prod` postures, `HI_AGENT_DATA_DIR` is required. The
`hi-agent doctor` command reports this as a **blocking** issue if unset.

The data directory stores:

| Subdirectory | Contents |
|-------------|---------|
| `runs/` | Durable run state (SQLite) |
| `artifacts/` | Artifact files keyed by project and run |
| `idempotency/` | Idempotency key store (SQLite, WAL mode) |
| `team_registry/` | Team run registry (SQLite) |

The directory must be writable by the server process. Create it and set
permissions before starting the server:

```bash
mkdir -p /var/hi_agent
chmod 700 /var/hi_agent
export HI_AGENT_DATA_DIR=/var/hi_agent
```

---

## Migration from dev to research posture

Use this checklist when promoting a deployment from `dev` to `research`:

- [ ] Set `HI_AGENT_POSTURE=research`
- [ ] Set `HI_AGENT_DATA_DIR` to a durable, writable directory
- [ ] Run `hi-agent doctor` and resolve all blocking issues before starting the server
- [ ] Set `HI_AGENT_PROJECT_ID_REQUIRED=1` to enforce project scoping
- [ ] Set `HI_AGENT_PROFILE_ID_REQUIRED=1` to enforce profile scoping
- [ ] Update all callers of `POST /runs` to supply `project_id` and `profile_id`
- [ ] Verify `GET /runs/{run_id}` returns the same state after a server restart
- [ ] Set `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` for real LLM mode
- [ ] Run `hi-agent init --posture research --config-dir ./my_config` to get a reference config

---

## Migration from research to prod posture

Additional steps beyond the research checklist:

- [ ] Set `HI_AGENT_POSTURE=prod`
- [ ] Set `HI_AGENT_LLM_MODE=real`
- [ ] Set `HI_AGENT_KERNEL_BASE_URL` to your kernel endpoint
- [ ] Set `HI_AGENT_EVOLVE_MODE=off` (or leave unset — prod default is `off`)
- [ ] Run the Rule 8 operator-shape gate and record evidence in `docs/delivery/`
- [ ] Configure PM2/systemd for process supervision (do not use foreground `python -m hi_agent serve`)

---

## Legacy Tenantless Artifact Policy

Artifacts written before tenant scoping was introduced (Wave 8 / CO-5) may have
`tenant_id=""` or omit the field entirely. hi-agent applies a posture-aware
policy when these artifacts are encountered during query or retrieval:

| Posture | Legacy artifact visible? | Signal emitted |
|---------|--------------------------|----------------|
| `dev` | Yes — visible to any authenticating tenant | `DEBUG` log + `hi_agent_legacy_tenantless_artifact_visible_total` counter incremented |
| `research` | No — denied | `WARNING` log with `artifact_id` + `tenant_requested`; `hi_agent_legacy_tenantless_artifact_denied_total` counter incremented |
| `prod` | No — denied | Same as research |

Under `research` and `prod` postures, a legacy tenantless artifact is
**never returned** to any tenant and is excluded from all list/query results.
This prevents accidental cross-tenant data leakage from pre-migration records.

### Migrating legacy tenantless artifacts

Use the built-in migration command to assign a tenant to all tenantless records
in the durable ledger:

```bash
# Preview affected rows without modifying the file
hi-agent artifacts migrate-tenant \
    --tenant-id <your-tenant-id> \
    --data-dir /var/hi_agent \
    --dry-run

# Apply the migration
hi-agent artifacts migrate-tenant \
    --tenant-id <your-tenant-id> \
    --data-dir /var/hi_agent
```

Options:

| Flag | Required | Description |
|------|----------|-------------|
| `--tenant-id TEXT` | yes | Target tenant to assign to all tenantless rows |
| `--project-id TEXT` | no | Also assign this project_id to rows that lack one |
| `--data-dir PATH` | no (reads `HI_AGENT_DATA_DIR`) | Directory containing `artifacts.jsonl` |
| `--dry-run` | no | Print count of affected rows without modifying the file |

After migration, all previously tenantless artifacts carry `tenant_id=<your-tenant-id>`
and will be visible to that tenant under all postures. No existing non-empty
`tenant_id` values are overwritten.
