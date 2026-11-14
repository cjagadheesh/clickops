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
- With the detector root now present, the Day 5 PR plan job will start planning it; set the repository variable `TF_ALERT_EMAIL` (the workflow passes it as `TF_VAR_alert_email`, falling back to a placeholder so `validate` and `plan` still run).

## Day 11: Lambda skeleton and packaging

**Built**
- `clickops/handler.py`: `handler` normalizes the event, classifies the actor and stores an item with outcome `unresolved` (severity `none`, resource key `unresolved#<EventName>`), then logs one structured JSON line. Failed calls are dropped, a retry of an already stored event is a no-op (conditional write), and a malformed event raises so Lambda retries it and then sends it to the DLQ. Trusted roles come from `CLICKOPS_TRUSTED_ROLES`, the table from `CLICKOPS_TABLE` and the detector's own role from `CLICKOPS_SELF_ROLE_ARN`.
- `clickops/store.py`: `build_item` and `put_event`.
- `scripts/build_lambda.sh`: exports the locked runtime dependencies (without boto3 and the CLI-only libraries), installs arm64 wheels for Python 3.12 into `build/lambda`, copies the package and writes `dist/clickops-detector.zip` with sorted entries and fixed timestamps. Two consecutive builds here gave the same sha256 (`6655fba8159adc13...`).
- `infra/detector/`: Lambda `clickops-detector` (Python 3.12, arm64, 256 MB, 30 s), log group with 14-day retention, SQS dead-letter queue `clickops-detector-dlq`, and an execution role with CloudWatch Logs writes, DynamoDB `PutItem` and `sqs:SendMessage` on the DLQ.
- `scripts/invoke_fixture.sh`: invokes the deployed Lambda with a fixture and prints the stored item.
- CI: the detector plan job builds the Lambda zip first.
- `tests/test_handler.py`: stored fields, retries, dropped and malformed events, the log line and every fixture against moto; infra tests check Lambda settings, role scope and environment variable names.

**Tests**
- `make check`: ruff clean, mypy strict clean, pytest 313 passed.

**Deviations**
- The role also has `sqs:SendMessage` on the DLQ (the plan lists only logs and `PutItem`) because Lambda needs it to deliver failed asynchronous invocations to the dead-letter queue.
- Terraform is not installed here, so `fmt`, `validate` and `plan` were not run on the new files; I aligned the environment block by hand to match `terraform fmt`.

**Needs the human**
- Run `scripts/build_lambda.sh`, then `terraform plan` and, after approval, `terraform apply` in `infra/detector`.
- "Done when": run `AWS_PROFILE=clickops-admin scripts/invoke_fixture.sh ec2/AuthorizeSecurityGroupIngress` and confirm the item appears with outcome `unresolved`. (The script and the Lambda write a real item to `clickops-events`.)

## Day 12: EventBridge rules

**Built**
- `infra/detector/patterns/regional.json` and `global.json`: the event patterns (detail-type "AWS API Call via CloudTrail", the watched event names, Lambda names matched with `prefix`). Terraform loads the same files, so tests and rules cannot drift.
- `infra/detector/rules.tf`: in `ap-south-1`, rule `clickops-regional` (`aws.ec2`, `aws.s3`, `aws.lambda`) and rule `clickops-global` (forwarded `aws.iam` and `aws.route53`), both targeting `clickops-detector` with the DLQ attached, a retry policy and a Lambda invoke permission scoped to each rule; an SQS queue policy letting EventBridge deliver dead letters. In `us-east-1` (provider alias `use1`), rule `clickops-forward-global` targeting the `ap-south-1` default bus through the role `clickops-event-forwarder`, which only has `events:PutEvents` on that bus.
- `tests/eventpattern.py`: an offline matcher for exact and prefix patterns. `tests/test_event_patterns.py` checks every fixture matches exactly the right rules and none of the others: ec2, s3 and lambda match only `regional`; iam and route53 match only the us-east-1 forwarder and, once forwarded, only `global`; unwatched, read-only and wrong-detail-type events match nothing; every watched event name is in a pattern.
- `scripts/test_event_patterns.sh`: runs every fixture through `aws events test-event-pattern` (read-only); CI runs it on detector pull requests.

**Tests**
- `make check`: ruff clean, mypy strict clean, pytest 365 passed.

**Deviations**
- The plan asks for the real `test-event-pattern` call in CI; with no AWS access here the committed tests use an offline matcher with the same semantics (exact values and prefix), and the AWS script is the cross-check for the human or CI.
- The forwarding rule has no DLQ: a rule's dead-letter queue must be in the rule's own region, and the only queue is in `ap-south-1`.

**Needs the human**
- Apply `infra/detector` (the rules reference the Lambda and DLQ), then run `AWS_PROFILE=clickops-admin scripts/test_event_patterns.sh`. "Done when": it prints "all fixtures match the expected patterns".
- After the apply, confirm in the console or with `aws events list-rules` in both regions that the three rules are enabled.

## Day 13: end-to-end smoke test (code part)

**Built**
- `clickops events --since 1h`: reads the `day-ts` index for every UTC day in the range, filters by timestamp, sorts oldest first and prints a rich table (time, actor and class, event, resource key, outcome, coloured severity). `--since` takes `30m`, `1h` or `2d`; `--json`, `--region` and `--table` are also available. Bad durations give a usage error.
- `clickops/store.py`: `query_since` (pages through results, spans midnight, ignores future events).
- `.github/workflows/terraform.yml`: `apply-detector` runs on pushes to `main` after `apply-sandbox`, builds the Lambda zip and applies `infra/detector` through OIDC.
- Tests: duration parsing, ranged queries across two days, and the command's table, JSON and empty output against moto; the workflow test now expects exactly the two applies.

**Tests**
- `make check`: ruff clean, mypy strict clean, pytest 380 passed.

**Deviations**
- None in the code. The AWS part of the day was not done (see below).

**Needs the human (the day's "Done when" is not met until then)**
1. With `clickops-admin` and your approval: add a rule allowing 8443 from `10.0.0.0/8` to the `web` group (`aws ec2 authorize-security-group-ingress --group-id <web> --protocol tcp --port 8443 --cidr 10.0.0.0/8`), then `aws iam put-role-policy` on `clickops-sandbox-app` with any small inline policy.
2. Wait for both events and run `clickops events --since 1h`; both should appear with actor class `cli-human` and the right display name. Write the measured delay from the API call to the stored item here (CloudTrail typically takes 5-15 minutes).
3. Revert with `terraform apply` in `infra/sandbox`, then check the revert events are also stored as `cli-human` (local applies run as the admin profile).
4. Merge-to-`main` now applies `infra/detector` automatically, so the detector root must have been applied once by hand (Days 10-12) before the first CI apply, and `TF_STATE_BUCKET`, `CLICKOPS_CI_ROLE_ARN`, `TF_ADMIN_CIDR` and `TF_ALERT_EMAIL` must be set as repository variables.

## Day 14: alarms and week-2 review

**Built**
- `infra/detector/alarms.tf`: alarm `clickops-detector-errors` (Lambda `Errors` sum greater than 0 over 5 minutes) and `clickops-detector-dlq-not-empty` (SQS `ApproximateNumberOfMessagesVisible` maximum greater than 0 over 5 minutes), both notifying `clickops-critical`, with missing data treated as not breaching. A topic policy lets CloudWatch alarms named `clickops-*` publish to the topic.
- `scripts/force_error.sh`: invokes the detector with a malformed event, synchronously (a Lambda error) and asynchronously (retried, then dead-lettered). A test checks the handler really rejects that payload.
- Tests for the alarm settings.

**Tests**
- `make check`: ruff clean, mypy strict clean, pytest 382 passed.

**Deviations**
- None.

**Needs the human**
- After the detector apply, run `AWS_PROFILE=clickops-admin scripts/force_error.sh` and confirm both alarm emails arrive (alarms evaluate every 5 minutes). Then purge the DLQ with the command the script prints. "Done when" is the alarm email arriving.

**Week-2 summary (Days 8-14)**

| Day | Code and docs | AWS-dependent "Done when" |
| --- | --- | --- |
| 8 normalizer | done: all 44 fixtures normalize, failed calls dropped, Lambda suffixes stripped | none |
| 9 actor classifier | done: five classes in the fixed order with edge-case fixtures | none |
| 10 trail, table, topic | done in Terraform and `store.py` | apply, then click the SNS confirmation link |
| 11 Lambda skeleton | done: handler, reproducible zip, Terraform | apply, then `scripts/invoke_fixture.sh` |
| 12 EventBridge rules | done: patterns, three rules, forwarding, offline and AWS pattern checks | apply, then `scripts/test_event_patterns.sh` |
| 13 smoke test | done: `clickops events`, detector apply in CI | the live change, the measured delay and the revert |
| 14 alarms | done in Terraform | `scripts/force_error.sh` and the alarm email |

- 382 tests pass; the full pipeline up to "store as unresolved" works against moto for every fixture.
- Nothing from Days 8-13 is unfinished in code. Everything left is an AWS step for the human, in dependency order: apply bootstrap and sandbox (Days 3-4), set the four repository variables, apply `infra/detector` (Days 10-12 and 14 together, after building the Lambda zip), confirm the SNS subscription, then run the checks above and the Day 13 live change.
- Open risks to watch on the first real run: the exact location of `sessionCredentialFromConsole` in real records (Day 9), whether `clickops-ci` needs extra permissions for the detector plan and apply (Day 5), and the CloudTrail-to-EventBridge delay (Day 13).

## Day 15: Terraform state reader

**Built**
- `clickops/state.py`: `parse_state` checks the state is format version 4 and returns the managed resources (data sources are skipped) with their address, ID and ARN; `StateIndex` looks resources up by `(type, id)` and by ARN; `build_index` merges several state files. Child resources map to their parent: security group rules to their group, `aws_s3_bucket_*` config resources to their bucket, role policies and attachments to their role, plus Lambda permissions, instance state and Route 53 records. `children()` and `owner()` expose the mapping.
- `StateReader`: reads the configured state locations from S3 with one `HeadObject` per file per call and downloads a file only when its ETag changed; keep one instance in the Lambda's global scope. Errors name the S3 location only.
- State files can hold secrets: attribute values are kept out of `repr`, and the only log line lists resource addresses.
- `infra/detector/lambda_role.tf`: the detector role may `s3:GetObject` the sandbox and detector state keys only.
- `tests/fixtures/state/sandbox-state.json`: a state file in the real format covering every resource in `infra/sandbox`, with IDs matching the CloudTrail fixtures, and a fake secret in the Lambda environment to prove nothing leaks.
- `tests/test_state.py`: every managed resource is found by ID and ARN, parents and children, version rejection, module addresses, merging, ETag caching, refresh on change and log hygiene, all against moto.

**Tests**
- `make check`: ruff clean, mypy strict clean, pytest 399 passed.

**Deviations**
- The fixture is synthetic, modelled on what the sandbox configuration produces, not a capture of the real state (no AWS access here). It is named `sandbox-state.json` because `*.tfstate*` is gitignored.
- The fixture's `ingress` and `egress` lists on the security groups are empty because rules are separate resources; the Day 18 comparator will use the rule resources.

**Needs the human**
- Optional but recommended: pull the real sandbox state (`terraform state pull > /tmp/state.json`), scrub secrets and IDs you don't want public, save it over `tests/fixtures/state/sandbox-state.json` (keeping the IDs consistent with the event fixtures or updating them) and run `make check` to confirm the index still resolves every resource.
- Apply `infra/detector` so the new state-read permission exists.

## Day 16: resolvers for security groups and IAM

**Built**
- `clickops/resolvers/__init__.py`: `resolve(event) -> list[ResourceRef]`, a registry keyed by CloudTrail event source (`ec2.amazonaws.com`, `iam.amazonaws.com`); an unknown source gives an empty list.
- `resolvers/base.py`: the `ResourceRef.type` names (`sg`, `iam-role`, `iam-policy`, `s3`, `ec2`, `lambda`, `route53-zone`, `route53-record`), the map from each to its Terraform state type, `find_in_state(index, ref)` and request/response parameter helpers.
- `resolvers/sg.py`: `CreateSecurityGroup` uses `responseElements.groupId`; delete, authorize, revoke and `ModifySecurityGroupRules` use `requestParameters.groupId`, so rule-level calls resolve to the parent group.
- `resolvers/iam.py`: role calls (create, delete, trust policy update, inline policy put and delete, attach and detach) resolve to the role (the ARN comes from `CreateRole`'s response when present); `CreatePolicy` and `CreatePolicyVersion` resolve to the policy ARN.
- Fixtures: the create fixtures now use a new security group and scratch role that are not in state, so "not found" is exercised (shadow creates) next to "found" for the managed ones.
- `tests/test_resolvers_sg_iam.py`: a table gives each of the 21 SG and IAM fixtures its expected ref and whether state knows it; also ARNs, rule children of the resolved group, unknown sources and names, and missing IDs.

**Tests**
- `make check`: ruff clean, mypy strict clean, pytest 425 passed.

**Deviations**
- `ModifySecurityGroupRules` resolves only when the event carries `groupId`; a real event that carries only rule IDs would need a describe call (to be checked against a real recording).
- Attach and detach resolve to the role only, because the drift is on the role even when the managed policy is AWS-owned.
- The instance events (`ec2.amazonaws.com`) are resolved on the next day.

**Needs the human**
- When real fixtures are recorded, confirm `ModifySecurityGroupRules` really includes `requestParameters.groupId`.

## Day 17: resolvers for S3, EC2, Lambda and Route 53

**Built**
- `resolvers/ec2.py`: `RunInstances` gives one ref per instance in the response, `TerminateInstances`, `StartInstances` and `StopInstances` one per instance in the request, `ModifyInstanceAttribute` the single instance; duplicates collapse.
- `resolvers/s3.py`: the eight bucket events resolve to `requestParameters.bucketName`.
- `resolvers/lambda_fn.py`: version suffixes are already stripped, so the five function events resolve to the bare function name, whether the event carries a name, a partial or full ARN, or a `name:qualifier`; `CreateFunction` reads the name from the response.
- `resolvers/route53.py`: `ChangeResourceRecordSets` gives one ref per distinct record name and type in the change batch, with the Terraform import ID format `ZONEID_name_TYPE` (lower-cased, no trailing dot, so it matches state); `CreateHostedZone` and `DeleteHostedZone` resolve to the zone (the `/hostedzone/` prefix is dropped).
- `resolvers/__init__.py`: the registry now maps each event source to a list of resolvers (`ec2.amazonaws.com` runs the security group and instance resolvers). An unwatched event or source returns an empty list and is logged once per source and name at debug level; nothing is raised.
- The create fixtures use a scratch bucket, function and hosted zone that are not in state, to exercise "not found".
- `tests/test_resolvers_rest.py`: a table for the remaining fixtures with expected refs and whether state knows them, plus a check that every fixture in the library resolves to at least one ref of a known type.

**Tests**
- `make check`: ruff clean, mypy strict clean, pytest 463 passed.

**Deviations**
- None.

**Needs the human**
- Nothing new. Real recordings (Day 6) should be replayed through `tests/test_resolvers_*.py`; Route 53 wildcard names arrive escaped (`\052`) in real events and are not decoded yet.

## Day 18: live-versus-state comparators

**Built**
- `clickops/compare/`: one module per resource type. Each reads live configuration with read-only calls and returns a `Comparison` (`exists`, plus field-level `changes` of `field`, `state`, `live`; `diff()` gives the dict a `Finding` stores).
  - security group: ingress and egress rules as sorted `proto from-to target` strings (CIDR, IPv6, referenced group, prefix list), built from the rule resources, inline blocks and legacy rule resources in state;
  - IAM role: trust policy, inline policies (name to normalized document) and attached policy ARNs; IAM managed policies: the default version's document;
  - S3 bucket: bucket policy, the four Block Public Access flags (reported one field each), versioning status and encryption algorithm, only for settings Terraform manages;
  - EC2 instance: instance type, security group IDs, instance profile and running or stopped (the `aws_ec2_instance_state` resource wins over the instance attribute);
  - Lambda function: runtime, handler, memory, timeout, role, code SHA-256 and environment variable names only (values are never read into the result);
  - Route 53 record: name, type, TTL and values.
- `compare/base.py`: `normalize_policy` parses JSON text, sorts keys and statements, and treats a single string and a one-item list as equal for actions, resources and principals (`"*"` equals `{"AWS": ["*"]}`).
- `compare/__init__.py`: `compare(event, ref, index)` returns `None` when state does not manage the ref; a resource-deleting event (`DeleteSecurityGroup`, `DeleteRole`, `DeleteBucket`, `TerminateInstances`, `DeleteFunction`, `DeleteHostedZone`) gives `exists=False` with no AWS call; a resource that is not found live also gives `exists=False`; hosted zones compare as unchanged.
- `infra/detector/lambda_role.tf`: the read-only calls the comparators make, each listed explicitly, scoped by resource ARN where AWS supports it (the two EC2 describe calls need `*`).
- Tests with moto for one change of every attribute in the plan's table, plus matching resources, missing resources, formatting-only policy differences and secrets never appearing in results.

**Tests**
- `make check`: ruff clean, mypy strict clean, pytest 526 passed.

**Deviations**
- The plan lists "code SHA-256" and "encryption algorithm" etc.; each is compared as above. A setting that Terraform does not manage (no state resource) is skipped rather than reported as drift.
- moto does not ship AWS-managed IAM policies, so the IAM tests create customer-managed policies to attach.
- The role gets `s3:ListBucket` on `arn:aws:s3:::*` because `HeadBucket` requires it.

**Needs the human**
- Nothing new. Once the detector is applied, the Day 19 end-to-end run exercises these read calls for real; any AccessDenied will name the missing action.

## Day 19: outcomes, severity and the full pipeline

**Built**
- `clickops/rules.py`: `decide(event, actor, ref, state, comparison, config)` returns an outcome, a severity and a reason.
  - Table: `managed-drift` warning, `managed-delete` critical, `shadow-create` info, `ignored` none. Machine actors (`clickops-self`, `ci`, `aws-service`) are ignored. A change to an unmanaged resource that is not a creation, and a change whose live configuration matches state, are also stored as `ignored`.
  - Critical overrides: ingress from `0.0.0.0/0` or `::/0` on any port other than exactly 80 or 443 (looked at in the requested rules and in the rules added since state, so a world-open rule that is already coded does not make every later change critical); an IAM Allow with `Action` or `Resource` `*` together with a write action (in the request's policy document or the live document that changed); S3 Block Public Access disabled (put with a flag not true, delete, or a live flag that differs from state). Attaching a managed policy such as `AmazonS3FullAccess` stays a warning.
  - `clickops:ignore=true` (state tags, `tags_all`, or tags in a create request) and `clickops.yaml` ignore rules (Terraform type and/or ID glob) make an event `ignored`; config severity overrides apply last (a specific type beats a general one) but never lower a critical override or touch ignored events.
  - Route 53: an UPSERT or CREATE of a record that state does not know is a shadow create; a DELETE of one is not.
- `clickops/handler.py`: normalize, classify, resolve, state lookup, compare, decide, store; one stored item per changed resource, with the outcome, severity, reason, Terraform address and diff (as JSON text). State is read through the cached `StateReader`; machine actors skip the state read. Settings come from a bundled `clickops.yaml` (path in `CLICKOPS_CONFIG`) or from `CLICKOPS_STATE_LOCATIONS`; `CLICKOPS_TRUSTED_ROLES` still adds CI roles.
- Failures raise instead of being swallowed: a malformed event, a missing or unreadable state object, and any AWS error such as throttling or access denied all propagate, so Lambda retries and then dead-letters the event. `infra/detector` now sets two retries on asynchronous invocations (`aws_lambda_function_event_invoke_config`) next to the existing DLQ and EventBridge retry policy.
- Golden tests: `tests/test_golden.py` replays all 45 fixtures through the full pipeline against moto (DynamoDB and S3 state) and compares the stored items with `tests/golden/<service>/<fixture>.json` (`UPDATE_GOLDEN=1` regenerates them). Live comparisons are canned there because the comparators have their own moto tests; `tests/test_pipeline_moto.py` runs the key scenarios with the real comparators (world SSH is critical with the diff, an office-only rule is a warning, a managed policy attachment is a warning, a matching change is ignored, a deleted group is a managed delete).
- `build_lambda.sh` bundles an optional, gitignored `clickops.yaml`.

**Tests**
- `make check`: ruff clean, mypy strict clean, pytest 596 passed.

**Deviations**
- Events that change a resource Terraform does not manage, and events whose result matches state, are stored as `ignored` (the spec lists `ignored` only for actors and opt-outs); alerting skips them either way.
- The golden tests canned the live side by design (see above); the pipeline test with real comparators covers the main scenarios, not every fixture.
- "Retried by Lambda and then lands in the DLQ" is configuration plus raising behaviour: it is tested up to the raise, and the retry and dead-letter delivery itself needs the deployed Lambda.

**Needs the human**
- After applying `infra/detector`, run `scripts/force_error.sh` (Day 14) and confirm the dead-lettered message and alarm; then `scripts/invoke_fixture.sh ec2/AuthorizeSecurityGroupIngress` should now store a `managed-drift` item with a diff (or an AccessDenied that names a missing read permission).
- Rebuild the Lambda zip before applying so it contains the new handler.

## Day 20: Slack and email alerts

**Built**
- `clickops/alerts.py`:
  - `render_slack` builds the Block Kit message: a header with a severity icon and the outcome title, fields for severity, outcome, resource, who (display name and source: AWS console or CLI/API), event and UTC time, the diff as a short code block (`+` live, `-` coded; lists as added and removed items, policy maps by changed name, scalars as old and new; clipped at 14 lines), the exact `terraform apply -target=...` command (shell-quoted) for managed resources, and a context line with the reason and any suppressed repeats. Shadow creates have no restore command.
  - `render_email` builds the plain-text body for critical findings. `should_alert` skips `ignored`, `unresolved` and severity `none`.
  - `Notifier.notify` posts to the webhook read from the SSM SecureString `/clickops/slack-webhook` (cached in memory, never logged; botocore debug logging is held at WARNING so response bodies cannot leak it) and publishes critical findings to `clickops-critical`. A missing webhook parameter logs a warning and skips Slack (email still goes out); a Slack failure raises.
  - Deduplication: a second finding for the same resource and actor within 10 minutes only increments a counter in a `window` row in `clickops-events` (sparse, so `clickops events` never shows it, with a TTL); the next alert after the window says how many were suppressed. The window opens only after a successful send, so a failed send is retried by Lambda.
- `handler.py`: after storing each finding it notifies with the restore targets (the resource's Terraform address plus its child resources, such as security group rules or bucket settings). The invocation fails if an alert cannot be sent, after the event is already stored.
- `infra/detector`: the role may `ssm:GetParameter` on that one parameter, `kms:Decrypt` on the AWS-managed SSM key (`alias/aws/ssm`), `sns:Publish` on `clickops-critical`, and `dynamodb:GetItem` and `UpdateItem` for the counters; the Lambda gets `CLICKOPS_CRITICAL_TOPIC_ARN` and `CLICKOPS_SLACK_PARAM`.
- `scripts/store_slack_webhook.sh`: the human's command. It reads the webhook URL with a hidden prompt (so it never reaches chat, shell history or git) and stores it as a tagged SecureString. The plain equivalent is `aws ssm put-parameter --name /clickops/slack-webhook --type SecureString --value '<paste URL>'`.
- Tests: rendered payloads for managed drift (critical and warning), managed delete, shadow create and tamper, console versus CLI labelling, diff formats and clipping, quoting, email body, delivery to Slack and SNS, the repeat window (counter, reopening, other actors and resources), missing webhook, Slack failure and retry, no webhook URL in logs, `post_json` over https only, and a tracked-files scan for webhook URLs.

**Tests**
- `make check`: ruff clean, mypy strict clean, pytest 635 passed.

**Deviations**
- Slack incoming webhooks cannot edit an earlier message, so "update a counter instead of sending a new message" is a DynamoDB counter, reported in the next alert after the window.
- One commit (the webhook URL scan test) was pushed with a failing test because it matched its own source; the next commit fixed it.

**Needs the human**
- Run `AWS_PROFILE=clickops-admin scripts/store_slack_webhook.sh` and paste the Slack webhook URL when prompted (the agent never handles it).
- Rebuild the Lambda zip and apply `infra/detector` (new permissions and environment variables).
- "Done when": `AWS_PROFILE=clickops-admin scripts/invoke_fixture.sh ec2/AuthorizeSecurityGroupIngress` should post a message to `#clickops-alerts` (and send the critical email, once the SNS subscription is confirmed). The fixture's resource must exist in the sandbox state for a diff to appear.
