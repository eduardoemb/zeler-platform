"""Execute persisted formula recovery outside the HTTP calculation path."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from pymongo.errors import PyMongoError

from zeler_sheets.event_persistence import SheetsEventPersistence
from zeler_sheets.formulas.recovery import COOLDOWN, FormulaRecoveryQueue


class FormulaRecoveryWorker:
    def __init__(
        self,
        *,
        db: Any,
        gateway: Any,
        queue: FormulaRecoveryQueue,
        detail_gateway: Any | None = None,
    ) -> None:
        self.db = db
        self.gateway = gateway
        self.detail_gateway = detail_gateway if detail_gateway is not None else gateway
        self.queue = queue

    async def process_one(self) -> bool:
        job = await self.queue.claim()
        if job is None:
            return False
        try:
            async with asyncio.timeout(240):
                if job["read_model"] != "questions":
                    raise ValueError("recovery source not implemented")
                await self._questions(job)
        except httpx.HTTPStatusError as exc:
            transient = exc.response.status_code == 429 or exc.response.status_code >= 500
            await self.queue.finish(
                job,
                succeeded=False,
                retryable=transient,
                failure_reason="source_temporarily_unavailable" if transient else "source_rejected",
            )
        except (httpx.TransportError, TimeoutError):
            await self.queue.finish(
                job,
                succeeded=False,
                retryable=True,
                failure_reason="source_temporarily_unavailable",
            )
        except PyMongoError:
            await self.queue.finish(
                job,
                succeeded=False,
                retryable=True,
                failure_reason="storage_unavailable",
            )
        except ValueError:
            await self.queue.finish(job, succeeded=False, failure_reason="source_incomplete")
        except Exception:  # noqa: BLE001 - never log upstream payloads or credentials.
            await self.queue.finish(job, succeeded=False)
        return True

    async def _questions(self, job: dict[str, Any]) -> None:
        seller_id = job["seller_id"]
        start = _utc(job["date_from"])
        end = _utc(job["date_to"])
        resources: list[dict[str, Any]] = []
        seen: set[str] = set()
        total: int | None = None
        scroll: str | None = None
        while True:
            params = {
                "seller_id": seller_id,
                "api_version": "4",
                "limit": "50",
                "search_type": "scan",
            }
            if scroll is not None:
                params["scroll_id"] = scroll
            page = await self.gateway.fetch_resource(
                seller_id=seller_id, path="/questions/search?" + urlencode(params)
            )
            if not isinstance(page, dict):
                raise ValueError("invalid question search")
            page_total = page.get("total")
            if type(page_total) is not int or not 0 <= page_total <= 10000:
                raise ValueError("question search total unavailable or over budget")
            if total is not None and page_total != total:
                raise ValueError("question search changed during recovery")
            total = page_total
            rows = page.get("questions")
            if not isinstance(rows, list):
                raise ValueError("question search missing results")
            for row in rows:
                if not isinstance(row, dict) or row.get("id") is None:
                    raise ValueError("question search missing identity")
                question_id = str(row["id"])
                if question_id in seen or not question_id.isdecimal():
                    raise ValueError("duplicate or invalid question identity")
                seen.add(question_id)
                created = _date(row.get("date_created"))
                if start <= created < end:
                    detail = await self.detail_gateway.fetch_resource(
                        seller_id=seller_id, path=f"/questions/{question_id}"
                    )
                    if (
                        not isinstance(detail, dict)
                        or str(detail.get("id")) != question_id
                        or str(detail.get("seller_id")) != seller_id
                        or _date(detail.get("date_created")) != created
                    ):
                        raise ValueError("question detail scope mismatch")
                    if detail.get("status") == "ANSWERED" and not isinstance(
                        detail.get("answer"), dict
                    ):
                        raise ValueError("question answer unavailable")
                    resources.append(detail)
            if len(seen) == total:
                break
            if not rows or len(seen) > total:
                raise ValueError("incomplete question search")
            scroll = page.get("scroll_id")
            if not isinstance(scroll, str) or not scroll:
                raise ValueError("question continuation unavailable")

        marker_id = f"{seller_id}:questions"
        # Invalidate before writes: a partial write must not retain prior proof.
        await self.db["sheets_read_model_freshness"].update_one(
            {"_id": marker_id, "seller_id": seller_id},
            {"$set": {"state": "stale", "updated_at": self.queue.now()}},
        )
        writer = SheetsEventPersistence(db=self.db, clock=self.queue.now)
        for resource in resources:
            await writer.persist(
                event_type="questions.updated", seller_id=seller_id, resource=resource
            )
        persisted = (
            await self.db["questions"]
            .find(
                {"seller_id": seller_id, "date_created": {"$gte": start, "$lt": end}},
                {"_id": 1},
            )
            .to_list(length=None)
        )
        if {str(row["_id"]) for row in persisted} != {str(row["id"]) for row in resources}:
            raise ValueError("persisted question inventory differs from authoritative source")
        marker = {
            "_id": marker_id,
            "seller_id": seller_id,
            "read_model": "questions",
            "state": "reconciled",
            "date_from": start,
            "reconciled_until": end,
            "fresh_until": end,
            "updated_at": self.queue.now(),
            "valid_until": self.queue.now() + timedelta(minutes=15),
            "source": "zelerdata_read_model_reconcile",
            "schema_version": 1,
        }
        # Publish proof and terminal job state together, only for the live owner.
        async with (
            await self.db.client.start_session() as session,
            session.start_transaction(),
        ):
            now = self.queue.now()
            finished = await self.queue.collection.update_one(
                self.queue._owned(job, now),
                {
                    "$set": {
                        "state": "completed",
                        "updated_at": now,
                        "available_at": now + COOLDOWN,
                    },
                    "$unset": {"attempt_token": "", "lease_until": "", "failure_reason": ""},
                },
                session=session,
            )
            if finished.matched_count != 1:
                raise ValueError("recovery lease lost before publication")
            await self.db["sheets_read_model_freshness"].replace_one(
                {"_id": marker_id, "seller_id": seller_id},
                marker,
                upsert=True,
                session=session,
            )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _date(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("question date unavailable")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("question date timezone unavailable")
    return parsed.astimezone(UTC)
