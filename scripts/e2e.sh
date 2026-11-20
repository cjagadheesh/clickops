#!/usr/bin/env bash
# Live end-to-end test: six real changes to the sandbox, each checked in the events table.
#
#   1. SSH from 0.0.0.0/0 on the admin group           -> critical managed-drift
#   2. AmazonS3FullAccess attached to the sandbox role -> warning  managed-drift
#   3. Block Public Access off on the sandbox bucket   -> critical managed-drift
#   4. Lambda timeout changed                          -> warning  managed-drift
#   5. Route 53 record value changed                   -> warning  managed-drift
#   6. New bucket created by the CLI                   -> info     shadow-create
#
# Each scenario waits up to 10 minutes for the detector's finding, asserts its outcome and
# severity and records the delay. Then everything is reverted: scenarios 1 and 2 with the inverse
# CLI calls (Terraform does not remove an extra rule or policy attachment it does not manage),
# scenarios 3 to 5 with `terraform apply` in infra/sandbox (it asks you to approve), and the
# scenario 6 bucket is deleted. Finally `terraform plan` must show no changes. Results are written
# to docs/e2e-results.md.
#
# Needs approval: it changes real resources and sends real alerts.
#
#   CONFIRM=yes AWS_PROFILE=clickops-admin scripts/e2e.sh
#   (set TF_APPLY_ARGS=-auto-approve to skip the apply prompt)
set -uo pipefail

if [ "${CONFIRM:-}" != "yes" ]; then
  echo "This changes real AWS resources and sends alerts. Re-run with CONFIRM=yes after approval." >&2
  exit 1
fi

cd "$(dirname "$0")/.."
REGION=ap-south-1
TIMEOUT=${E2E_TIMEOUT:-600}
RESULTS=$(mktemp)
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
ROLE=clickops-sandbox-app
POLICY=arn:aws:iam::aws:policy/AmazonS3FullAccess
FUNCTION=clickops-sandbox-hello
SANDBOX_BUCKET=clickops-sandbox-$ACCOUNT
NEW_BUCKET=clickops-e2e-$ACCOUNT-$(date +%s)
RECORD=app.clickops.internal

VPC=$(aws ec2 describe-vpcs --region $REGION --filters Name=tag:Name,Values=clickops-sandbox \
  --query 'Vpcs[0].VpcId' --output text)
ADMIN_SG=$(aws ec2 describe-security-groups --region $REGION \
  --filters Name=group-name,Values=admin Name=vpc-id,Values="$VPC" \
  --query 'SecurityGroups[0].GroupId' --output text)
ZONE=$(aws route53 list-hosted-zones-by-name --dns-name clickops.internal \
  --query 'HostedZones[0].Id' --output text | sed 's#/hostedzone/##')

now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
failures=0

check() { # label resource event outcome severity since
  uv run python scripts/wait_for_finding.py --label "$1" --resource "$2" --event "$3" \
    --since "$6" --timeout "$TIMEOUT" --expect-outcome "$4" --expect-severity "$5" \
    --append "$RESULTS" || failures=$((failures + 1))
}

reverted=0
revert() {
  [ "$reverted" = 1 ] && return
  reverted=1
  echo "== reverting"
  aws ec2 revoke-security-group-ingress --region $REGION --group-id "$ADMIN_SG" \
    --protocol tcp --port 22 --cidr 0.0.0.0/0 > /dev/null 2>&1 || true
  aws iam detach-role-policy --role-name $ROLE --policy-arn $POLICY > /dev/null 2>&1 || true
  aws s3api delete-bucket --bucket "$NEW_BUCKET" --region $REGION > /dev/null 2>&1 || true
  local ok=true
  # shellcheck disable=SC2086
  terraform -chdir=infra/sandbox apply ${TF_APPLY_ARGS:-} || ok=false
  if terraform -chdir=infra/sandbox plan -detailed-exitcode -input=false > /dev/null; then
    echo "terraform plan: no changes, the sandbox is back to its coded state"
  else
    echo "FAIL: terraform plan still shows changes after the revert" >&2
    ok=false
  fi
  printf '{"kind": "revert", "ok": %s}\n' "$ok" >> "$RESULTS"
  [ "$ok" = true ] || failures=$((failures + 1))
}
# An interrupted run must not leave the sandbox changed.
trap 'revert' EXIT

echo "== 1. SSH from the world on admin ($ADMIN_SG)"
S=$(now)
aws ec2 authorize-security-group-ingress --region $REGION --group-id "$ADMIN_SG" \
  --protocol tcp --port 22 --cidr 0.0.0.0/0 > /dev/null
check "SSH from 0.0.0.0/0 on the admin group" "sg#$ADMIN_SG" AuthorizeSecurityGroupIngress \
  managed-drift critical "$S"

echo "== 2. AmazonS3FullAccess on the sandbox role"
S=$(now)
aws iam attach-role-policy --role-name $ROLE --policy-arn $POLICY
check "AmazonS3FullAccess attached to the sandbox role" "iam-role#$ROLE" AttachRolePolicy \
  managed-drift warning "$S"

echo "== 3. Block Public Access off on the sandbox bucket"
S=$(now)
aws s3api put-public-access-block --bucket "$SANDBOX_BUCKET" --public-access-block-configuration \
  BlockPublicAcls=false,IgnorePublicAcls=false,BlockPublicPolicy=false,RestrictPublicBuckets=false
check "Block Public Access disabled on the sandbox bucket" "s3#$SANDBOX_BUCKET" \
  PutBucketPublicAccessBlock managed-drift critical "$S"

echo "== 4. Lambda timeout changed"
S=$(now)
aws lambda update-function-configuration --region $REGION --function-name $FUNCTION \
  --timeout 25 > /dev/null
check "Lambda timeout changed" "lambda#$FUNCTION" UpdateFunctionConfiguration \
  managed-drift warning "$S"

echo "== 5. Route 53 record value changed"
S=$(now)
aws route53 change-resource-record-sets --hosted-zone-id "$ZONE" --change-batch \
  "{\"Changes\":[{\"Action\":\"UPSERT\",\"ResourceRecordSet\":{\"Name\":\"$RECORD\",\"Type\":\"A\",\"TTL\":300,\"ResourceRecords\":[{\"Value\":\"10.20.1.99\"}]}}]}" > /dev/null
check "Route 53 record value changed" "route53-record#${ZONE}_${RECORD}_A" \
  ChangeResourceRecordSets managed-drift warning "$S"

echo "== 6. New bucket created by the CLI ($NEW_BUCKET)"
S=$(now)
aws s3api create-bucket --bucket "$NEW_BUCKET" --region $REGION \
  --create-bucket-configuration LocationConstraint=$REGION > /dev/null
check "New bucket created by the CLI" "s3#$NEW_BUCKET" CreateBucket shadow-create info "$S"

revert
mkdir -p docs
uv run python scripts/e2e_report.py --results "$RESULTS" --out docs/e2e-results.md
echo "results written to docs/e2e-results.md"
exit $failures
