from __future__ import annotations

from zeler_publicador.schemas import DashboardSummary, PublicadorSettings


class PublicadorContractService:
    """Batch-1 contract service with safe empty defaults for later parity batches."""

    async def dashboard(self, *, seller_id: str, account_id: str) -> DashboardSummary:
        return DashboardSummary(seller_id=seller_id, account_id=account_id)

    async def settings(self, *, seller_id: str, account_id: str) -> PublicadorSettings:
        return PublicadorSettings(seller_id=seller_id, account_id=account_id)
