# Runbook: Cross-Tenant Primitive Footgun

## Symptom
A route in `NO_SCOPE_ALLOWLIST` with `risk: high` has no tenant-isolation test, OR a knowledge/skill route processes data without validating `tenant_id` matches the caller.

## Cause
High-risk routes (knowledge ingest/sync, skill optimize/promote) were allowlisted without accompanying isolation tests.

## Resolution
1. Identify which high-risk route was triggered.
2. Check if a `test_route_<name>_tenant_isolation.py` exists and passes.
3. If not, author the isolation test: tenant A creates resource, tenant B asserts 404.
4. After test is green, remove the route from `NO_SCOPE_ALLOWLIST`.

## Prevention
7 tenant-isolation tests gate the 7 high-risk routes. `check_route_scope.py` blocks ship on any high-risk expiring entry without a replacement_test.
