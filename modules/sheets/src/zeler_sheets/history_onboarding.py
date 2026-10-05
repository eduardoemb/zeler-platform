"""Account-link policy executor reusing bounded recovery and source writers.

A durable plan lease protects the scheduler; queue leases protect recovery work.
No monthly prompts, annual rescans, destructive relink or coverage shortcuts.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from pymongo import ReturnDocument

from zeler_platform_core.clients.meli_gateway_client import GatewayRateLimitError
from zeler_platform_core.history_onboarding import (
    PLAN_COLLECTION,
    POLICY_VERSION,
    SOURCES,
    history_execution_allowed,
    history_execution_query,
    history_request_trace,
)
from zeler_platform_core.history_work_intent import HistoryWorkIntent, HistoryWorkWaitError
from zeler_sheets.formulas.pacing import (
    HistoryPolicyWaitError,
    PacedMeliGateway,
    admit_paced_dispatch,
    history_policy_dispatch,
)
from zeler_sheets.formulas.recovery import (
    FormulaRecoveryQueue,
    OrderHistoryRecoveryRequest,
    QuestionScanRecoveryRequest,
    RecoveryCapacityError,
    RecoveryRequest,
    ShipmentIdsRecoveryRequest,
)
from zeler_sheets.formulas.recovery_worker import FormulaRecoveryWorker
from zeler_sheets.history_question_worker import HistoryQuestionsWorker
from zeler_sheets.history_worker import HistoryOrdersWorker
from zeler_sheets.modification_scan_store import ModificationScanStore
from zeler_sheets.modification_scan_worker import ModificationScanWorker
from zeler_sheets.pilot_history import HistoryPlanner

MESSAGE_PERIODIC_BATCH = 40
MESSAGE_PERIODIC_REQUESTS = 2


def validate_history_sellers(sellers: frozenset[str] | None) -> frozenset[str] | None:
    """Explicit rollout scopes fail closed; no scope means ordinary eligibility."""
    if sellers is None:
        return None
    if not sellers or any(
        not isinstance(seller, str)
        or not seller.isascii()
        or not seller.isdecimal()
        or len(seller) > 20
        or str(int(seller)) != seller
        for seller in sellers
    ):
        raise ValueError("explicit history seller scope must contain canonical numeric sellers")
    return sellers


def history_onboarding_sellers(raw: str | None) -> frozenset[str] | None:
    return validate_history_sellers(
        None if raw is None else frozenset(value.strip() for value in raw.split(","))
    )


def message_periodic_progress(plan: dict[str, Any]) -> dict[str, Any] | None:
    """Sanitized progress, never pack IDs, message content or an exact total."""
    state = plan.get("message_periodic_recovery")
    if not isinstance(state, dict):
        return None
    checkpoint = state.get("checkpoint") or {}
    return {
        "state": state.get("state", "running"),
        "sweep_complete": bool(state.get("sweep_complete")),
        "sweep_start": state.get("sweep_start"),
        "sweep_end": state.get("sweep_end"),
        "next_sweep_at": state.get("next_sweep_at"),
        "packs_completed": state.get("packs_completed", 0),
        "batch_size": len(checkpoint.get("target_ids", [])),
        "batch_completed": checkpoint.get("target_index", 0),
        "page_offset": checkpoint.get("offset", 0),
        "persisted": state.get("persisted", 0) + checkpoint.get("persisted", 0),
        "issue_count": state.get("issue_count", 0) + checkpoint.get("issue_count", 0),
        "reason": state.get("reason"),
        "max_requests_per_turn": MESSAGE_PERIODIC_REQUESTS,
        "coverage_complete": False,
    }


async def seller_eligible(db: Any, seller: str) -> bool:
    account = await db["meli_accounts"].find_one(
        {"seller_id": {"$in": [seller, int(seller)]}, "status": "active"}
    )
    return account is not None


class PlanBudgetGateway(PacedMeliGateway):
    """Charge each physical attempt atomically BEFORE dispatch, including failures."""

    def __init__(
        self,
        db: Any,
        inner: Any,
        seller: str,
        source: str,
        *,
        lease_token: str | None = None,
        work_intent: HistoryWorkIntent | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.db, self.inner, self.seller, self.source = db, inner, seller, source
        self.lease_token, self.now = lease_token, now
        self._inner = inner
        if work_intent is not None and (work_intent.source != source or source not in SOURCES[:-1]):
            raise HistoryPolicyWaitError("work source does not match policy")
        self.work_intent = work_intent
        self.incremental = work_intent is not None
        self._work_lock = asyncio.Lock()
        self._work_nonce: str | None = None
        self._work_receipt: dict[str, Any] | None = None
        self.trace_headers: dict[str, str] = {}
        self._charged_plan: dict[str, Any] = {}
        self._execution_filter: dict[str, Any] = {}
        self._execution_credit: dict[str, int] = {}

    def check_path(self, path: str) -> None:
        parsed = urlsplit(path)
        allowed = {
            "orders": ("/orders/",),
            "questions": ("/questions/",),
            "shipments": ("/shipments/",),
            "messages": ("/messages/packs/",),
            "claims_returns": (
                "/post-purchase/v1/claims/",
                "/post-purchase/v2/claims/",
                "/orders/",
            ),
            "full_withdrawals": ("/stock/fulfillment/operations/",),
        }
        if (
            parsed.scheme
            or parsed.netloc
            or not parsed.path.startswith(allowed.get(self.source, ()))
        ):
            raise ValueError("read is outside onboarding source scope")
        for key, values in parse_qs(parsed.query).items():
            if key in {"seller", "seller_id"} and values != [self.seller]:
                raise ValueError("onboarding query seller mismatch")

    async def check_dates(self, path: str) -> None:
        params = parse_qs(urlsplit(path).query)
        bounds = {
            key: values
            for key, values in params.items()
            if key
            in {
                "date_from",
                "date_to",
                "order.date_created.from",
                "order.date_created.to",
                "order.date_last_updated.from",
                "order.date_last_updated.to",
            }
        }
        if not bounds:
            return
        plan = await self.db[PLAN_COLLECTION].find_one(
            {"_id": self.seller, "seller_id": self.seller, "policy_version": POLICY_VERSION}
        )
        if plan is None:
            raise ValueError("missing plan range authority")
        start = plan["date_from"]
        end = max(plan["cutoff"], self.now()) if self.incremental else plan["cutoff"]
        for values in bounds.values():
            if len(values) != 1:
                raise ValueError("ambiguous provider range")
            value = datetime.fromisoformat(values[0].replace("Z", "+00:00"))
            # Full day boundaries and order hour-precision searches expand only
            # source query edges; downstream writers retain exact half-open bounds.
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            if not start - timedelta(days=1) <= value <= end + timedelta(days=1):
                raise ValueError("provider range lies outside persisted policy")

    async def charge(self) -> None:
        if self.work_intent is not None:
            if not self.incremental or self._work_receipt is None:
                raise HistoryPolicyWaitError("work requires its maintenance receipt")
            try:
                await self.work_intent.assert_live(self.db, self.now())
            except HistoryWorkWaitError:
                raise HistoryPolicyWaitError("work ownership unavailable") from None
        if self.source not in SOURCES or not await seller_eligible(self.db, self.seller):
            raise HistoryPolicyWaitError("account is not eligible for acquisition")
        snapshot = await self.db[PLAN_COLLECTION].find_one({"_id": self.seller})
        if snapshot is None:
            raise HistoryPolicyWaitError("missing onboarding authority")
        if self.work_intent is not None and not self._work_policy_available(snapshot):
            raise HistoryPolicyWaitError("work policy or counters unavailable")
        trace = history_request_trace(snapshot, self.source, incremental=self.incremental)
        if self.work_intent is not None and trace is None:
            raise HistoryPolicyWaitError("work execution unavailable")
        execution = snapshot.get("execution_id")
        self._execution_filter = {"execution_id": execution}
        phase = "maintenance" if self.incremental else "initial"
        self._execution_credit = (
            {f"execution_charged.{execution}.{self.source}.{phase}": 1}
            if trace and self.work_intent is None
            else {}
        )
        if self.incremental:
            await self._charge_incremental()
            return
        result = await self.db[PLAN_COLLECTION].find_one_and_update(
            {
                "_id": self.seller,
                "seller_id": self.seller,
                "policy_version": POLICY_VERSION,
                "state": "active",
                "eligible": True,
                "sources": self.source,
                **self._execution_filter,
                **history_execution_query(self.now()),
                **(
                    {"lease_token": self.lease_token, "lease_until": {"$gt": self.now()}}
                    if self.lease_token
                    else {}
                ),
                "$expr": {
                    "$and": [
                        {
                            "$lt": [
                                f"$budget.{self.source}.consumed",
                                f"$budget.{self.source}.physical_attempts",
                            ]
                        },
                        {"$lt": ["$total_consumed", "$total_budget"]},
                    ]
                },
            },
            {
                "$inc": {
                    f"budget.{self.source}.consumed": 1,
                    "total_consumed": 1,
                    "execution_consumed": 1,
                    **self._execution_credit,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if result is None:
            raise HistoryPolicyWaitError("onboarding authority or budget exhausted")
        self._set_trace(result)

    def _work_policy_available(self, snapshot: dict[str, Any]) -> bool:
        """Bounded work never rolls over or repairs a prepared pilot's counters."""
        day = self.now().astimezone(UTC).date().isoformat()
        policy = snapshot.get("incremental_policy")
        consumed = snapshot.get("incremental_source_consumed")
        return bool(
            isinstance(snapshot.get("execution_id"), str)
            and re.fullmatch(r"[a-f0-9]{32}", snapshot["execution_id"]) is not None
            and isinstance(snapshot.get("execution_until"), datetime)
            and snapshot.get("execution_utc_day") == day
            and snapshot.get("incremental_day") == day
            and isinstance(policy, dict)
            and isinstance(consumed, dict)
            and ("execution_work" not in snapshot or isinstance(snapshot["execution_work"], dict))
            and all(
                type(value) is int and value >= 0
                for value in (
                    snapshot.get("execution_attempt_limit"),
                    snapshot.get("execution_consumed"),
                    snapshot.get("incremental_consumed"),
                    consumed.get(self.source),
                    policy.get("max_daily_total"),
                    policy.get("max_daily_source"),
                )
            )
            and history_execution_allowed(snapshot, now=self.now())
        )

    async def _charge_incremental(self) -> None:
        day = self.now().astimezone(UTC).date().isoformat()
        owned = {
            "_id": self.seller,
            "seller_id": self.seller,
            "policy_version": POLICY_VERSION,
            "state": "active",
            "eligible": True,
            "sources": self.source,
            **self._execution_filter,
            **history_execution_query(self.now()),
            **(
                {"lease_token": self.lease_token, "lease_until": {"$gt": self.now()}}
                if self.lease_token
                else {}
            ),
        }
        if self.work_intent is not None:
            owned.update(
                {
                    "authority.kind": "account_link_policy",
                    "execution_until": {"$gt": self.now()},
                    "execution_utc_day": self.now().astimezone(UTC).date().isoformat(),
                    "execution_attempt_limit": {"$type": ["int", "long"], "$gte": 0},
                    "execution_consumed": {"$type": ["int", "long"], "$gte": 0},
                    "incremental_day": day,
                    "incremental_consumed": {"$type": ["int", "long"], "$gte": 0},
                    f"incremental_source_consumed.{self.source}": {
                        "$type": ["int", "long"],
                        "$gte": 0,
                    },
                    "incremental_policy.max_daily_total": {"$type": ["int", "long"], "$gte": 0},
                    "incremental_policy.max_daily_source": {"$type": ["int", "long"], "$gte": 0},
                    f"execution_work.{self._work_nonce}": {"$exists": False},
                }
            )
            owned["$and"].append(
                {
                    "$or": [
                        {"execution_work": {"$exists": False}},
                        {"execution_work": {"$type": "object"}},
                    ]
                }
            )
        # Reset only the policy's DAILY incremental budget. Initial acquisition
        # budget/progress never resets; persisted standing policy authorizes
        # subsequent bounded maintenance without monthly prompts.
        if self.work_intent is None:
            await self.db[PLAN_COLLECTION].update_one(
                {**owned, "incremental_day": {"$ne": day}},
                {
                    "$set": {
                        "incremental_day": day,
                        "incremental_consumed": 0,
                        "incremental_source_consumed": dict.fromkeys(SOURCES, 0),
                    }
                },
            )
        result = await self.db[PLAN_COLLECTION].find_one_and_update(
            {
                **owned,
                "incremental_day": day,
                "$expr": {
                    "$and": [
                        {"$lt": ["$incremental_consumed", "$incremental_policy.max_daily_total"]},
                        {
                            "$lt": [
                                f"$incremental_source_consumed.{self.source}",
                                "$incremental_policy.max_daily_source",
                            ]
                        },
                    ]
                },
            },
            {
                "$inc": {
                    "incremental_consumed": 1,
                    f"incremental_source_consumed.{self.source}": 1,
                    "execution_consumed": 1,
                    **self._execution_credit,
                },
                **(
                    {"$set": {f"execution_work.{self._work_nonce}": self._work_receipt}}
                    if self.work_intent is not None
                    else {}
                ),
            },
            return_document=ReturnDocument.AFTER,
        )
        if result is None:
            raise HistoryPolicyWaitError("incremental policy authority or daily budget exhausted")
        self._set_trace(result)

    def _set_trace(self, plan: dict[str, Any]) -> None:
        self._charged_plan = plan
        trace = history_request_trace(plan, self.source, incremental=self.incremental)
        self.trace_headers = {"X-Zeler-History-Trace": trace} if trace else {}
        if self.work_intent is not None and self._work_nonce is not None:
            self.trace_headers["X-Zeler-History-Work"] = self._work_nonce

    def _validate_dispatch_window(self) -> None:
        # No awaited Mongo work may follow pacing before starting the RPC. The
        # gateway rechecks current persisted authority after broker/token awaits.
        if not history_execution_allowed(self._charged_plan, now=self.now(), charged=True):
            raise HistoryPolicyWaitError("history execution window ended after pacing")

    async def fetch_resource(self, **kwargs: Any) -> Any:
        if self.work_intent is not None:
            # A delivery owns one wrapper, but its nested callers must also keep
            # nonce/receipt/headers local to a physical attempt across pacing.
            async with self._work_lock:
                return await self._fetch_resource(**kwargs)
        return await self._fetch_resource(**kwargs)

    def _prepare_work_receipt(self, path: str) -> None:
        if self.work_intent is not None:
            self._work_nonce = uuid4().hex
            self._work_receipt = {**self.work_intent.receipt(path), "credit": 1, "sent": 0}

    async def _fetch_resource(self, **kwargs: Any) -> Any:
        seller_id, path = kwargs["seller_id"], kwargs["path"]
        request_timeout = kwargs.get("request_timeout", 10)
        if str(seller_id) != self.seller:
            raise ValueError("onboarding seller mismatch")
        self.check_path(path)
        await self.check_dates(path)
        if self.work_intent is not None and not hasattr(self.inner, "fetch_resource_once"):
            raise HistoryPolicyWaitError("single physical work attempt is required")
        self._prepare_work_receipt(path)
        await self.charge()
        physical = await admit_paced_dispatch(self.inner)
        self._validate_dispatch_window()
        if self.work_intent is not None and not callable(
            getattr(physical, "fetch_resource_once", None)
        ):
            # A pacing facade may expose once even when its physical client does
            # not. Keep the charged attempt, but never fall back to hidden retries.
            raise HistoryPolicyWaitError("single physical work attempt is required")
        method = getattr(physical, "fetch_resource_once", physical.fetch_resource)
        async with history_policy_dispatch(), asyncio.timeout(request_timeout):
            return await method(
                seller_id=seller_id,
                path=path,
                **({"headers": self.trace_headers} if self.trace_headers else {}),
            )

    async def request(self, **kwargs: Any) -> Any:
        if self.work_intent is not None:
            async with self._work_lock:
                return await self._request(**kwargs)
        return await self._request(**kwargs)

    async def _request(self, **kwargs: Any) -> Any:
        if kwargs.get("method") != "GET" or str(kwargs.get("seller_id")) != self.seller:
            raise ValueError("onboarding request must be read-only for its seller")
        self.check_path(kwargs["path"])
        await self.check_dates(kwargs["path"])
        self._prepare_work_receipt(kwargs["path"])
        await self.charge()
        physical = await admit_paced_dispatch(self.inner)
        self._validate_dispatch_window()
        kwargs["headers"] = {
            **dict(kwargs.get("headers") or {}),
            **self.trace_headers,
            "X-Zeler-Proxy-Retry": "disabled",
        }
        timeout = kwargs.pop("request_timeout", 10)
        async with history_policy_dispatch(), asyncio.timeout(timeout):
            response = await physical.request(**kwargs)
        if response.headers.get("X-Zeler-Upstream-Attempts") != "1":
            raise ValueError("single physical attempt metadata is required")
        return response

    async def fetch_resource_once(self, **kwargs: Any) -> Any:
        return await self.fetch_resource(**kwargs)


class HistoryOnboardingWorker:
    def __init__(
        self,
        db: Any,
        discovery: Any,
        detail: Any,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        allowed_sellers: frozenset[str] | None = None,
    ) -> None:
        self.db, self.discovery, self.detail, self.now = db, discovery, detail, now
        self._indexes_ready = False
        self.allowed_sellers = validate_history_sellers(allowed_sellers)

    def queue(self, seller: str, models: frozenset[str]) -> FormulaRecoveryQueue:
        return FormulaRecoveryQueue(
            self.db,
            allowed_sellers=frozenset({seller}),
            enabled_models=models,
            max_active_jobs_per_seller=4,
            policy_authority=POLICY_VERSION,
            now=self.now,
        )

    async def process_once(self) -> str:
        now = self.now()
        if not self._indexes_ready:
            await self.queue("0", frozenset({"orders", "questions", "shipments"})).ensure_indexes()
            await self.db[PLAN_COLLECTION].create_index(
                [("policy_version", 1), ("next_cycle_at", 1)], name="onboarding_due"
            )
            self._indexes_ready = True
        token = uuid4().hex
        plan = await self.db[PLAN_COLLECTION].find_one_and_update(
            {
                "policy_version": POLICY_VERSION,
                "state": "active",
                "eligible": True,
                **history_execution_query(now),
                **(
                    {"seller_id": {"$in": sorted(self.allowed_sellers)}}
                    if self.allowed_sellers is not None
                    else {}
                ),
                "next_cycle_at": {"$lte": now},
                "$or": [{"lease_until": {"$exists": False}}, {"lease_until": {"$lte": now}}],
            },
            {"$set": {"lease_token": token, "lease_until": now + timedelta(minutes=6)}},
            sort=[("next_cycle_at", 1), ("_id", 1)],
            return_document=ReturnDocument.AFTER,
        )
        if plan is None:
            return "idle"
        seller = plan["seller_id"]
        owned = {"_id": seller, "lease_token": token}
        heartbeat = asyncio.create_task(self._heartbeat(owned))
        try:
            if not await seller_eligible(self.db, seller):
                await self.db[PLAN_COLLECTION].update_one(
                    owned, {"$set": {"onboarding_status": "temporarily_inaccessible"}}
                )
                return "processed"
            sources = plan.get("sources", list(SOURCES))
            if (
                not isinstance(sources, list)
                or not sources
                or any(not isinstance(source, str) or source not in SOURCES for source in sources)
                or len(set(sources)) != len(sources)
            ):
                await self.db[PLAN_COLLECTION].update_one(
                    owned,
                    {
                        "$set": {
                            "onboarding_status": "temporarily_inaccessible",
                            "onboarding_reason": "source_policy_invalid",
                        }
                    },
                )
                return "processed"
            linked_at = plan.get("last_linked_at")
            if isinstance(linked_at, datetime) and linked_at != plan.get("last_relink_handled_at"):
                # Only a NEW legitimate OAuth link can re-arm access failures.
                # Restarts cannot reset attempts, and detail failures stay in
                # their per-record partial recovery path. Heads remain intact.
                await self.db["sheets_formula_recovery_jobs"].update_many(
                    {
                        "seller_id": seller,
                        "policy_authority": POLICY_VERSION,
                        "state": "failed",
                        "failure_reason": "source_rejected",
                        "updated_at": {"$lt": linked_at},
                    },
                    {
                        "$set": {"state": "pending", "attempts": 0, "available_at": self.now()},
                        "$unset": {"failure_reason": ""},
                    },
                )
                await self.db[PLAN_COLLECTION].update_one(
                    owned, {"$set": {"last_relink_handled_at": linked_at}}
                )
            from zeler_sheets.devoluciones_runner import renew_due_certificates

            renewal = await renew_due_certificates(
                self.db, seller, now=self.now, max_count=20, seconds=10
            )
            await self.db[PLAN_COLLECTION].update_one(
                owned, {"$set": {"certificate_renewal": {**renewal, "updated_at": self.now()}}}
            )
            source = sources[plan.get("source_cursor", 0) % len(sources)]
            gateway = PlanBudgetGateway(
                self.db, self.discovery, seller, source, lease_token=token, now=self.now
            )
            detail = PlanBudgetGateway(
                self.db, self.detail, seller, source, lease_token=token, now=self.now
            )
            previous_source = plan.get("onboarding_sources", {}).get(source, {})
            try:
                retry_at = previous_source.get("next_attempt_at")
                if isinstance(retry_at, datetime) and self.now() < retry_at:
                    result = previous_source
                else:
                    result = await self.advance_source(plan, source, gateway, detail)
            except HistoryPolicyWaitError:
                result = {**previous_source, "state": "pending", "reason": "policy_wait"}
            except RecoveryCapacityError:
                result = {"state": "pending", "reason": "capacity"}
            except Exception as error:  # noqa: BLE001 - isolate each durable source lane
                # Persist only exception type, never provider payload/message/PII.
                failures = previous_source.get("consecutive_failures", 0) + 1
                delay = min(900, 30 * 2 ** min(failures, 5))
                if isinstance(error, GatewayRateLimitError):
                    header = error.response.headers.get("Retry-After", "")
                    if header.isascii() and header.isdecimal():
                        delay = max(1, int(header))
                result = {
                    "state": "pending",
                    "reason": type(error).__name__,
                    "consecutive_failures": failures,
                    "next_attempt_at": self.now() + timedelta(seconds=delay),
                }
                if isinstance(error, ValueError) and "budget exhausted" in str(error):
                    result["state"] = "blocked"
                    result["reason"] = (
                        "daily_budget_exhausted"
                        if gateway.incremental or detail.incremental
                        else "initial_budget_exhausted"
                    )
                    result["required_action"] = (
                        "wait_next_utc_day"
                        if gateway.incremental or detail.incremental
                        else "review_persisted_policy_budget"
                    )
                    if gateway.incremental or detail.incremental:
                        result["next_attempt_at"] = (self.now() + timedelta(days=1)).replace(
                            hour=0, minute=0, second=0, microsecond=0
                        )
            await self.db[PLAN_COLLECTION].update_one(
                owned,
                {
                    "$set": {f"onboarding_sources.{source}": {**result, "updated_at": self.now()}},
                    "$inc": {"source_cursor": 1},
                },
            )
            stored = await self.db[PLAN_COLLECTION].find_one({"_id": seller})
            stored_sources = (stored or {}).get("onboarding_sources", {})
            entries = [stored_sources[name] for name in sources if name in stored_sources]
            statuses = [entry.get("state") for entry in entries]
            observations = any(
                value in {"ready_with_observations", "blocked", "failed"} for value in statuses
            )
            useful = any(
                entry.get("state") == "ready"
                or entry.get("persisted", 0) > 0
                or entry.get("completed_units", 0) > 0
                or (entry.get("partial") or {}).get("persisted", 0) > 0
                for entry in entries
            )
            status = "running"
            if observations:
                status = "ready_with_observations" if useful else "running_with_observations"
            if (
                len(statuses) == len(sources)
                and not useful
                and all(value in {"blocked", "failed"} for value in statuses)
            ):
                status = "temporarily_inaccessible"
            if len(statuses) == len(sources) and all(value == "ready" for value in statuses):
                status = "ready"
            await self.db[PLAN_COLLECTION].update_one(
                owned, {"$set": {"onboarding_status": status, "updated_at": self.now()}}
            )
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
            await self.db[PLAN_COLLECTION].update_one(
                owned,
                {
                    "$set": {"next_cycle_at": self.now() + timedelta(seconds=5)},
                    "$unset": {"lease_token": "", "lease_until": ""},
                },
            )
        return "processed"

    async def _heartbeat(self, owned: dict[str, Any]) -> None:
        while True:
            await asyncio.sleep(30)
            result = await self.db[PLAN_COLLECTION].update_one(
                owned, {"$set": {"lease_until": self.now() + timedelta(minutes=6)}}
            )
            if not result.matched_count:
                return

    def _owned(self, plan: dict[str, Any]) -> dict[str, Any]:
        return {
            "_id": plan["seller_id"],
            **({"lease_token": plan["lease_token"]} if plan.get("lease_token") else {}),
        }

    async def _advance_periodic_messages(self, plan: dict[str, Any], detail: Any) -> dict[str, Any]:
        """Rotate old packs without depending on order modification events.

        No documented chronological order permits skipping old pages. Every
        visited pack starts at offset0, but only40 frozen targets and2 pages are
        admitted per turn. The separate durable cursor survives restart, quota
        waits and partial initial acquisition. A sweep freezes its message-date
        interval; messages arriving during it are acquired by the next sweep.
        """
        from zeler_sheets.onboarding_sources import collect_pack_messages

        now, cutoff = self.now(), plan["cutoff"]
        state = dict(plan.get("message_periodic_recovery") or {})
        checkpoint = state.get("checkpoint")
        wait_until = state.get("next_sweep_at")
        if isinstance(wait_until, datetime) and now < wait_until:
            return self._periodic_message_result(plan, state)
        if state.get("sweep_complete"):
            # Advance a fixed message-date window, not the order creation range.
            state = {
                "sweep_start": state["sweep_end"] - timedelta(minutes=5),
                "sweep_end": now,
                "packs_completed": 0,
                "persisted": 0,
                "issue_count": 0,
            }
            checkpoint = None
        if not state:
            state = {
                "sweep_start": max(plan["date_from"], cutoff - timedelta(minutes=5)),
                "sweep_end": now,
                "packs_completed": 0,
                "persisted": 0,
                "issue_count": 0,
            }
        if checkpoint and checkpoint.get("discovery_complete"):
            state["after_pack"] = checkpoint["target_ids"][-1]
            state["packs_completed"] += len(checkpoint["target_ids"])
            state["persisted"] += checkpoint.get("persisted", 0)
            state["issue_count"] += checkpoint.get("issue_count", 0)
            checkpoint = None
        packs = sorted(
            {
                str(value)
                for value in await self.db.orders.distinct(
                    "meli_pack_id", {"seller_id": plan["seller_id"]}
                )
                if value and str(value).isascii() and str(value).isdecimal()
            }
        )
        remaining = [pack for pack in packs if pack > state.get("after_pack", "")]
        if not remaining and not checkpoint:
            state.update(
                sweep_complete=True,
                state="awaiting_next_sweep",
                next_sweep_at=now + timedelta(minutes=15),
            )
            state.pop("checkpoint", None)
        else:
            detail.incremental = True
            try:
                result = await collect_pack_messages(
                    db=self.db,
                    gateway=detail,
                    seller_id=plan["seller_id"],
                    targets=tuple(remaining[:MESSAGE_PERIODIC_BATCH]),
                    start=state["sweep_start"],
                    end=state["sweep_end"],
                    max_requests=MESSAGE_PERIODIC_REQUESTS,
                    checkpoint=checkpoint,
                )
            except ValueError as error:
                if "budget exhausted" not in str(error):
                    raise
                # Only this maintenance lane waits; initial history still runs
                # on its alternating turn under its own unchanged authority.
                state.update(
                    state="waiting_daily_budget",
                    reason="daily_budget_exhausted",
                    next_sweep_at=(now + timedelta(days=1)).replace(
                        hour=0, minute=0, second=0, microsecond=0
                    ),
                )
            else:
                state.update(
                    checkpoint=result["checkpoint"],
                    state="running",
                    reason=result.get("blocked_reason"),
                    sweep_complete=False,
                )
                state.pop("next_sweep_at", None)
                if result.get("blocked_reason") == "daily_budget_exhausted":
                    state.update(
                        state="waiting_daily_budget",
                        next_sweep_at=(now + timedelta(days=1)).replace(
                            hour=0, minute=0, second=0, microsecond=0
                        ),
                    )
                if result["discovery_complete"]:
                    completed = state.pop("checkpoint")
                    state["after_pack"] = completed["target_ids"][-1]
                    state["packs_completed"] += len(completed["target_ids"])
                    state["persisted"] += completed.get("persisted", 0)
                    state["issue_count"] += completed.get("issue_count", 0)
                    if not any(pack > state["after_pack"] for pack in packs):
                        state.update(
                            sweep_complete=True,
                            state="awaiting_next_sweep",
                            next_sweep_at=now + timedelta(minutes=15),
                        )
        await self.db[PLAN_COLLECTION].update_one(
            self._owned(plan), {"$set": {"message_periodic_recovery": state}}
        )
        return self._periodic_message_result(plan, state)

    def _periodic_message_result(
        self, plan: dict[str, Any], state: dict[str, Any]
    ) -> dict[str, Any]:
        previous = dict(plan.get("onboarding_sources", {}).get("messages", {}))
        previous.update(
            state=previous.get("state", "running"),
            periodic_recovery=message_periodic_progress({"message_periodic_recovery": state}),
        )
        if state.get("persisted") and previous["state"] not in {"ready", "ready_with_observations"}:
            previous["state"] = "ready_with_observations"
        previous.setdefault("coverage_complete", False)
        return previous

    async def advance_source(
        self, plan: dict[str, Any], source: str, gateway: Any, detail: Any
    ) -> dict[str, Any]:
        seller, start, cutoff = plan["seller_id"], plan["date_from"], plan["cutoff"]
        plan_id = f"pilot-12m:{cutoff.isoformat(timespec='milliseconds')}"
        if source in {"orders", "questions"}:
            queue = self.queue(seller, frozenset({source}))
            requests = (
                [
                    OrderHistoryRecoveryRequest(seller, plan_id, chunk.start, chunk.end)
                    for chunk in HistoryPlanner(cutoff=cutoff.astimezone(UTC), months=12)
                    .plan_for("orders")
                    .resume(completed_ids=())
                ]
                if source == "orders"
                else [QuestionScanRecoveryRequest(seller, plan_id, start, cutoff)]
            )
            for request in requests:
                if await queue.collection.find_one({"_id": request.key}) is None:
                    # Capacity never prevents draining already admitted work.
                    with suppress(RecoveryCapacityError):
                        await queue.enqueue(request, reopen_terminal=False)
                    break
            worker = FormulaRecoveryWorker(
                db=self.db, queue=queue, lane="ranges", gateway=gateway, detail_gateway=detail
            )
            await (
                HistoryOrdersWorker(worker)
                if source == "orders"
                else HistoryQuestionsWorker(worker)
            ).process_once()
            jobs = await queue.collection.find(
                {"_id": {"$in": [request.key for request in requests]}}
            ).to_list(length=len(requests))
            partial_result = None
            for failed_job in jobs:
                if failed_job.get("state") == "failed" and not failed_job.get("partial_done"):
                    from zeler_sheets.partial_history import advance_partial_history

                    partial_result = await advance_partial_history(
                        db=self.db, worker=worker, job=failed_job, max_details=20
                    )
                    if partial_result.get("complete"):
                        await queue.collection.update_one(
                            {"_id": failed_job["_id"], "state": "failed"},
                            {"$set": {"partial_done": True}},
                        )
                    break
            completed = sum(job.get("state") == "completed" for job in jobs)
            failed = sum(job.get("state") == "failed" for job in jobs)
            result = {
                "state": "ready"
                if completed == len(requests)
                else "ready_with_observations"
                if failed
                else "running",
                "completed_units": completed,
                "pending_units": len(requests) - completed - failed,
                "failed_units": failed,
                **({"partial": partial_result, "exact": False} if partial_result else {}),
            }
            # After the fixed historical cut, bounded scans only. Watermark is
            # advanced by the existing store after durable ID admission.
            if self.now() >= cutoff + timedelta(minutes=15):
                live_queue = self.queue(seller, frozenset({"orders", "questions"}))
                gateway.incremental = True
                detail.incremental = True
                if source == "orders":
                    await ModificationScanWorker(
                        ModificationScanStore(self.db, live_queue, now=self.now),
                        gateway,
                        sellers=frozenset({seller}),
                        now=self.now,
                    ).process_once()
                else:
                    watermark = plan.get("question_watermark", cutoff)
                    end = min(self.now(), watermark + timedelta(days=1))
                    await live_queue.enqueue(
                        RecoveryRequest(
                            seller, "questions", max(start, watermark - timedelta(minutes=5)), end
                        ),
                        reopen_terminal=False,
                    )
                    await self.db[PLAN_COLLECTION].update_one(
                        {**self._owned(plan), "question_watermark": plan.get("question_watermark")},
                        {"$set": {"question_watermark": end}},
                    )
                await FormulaRecoveryWorker(
                    db=self.db,
                    queue=live_queue,
                    lane="ids" if source == "orders" else "ranges",
                    gateway=gateway,
                    detail_gateway=detail,
                ).process_once()
            return result
        if source == "shipments":
            queue = self.queue(seller, frozenset({"shipments"}))
            identities = await self.db.orders.distinct(
                "shipment_id", {"seller_id": seller, "shipment_id": {"$ne": None}}
            )
            identities = sorted(
                {
                    str(value)
                    for value in identities
                    if str(value).isascii() and str(value).isdecimal()
                }
            )
            shipment_keys = []
            for offset in range(0, len(identities), 100):
                shipment_request = ShipmentIdsRecoveryRequest(
                    seller, tuple(identities[offset : offset + 100])
                )
                shipment_keys.append(shipment_request.key)
                job = await queue.collection.find_one({"_id": shipment_request.key})
                if job is None:
                    with suppress(RecoveryCapacityError):
                        await queue.enqueue(shipment_request, reopen_terminal=False)
                    break
            await FormulaRecoveryWorker(
                db=self.db, queue=queue, lane="ids", gateway=gateway, detail_gateway=detail
            ).process_once()
            jobs = (
                await queue.collection.find({"_id": {"$in": shipment_keys}}).to_list(
                    length=len(shipment_keys)
                )
                if shipment_keys
                else []
            )
            completed = sum(job.get("state") == "completed" for job in jobs)
            failed = sum(job.get("state") == "failed" for job in jobs)
            dependencies_ready = (
                plan.get("onboarding_sources", {}).get("orders", {}).get("state") == "ready"
            )
            return {
                "state": "ready_with_observations"
                if failed
                else "ready"
                if dependencies_ready and completed == len(shipment_keys)
                else "pending",
                "known_identities": len(identities),
                "completed_units": completed,
                "failed_units": failed,
                "pending_units": len(shipment_keys) - completed - failed,
                "coverage_complete": dependencies_ready
                and not failed
                and completed == len(shipment_keys),
                "reason": None if dependencies_ready else "order_dependencies_unknown",
            }
        if source == "claims_returns":
            from zeler_sheets.devoluciones_runner import advance_onboarding_devoluciones

            windows = plan.get("claims_windows")
            if windows is None:
                windows = [
                    {
                        "start": start + timedelta(days=index * 10),
                        "end": min(cutoff, start + timedelta(days=(index + 1) * 10)),
                    }
                    for index in range(((cutoff - start).days + 9) // 10)
                ]
                await self.db[PLAN_COLLECTION].update_one(
                    self._owned(plan), {"$set": {"claims_windows": windows}}
                )
            incremental = False
            if not windows:
                watermark = plan.get("claims_watermark", cutoff)
                if self.now() < watermark + timedelta(minutes=15):
                    return {
                        "state": "ready_with_observations"
                        if plan.get("claims_failed_units")
                        else "ready",
                        "completed_units": plan.get("claims_completed_units", 0),
                        "failed_units": plan.get("claims_failed_units", 0),
                    }
                incremental = True
                detail.incremental = True
                window = {
                    "start": watermark - timedelta(minutes=5),
                    "end": min(self.now(), watermark + timedelta(hours=23)),
                }
                await self.db[PLAN_COLLECTION].update_one(
                    self._owned(plan),
                    {
                        "$set": {
                            "incremental_scopes.claims_returns": {
                                "date_from": window["start"],
                                "date_to": window["end"],
                                "policy_version": POLICY_VERSION,
                            }
                        }
                    },
                )
                plan = await self.db[PLAN_COLLECTION].find_one(self._owned(plan))
            else:
                window = windows[0]
            result = await advance_onboarding_devoluciones(
                self.db,
                plan,
                gateway=detail,
                start=window["start"],
                end=window["end"],
                now=self.now,
            )
            terminal = result.get("state") in {"completed", "failed", "aborted", "expired"}
            if terminal:
                failed = result.get("state") != "completed"
                if (
                    result.get("reason") == "physical_budget_exceeded"
                    and window["end"] - window["start"] > timedelta(hours=1)
                    and not incremental
                ):
                    middle = window["start"] + (window["end"] - window["start"]) / 2
                    windows = [
                        {"start": window["start"], "end": middle},
                        {"start": middle, "end": window["end"]},
                        *windows[1:],
                    ]
                    await self.db[PLAN_COLLECTION].update_one(
                        self._owned(plan), {"$set": {"claims_windows": windows}}
                    )
                    return {
                        "state": "running",
                        "reason": "dense_interval_subdivided",
                        "pending_units": len(windows),
                    }
                updates = {"claims_windows": windows[1:] if not incremental else windows}
                if incremental:
                    updates["claims_watermark"] = window["end"]
                await self.db[PLAN_COLLECTION].update_one(
                    self._owned(plan),
                    {
                        "$set": updates,
                        "$inc": {
                            "claims_completed_units": int(not failed),
                            "claims_failed_units": int(failed),
                        },
                    },
                )
            result["state"] = (
                "ready_with_observations"
                if result.get("state") in {"failed", "aborted", "expired"}
                else "running"
            )
            result["pending_units"] = len(windows)
            result["incremental"] = incremental
            return result
        from zeler_sheets.onboarding_sources import collect_full_operations, collect_pack_messages

        if source == "messages" and self.now() >= cutoff + timedelta(minutes=15):
            # Do not replace an unfinished initial collector with maintenance.
            # Fair alternating turns let both durable lanes make progress.
            turn = plan.get("message_periodic_turn", 0)
            await self.db[PLAN_COLLECTION].update_one(
                self._owned(plan), {"$inc": {"message_periodic_turn": 1}}
            )
            if turn % 2 == 0:
                return await self._advance_periodic_messages(plan, detail)

        checkpoint = plan.get("collector_checkpoints", {}).get(source)
        interval_start = start
        interval_end = cutoff
        if checkpoint:
            interval_start = datetime.fromisoformat(checkpoint["start"])
            interval_end = datetime.fromisoformat(checkpoint["end"])
            if checkpoint.get("discovery_complete"):
                if source == "full_withdrawals" and interval_end < cutoff:
                    interval_start, interval_end = (
                        interval_end,
                        min(cutoff, interval_end + timedelta(days=59)),
                    )
                    checkpoint = None
                elif self.now() >= interval_end + timedelta(minutes=15):
                    interval_start, interval_end = (
                        interval_end - timedelta(minutes=5),
                        min(self.now(), interval_end + timedelta(days=1)),
                    )
                    checkpoint = None
                else:
                    if (
                        source == "messages"
                        and plan.get("onboarding_sources", {}).get("orders", {}).get("state")
                        != "ready"
                    ):
                        return {
                            "state": "ready_with_observations"
                            if checkpoint.get("persisted")
                            else "pending",
                            "coverage_complete": False,
                            "dependency_reason": "order_dependencies_unknown",
                            "persisted": checkpoint.get("persisted", 0),
                        }
                    return {
                        "state": "ready_with_observations"
                        if checkpoint.get("issue_count") or source == "full_withdrawals"
                        else "ready",
                        "reason": "full_contract_mapping_pending"
                        if source == "full_withdrawals"
                        else None,
                        "persisted": checkpoint.get("persisted", 0),
                    }
        elif source == "full_withdrawals":
            interval_end = min(cutoff, start + timedelta(days=59))
        if source == "messages":
            pack_scope: dict[str, Any] = {"seller_id": seller}
            if interval_end > cutoff:
                detail.incremental = True
                # The provider has no documented date filter or stable append
                # ordering. Bound targets to recent/changed orders, never sweep
                # every historical conversation on each incremental cycle.
                pack_scope["$or"] = [
                    {"date_created": {"$gte": interval_start - timedelta(days=14)}},
                    {"last_updated": {"$gte": interval_start}},
                ]
            packs = await self.db.orders.distinct("meli_pack_id", pack_scope)
            result = await collect_pack_messages(
                db=self.db,
                gateway=detail,
                seller_id=seller,
                targets=tuple(str(value) for value in packs if value),
                start=interval_start,
                end=interval_end,
                max_requests=2,
                checkpoint=checkpoint,
            )
        else:
            if interval_end > cutoff:
                detail.incremental = True
            result = await collect_full_operations(
                db=self.db,
                gateway=detail,
                seller_id=seller,
                start=interval_start,
                end=interval_end,
                max_requests=2,
                checkpoint=checkpoint,
                now=self.now(),
            )
        await self.db[PLAN_COLLECTION].update_one(
            self._owned(plan), {"$set": {f"collector_checkpoints.{source}": result["checkpoint"]}}
        )
        result.pop("checkpoint", None)
        if (
            source == "messages"
            and plan.get("onboarding_sources", {}).get("orders", {}).get("state") != "ready"
        ):
            result["coverage_complete"] = False
            result["state"] = "ready_with_observations" if result.get("persisted") else "pending"
            result["dependency_reason"] = "order_dependencies_unknown"
            return result
        result["state"] = (
            "ready_with_observations"
            if result.get("blocked_reason") or result.get("issue_count")
            else "ready"
            if result.get("coverage_complete")
            else "running"
        )
        return result
