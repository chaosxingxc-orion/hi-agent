"""Tests for agent_server contract dataclasses."""
from __future__ import annotations

import importlib
import inspect

import pytest
from agent_server.contracts.errors import (
    AuthError,
    ConflictError,
    ContractError,
    NotFoundError,
    QuotaError,
    RuntimeContractError,
)
from agent_server.contracts.memory import MemoryReadKey, MemoryTierEnum
from agent_server.contracts.run import RunRequest
from agent_server.contracts.tenancy import TenantContext
from agent_server.contracts.workspace import ContentHash


def test_tenant_context_requires_tenant_id():
    with pytest.raises(TypeError):
        TenantContext()  # tenant_id required


def test_tenant_context_frozen():
    from dataclasses import FrozenInstanceError

    ctx = TenantContext(tenant_id="t1")
    with pytest.raises(FrozenInstanceError):
        ctx.tenant_id = "t2"  # type: ignore  # expiry_wave: Wave 30


def test_run_request_requires_tenant_id():
    with pytest.raises(TypeError):
        RunRequest(profile_id="p1", goal="do something")


def test_run_request_frozen():
    from dataclasses import FrozenInstanceError

    req = RunRequest(tenant_id="t1", profile_id="p1", goal="do something")
    with pytest.raises(FrozenInstanceError):
        req.goal = "changed"  # type: ignore  # expiry_wave: Wave 30


def test_memory_tier_enum_values():
    assert MemoryTierEnum.L0.value == "L0"
    assert MemoryTierEnum.L3.value == "L3"


def test_memory_read_key_requires_tenant_id():
    with pytest.raises(TypeError):
        MemoryReadKey(tier=MemoryTierEnum.L0)


def test_content_hash_short_property():
    ch = ContentHash(algorithm="sha256", hex_digest="abcdef1234567890" + "0" * 48)
    assert len(ch.short) == 16
    assert ch.short == "abcdef1234567890"


def test_blob_ref_requires_tenant_id():
    from agent_server.contracts.workspace import BlobRef

    with pytest.raises(TypeError):
        BlobRef(content_hash=ContentHash("sha256", "a" * 64))


def test_llm_request_requires_tenant_id_and_run_id():
    from agent_server.contracts.llm_proxy import LLMRequest

    with pytest.raises(TypeError):
        LLMRequest(messages=({"role": "user", "content": "hi"},))


def test_error_hierarchy():
    err = AuthError("unauthorized", tenant_id="t1")
    assert isinstance(err, ContractError)
    assert err.http_status == 401
    assert err.tenant_id == "t1"


def test_quota_error_status():
    assert QuotaError.http_status == 429


def test_conflict_error_status():
    assert ConflictError.http_status == 409


def test_not_found_error_status():
    assert NotFoundError.http_status == 404


def test_runtime_contract_error_does_not_shadow_builtin():
    # RuntimeContractError must not shadow Python's RuntimeError
    assert RuntimeContractError is not RuntimeError
    err = RuntimeContractError("oops")
    assert isinstance(err, ContractError)


def test_no_domain_vocabulary_in_contracts():
    """Confirm no forbidden domain types appear in any contracts module."""
    forbidden = {
        "Paper",
        "Phase",
        "Hypothesis",
        "Theorem",
        "PIAgent",
        "Survey",
        "Analysis",
        "Experiment",
        "Writing",
        "Author",
        "Reviewer",
        "Editor",
        "Backtrack",
        "Citation",
        "Lean",
        "Dataset",
    }
    modules = [
        "agent_server.contracts.tenancy",
        "agent_server.contracts.run",
        "agent_server.contracts.skill",
        "agent_server.contracts.memory",
        "agent_server.contracts.workspace",
        "agent_server.contracts.gate",
        "agent_server.contracts.llm_proxy",
        "agent_server.contracts.streaming",
        "agent_server.contracts.errors",
    ]
    for mod_name in modules:
        mod = importlib.import_module(mod_name)
        src = inspect.getsource(mod)
        for name in forbidden:
            assert name not in src, f"Forbidden domain type {name!r} found in {mod_name}"


def test_contracts_stdlib_only():
    """Confirm no pydantic, httpx, starlette, or fastapi in contracts."""
    forbidden_imports = ["pydantic", "httpx", "starlette", "fastapi"]
    modules = [
        "agent_server.contracts.tenancy",
        "agent_server.contracts.run",
        "agent_server.contracts.skill",
        "agent_server.contracts.memory",
        "agent_server.contracts.workspace",
        "agent_server.contracts.gate",
        "agent_server.contracts.llm_proxy",
        "agent_server.contracts.streaming",
        "agent_server.contracts.errors",
    ]
    for mod_name in modules:
        mod = importlib.import_module(mod_name)
        src = inspect.getsource(mod)
        for imp in forbidden_imports:
            assert imp not in src, f"Forbidden import {imp!r} found in {mod_name}"
