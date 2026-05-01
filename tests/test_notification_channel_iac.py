from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_notification_channels_file_exists() -> None:
    assert (ROOT / "infra" / "monitoring" / "notification_channels.yaml").is_file()


def test_notification_channel_declares_ops_email_destination() -> None:
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
        }
    ]


def test_dlq_alert_references_notification_channel_placeholder() -> None:
    alert = yaml.safe_load((ROOT / "infra" / "monitoring" / "dlq_alert.yaml").read_text())

    assert alert["notificationChannels"] == [
        "projects/${GCP_PROJECT}/notificationChannels/${NOTIFICATION_CHANNEL_ID}"
    ]
