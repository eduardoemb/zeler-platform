from __future__ import annotations

PUBLICADOR_BATCH8_SMOKE_ROUTES = [
    "/publicador/dashboard",
    "/publicador/products/new",
    "/publicador/products/new/assets",
    "/publicador/products/new/generate",
    "/publicador/products/new/taxonomy",
    "/publicador/publications",
    "/publicador/publications/<publication_id>",
    "/publicador/publications/<publication_id>/approval",
    "/publicador/publications/<publication_id>/process",
    "/publicador/publications/<publication_id>/validation",
    "/publicador/publications/<publication_id>/publish-review",
    "/publicador/publications/<publication_id>/catalog",
    "/publicador/batches",
    "/publicador/batches/new",
    "/publicador/batches/<batch_id>",
    "/publicador/suggestions",
    "/publicador/logs",
    "/publicador/statistics",
    "/publicador/settings",
]


def build_publicador_smoke_plan(*, pilot_seller_id: str) -> dict[str, object]:
    seller_id = pilot_seller_id.strip()
    if not seller_id:
        raise ValueError("pilot_seller_id is required for Publicador smoke plan")

    return {
        "pilot_seller_id": seller_id,
        "execution_contexts": [
            "authenticated zeler-app session",
            "approved VM/VPC/runtime container",
        ],
        "routes": PUBLICADOR_BATCH8_SMOKE_ROUTES,
        "auth_contract": (
            "Use the zeler-app broker/module-admin flow for admin:publicador; "
            "do not paste credentials into logs."
        ),
        "evidence_contract": (
            "Capture sanitized status, route, and seller-scoped outcome only; "
            "redact credentials and production environment values."
        ),
        "blocked_if": [
            "unauthenticated browser session",
            "local production Mongo access would be required",
            "workspace contains unrelated deploy changes",
        ],
    }
