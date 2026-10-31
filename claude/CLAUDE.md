# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

The plan is `claude/plan1.md` (kept in `claude/` rather than `docs/PLAN.md`, per the Important section below). Progress is logged in `PROGRESS.md` at the repo root. Read both, then do the next unfinished day. One day per session. Days 1-6 done in code: scaffold, models, config loader, `clickops doctor`, `infra/bootstrap` and `infra/sandbox` (apply status tracked in PROGRESS.md), Terraform CI workflow, synthetic CloudTrail fixtures.

## What clickops is

Watches one AWS account (`ap-south-1`) and alerts on Slack when someone changes Terraform-managed infrastructure outside Terraform. Also provides `clickops scan` (shadow resources found in no Terraform state) and `clickops import` (writes `import` blocks and runs `terraform plan -generate-config-out`).

## Commands

- `make check` runs ruff, mypy (strict on `clickops/`) and pytest. It must pass before every commit.
- `make fmt`, `make lint`, `make typecheck`, `make test` run the individual steps.
- Single test: `uv run pytest tests/path/test_x.py::test_name`
- Lambda build: `scripts/build_lambda.sh` (reproducible zip)
- Final end-to-end check: `scripts/e2e.sh` (hits the real account, needs approval)

## Architecture

One Python 3.12 package, `clickops`, shared by the CLI (typer, rich) and the Lambda (`handler.py`). Models and config use pydantic v2.

Event path: CloudTrail → EventBridge rule → `clickops-detector` Lambda → `events.py` (normalize, drop events with `errorCode`, strip Lambda version suffixes) → `actors.py` → `resolvers/` (event → `ResourceRef`s) → `state.py` (Terraform state index from S3) → `compare/` (live config vs state) → `rules.py` (outcome and severity) → `store.py` (DynamoDB `clickops-events`) → `alerts.py` (Slack, plus SNS email for critical).

Things that span files:
- Actor classes are checked in a fixed order: `clickops-self` → `ci` → `aws-service` → `console-human` → `cli-human`.
- Outcomes: `managed-drift`, `managed-delete`, `shadow-create`, `ignored`, and later `tamper`. Critical overrides: ingress from the world on a port other than 80/443, IAM wildcard with a write action, S3 Block Public Access disabled. The tag `clickops:ignore=true` suppresses alerts.
- Scope is exactly six resource types: security group, IAM role/policy, S3 bucket, EC2 instance, Lambda function, Route 53 record. Each has a resolver and a comparator.
- IAM and Route 53 events arrive in `us-east-1`. A forwarding rule there sends them to the `ap-south-1` default bus, where a second rule targets the detector.
- Three Terraform roots under `infra/`: `bootstrap/` (local state, OIDC provider, `clickops-ci` role, state bucket), `sandbox/` (the infrastructure that gets drifted) and `detector/` (trail, rules, Lambda, DynamoDB, SNS). Backend is S3 with `use_lockfile = true`.
- Config lives in `clickops.yaml` (state locations, trusted roles, ignore rules, severity overrides).
- Tests use moto and CloudTrail fixtures in `tests/fixtures/cloudtrail/<service>/<EventName>.json`. Each fixture has a `_source: real|synthetic` field. Golden tests replay every fixture through the full pipeline.

## Rules from the plan

- Ask the human before every `terraform apply`/`destroy` and before any AWS CLI call that creates, changes or deletes a resource. `terraform plan` is fine without asking.
- Never create NAT gateways, load balancers, RDS, EKS or running EC2 instances. Tag every resource `project=clickops`, `owner=agent`. Ask before anything that costs money.
- No secrets in git. The Slack webhook lives in SSM (`/clickops/slack-webhook`); the human stores it, so never handle the URL. Account-specific values go in gitignored `*.auto.tfvars`. Never log Terraform state attribute values, only addresses and IDs.
- CI reaches AWS only through GitHub OIDC (role `clickops-ci`). The local profile `clickops-admin` is for bootstrap and approved applies only.
- Conventional Commits, at least one per task, on a `day-NN` branch merged through a PR.
- Settled decisions (tools, region, table names) are not up for redesign. If one is wrong, record it in `PROGRESS.md` and pick the smallest fix.
- At the end of each day, append to `PROGRESS.md`: day number, what was built, test results, deviations and open issues.



## Important
- DO NOT add claude as a contributor while commiting
- Break 1 day task into many smaller tasks and then develop and commit.
- Commit every smaller changes and push to gihub making more contributions.
- keep every agent and plan related files seperate from the codebase (inside /claude)