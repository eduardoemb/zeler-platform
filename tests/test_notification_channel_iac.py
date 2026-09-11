from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_notification_channels_file_exists() -> None:
    assert (ROOT / "infra" / "monitoring" / "notification_channels.yaml").is_file()


def test_notification_channel_declares_both_operator_email_destinations() -> None:
    """Q26-b: laloramirez@zeler.ai joins the existing ops channel."""
    channels = yaml.safe_load(
        (ROOT / "infra" / "monitoring" / "notification_channels.yaml").read_text()
    )

    email_channels = [
        channel for channel in channels["notificationChannels"] if channel["type"] == "email"
    ]
    assert email_channels == [
        {
            "id": "${NOTIFICATION_CHANNEL_ID}",
            "displayName": "zeler-ops-email",
            "type": "email",
            "labels": {"email_address": "ops@zeler.ai"},
        },
        {
            "id": "${ZELERDATA_NOTIFICATION_CHANNEL_ID}",
            "displayName": "zelerdata-ops-email",
            "type": "email",
            "labels": {"email_address": "laloramirez@zeler.ai"},
        },
    ]


def test_dlq_alert_references_notification_channel_placeholder() -> None:
    alert = yaml.safe_load((ROOT / "infra" / "monitoring" / "dlq_alert.yaml").read_text())

    assert alert["notificationChannels"] == [
        "projects/${GCP_PROJECT}/notificationChannels/${NOTIFICATION_CHANNEL_ID}"
    ]


def test_zelerdata_freshness_metric_extracts_bounded_alarm_labels() -> None:
    metric = yaml.safe_load(
        (ROOT / "infra" / "monitoring" / "zelerdata_freshness_metric.yaml").read_text()
    )

    assert metric["name"] == "zelerdata_freshness_alarm"
    assert 'jsonPayload.event="zelerdata.freshness_alarm"' in metric["filter"]
    assert "severity>=ERROR" in metric["filter"]
    extractors = metric["labelExtractors"]
    assert extractors["read_model"] == "EXTRACT(jsonPayload.read_model)"
    assert extractors["reason"] == "EXTRACT(jsonPayload.reason)"
    # The label set stays bounded: no seller, token, cuenta or payload field.
    assert set(extractors) == {"read_model", "reason"}


def test_zelerdata_freshness_alert_notifies_both_operators() -> None:
    alert = yaml.safe_load(
        (ROOT / "infra" / "monitoring" / "zelerdata_freshness_alert.yaml").read_text()
    )

    assert alert["displayName"] == "zelerdata-freshness-alarm"
    assert alert["combiner"] == "OR"
    assert alert["enabled"] is True
    assert alert["notificationChannels"] == [
        "projects/${GCP_PROJECT}/notificationChannels/${NOTIFICATION_CHANNEL_ID}",
        "projects/${GCP_PROJECT}/notificationChannels/${ZELERDATA_NOTIFICATION_CHANNEL_ID}",
    ]
    conditions = [condition["conditionThreshold"] for condition in alert["conditions"]]
    assert len(conditions) == 1
    condition = conditions[0]
    assert (
        'metric.type="logging.googleapis.com/user/zelerdata_freshness_alarm"'
        in (condition["filter"])
    )
    assert 'resource.type="gce_instance"' in condition["filter"]
    assert condition["comparison"] == "COMPARISON_GT"
    assert condition["thresholdValue"] == 0
    assert condition["duration"] == "60s"
    assert "laloramirez@zeler.ai" in alert["documentation"]["content"]
