# Carry-forward Follow-ups — greenfield-live-readiness

These items are intentionally **non-blocking** for moving the latest verdict from `FAIL` to
`PASS_WITH_WARNINGS`. They came from `sdd/greenfield-live-readiness/verify-report.md` and can be
re-opened by an operator as one or more follow-up SDD changes.

## Cosmetic/documentation follow-ups

1. **Rollout wave numbering decision**
   - Verify noted that the written spec uses waves 1-5 while the implementation and playbook use
     wave numbering 0-4.
   - Operator-facing decision: we keep `0-4` in operational tooling, where `0=pilot` and `1-5`
     are rollout batches described to humans as pilot, 5 sellers, 20 sellers, 100 sellers, and
     remainder.
   - If future tooling needs strict spec numbering, open a follow-up SDD to normalize docs and CLI
     arguments together.

2. **Pilot runbook H2 order**
   - Verify noted that pilot runbook H2 order differs from the exact spec order.
   - The content is complete; ordering is a doc-style choice so operators see pre-flight checks
     before triggering live behavior.
   - If an automated parser later requires exact ordering, re-open as a doc-contract SDD.

## Functional carry-forward follow-ups

1. **Dispatcher retry republish to `bootstrap.retry` queue**
   - R6 remains partial because dispatch failure currently preserves pending state and logs failure,
     but does not prove republish to the `bootstrap.retry` queue.
   - Open a focused dispatcher retry SDD to implement and test the R5-style retry queue semantics.

2. **Drift report shape exact `missing_fields` output**
   - R4 remains partial because drift detection reports broader drift state instead of the exact
     `missing_fields` diff shape from the scenario.
   - Open a drift-report compatibility SDD to add exact missing-field extraction while preserving the
     existing full-validator diagnostics.

3. **Alerts catalog mechanical reconciliation with IaC**
   - R9 remains partial because the alerts catalog is useful but not mechanically reconciled against
     every alert IaC artifact.
   - Open a monitoring-catalog SDD to compare alert policy count/name/runbook/channel against
     `infra/monitoring/` in CI.

## Operator note

Any operator can re-open one of these as a follow-up SDD. None of these items blocks archive once
the preflight CLI, strict paused-seller body, notification channel IaC, and this carry-forward note
are verified.
