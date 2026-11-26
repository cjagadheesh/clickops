#!/usr/bin/env bash
# Tear clickops down in the safe order: sandbox -> detector -> bootstrap.
#
# The order matters. The sandbox and detector keep their Terraform state in the bucket that the
# bootstrap root owns, and the detector watches the sandbox, so the state bucket and the CI role go
# last. None of the clickops buckets set force_destroy, so each one is emptied (all versions)
# right before its own destroy. Terraform still asks you to approve each destroy.
#
# What it does NOT remove: anything you created outside Terraform (an AWS Budget, the
# clickops-admin profile) and the GitHub repository variables.
#
#   make destroy                       # prompts; you type "destroy <account-id>"
#   DRY_RUN=1 scripts/destroy.sh       # prints the plan and changes nothing
#
# Environment: AWS_PROFILE (default clickops-admin), TF_DESTROY_ARGS (e.g. -auto-approve).
set -euo pipefail

cd "$(dirname "$0")/.."
export AWS_PROFILE=${AWS_PROFILE:-clickops-admin}
REGION=ap-south-1
SLACK_PARAM=${CLICKOPS_SLACK_PARAM:-/clickops/slack-webhook}
# shellcheck disable=SC2206
DESTROY_ARGS=(${TF_DESTROY_ARGS:-})

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)

cat <<PLAN
This will destroy clickops in AWS account $ACCOUNT ($REGION), in this order:

  1. infra/sandbox   VPC, security groups, instance, bucket clickops-sandbox-$ACCOUNT (emptied
                     first), role, Lambda, private Route 53 zone
  2. infra/detector  trail and bucket clickops-trail-$ACCOUNT (emptied first), events table
                     (stored findings are lost), SNS topic, Lambda, rules, alarms; then the SSM
                     parameter $SLACK_PARAM
  3. infra/bootstrap state bucket clickops-tfstate-$ACCOUNT (emptied first, all state history is
                     lost), GitHub OIDC provider, clickops-ci role

Not removed: resources made outside Terraform (such as an AWS Budget) and GitHub repository variables.
PLAN

if [ "${DRY_RUN:-}" = "1" ]; then
  echo "DRY_RUN=1: nothing was changed."
  exit 0
fi

for f in infra/sandbox/backend.hcl infra/detector/backend.hcl infra/detector/detector.auto.tfvars \
         infra/bootstrap/bootstrap.auto.tfvars; do
  if [ ! -f "$f" ]; then
    echo "Missing $f. Terraform needs the same local files you applied with (see the README quickstart)." >&2
    exit 1
  fi
done

printf 'Type "destroy %s" to continue: ' "$ACCOUNT"
read -r answer
if [ "$answer" != "destroy $ACCOUNT" ]; then
  echo "Aborted: nothing was changed." >&2
  exit 1
fi

tf() { terraform -chdir="$1" "${@:2}"; }

echo "== 1/3 sandbox"
tf infra/sandbox init -input=false -backend-config=backend.hcl
uv run --quiet python scripts/empty_bucket.py "clickops-sandbox-$ACCOUNT"
tf infra/sandbox destroy ${DESTROY_ARGS[@]+"${DESTROY_ARGS[@]}"}

echo "== 2/3 detector"
# Terraform reads the Lambda zip while planning a destroy, so it must exist.
[ -f dist/clickops-detector.zip ] || scripts/build_lambda.sh
tf infra/detector init -input=false -backend-config=backend.hcl
uv run --quiet python scripts/empty_bucket.py "clickops-trail-$ACCOUNT"
tf infra/detector destroy ${DESTROY_ARGS[@]+"${DESTROY_ARGS[@]}"}
aws ssm delete-parameter --name "$SLACK_PARAM" --region "$REGION" 2>/dev/null \
  || echo "SSM parameter $SLACK_PARAM was already gone."

echo "== 3/3 bootstrap"
tf infra/bootstrap init -input=false
uv run --quiet python scripts/empty_bucket.py "clickops-tfstate-$ACCOUNT"
tf infra/bootstrap destroy ${DESTROY_ARGS[@]+"${DESTROY_ARGS[@]}"}

echo "clickops is removed. Delete any AWS Budget and the CLICKOPS_* repository variables by hand."
