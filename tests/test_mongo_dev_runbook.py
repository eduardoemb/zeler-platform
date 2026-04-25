from pathlib import Path


def test_dev_mongo_runbook_documents_replica_set_bootstrap_sequence() -> None:
    runbook = Path("infra/docker/README.md").read_text(encoding="utf-8")

    assert "Dev Mongo replica-set bootstrap" in runbook
    assert "docker compose -f infra/docker/mongo-dev.yml down -v" in runbook
    assert "docker compose -f infra/docker/mongo-dev.yml up -d" in runbook
    assert "MONGO_RS_NAME=rs0-dev" in runbook
    assert "MONGO_INIT_URI=mongodb://127.0.0.1:27017/?directConnection=true" in runbook
    assert "MONGO_RS_MEMBER_HOST=127.0.0.1:27017" in runbook
    assert "uv run python -m infra.mongo.init_replica_set" in runbook
    assert "rs.status().myState" in runbook


def test_dev_mongo_runbook_documents_smoke_result_rollback_and_option_a() -> None:
    runbook = Path("infra/docker/README.md").read_text(encoding="utf-8")

    assert "prints `1`" in runbook
    assert "rollback" in runbook.lower()
    assert "git revert" in runbook
    assert "--keyFile" in runbook
    assert "Option A" in runbook
    assert "gen_mongo_keyfile.sh" in runbook


def test_dev_mongo_runbook_documents_failure_modes() -> None:
    runbook = Path("infra/docker/README.md").read_text(encoding="utf-8")

    assert "AlreadyInitialized=23" in runbook
    assert "UserAlreadyExists=51003" in runbook
    assert "Auth required" in runbook
    assert "port collision" in runbook.lower()
