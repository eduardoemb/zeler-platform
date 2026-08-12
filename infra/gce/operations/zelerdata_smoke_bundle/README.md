# ZelerData smoke host bundle

This directory contains only the fixed executable launcher. Install the
launcher, the existing `authenticated_smoke.py`, and a dedicated Python 3.11
environment under `/opt/zeler-platform/zelerdata-smoke/`. The launcher never
reads a secret from a file and accepts no operational configuration.

Install the runner and CLI using their repository package layout:

```text
/opt/zeler-platform/infra/gce/operations/zelerdata_smoke_runner.py
/opt/zeler-platform/infra/gce/operations/zelerdata_smoke_cli.py
```

Invoke the CLI with `PYTHONPATH=/opt/zeler-platform` and
`-m infra.gce.operations.zelerdata_smoke_cli`. Do not install or import the CLI
as a top-level `zelerdata_smoke_cli` module: it imports the runner through the
`infra.gce.operations` package and both files must resolve from the same
revision.

Before a privileged host installation, verify the static bundle with:

```bash
sha256sum launch_authenticated_smoke README.md
```

The B1 CLI is the only supported entry point. Do not add environment files,
secret files, service units, timers, or automatic execution hooks.
