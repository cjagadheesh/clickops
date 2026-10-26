# clickops — 30-Day Build Plan for Claude Code

Oct 26, 2026 · @jagadheesh

## How to use this plan

Claude Code builds clickops alone in 30 sessions, one numbered day per session, in order. Export this doc as Markdown, save it in the repo as `docs/PLAN.md`, and start each session with: *"Read docs/PLAN.md and PROGRESS.md, then do the next unfinished day."*

**Ground rules for the agent**

- **One day per session.** Finish the day's tasks and its *Done when* checks before stopping. If a day overruns, carry the rest into the next session before starting new work.
- **PROGRESS.md is the memory.** At the end of each day, append: the day number, what was built, the test results, any deviation from this plan and why, and open issues.
- **Ask before touching AWS.** Run `terraform plan` freely. Show the plan summary and wait for the human's yes before every `terraform apply` or `destroy`, and before any AWS CLI call that creates, changes or deletes a resource.
- **Cost guardrails.** Never create NAT gateways, load balancers, RDS, EKS, or running EC2 instances. Every resource carries the tags `project=clickops` and `owner=agent`. If something new would cost money, stop and ask.
- **No secrets in git.** No access keys, webhook URLs or account IDs in committed files. Secrets live in SSM Parameter Store; account-specific values go in `*.auto.tfvars`, which is gitignored.
- **Tests are the gate.** `make check` (ruff, mypy, pytest) must pass before every commit. Every new AWS behaviour is tested with moto or a recorded CloudTrail fixture before it runs against the real account.
- **Small commits.** Use Conventional Commits (`feat:`, `fix:`, `test:`, `infra:`, `docs:`), at least one per task, pushed to a `day-NN` branch and merged to `main` through a PR so CI runs.
- **Don't redesign.** The decisions under *Spec and fixed decisions* are settled. If one turns out to be wrong, record the problem in PROGRESS.md and choose the smallest fix; don't swap tools.

**The human's part:** the one-time setup below, approving applies, and reading each day's PR. Reading the PRs matters: interviewers will ask why clickops works the way it does, and *the agent wrote it* won't be an answer.

## Before Day 1: what only you can do

The agent can't create accounts or handle credentials, so these take about an hour, once.

- [ ] **AWS sandbox account.** Use a separate account (or one you use only for portal and clickops), never one with anything important in it. Turn on MFA for the root user.
- [ ] **Budget alarm.** In AWS Budgets, create a USD 5 monthly cost budget that emails you at 50% and 100%.
- [ ] **Local admin profile.** Create an IAM user or Identity Center user with AdministratorAccess, and configure it as the profile `clickops-admin` with `aws configure` (or `aws configure sso`). The agent uses this profile only for bootstrap and for applies you approve.
- [ ] **Tools on your laptop:** Terraform 1.10 or newer, Python 3.12, uv, AWS CLI v2, `gh` (logged in), and VHS for the demo GIF on Day 28.
- [ ] **GitHub repo:** create an empty public repo `clickops` and clone it to `~/Dev/clickops`.
- [ ] **Slack webhook:** create a free Slack workspace (or use one you own), add an Incoming Webhook to a `#clickops-alerts` channel, and keep the URL ready. On Day 20 the agent gives you one command that stores it in SSM; you paste the URL there, not into chat.
- [ ] **Region:** the plan assumes `ap-south-1` (Mumbai). IAM and Route 53 are global services whose events arrive in `us-east-1`, and the plan handles that.

To start Day 1, open Claude Code in `~/Dev/clickops` and paste the session prompt from the section above.

## Spec and fixed decisions

clickops v0.1 watches one AWS account, alerts when a person changes Terraform-managed infrastructure outside Terraform, and turns console-made resources into Terraform code.

**Three user-facing features**

1. **Live drift alerts.** Within a few minutes of a write call, Slack gets: who did it, from where (console or CLI), what changed versus Terraform state, and a severity.
2. **`clickops scan`** lists shadow resources: they exist in AWS but in no Terraform state.
3. **`clickops import`** writes Terraform `import` blocks for shadow resources and runs `terraform plan -generate-config-out` to produce starter HCL.

**How an event flows:** CloudTrail records the API call → EventBridge rule (write events, six services) → `clickops-detector` Lambda → normalize the event → classify the actor → resolve the resource → look it up in Terraform state → compare live config with state → decide outcome and severity → store in DynamoDB → alert Slack (and SNS email for critical).

&#91;embedded content: clickops architecture · event path and CLI\]

The Lambda is the only moving part: everything left of it is AWS doing its normal job, and everything right of it is output.

**Fixed technical decisions**

| Area | Decision |
| --- | --- |
| Language | Python 3.12, managed with uv; one package `clickops` used by both the CLI and the Lambda |
| Libraries | boto3, typer (CLI), rich (tables), pydantic v2 (models and config) |
| Quality | ruff (lint and format), mypy strict on `clickops/`, pytest, moto for AWS mocks |
| IaC | Terraform 1.10+, AWS provider 5.x, S3 backend with `use_lockfile = true` (no DynamoDB lock table) |
| CI/CD | GitHub Actions; AWS access only through GitHub OIDC and the role `clickops-ci`, never stored keys |
| Region | `ap-south-1`, plus a forwarding rule in `us-east-1` for IAM and Route 53 events |
| Event store | DynamoDB table `clickops-events`, on-demand, TTL 90 days |
| Secrets | Slack webhook in SSM Parameter Store, SecureString `/clickops/slack-webhook` |
| Config | `clickops.yaml`: state locations, trusted roles, ignore rules, severity overrides |
| Opt-out | a resource tagged `clickops:ignore=true` never alerts |

**Outcomes and severity**

| Outcome | Meaning | Default severity |
| --- | --- | --- |
| `managed-drift` | a person changed a resource that is in Terraform state | warning |
| `managed-delete` | a person deleted a resource that is in Terraform state | critical |
| `shadow-create` | a person created a resource that no state knows about | info |
| `ignored` | actor is CI, clickops itself or an AWS service, or the resource is opted out | none (stored, not alerted) |

Any outcome becomes **critical** when the resulting config: allows ingress from `0.0.0.0/0` or `::/0` on a port other than 80 or 443; grants an IAM policy with `"Action": "*"` or `"Resource": "*"` together with a write action; or disables S3 Block Public Access.

**Resource coverage (v0.1: exactly these six)**

| Resource | CloudTrail events watched | Where the ID is | Terraform types matched |
| --- | --- | --- | --- |
| Security group | `CreateSecurityGroup`, `DeleteSecurityGroup`, `AuthorizeSecurityGroupIngress/Egress`, `RevokeSecurityGroupIngress/Egress`, `ModifySecurityGroupRules` | `requestParameters.groupId` (create: `responseElements.groupId`) | `aws_security_group`, `aws_vpc_security_group_ingress_rule`, `aws_vpc_security_group_egress_rule` |
| IAM role and policy | `CreateRole`, `DeleteRole`, `UpdateAssumeRolePolicy`, `PutRolePolicy`, `DeleteRolePolicy`, `AttachRolePolicy`, `DetachRolePolicy`, `CreatePolicy`, `CreatePolicyVersion` | `roleName`, `policyArn` | `aws_iam_role`, `aws_iam_role_policy`, `aws_iam_role_policy_attachment`, `aws_iam_policy` |
| S3 bucket | `CreateBucket`, `DeleteBucket`, `PutBucketPolicy`, `DeleteBucketPolicy`, `PutBucketPublicAccessBlock`, `DeleteBucketPublicAccessBlock`, `PutBucketVersioning`, `PutBucketEncryption` | `bucketName` | `aws_s3_bucket` and its `aws_s3_bucket_*` config resources |
| EC2 instance | `RunInstances`, `TerminateInstances`, `ModifyInstanceAttribute`, `StartInstances`, `StopInstances` | instance IDs in request or response | `aws_instance`, `aws_ec2_instance_state` |
| Lambda function | `CreateFunction*`, `DeleteFunction*`, `UpdateFunctionConfiguration*`, `UpdateFunctionCode*`, `AddPermission*` (names carry API-version suffixes, so match by prefix) | `functionName` | `aws_lambda_function`, `aws_lambda_permission` |
| Route 53 record | `ChangeResourceRecordSets`, `CreateHostedZone`, `DeleteHostedZone` | `hostedZoneId` plus record names in `changeBatch` | `aws_route53_zone`, `aws_route53_record` |

**Actor classes** (checked in this order): `clickops-self` (the detector's own role) → `ci` (role ARN matches `clickops-ci` or a trusted role in config) → `aws-service` (`userIdentity.type` is `AWSService`, or `invokedBy` is set) → `console-human` (`sessionCredentialFromConsole` is `"true"`) → `cli-human` (everything else).

**Repo layout**

```
clickops/
├── clickops/             # Python package (CLI + Lambda share it)
│   ├── cli.py            # typer app: scan, import, events, status, doctor
│   ├── config.py         # clickops.yaml model
│   ├── events.py         # CloudTrail → NormalizedEvent
│   ├── actors.py         # actor classification
│   ├── state.py          # Terraform state reader + index
│   ├── resolvers/        # one module per resource type
│   ├── compare/          # live-vs-state comparators per type
│   ├── rules.py          # outcome + severity
│   ├── store.py          # DynamoDB event log
│   ├── alerts.py         # Slack + SNS
│   ├── scan.py           # shadow-resource discovery
│   ├── importer.py       # import blocks + generate-config-out
│   └── handler.py        # Lambda entry point
├── tests/
│   ├── fixtures/cloudtrail/   # one JSON event per watched call
│   └── ...
├── infra/
│   ├── bootstrap/        # state bucket, OIDC provider, CI role (local state)
│   ├── sandbox/          # the infrastructure that gets drifted
│   └── detector/         # CloudTrail, EventBridge, Lambda, DynamoDB, SNS
├── docs/                 # PLAN.md, architecture.md, cost.md, threat-model.md
├── .github/workflows/    # ci.yml, terraform.yml, release.yml
├── clickops.yaml
├── Makefile
├── PROGRESS.md
└── README.md
```

## Week 1 (Days 1–7): foundations and the sandbox to drift

By the end of week 1, a Terraform-managed sandbox exists in AWS, CI plans and applies it through OIDC, and every watched CloudTrail event has a test fixture.

### Day 1: repo scaffold

- Initialise the uv project and the `clickops/` package with empty modules matching the repo layout.
- Configure ruff and mypy (strict) in `pyproject.toml`. Add a `Makefile` with `fmt`, `lint`, `typecheck`, `test` and `check` (all three).
- Write `CLAUDE.md`: point to `docs/PLAN.md`, `PROGRESS.md` and the ground rules. Create an empty `PROGRESS.md`.
- `.gitignore` covers `*.tfstate*`, `.terraform/`, `*.auto.tfvars`, `.env`, `dist/`.
- `.github/workflows/ci.yml` runs `make check` on every PR and push to `main`.

**Done when:** `make check` passes locally with one placeholder test, and the first PR shows a green CI run.

### Day 2: core models, config and `doctor`

- In `clickops/models.py`, define pydantic models: `NormalizedEvent`, `Actor`, `ResourceRef` (type, id, arn, region), `Finding` (event, actor, resource, outcome, severity, diff).
- `config.py` loads and validates `clickops.yaml` (state locations, trusted role ARNs, ignore rules, severity overrides). Commit an example config with placeholders.
- CLI command `clickops doctor` checks: AWS credentials (`sts get-caller-identity`), Terraform version ≥ 1.10, config validity, and read access to each state file. Each check prints pass or fail with a fix hint.

**Done when:** unit tests cover valid and invalid configs, and `doctor` runs against moto with a clear report.

### Day 3: bootstrap infrastructure *(needs one approved apply)*

- `infra/bootstrap/` (local state, run once with the `clickops-admin` profile) creates:
  - the state bucket `clickops-tfstate-<account-id>`: versioning on, SSE-S3, Block Public Access, a bucket policy denying non-TLS requests;
  - the GitHub OIDC identity provider for `token.actions.githubusercontent.com`;
  - the role `clickops-ci`, trusted only for this repo's `main` branch and its pull requests, with a scoped policy for the sandbox and detector resource types (tightened again on Day 26).
- Account ID and GitHub owner come from `bootstrap.auto.tfvars` (gitignored).

**Done when:** after the approved apply, a throwaway workflow on a branch assumes `clickops-ci` and prints the caller identity.

### Day 4: the sandbox *(needs one approved apply)*

`infra/sandbox/` (S3 backend) holds the infrastructure that clickops will watch. Keep it cheap:

- a VPC with one public subnet and an internet gateway, **no NAT gateway**;
- security group `web` (443 from anywhere) and `admin` (22 from one placeholder /32), with rules as `aws_vpc_security_group_ingress_rule` resources;
- one `t4g.nano` instance held **stopped** with `aws_ec2_instance_state`, so only its small EBS volume costs money;
- one S3 bucket with versioning, encryption and Block Public Access;
- one IAM role with an inline policy and one managed-policy attachment;
- one Python "hello" Lambda function packaged with `archive_file`;
- one private Route 53 hosted zone attached to the VPC, with two A records.

Add `docs/cost.md` with the expected monthly cost of the sandbox (hosted zone and stopped EBS volume; everything else free tier or near zero).

**Done when:** after the approved apply, a second `terraform plan` shows no changes.

### Day 5: Terraform CI

- `.github/workflows/terraform.yml`:
  - on PR: `terraform fmt -check`, `validate`, `tflint`, and `plan` for `sandbox` and `detector` (the detector directory is still empty), posting the plan as a PR comment;
  - on push to `main`: `apply` for `sandbox` only (the detector gets automatic apply on Day 13).
- Use `aws-actions/configure-aws-credentials` with `role-to-assume` and `permissions: id-token: write`.

**Done when:** a PR that changes one sandbox tag shows a plan comment, and merging it applies the change.

### Day 6: CloudTrail fixture library

- Record real events: with the admin profile, run a short script (`scripts/make_fixture_events.sh`) that makes each watched write call once against sandbox resources. Fetch the events with `aws cloudtrail lookup-events`, which reads the free 90-day event history. Then run `terraform apply` in the sandbox to undo every change *(approval needed for both the script and the apply)*.
- Write synthetic fixtures for calls not safe to make for real (for example `DeleteHostedZone`), modelled on the real ones.
- Save each to `tests/fixtures/cloudtrail/<service>/<EventName>.json`, with a `_source: real|synthetic` field. Hand-write at least two `console-human` fixtures by setting `sessionCredentialFromConsole`, since the agent can't click the console.

**Done when:** every event in the resource coverage table has at least one fixture, and a test confirms each fixture parses as valid CloudTrail JSON.

### Day 7: buffer and week-1 review

- Finish anything left from Days 1–6.
- Write `docs/architecture.md` with a Mermaid diagram of the event flow and the three Terraform roots.
- Confirm the sandbox costs what `docs/cost.md` predicts, using `aws ce get-cost-and-usage` (each Cost Explorer API request costs USD 0.01; one call is enough).

**Done when:** PROGRESS.md has a week-1 summary and every Day 1–6 check passes.

## Week 2 (Days 8–14): the event pipeline

By the end of week 2, a real write call in the sandbox lands in DynamoDB as a stored event with its actor classified, within a few minutes.

### Day 8: event normalizer

- `events.py`: turn an EventBridge "AWS API Call via CloudTrail" event into a `NormalizedEvent`: event ID, time, source, name, region, account, user identity, request and response parameters, error code.
- Drop failed calls (`errorCode` present): a call that failed changed nothing.
- Handle Lambda's suffixed event names by normalising them to the base name (`UpdateFunctionConfiguration20150331v2` → `UpdateFunctionConfiguration`).

**Done when:** every fixture normalizes without error, and tests assert the fields for at least one fixture per service.

### Day 9: actor classifier

- `actors.py`: apply the actor classes in the fixed order from the spec. Produce a display name: the IAM user name, or for assumed roles the session name (for Identity Center roles named `AWSReservedSSO_*`, that is the person's login).
- Trusted roles come from `clickops.yaml`; the detector's own role ARN comes from an environment variable.
- Edge cases to test: an Identity Center user in the console, the same user on the CLI, `clickops-ci` from GitHub Actions, an AWS service-linked role, and CloudFormation acting on a person's behalf (`invokedBy`).

**Done when:** each fixture has an expected actor class in a parametrised test, and all pass.

### Day 10: detector storage and trail *(needs one approved apply)*

Create the `infra/detector/` root (S3 backend, separate state key) with:

- a multi-region CloudTrail trail for **write-only** management events (the first copy of management events has no CloudTrail charge), logging to a new bucket with a 30-day lifecycle rule and the standard CloudTrail bucket policy;
- the DynamoDB table `clickops-events`: on-demand, partition key `resource_key` (for example `sg#sg-0abc`), sort key `ts#event_id`, a GSI on `day` + `ts` for time-range queries, TTL attribute `expires_at` (90 days);
- an SNS topic `clickops-critical` with an email subscription to the address in `detector.auto.tfvars`.

**Done when:** after the approved apply, `terraform plan` is clean and the email subscription is confirmed (the human clicks the link).

### Day 11: Lambda skeleton and packaging *(needs one approved apply)*

- `handler.py`: normalize → classify → write a stored event with outcome `unresolved` (resolution arrives in week 3). Log one structured JSON line per event.
- `scripts/build_lambda.sh`: `uv export` the runtime dependencies, install them into `build/`, copy the package, zip it. Make it reproducible so an unchanged build gives an unchanged hash.
- Terraform: `aws_lambda_function` `clickops-detector` (Python 3.12, arm64, 256 MB, 30 s timeout), its log group (14-day retention), an SQS dead-letter queue, and an execution role with only CloudWatch Logs and DynamoDB `PutItem` for now.

**Done when:** invoking the deployed Lambda with a fixture (`aws lambda invoke`) creates the expected DynamoDB item.

### Day 12: EventBridge rules *(needs one approved apply)*

- In `ap-south-1`: a rule on the default bus matching `detail-type` "AWS API Call via CloudTrail", sources `aws.ec2`, `aws.s3`, `aws.lambda`, and the watched event names (use `prefix` matching for Lambda), targeting the detector with the DLQ attached.
- In `us-east-1` (second provider alias): a rule matching `aws.iam` and `aws.route53` with their watched event names, targeting the `ap-south-1` default event bus. It needs an IAM role that allows `events:PutEvents` on that bus.
- In `ap-south-1`: a second rule matching the forwarded IAM and Route 53 events, targeting the detector.
- Unit-test the event patterns with `aws events test-event-pattern` against the fixtures, in a script CI can run.

**Done when:** every fixture matches exactly the rule it should and none of the others.

### Day 13: end-to-end smoke test *(needs approval for the change and the revert)*

- Add `clickops events --since 1h` (reads the GSI, prints a rich table).
- Make one real change with the admin profile: add a rule allowing 8443 from `10.0.0.0/8` to the `web` group, then `aws iam put-role-policy` on the sandbox role. Wait for both events and record the delay in PROGRESS.md.
- Revert with `terraform apply` in the sandbox, and confirm those revert events are stored as `ci` or `cli-human` correctly (local applies run as the admin profile, so `cli-human` is correct here).
- Enable apply on `main` for `infra/detector` in `terraform.yml`.

**Done when:** both changes appear in `clickops events` with the right actor, and the measured delay is written down.

### Day 14: buffer, alarms and week-2 review

- CloudWatch alarms to `clickops-critical`: detector `Errors` > 0 over 5 minutes, and DLQ `ApproximateNumberOfMessagesVisible` > 0.
- Finish anything left from Days 8–13.

**Done when:** a forced Lambda error (invoke with a malformed event) triggers the alarm email, and PROGRESS.md has a week-2 summary.

## Week 3 (Days 15–21): matching events to Terraform, and alerting

By the end of week 3, opening SSH to the world from the CLI sends a critical Slack alert naming the person and showing the diff against Terraform state.

### Day 15: Terraform state reader

- `state.py`: read each state file listed in `clickops.yaml` from S3, check it is format version 4, and build an index keyed by Terraform type + primary ID and by ARN.
- Map child resources to their parent: security group rules → their group, `aws_s3_bucket_*` config resources → their bucket, role policies and attachments → their role.
- Cache the index in the Lambda's global scope; refresh only when the object's ETag changes (one `HeadObject` per invocation).
- State files can contain secrets: never log attribute values, only addresses and IDs.
- Grant the detector role `s3:GetObject` on the two state keys only (it covers both GET and HEAD requests).

**Done when:** tests build the index from a captured copy of the real sandbox state (with secrets scrubbed) and look up every sandbox resource by ID and by ARN.

### Day 16: resolvers for security groups and IAM

- `resolvers/sg.py` and `resolvers/iam.py`: turn a `NormalizedEvent` into one or more `ResourceRef`s, using the ID locations in the coverage table. `ModifySecurityGroupRules` and rule-level calls resolve to the parent group.
- A shared interface: `resolve(event) -> list[ResourceRef]`, registered by event source in `resolvers/__init__.py`.

**Done when:** every SG and IAM fixture resolves to the expected refs, and each resolved ref is found (or correctly not found) in the state index.

### Day 17: resolvers for S3, EC2, Lambda and Route 53

- `RunInstances` and `TerminateInstances` can carry several instances: one ref each.
- `ChangeResourceRecordSets` can change several records: one ref per name and type in the `changeBatch`.
- An unknown or unwatched event name returns an empty list and is logged once at debug level, not raised.

**Done when:** all fixtures resolve, and the resolver test suite covers all six resource types.

### Day 18: live-versus-state comparators

`compare/<type>.py` fetches the live configuration with read-only calls and compares a fixed attribute set against state, returning a field-level diff:

| Resource | Attributes compared |
| --- | --- |
| Security group | ingress and egress rules (protocol, ports, CIDR or referenced group) |
| IAM role | trust policy, inline policies, attached policy ARNs |
| S3 bucket | bucket policy, the four Block Public Access flags, versioning status, encryption algorithm |
| EC2 instance | instance type, security group IDs, instance profile, running or stopped |
| Lambda function | runtime, handler, memory, timeout, role, code SHA-256, environment variable **names only** |
| Route 53 record | name, type, TTL, values |

- Normalize IAM and bucket policy JSON before comparing (sort keys, treat a single string and a one-item list as equal).
- A resource that no longer exists produces `managed-delete` without a describe call.
- Add the needed read-only actions to the detector role, each listed explicitly (no `*`).

**Done when:** moto-backed tests produce the expected diff for one change of each attribute listed above.

### Day 19: outcomes, severity and the full pipeline

- `rules.py`: decide the outcome and severity from the spec tables, then apply the critical overrides, the `clickops:ignore=true` tag and config severity overrides.
- Wire `handler.py` end to end: normalize → classify → resolve → state lookup → compare → rules → store.
- Golden tests: replay every fixture through the full pipeline against moto and compare the stored `Finding` with a checked-in expected JSON.

**Done when:** all golden tests pass, and a malformed event or an AWS throttling error is retried by Lambda and then lands in the DLQ rather than crashing silently.

### Day 20: Slack and email alerts *(the human stores the webhook once)*

- Print the one command for the human to run: `aws ssm put-parameter --name /clickops/slack-webhook --type SecureString --value '<paste URL>'`. The agent never sees or handles the URL.
- `alerts.py`: Slack Block Kit message with severity, outcome, resource, actor and source (console or CLI), the diff as a short code block, and the exact `terraform apply -target=...` command that would restore the coded state.
- Critical findings also publish to `clickops-critical` (email).
- Deduplicate: repeat findings for the same resource and actor within 10 minutes update a counter instead of sending a new message.
- Grant the detector `ssm:GetParameter` on that one parameter and `kms:Decrypt` for the AWS-managed SSM key.

**Done when:** tests check the rendered Slack payload for each outcome, and a fixture invocation of the deployed Lambda posts a real message to `#clickops-alerts`.

### Day 21: real end-to-end and week-3 review *(needs approval for the change and the revert)*

- With the admin profile, allow port 22 from `0.0.0.0/0` on the `admin` group. Expect: a critical Slack alert and an email.
- Attach `AmazonS3FullAccess` to the sandbox role. Expect: a warning alert with the diff.
- Revert both with `terraform apply` in the sandbox.

**Done when:** both alerts arrive with correct content, the measured delays are in PROGRESS.md, and the week-3 summary is written.

## Week 4 (Days 22–30): scan, import, hardening and release

By Day 30, clickops v0.1.0 is tagged on GitHub with a working `scan` and `import`, tamper alerts, least-privilege roles, a scripted end-to-end test and a README with a demo GIF.

### Day 22: `clickops scan`

- `scan.py` lists live resources of the six types with read-only calls and reports those found in no configured state file.
- Exclude what isn't really shadow: the default VPC security group, terminated instances, service-linked roles (path `/aws-service-role/`), `AWSReservedSSO_*` roles, AWS-managed policies, buckets in other regions, and NS and SOA records.
- Output a rich table (type, ID, name, created date where available, creator if found in the event store) or `--json`.

**Done when:** moto tests cover each exclusion, and a real `scan` of the sandbox account lists nothing except what is genuinely unmanaged (record the list in PROGRESS.md).

### Day 23: `clickops import` *(needs approval to create and later delete one test bucket)*

- `importer.py` writes `imports/<timestamp>/imports.tf` with one `import` block per shadow resource, using each provider type's import ID format (for example `role:policy` for `aws_iam_role_policy`, `ZONEID_name_TYPE` for `aws_route53_record`, the `sgr-` ID for rule resources).
- Then, in a temporary working directory with the same provider settings, run `terraform init` and `terraform plan -generate-config-out=generated.tf`, followed by `terraform validate`.
- Generated config is a starting point: when `validate` fails, keep the file, add a comment at the top listing the errors, and print them.
- Test on a real shadow resource: create one S3 bucket by CLI, import it, check the plan shows only the import, then delete the bucket.

**Done when:** the import of the test bucket produces config that validates and a plan with "1 to import, 0 to add, 0 to change, 0 to destroy".

### Day 24: least privilege for both roles *(needs one approved apply)*

- Rewrite the `clickops-ci` and detector policies as resource-scoped statements (ARNs with the `clickops`/sandbox names or tag conditions), removing every wildcard that isn't required.
- In CI, extract every IAM policy from `terraform show -json` and run `aws accessanalyzer validate-policy` on it; fail the job on any `ERROR` or `SECURITY_WARNING` finding.
- Write `docs/threat-model.md`: what each role can do, what an attacker with the detector's role could do (read config, write events, send alerts), and what clickops does not protect against.

**Done when:** Access Analyzer reports no errors or security warnings, and the Day 21 scenarios still alert correctly after the apply.

### Day 25: tamper alerts and `clickops status`

- Watch clickops' own resources: `StopLogging`, `DeleteTrail`, `UpdateTrail`, `PutEventSelectors` on its trail; `DisableRule`, `DeleteRule`, `RemoveTargets` on its rules; `DeleteFunction` and `UpdateFunctionCode` on the detector. Any of these by anyone other than `clickops-ci` is a critical `tamper` outcome.
- Add `tamper` to the outcomes table in `rules.py` and to the README.
- `clickops status` shows: trail logging on or off, each rule enabled, time of the last stored event, DLQ depth, and open alarms.

**Done when:** fixtures for each tamper event produce a critical finding, and `status` passes against the real account.

### Day 26: scripted end-to-end test *(needs approval to run)*

`scripts/e2e.sh` runs six scenarios with the admin profile, polls DynamoDB for up to 10 minutes per scenario, asserts outcome and severity, then reverts:

1. SSH from `0.0.0.0/0` on `admin` → critical `managed-drift`
2. Managed policy attached to the sandbox role → warning `managed-drift`
3. Block Public Access turned off on the sandbox bucket → critical `managed-drift`
4. Lambda timeout changed → warning `managed-drift`
5. Route 53 record value changed → warning `managed-drift`
6. New bucket created by CLI → info `shadow-create`, then deleted

The revert step is one `terraform apply` in the sandbox plus deleting the scenario 6 bucket.

**Done when:** all six pass in one run, and the results with measured delays are saved to `docs/e2e-results.md`.

### Day 27: packaging and release pipeline

- Console entry point `clickops` in `pyproject.toml`; installable with `pipx install git+https://github.com/<owner>/clickops`.
- `.github/workflows/release.yml`: on a `v*` tag, run `make check`, build the wheel and the Lambda zip, and attach both to a GitHub release with notes from `CHANGELOG.md`.
- Write `CHANGELOG.md` for 0.1.0.

**Done when:** a pre-release tag `v0.1.0-rc1` produces a release with both files, and a fresh `pipx install` from it runs `clickops doctor`.

### Day 28: README and demo

- README sections, in order: the problem in three sentences; the demo GIF; what it detects (the coverage table); architecture (Mermaid); quickstart in five steps; cost (from `docs/cost.md`); security model (link to the threat model); limitations; how it differs from running `terraform plan` on a schedule.
- Limitations to state plainly: six resource types, one account, resources in one region (plus global IAM and Route 53), alert delay of a few minutes, no automatic revert.
- Record the demo with a VHS tape file (`demo/demo.tape`): `clickops scan`, then `clickops import` on the Day 23-style test bucket, then `clickops events`. Re-runnable, so the GIF can be regenerated.
- Optional, by the human (two minutes): make one change in the AWS console and screenshot the resulting Slack alert for the README, since the agent can't click the console.

**Done when:** a reviewer can follow the quickstart from a fresh clone using only the README.

### Day 29: fresh-clone verification and teardown docs

- In a new directory, clone the repo and follow the README quickstart up to `terraform plan` for every root (plan only, no apply). Fix every doc or script gap found.
- Add `make destroy` with the safe order (sandbox → detector → bootstrap, with a confirmation prompt) and document it. Don't run it unless the human asks.
- Re-check monthly cost with one Cost Explorer call and update `docs/cost.md` with the real figure.

**Done when:** the fresh-clone run needs no steps that aren't in the README.

### Day 30: buffer and v0.1.0

- Finish anything left over. Run `make check`, the Terraform CI and `scripts/e2e.sh` one last time.
- Tag `v0.1.0`.
- Close PROGRESS.md with a final summary and a short *v0.2 ideas* list (more resource types, multi-account via AWS Organizations, auto-revert behind an approval button).

## Definition of done for v0.1.0

- [ ] `make check`, Terraform CI and `scripts/e2e.sh` all pass on `main`
- [ ] All six resource types alert correctly, with the right actor and severity
- [ ] `scan` and `import` work on the real sandbox account
- [ ] Tamper alerts fire for changes to clickops' own trail, rules and Lambda
- [ ] No stored credentials anywhere: CI uses OIDC, the webhook lives in SSM
- [ ] IAM Access Analyzer shows no errors or security warnings on either role
- [ ] Monthly cost confirmed in `docs/cost.md`
- [ ] README quickstart verified from a fresh clone, demo GIF included
- [ ] `v0.1.0` tagged with release assets
- [ ] PROGRESS.md closed with a final summary and v0.2 ideas
