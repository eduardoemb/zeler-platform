# Design: ZelerData Buybox Load Control

The existing buybox worker already persists price-to-win evidence and leaves missing offers fields unknown. Change only the exact HTTP 404 from `/products/{catalog_product_id}/items` so it does not become a chunk failure. Keep 429, 5xx, transport, malformed identity, ownership and price-to-win failures unchanged. The existing 15-minute buybox snapshot cut bounds demand-driven refresh; no new persistence field is needed.

Extend the seller admission transaction's active-ID subtraction from `item_formula_rows` to `catalog_buybox_snapshots`. Match both seller and read model, retain catalog and small request identities, and use the existing admission revision to serialize concurrent callers. The current 20-job cap stays intact.

Generalize the existing item reconciliation implementation behind item and buybox wrappers. Scope each preview to one seller/read model, include read model in the fingerprint and replacement key, reject live leases and invalid checkpoints, and preserve successful IDs before deriving the unfinished union. The operator CLI accepts a fixed enum for the read model and emits aggregate counts only. No job is deleted.

Rollout uses the running image digests as rollback authority. Stop the worker, preview and execute reconciliation against a stable fingerprint, deploy the API and worker from one verified commit, then observe queue progress, catalog offers 404 rate, DLQ and capacity. If validation fails, stop recovery and restore the compatible prior images while preserving job evidence.
