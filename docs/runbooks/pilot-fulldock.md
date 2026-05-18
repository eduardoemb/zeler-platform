# Pilot runbook — fulldock (archived)

Fulldock is decommissioned. This runbook is retained only to explain why old
Fulldock pilot operations should not be executed during current platform work.

- Do not start or validate a Fulldock API/worker runtime.
- Do not bind/replay stock-location events to Fulldock queues.
- Do not mutate `fulldock_inventory_rules` or `fulldock_history` without a
  future explicit data-retention SDD and operator approval.

Rollback or reactivation must restore the deleted module code from git history
or a previously built image, then restore UI catalog/route, `admin:fulldock`,
runtime services, DNS, and RabbitMQ bindings before any live traffic is sent.
