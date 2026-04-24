from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from typing import Literal

from infra.decommission.inventory import LegacyInventory, legacy_inventory

AuditStatus = Literal["manual_approval_required", "planning_only"]


@dataclass(frozen=True)
class DecommissionAction:
    task_id: str
    title: str
    destructive: bool
    status: AuditStatus
    targets: tuple[str, ...]
    prerequisites: tuple[str, ...]
    manual_approval_required: str


@dataclass(frozen=True)
class DecommissionAudit:
    mode: Literal["dry-run"]
    safe_to_execute: bool
    actions: tuple[DecommissionAction, ...]


def build_decommission_audit(inventory: LegacyInventory | None = None) -> DecommissionAudit:
    """Build a dry-run audit for Phase 7 legacy decommission.

    The audit is deliberately non-executable: destructive steps are represented as gated manual
    actions with explicit prerequisites. This keeps automation useful for review without hiding
    the blast radius of archiving repos, stopping services, dropping DBs, or revoking OAuth apps.
    """

    current_inventory = inventory or legacy_inventory()
    product_repos = tuple(product.repository for product in current_inventory.products)
    service_targets = tuple(
        target
        for product in current_inventory.products
        for target in (*product.cloud_run_services, *product.vm_workloads)
    )
    databases = (
        tuple(
            database
            for product in current_inventory.products
            for database in product.database_names
        )
        + current_inventory.zeler_core_databases
    )
    oauth_apps = tuple(product.oauth_app_id for product in current_inventory.products)

    actions = (
        DecommissionAction(
            task_id="P7.1",
            title="Freeze 5 legacy product repositories on GitHub",
            destructive=True,
            status="manual_approval_required",
            targets=product_repos,
            prerequisites=(
                "Phase 6 parity archived with CRITICAL=0",
                "seller migration communication delivered",
                "repo deprecation README reviewed by an operator",
            ),
            manual_approval_required=(
                "Requires explicit human approval before GitHub archive/read-only changes."
            ),
        ),
        DecommissionAction(
            task_id="P7.2",
            title="Archive zeler-core repository",
            destructive=True,
            status="manual_approval_required",
            targets=(current_inventory.zeler_core_repository,),
            prerequisites=(
                "legacy product repos frozen or scheduled",
                "zeler-core deprecation/migration README reviewed",
                "final v-final tag plan approved",
            ),
            manual_approval_required=(
                "Requires explicit human approval before zeler-core commit/tag/archive."
            ),
        ),
        DecommissionAction(
            task_id="P7.3",
            title="Stop legacy Cloud Run services and VM workloads",
            destructive=True,
            status="manual_approval_required",
            targets=service_targets,
            prerequisites=(
                "Cloud Monitoring proves zero production traffic",
                "rollback owner and restart commands documented",
                "GCP project/credentials verified by operator",
            ),
            manual_approval_required=(
                "Requires explicit human approval before service stop/delete operations."
            ),
        ),
        DecommissionAction(
            task_id="P7.4",
            title="Drop legacy Mongo databases after recovery window",
            destructive=True,
            status="manual_approval_required",
            targets=databases,
            prerequisites=(
                "final Mongo/Atlas snapshot",
                "30-day recovery window elapsed after P7.1 freeze",
                "no platform code reads legacy connection strings",
            ),
            manual_approval_required=(
                "Requires explicit human approval; legacy databases must not be dropped before "
                "the recovery window."
            ),
        ),
        DecommissionAction(
            task_id="P7.5",
            title="Revoke legacy Meli OAuth applications",
            destructive=True,
            status="manual_approval_required",
            targets=oauth_apps,
            prerequisites=(
                "P7.4 database drop is complete and logged",
                'zeler_platform.meli_accounts contains only app_id="zeler-platform"',
                "Meli developer portal access verified by operator",
            ),
            manual_approval_required=(
                "Requires explicit human approval in the Meli developer portal."
            ),
        ),
        DecommissionAction(
            task_id="P7.6",
            title="Maintain migration post-mortem draft",
            destructive=False,
            status="planning_only",
            targets=("docs/migration-postmortem.md",),
            prerequisites=("P7.1-P7.5 execution timestamps and evidence attached",),
            manual_approval_required=(
                "No destructive approval needed; final publication waits for P7.1-P7.5 evidence."
            ),
        ),
    )

    return DecommissionAudit(mode="dry-run", safe_to_execute=False, actions=actions)


def render_markdown(audit: DecommissionAudit) -> str:
    lines = [
        "# Legacy Decommission Audit — DRY RUN",
        "",
        "This report does not archive repositories, stop services, revoke OAuth apps, "
        "or drop databases.",
        "It is a planning artifact for Phase 7 manual approval gates.",
        "",
        f"- Mode: `{audit.mode}`",
        f"- Safe to execute automatically: `{str(audit.safe_to_execute).lower()}`",
        "",
        "| Task | Status | Destructive | Targets | Required approval |",
        "|------|--------|-------------|---------|-------------------|",
    ]

    for action in audit.actions:
        lines.append(
            "| "
            f"{action.task_id} — {action.title} | `{action.status}` | "
            f"{str(action.destructive).lower()} | {', '.join(action.targets)} | "
            f"{action.manual_approval_required} |"
        )

    lines.extend(["", "## Critical safeguards", ""])
    lines.extend(
        f"- {action.task_id}: " + "; ".join(action.prerequisites) for action in audit.actions
    )
    return "\n".join(lines) + "\n"


def _to_json(audit: DecommissionAudit) -> str:
    return json.dumps(asdict(audit), indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a non-destructive Phase 7 decommission audit."
    )
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args()

    audit = build_decommission_audit()
    if args.format == "json":
        print(_to_json(audit), end="")
    else:
        print(render_markdown(audit), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
