# Rollout playbook

## Overview

Use `infra/rollout/wave_gate.py` before advancing each wave. Use the seller kill-switch in `docs/runbooks/account-kill-switch.md` and the module kill-switch (`module_registry.status="disabled"`) when a wave must halt.

## Wave 0 — Pilot (1 seller, 82453304)

- Pre-flight: all pilot runbooks pass `tests/operations/preflight.py`; seller `82453304` active.
- Gates: `uptime green 1h`, `DLQ depth 0`.
- Evidence checklist: health green, history doc written, no DLQ, gateway audit log present.
- Rollback: pause seller `82453304` and drain module consumers.

## Wave 1 — Internal (5 sellers)

- Gates: `24h DLQ flat`, `health all green`.
- Batch enroll script: operator-approved seller list only; enroll in batches of five.
- Rollback: pause the internal seller cohort, newest first, within 15 minutes.

## Wave 2 — Beta (20 sellers)

- Gates: `72h flat`, `paused count < 2`, no recent worker errors.
- Customer-comm template ref: `docs/operations/comms/beta-customer-email.md` (placeholder).
- Rollback: pause impacted beta sellers, highest error count first, within 30 minutes.

## Wave 3 — General (100 sellers)

- Gates: `72h flat`, health all green, gateway refresh failures flat.
- Support readiness: support owner assigned, alerts watched during business hours.
- Rollback: pause sellers by cohort in descending risk order within 60 minutes.

## Wave 4 — Remainder

- Gates: full-fleet readiness, no open P0/P1 alerts, all prior wave evidence accepted.
- Communication: send broad availability notice after wave gate passes.
- Rollback: pause affected sellers by incident cohort and stop onboarding intake.

## Rollback procedures per wave

### Rollback for wave 0

- Sellers to pause: seller `82453304`; ordering rule: pause before draining; time budget: 10 minutes; communication template path: `docs/operations/comms/pilot-rollback.md`.

### Rollback for wave 1

- Sellers to pause: internal cohort; ordering rule: newest enrolled first; time budget: 15 minutes; communication template path: `docs/operations/comms/internal-rollback.md`.

### Rollback for wave 2

- Sellers to pause: beta cohort; ordering rule: highest DLQ/error evidence first; time budget: 30 minutes; communication template path: `docs/operations/comms/beta-rollback.md`.

### Rollback for wave 3

- Sellers to pause: general 100 cohort; ordering rule: highest revenue-risk unaffected last; time budget: 60 minutes; communication template path: `docs/operations/comms/general-rollback.md`.

### Rollback for wave 4

- Sellers to pause: remainder cohort; ordering rule: incident cohort first then newest enrolled; time budget: 2 hours; communication template path: `docs/operations/comms/remainder-rollback.md`.

## Global rollback order

1. Stop OAuth/new onboarding with the gateway flag.
2. Pause affected sellers via `meli_accounts.paused/status` kill switch.
3. Drain consumers and inspect DLQ depth.
4. Full revert only after queues are safe and communications are sent.

## Communication artifacts (placeholder section)

- Customer email template path placeholder: `docs/operations/comms/customer-email-template.md`.
- In-app banner placeholder: `docs/operations/comms/in-app-banner.md`.
