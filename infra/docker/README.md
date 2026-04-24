# Dev MongoDB

## Purpose

This Compose stack provides the development MongoDB instance for phases P0 through P3.
From P4 onward, the platform target is Eduardo's on-prem MongoDB server per design decision D8.

## Start

```bash
docker compose -f infra/docker/mongo-dev.yml --env-file ../../.env up -d
```

## Stop

```bash
docker compose -f infra/docker/mongo-dev.yml down
```

## Volume persistence

Mongo data is stored in the named volume `zeler-mongo-data`, so data survives container restarts until the volume is removed explicitly.

## Security note

TLS is intentionally disabled in local development.
The container binds only to `127.0.0.1`, and TLS becomes mandatory for the on-prem deployment path defined in D11.
