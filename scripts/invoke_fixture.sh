#!/usr/bin/env bash
# Invoke the deployed detector with one fixture and show the item it stored.
# Needs approval: it writes an item to the real clickops-events table.
#
#   AWS_PROFILE=clickops-admin scripts/invoke_fixture.sh ec2/AuthorizeSecurityGroupIngress
set -euo pipefail

FIXTURE="${1:?usage: invoke_fixture.sh <service>/<EventName>}"
FILE="$(dirname "$0")/../tests/fixtures/cloudtrail/${FIXTURE}.json"
REGION=ap-south-1
OUT=$(mktemp)

aws lambda invoke --region $REGION --function-name clickops-detector \
  --cli-binary-format raw-in-base64-out --payload "fileb://$FILE" "$OUT" \
  --query '{status:StatusCode,error:FunctionError}'
cat "$OUT"; echo
EVENT_ID=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['detail']['eventID'])" "$FILE")
DAY=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['detail']['eventTime'][:10])" "$FILE")

aws dynamodb query --region $REGION --table-name clickops-events --index-name day-ts \
  --key-condition-expression '#d = :d' --expression-attribute-names '{"#d":"day"}' \
  --filter-expression 'event_id = :e' \
  --expression-attribute-values "{\":d\":{\"S\":\"$DAY\"},\":e\":{\"S\":\"$EVENT_ID\"}}" \
  --query 'Items[0]'
rm -f "$OUT"
