"""Fetch recent CloudTrail events with lookup-events and save them as real fixtures.

Wraps each CloudTrail record in an EventBridge "AWS API Call via CloudTrail" envelope so fixtures
look like what the detector receives. Account IDs are replaced with a placeholder.

    uv run python scripts/fetch_fixtures.py --since 2026-10-26T10:00:00Z
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import boto3

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "cloudtrail"
SERVICES = {
    "ec2.amazonaws.com": ("ec2", "ap-south-1"),
    "s3.amazonaws.com": ("s3", "ap-south-1"),
    "lambda.amazonaws.com": ("lambda", "ap-south-1"),
    "iam.amazonaws.com": ("iam", "us-east-1"),
    "route53.amazonaws.com": ("route53", "us-east-1"),
}
PLACEHOLDER_ACCOUNT = "111122223333"


def envelope(record: dict[str, Any], service: str) -> dict[str, Any]:
    return {
        "_source": "real",
        "version": "0",
        "id": record["eventID"],
        "detail-type": "AWS API Call via CloudTrail",
        "source": f"aws.{service}",
        "account": record["recipientAccountId"],
        "time": record["eventTime"],
        "region": record["awsRegion"],
        "resources": [],
        "detail": record,
    }


def scrub(text: str, account: str) -> str:
    text = text.replace(account, PLACEHOLDER_ACCOUNT)
    return re.sub(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b", "ASIAEXAMPLEEXAMPLE", text)


def fetch(since: datetime, account: str) -> int:
    saved = 0
    for event_source, (service, region) in SERVICES.items():
        client = boto3.client("cloudtrail", region_name=region)
        pages = client.get_paginator("lookup_events").paginate(
            LookupAttributes=[{"AttributeKey": "EventSource", "AttributeValue": event_source}],
            StartTime=since,
        )
        seen: set[str] = set()
        for page in pages:
            for item in page["Events"]:
                record = json.loads(item["CloudTrailEvent"])
                name = record["eventName"]
                if record.get("readOnly") or record.get("errorCode") or name in seen:
                    continue
                seen.add(name)
                path = OUT / service / f"{name}.json"
                body = json.dumps(envelope(record, service), indent=2, sort_keys=True)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(scrub(body, account) + "\n")
                saved += 1
    return saved


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", required=True)
    args = parser.parse_args()
    account = boto3.client("sts").get_caller_identity()["Account"]
    since = datetime.fromisoformat(args.since.replace("Z", "+00:00"))
    print(f"saved {fetch(since, account)} fixtures")


if __name__ == "__main__":
    main()
