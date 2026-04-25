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

## First-time prod Mongo setup (one-time runbook)

Follow this sequence exactly on a clean prod host:

1. Generate the replica-set keyfile:

   ```bash
   bash infra/docker/gen_mongo_keyfile.sh
   ```

2. Set the bootstrap admin credentials in your shell, not in `.env`:

   ```bash
   export MONGO_ADMIN_USER=<distinct-from-dev>
   export MONGO_ADMIN_PASSWORD=<strong-password>
   ```

3. Bring up the prod Mongo container, feeding it the admin credentials via `--env-file`:

   ```bash
   docker compose -f infra/docker/mongo-prod.yml --env-file .env.prod up -d
   ```

   The compose file forwards `MONGO_ADMIN_USER` / `MONGO_ADMIN_PASSWORD` from
   `.env.prod` into the container's `MONGO_INITDB_ROOT_*` env vars. The
   names match what `init_replica_set.py` will read in the next step, so a
   single `.env.prod` is the only source of credentials.

4. Wait until the container is healthy:

   ```bash
   docker compose -f infra/docker/mongo-prod.yml ps
   ```

5. Initialize the replica set and admin user:

   ```bash
   uv run python -m infra.mongo.init_replica_set
   ```

6. Verify the replica set is PRIMARY. The command should print `1`:

   ```bash
   docker exec -it zeler-mongo-prod mongosh --eval 'rs.status().myState'
   ```

7. Set runtime env in `.env.prod` using `.env.prod.example` as the template:

   ```dotenv
   MONGO_URI=mongodb://service-user:pwd@127.0.0.1:27019/zeler_platform_prod?replicaSet=rs0&directConnection=true&authSource=admin
   MONGO_DB=zeler_platform_prod
   ```

8. Apply validators:

   ```bash
   MONGO_URI=$MONGO_URI uv run python -m infra.mongo.apply_validators
   ```

9. Apply seeds:

   ```bash
   MONGO_URI=$MONGO_URI uv run python -m infra.mongo.apply_seeds
   ```

10. Confirm readiness:

    ```bash
    MONGO_URI=$MONGO_URI uv run python -m infra.mongo.readiness
    ```

Warnings:

- The bootstrap `MONGO_ADMIN_*` credentials are SEPARATE from the runtime service-user credentials embedded in `MONGO_URI`. Keep them distinct from each other.
- `MONGO_INIT_URI` defaults to `mongodb://127.0.0.1:27019/?directConnection=true` and rarely needs to be overridden.
- `infra/docker/mongo-keyfiles/` is gitignored — DO NOT commit the keyfile.
- Prod admin credentials MUST differ from dev admin credentials.

## Day-2 ops

- Re-running validators and seeds is idempotent; both fail loud if `MONGO_URI` is unset.
- Re-running `init_replica_set.py` is idempotent. It handles `AlreadyInitialized=23` and `UserAlreadyExists=51003` as success.
- Stopping prod keeps data in the named volume `zeler-mongo-prod-data`:

  ```bash
  docker compose -f infra/docker/mongo-prod.yml down
  ```

- Wiping prod is destructive. This removes the `zeler-mongo-prod-data` volume:

  ```bash
  docker compose -f infra/docker/mongo-prod.yml down -v
  ```

## Rollback and recovery

### Full rollback (clean slate)

If the prod Mongo bring-up went sideways and you need to start over from a known-good
git state, use this sequence in order:

1. Stop and wipe the container plus its data volume:

   ```bash
   docker compose -f infra/docker/mongo-prod.yml down -v
   ```

2. Remove the locally-generated keyfile so the next bring-up regenerates it:

   ```bash
   rm -f infra/docker/mongo-keyfiles/rs0.key
   ```

3. Revert the change that introduced the broken state. Replace `<sha>` with the
   bad commit (use `git log --oneline infra/docker/ infra/mongo/ | head` to find it):

   ```bash
   git revert <sha>
   ```

4. Re-run the first-time setup runbook from step 1.

### Recovery: replica set initialized with the wrong member host

If `init_replica_set.py` ran with a stale `MONGO_RS_MEMBER_HOST` (e.g. `localhost:27017`
instead of `127.0.0.1:27019`), the RS will be technically alive but the driver may
fail to connect because the advertised member host does not match the URI.

Reconfigure the RS in place without losing data:

```bash
docker exec -it zeler-mongo-prod mongosh \
  -u "$MONGO_ADMIN_USER" -p "$MONGO_ADMIN_PASSWORD" --authenticationDatabase admin \
  --eval '
    cfg = rs.conf();
    cfg.members[0].host = "127.0.0.1:27019";
    rs.reconfig(cfg, { force: true });
    rs.status().myState
  '
```

The final line prints `1` when the node is back to PRIMARY with the corrected host.
