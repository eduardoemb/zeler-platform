# ZelerData smoke host bundle

This directory contains only the fixed executable launcher. Install the
launcher, the existing `authenticated_smoke.py`, and a dedicated Python 3.11
environment under `/opt/zeler-platform/zelerdata-smoke/`. The launcher never
reads a secret from a file and accepts no operational configuration.

Before a privileged host installation, verify the static bundle with:

```bash
sha256sum launch_authenticated_smoke README.md
```

The B1 CLI is the only supported entry point. Do not add environment files,
secret files, service units, timers, or automatic execution hooks.
