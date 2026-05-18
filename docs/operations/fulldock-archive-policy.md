# Fulldock archive policy

Fulldock/FulldockManager is decommissioned and must remain absent from active
product, runtime, registry, worker, and RabbitMQ topology surfaces.

## Historical Mongo collections

The following collections are retained only as historical archive data:

- `fulldock_inventory_rules`
- `fulldock_history`

Policy:

- Treat these collections as read-only archive records.
- Do not create new active writers for these collections.
- Do not run delete, drop, rewrite, or migration operations against these
  collections without a separate approved SDD, backup/archive plan, and explicit
  operator approval.
- Production inspection must run only from the approved VM/VPC/runtime context
  with sanitized aggregate output. Do not print raw documents or secrets.
- Keep schema and index JSON files in the repository as archive contracts until
  a future approved retention/deletion change says otherwise.

## RabbitMQ legacy cleanup

The active runtime no longer declares Fulldock queues. Live cleanup must inspect
queue/DLQ depths first. Empty retired queues can be removed. Non-empty queues
must not be purged or deleted without explicit approval for message disposal.

## DNS/TLS parking

`fulldock.zeler.ai` is parked at the reverse proxy and returns HTTP `410 Gone`.
It must not proxy to a Fulldock API or worker. Full DNS removal can happen later
from the DNS provider if the team wants the hostname to stop resolving entirely.
