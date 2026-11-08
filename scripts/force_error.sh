#!/usr/bin/env bash
# Force the detector to fail so the alarms fire. The malformed event makes the handler raise.
#   - a synchronous invoke records a Lambda Error (alarm: clickops-detector-errors)
#   - an asynchronous invoke is retried twice, then lands in the DLQ
#     (alarm: clickops-detector-dlq-not-empty)
# Needs approval: it triggers real alarms and emails. Purge the DLQ afterwards.
#
#   AWS_PROFILE=clickops-admin scripts/force_error.sh
set -euo pipefail

REGION=ap-south-1
PAYLOAD='{"detail":{"eventName":"Malformed"}}'

echo "== synchronous invoke (expect FunctionError)"
aws lambda invoke --region $REGION --function-name clickops-detector \
  --cli-binary-format raw-in-base64-out --payload "$PAYLOAD" /dev/null \
  --query '{status:StatusCode,error:FunctionError}'

echo "== asynchronous invoke (expect a message in the DLQ after about 3 minutes)"
aws lambda invoke --region $REGION --function-name clickops-detector \
  --invocation-type Event --cli-binary-format raw-in-base64-out --payload "$PAYLOAD" /dev/null \
  --query '{status:StatusCode}'

echo "Alarms evaluate every 5 minutes; check the clickops-critical email."
echo "Then purge the queue:"
echo "  aws sqs purge-queue --region $REGION --queue-url \$(aws sqs get-queue-url --region $REGION --queue-name clickops-detector-dlq --query QueueUrl --output text)"
