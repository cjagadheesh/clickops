#!/usr/bin/env bash
# Live check of `clickops import` on a real shadow resource: create one scratch S3 bucket with the
# CLI, import it, show the plan summary, then delete the bucket.
#
# Needs Terraform 1.10+, a clickops.yaml with real state locations, and approval: it creates and
# deletes one bucket (free, empty).
#
#   CONFIRM=yes AWS_PROFILE=clickops-admin scripts/test_import_bucket.sh
set -euo pipefail

if [ "${CONFIRM:-}" != "yes" ]; then
  echo "This creates and deletes one S3 bucket. Re-run with CONFIRM=yes after approval." >&2
  exit 1
fi

cd "$(dirname "$0")/.."
REGION=ap-south-1
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
BUCKET="clickops-import-test-$ACCOUNT-$(date +%s)"
trap 'aws s3api delete-bucket --bucket "$BUCKET" --region $REGION 2>/dev/null || true' EXIT

aws s3api create-bucket --bucket "$BUCKET" --region $REGION \
  --create-bucket-configuration LocationConstraint=$REGION > /dev/null
aws s3api put-bucket-tagging --bucket "$BUCKET" \
  --tagging 'TagSet=[{Key=project,Value=clickops},{Key=owner,Value=agent}]'
echo "created $BUCKET"

OUT=$(mktemp -d)
uv run clickops import --only "s3/$BUCKET" --out "$OUT" | tee "$OUT/run.log"
grep -q "1 to import, 0 to add, 0 to change, 0 to destroy" "$OUT/run.log" \
  || { echo "FAIL: the plan is not just the import" >&2; exit 1; }
grep -q "validates" "$OUT/run.log" || { echo "FAIL: generated config does not validate" >&2; exit 1; }
echo "OK: the import plan shows only the import and the generated config validates"
echo "Generated config: $(ls "$OUT"/*/generated.tf)"
