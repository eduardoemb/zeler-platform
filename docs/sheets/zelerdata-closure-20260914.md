# ZelerData full closure — September 14, 2026

Status: implementation and recovery in progress; the 90-minute certification
window has not started. Source of acceptance: the updated
`openspec/changes/zelerdata-live-formula-repairs/` artifacts and the user's
approved plan (35 simultaneous cases, 90 minutes, combined evidence for absent
positive production fixtures).

## Broker baseline

Read-only probes inside the approved Sheets runtime confirmed DNS and TCP
connectivity, HTTP 200 from broker management, 20 current connections and a
configured `max-connections=20`. Seventeen connections had no channels; all 20
were running and older than ten minutes. A new AMQP connection was rejected
with reply code 530. No limits, topology, messages or credentials were changed.

API `/health` and gateway `/ready` returned 503 with RabbitMQ unavailable;
Mongo and registry checks passed, as did the gateway scheduler. Sheets worker
Docker health remained healthy, so that alone does not prove broker admission.

Installed aio_pika exposes `is_closed`/`connected`, not `is_open`. A local
non-network reproduction of the actual gateway checker performed ten probes,
created ten additional connections and never closed the original. Existing
test doubles supplied `is_open` and hid the real interface mismatch. The
gateway correction must preserve ownership during reconnect, cancellation and
shutdown as well as normal reuse.

Independent probe inspection additionally reproduced orphan robust reconnect
work after core health timeout and an unbounded Sheets passive queue operation.
Each executable correction requires its own failing regression before editing.

## Delivery boundaries

No runtime changes have been made in this closure phase yet. Preserve the
currently running gateway `sha256:2d4a514cab2d3ddca7e95109aeedc1e11e41115f8c09fddedd850aa0dc9ef130`,
Sheets API `sha256:07499cf3ce2de2e99d41f31db8be557110131c4e941e7068d788b3e2e747f7b7`
and Sheets worker `sha256:887781cf8d9264a9d49912af03049979a618dd30292a716e3d734a6e75001b98`
as observed identities, not as proof of stable acceptance. Record exact candidate
commits/builds/digests and compatible rollback before each authorized delivery.

Current source calls the shared helper from four module APIs. Runtime inspection
confirmed that repricer, publicador and autoreply still run older images without
that helper; their updates would include unrelated product changes. This delivery
is limited to gateway, sheets-api and sheets-worker. Record those other images
as drift requiring a separately scoped assessment.

## Certification record

Pending: guarded returns/historical source verification, complete matrix
expected/actual evidence, final local gates, exact-source delivery and warm-up,
three simultaneous 35-case rounds at minutes 0/30/60, 90 continuous minutes of
lightweight runtime observations, diagnosis readback and independent SDD closure.

## Local implementation acceptance

Final corrected isolated-Mongo suite: **4663 passed, 9 skipped** in 244.07 seconds.
The eight protected replica-set cases passed separately with an explicit verified
loopback target and no ambient MONGO_URI. The ninth skip is the existing Caddy
fixture with no required keys. Ruff check/format and full mypy passed (547 files);
direct-Meli lint passed. Initial suite failures were caused by an invocation URI
without a default database; all 39 affected cases and the full corrected suite
passed. No production database was used.

Gateway ownership, ephemeral probe cleanup and inventory cadence each have
RED/GREEN evidence and independent focused review in the change's apply-progress
artifacts. A 35-way local authenticated API harness with 1900 source documents
completed in 3.096 seconds (maximum request 3.061 seconds), with no HTTP 5xx or
PROCESSING. This proves bounded local load, not 35 positive production outcomes:
nine cases had explicit missing synthetic coverage, and the harness excludes
the gateway and native Sheets execution. Production certification remains pending.
