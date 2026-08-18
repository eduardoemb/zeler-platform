# Sheets DLQ reconciliation runbook

This runbook documents the one-shot, read-only, fail-closed capability that
classifies and plans the disposition of Sheets product dead-letter-queue (DLQ)
messages so duplicate Google Sheets rows are never created.

This document authorizes **no execution**. It does not authorize replay, purge,
delete, archive/terminal-close, deploy, restart, or any MongoDB/RabbitMQ
mutation. Every action is dry-run-first and requires a separate, explicit,
digest-bound human approval.

For the operative replay-publish runbook, see
[`docs/ops/webhook-backlog-replay.md`](webhook-backlog-replay.md). This
capability cross-references that runbook for replay; it does not replace it.

## Scope and intent

- Read-only DLQ snapshot classification with a clean, evidence-based plan.
- A closed action allowlist per class, so forged or skipped transitions fail
  closed.
- Digest-bound approvals that are re-validated immediately before execution.
- Pre-publish duplicate prevention that re-checks the exact scoped
  `processed_events` key.
- An append-only immutable ledger with hash-chain links.
- Fail-closed rollback and quarantine disposition that leave source messages
  untouched unless a separately authorized, proven adapter is bound.
- Rate, size, and action caps.

Out of scope: UI routes, new admin scopes, A5 poller/reboot persistence,
topology changes, deployment, and runtime operations (see "Scope boundary").

## Safety contract

- The tool is read-only and dry-run by default. It never opens a live broker or
  Mongo connection and launches no shell or subprocess.
- Without an explicit, non-expired, digest-bound approval whose plan digest,
  classification, action, and message fingerprint still match, no publish or
  mutation occurs.
- Only `replay_candidate` may publish replay, and only through exchange
  `zeler.sheets.replay` with concurrency `1` at a rate below `1` message/second.
- The exact scoped idempotency key and ledger state are re-checked immediately
  before publish. An active key, prior replay success, or unreconciled durable
  replay reservation blocks the publish.
- A durable replay reservation is appended before publish. Publisher confirm
  precedes source acknowledgement and the final success-ledger append. If that
  final append fails, the reservation remains blocking until explicit
  reconciliation proves no publish occurred.
- Rollback stops publishing and applies only the approved quarantine
  disposition to the remaining approved items. Without a usable adapter,
  rollback fails closed and appends nothing.
- Caps: snapshot ≤ 10,000 messages; actions ≤ 100/run; MongoDB ≤ 100
  writes/batch and ≤ 1 batch/second; reject oversize bodies.

## Classification

Every DLQ message resolves to exactly one fail-closed class using the
descending evidence hierarchy `processed_events`, `sheets_devoluciones_operations`,
`webhook_events`, logs, broker, then approved external evidence. Operations
success is corroboration only, because the Sheets handler finishes the
operation before the append.

| Class | Meaning | Allowed approved transitions | Forbidden |
|---|---|---|---|
| `already_applied` | Active exact scoped key | `terminal_close_archive` only | replay, quarantine, purge, delete |
| `terminal_upstream_404` | Identity-matched sanitized 404 | `quarantine` then `terminal_close_archive` | replay, direct close/archive, purge, delete |
| `unknown_append_outcome` | No conclusive success/failure | `quarantine_manual_review` only | replay, close/archive, purge, delete |
| `replay_candidate` | Valid source, enabled export, stable key, negative append proof | `approved_dry_run` then individually approved `replay` | batch/global replay, quarantine, purge, delete |

## Bounded snapshot adapter runbook

The bounded snapshot adapter
(`infra/operations/sheets_dlq_snapshot_adapter.py`) is a one-shot, read-only
surface that snapshots up to `K = SNAPSHOT_CAP = 24` distinct current DLQ
messages while they remain unacked, then nacks them in ascending delivery-tag
order. It ships **inactive by default**: importing it or invoking `main`
without injected broker/runtime ports contacts no live broker, Mongo, or
subprocess. Its purpose is bounded, privacy-preserving classification and it
uses the canonical `classify_and_sanitize_one` taxonomy from this capability.
It grants no execution authorization.

### Preconditions (fail closed)

- Run on the **authoritative host**. Exclusion is same-host only
  (`fcntl.flock` on an operator-supplied `--lock-path`); no cross-host
  exclusion is claimed.
- **Zero DLQ consumers**: the live queue inspection reports
  `consumers == 0` and the offline zero-consumer check passes.
- The **Sheets worker runtime is healthy**. Health confirms the worker probe
  responds; it does not require or assert an exact worker instance count.
- **No Mongo writes**: the adapter exposes no Mongo write path.

Any unmet precondition rejects the run before any `basic.get`.

### Privacy boundary and residuals

Up to 24 raw messages may reside only in the bounded in-memory buffer while the
run is live. Raw payload bytes, ids, credentials, and URIs never enter logs,
files, stdout, HTTP bodies, Mongo documents, or Engram observations. Accepted
residuals the adapter minimizes but cannot eliminate are library/process
memory, crash dumps, external tracing/debuggers, and `/proc/<pid>/mem`
inspection. Payload fingerprints are omitted by default and only emitted when
`--payload-fingerprint-sha256` is explicitly enabled.

### Honest nack outcomes and abort

Each nack records exactly one of `requeue_requested`, `requeue_send_failed`, or
`outcome_unknown`. The adapter **never claims broker confirmation of requeue**.
On `requeue_send_failed` or `outcome_unknown` it closes the channel and issues
no further gets or nacks. SIGINT/SIGTERM trigger a best-effort channel close so
unacked messages auto-requeue; abrupt death (SIGKILL, OOM, segfault) cannot emit
a completion claim and relies on AMQP connection termination to requeue.

### Authorization separation

Design or documentation approval of this adapter **does not authorize
execution or RabbitMQ delivery/requeue**. The first authorized run uses
`K = 24` and `SNAPSHOT_CAP = 24`; any future adjustment of `K` or the cap is a
separate explicit operator decision. No worker pause, topology mutation,
publish, replay, purge, delete, quarantine, disposition, deploy, or production
run is performed by the adapter:

```bash
# Inert by default; live execution requires separately authorized injected
# broker/runtime ports and never runs without explicit operator authorization.
python -m infra.operations.sheets_dlq_snapshot_adapter --help
```

## Dry-run plan (read-only)

Run the dry-run CLI against a capped, sanitized snapshot (local file only):

```bash
python -m infra.operations.sheets_dlq_reconcile \
  --snapshot /tmp/sheets-dlq/snapshot.json \
  --evidence /tmp/sheets-dlq/evidence.json
```

The emitted plan contains counts, hashed seller references, message
fingerprints, classifications, reason codes, and hashed evidence pointers only.
It must never include payloads, documents, raw bodies, credentials, URIs, or
OAuth data. Review it before requesting any approval.

## Approval workflow

1. Operator produces the sanitized dry-run plan.
2. For each `replay_candidate` to replay (or an allowed disposition), the
   business owner explicitly approves that exact plan digest, classification,
   action, message fingerprint, actor, and expiry.
3. The approval is recorded as an immutable ledger event.
4. Immediately before execution, the approval is re-validated: plan digest,
   classification, message fingerprint, action allowlist, and expiry. Any
   mismatch, change, or expiry fails closed.
5. Replay publish still requires passing the pre-publish duplicate check.

## Execute

Do not execute replay, purge, delete, archive/terminal-close, deploy, restart,
or any MongoDB/RabbitMQ mutation from this capability. Replay, if any, follows
the separate
[`docs/ops/webhook-backlog-replay.md`](webhook-backlog-replay.md) runbook and
requires an independent approved command with a run ID.

## Rollback

On operator rollback:

- Stop publishing.
- Apply only the approved quarantine disposition to the remaining approved
  items via a bound, proven adapter. If no adapter is usable, fail closed and
  append nothing.
- Append one or more immutable rollback events.

## Stop conditions

- Snapshot exceeds the cap.
- Approval is expired, digest-mismatched, or its classification/action
  fingerprint no longer matches.
- Replay gate sees an active scoped key, prior replay-success event, or
  unreconciled replay reservation.
- Publisher confirm fails.
- Quarantine adapter is unavailable during rollback.
- Any ledger hash-chain link breaks (append-only integrity).

## Post-check

1. Confirm every decision and action has exactly one immutable ledger event.
2. Confirm the ledger has no update/delete path and sequence/hash-chain are
   intact.
3. Confirm no rows were duplicated in Google Sheets.
4. Store the sanitized plan and any ledger artifacts with the change record.

## Scope boundary

This change does not add UI routes, new admin scopes, A5 poller/reboot
persistence, topology changes, or runtime operations. It introduces no new
RabbitMQ topology and reuses no devoluciones/claims quarantine queue. The tool
ships inactive and dry-run-first; every schema/index application and runtime
action requires separate, explicit authorization.

## Explicit non-actions

- Do not execute during planning/apply.
- Do not publish to production RabbitMQ without explicit approval.
- Do not update production MongoDB except during an independently approved
  execute.
- Do not create indexes or validators from this tool.
- Do not deploy, restart, rebuild, or mutate VM/container topology.
- Do not launch shells or subprocesses from the CLI.

## Follow-up

The tool ships as an inert, dry-run-first planning surface. Wiring it to real
replay, quarantine, terminal-close/archive, or ledger persistence requires a
separate, fully authorized rollback-and-approval workflow before any live use.
