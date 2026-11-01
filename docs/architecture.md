# Architecture

clickops watches one AWS account in `ap-south-1`. A write call recorded by CloudTrail travels through
EventBridge to one Lambda, which decides whether the change was made outside Terraform and, if so,
stores it and alerts Slack.

## Event flow

```mermaid
flowchart LR
    person([Person: console or CLI]) --> api[AWS API call]
    api --> trail[CloudTrail<br/>write-only management events]
    trail --> eb[EventBridge default bus<br/>ap-south-1]
    api -. IAM and Route 53<br/>arrive in us-east-1 .-> fwd[Forwarding rule<br/>us-east-1]
    fwd --> eb
    eb -->|rule matches watched events| lambda[clickops-detector Lambda]
    eb -. failed delivery .-> dlq[(SQS DLQ)]
    lambda --> norm[events.py<br/>normalize]
    norm --> actor[actors.py<br/>classify actor]
    actor --> res[resolvers/<br/>event to ResourceRefs]
    res --> state[state.py<br/>Terraform state index from S3]
    state --> cmp[compare/<br/>live config vs state]
    cmp --> rules[rules.py<br/>outcome and severity]
    rules --> ddb[(DynamoDB<br/>clickops-events)]
    rules --> slack[Slack webhook<br/>from SSM]
    rules -->|critical| sns[SNS clickops-critical<br/>email]
```

Everything left of the Lambda is AWS doing its normal job; everything right of it is output.

## Outcomes

| Outcome | Meaning | Default severity |
| --- | --- | --- |
| `managed-drift` | a person changed a resource that is in Terraform state | warning |
| `managed-delete` | a person deleted a resource that is in Terraform state | critical |
| `shadow-create` | a person created a resource that no state knows about | info |
| `ignored` | actor is CI, clickops itself or an AWS service, or the resource is opted out | none |

## Terraform roots

```mermaid
flowchart TB
    subgraph local[Local state]
        bootstrap[infra/bootstrap<br/>state bucket, OIDC provider, clickops-ci role]
    end
    subgraph s3[S3 backend: clickops-tfstate-account-id]
        sandbox[infra/sandbox<br/>VPC, security groups, stopped instance,<br/>bucket, role, Lambda, private zone]
        detector[infra/detector<br/>trail, rules, Lambda, DynamoDB, SNS]
    end
    bootstrap -->|creates| s3
    bootstrap -->|creates| ci[clickops-ci role]
    gha[GitHub Actions] -->|OIDC| ci
    ci -->|plan on PR, apply sandbox on main| sandbox
    ci -.->|from Day 13| detector
    sandbox -->|state read by| lambda2[clickops-detector]
    detector -->|state read by| lambda2
```

- `bootstrap` is applied once by hand with the `clickops-admin` profile; its local state stays on that machine.
- `sandbox` is the infrastructure that gets drifted on purpose, so clickops has something to watch.
- `detector` is clickops itself. The detector Lambda reads the sandbox and detector state files with `s3:GetObject` on those two keys only.

## Actor classes

Checked in this order: `clickops-self`, `ci`, `aws-service`, `console-human`, `cli-human`.

## Package layout

One Python package, `clickops`, serves the CLI (`typer`, `rich`) and the Lambda (`handler.py`). Models and
config use pydantic v2. Tests use moto and the CloudTrail fixtures in `tests/fixtures/cloudtrail/`.
