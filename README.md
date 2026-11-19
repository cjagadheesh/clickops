# clickops

Alerts on Slack when someone changes Terraform-managed AWS infrastructure outside Terraform.
Under construction; see `claude/plan1.md` for the build plan.

## Outcomes

Every watched change is stored with one of these outcomes and a severity. Only the rows with a
severity above "none" are alerted.

| Outcome | Meaning | Default severity |
| --- | --- | --- |
| `managed-drift` | a person changed a resource that is in Terraform state | warning |
| `managed-delete` | a person deleted a resource that is in Terraform state | critical |
| `shadow-create` | a person created a resource that no state knows about | info |
| `tamper` | anyone other than `clickops-ci` stopped or changed clickops' own trail, event rules or detector function (`StopLogging`, `DeleteTrail`, `UpdateTrail`, `PutEventSelectors`, `DisableRule`, `DeleteRule`, `RemoveTargets`, `DeleteFunction`, `UpdateFunctionCode`) | critical |
| `ignored` | the actor is CI, clickops itself or an AWS service; the resource is opted out (`clickops:ignore=true` or an ignore rule); it is not managed by Terraform; or the live configuration matches state | none |

Any outcome except `ignored` becomes **critical** when the change allows ingress from `0.0.0.0/0`
or `::/0` on a port other than 80 or 443, grants an IAM policy with `*` as the action or resource
together with a write action, or disables S3 Block Public Access. A `tamper` outcome cannot be
silenced by tags, ignore rules or severity overrides.

## Commands

| Command | What it does |
| --- | --- |
| `clickops doctor` | checks credentials, Terraform, the config and read access to the state files |
| `clickops events --since 1h` | shows stored events, oldest first |
| `clickops scan` | lists live resources of the six types that are in no Terraform state |
| `clickops import` | writes Terraform `import` blocks for shadow resources and drafts their config |
| `clickops status` | checks that the trail is logging, the rules are enabled, the dead-letter queue is empty and no alarm is open |
