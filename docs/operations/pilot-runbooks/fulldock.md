# Pilot runbook — fulldock (archived)

Fulldock is decommissioned and is no longer an active pilot module. Do not run
Fulldock health checks, workers, queue consumers, or stock-location replay as
part of normal platform rollout.

Historical collections `fulldock_inventory_rules` and `fulldock_history` are
retained as archive/read-only data. Any future deletion, reactivation, or data
rewrite requires explicit approval, a backup/archive plan, and a separate SDD.
Reactivation after code deletion must restore the module from git history or a
previously built image plus the UI catalog/route, `admin:fulldock`, runtime
services, DNS, and RabbitMQ prerequisites before traffic.
