"""Version constants for agent_server.

W31-N (N.8): ``V1_FROZEN_HEAD`` is reconciled with the
``v1_frozen_head`` field of ``docs/governance/contract_v1_freeze.json``.
``check_contract_freeze.py --enforce`` now asserts the two values agree
and ``--snapshot`` overwrites this constant unconditionally so the next
freeze re-snapshot keeps the two in sync.
"""
API_VERSION = "v1"
SCHEMA_VERSION = "1.0"
V1_RELEASED = True
V1_RELEASED_AT = "2026-04-30"
# Filled by: python scripts/check_contract_freeze.py --snapshot
V1_FROZEN_HEAD = "55e51a7f4e3c67ffd0b9cfb53608ac3bdd3c8266"
