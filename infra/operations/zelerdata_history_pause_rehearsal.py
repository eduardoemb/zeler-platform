"""Root runs ONLY inside the isolated worker container; no production inputs.

seed emits one synthetic local job + one real-broker delivery. inspect/assert
emit counts/state only. Intentional fixture writes target one literal disposable
DB. Does not read env Mongo, credentials, OAuth, or provider data.
"""

import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

from pymongo import MongoClient

URI = "mongodb://zeler-rehearsal-mongo:27017/?replicaSet=rs0&directConnection=true"
DB = "zeler_pause_rehearsal_20261003"
BROKER = "amqp://ci:ci-local@zeler-rehearsal-rabbit:5672/"
SELLER = "999001"


def run(action: str) -> None:
    client: MongoClient[dict[str, Any]] = MongoClient(
        URI, tz_aware=True, serverSelectionTimeoutMS=5000
    )
    db = client[DB]
    if action == "prepare":
        if db["platform_migrations"].count_documents({}):
            raise RuntimeError("fixture migration must be absent")
        db["platform_migrations"].insert_one(
            {
                "_id": "sheets_sync_jobs_v2_activation_cutoff",
                "activation_cutoff": datetime.now(UTC) - timedelta(hours=1),
            }
        )

        async def prepare_broker() -> None:
            import aio_pika

            connection = await aio_pika.connect_robust(BROKER)
            try:
                channel = await connection.channel()
                exchange = await channel.declare_exchange(
                    "meli.events", aio_pika.ExchangeType.TOPIC, durable=True
                )
                dlx = await channel.declare_exchange(
                    "zeler.sheets.claims.dlx", aio_pika.ExchangeType.DIRECT, durable=True
                )
                dlq = await channel.declare_queue("zeler.sheets.claims.dlq", durable=True)
                await dlq.bind(dlx, routing_key="zeler.sheets.claims.dlq")
                queue = await channel.declare_queue(
                    "zeler.sheets.claims",
                    durable=True,
                    arguments={
                        "x-dead-letter-exchange": "zeler.sheets.claims.dlx",
                        "x-dead-letter-routing-key": "zeler.sheets.claims.dlq",
                    },
                )
                await queue.bind(exchange, routing_key="claims.updated")
            finally:
                await connection.close()

        asyncio.run(prepare_broker())
    elif action == "seed":
        # Refuse replacing jobs, repeating attempts, or touching restored records.
        if db["sheets_sync_jobs"].count_documents({}) or db["webhook_events"].count_documents({}):
            raise RuntimeError("fixture database must be fresh")
        now = datetime.now(UTC)
        db["sheets_sync_jobs"].insert_one(
            {
                "_id": "synthetic-pause-job",
                "seller_id": SELLER,
                "spreadsheet_id": "never-provider",
                "state": "pending",
                "created_at": now,
                "requested_at": now - timedelta(minutes=1),
                "available_at": None,
                "attempt_count": 0,
                "fence": 0,
                "lease_until": None,
                "append_started_at": None,
            }
        )
        db["webhook_events"].insert_one(
            {
                "_id": "synthetic-pause-delta",
                "user_id": int(SELLER),
                "received_at": now,
                "classification": "items.updated",
                "resource": "/items/SYNTHETIC_PAUSE_JOB",
            }
        )

        # Publish from same isolated image dependencies; real Rabbit ack/requeue.
        async def publish() -> None:
            import aio_pika

            connection = await aio_pika.connect_robust(BROKER)
            try:
                channel = await connection.channel()
                exchange = await channel.declare_exchange(
                    "meli.events", aio_pika.ExchangeType.TOPIC, durable=True
                )
                await exchange.publish(
                    aio_pika.Message(
                        json.dumps(
                            {
                                "event_id": "synthetic-pause-amqp",
                                "event_type": "items.updated",
                                "seller_id": int(SELLER),
                                "resource": "/items/SYNTHETIC_PAUSE_AMQP",
                                "idempotency_key": "synthetic-pause-amqp",
                            }
                        ).encode(),
                        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    ),
                    routing_key="items.updated",
                    mandatory=True,
                )
            finally:
                await connection.close()

        asyncio.run(publish())
    elif action in ("inspect", "assert-drained"):
        job = db["sheets_sync_jobs"].find_one({"_id": "synthetic-pause-job"})
        if job is None:
            raise RuntimeError("fixture job absent")
        values = {
            "state": job["state"],
            "attempt_count": job["attempt_count"],
            "fence": job["fence"],
            "lease_present": job.get("lease_until") is not None,
            "append_started": job.get("append_started_at") is not None,
            "checkpoint_present": job.get("cursor_event_id") == "synthetic-pause-delta",
            "jobs_count": db["sheets_sync_jobs"].count_documents({}),
        }
        if action == "assert-drained" and not (
            values["state"] == "succeeded"
            and values["attempt_count"] == 1
            and values["fence"] == 1
            and not values["lease_present"]
            and values["checkpoint_present"]
            and values["jobs_count"] == 1
        ):
            raise RuntimeError("drain failed")
        print(json.dumps(values, sort_keys=True))
    else:
        raise RuntimeError("fixture action not allowed")
    client.close()


if __name__ == "__main__":
    try:
        run(sys.argv[1])
    except Exception as exc:  # noqa: BLE001 - sanitized receipt, no exception payload.
        # Only class; do not print driver/transport payloads.
        print(json.dumps({"ok": False, "error_class": type(exc).__name__}))
        raise SystemExit(1) from None
