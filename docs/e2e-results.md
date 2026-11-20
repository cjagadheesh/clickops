# End-to-end results

Not run yet. `scripts/e2e.sh` writes this file: it makes six real changes to the sandbox as the
admin profile, waits for the detector's finding in `clickops-events` (up to 10 minutes each),
checks the outcome and severity, records the delay and reverts.

```
CONFIRM=yes AWS_PROFILE=clickops-admin scripts/e2e.sh
```
