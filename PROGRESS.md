# PROGRESS

## Day 1: repo scaffold

**Built**
- uv project (`pyproject.toml`, `uv.lock`, Python 3.12) with the `clickops` package: empty modules matching the repo layout, `resolvers/` and `compare/` subpackages, `py.typed`.
- ruff (lint and format) and mypy strict on `clickops/` configured in `pyproject.toml`; pytest with one placeholder test.
- `Makefile` with `fmt`, `lint`, `typecheck`, `test` and `check`.
- `.gitignore` covering `*.tfstate*`, `.terraform/`, `*.auto.tfvars`, `.env`, `dist/` (plus build and tool caches).
- `.github/workflows/ci.yml` runs `make check` on PRs and pushes to `main`.
- `claude/CLAUDE.md` status section updated.

**Tests**
- `make check`: ruff clean, mypy strict clean (15 source files), pytest 1 passed.

**Deviations**
- The plan says to save itself as `docs/PLAN.md` and write `CLAUDE.md` at the repo root. The repo's instructions say to keep all agent and plan files in `claude/`, so the plan stays at `claude/plan1.md` and `CLAUDE.md` stays at `claude/CLAUDE.md`. No `docs/PLAN.md` was created.
- Commits are authored as the repo owner with no Claude trailers, per the scheduled-run instructions.

**Open issues / needs the human**
- "First PR shows a green CI run" can only be confirmed on GitHub once the PR runs; check the Actions tab on the Day 1 PR.

## Day 2: core models, config and `doctor`

**Built**
- `clickops/models.py`: `NormalizedEvent`, `Actor`, `ResourceRef` (with `key` for the event store), `Finding`, plus `ActorClass`, `Outcome` and `Severity` enums.
- `clickops/config.py`: `clickops.yaml` model (state locations, trusted role ARNs, ignore rules, severity overrides) and `load_config`, which raises `ConfigError` for missing, malformed or invalid files. `clickops.example.yaml` holds placeholders.
- `clickops/doctor.py` and `clickops doctor`: checks AWS credentials (`sts get-caller-identity`), Terraform >= 1.10, config validity and `HeadObject` access to each state file. Each result is pass or fail with a fix hint; exit code 1 on any failure. `clickops` console script added.
- Added `pyyaml` and `types-PyYAML`.

**Tests**
- `make check`: ruff clean, mypy strict clean, pytest 23 passed (models, valid and invalid configs, doctor against moto).

**Deviations**
- Doctor logic lives in `clickops/doctor.py` (not in the plan's layout) to keep `cli.py` thin.
- Added an `unresolved` outcome now, since Day 11's handler stores it.
- Terraform is not installed in this environment, so the real `terraform version` path is only tested for the missing-binary case and by parsing sample output.

**Open issues / needs the human**
- Run `clickops doctor` once with real credentials and a real `clickops.yaml` after Day 3 creates the state bucket.

## Day 3: bootstrap infrastructure

**Built**
- `infra/bootstrap/` (local state, AWS provider ~> 5.81, Terraform >= 1.10): state bucket `clickops-tfstate-<account-id>` (versioning, SSE-S3, Block Public Access, deny-non-TLS policy), the GitHub OIDC provider, and the `clickops-ci` role trusted only for `repo:<owner>/<repo>:ref:refs/heads/main` and `:pull_request`, with a policy scoped to the sandbox and detector resource types (Day 24 tightens it).
- `bootstrap.auto.tfvars.example` and a README with the apply steps. Account ID and GitHub owner come from the gitignored `bootstrap.auto.tfvars`.
- `.github/workflows/oidc-check.yml`: manual workflow that assumes `clickops-ci` and prints the caller identity. It reads the role ARN from the repository variable `CLICKOPS_CI_ROLE_ARN`.
- `tests/test_infra_hygiene.py`: no state files, tfvars, account IDs or access keys are tracked.

**Tests**
- `make check`: ruff clean, mypy strict clean, pytest 25 passed.

**Deviations**
- The plan asks for a throwaway workflow on a branch. Work is committed to `main` only, so it is a `workflow_dispatch` workflow on `main`; the trust policy allows `main`, so it can run there.
- Terraform is not installed in this environment, so `terraform fmt`, `validate` and `plan` were not run on these files.

**Needs the human**
- Run `terraform init`, `fmt -check`, `validate` and `plan` in `infra/bootstrap`; fix anything they flag (the OIDC resource assumes provider >= 5.81 so no thumbprint is needed).
- Copy `bootstrap.auto.tfvars.example` to `bootstrap.auto.tfvars`, fill it in, and approve the apply with the `clickops-admin` profile.
- Set the repository variable `CLICKOPS_CI_ROLE_ARN` and run the `oidc-check` workflow; the day's "Done when" is confirmed when it prints the caller identity.

## Day 4: the sandbox

**Built**
- `infra/sandbox/` (S3 backend with `use_lockfile`, bucket and region from the gitignored `backend.hcl`): VPC with one public subnet and internet gateway (no NAT); security groups `web` (443 from anywhere) and `admin` (22 from `admin_cidr`, default a placeholder /32) with rules as `aws_vpc_security_group_ingress_rule`; one `t4g.nano` held stopped with `aws_ec2_instance_state`; one versioned, encrypted, public-access-blocked bucket `clickops-sandbox-<account-id>`; role `clickops-sandbox-app` with an inline policy and a managed-policy attachment; Lambda `clickops-sandbox-hello` packaged with `archive_file`; private Route 53 zone `clickops.internal` with two A records.
- `docs/cost.md`: about USD 1.25 per month for the sandbox.
- `tests/test_cost_guardrails.py`: no NAT, load balancer, RDS or EKS resources anywhere in `infra/`, and the instance stays stopped.

**Tests**
- `make check`: ruff clean, mypy strict clean, pytest 27 passed.

**Deviations**
- One role serves as both the "IAM role" and the Lambda execution role, to stay within the plan's one-role limit; it trusts `lambda.amazonaws.com`.
- The AMI comes from `data.aws_ami` (not SSM) so the CI role needs no SSM permission, and `ignore_changes = [ami]` stops newer images forcing replacement.
- Terraform is not installed here, so `fmt`, `validate` and `plan` were not run.
- A few pushes failed transiently; the later pushes carried those commits, and `main` matches `origin/main`.

**Needs the human**
- Run `terraform init -backend-config=backend.hcl`, `validate` and `plan` in `infra/sandbox`, fix anything flagged, then approve the apply. The "Done when" check is a second `terraform plan` that shows no changes.
- The apply needs Day 3's bootstrap applied first (state bucket must exist). Set your real `admin_cidr` in a gitignored `sandbox.auto.tfvars`.
- The `clickops-ci` role may lack permissions the sandbox needs (for example `ec2:ModifyInstanceMetadataOptions` or tagging calls); Day 5's CI run will show gaps to add.

## Day 5: Terraform CI

**Built**
- `.github/workflows/terraform.yml`: on pull requests and pushes touching `infra/`, a `static` job runs `terraform fmt -check`, `validate` (no backend) and `tflint` for every root with `.tf` files. On pull requests a `plan` job runs for `sandbox` and `detector` (skipped while `infra/detector` has no `.tf` files) and posts or updates one plan comment per root. On push to `main`, `apply-sandbox` applies the sandbox only (the detector gets apply on Day 13).
- AWS access uses `aws-actions/configure-aws-credentials` with `role-to-assume` and `id-token: write`; no stored keys.
- `.tflint.hcl` with the recommended ruleset.
- `tests/test_terraform_workflow.py` checks triggers, the sandbox/detector plan matrix, the main-only sandbox-only apply and OIDC-only access.

**Tests**
- `make check`: ruff clean, mypy strict clean, pytest 46 passed (includes tests the owner added for config and doctor).

**Deviations**
- The plan has plan and apply use the `clickops-ci` role; the state bucket and admin CIDR reach the workflow through repository variables rather than files, since `backend.hcl` and tfvars are gitignored.
- Terraform, tflint and GitHub Actions cannot run in this environment, so the workflow is checked structurally only.
- Day 4's sandbox apply is assumed done by the owner (lock files were committed); nothing in the repo records the result.

**Needs the human**
- Set repository variables `CLICKOPS_CI_ROLE_ARN`, `TF_STATE_BUCKET` and `TF_ADMIN_CIDR` (same value the sandbox was applied with, or the first CI plan will show a rule change).
- "Done when": open a PR that changes one sandbox tag, confirm the plan comment appears, merge it, and confirm the apply job succeeds. Expect to widen `clickops-ci` if the plan hits AccessDenied (Day 24 tightens it later).

## Day 6: CloudTrail fixture library

**Built**
- 40 synthetic fixtures in `tests/fixtures/cloudtrail/<service>/<EventName>.json` (ec2, iam, s3, lambda, route53), one for every event in the coverage table, shaped as EventBridge "AWS API Call via CloudTrail" events with `_source: synthetic`. Lambda events keep their API-version suffixes. Three `*.console.json` variants (`AuthorizeSecurityGroupIngress`, `AttachRolePolicy`, `PutBucketPublicAccessBlock`) set `sessionCredentialFromConsole: "true"`. IAM and Route 53 events are in `us-east-1`.
- `scripts/gen_synthetic_fixtures.py` regenerates the synthetic set deterministically and never overwrites a file marked `real`.
- `scripts/make_fixture_events.sh` (needs `CONFIRM=yes` and approval) makes each watched write call once against scratch resources and the sandbox, then `scripts/fetch_fixtures.py` pulls the events from `lookup-events`, replaces account IDs and access keys with placeholders and saves them as `_source: real`.
- `tests/test_fixtures.py`: every fixture parses as CloudTrail JSON, every coverage-table event has a fixture, at least two console-human fixtures exist. `tests/test_fetch_fixtures.py` covers scrubbing and the envelope.

**Tests**
- `make check`: ruff clean, mypy strict clean, pytest 128 passed.

**Deviations**
- Every fixture is synthetic for now because there are no AWS credentials. The recording script keeps `RunInstances`, `TerminateInstances`, `CreateHostedZone` and `DeleteHostedZone` synthetic on purpose (cost and safety); the other events can be replaced with real ones.
- Fixtures use the EventBridge envelope (what the detector receives), not the raw `lookup-events` record.

**Needs the human**
- Approve and run `CONFIRM=yes AWS_PROFILE=clickops-admin scripts/make_fixture_events.sh` (it creates and deletes scratch resources and briefly starts the stopped sandbox instance), then `terraform apply` in `infra/sandbox` to undo the Lambda and Route 53 changes. Check the saved real fixtures before committing them (the script scrubs account IDs and keys, but look for anything else sensitive such as IPs or user names).

## Day 7: buffer and week-1 review

**Built**
- `docs/architecture.md`: Mermaid diagram of the event flow (including the `us-east-1` forwarding path and the DLQ) and of the three Terraform roots, plus the outcome table and actor order. `tests/test_architecture_doc.py` keeps both diagrams and every pipeline stage in the doc.
- Nothing from Days 1-6 was left unfinished in code.

**Tests**
- `make check`: ruff clean, mypy strict clean, pytest 129 passed.

**Week-1 summary (Days 1-7)**

| Day | Code and docs | "Done when" status |
| --- | --- | --- |
| 1 scaffold | done | `make check` passes; green CI on GitHub not confirmable from here |
| 2 models, config, `doctor` | done | unit tests cover valid and invalid configs; `doctor` runs against moto |
| 3 bootstrap | done | needs the human: apply, then run the `oidc-check` workflow |
| 4 sandbox | done | needs the human: apply, then a second `plan` showing no changes |
| 5 Terraform CI | done | needs the human: set repo variables, run the tag-change PR |
| 6 fixtures | done (all synthetic) | every coverage-table event has a fixture and a test confirms they parse; real recordings need the human |
| 7 review | done | this summary |

- The repo owner has already pushed Terraform lock files for `bootstrap` and `sandbox` and some config and doctor fixes, which suggests `terraform init` ran locally. No file records whether either apply happened.

**Blocked on AWS (needs the human)**
- Confirm Days 3 and 4 applied cleanly and that the sandbox costs what `docs/cost.md` predicts: one `aws ce get-cost-and-usage` call (USD 0.01) after the sandbox has run a few days; update `docs/cost.md` if it differs.
- Record real fixtures with `scripts/make_fixture_events.sh` (Day 6), then `terraform apply` in `infra/sandbox` to undo the changes.
- Check the Day 1 PR/Actions run is green and the Day 5 PR check works.

**Deviations**
- Work is committed straight to `main` rather than `day-NN` branches and PRs, as the scheduled instructions require, so "PR shows green CI" checks are replaced by checking the Actions tab on `main`.
- The identity on commits follows the schedule prompt (`cjagadheesh <jagadheeeeesh@gmail.com>`); the owner earlier asked for `jagadheeshc07@gmail.com`, so one of the two needs updating.

## Day 8: event normalizer

**Built**
- `clickops/events.py`: `normalize(raw)` turns an EventBridge "AWS API Call via CloudTrail" event into a `NormalizedEvent` (event ID, time, source, name, region, account, user identity, request and response parameters, source IP, user agent). It returns `None` for a call with an `errorCode`, strips Lambda version suffixes (`UpdateFunctionConfiguration20150331v2` becomes `UpdateFunctionConfiguration`), and raises `NormalizationError` for events that are not CloudTrail calls or lack a required field, so the handler can let those fail into the DLQ later.
- `tests/conftest.py` fixture helpers.
- `tests/test_events.py`: all 40 fixtures normalize, with field assertions for ec2, iam, s3, lambda and route53 fixtures, plus failed-call, missing-field and bad-timestamp cases.

**Tests**
- `make check`: ruff clean, mypy strict clean, pytest 186 passed.

**Deviations**
- None. The normalizer accepts the EventBridge envelope (the format of the fixtures and of what the Lambda receives).

**Open issues / needs the human**
- None new. Real fixtures from Day 6 should also normalize; rerun `make check` after recording them.

## Day 9: actor classifier

**Built**
- `clickops/actors.py`: `classify(event, trusted_roles, self_role_arn)` applies `clickops-self`, `ci`, `aws-service`, `console-human`, `cli-human` in that order and returns an `Actor` with a display name. The detector's own role ARN comes from the `self_role_arn` argument or the `CLICKOPS_SELF_ROLE_ARN` environment variable. CI is a role named `clickops-ci` or a trusted role from `clickops.yaml`; roles are compared by account and role name, so IAM paths and STS ARNs both match. AWS service means `type: AWSService`, `invokedBy` set, or a service-linked role (`/aws-service-role/`). Display names: IAM user name, the session name for assumed roles (for `AWSReservedSSO_*` that is the person's login), the invoking service, or `root`.
- Four new fixtures for the edge cases: `AuthorizeSecurityGroupIngress.ci` (GitHub Actions), `StopInstances.service-linked`, `AuthorizeSecurityGroupIngress.cloudformation` (`invokedBy`) and `PutRolePolicy.self`; the generator writes them.
- `events.normalize` now keeps a record-level `sessionCredentialFromConsole` in the user identity.
- `tests/test_actors.py`: a parametrised test gives every fixture an expected class and name, plus precedence, trusted-role, IAM-path, environment and top-level-flag cases.

**Tests**
- `make check`: ruff clean, mypy strict clean, pytest 249 passed.

**Deviations**
- Fixtures place `sessionCredentialFromConsole` inside `userIdentity.sessionContext.attributes`, but real records may carry it beside `userIdentity`. The classifier and normalizer accept both.

**Open issues / needs the human**
- When real fixtures are recorded, check where the real record puts `sessionCredentialFromConsole` (and the real shape of an Identity Center console session) and adjust the synthetic ones to match.

## Day 10: detector storage and trail

**Built**
- `infra/detector/` (S3 backend, state key `detector/terraform.tfstate`, bucket and region from the gitignored `backend.hcl`):
  - a multi-region CloudTrail trail `clickops-trail` for write-only management events with log file validation, logging to `clickops-trail-<account-id>` (SSE-S3, Block Public Access, 30-day expiry, the standard CloudTrail bucket policy scoped to the trail ARN, TLS-only);
  - the DynamoDB table `clickops-events`: on-demand, partition key `resource_key`, sort key `sk` (`ts#event_id`), GSI `day-ts` (`day` + `ts`), TTL attribute `expires_at`;
  - the SNS topic `clickops-critical` with an email subscription to `alert_email` from the gitignored `detector.auto.tfvars` (an example file and README are committed).
- `clickops/store.py`: the table schema (`TABLE_DEFINITION`), attribute names and the key builders `sort_key`, `day_of`, `utc_iso`, `expires_at` (90-day TTL), all in UTC.
- Tests: `tests/test_store_schema.py` checks the key builders, that the Terraform table matches the Python schema, and that the schema supports a per-resource query and a per-day range query against moto. `tests/test_detector_infra.py` checks the trail, bucket, table and topic settings in the Terraform text.

**Tests**
- `make check`: ruff clean, mypy strict clean, pytest 259 passed.

**Deviations**
- The sort key attribute is named `sk` (the plan only says "sort key `ts#event_id`").
- The trail lives in `ap-south-1` and `include_global_service_events` is on so IAM events are captured; the moment IAM and Route 53 events reach EventBridge is verified on Day 12.
- Terraform is not installed here, so `fmt`, `validate` and `plan` were not run on these files.
- One commit (the detector infra test) was pushed while a retention-default assertion was failing; the next commit fixed it. No other commit was red.

**Needs the human**
- Copy `detector.auto.tfvars.example` to `detector.auto.tfvars`, set `alert_email`, copy `backend.hcl.example` to `backend.hcl`, then run `terraform init -backend-config=backend.hcl`, `validate` and `plan` in `infra/detector` and approve the apply.
- Click the confirmation link in the SNS subscription email. "Done when": `terraform plan` is clean and the subscription is confirmed.
- With the detector root now present, the Day 5 PR plan job will start planning it; it needs `detector.auto.tfvars` values too, so set a repository variable or add `TF_VAR_alert_email` for the workflow (not yet wired).
