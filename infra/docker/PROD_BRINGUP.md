# Production MongoDB Bring-Up Validation

Use this runbook for day-1 validation of the production single-node MongoDB replica set. Keep filled evidence in a copied file named `infra/docker/PROD_BRINGUP_EVIDENCE_<date>.md`; those operator artifacts are intentionally ignored by git.

## 1. Pre-flight

- Confirm the deployment commit range you are validating.
- Populate `.env.prod` from `.env.prod.example` with `MONGO_ADMIN_USER`, `MONGO_ADMIN_PASSWORD`, and any required overrides.
- Do not set `MONGO_RS_MEMBER_HOST` for the standard single-host loopback layout; `init_replica_set.py` defaults it to `localhost:27017`. Override it only for multi-host or non-loopback deployments.
- Confirm port `127.0.0.1:27019` is available on the target host.
- Generate the MongoDB keyfile if the host does not already have one.

## 2. Bring-up

```bash
docker compose -f infra/docker/mongo-prod.yml --env-file .env.prod up -d
```

Confirm the container is running:

```bash
docker ps
```

## 3. Initialize the replica set

```bash
uv run python infra/mongo/init_replica_set.py
```

Optionally inspect `rs.status()` directly after initialization:

```bash
mongosh "$MONGO_URI" --eval 'rs.status()'
```

## 4. Smoke validation

Run the production smoke script:

```bash
set -a
source .env.prod
set +a
uv run python infra/mongo/smoke_prod.py
```

The smoke script intentionally reads only process environment variables. Sourcing
`.env.prod` here keeps credential loading explicit for the operator and avoids
coupling the CLI to dotenv parsing behavior.

Exit-code taxonomy:

| Code | Tag | Meaning |
|------|-----|---------|
| 0 OK | ok | All checks passed |
| 10 connectivity | connectivity | Could not reach mongod |
| 11 auth | auth | Admin credentials were rejected |
| 20 rs.status | rs.status | `rs.status()` failed or returned unhealthy data |
| 21 not-primary | not-primary | Replica set member is not PRIMARY |
| 30 roundtrip | roundtrip | Insert/read/delete sentinel roundtrip failed |
| 40 transaction | transaction | Multi-document transaction failed |
| 50 change-stream | change-stream | Change-stream event was not received |
| 60 cleanup | cleanup | `_smoke` cleanup failed |
| 99 unexpected | unexpected | Unclassified smoke-script error |

Every non-zero exit prints `error: <tag>: <detail>` to stderr.

## 5. Evidence capture

Copy `infra/docker/PROD_BRINGUP_EVIDENCE.template.md` to a dated evidence file and paste the requested outputs:

```bash
cp infra/docker/PROD_BRINGUP_EVIDENCE.template.md infra/docker/PROD_BRINGUP_EVIDENCE_$(date +%F).md
```

Paste the validated commit hash range, raw `rs.status()` output, smoke-script exit code, smoke stdout/stderr, `docker ps`, timestamp, operator name, and sign-off.

## 6. Failure tree and rollback

- `10 connectivity`: confirm container health, bind address, firewall, and port `27019`.
- `11 auth`: verify `.env.prod` credentials and re-run initialization only after correcting secrets.
- `20 rs.status`: inspect `rs.status()` and container logs before retrying.
- `21 not-primary`: wait briefly, inspect election status, and do not proceed until PRIMARY.
- `30 roundtrip`: inspect disk, permissions, and sentinel collection write/read behavior.
- `40 transaction`: confirm the replica set is initialized; standalone mongod cannot support transactions.
- `50 change-stream`: confirm replica set health and oplog availability.
- `60 cleanup`: manually drop `_smoke` and inspect permissions.
- `99 unexpected`: preserve stderr and escalate with the evidence file.

Rollback if the bring-up must be abandoned:

The rollback action is `docker compose down -v`; include the same compose file and env file used for bring-up.

```bash
docker compose -f infra/docker/mongo-prod.yml --env-file .env.prod down -v
```

## 7. Day-2 pointer and sentinel cleanup

The smoke script drops the `_smoke` database at start and end. If a mid-test failure leaves sentinel state behind, clean it manually:

```bash
mongosh "$MONGO_URI" --eval 'db.getSiblingDB("_smoke").dropDatabase()'
```

After cleanup, re-run `uv run python infra/mongo/smoke_prod.py` and attach the new evidence.
