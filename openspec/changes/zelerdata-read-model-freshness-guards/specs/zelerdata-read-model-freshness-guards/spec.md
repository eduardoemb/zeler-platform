# Read-Model Freshness Guards Specification

## Purpose

Define sanitized, fail-closed reporting and guarded generic transitions to `stale` or `failed` for ZelerData read-model freshness markers.

## Requirements

### Requirement: Report covers every read model

The system MUST emit one row per read model.

#### Scenario: Complete marker set

- GIVEN all 17 markers exist
- WHEN the status report is generated
- THEN the output contains 17 rows, one per model

#### Scenario: Empty marker collection

- GIVEN `sheets_read_model_freshness` is empty
- WHEN the status report is generated
- THEN the output contains 17 rows with `state: "missing"`

### Requirement: Report output is sanitized

The system MUST include only contracted fields and MUST NOT expose seller_id, `_id`, raw documents, tokens, credentials, or environment values.

#### Scenario: Extra fields are filtered

- GIVEN a marker contains seller_id, `_id`, and extra metadata
- WHEN the report is generated
- THEN the output excludes those fields and contains only contracted fields

### Requirement: Productive window and readiness are fail-closed

The system MUST set `in_productive_window` to `true` only when `state` is `fresh` or `reconciled` and the coverage window includes now. The system MUST report `ready` only when all rows have `action_recommended: "none"`.

#### Scenario: Fully productive seller

- GIVEN all markers are `reconciled` with current coverage
- WHEN the readiness summary is emitted
- THEN `status` is `"ready"` and `blocking` is empty

#### Scenario: Stale marker blocks readiness

- GIVEN one marker is `stale`
- WHEN the readiness summary is emitted
- THEN `status` is `"degraded"` and `blocking` lists the stale read model

### Requirement: Recommended actions are deterministic

The system MUST map state to action per the contract: missing reconciled models → `re_run_reconcile`; missing `questions` → `await_lease`; `stale`/`failed` → `re_run_reconcile`; productive → `none`.

#### Scenario: Missing questions marker

- GIVEN `questions` has no marker
- WHEN the report is generated
- THEN `action_recommended` is `"await_lease"`

### Requirement: Writer accepts only non-productive states

The system MUST reject `target_state` values outside `{stale, failed}` before DB access and MUST NOT set productive time ranges.

#### Scenario: Valid stale transition

- GIVEN `approved_runtime=True` and `target_state="stale"`
- WHEN the writer is called for a non-devoluciones read model
- THEN the marker is upserted with `state: "stale"`

#### Scenario: Reconciled target rejected

- GIVEN `target_state="reconciled"`
- WHEN the writer is called
- THEN a `ValueError` is raised before DB access

### Requirement: Writer enforces runtime approval and devoluciones authority

The system MUST require `approved_runtime=True` for non-devoluciones writes and fail closed before DB access if false. The system MUST delegate `devoluciones` transitions to the existing lease-guarded invalidation path.

#### Scenario: Unapproved runtime rejected

- GIVEN `approved_runtime=False`
- WHEN the writer is called for `catalog_buybox_snapshots`
- THEN an exception is raised before any database write

#### Scenario: Devoluciones uses lease path

- GIVEN `read_model="devoluciones"` and `target_state="stale"`
- WHEN the writer is called
- THEN `invalidate_devoluciones_readiness` is invoked and the generic upsert path is not used

### Requirement: Writer stores transition metadata

The system MUST perform non-devoluciones writes inside a Mongo session, set `fresh_until`, `valid_until`, and `updated_at` to now, and record the provided `source`.

#### Scenario: Failed marker stores metadata

- GIVEN `target_state="failed"` and `source="operator-action"`
- WHEN the writer completes
- THEN the marker has `state: "failed"`, current timestamps, and `source: "operator-action"`

### Requirement: Concurrent writes are serialized

The system MUST rely on the unique index on `(seller_id, read_model)` to serialize concurrent transitions and leave the marker valid.

#### Scenario: Concurrent stale and failed writes

- GIVEN two concurrent calls target the same `(seller_id, read_model)`
- WHEN both complete
- THEN the marker ends in one valid requested state

### Requirement: Hard exclusions remain in force

The system MUST NOT introduce schedulers, timers, cloud changes, per-read-model automatic writers, schema/index changes, campaign logic, credential handling, or production access.

#### Scenario: Change boundary review

- GIVEN the implementation is reviewed
- THEN no scheduler, timer, cloud deployment, schema change, or credential code is present
