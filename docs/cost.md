# Expected monthly cost

Estimates for `ap-south-1`, USD, rounded up. Check against Cost Explorer once the sandbox has run a month.

## Sandbox

| Item | Cost |
| --- | --- |
| Route 53 private hosted zone | 0.50 |
| 8 GB gp3 EBS volume (instance held stopped) | about 0.75 |
| `t4g.nano` instance | 0 while stopped |
| VPC, subnet, internet gateway, security groups | 0 |
| S3 bucket (a few KB) | under 0.01 |
| Lambda function (no invocations) | 0 |
| IAM role and policies | 0 |

Sandbox total: about USD 1.25 per month. There is no NAT gateway, load balancer or RDS.

## Detector (added from Day 10)

CloudTrail's first copy of management events is free. DynamoDB on-demand, Lambda, SNS and EventBridge stay
inside the free tier or cost cents at this volume. Estimate to be confirmed after Day 13.

## Guardrail

A USD 5 monthly AWS Budget emails at 50% and 100%.
