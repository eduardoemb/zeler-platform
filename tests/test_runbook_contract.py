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
