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

## Day 21: real end-to-end and week-3 review (code part)

**Built**
- `scripts/e2e_alerts.sh` (needs `CONFIRM=yes` and approval): allows SSH from `0.0.0.0/0` on the sandbox `admin` group and attaches `AmazonS3FullAccess` to `clickops-sandbox-app`, and for each waits for the stored finding and checks the outcome and severity (critical and warning). It does not revert anything; reverting is `terraform apply` in `infra/sandbox`, which stays with the human.
- `scripts/wait_for_finding.py`: polls the events table through the day index for a resource and event, prints the measured delay, actor, outcome and severity as JSON, and exits non-zero on a timeout or mismatch. Reusable for the full end-to-end run later.
- `docs/alert-examples.md`: the Slack payload and email for both scenarios, rendered from fixtures by `scripts/render_example_alerts.py`; a test fails when the doc is stale.
- Offline evidence for the two scenarios: `tests/test_pipeline_moto.py` already runs both through the real comparators and rules (world SSH is critical with the added rule in the diff; attaching a managed policy is a warning with the diff).

**Tests**
- `make check`: ruff clean, mypy strict clean, pytest 643 passed.

**Deviations**
- None in the code. The live part of the day is not done: there are no AWS credentials here.

**Needs the human (the day's "Done when" is not met until then)**
- Make sure everything below is in place: the Day 3 and 4 applies, the four repository variables, the Slack webhook stored with `scripts/store_slack_webhook.sh`, the SNS email subscription confirmed, a freshly built Lambda zip and `infra/detector` applied.
- Run `CONFIRM=yes AWS_PROFILE=clickops-admin scripts/e2e_alerts.sh`. It prints the delay for each scenario; copy those numbers here. Confirm a red critical message in `#clickops-alerts` plus an email for the SSH change, and an orange warning showing the diff for the policy attachment.
- Revert with `terraform apply` in `infra/sandbox`, and check the two revert events are stored as `cli-human` (and ignored only if they match state).

**Week-3 summary (Days 15-21)**

| Day | Code and docs | AWS-dependent "Done when" |
| --- | --- | --- |
| 15 state reader | done: format 4 index by type and ID and by ARN, parent mapping, ETag cache, no values logged | real sandbox state capture (fixture is synthetic) |
| 16 SG and IAM resolvers | done | confirm real `ModifySecurityGroupRules` carries `groupId` |
| 17 other resolvers | done: S3, EC2, Lambda, Route 53, unwatched events logged once | replay real recordings |
| 18 comparators | done: six types, moto tests per attribute, explicit read permissions | first real run shows any missing permission |
| 19 rules and pipeline | done: outcomes, critical overrides, tag and config handling, golden tests, failures raise | DLQ delivery check with `scripts/force_error.sh` |
| 20 alerts | done: Slack Block Kit, email, repeat window, SSM and SNS permissions | store the webhook, then post a real message |
| 21 live end to end | script and examples done | the live run, the delays and the revert |

- 643 tests pass. Every fixture goes through normalize, classify, resolve, state lookup, compare, decide, store and alert against moto, with golden files for the stored items.
- Remaining AWS work, in dependency order: apply bootstrap and sandbox (Days 3-4), set the four repository variables, store the Slack webhook, build the Lambda zip and apply `infra/detector`, confirm the SNS subscription, run the checks from Days 11-14 and 19-20, then `scripts/e2e_alerts.sh` and revert.
- Risks to watch on the first live run: the exact CloudTrail field for the console flag (Day 9), read permissions the comparators need beyond the ones granted (Day 18), `clickops-ci` permissions for the detector plan and apply (Day 5), and the CloudTrail-to-EventBridge delay (Day 13).

## Day 22: `clickops scan`

**Built**
- `clickops/scan.py`: `scan(index, region, table)` lists live resources of the six types with read-only calls and returns those whose Terraform type and ID are in no state file, sorted by type and ID. Exclusions: the default security group of every VPC, terminated and shutting-down instances, roles under `/aws-service-role/`, `AWSReservedSSO_*` roles, AWS-managed policies (only customer-managed ones are listed), buckets outside the scanned region, and NS and SOA records. Records of a hosted zone that state does not know are not listed one by one (the zone is reported instead). A resource's creator is the actor of its first stored `shadow-create` event in `clickops-events`; a missing table or no stored event leaves it blank rather than failing.
- `clickops scan [--config] [--region] [--json]`: reads the configured state files, prints a rich table (type, ID, name, created date where AWS gives one, creator) or JSON, and says so when nothing is unmanaged. A bad config or state file exits with code 2.
- `tests/test_scan.py`: moto tests for every exclusion, managed versus unmanaged matching per type, the creator lookup (found, unknown, table missing), ordering and JSON, and the command itself.

**Tests**
- `make check`: ruff clean, mypy strict clean, pytest 660 passed.

**Deviations**
- Lambda functions have no creation date in the API, so their "created" column is blank.
- Instance launch times and bucket and role creation dates are shown; policies show their creation date.

**Needs the human**
- Run `AWS_PROFILE=clickops-admin uv run clickops scan --config clickops.yaml` against the real sandbox account (with `clickops.yaml` copied from `clickops.example.yaml` and real state locations) and write the list it prints into this file. The day's "Done when" expects only genuinely unmanaged things there (for example the bootstrap state bucket and role if they are not in a configured state, and any leftover scratch resources from the fixture recording). The identity needs read access to EC2, IAM, S3, Lambda, Route 53 and the events table.

## Day 23: `clickops import`

**Built**
- `clickops/importer.py`:
  - `render_imports` writes one `import { to = <type>.<name>  id = "<id>" }` block per shadow resource, using each type's provider import ID: the group ID, role name, policy ARN, bucket name, instance ID, function name, hosted zone ID, and `ZONEID_name_TYPE` for a record. Names are derived from the resource name, made valid and unique (records of different types get different names).
  - `write_imports` creates `imports/<timestamp>/imports.tf` (the folder is gitignored).
  - `generate_config` copies the blocks into a temporary directory with a `providers.tf` (Terraform `>= 1.10`, AWS provider `~> 5.81`, the region), runs `terraform init`, `terraform plan -generate-config-out=generated.tf` and `terraform validate -json`, keeps `generated.tf` next to `imports.tf`, and records the plan summary line. If validation fails the file is kept with a comment header listing the errors. A failed init or plan raises with the end of Terraform's output; a missing binary is reported clearly. Nothing is ever applied.
- `clickops import [--config] [--region] [--only ID|type/id ...] [--out DIR] [--no-terraform] [--terraform BIN]`: scans for shadow resources, writes the blocks, runs the steps and prints the plan summary and validation result. Exit codes: 0 done, 1 generated config does not validate yet, 2 bad config or state, 3 Terraform failed or is missing (the import blocks are kept).
- `scripts/test_import_bucket.sh` (needs `CONFIRM=yes`): creates a scratch bucket, imports it, requires "1 to import, 0 to add, 0 to change, 0 to destroy" and a validating config, and deletes the bucket on exit.
- Tests: import blocks for all six types, name rules, the exact Terraform steps with a fake runner (order, flags, temporary directory cleaned up, nothing applied), validation errors, failures, and the command against moto with that fake runner.

**Tests**
- `make check`: ruff clean, mypy strict clean, pytest 683 passed.

**Deviations**
- Terraform is not installed in this environment, so the real `terraform init`, `plan -generate-config-out` and `validate` were never run; they are covered with a fake runner. The provider is pinned the same way as the repo's roots, without the repo's `default_tags`, so generated configs stay free of them.
- A security group rule would use its `sgr-` ID, but `scan` reports groups, not rules, so rule imports are not generated yet.

**Needs the human (the day's "Done when" is not met until then)**
- With Terraform 1.10+, a real `clickops.yaml` and AWS access, run `CONFIRM=yes AWS_PROFILE=clickops-admin scripts/test_import_bucket.sh`. It should end with "OK" and show the plan line "1 to import, 0 to add, 0 to change, 0 to destroy". If Terraform's generated config has errors, the script fails and the kept `generated.tf` shows them in its header.

## Day 24: least privilege for both roles

**Built**
- `infra/bootstrap/policies/*.json.tftpl`: the `clickops-ci` permissions rewritten as five resource-scoped policy templates (state and buckets, EC2, IAM and Lambda, data and events, observability and DNS), attached as customer-managed policies through `templatefile` and `aws_iam_role_policy_attachment`. The old inline policy with `iam:*`, `lambda:*`, `dynamodb:*`, `sns:*`, `sqs:*`, `events:*`, `cloudtrail:*`, `logs:*`, `cloudwatch:*` and `s3:*` on `clickops-*` is gone.
  - No wildcard actions: every action is listed. `Resource: *` remains only on read-only list and describe calls and on calls AWS cannot scope (`CreateHostedZone`, the Route 53 lookups, `GetChange`, `kms:ListAliases`, `access-analyzer:ValidatePolicy`).
  - State objects are limited to `sandbox/*` and `detector/*`; the managed buckets are named exactly; DynamoDB, SNS, SQS, the trail, the Lambda functions, the three clickops roles, the log groups and `clickops-*` rules and alarms are named; EC2 writes are limited to the account and `ap-south-1`.
  - `iam:AttachRolePolicy` may attach only `AWSLambdaBasicExecutionRole`; `iam:PassRole` is limited to the roles that need it and to Lambda or EventBridge; there is no way to create users, other roles or arbitrary policies.
- The detector's own policy (Day 18-20) was already listed action by action and scoped by ARN where AWS supports it; its remaining account-wide read scopes (any role, bucket, function or hosted zone) are needed because which resources to read comes from state.
- `scripts/validate_policies.py`: sends policies to IAM Access Analyzer and fails on any `ERROR` or `SECURITY_WARNING` finding. CI runs it on every IAM policy and trust policy found in the `sandbox` and `detector` plans (`terraform plan -out`, `terraform show -json`) and, in a separate job, on the CI policy templates rendered with placeholders. Policies whose documents are unknown until apply are skipped by the plan check.
- `docs/threat-model.md`: what each role can do, what an attacker holding the detector's role could do (read the two state files, read the Slack webhook, write events, read the six resource types) and what clickops does not protect against.
- Tests: size limit per policy, no wildcard actions, `*` resources only for the listed calls, resources inside this account and region, IAM actions limited to the three clickops roles, attachment and `PassRole` conditions, state paths, the validator against a fake Access Analyzer, the workflow steps and the threat-model content.

**Tests**
- `make check`: ruff clean, mypy strict clean, pytest 715 passed.

**Deviations**
- EC2 resources cannot be named before they exist, so EC2 permissions are scoped to the account and region rather than to tags; tag conditions would be a v0.2 hardening.
- The CI policy templates reach CI only after the owner applies `infra/bootstrap` with the admin profile (CI cannot change its own role); until then the old policy stays in force.
- Terraform and Access Analyzer could not be run here, so the policies were never exercised against AWS.

**Needs the human**
- Run `terraform plan` in `infra/bootstrap` with the admin profile (the plan should replace the inline policy with five managed policies and attachments), then approve the apply.
- Run `uv run python scripts/validate_policies.py --templates infra/bootstrap/policies` with AWS access to confirm Access Analyzer reports no errors or security warnings; CI also does this on the next pull request.
- Open a pull request that touches `infra/` and check that the plan job still succeeds with the narrowed role. An `AccessDenied` in a plan or apply names the missing action; add it to the matching template (the first real plans are the likeliest place for a missing read action such as an extra `ec2:Describe*` call) and re-run.
- Repeat the Day 21 scenarios (`scripts/e2e_alerts.sh`) after the apply to confirm both alerts still arrive.

## Day 25: tamper alerts and `clickops status`

**Built**
- Tamper detection: `StopLogging`, `DeleteTrail`, `UpdateTrail` and `PutEventSelectors` on `clickops-trail`; `DisableRule`, `DeleteRule` and `RemoveTargets` on any `clickops-*` rule; `DeleteFunction` and `UpdateFunctionCode` on `clickops-detector`. By anyone except `clickops-ci` (including humans, AWS services and the detector's own role) they become a critical `tamper` outcome, decided before every other rule so tags, ignore rules and severity overrides cannot silence them; by CI they are `ignored`. The handler does not read Terraform state for them, so tamper alerts work even if state is unreadable. The alert tells the reader to `cd infra/detector && terraform apply`.
- New resolvers for CloudTrail and EventBridge calls (`resolvers/own.py`, resource types `trail` and `event-rule`).
- `infra/detector`: a third rule `clickops-tamper` (pattern `patterns/tamper.json`, home region) with the same target, DLQ and retries. A rule cannot see its own disable call, so this rule watches the other two and the regional rule watches it. The `global` pattern is now limited to `us-east-1` and the tamper pattern to `ap-south-1` so no event matches both. The Lambda events on the detector function still arrive through the regional rule.
- Fixtures: seven CloudTrail and EventBridge tamper fixtures, two Lambda fixtures on `clickops-detector`, and CI variants; golden files for all of them. `scripts/test_event_patterns.sh` also checks the tamper pattern.
- `clickops status` (`clickops/status.py`): CloudTrail logging on or off, each of the four rules enabled (three in `ap-south-1`, the forwarder in `us-east-1`), time and name of the last stored event (looked up through the day index, ignoring alert counters), dead-letter queue depth and open `clickops-*` alarms. Exit code 1 when anything is wrong.
- README: the outcomes table now lists `tamper` and the commands.

**Tests**
- `make check`: ruff clean, mypy strict clean, pytest 820 passed. Every tamper fixture produces a critical `tamper` finding through the full handler without state; the CI variants are ignored; `status` is tested against moto for each check.

**Deviations**
- A tamper call that disables the last remaining watcher cannot be seen by it. Two rules watch each other, the `us-east-1` forwarder is not watched at all, and `clickops status` reports the state of all four, so a periodic `status` run (or a check after every apply) is the backstop. This is recorded in the threat model's list of gaps.
- Only `DeleteFunction` and `UpdateFunctionCode` are tamper calls on the detector function (as the plan lists); other changes to it are still `managed-drift` through the detector root's state.

**Needs the human (the day's "Done when" is not met until then)**
- Apply `infra/detector` (new rule and pattern changes), then run `AWS_PROFILE=clickops-admin uv run clickops status` and confirm every row says `ok`. Re-run `scripts/test_event_patterns.sh` to confirm all fixtures match the intended rules in EventBridge itself.
- To see a live tamper alert, with approval, run `aws events disable-rule --name clickops-tamper` and then `aws events enable-rule --name clickops-tamper`; the disable should alert as `tamper`.

## Day 26: scripted end-to-end test

**Built**
- `scripts/e2e.sh` (needs `CONFIRM=yes`): runs the six scenarios with the admin profile and, for each, waits up to 10 minutes (`E2E_TIMEOUT`) for the stored finding and checks its outcome and severity: SSH from `0.0.0.0/0` on `admin` (critical `managed-drift`), `AmazonS3FullAccess` attached to the sandbox role (warning), Block Public Access off on the sandbox bucket (critical), Lambda timeout changed (warning), a Route 53 record value changed (warning), and a new bucket made by the CLI (info `shadow-create`). It then reverts and requires `terraform plan` to show no changes.
- `scripts/wait_for_finding.py` gained `--label` and `--append`, so each scenario's expected and actual outcome, severity, actor and measured delay are collected; `scripts/e2e_report.py` renders them into `docs/e2e-results.md` (table, pass count, fastest, slowest and mean delay, revert state). `docs/e2e-results.md` currently says it has not been run.
- Interrupted runs still revert (an `EXIT` trap).
- Tests: the scenarios' expected severities and event names, the timeout, the revert steps and trap, report rendering for passes, failures and timeouts, and the exit codes.

**Tests**
- `make check`: ruff clean, mypy strict clean, pytest 833 passed.

**Deviations (a correction to the plan)**
- The plan says to revert with one `terraform apply`. That does not undo scenarios 1 and 2: Terraform does not remove a security group rule or a role policy attachment that is not in its configuration (the group has no inline rules and the attachment is a separate resource). `scripts/e2e.sh` therefore undoes those two with the inverse CLI calls, scenarios 3 to 5 with `terraform apply` (it asks for approval; `TF_APPLY_ARGS=-auto-approve` skips that), deletes the scenario 6 bucket, and finishes with a `terraform plan -detailed-exitcode` that must be clean. `scripts/e2e_alerts.sh` (the earlier two-scenario check) had the same wrong revert instruction and now offers `REVERT=yes` with the inverse calls. If you already ran it and applied Terraform to "revert", check the admin group and the role by hand: `aws ec2 describe-security-groups` and `aws iam list-attached-role-policies --role-name clickops-sandbox-app`.
- The live run was not done: there are no AWS credentials here.

**Needs the human (the day's "Done when" is not met until then)**
- With everything from Days 3 to 25 in place (applies, repository variables, webhook, detector applied and a fresh Lambda zip), run `CONFIRM=yes AWS_PROFILE=clickops-admin scripts/e2e.sh`, approve the Terraform apply at the end, and commit the `docs/e2e-results.md` it writes. All six scenarios must pass in one run. Route 53 findings arrive through the `us-east-1` forwarding rule, so expect the longest delay there.

## Day 27: packaging and release pipeline

**Built**
- Version `0.1.0` in `pyproject.toml` (the `clickops` console script was already declared), with `clickops --version` and `clickops.__version__` read from the installed package metadata. A test keeps `pyproject.toml`, the package and `CHANGELOG.md` in step.
- `CHANGELOG.md` with the 0.1.0 section: features, the six resource types, outcomes and severity, alerts, tamper detection, the CLI commands, the three Terraform roots, CI and release automation, and known limitations. The heading says "Unreleased" until the owner tags it (Day 30 sets the date).
- `.github/workflows/release.yml`: on a `v*` tag it runs `make check`, extracts the release notes from `CHANGELOG.md` (`scripts/release_notes.py`, which also checks that the tag matches the project version and that a changelog section exists), builds the wheel and the reproducible Lambda package (renamed with the version), writes `SHA256SUMS`, smoke-tests the wheel, and creates the GitHub release with all three files. A tag with a suffix such as `v0.1.0-rc1` is published as a pre-release with notes taken from the `0.1.0` section.
- `scripts/smoke_install.sh`: installs a wheel into a clean virtual environment (with `uv`, so it gets Python 3.12 whatever the system python is), runs `clickops --version` and `clickops doctor`, and requires doctor to produce its report and exit 1 when there are no credentials or config.
- The doctor fix hint now says the example config is in the repository (pip and pipx installs do not ship it).
- Tests: the console script and wheel settings, version consistency, tag parsing and rejection of malformed tags, the notes for releases and pre-releases, mismatched versions, the workflow's order of steps, its attached files and permissions, and the smoke script.

**Tests**
- `make check`: ruff clean, mypy strict clean, pytest 854 passed.
- Done here for real: `uv build --wheel` produced `clickops-0.1.0-py3-none-any.whl`, and `scripts/smoke_install.sh` installed it into a fresh Python 3.12 environment where `clickops --version` printed `clickops 0.1.0` and `clickops doctor` printed its table of failing checks (no credentials, no Terraform, no config) and exited 1, as intended.

**Deviations**
- The wheel for `v0.1.0-rc1` is still named `0.1.0` (the version in `pyproject.toml`); only the GitHub release is marked a pre-release.
- Tags and releases are created on GitHub, which this environment cannot do, so the "Done when" is not met yet.

**Needs the human**
- Push a pre-release tag from `main`: `git tag v0.1.0-rc1 && git push origin v0.1.0-rc1`. The release workflow should finish green and attach the wheel, `clickops-detector-0.1.0.zip` and `SHA256SUMS`.
- Check from a clean machine: `pipx install https://github.com/<owner>/clickops/releases/download/v0.1.0-rc1/clickops-0.1.0-py3-none-any.whl` (or `pipx install git+https://github.com/<owner>/clickops`), then `clickops doctor`. Delete the rc release and tag if you do not want it kept.

## Day 28: README and demo

**Built**
- `README.md` rewritten in the planned order: the problem in three sentences, the demo GIF, what it detects (coverage table checked against the comparators, then the outcomes table), a Mermaid architecture diagram, a five-step quickstart (clone and install, bootstrap, sandbox, build and apply the detector with the Slack webhook, configure and check), the commands table, cost (from `docs/cost.md`), the security model (linking `docs/threat-model.md`), the limitations stated plainly, and how clickops differs from a scheduled `terraform plan`.
- `demo/demo.tape` (VHS): `clickops scan`, `clickops import` on a scratch bucket, `clickops events`. `demo/prepare.sh` creates the tagged empty bucket and `demo/cleanup.sh` deletes it (it refuses names that do not start with `clickops-demo-`) and the `imports/` folder. `demo/README.md` explains how to re-record.
- `tests/test_readme.py`: section order, relative links, five numbered quickstart steps, scripts and example files named in the quickstart exist, limitations present, the tape runs the commands in order.

**Tests**
- `make check`: ruff clean, mypy strict clean, pytest 862 passed.

**Deviations**
- `demo/demo.gif` is not committed (no VHS, AWS or Terraform here), so the README image link is broken until the owner records it. The link test allows exactly that one missing file.
- The README recommends the USD 5 budget as a guardrail; no Terraform in this repo creates it.
- The quickstart has not been followed from a fresh clone by anyone (Day 29 does that), and no Terraform command in it has ever been run.

**Needs the human**
- Install VHS and run `AWS_PROFILE=clickops-admin vhs demo/demo.tape` once the detector is applied, then commit `demo/demo.gif`.
- Optional: make one console change and add a screenshot of the Slack alert to the README.
- Replace `<owner>` in the clone URL if wanted.

## Day 29: fresh-clone verification and teardown

**Fresh-clone run (done here, as far as it can go without Terraform or AWS)**
- Cloned the repository into a new directory and followed the README quickstart: `uv sync`, `clickops --version` and `scripts/build_lambda.sh` (zip built, same hash as before) all worked, and every `*.example` file the README names copied cleanly.
- Not done: `terraform plan` for the three roots. There is no Terraform binary here, and no AWS credentials.
- Gaps found and fixed:
  - `clickops doctor` on the copied example config produced a raw botocore "Invalid bucket name" error. The config loader now rejects any `<placeholder>` left in a value, with a message that names them (comments are ignored). The shipped example test now fills the placeholders first.
  - `clickops.yaml` is copied into the Lambda zip, but the quickstart created it after the build. The quickstart now has a "Configure" step before "Build and apply the detector" (still five steps), says where the state bucket name comes from (the `state_bucket` bootstrap output), and that trusted CI roles can also go in `trusted_role_arns` and that a later config change needs a rebuild and apply.
  - `infra/detector/README.md` still said the Lambda, rules and alarms came "later" and did not mention building the zip first. Fixed.
  - Teardown would have failed: no clickops bucket sets `force_destroy`, so Terraform cannot delete a bucket that holds objects (the trail logs, the versioned state bucket, the sandbox bucket).

**Built**
- `make destroy` (`scripts/destroy.sh`): prints what it will remove, asks you to type `destroy <account-id>`, then runs sandbox, detector (then deletes the SSM webhook parameter) and bootstrap in that order. Each bucket is emptied right before its own destroy with `scripts/empty_bucket.py` (all versions and delete markers, only `clickops-*` names), and Terraform still prompts per root unless `TF_DESTROY_ARGS=-auto-approve`. `DRY_RUN=1` prints the plan only. It checks the local `backend.hcl` and tfvars files first, builds the Lambda zip if missing (Terraform reads it while planning a destroy), and stops at the first failed destroy.
- `scripts/cost_report.py`: one Cost Explorer call for last month's cost of everything tagged `project=clickops`, by service (USD 0.01 per call).
- README "Teardown" section; `docs/cost.md` "Checking the real figure" section.
- Tests: the config placeholder check, `empty_bucket.py` against moto (versions, delete markers, missing bucket, refusal of other names), `destroy.sh` with stand-in aws, terraform and uv commands (dry run, wrong or missing confirmation, missing files, exact call order, init arguments, zip rebuild, argument pass-through, missing SSM parameter, a failed destroy stopping later roots), the cost report's month maths and summary.

**Tests**
- `make check`: ruff clean, mypy strict clean, pytest 883 passed before the last doc commits (docs only after that).

**Deviations**
- `make destroy` was not run, as the plan says. The monthly cost in `docs/cost.md` is still an estimate: the Cost Explorer call needs credentials and costs a cent.
- The "done when" (a fresh-clone run needing no steps outside the README) is only met for the parts that run without AWS and Terraform.

**Needs the human**
- On a laptop with Terraform: clone fresh, follow the README, and run `terraform plan` (no apply) in `infra/bootstrap`, `infra/sandbox` and `infra/detector`. Terraform `fmt`, `validate` and `plan` have never been run on these files, so expect small fixes; tell me what breaks.
- After a full month: activate the `project` cost allocation tag in Billing, run `scripts/cost_report.py`, and put the figure in `docs/cost.md`.
- Run `DRY_RUN=1 make destroy` to read the plan. Only run the real one when you want everything gone.

## Day 30: buffer and v0.1.0

**Done**
- Re-ran `make check` on `main`: ruff clean, mypy strict clean, pytest 889 passed.
- Added the Day 27 to 29 items to `CHANGELOG.md` and a release checklist, `docs/release-checklist.md`, that maps each line of the definition of done to the command that verifies it and what it needs. Checked its credential search for real: no `AKIA` key or Slack webhook URL is in the repository apart from the fake key in `tests/test_fetch_fixtures.py` that proves redaction works.
- Nothing was left over from Days 1 to 29 that can be built without AWS.

**Not done (needs you)**
- `scripts/e2e.sh`, the Terraform CI run on `main` and the first `terraform plan` of the three roots need an AWS account and Terraform, so the definition of done is not met.
- The `v0.1.0` tag was not created: it must follow a green live run. Steps are in `docs/release-checklist.md` (optional `v0.1.0-rc1` first, set the date on the changelog heading, then `git tag v0.1.0 && git push origin v0.1.0`).

## Final summary

clickops 0.1.0 is complete in code. One Python 3.12 package serves both the CLI (`doctor`, `events`, `scan`, `import`, `status`) and the detector Lambda. The Lambda turns a CloudTrail write event into a stored finding and a Slack or email alert: normalize, classify the actor, resolve the resource, compare with Terraform state, decide outcome and severity. It covers six resource types, detects tampering with its own trail, rules and function, and never reverts anything. Three Terraform roots (bootstrap, sandbox, detector) build the infrastructure, with GitHub OIDC and scoped least-privilege policies checked by Access Analyzer. Releases, the reproducible Lambda zip, a threat model, a cost document, a teardown command and a README quickstart are in place. 889 tests run on moto and synthetic fixtures; nothing has run against a real AWS account.

**Everything that needs a human, in order**
1. Create the repository variables, then `terraform apply` the bootstrap, sandbox and detector roots. Expect small Terraform fixes on first use: `fmt`, `validate` and `plan` have never been run.
2. Store the Slack webhook (`scripts/store_slack_webhook.sh`) and confirm the SNS email.
3. Record real fixtures (`scripts/fetch_fixtures.py`) and replace the synthetic ones.
4. Run `scripts/e2e_alerts.sh`, `scripts/e2e.sh` and `scripts/test_import_bucket.sh`; commit `docs/e2e-results.md`.
5. Run `clickops scan` and `clickops status` against the real account.
6. Record `demo/demo.gif`; optionally add a Slack alert screenshot.
7. After a month, run `scripts/cost_report.py` and update `docs/cost.md`.
8. Push `v0.1.0-rc1`, check the release assets, then tag `v0.1.0`.

## v0.2 ideas

- More resource types: RDS, SQS and SNS, KMS keys, VPC route tables and network ACLs, DynamoDB tables.
- Multi-account through AWS Organizations: an organization trail and a delegated detector account.
- Auto-revert behind an approval button in Slack, using the `terraform apply -target` command the alert already shows.
- Catch drift that makes no API call (provider changes) with a scheduled `terraform plan` that feeds the same events table.
- Several regions, and a `clickops.yaml` setting for which ones.
- A small `clickops explain <event-id>` command that shows the comparison behind a finding.
- Per-resource owners (from tags) so alerts mention the person or team responsible.
