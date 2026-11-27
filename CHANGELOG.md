# Changelog

All notable changes to clickops are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - Unreleased

First release. clickops watches one AWS account in `ap-south-1` and tells you on Slack when someone
changes Terraform-managed infrastructure outside Terraform.

### Added

- **Live drift alerts.** A write call recorded by CloudTrail reaches the `clickops-detector` Lambda
  through EventBridge. The detector normalizes the event, classifies the actor (clickops itself, CI,
  AWS service, console human or CLI human), resolves the resource, compares the live configuration
  with Terraform state and stores a finding in the `clickops-events` DynamoDB table.
- **Six resource types:** security groups (and their rules), IAM roles and policies, S3 buckets,
  EC2 instances, Lambda functions and Route 53 records. IAM and Route 53 events are forwarded from
  `us-east-1`.
- **Outcomes and severity:** `managed-drift` (warning), `managed-delete` (critical),
  `shadow-create` (info), `tamper` (critical) and `ignored`. Findings become critical for ingress
  from the world on a port other than 80 or 443, an IAM policy with a wildcard and a write action,
  or S3 Block Public Access being turned off. The `clickops:ignore=true` tag, ignore rules and
  severity overrides in `clickops.yaml` are supported.
- **Slack and email alerts** with the actor, the source (console or CLI), a short diff against
  state and the `terraform apply -target=...` command that would restore the coded state. Critical
  findings are also emailed through SNS. Repeats for the same resource and actor within ten minutes
  only update a counter.
- **Tamper alerts** when anyone other than `clickops-ci` stops or changes clickops' own trail, event
  rules or detector function.
- **CLI:** `clickops doctor`, `clickops events`, `clickops scan` (shadow resources),
  `clickops import` (import blocks plus `terraform plan -generate-config-out`) and
  `clickops status`.
- **Infrastructure as code** in three Terraform roots: `bootstrap` (state bucket, GitHub OIDC
  provider and the least-privilege `clickops-ci` role), `sandbox` (the infrastructure that gets
  drifted) and `detector` (trail, rules, Lambda, table, topic and alarms).
- **CI and release automation:** `make check` (ruff, strict mypy, pytest), Terraform plan and apply
  through GitHub OIDC, IAM Access Analyzer checks on every policy, and a release workflow that
  attaches the wheel and the reproducible Lambda package to a GitHub release.
- **Teardown and cost:** `make destroy` removes the three roots in the safe order (with a confirmation
  prompt and `DRY_RUN=1`), and `scripts/cost_report.py` reports the real monthly cost of everything
  tagged `project=clickops`.
- **Demo:** a re-runnable VHS tape in `demo/`.
- Documentation: architecture, threat model, cost and example alerts in `docs/`.

### Known limitations

- One account, one region (plus global IAM and Route 53 events) and six resource types.
- Alerts arrive a few minutes after the change, because CloudTrail delivers events with a delay.
- clickops never reverts a change; it prints the command that would.
