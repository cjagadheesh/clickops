import re
from pathlib import Path

DETECTOR = Path(__file__).resolve().parent.parent / "infra" / "detector"


def _read(name: str) -> str:
    return (DETECTOR / name).read_text()


def test_trail_is_multi_region_and_write_only() -> None:
    tf = _read("trail.tf")
    assert "is_multi_region_trail         = true" in tf
    assert 'read_write_type           = "WriteOnly"' in tf
    assert "include_management_events = true" in tf
    assert "enable_log_file_validation    = true" in tf


def test_trail_bucket_expires_logs_and_blocks_public_access() -> None:
    tf = _read("trail_bucket.tf")
    assert "expiration" in tf and "var.trail_log_retention_days" in tf
    assert "block_public_policy     = true" in tf
    assert "AWSCloudTrailWrite" in tf and "cloudtrail.amazonaws.com" in tf
    assert "aws:SecureTransport" in tf
    assert re.search(r"trail_log_retention_days.*?default\s*=\s*30", _read("variables.tf"), re.S)


def test_events_table_has_ttl_and_day_index() -> None:
    tf = _read("events_table.tf")
    assert "PAY_PER_REQUEST" in tf
    assert 'attribute_name = "expires_at"' in tf
    assert "global_secondary_index" in tf


def test_critical_topic_has_email_subscription_from_variable() -> None:
    tf = _read("alerts_topic.tf")
    assert 'name = "clickops-critical"' in tf
    assert 'protocol  = "email"' in tf
    assert "var.alert_email" in tf


def test_detector_uses_its_own_state_key_and_no_email_is_committed() -> None:
    assert 'key          = "detector/terraform.tfstate"' in _read("versions.tf")
    example = _read("detector.auto.tfvars.example")
    assert "you@example.com" in example


def test_lambda_settings_match_the_spec() -> None:
    tf = _read("lambda.tf")
    assert 'runtime          = "python3.12"' in tf
    assert 'architectures    = ["arm64"]' in tf
    assert "memory_size      = 256" in tf
    assert "timeout          = 30" in tf
    assert "retention_in_days = 14" in tf
    assert "dead_letter_config" in tf
    assert 'handler          = "clickops.handler.handler"' in tf


def test_lambda_role_is_limited_to_logs_dynamodb_put_and_dlq() -> None:
    tf = _read("lambda_role.tf")
    assert '"dynamodb:PutItem"' in tf
    assert "logs:CreateLogStream" in tf and "logs:PutLogEvents" in tf
    assert "sqs:SendMessage" in tf
    for broad in ('"dynamodb:*"', '"logs:*"', '"s3:*"', '"*"'):
        assert broad not in tf


def test_lambda_env_names_match_the_code() -> None:
    from clickops import handler
    from clickops.actors import SELF_ROLE_ENV
    from clickops.store import TABLE_NAME

    tf = _read("lambda.tf")
    assert handler.TABLE_ENV in tf and handler.TRUSTED_ROLES_ENV in tf and SELF_ROLE_ENV in tf
    assert TABLE_NAME == "clickops-events"


def test_rules_target_the_detector_with_a_dlq_and_permission() -> None:
    tf = _read("rules.tf")
    assert tf.count("dead_letter_config") == 2
    assert tf.count('principal     = "events.amazonaws.com"') == 2
    assert "patterns/regional.json" in tf
    assert tf.count("patterns/global.json") == 2


def test_forwarding_rule_lives_in_us_east_1_and_targets_the_mumbai_bus() -> None:
    tf = _read("rules.tf")
    forward = tf[tf.index('resource "aws_cloudwatch_event_rule" "forward"') :]
    assert "provider       = aws.use1" in forward
    assert "arn      = local.default_bus_arn" in forward
    assert "role_arn = aws_iam_role.forwarder.arn" in forward
    assert 'region = "us-east-1"' in _read("versions.tf")
    assert 'actions   = ["events:PutEvents"]' in tf
    assert "resources = [local.default_bus_arn]" in tf


def test_pattern_files_are_valid_json_for_cloudtrail_api_calls() -> None:
    import json

    for name in ("regional", "global"):
        pattern = json.loads((DETECTOR / "patterns" / f"{name}.json").read_text())
        assert pattern["detail-type"] == ["AWS API Call via CloudTrail"]
        assert pattern["detail"]["eventName"]
    sources = json.loads((DETECTOR / "patterns" / "regional.json").read_text())["source"]
    assert sources == ["aws.ec2", "aws.s3", "aws.lambda"]
