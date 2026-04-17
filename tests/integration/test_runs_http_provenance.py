"""Layer 3 E2E: execution_provenance in HTTP /runs response — HI-W1-D3-001.

Requires a running server. Skip in CI unless server is started externally.
"""
import pytest


@pytest.mark.skip(reason="Layer 3 E2E test — requires running server; run manually with a live AgentServer instance")
class TestRunsHttpProvenance:
    """Verify execution_provenance is present in the HTTP /runs result payload."""

    def test_provenance_in_run_result(self, http_client):  # type: ignore[no-untyped-def]
        """POST /runs → execution_provenance dict must appear in result."""
        from hi_agent.contracts.execution_provenance import CONTRACT_VERSION

        resp = http_client.post("/runs", json={"goal": "test provenance shape"})
        assert resp.status_code == 201
        run_id = resp.json()["run_id"]

        # Poll for completion (adapt poll helper from test_prod_e2e if needed)
        import time
        for _ in range(30):
            r = http_client.get(f"/runs/{run_id}")
            assert r.status_code == 200
            data = r.json()
            if data.get("state") in {"completed", "failed"}:
                break
            time.sleep(1)

        result = data.get("result", {})
        prov = result.get("execution_provenance")
        assert prov is not None
        assert prov.get("contract_version") == CONTRACT_VERSION
        expected_keys = {
            "contract_version", "runtime_mode", "llm_mode", "kernel_mode",
            "capability_mode", "mcp_transport", "fallback_used",
            "fallback_reasons", "evidence",
        }
        assert set(prov.keys()) == expected_keys
