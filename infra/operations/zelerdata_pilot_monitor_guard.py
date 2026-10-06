"""Pure RAM-only guard for the selected, same-day ZelerData pilot.

No I/O, provider calls, state repair or acceptance certification occurs here.
The operator retains the authenticated original baseline and passes the previous
successful snapshots for monotonic comparisons. Running jobs require a projected
``owner_present`` boolean; owner tokens never appear in the result.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from zeler_sheets.history_onboarding import _message_checkpoint_bound
from zeler_sheets.onboarding_sources import _state


def classify(
    plan: dict[str, Any],
    qjob: dict[str, Any],
    qhead: dict[str, Any],
    baseline: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    """Return a closed receipt; neither mutate inputs nor refresh stored errors.

    ``baseline`` contains ``plan``, ``qjob`` and ``qhead`` RAM snapshots. Sequential
    reads are not an isolated snapshot: mismatched bindings fail closed. Historical
    errors remain visible; a ready state alone does not prove calendar coverage.

    Additive mode keeps the original snapshots, ``origin_authenticated=True``,
    ``origin_receipt_sha256``, ``quiescence_receipt_sha256``, ``previous`` snapshots
    with ``observed_at`` and ``debt_first_seen``. Root MUST authenticate the receipt
    pins and bind the original/quiescence facts first: flags/hashes are NOT proof.
    Only the recorded83/90 episodes are admitted. Episode90 also binds the previous
    origin pin and watches durable claims failure/completion counters separately.
    ``previous.observed_at`` equals the exact ``now`` passed for that snapshot.
    Persist the returned first-seen clock externally; never roll/absorb the origin.
    """

    class StopError(ValueError):
        pass

    def require(condition: bool, code: str) -> None:
        if not condition:
            raise StopError(code)

    def count(value: Any) -> int:
        require(
            isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 2**63,
            "invalid_counter",
        )
        return int(value)

    def optional_count(document: dict[str, Any], field: str) -> int:
        return count(document[field]) if field in document else 0

    def section(document: dict[str, Any], field: str, *, nullable: bool = False) -> dict[str, Any]:
        if field not in document or (nullable and document[field] is None):
            return {}
        require(isinstance(document[field], dict), "metadata_invalid")
        result: dict[str, Any] = document[field]
        return result

    def utc(value: Any) -> datetime:
        require(isinstance(value, datetime) and value.tzinfo is not None, "invalid_clock")
        result: datetime = value.astimezone(UTC)
        return result

    def signature(source: dict[str, Any]) -> tuple[Any, ...]:
        return (
            source.get("reason"),
            source.get("blocked_reason"),
            optional_count(source, "consecutive_failures"),
            source.get("next_attempt_at"),
            optional_count(source, "failed_units"),
            source.get("error_type"),
            source.get("error_signature"),
        )

    def progress(document: dict[str, Any], source: str) -> tuple[int, ...]:
        state = section(section(document, "onboarding_sources"), source)
        checkpoint = section(section(document, "collector_checkpoints"), source, nullable=True)
        periodic = (
            section(document, "message_periodic_recovery", nullable=True)
            if source == "messages"
            else {}
        )
        periodic_checkpoint = section(periodic, "checkpoint", nullable=True)
        values = tuple(
            optional_count(row, field)
            for row, field in (
                (state, "completed_units"),
                (state, "persisted"),
                (checkpoint, "persisted"),
                (checkpoint, "target_index"),
                (checkpoint, "offset"),
                (periodic, "packs_completed"),
                (periodic, "persisted"),
                (periodic_checkpoint, "persisted"),
                (periodic_checkpoint, "target_index"),
                (periodic_checkpoint, "offset"),
            )
        )
        return values + (
            (optional_count(document, "claims_completed_units"),)
            if source == "claims_returns"
            else ()
        )

    def issues(document: dict[str, Any], source: str) -> tuple[int, int, int]:
        state = section(section(document, "onboarding_sources"), source)
        checkpoint = section(section(document, "collector_checkpoints"), source, nullable=True)
        periodic = (
            section(document, "message_periodic_recovery", nullable=True)
            if source == "messages"
            else {}
        )
        return (
            optional_count(state, "issue_count"),
            optional_count(checkpoint, "issue_count"),
            optional_count(periodic, "issue_count")
            + optional_count(section(periodic, "checkpoint", nullable=True), "issue_count"),
        )

    def same(current: dict[str, Any], previous: dict[str, Any], keys: tuple[str, ...]) -> bool:
        return all(current[key] == previous[key] for key in keys)

    try:
        origin_plan, origin_job, origin_head = baseline["plan"], baseline["qjob"], baseline["qhead"]
        additive = any(
            field in baseline
            for field in (
                "origin_authenticated",
                "origin_receipt_sha256",
                "quiescence_receipt_sha256",
                "previous",
                "debt_first_seen",
            )
        )
        old_plan, old_job, old_head = origin_plan, origin_job, origin_head
        episode90 = False
        previous_observed: datetime | None = None
        debt_first_seen: datetime | None = None
        if additive:
            require(
                baseline.get("origin_authenticated") is True
                and all(
                    isinstance(baseline.get(field), str)
                    and re.fullmatch(r"[a-f0-9]{64}", baseline[field]) is not None
                    for field in ("origin_receipt_sha256", "quiescence_receipt_sha256")
                ),
                "origin_authentication_invalid",
            )
            origin_counts = tuple(
                count(origin_plan[field])
                for field in (
                    "execution_consumed",
                    "execution_sent",
                    "total_consumed",
                    "incremental_consumed",
                )
            )
            require(
                origin_plan["state"] == "paused"
                and origin_plan["eligible"] is True
                and origin_counts in {(83, 80, 58, 25), (90, 87, 65, 25)},
                "origin_policy_invalid",
            )
            episode90 = origin_counts == (90, 87, 65, 25)
            previous_snapshot = section(baseline, "previous")
            if episode90:
                require(
                    previous_snapshot.get("origin_receipt_sha256")
                    == baseline["origin_receipt_sha256"],
                    "origin_authentication_invalid",
                )
            old_plan, old_job, old_head = (
                previous_snapshot["plan"],
                previous_snapshot["qjob"],
                previous_snapshot["qhead"],
            )
            previous_observed = utc(previous_snapshot["observed_at"])
        now = utc(now)
        received = datetime(2026, 10, 6, 15, 32, 58, tzinfo=UTC)
        deadline = datetime(2026, 10, 6, 20, 32, 58, tzinfo=UTC)
        require(received <= now < deadline, "clock_stop")
        if additive:
            require(
                previous_observed is not None and received <= previous_observed <= now,
                "debt_clock_invalid",
            )
            require(
                same(
                    plan,
                    origin_plan,
                    (
                        "_id",
                        "seller_id",
                        "execution_id",
                        "execution_until",
                        "execution_utc_day",
                        "incremental_day",
                        "date_from",
                        "date_to",
                        "cutoff",
                        "policy_version",
                        "authority",
                        "sources",
                        "total_budget",
                        "execution_attempt_limit",
                        "incremental_policy",
                    ),
                ),
                "scope_drift",
            )
            require(
                same(
                    qjob,
                    origin_job,
                    (
                        "_id",
                        "seller_id",
                        "read_model",
                        "history_plan_id",
                        "history_acquisition_id",
                        "date_from",
                        "date_to",
                        "policy_authority",
                    ),
                )
                and same(
                    qhead,
                    origin_head,
                    (
                        "_id",
                        "job_id",
                        "seller_id",
                        "read_model",
                        "plan_id",
                        "date_from",
                        "date_to",
                    ),
                ),
                "binding_loss",
            )
        require(plan["state"] == "active" and plan["eligible"] is True, "inactive")
        require(utc(plan["execution_until"]) == deadline, "deadline_drift")
        require(
            same(
                plan,
                old_plan,
                (
                    "_id",
                    "seller_id",
                    "execution_id",
                    "execution_until",
                    "execution_utc_day",
                    "incremental_day",
                    "date_from",
                    "date_to",
                    "cutoff",
                    "policy_version",
                    "authority",
                    "sources",
                ),
            ),
            "scope_drift",
        )
        require(
            plan["seller_id"] == plan["_id"] == "82453304"
            and plan["execution_id"] == "868b413e20184befb7e8358e0051924f"
            and plan["execution_utc_day"] == plan["incremental_day"] == "2026-10-06",
            "scope_drift",
        )
        caps = dict(orders=800, questions=150, shipments=250, messages=300, claims_returns=500)
        require(set(plan["sources"]) == set(caps) and len(plan["sources"]) == 5, "source_drift")
        require(count(plan["total_budget"]) == count(old_plan["total_budget"]) == 2000, "cap_drift")
        require(
            count(plan["execution_attempt_limit"])
            == count(old_plan["execution_attempt_limit"])
            == 2500,
            "cap_drift",
        )
        policy = plan["incremental_policy"]
        require(policy == old_plan["incremental_policy"], "maintenance_policy_drift")
        require(
            count(policy["max_daily_total"]) == 500 and count(policy["max_daily_source"]) == 300,
            "maintenance_policy_drift",
        )
        for source, cap in caps.items():
            budget, previous = plan["budget"][source], old_plan["budget"][source]
            require(
                count(budget["physical_attempts"]) == count(previous["physical_attempts"]) == cap,
                "source_cap_drift",
            )
            require(
                count(previous["consumed"]) <= count(budget["consumed"]) <= cap, "refund_or_cap"
            )
            if additive:
                require(
                    count(origin_plan["budget"][source]["physical_attempts"]) == cap
                    and count(origin_plan["budget"][source]["consumed"])
                    <= count(budget["consumed"])
                    and count(origin_plan["incremental_source_consumed"][source])
                    <= count(plan["incremental_source_consumed"][source]),
                    "refund_or_cap",
                )
            require(
                count(old_plan["incremental_source_consumed"][source])
                <= count(plan["incremental_source_consumed"][source])
                <= 300,
                "refund_or_cap",
            )
        require(
            count(plan["budget"]["full_withdrawals"]["physical_attempts"]) == 0
            and count(plan["budget"]["full_withdrawals"]["consumed"]) == 0
            and count(plan["incremental_source_consumed"]["full_withdrawals"]) == 0,
            "full_used",
        )
        charged, sent = count(plan["execution_consumed"]), count(plan["execution_sent"])
        initial, maintenance = count(plan["total_consumed"]), count(plan["incremental_consumed"])
        require(
            max(81, count(origin_plan["execution_consumed"]), count(old_plan["execution_consumed"]))
            <= charged
            < 2500,
            "charged_stop",
        )
        require(
            max(79, count(origin_plan["execution_sent"]), count(old_plan["execution_sent"]))
            <= sent
            <= charged,
            "refund_or_cap",
        )
        gap = charged - sent
        if not additive:
            require(gap <= 2, "send_gap")
        else:
            require(gap >= 3, "debt_origin_drift")
            require(gap <= 4, "debt_growth")
            previous_gap = count(old_plan["execution_consumed"]) - count(old_plan["execution_sent"])
            require(previous_gap in (3, 4), "debt_origin_drift")
            if gap == 4:
                supplied = baseline.get("debt_first_seen")
                require(supplied is not None or previous_gap == 3, "debt_clock_missing")
                debt_first_seen = now if supplied is None else utc(supplied)
                require(received <= debt_first_seen <= now, "debt_clock_invalid")
                if previous_gap == 4:
                    require(
                        previous_observed is not None and debt_first_seen <= previous_observed,
                        "debt_clock_invalid",
                    )
                else:
                    require(
                        previous_observed is not None and previous_observed <= debt_first_seen,
                        "debt_clock_invalid",
                    )
                require((now - debt_first_seen).total_seconds() < 10, "debt_timeout")
                if previous_gap == 4:
                    require(debt_first_seen == previous_observed, "debt_tick_limit")
        require(
            max(57, count(origin_plan["total_consumed"]), count(old_plan["total_consumed"]))
            <= initial
            <= 2000
            and max(
                24,
                count(origin_plan["incremental_consumed"]),
                count(old_plan["incremental_consumed"]),
            )
            <= maintenance
            <= 500,
            "refund_or_cap",
        )
        require(
            charged == initial + maintenance
            and initial == sum(count(plan["budget"][s]["consumed"]) for s in caps)
            and maintenance == sum(count(plan["incremental_source_consumed"][s]) for s in caps),
            "ledger_mismatch",
        )
        require(
            same(
                qjob,
                old_job,
                (
                    "_id",
                    "seller_id",
                    "read_model",
                    "history_plan_id",
                    "history_acquisition_id",
                    "date_from",
                    "date_to",
                    "policy_authority",
                ),
            )
            and same(
                qhead,
                old_head,
                (
                    "_id",
                    "job_id",
                    "seller_id",
                    "read_model",
                    "plan_id",
                    "date_from",
                    "date_to",
                ),
            )
            and qhead["seller_id"] == qjob["seller_id"] == plan["seller_id"]
            and qhead["read_model"] == qjob["read_model"] == "questions"
            and qhead["_id"] == qjob["history_acquisition_id"]
            and qhead["job_id"] == qjob["_id"]
            and qhead["plan_id"] == qjob["history_plan_id"],
            "binding_loss",
        )
        require(
            count(qhead["generation"]) == count(qjob["history_generation"]) == 1, "binding_loss"
        )
        require(
            count(qhead["pass_number"]) >= max(2, count(old_head["pass_number"]))
            and qhead["pass_number"] == count(qjob["history_pass_number"]),
            "binding_loss",
        )
        require(
            count(qhead["checkpoint_revision"]) >= max(4, count(old_head["checkpoint_revision"]))
            and count(qhead["page_sequence"]) >= max(3, count(old_head["page_sequence"])),
            "checkpoint_regression",
        )
        require(
            qhead["phase"] in {"discover", "hydrate", "verify", "publish", "completed"},
            "binding_loss",
        )
        completed = qjob["state"] == "completed" and qhead["phase"] == "completed"
        lag = qhead["checkpoint_revision"] - count(qjob["history_checkpoint_revision"])
        require(lag in ((0, 1) if completed else (0,)), "binding_loss")
        require(
            qjob["state"] in {"pending", "running", "completed"}
            and not qjob.get("failure_reason")
            and not qjob.get("blocked_reason")
            and (qjob["state"] != "completed" or completed),
            "fresh_job_failure",
        )
        for field in ("discovered_count", "fetched_count", "published_count"):
            require(count(qhead[field]) >= count(old_head[field]), "checkpoint_regression")
        require(
            qhead["published_count"] <= qhead["fetched_count"] <= qhead["discovered_count"],
            "binding_loss",
        )
        if qjob["state"] == "running":
            require(
                qjob.get("owner_present") is True and utc(qjob["lease_until"]) > now,
                "ownership_loss",
            )
        if qhead.get("next_cursor") is not None:
            require(0 <= (now - utc(qhead["observed_until"])).total_seconds() < 300, "cursor_stop")
        for checkpoint, holder, start, end in (
            (plan.get("collector_checkpoints", {}).get("messages"), plan, "date_from", "cutoff"),
            (
                (plan.get("message_periodic_recovery") or {}).get("checkpoint"),
                plan.get("message_periodic_recovery") or {},
                "sweep_start",
                "sweep_end",
            ),
        ):
            if checkpoint is not None:
                first = _message_checkpoint_bound(checkpoint["start"], holder[start])
                last = _message_checkpoint_bound(checkpoint["end"], holder[end])
                checked = _state(plan["seller_id"], first, last, "messages", checkpoint)
                targets = checked.get("target_ids", [])
                require(
                    isinstance(targets, list) and checked["target_index"] <= len(targets),
                    "checkpoint_invalid",
                )
        if episode90:
            for field in ("claims_failed_units", "claims_completed_units"):
                require(
                    max(optional_count(origin_plan, field), optional_count(old_plan, field))
                    <= optional_count(plan, field),
                    "checkpoint_regression",
                )
            require(
                optional_count(plan, "claims_failed_units")
                <= optional_count(old_plan, "claims_failed_units"),
                "fresh_source_failure",
            )
        labels: dict[str, str] = {}
        for source in caps:
            previous = old_plan.get("onboarding_sources", {}).get(source, {})
            current = plan.get("onboarding_sources", {}).get(source, {})
            old_signature, current_signature = signature(previous), signature(current)
            require(
                current_signature[3] is None or current_signature[3] == old_signature[3],
                "source_error_changed",
            )
            require(
                current_signature[2] <= old_signature[2]
                and current_signature[4] <= old_signature[4]
                and all(
                    current <= previous
                    for current, previous in zip(
                        issues(plan, source), issues(old_plan, source), strict=True
                    )
                ),
                "fresh_source_failure",
            )
            progressed = any(
                x > y
                for x, y in zip(progress(plan, source), progress(old_plan, source), strict=True)
            )
            if source == "questions":
                # Bindings, ownership and monotonic counters were checked above.
                # A staged page is progress, never a calendar/reader certificate.
                progressed = progressed or any(
                    count(qhead[field]) > count(old_head[field])
                    for field in ("discovered_count", "fetched_count", "published_count")
                )
            terminal = (
                completed
                if source == "questions"
                else (current.get("state") == "ready" and previous.get("state") != "ready")
            )
            cleared = (
                not current.get("reason")
                and not current.get("blocked_reason")
                and not current.get("error_type")
                and not current.get("error_signature")
            )
            improved = cleared and (progressed or terminal)
            unchanged = current_signature == old_signature
            require(
                unchanged or improved or (not any(old_signature) and not any(current_signature)),
                "source_error_changed",
            )
            labels[source] = (
                "HISTORICAL_PENDING"
                if unchanged and any(current_signature)
                else "IMPROVED"
                if improved
                else "OBSERVING"
            )
        result: dict[str, Any] = {
            "status": "RUNNING",
            "questions": qjob["state"],
            "sources": labels,
            "snapshot_proven": False,
        }
        if episode90:
            result["claims_failed_units"] = optional_count(plan, "claims_failed_units")
            result["claims_completed_units"] = optional_count(plan, "claims_completed_units")
        if additive:
            result["debt_first_seen"] = None
            if debt_first_seen is not None:
                result.update(
                    status="DEBT_UNPROVEN",
                    debt_first_seen=debt_first_seen.isoformat(),
                    debt_age_seconds=(now - debt_first_seen).total_seconds(),
                )
        return result
    except StopError as error:
        return {"status": "STOP", "reason": str(error), "snapshot_proven": False}
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return {"status": "STOP", "reason": "metadata_invalid", "snapshot_proven": False}
