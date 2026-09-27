# Scheduled refresh delta

## Requirement: bounded default scheduling

When the ZelerData refresh supervisor is enabled for a seller and the scheduled bulk flag is absent or false, it SHALL plan `orders` and `questions` ranges on the configured interval. It SHALL NOT schedule whole-seller inventory, catalog product, buybox or shipment identity sweeps.

### Scenario: default pilot cycle

Given recovery and refresh are enabled and the bulk flag is absent, constructing the supervisor selects only the two range models and does not install the inventory tick.

## Requirement: explicit bulk opt-in

When `ZELERDATA_SCHEDULED_BULK_REFRESH_ENABLED=true`, the supervisor SHALL preserve the previous six-model planner and inventory tick behavior.

### Scenario: measured-capacity environment

Given the flag is true, constructing the supervisor selects all implemented refresh models and wires the inventory tick to the planner.

## Requirement: demand remains available

The scheduled flag SHALL NOT disable formula-triggered recovery or alter existing queue jobs, snapshot freshness, or visible unavailable data.
