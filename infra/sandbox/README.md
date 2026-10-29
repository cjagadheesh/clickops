# sandbox

The infrastructure clickops watches and that gets drifted on purpose: a VPC with a public subnet and
internet gateway (no NAT), security groups `web` and `admin`, a stopped `t4g.nano`, one bucket, one
role, one Lambda and a private Route 53 zone with two A records.

```
cp backend.hcl.example backend.hcl                # gitignored; use the bootstrap state bucket
echo 'admin_cidr = "<your-ip>/32"' > sandbox.auto.tfvars   # gitignored
terraform init -backend-config=backend.hcl
terraform plan
terraform apply                                   # review the plan first
terraform plan                                    # must show no changes
```
