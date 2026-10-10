"""A claim Mercado Libre lists but forbids must not stall the ordinary tail.

2026-10-09/10 (seller 82453304): the daily tail for 2026-07-31..08-10 failed in
the same minute two days running. The window inventory listed six claims; the
detail of one of them (stage dispute) answered 403 from Mercado Libre on every
claim endpoint, so the window could never close and coverage froze. Only the
ordinary tail may exclude such a claim, only one per window and only while it
is a small share of the inventory. Operator and pilot runs keep failing closed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from test_devoluciones_reconciliation import (
    END,
    START,
    HydratingSource,
    _claim,
    _fixture,
    _operation,
)

import zeler_sheets.devoluciones_reconciliation as reconciliation_module
from zeler_sheets.devoluciones_reconciliation import (
    DevolucionesReadModelVerificationError,
    InventoryExclusionEvidence,
    InventoryExclusionReason,
    SourceCallRecorder,
)

FORBIDDEN = "519988003"
CAPTURED = datetime(2026, 7, 10, 12, tzinfo=UTC)


def _status_error(status_code: int, *, attempts: str | None = "1") -> httpx.HTTPStatusError:
    # The gateway forwards Mercado Libre's own answer with the single-attempt
    # header; a refusal the gateway makes itself carries no such header.
    request = httpx.Request("GET", "https://gateway.invalid/proxy/meli/post-purchase/v1/claims/1")
    headers = {"X-Zeler-Upstream-Attempts": attempts} if attempts is not None else {}
    response = httpx.Response(status_code, headers=headers, request=request)
    return httpx.HTTPStatusError("upstream refused", request=request, response=response)


class ForbiddenClaimSource(HydratingSource):
    """Two productive claims, closed cancellations and claims whose detail fails."""

    def __init__(
        self,
        *,
        forbidden: tuple[str, ...] = (FORBIDDEN,),
        cancellations: int = 3,
        status_code: int = 403,
        attempts: str | None = "1",
        readable: bool = False,
    ) -> None:
        super().__init__()
        self.forbidden = () if readable else forbidden
        self.status_code = status_code
        self.attempts = attempts
        rows = [
            {
                "id": claim_id,
                "last_updated": f"2026-06-{17 + index:02d}T10:05:00.000Z",
                "date_created": f"2026-06-{17 + index:02d}T10:00:00.000Z",
                "type": "mediations",
                "status": "closed",
            }
            for index, claim_id in enumerate(forbidden)
        ] + [
            {
                "id": f"51998810{index}",
                "last_updated": "2026-06-25T10:05:00.000Z",
                "date_created": "2026-06-25T10:00:00.000Z",
                "type": "cancel_purchase",
                "status": "closed",
            }
            for index in range(cancellations)
        ]
        for page in self.responses:
            page["data"].extend(rows)
            page["paging"]["total"] = len(page["data"])
        if readable:
            # The same inventory, but Mercado Libre now serves the detail.
            for row in rows[: len(forbidden)]:
                self.claims[row["id"]] = _claim() | {
                    key: row[key] for key in ("id", "last_updated", "date_created")
                }
                self.returns[row["id"]] = _fixture("return_v2.json")

    async def get_claim(self, *, seller_id: str, claim_id: str) -> dict[str, Any]:
        if claim_id in self.forbidden:
            self.hydration_calls.append(("claim", claim_id))
            raise _status_error(self.status_code, attempts=self.attempts)
        return await super().get_claim(seller_id=seller_id, claim_id=claim_id)


async def _collect(source: Any, **kwargs: Any) -> Any:
    return await reconciliation_module.collect_devoluciones_snapshot(
        source=source,
        seller_id="82453304",
        start=START,
        end=END,
        captured_at=CAPTURED,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_operator_and_pilot_snapshots_still_fail_closed_on_a_forbidden_claim() -> None:
    """The production failure: a 403 on claim detail ends the whole window."""
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await _collect(ForbiddenClaimSource())

    assert reconciliation_module._private_focused_devoluciones_diagnostic(exc_info.value) == {
        "failure_class": "source_failure",
        "source_stage": "claim_detail",
        "source_family": "client_other",
    }


@pytest.mark.asyncio
async def test_tail_snapshot_excludes_one_claim_whose_detail_mercado_libre_forbids() -> None:
    source = ForbiddenClaimSource()

    snapshot = await _collect(source, exclude_forbidden_claim_details=True)

    assert snapshot.expected_claim_ids == frozenset({"519988001", "519988002"})
    assert (
        InventoryExclusionEvidence(
            claim_id=FORBIDDEN,
            last_updated="2026-06-17T10:05:00.000Z",
            reason=InventoryExclusionReason.CLAIM_DETAIL_FORBIDDEN,
        )
        in snapshot.exclusions
    )
    assert snapshot.counters["excluded_claim_detail_forbidden"] == 1
    assert snapshot.counters["inventory_candidates"] == 6
    # Nothing else is read for a claim whose detail is forbidden.
    assert [call for call in source.hydration_calls if call[1] == FORBIDDEN] == [
        ("claim", FORBIDDEN)
    ]
    # The exclusion is part of the window's source identity.
    readable = await _collect(ForbiddenClaimSource(forbidden=()))
    assert snapshot.read_model_fingerprint == readable.read_model_fingerprint
    assert snapshot.exclusion_fingerprint != readable.exclusion_fingerprint
    assert snapshot.source_fingerprint != readable.source_fingerprint


@pytest.mark.parametrize(
    ("status_code", "attempts"),
    [(401, "1"), (404, "1"), (429, "1"), (500, "1"), (403, None)],
    ids=("unauthorized", "not-found", "throttled", "server", "gateway-own-403"),
)
@pytest.mark.asyncio
async def test_tail_snapshot_tolerates_only_mercado_libre_403_on_claim_detail(
    status_code: int, attempts: str | None
) -> None:
    source = ForbiddenClaimSource(status_code=status_code, attempts=attempts)

    with pytest.raises(httpx.HTTPStatusError):
        await _collect(source, exclude_forbidden_claim_details=True)


@pytest.mark.parametrize(
    ("forbidden", "cancellations"),
    [((FORBIDDEN, "519988004"), 5), ((FORBIDDEN,), 1)],
    ids=("more-than-one", "more-than-a-fifth"),
)
@pytest.mark.asyncio
async def test_tail_snapshot_fails_closed_past_the_forbidden_claim_threshold(
    forbidden: tuple[str, ...], cancellations: int
) -> None:
    # 2 of 9 claims, then 1 of 4 claims (25 %): both look like an access
    # problem rather than one inaccessible claim.
    source = ForbiddenClaimSource(forbidden=forbidden, cancellations=cancellations)

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await _collect(source, exclude_forbidden_claim_details=True)

    assert reconciliation_module._private_focused_devoluciones_diagnostic(exc_info.value)[
        "source_stage"
    ] == ("claim_detail")


async def _revalidate(snapshot: Any, source: Any) -> Any:
    operation = _operation()
    operation.source_fingerprint = snapshot.source_fingerprint

    async def heartbeat() -> None:
        return None

    return await reconciliation_module.revalidate_devoluciones_snapshot(
        source=source,
        snapshot=snapshot,
        operation=operation,
        absolute_deadline=100.0,
        recorder=SourceCallRecorder(),
        heartbeat=heartbeat,
        monotonic=lambda: 1.0,
        now=lambda: CAPTURED,
        exclude_forbidden_claim_details=True,
    )


@pytest.mark.asyncio
async def test_tail_revalidation_requires_the_same_forbidden_claim() -> None:
    snapshot = await _collect(ForbiddenClaimSource(), exclude_forbidden_claim_details=True)

    current = await _revalidate(snapshot, ForbiddenClaimSource())

    assert current.source_fingerprint == snapshot.source_fingerprint
    # A claim that became readable between the passes changes the window.
    with pytest.raises(DevolucionesReadModelVerificationError):
        await _revalidate(snapshot, ForbiddenClaimSource(readable=True))
