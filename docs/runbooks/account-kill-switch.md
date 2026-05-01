# Account Kill Switch Runbook

## When to use

Use this emergency procedure for a Meli credential breach, suspected abuse, runaway worker behavior, or an ops emergency where a seller must stop flowing through gateway and worker paths immediately.

## How to pause an account

Run this against the production MongoDB database from an approved ops shell:

```javascript
db.meli_accounts.updateOne(
  {user_id: "<seller_id>"},
  {$set: {
    status: "paused",
    paused_at: new Date().toISOString(),
    paused_by: "ops",
    paused_reason: "<incident or ticket>"
  }}
)
```

Prerequisite: `status="paused"` requires the T28 schema delta to be deployed before this command is accepted by validators.

## How to resume

Only resume after the incident owner confirms credentials, seller settings, and worker queues are safe:

```javascript
db.meli_accounts.updateOne(
  {user_id: "<seller_id>"},
  {$set: {status: "active"}, $unset: {paused_reason: ""}}
)
```

## What stops

- Gateway proxy requests for the paused seller return `423 Locked` with `seller_paused`.
- Workers skip messages for paused sellers before making any Meli call.
- Delayed retry messages remain safe because the paused check happens when they are processed again.

## Verification

Check service logs for `worker.message.skipped.paused` and gateway responses returning `423 Locked`. If either is missing after a pause, keep the account paused and escalate before resuming.
