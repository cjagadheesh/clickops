# Release checklist for v0.1.0

Each line of the definition of done, how to check it, and what it needs. Tick it off in the release
pull request or issue. The code side is finished; everything left needs an AWS account or GitHub.

| Item | How to check | Needs |
| --- | --- | --- |
| `make check` passes on `main` | `make check`, and the `ci` workflow is green | nothing |
| Terraform CI passes on `main` | the `terraform` workflow: static checks, plan, Access Analyzer | repository variables `CLICKOPS_CI_ROLE_ARN`, `TF_STATE_BUCKET`, `TF_ADMIN_CIDR`, `TF_ALERT_EMAIL` |
| Every root applies and plans clean | `terraform apply`, then `terraform plan` shows no changes, in `bootstrap`, `sandbox` and `detector` | AWS admin profile; Terraform has never been run on these files |
| `scripts/e2e.sh` passes | `CONFIRM=yes AWS_PROFILE=clickops-admin scripts/e2e.sh`, then commit `docs/e2e-results.md` | applied stack, Slack webhook, a fresh Lambda zip |
| All six resource types alert correctly | the six scenarios in `docs/e2e-results.md` all pass | the e2e run |
| `scan` and `import` work on the real account | `clickops scan`; `CONFIRM=yes scripts/test_import_bucket.sh` | Terraform 1.10+, `clickops.yaml` |
| Tamper alerts fire | `scripts/e2e_alerts.sh` and `clickops status` after stopping the trail in a throwaway test | applied detector |
| No stored credentials | `git grep -nE 'AKIA[0-9A-Z]{16}|hooks\.slack\.com/services' -- . ':!docs/release-checklist.md' ':!tests/test_fetch_fixtures.py'` finds nothing (that test holds a fake key to prove redaction); CI uses OIDC; the webhook is in SSM | nothing |
| Access Analyzer shows no errors or security warnings | the plan job's Access Analyzer step is green for both roles | CI role set up |
| Monthly cost confirmed | `scripts/cost_report.py` after a full month; put the figure in `docs/cost.md` | cost allocation tag activated |
| README quickstart verified from a fresh clone | follow the README in a new directory, up to `terraform plan` for every root | Terraform |
| Demo GIF included | `AWS_PROFILE=clickops-admin vhs demo/demo.tape`, commit `demo/demo.gif` | VHS, applied detector |
| `v0.1.0` tagged with release assets | see below | all of the above |
| `PROGRESS.md` closed | done: final summary and the v0.2 ideas list | nothing |

## Tagging

1. Optionally push a pre-release first: `git tag v0.1.0-rc1 && git push origin v0.1.0-rc1`. The `release`
   workflow should attach the wheel, `clickops-detector-0.1.0.zip` and `SHA256SUMS`. Delete the
   pre-release and tag afterwards if you do not want them kept.
2. Change the heading in `CHANGELOG.md` from `[0.1.0] - Unreleased` to `[0.1.0] - <date>` and commit it.
3. From `main`: `git tag v0.1.0 && git push origin v0.1.0`.
4. On a clean machine, `pipx install` the wheel from the release and run `clickops doctor`.
