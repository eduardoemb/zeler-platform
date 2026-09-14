# Inventory refresh cadence correction

Scope: task 7.3, existing refresh planner and supervisor only, plus its existing runtime factory.

The full six-model planner previously slept 900 seconds after each cycle. Inventory completion during this sleep could wait almost 900 seconds for readmission without sheet traffic. The same supervisor now wakes every 30 seconds to submit only ItemInventoryRecoveryRequest through the existing planner queue and allowlist. Active requests retain their deterministic key and coalesce in FormulaRecoveryQueue; completed requests reopen using the existing admission transaction. No Mercado Libre request is performed by a tick. Existing source pacing, budgets, TTLs, queue schema, and job lifecycle remain unchanged.

The full planner, observed markers, returns renewal, optional precalculation, alarms, and daily DLQ work retain the existing full-cycle cadence (900 seconds after completion by default). All scheduling uses monotonic elapsed time. There is one owned supervisor task; stop interrupts its wait and drains in-flight work. Admission is bounded by the planner's existing two-second timeout; one seller's error is isolated. As with the existing serial supervisor, slow seller discovery or a broad cycle can delay a tick; this is not a hard real-time deadline across unavailable storage.

RED: three inventory cadence tests failed before the behavior existed, and the runtime factory wiring assertion separately failed with inventory_refresher=None. Logs: /tmp/zeler-refresh-cadence-red.log and /tmp/zeler-refresh-factory-red.log.

GREEN: `uv run pytest modules/sheets/tests/test_refresh_inventory_cadence.py modules/sheets/tests/test_zelerdata_refresh.py -q -o addopts=''` => 60 passed in 0.40 seconds. The virtual-time regression observes inventory-only ticks at 30, 60, ... 870 seconds and full planner/returns callbacks only at 0 and 900 seconds. Tests also cover seller allowlist, request type/key, admission failure isolation, and stop/drain. Existing refresh tests preserve daily/full scheduling and runtime flags.

Focused ruff check, ruff format --check, and mypy for refresh.py and both test files passed. Full repository gates and independent review are root-owned and still pending. Production refresh enablement and the 90-minute simultaneous formula acceptance run remain pending; local tests are not live acceptance evidence.
