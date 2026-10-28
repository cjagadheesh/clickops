# bootstrap

Creates the Terraform state bucket (`clickops-tfstate-<account-id>`), the GitHub OIDC provider and
the `clickops-ci` role. It uses local state and is applied once with the `clickops-admin` profile.

```
cp bootstrap.auto.tfvars.example bootstrap.auto.tfvars   # gitignored; fill in account and owner
AWS_PROFILE=clickops-admin terraform init
AWS_PROFILE=clickops-admin terraform plan
AWS_PROFILE=clickops-admin terraform apply               # review the plan first
```

Then set the repository variable `CLICKOPS_CI_ROLE_ARN` to the `ci_role_arn` output and run the
`oidc-check` workflow from the Actions tab. It should print the `clickops-ci` assumed-role identity.

The local `terraform.tfstate` is gitignored. Keep it: it is the only record of this root.
