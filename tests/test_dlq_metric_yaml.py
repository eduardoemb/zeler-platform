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
    assert alert["combiner"] == "OR"

    threshold_conditions = [condition["conditionThreshold"] for condition in alert["conditions"]]
    filters = [condition["filter"] for condition in threshold_conditions]

    assert any('resource.type="cloud_run_revision"' in filter_ for filter_ in filters)
    assert any('resource.type="gce_instance"' in filter_ for filter_ in filters)
    for condition in threshold_conditions:
        assert 'metric.type="logging.googleapis.com/user/dlq_events_total"' in condition["filter"]
        assert 'resource.type="' in condition["filter"]
        assert condition["thresholdValue"] == 0
        assert condition["comparison"] == "COMPARISON_GT"
        assert condition["duration"] == "60s"
        assert condition["aggregations"] == [
            {
                "alignmentPeriod": "60s",
                "perSeriesAligner": "ALIGN_DELTA",
                "crossSeriesReducer": "REDUCE_SUM",
            }
        ]
    assert alert["notificationChannels"] == [
        "projects/${GCP_PROJECT}/notificationChannels/${NOTIFICATION_CHANNEL_ID}"
    ]
