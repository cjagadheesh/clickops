import json
from pathlib import Path
from typing import Any

import pytest
from conftest import COVERAGE, fixture_paths
from eventpattern import matches

PATTERNS = Path(__file__).resolve().parent.parent / "infra" / "detector" / "patterns"


def _pattern(name: str) -> dict[str, Any]:
    return json.loads((PATTERNS / f"{name}.json").read_text())


# Rule name -> (region whose default bus it sits on, pattern file)
RULES = {
    "regional": ("ap-south-1", "regional"),
    "forward-us-east-1": ("us-east-1", "global"),
    "global-ap-south-1": ("ap-south-1", "global"),
}


def _buses(event: dict[str, Any]) -> list[str]:
    """Buses an event is delivered to: its own region, plus ap-south-1 after the forwarding rule."""
    region = event["region"]
    return [region] + (["ap-south-1"] if region == "us-east-1" else [])


def matching_rules(event: dict[str, Any], bus: str) -> set[str]:
    return {
        name
        for name, (rule_bus, pattern) in RULES.items()
        if rule_bus == bus and matches(_pattern(pattern), event)
    }


@pytest.mark.parametrize("path", fixture_paths(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_each_fixture_matches_exactly_the_right_rules(path: Path) -> None:
    event = json.loads(path.read_text())
    service = path.parent.name
    if service in ("ec2", "s3", "lambda"):
        assert matching_rules(event, event["region"]) == {"regional"}
        assert event["region"] == "ap-south-1"
    else:
        # IAM and Route 53 arrive in us-east-1, are forwarded, then matched in ap-south-1.
        assert event["region"] == "us-east-1"
        assert matching_rules(event, "us-east-1") == {"forward-us-east-1"}
        assert matching_rules(event, "ap-south-1") == {"global-ap-south-1"}


def test_every_fixture_reaches_a_detector_rule() -> None:
    for path in fixture_paths():
        event = json.loads(path.read_text())
        delivered = set().union(*(matching_rules(event, b) for b in _buses(event)))
        assert delivered, path.name


def test_every_watched_event_name_is_in_the_patterns() -> None:
    regional = _pattern("regional")["detail"]["eventName"]
    glob = _pattern("global")["detail"]["eventName"]
    for service, names in COVERAGE.items():
        pattern_names = regional if service in ("ec2", "s3", "lambda") else glob
        for name in names:
            wanted: Any = {"prefix": name} if service == "lambda" else name
            assert wanted in pattern_names, f"{name} missing from the {service} pattern"


def test_unwatched_and_read_only_calls_do_not_match() -> None:
    base = {"detail-type": "AWS API Call via CloudTrail", "source": "aws.ec2"}
    for name in ("DescribeInstances", "ListBuckets", "GetFunction"):
        event = {**base, "detail": {"eventName": name}}
        assert not matches(_pattern("regional"), event)
    wrong_type = {**base, "detail-type": "EC2 Instance State-change Notification"}
    wrong_type["detail"] = {"eventName": "RunInstances"}
    assert not matches(_pattern("regional"), wrong_type)


def test_lambda_names_match_by_prefix() -> None:
    event = {
        "detail-type": "AWS API Call via CloudTrail",
        "source": "aws.lambda",
        "detail": {"eventName": "UpdateFunctionConfiguration20150331v2"},
    }
    assert matches(_pattern("regional"), event)
    event["detail"]["eventName"] = "InvokeFunction"
    assert not matches(_pattern("regional"), event)


def test_matcher_semantics() -> None:
    assert matches({"a": ["x", "y"]}, {"a": "y"})
    assert matches({"a": {"b": [1]}}, {"a": {"b": 1}})
    assert matches({"a": ["x"]}, {"a": ["w", "x"]})
    assert not matches({"a": ["x"]}, {})
    assert not matches({"a": {"b": ["x"]}}, {"a": "x"})
