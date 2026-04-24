# On-Prem Mongo Setup

## Prerequisites

- Ubuntu 22.04 LTS server.
- Fixed public IP address.
- Domain name pointing to that server.

## OS Hardening

- Enable `ufw` or `firewalld` before exposing any service.
- Install and configure `fail2ban` for SSH protection.
- Disable password-based SSH and enforce SSH key-only access.
- Enable `unattended-upgrades` for security patching.

## Mongo Install

Use the official MongoDB 7 apt repository on Ubuntu 22.04:

```bash
curl -fsSL https://pgp.mongodb.com/server-7.0.asc | sudo gpg --dearmor -o /usr/share/keyrings/mongodb-server-7.0.gpg
echo "deb [ signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list
sudo apt update
sudo apt install -y mongodb-org
```

## Mongo Config

Configure `/etc/mongod.conf` with at least:

```yaml
net:
  bindIp: 0.0.0.0
security:
  authorization: enabled
```

TLS is intentionally deferred to Phase 4. Add a note in the server checklist that `tlsMode: requireTLS` and certificate paths become mandatory before Cloud Run connects to the on-prem instance.

## systemd Verification

Verify the service is healthy after configuration changes:

```bash
sudo systemctl enable mongod
sudo systemctl restart mongod
sudo systemctl status mongod
```

## Initial Users

Create:

- One admin user in the `admin` database for cluster administration.
- One platform application user with scoped roles for `zeler_platform`.

Keep backup/restore users separated later if Batch B introduces dedicated backup automation.

## Firewall

Allow MongoDB port `27017` ONLY from the Cloud Run static egress IP that will be provisioned in P4.1.
Until that IP exists, keep the firewall rule as a placeholder and do not open the port broadly.

## TLS Strategy

TLS is deferred to P4, where the final choice between Let's Encrypt and a self-signed CA bundle will be locked in.
Document the selected certificate chain and renewal workflow before production traffic is allowed.

## Backups

Per D13, install a daily cron entry at `/etc/cron.d/mongodump-daily`.
The backup script itself is delivered later in P0.12.* and should upload encrypted dumps off-host.

## Restore Drills

Run a restore drill monthly.
Use the future `mongo-restore.md` runbook from P0.12.3 as the source of truth for the recovery steps.
