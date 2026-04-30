"""Operator drill v2 - five real-fault scenarios (W24 Track G, RIA H-11).

This package replaces the 6-action smoke-test operator drill v1 with five
scenarios that exercise the failure paths an operator must actually handle:

  1. ``stuck_run``        - run that ceases progressing; operator-visible stall
  2. ``provider_outage``  - LLM provider unavailable; degraded path observable
  3. ``db_contention``    - slow/locked SQLite; throughput recovers
  4. ``restart_mid_run``  - server termination mid-run; restart re-attaches
  5. ``slo_burn``         - sustained latency that should burn an SLO budget

Each scenario module exposes:

  - ``SCENARIO_NAME`` (str)
  - ``SCENARIO_DESCRIPTION`` (str)
  - ``run_scenario(base_url: str, timeout: float = 60.0) -> dict``

The result dict carries at least::

    {
      "name": SCENARIO_NAME,
      "passed": bool,
      "provenance": "real" | "simulated_pending_pm2",
      "duration_s": float,
      "notes": str,
      "evidence": { ... per-scenario ... }
    }

Provenance is "real" when the scenario actually injected the fault into a live
process and observed the operator-visible signal. It is
"simulated_pending_pm2" when the platform-level fault (e.g. real SIGTERM of a
PM2-managed worker) cannot be exercised in-process and the scenario instead
records the structural evidence that mirrors what a real drill would produce.
This is by design: better partial-real than fake-full-real.

The driver in ``scripts/run_operator_drill.py --version 2`` aggregates all five
scenario results into a single evidence file under ``docs/verification/<head>-
operator-drill-v2.json``. The check gate ``scripts/check_operator_drill.py
--json`` reads the latest evidence and emits PASS only when ``version==2``
and ``5/5`` scenarios passed.
"""
from __future__ import annotations

SCENARIO_MODULES = (
    "stuck_run",
    "provider_outage",
    "db_contention",
    "restart_mid_run",
    "slo_burn",
)
"""Canonical scenario order - the driver iterates in this sequence."""
