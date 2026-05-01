from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_dlq_metric_yaml_parses_and_has_event_filter() -> None:
    metric = yaml.safe_load((ROOT / "infra" / "monitoring" / "dlq_metric.yaml").read_text())

    assert metric["name"] == "dlq_events_total"
    assert 'jsonPayload.event="worker.message.dlq"' in metric["filter"]
    assert "severity>=ERROR" in metric["filter"]
    assert metric["labelExtractors"]["seller_id"] == "EXTRACT(jsonPayload.seller_id)"


def test_dlq_alert_yaml_parses_and_has_policy() -> None:
    alert = yaml.safe_load((ROOT / "infra" / "monitoring" / "dlq_alert.yaml").read_text())

    assert alert["displayName"] == "dlq-events-spike"
    condition = alert["conditions"][0]["conditionThreshold"]
    assert condition["filter"] == 'metric.type="logging.googleapis.com/user/dlq_events_total"'
    assert condition["thresholdValue"] == 0
    assert condition["comparison"] == "COMPARISON_GT"
    assert alert["notificationChannels"] == [
        "projects/${GCP_PROJECT}/notificationChannels/${NOTIFICATION_CHANNEL_ID}"
    ]
