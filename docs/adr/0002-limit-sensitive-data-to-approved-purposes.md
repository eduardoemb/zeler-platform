# Limit sensitive ZelerData storage to approved purposes

ZelerData persists every Mercado Libre field needed by its approved formulas and
existing product surfaces, including sensitive fields when required, but does
not retain complete API payloads or unused fields. Purpose-complete data remains
available only through its authorized lifecycle and must be encrypted at rest,
isolated by seller, access-controlled, auditable, sanitized from logs, and
deletable; these controls follow functional stabilization but remain a gate for
declaring the stabilization mission complete.
