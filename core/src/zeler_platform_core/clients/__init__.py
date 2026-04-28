"""HTTP clients shared by zeler-platform services."""

from zeler_platform_core.clients.meli_gateway_client import (
    GatewayRateLimitError,
    MeliGatewayClient,
)

__all__ = ["GatewayRateLimitError", "MeliGatewayClient"]
