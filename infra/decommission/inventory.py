from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LegacyProduct:
    capability: str
    repository: str
    database_names: tuple[str, ...]
    cloud_run_services: tuple[str, ...]
    vm_workloads: tuple[str, ...]
    oauth_app_id: str


@dataclass(frozen=True)
class LegacyInventory:
    products: tuple[LegacyProduct, ...]
    zeler_core_repository: str
    zeler_core_databases: tuple[str, ...]


def legacy_inventory() -> LegacyInventory:
    """Return the Phase 7 legacy inventory as a static, auditable contract.

    This function intentionally performs no network calls and mutates nothing. Operators can use the
    resulting inventory as the starting point for GitHub/GCP/Mongo/Meli manual checks.
    """

    return LegacyInventory(
        products=(
            LegacyProduct(
                capability="SheetSeller",
                repository="sheetsellerappindividual",
                database_names=("sheetsellerapp", "sheetseller_app"),
                cloud_run_services=("sheetseller-api", "sheetseller-vinculacion"),
                vm_workloads=(
                    "sheetseller-notificaciones-producer",
                    "sheetseller-notificaciones-consumer",
                ),
                oauth_app_id="sheetseller",
            ),
            LegacyProduct(
                capability="PublicadorMeli",
                repository="publicadormeli",
                database_names=("publicadormeli",),
                cloud_run_services=("publicadormeli-api",),
                vm_workloads=(),
                oauth_app_id="publicador",
            ),
            LegacyProduct(
                capability="Repricer MeLi",
                repository="repricer-meli",
                database_names=("repricer_app",),
                cloud_run_services=("repricer-api", "repricer-vinculacion"),
                vm_workloads=(
                    "repricer-notificaciones-producer",
                    "repricer-notificaciones-consumer",
                ),
                oauth_app_id="repricer",
            ),
            LegacyProduct(
                capability="Autoreplyia",
                repository="Autoreplyia",
                database_names=("autoreply",),
                cloud_run_services=("autoreply-api", "autoreply-vinculacion"),
                vm_workloads=(
                    "autoreply-notificaciones-producer",
                    "autoreply-notificaciones-consumer",
                ),
                oauth_app_id="autoreply",
            ),
            LegacyProduct(
                capability="FullDockManager",
                repository="fulldockmanager",
                database_names=("fulldock",),
                cloud_run_services=("fulldock-api", "fulldock-vinculacion"),
                vm_workloads=(
                    "fulldock-notificaciones-producer",
                    "fulldock-notificaciones-consumer",
                ),
                oauth_app_id="fulldock",
            ),
        ),
        zeler_core_repository="zeler-core",
        zeler_core_databases=("zeler_core",),
    )
