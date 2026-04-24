from __future__ import annotations

from scripts.rule15_structural_gate import (
    FakeLLMState,
    _build_server_env,
    _extract_fake_llm_count,
    _fake_chat_completion_payload,
    _fake_content_for_request,
)


def test_fake_chat_completion_payload_is_openai_compatible() -> None:
    payload = _fake_chat_completion_payload("ok")
    assert payload["choices"][0]["message"]["content"] == "ok"
    assert payload["choices"][0]["finish_reason"] == "stop"
    assert payload["usage"]["total_tokens"] > 0


def test_build_server_env_points_volces_to_fake_llm() -> None:
    env = _build_server_env("http://127.0.0.1:19081/v1")
    assert env["HI_AGENT_LLM_MODE"] == "real"
    assert env["HI_AGENT_ENV"] == "dev"
    assert env["VOLCE_API_KEY"] == "structural-test-key"
    assert env["VOLCE_BASE_URL"] == "http://127.0.0.1:19081/v1"


def test_extract_fake_llm_count_reads_evidence() -> None:
    payload = {"fake_llm": {"request_count": 4}}
    assert _extract_fake_llm_count(payload) == 4


def test_fake_content_matches_memory_compressor_prompt() -> None:
    content = _fake_content_for_request(
        {"messages": [{"content": "You are a memory compression engine."}]}
    )
    assert '"findings"' in content
    assert '"outcome"' in content


def test_fake_content_matches_skill_extractor_prompt() -> None:
    content = _fake_content_for_request(
        {"messages": [{"content": "expert at identifying reusable execution patterns"}]}
    )
    assert content == "[]"


def test_fake_llm_state_starts_at_zero() -> None:
    state = FakeLLMState()
    assert state.request_count == 0


def test_structural_gate_evidence_payload_shape() -> None:
    payload = {
        "status": "passed",
        "runs": [
            {"run_id": "run-1", "final_state": "completed", "fallback_events": []}
        ],
        "cancel_known": {"status_code": 200},
        "cancel_unknown": {"status_code": 404},
        "fake_llm": {"request_count": 3},
    }
    assert _extract_fake_llm_count(payload) == 3
    assert payload["runs"][0]["final_state"] == "completed"
    assert payload["cancel_known"]["status_code"] == 200
    assert payload["cancel_unknown"]["status_code"] == 404
