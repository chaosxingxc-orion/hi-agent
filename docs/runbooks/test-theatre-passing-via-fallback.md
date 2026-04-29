# Runbook: Test Theatre -- Test Passes via Fallback

## Symptom
A test passes but the feature under test is actually falling back to a mock or degraded mode. Common patterns: SUT-internal mock in an integration test, wide terminal-state acceptance (`error` counted as success), vacuous assertions (`assert True`).

## Cause
Integration test mocks the SUT's internal implementation class instead of only mocking network/external boundaries.

## Resolution
1. Identify the test using `check_test_honesty.py` or `check_vacuous_asserts.py`.
2. Replace the SUT-internal mock with a real in-process fixture (echo LLM, pass-through invoker), OR re-label the test as `tests/unit/`.
3. Replace wide terminal-state sets with `SUCCESS_STATES = {"done", "completed"}`.
4. Replace `assert True` with a concrete assertion on the observable output.

## Prevention
`check_test_honesty.py` and `check_vacuous_asserts.py` are CI gates that block on these patterns.
