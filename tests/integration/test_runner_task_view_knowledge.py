"""Integration test for runner task-view knowledge enrichment."""

from hi_agent.contracts import TaskContract
from hi_agent.memory.l0_raw import RawMemoryStore
from hi_agent.runner import RunExecutor

from tests.helpers.kernel_adapter_fixture import MockKernel


def test_runner_calls_knowledge_query_and_records_knowledge_in_task_view() -> None:
    """Runner should query knowledge and include it in task-view payload."""
    query_calls: list[tuple[str, int]] = []

    def _knowledge_query(*, query_text: str, top_k: int) -> list[str]:
        query_calls.append((query_text, top_k))
        return ["kb:rollback-playbook", "kb:migration-checklist"]

    contract = TaskContract(task_id="int-knowledge-001", goal="safe schema migration")
    kernel = MockKernel(strict_mode=True)
    executor = RunExecutor(
        contract,
        kernel,
        knowledge_query_fn=_knowledge_query,
        raw_memory=RawMemoryStore(),
    )

    result = executor.execute()

    assert result == "completed"
    assert query_calls, "knowledge query should be called at least once"
    assert any("safe schema migration" in call[0] for call in query_calls)
    assert all(call[1] == 3 for call in query_calls)
    assert any(
        view.get("knowledge") == ["kb:rollback-playbook", "kb:migration-checklist"]
        for view in kernel.task_views.values()
    )
