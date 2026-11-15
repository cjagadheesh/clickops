#!/usr/bin/env bash
# Live check of the two headline alerts against the real sandbox, with measured delays.
#
#   1. allow SSH from 0.0.0.0/0 on the admin group  -> critical managed-drift, Slack and email
#   2. attach AmazonS3FullAccess to the sandbox role -> warning managed-drift, Slack
#
# Needs approval: it changes real resources. Afterwards revert with `terraform apply` in
# infra/sandbox (this script does not apply anything). Check #clickops-alerts and your email.
#
#   CONFIRM=yes AWS_PROFILE=clickops-admin scripts/e2e_alerts.sh
set -euo pipefail

if [ "${CONFIRM:-}" != "yes" ]; then
  echo "This changes real AWS resources. Re-run with CONFIRM=yes after approval." >&2
  exit 1
fi

cd "$(dirname "$0")/.."
REGION=ap-south-1
ROLE=clickops-sandbox-app
POLICY=arn:aws:iam::aws:policy/AmazonS3FullAccess

VPC=$(aws ec2 describe-vpcs --region $REGION --filters Name=tag:Name,Values=clickops-sandbox \
  --query 'Vpcs[0].VpcId' --output text)
ADMIN_SG=$(aws ec2 describe-security-groups --region $REGION \
  --filters Name=group-name,Values=admin Name=vpc-id,Values="$VPC" \
  --query 'SecurityGroups[0].GroupId' --output text)

now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
failures=0

echo "== 1. SSH from the world on the admin group ($ADMIN_SG)"
START=$(now)
aws ec2 authorize-security-group-ingress --region $REGION --group-id "$ADMIN_SG" \
  --protocol tcp --port 22 --cidr 0.0.0.0/0 > /dev/null
uv run python scripts/wait_for_finding.py --resource "sg#$ADMIN_SG" \
  --event AuthorizeSecurityGroupIngress --since "$START" \
  --expect-outcome managed-drift --expect-severity critical || failures=$((failures + 1))

echo "== 2. AmazonS3FullAccess on the sandbox role"
START=$(now)
aws iam attach-role-policy --role-name $ROLE --policy-arn $POLICY
uv run python scripts/wait_for_finding.py --resource "iam-role#$ROLE" \
  --event AttachRolePolicy --since "$START" \
  --expect-outcome managed-drift --expect-severity warning || failures=$((failures + 1))

echo
echo "Now revert both with: (cd infra/sandbox && terraform apply)"
echo "Check that a critical message and email arrived for step 1 and a warning for step 2,"
echo "then write the delays above into PROGRESS.md."
exit $failures
