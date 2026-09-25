from __future__ import annotations

from typing import Any

import pytest

from zeler_bootstrap.dispatcher_worker import DispatcherSettings, MongoHeartbeat


def test_dispatcher_settings_require_specific_runtime_configuration() -> None:
    values = {
        "MONGO_URI": "mongodb://test-host/test-db",
        "MONGO_DB": "test-db",
        "RABBITMQ_URL": "amqp://test-host/vhost",
        "GCP_PROJECT_ID": "test-project",
        "BOOTSTRAP_DISPATCH_REGION": "us-central1",
        "BOOTSTRAP_CLOUD_RUN_JOB": "zeler-bootstrap",
    }

    settings = DispatcherSettings.from_env(values)

    assert settings.mongo_db == "test-db"
    assert settings.job_name == "zeler-bootstrap"
    assert "mongodb://" not in repr(settings)
    assert "amqp://" not in repr(settings)
    with pytest.raises(ValueError, match="BOOTSTRAP_CLOUD_RUN_JOB"):
        DispatcherSettings.from_env(
            {key: value for key, value in values.items() if key != "BOOTSTRAP_CLOUD_RUN_JOB"}
        )
    with pytest.raises(ValueError, match="MONGO_DB"):
        DispatcherSettings.from_env({**values, "MONGO_URI": "mongodb://test-host/other-db"})


@pytest.mark.asyncio
async def test_mongo_heartbeat_degrades_after_failed_ping() -> None:
    class Database:
        fail = False

        async def command(self, command: str) -> dict[str, Any]:
            assert command == "ping"
            if self.fail:
                raise RuntimeError("mongo unavailable")
            return {"ok": 1}

    db = Database()
    probe = MongoHeartbeat(db)
    assert probe.status == "error"

    await probe.check_once()
    assert probe.status == "ok"
    db.fail = True
    await probe.check_once()
    assert probe.status == "error"
