# Tasks: ZelerData Read-Model Freshness Guards

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: High

Estimated: 1200–1450 across PR 1 → PR 8 (each slice ≤400). Recovery: PR #1 (844) and S4 (454) rejected; resliced — S4a ~300, S4b ~90, S4c ~55.

### Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| S1 | Inventory + validation | PR 1 (base=tracker) | `uv run pytest tests/test_read_model_freshness_writer.py` | N/A: unit tests; live DB excluded | Remove core writer + test |
| S2 | Generic upsert + session + concurrency | PR 2 (base=PR 1) | `uv run pytest tests/test_read_model_freshness_writer.py` | N/A: same | Revert S2 additions |
| S3 | Devoluciones lease-guarded transitions | PR 3 (base=PR 2) | `uv run pytest tests/test_read_model_freshness_writer.py` | N/A: same | Revert S3 additions |
| S4a | Report core: 17 rows, exact keys, sanitized output, summary | PR 4 (base=PR 3) | `uv run pytest tests/operations/test_zelerdata_read_model_status.py` | N/A: report fn via fake collection in tests; no deploy | Remove report core + tests |
| S4b | Productive-window gates + deterministic actions | PR 5 (base=PR 4) | `uv run pytest tests/operations/test_zelerdata_read_model_status.py` | N/A: same | Revert S4b additions |
| S4c | CLI: parser, argv validation pre-DB, JSON output | PR 6 (base=PR 5) | `uv run pytest tests/operations/test_zelerdata_read_model_status.py` | N/A: `main(argv, db)` in tests; no deploy | Revert S4c additions |
| S5 | Readiness + main() contract | PR 7 (base=PR 6) | `uv run pytest tests/operations/test_zelerdata_read_model_status.py` | N/A: same | Revert S5 additions |
| S6 | Docs + final verification | PR 8 (base=PR 7) | `uv run pytest tests/test_read_model_freshness_writer.py tests/operations/test_zelerdata_read_model_status.py` | N/A: no runtime change | Revert 2 doc links |

## Phase 1: Core writer (TDD) — S1–S3

- [x] 1.1 [S1] RED: inventory contract — reconcile `READ_MODELS` + `devoluciones` == core 17 names
- [x] 1.2 [S1] RED: reject `reconciled`/unknown `target_state` (ValueError, pre-DB)
- [x] 1.3 [S1] RED: reject unapproved runtime, unknown read_model/source pre-DB
- [x] 1.8a [S1] GREEN: create `core/src/zeler_platform_core/read_model_freshness.py` — inventory, allowlists, validation-only entry, passing 1.1–1.3
- [x] 1.4 [S2] RED: upsert `stale`/`failed` at exact `(seller_id, read_model)`, `$$NOW`, `source="operator-action"`
- [x] 1.5 [S2] RED: fails closed without session/transaction support
- [x] 1.6 [S2] RED: same-pair concurrency — unique-index serialize, one bounded retry, valid final state
- [x] 1.8b [S2] GREEN: add `_set_generic_state`, `_marker_transition_pipeline`, `_start_session` + wire entry, passing 1.4–1.6
- [x] 1.7 [S3] RED: devoluciones — `stale`→`invalidate_devoluciones_readiness`, `failed`→`guarded_devoluciones_write` + expiry; foreign/lost lease fails pre-write
- [x] 1.8c [S3] GREEN: add devoluciones dispatch (`_set_devoluciones_state`, `_set_devoluciones_failed`), passing 1.7

## Phase 2: Status CLI (TDD) — S4a–S4c, S5

- [x] 2.1 [S4a] RED: full/empty → 17 rows, exact keys, `missing`
- [x] 2.2 [S4a] RED: seller_id/`_id`/extra excluded; malformed/unknown-source degrade (`source: null`)
- [ ] 2.3 [S4b] RED: `in_productive_window` only on productive evidence
- [ ] 2.4 [S4b] RED: actions `none` / `await_lease` (missing questions) / `re_run_reconcile`
- [ ] 3.1 [S4c] Wire CLI to core inventory import (no duplicated list); 1.1 parity test locks it
- [x] 2.6a [S4a] GREEN: create report core in `infra/operations/zelerdata_read_model_status.py` — projected query, 17-row synthesis, summary, sanitization (no argv/JSON yet); passing 2.1–2.2
- [ ] 2.6c [S4b] GREEN: extend window gates (source-gated legacy basis, devoluciones `valid_until`) + action map; passing 2.3–2.4
- [ ] 2.6d [S4c] GREEN: add `validate_status_argv`, parser, `main(argv, db)` JSON output; passing 3.1 + argv tests
- [ ] 2.5 [S5] RED: readiness `ready`/`degraded` + `blocking`; `main(argv)` twice → one read, zero writes; nonzero exit; sanitized errors
- [ ] 2.6b [S5] GREEN: add readiness + `main()` contract, passing 2.5

## Phase 3: Docs and verification — S6

- [ ] 3.2 [S6] Cross-link status command in `docs/sheets/zelerdata-formulas.md`
- [ ] 3.3 [S6] Document unwired-model operator guidance in `docs/ops/zelerdata-seller-data-matrix-rollout.md`
- [ ] 3.4 [S6] Verify: S6 pytest command + `uv run ruff check .` + `uv run mypy core/src/zeler_platform_core/read_model_freshness.py infra/operations/zelerdata_read_model_status.py`

Index guard: rely on existing unique `(seller_id, read_model)`; never alter schema/indexes. B1 stays blocked (no workaround).

Threat matrix: all rows N/A (no shell/subprocess/VCS); no RED tests required.
