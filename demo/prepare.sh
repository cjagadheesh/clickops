#!/usr/bin/env bash
# Creates the empty scratch bucket the demo imports and prints its name. Free; tagged for cleanup.
set -euo pipefail
REGION=ap-south-1
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
BUCKET="clickops-demo-$ACCOUNT-$(date +%s)"
aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
  --create-bucket-configuration LocationConstraint="$REGION" > /dev/null
aws s3api put-bucket-tagging --bucket "$BUCKET" \
  --tagging 'TagSet=[{Key=project,Value=clickops},{Key=owner,Value=agent}]'
echo "$BUCKET"
