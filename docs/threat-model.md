# Threat model

clickops watches one AWS account and tells a person when Terraform-managed infrastructure is
changed outside Terraform. This page lists what each identity can do, what an attacker holding one
of them could do, and what clickops does not protect against. The policies themselves are in
`infra/bootstrap/policies/` (the CI role) and `infra/detector/lambda_role.tf` (the detector).

## Identities

| Identity | Used by | Created in |
| --- | --- | --- |
| `clickops-admin` | the owner, for bootstrap and approved applies only | outside this repo |
| `clickops-ci` | GitHub Actions, through OIDC | `infra/bootstrap` |
| `clickops-detector` | the detector Lambda | `infra/detector` |
| `clickops-event-forwarder` | EventBridge, to forward IAM and Route 53 events from `us-east-1` | `infra/detector` |
| `clickops-sandbox-app` | the sandbox Lambda (the thing that gets drifted) | `infra/sandbox` |

## `clickops-ci`

Trust: only this repository's `main` branch and its pull requests, through the GitHub OIDC
provider, with audience `sts.amazonaws.com`. No access keys exist.

It can plan and apply the `sandbox` and `detector` roots, so it can:

- read and write Terraform state objects under `sandbox/` and `detector/` in the state bucket;
- create, change and delete the named clickops resources: the sandbox and trail buckets, the
  `clickops-events` table, the `clickops-critical` topic, the dead-letter queue, the
  `clickops-*` event rules, the trail, the log groups and alarms, the two Lambda functions, and
  the three clickops roles (by exact name);
- create EC2 networking, security groups and instances, and Route 53 zones, limited to this account
  and `ap-south-1`. AWS cannot scope these by name before they exist, so the limit is the account
  and region, not individual resources.

It cannot: create IAM users, other roles or policies; attach any managed policy except
`AWSLambdaBasicExecutionRole`; pass roles to services other than Lambda and EventBridge; touch
other buckets, tables or functions; use any service outside the list above. There are no wildcard
actions. `Resource: *` appears only on read-only list and describe calls and on the create-only
calls AWS cannot scope (`CreateHostedZone`, the Route 53 lookups, `GetChange`, `kms:ListAliases`,
`access-analyzer:ValidatePolicy`).

If an attacker could merge to `main` (or open a pull request, for plans), they could change
infrastructure inside that list, including the detector's own code and permissions: the CI role is
trusted by design, and clickops ignores `ci` actors. Branch protection and review on `main` are the
control for this, not clickops.

## `clickops-detector`

It can:

- read the two Terraform state objects (`sandbox/terraform.tfstate`, `detector/terraform.tfstate`);
- make a fixed list of read-only describe and get calls for the six resource types;
- `PutItem`, `GetItem` and `UpdateItem` on the `clickops-events` table;
- read the one SSM parameter holding the Slack webhook and decrypt it with the AWS-managed SSM key;
- publish to the `clickops-critical` topic;
- write its own logs and send to its dead-letter queue.

An attacker with this role could:

- **read the Terraform state**, which can contain secrets such as passwords and keys for resources
  Terraform manages (the sandbox has none today). This is the most sensitive thing the detector can
  reach. Keep secrets out of state or out of these two roots;
- **read the Slack webhook** and post arbitrary messages to the alerts channel, or email the
  critical topic's subscriber;
- **write or overwrite events**, hiding a finding or inventing one (the table is not append-only);
- read configuration of the six resource types, which reveals the account's layout.

They could not change infrastructure, read other secrets, or reach any other table, bucket or key.

## `clickops-event-forwarder`

It can only `events:PutEvents` on the `ap-south-1` default bus. An attacker with it could inject
forged CloudTrail-shaped events into that bus, which the detector would store and alert on; they
could not read anything.

## What clickops does not protect against

- **Anything outside the six resource types**, other regions and other accounts. A change to an
  RDS database or an IAM user is invisible.
- **Delay.** CloudTrail delivers events in minutes; a fast change and revert can finish before an
  alert and leave no drift to compare (the event is still stored).
- **Watching the watchers.** Two rules (`clickops-regional` and `clickops-tamper`) report calls on
  each other, but nothing reports a change to the `us-east-1` forwarder, and an attacker who
  disables every watcher in one step goes unreported. `clickops status` shows the state of all four
  rules; run it after each apply and on a schedule.
- **A person with `clickops-admin`** or an administrator in the account. They can stop the trail,
  disable the rules or change the Lambda. Tamper alerts (see `README.md`) report those changes
  unless the attacker also silences the alert path, and do not stop them.
- **Misclassified actors.** Actor classes come from the CloudTrail identity. A person who assumes
  a role named `clickops-ci` or a role listed in `trusted_roles` is treated as CI and ignored.
- **Failed calls.** A call that failed (`errorCode`) changed nothing, so it is dropped; attempted
  attacks that were denied are not reported.
- **Read access.** Reads are not watched; exfiltration through read calls is out of scope.
- **Tampered state.** The comparison trusts the Terraform state files. Someone who can write the
  state bucket can make drift look like intent.
- **Opt-outs.** A resource tagged `clickops:ignore=true`, and anything matching an ignore rule in
  `clickops.yaml`, never alerts. Anyone who can tag a resource can silence it.
- **Alert delivery.** If Slack and email are both down or unconfigured, findings are still stored,
  but nobody is told; the alarms on Lambda errors and the dead-letter queue are the backstop.
- **Automatic repair.** clickops never reverts a change; the alert only prints the
  `terraform apply -target=...` command to restore the coded state.

## Checks

- CI validates every IAM policy in the `sandbox` and `detector` plans, and the `clickops-ci`
  policy templates, with IAM Access Analyzer, and fails on any `ERROR` or `SECURITY_WARNING`
  finding (`scripts/validate_policies.py`).
- Tests assert there are no wildcard actions in the CI policies, that `Resource: *` is limited to
  the calls listed above, that role actions name the three clickops roles, and that policy
  attachment and `PassRole` stay conditioned.
