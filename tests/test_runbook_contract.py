from pathlib import Path


def test_prod_mongo_runbook_keeps_critical_operator_steps() -> None:
    runbook = Path("infra/docker/README.md").read_text(encoding="utf-8")

    assert "gen_mongo_keyfile.sh" in runbook
    assert "init_replica_set" in runbook
    assert "rs.status().myState" in runbook
    assert "apply_validators" in runbook
    assert "apply_seeds" in runbook
    assert "readiness" in runbook
    assert "MONGO_ADMIN_USER" in runbook
    assert "distinct from" in runbook


def test_prod_mongo_runbook_uses_env_file_for_compose_invocation() -> None:
    """The prod compose command must be documented WITH `--env-file .env.prod`.

    Without it, the container would not receive `MONGO_ADMIN_USER` /
    `MONGO_ADMIN_PASSWORD` and the localhost-exception bootstrap would
    silently fall back to anonymous, which the keyfile-armed mongod will
    eventually reject.
    """
    runbook = Path("infra/docker/README.md").read_text(encoding="utf-8")

    assert "--env-file .env.prod" in runbook


def test_prod_mongo_runbook_documents_rollback_and_rs_reconfig() -> None:
    """A rollback section MUST exist with the two recovery levers an operator needs.

    1. Full rollback: `docker compose down -v` + `git revert` to undo a bad change.
    2. In-place fix: `rs.reconfig(...)` to repair an RS initialized with the wrong host.
    """
    runbook = Path("infra/docker/README.md").read_text(encoding="utf-8")

    # Full rollback path
    assert "Rollback" in runbook
    assert "git revert" in runbook
    assert "down -v" in runbook

    # In-place RS member-host repair
    assert "rs.reconfig" in runbook
