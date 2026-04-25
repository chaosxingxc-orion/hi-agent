# T3 Concurrency Gate Evidence

Date: 2026-04-25
SHA: fa98c7b
Runs: 20
Pass: 0 | Fail: 20

## Results
- FAIL e6d997a3-bc16-4679-84eb-6a74caa5bee7 state=created fallback=0 finished_at=null
- FAIL d6b5fae0-7a49-467b-b596-a529704a6da9 state=created fallback=0 finished_at=null
- FAIL 6bfaa1be-34e8-4f72-ba23-2118898088b3 state=created fallback=0 finished_at=null
- FAIL b844cc55-6266-4193-bc32-01d9efdbcd06 state=failed fallback=0 finished_at=null
- FAIL 662aa31c-8c5c-47ed-bcbb-61fcad2a4f7d state=failed fallback=0 finished_at=null
- FAIL 953ffc3a-875a-4901-be6d-486daaa5317e state=failed fallback=0 finished_at=null
- FAIL 7d06725c-27bd-4b14-bdba-4d4d705affc6 state=failed fallback=0 finished_at=null
- FAIL b2e196e4-7936-465f-a690-a80654453ecc state=failed fallback=0 finished_at=null
- FAIL fa1b29aa-3499-462f-b722-e6da8aab810b state=failed fallback=0 finished_at=null
- FAIL e69c1a85-6918-4be0-90ff-ded84b230b16 state=failed fallback=0 finished_at=null
- FAIL 72290873-52da-4453-a6d9-fef4c88135a0 state=failed fallback=0 finished_at=null
- FAIL 29999d51-95ed-4b1a-b7fa-a95a8c5e2859 state=failed fallback=0 finished_at=null
- FAIL 209eb76f-7d7c-46e1-8368-d552f9a0daf5 state=failed fallback=0 finished_at=null
- FAIL 266c73ab-d6fe-4d9e-abb7-41aaaba5d5aa state=failed fallback=0 finished_at=null
- FAIL bdd75007-e044-488f-b426-dcd99b887f4b state=failed fallback=0 finished_at=null
- FAIL 73b53faf-cf04-49a3-8950-8c08ae7e2fde state=failed fallback=0 finished_at=null
- FAIL 2187a4a4-c9d0-4cfa-81b4-4aecaa6918b0 state=failed fallback=0 finished_at=null
- FAIL 14fba732-864c-4909-b9d6-0f2233f83111 state=failed fallback=0 finished_at=null
- FAIL dde32740-62fd-45b3-9b2a-5e5667a1fc2a state=failed fallback=0 finished_at=null
- FAIL 7253cd46-05fd-4f8b-9b93-55858ac5ad5e state=failed fallback=0 finished_at=null

## Phase 2 — Idempotent Dedupe Contention

Key: gate-dedupe-1777100665
Concurrent requests: 5
Distinct run_ids: 5 (expected 1)
HTTP 201 (created): 5
HTTP 200 (replayed): 0
Result: FAIL
