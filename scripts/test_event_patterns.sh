#!/usr/bin/env bash
# Check every fixture against the real EventBridge matcher with `aws events test-event-pattern`.
# Read-only (the call changes nothing), so CI can run it with the clickops-ci role.
#
#   scripts/test_event_patterns.sh
set -euo pipefail

cd "$(dirname "$0")/.."
REGION=${AWS_REGION:-ap-south-1}
REGIONAL=$(python3 -c "import json;print(json.dumps(json.load(open('infra/detector/patterns/regional.json'))))")
GLOBAL=$(python3 -c "import json;print(json.dumps(json.load(open('infra/detector/patterns/global.json'))))")
failures=0

check() { # fixture, pattern name, pattern, expected
  local file=$1 name=$2 pattern=$3 expected=$4 event result
  event=$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); d.pop('_source',None); print(json.dumps(d))" "$file")
  result=$(aws events test-event-pattern --region "$REGION" --event "$event" \
    --event-pattern "$pattern" --query Result --output text)
  if [ "$result" != "$expected" ]; then
    echo "FAIL $file: $name pattern returned $result, expected $expected"
    failures=$((failures + 1))
  fi
}

for file in tests/fixtures/cloudtrail/*/*.json; do
  service=$(basename "$(dirname "$file")")
  case "$service" in
    ec2|s3|lambda) check "$file" regional "$REGIONAL" True;  check "$file" global "$GLOBAL" False ;;
    iam|route53)   check "$file" regional "$REGIONAL" False; check "$file" global "$GLOBAL" True ;;
  esac
done

if [ "$failures" -ne 0 ]; then
  echo "$failures pattern checks failed" >&2
  exit 1
fi
echo "all fixtures match the expected patterns"
