# detector

The clickops detector's infrastructure. Applied in stages as the detector is built:

- a multi-region CloudTrail trail for write-only management events, logging to
  `clickops-trail-<account-id>` (30-day lifecycle, CloudTrail bucket policy, TLS only);
- the DynamoDB table `clickops-events` (on-demand, partition key `resource_key`, sort key `sk` =
  `ts#event_id`, GSI `day-ts` for time-range queries, TTL attribute `expires_at`);
- the SNS topic `clickops-critical` with an email subscription;
- later: the Lambda, its DLQ, EventBridge rules and alarms.

```
cp backend.hcl.example backend.hcl                         # gitignored
cp detector.auto.tfvars.example detector.auto.tfvars       # gitignored
terraform init -backend-config=backend.hcl
terraform plan
terraform apply                                            # review the plan first
```

Then click the link in the SNS confirmation email. `terraform plan` should be clean afterwards.
