# Platform Freeze and Reactivation Runbook

> **Status (2026-10-19): production is FROZEN.** `platform-vm`, its disks, its
> static IP and the serverless VPC connector were deleted to stop spending while
> the product earns no revenue. `app.zeler.ai` (Vercel) still loads but every
> backend call fails. Nothing on `*.zeler.ai` answers until this runbook is run.

Part A records what was frozen and what was kept. Part B brings the same
platform back on GCP. Part C describes a no-cost hosting alternative.

---

## Part A — What the freeze did

### Kept (needed to come back)

| Resource | Name | Why it matters |
| --- | --- | --- |
| Boot disk snapshot | `platform-vm-freeze-20261019` (8.1 GB stored) | Full VM as it ran: `/opt/zeler-platform` (compose, Caddyfile, scripts, env), Docker with every image cached, Caddy certificates, systemd units, and the Mongo dump below. |
| Mongo disk snapshot | `zeler-mongo-freeze-20261019` (2.0 GB stored) | `/var/lib/zeler-mongo` after a clean `mongod` shutdown. |
| Mongo dump (inside the boot snapshot) | `/var/lib/zeler-mongo-freeze-20261019.archive.gz` + `.sha256` + `.counts.json` | Second, independent copy of all databases (`mongodump --archive --gzip`, 117 MB, SHA-256 `06233d09…bcf4`). Per-collection counts for parity checks. |
| Freeze manifest in GCS | `gs://zeler-platform-backups/mongo/freeze-20261019/` | `images-manifest.txt` (running digest per service) and `vm.json` (the deleted VM's full description). No data, no secrets. |
| Artifact Registry | `zeler-platform` repo, only the 10 running digests | Every other version was deleted. Digests are listed in `images-manifest.txt`. |
| KMS | keyring `zeler-platform` (`meli-tokens`, `google-tokens`, `platform-jwt`) | **Never destroy these keys or their versions.** Stored Meli/Google tokens are encrypted with them and app JWTs are signed with `platform-jwt`. |
| Secret Manager | all secrets | `zeler-platform-secrets.service` rebuilds `/opt/zeler-platform/env/*.env` from them on every boot. |
| Service account, firewall rules, Cloud Run jobs, buckets | unchanged | Free or near-free when idle. |
| CloudAMQP, Vercel, Squarespace DNS | unchanged (outside GCP) | Review their plans separately; see A.3. |

Expected residual GCP cost: about USD 1–2 per month (snapshots, the remaining
images, KMS key versions, secret versions). Set a billing budget alert if you
want a hard signal.

### Deleted

- VM `platform-vm` (e2-medium, `us-central1-a`, internal IP `10.128.0.2`).
- Disks `platform-vm` and `zeler-mongo-data` (both 50 GB pd-balanced).
- Static IP `platform-vm-ip` (`34.133.106.82`). A new IP is assigned on return, so DNS must change.
- VPC connector `zeler-platform-serverless` (2–10 × e2-micro, range `10.8.0.0/28`). Only the bootstrap Cloud Run job uses it.
- Snapshots `*-pre-recovery-20260926` and `*-pre-recovery-20261002`.
- 1,082 old image versions, including all `fulldock-*` images.

Before the VM stopped, the app containers and then Mongo were stopped, and the
`zeler-docker-maintenance` and `zelerdata-devoluciones-reconcile` timers were
**disabled**. Containers use `restart: unless-stopped`, so they stay down after
the VM boots until someone starts them (B.5).

### A.3 Pending items outside this freeze

- **Alert policies are disabled** (all six, 2026-10-19). Re-enable them in B.6.
  The two uptime checks (`zeler-gateway-availability`, `zeler-sheets-availability`)
  stay within the free quota and keep failing while frozen.
- **CloudAMQP:** if the instance is on a paid plan, move it to the free
  "Little Lemur" plan. Shared plans change in place; a dedicated instance cannot
  move to a shared plan, so create a new Little Lemur instance and delete the
  old one. A new instance has new URLs: before reactivating, add new versions of
  the `cloudamqp-url` and `cloudamqp-management-url` secrets. Little Lemur
  (about 1 M messages per month, 20 connections) may be too small once ZelerData
  runs again; review the plan at reactivation. Free instances may drop idle
  queues; the consumers and topology scripts redeclare them on start (B.6).
- **Vercel (`zeler-app`):** free on the Hobby plan; on a paid team plan, consider
  pausing the project.
- **Domain `zeler.ai`:** keep renewing it in Squarespace.

---

## Part B — Reactivate on GCP (about 1 hour)

Run from the main checkout on `main`, with `gcloud` authenticated as project
owner. Do not print secrets or env values at any step.

```bash
PROJECT=zeler-platform-dev
REGION=us-central1
ZONE=us-central1-a
SA=platform-vm-sa@${PROJECT}.iam.gserviceaccount.com
```

### B.1 Recreate the disks from the snapshots

```bash
gcloud compute disks create platform-vm \
  --source-snapshot=platform-vm-freeze-20261019 \
  --type=pd-balanced --size=50GB --zone=$ZONE --project=$PROJECT
gcloud compute disks create zeler-mongo-data \
  --source-snapshot=zeler-mongo-freeze-20261019 \
  --type=pd-balanced --size=50GB --zone=$ZONE --project=$PROJECT
```

### B.2 Reserve a static IP

```bash
gcloud compute addresses create platform-vm-ip --region=$REGION --project=$PROJECT
gcloud compute addresses describe platform-vm-ip --region=$REGION \
  --project=$PROJECT --format="value(address)"
```

### B.3 Create the VM on the restored disks

The internal IP is pinned to `10.128.0.2` because the bootstrap job's Mongo URI
and `MONGO_PRIVATE_BIND_IP` point at it.

```bash
gcloud compute instances create platform-vm \
  --zone=$ZONE --project=$PROJECT \
  --machine-type=e2-medium \
  --disk=name=platform-vm,boot=yes,auto-delete=yes \
  --disk=name=zeler-mongo-data,device-name=mongo-data,mode=rw,boot=no,auto-delete=no \
  --address=platform-vm-ip \
  --private-network-ip=10.128.0.2 \
  --service-account=$SA --scopes=cloud-platform \
  --tags=platform-vm,http-server,https-server \
  --shielded-vtpm --shielded-integrity-monitoring \
  --metadata-from-file=startup-script=infra/gce/platform-vm-startup.sh
```

The startup script is idempotent. On a restored disk it finds Docker, swap and
the `/var/lib/zeler-mongo` fstab entry already in place, and
`zeler-platform-secrets.service` rewrites the env files from Secret Manager.

### B.4 Point DNS at the new IP

In Squarespace DNS for `zeler.ai`, set the `A` record of `gateway`, `sheets`,
`repricer`, `publicador` and `autoreply` to the new IP from B.2. Wait until
`dig +short gateway.zeler.ai` returns it. Caddy renews certificates by itself
once the names resolve.

### B.5 Start the stack

```bash
gcloud compute ssh platform-vm --tunnel-through-iap --zone=$ZONE --project=$PROJECT
```

On the VM:

```bash
test -f /opt/zeler-platform/.startup-complete && echo startup OK
df -h / /var/lib/zeler-mongo          # Mongo disk mounted, ~2.3 GB used
systemctl is-active zeler-platform-secrets.service
cd /opt/zeler-platform
sudo docker compose up -d mongo
sudo docker compose ps mongo          # wait for (healthy)
sudo docker compose up -d             # images are cached on the disk; no pull
sudo systemctl enable --now zeler-docker-maintenance.timer zelerdata-devoluciones-reconcile.timer
```

If Mongo does not come up healthy from the restored data disk, restore the dump
instead (verify the checksum first, then follow `docs/deploy.md` §3 steps 6–9,
using `/var/lib/zeler-mongo-freeze-20261019.archive.gz` as the archive and
`.counts.json` as the parity reference).

### B.6 Verify

1. Running digests match `gs://zeler-platform-backups/mongo/freeze-20261019/images-manifest.txt`.
2. The `docs/deploy.md` §8 smoke checklist: capacity baseline, HTTPS health on
   every subdomain with a valid certificate, gateway `/ready`, worker health
   reporting RabbitMQ and Mongo ready.
3. RabbitMQ topology is present (queues and DLQs for each worker). The
   consumers declare their own queues on start; if DLQs, delay queues or the
   DEVOLUCIONES topology are missing, reapply them with
   `infra/rabbitmq/apply_topology.py` and the `docs/deploy.md` §5d topology step.
4. Re-enable the alert policies disabled in A.3:
   ```bash
   for id in $(gcloud alpha monitoring policies list --project=$PROJECT --format="value(name)"); do
     gcloud alpha monitoring policies update "$id" --enabled --project=$PROJECT
   done
   ```
5. App smoke with pilot seller `82453304` (`docs/deploy.md` §5c).

### B.7 Things that may have expired while frozen

- **Mercado Libre tokens:** refresh tokens stop working after a long period
  without use (about six months). If token refresh fails, re-link each seller
  through `/accounts` in `zeler-app`; never copy tokens by hand.
- **Mercado Libre webhooks:** in the Meli developer app, confirm the
  notification callback URL still points at the gateway and topics are enabled.
- **Google OAuth (ZelerData):** reconnect Google from `/sheets/config` if the
  sheets worker reports `invalid_grant`.

### B.8 Optional pieces

- **Bootstrap Cloud Run job** needs the VPC connector again (about USD 12+/month
  while it exists):
  ```bash
  gcloud compute networks vpc-access connectors create zeler-platform-serverless \
    --region=$REGION --network=default --range=10.8.0.0/28 \
    --min-instances=2 --max-instances=10 --machine-type=e2-micro --project=$PROJECT
  ```
- **New code:** once the frozen stack is healthy, build and deploy newer `main`
  commits with `docs/deploy.md` §2 and §5 as usual.
- **Cleanup:** keep the freeze snapshots until the restored platform has run
  cleanly for at least a week, then delete them.

---

## Part C — No-cost alternative

The stack fits one machine (it ran on an e2-medium with 4 GB plus swap), so
the realistic free path is one always-free VM running the same Compose file.
Free tiers change without notice: confirm current terms before moving.

### Recommended: Oracle Cloud Always Free (Ampere A1, arm64)

- **Capacity:** historically 4 OCPU / 24 GB; reports say Oracle cut it to
  2 OCPU / 12 GB in June 2026. Either is more than `platform-vm` had. It also
  includes up to 200 GB of block storage.
- **Layout:** one Ubuntu arm64 VM running the existing `infra/gce/docker-compose.yml`
  with Mongo, Caddy, the APIs and workers. Add a `rabbitmq:3-management`
  container to replace CloudAMQP, so the broker has no message quotas.
- **Data:** restore the freeze dump (659 MB on disk; too large for MongoDB Atlas
  M0's 512 MB without pruning `audit_log`, which holds most documents).
- **GCP dependencies stay in GCP:** KMS (token encryption, JWT signing) and
  Secret Manager cost cents per month. The Oracle VM has no GCP metadata server,
  so it needs a dedicated service account key (or Workload Identity Federation)
  with only `cloudkms.cryptoKeyEncrypterDecrypter`, `cloudkms.signerVerifier`
  and `secretmanager.secretAccessor`. Store the key outside the repo with mode
  `0600`. Do **not** create new KMS keys: existing tokens only decrypt with the
  current ones.
- **Code changes needed (one worktree, normal TDD flow):**
  - `zeler-platform-secrets.sh` reads secrets through the metadata-server token;
    it needs a variant that uses `GOOGLE_APPLICATION_CREDENTIALS`.
  - Images must be `linux/arm64`. All Dockerfiles use `python:3.11-slim`, which
    is multi-arch, but every native wheel must have an arm64 build. Build in
    Cloud Build with `docker buildx` (within its free build minutes), or
    natively on the Oracle VM from an exact `main` commit. The VM build skips
    the VERIFIED provenance gate in `docs/deploy.md`; decide explicitly before
    using it.
  - Remove the `/var/lib/zeler-mongo` persistent-disk assumptions or point them
    at the Oracle block volume.
- **Networking:** open 80/443 in the VCN security list **and** in the instance
  firewall (Oracle's Ubuntu images ship restrictive `iptables` rules). Point the
  five `A` records at the instance's public IP.
- **Risks:** Oracle may reclaim Always Free instances that sit idle (low CPU,
  network and memory for days); upgrading the account to Pay As You Go keeps the
  free shapes and avoids reclamation, but then set a USD 1 budget alert. A1
  capacity is often unavailable in busy regions; retry or pick another home
  region at signup (the home region cannot change later).

### Other options considered

| Option | Verdict |
| --- | --- |
| GCP free tier `e2-micro` | 1 GB RAM: not enough for Mongo plus ten app containers. |
| Render, Koyeb, Fly.io free plans | Web services that sleep, or no free always-on background workers; the workers need persistent consumers. |
| A spare home machine + Cloudflare Tunnel | Free and keeps the x86 images, but the machine must stay on, and named tunnels require moving the `zeler.ai` DNS zone to Cloudflare. Good fallback for demos. |
| MongoDB Atlas M0 + CloudAMQP Little Lemur | Free managed data and broker, but 512 MB storage and about 1 M messages per month are below current usage. |
