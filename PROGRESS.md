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
