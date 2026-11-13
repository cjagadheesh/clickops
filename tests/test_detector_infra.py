import re
from pathlib import Path

import pytest

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
    for broad in ('"dynamodb:*"', '"logs:*"', '"s3:*"'):
        assert broad not in tf
    assert tf.count('"*"') == 1  # only the EC2 describe calls, which have no resource-level scope


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


def test_alarms_notify_the_critical_topic() -> None:
    tf = _read("alarms.tf")
    assert 'metric_name         = "Errors"' in tf
    assert 'metric_name         = "ApproximateNumberOfMessagesVisible"' in tf
    assert tf.count("period              = 300") == 2
    assert tf.count("threshold           = 0") == 2
    assert tf.count('comparison_operator = "GreaterThanThreshold"') == 2
    assert tf.count("alarm_actions       = [aws_sns_topic.critical.arn]") == 2
    assert "cloudwatch.amazonaws.com" in tf and "sns:Publish" in tf


def test_forced_error_script_uses_a_payload_the_handler_rejects() -> None:
    import json
    import re

    from clickops.events import NormalizationError, normalize

    script = (DETECTOR.parent.parent / "scripts" / "force_error.sh").read_text()
    payload = re.search(r"PAYLOAD='(.*)'", script)
    assert payload
    with pytest.raises(NormalizationError):
        normalize(json.loads(payload.group(1)))


def test_detector_can_read_only_the_two_state_keys() -> None:
    tf = _read("lambda_role.tf")
    block = tf[tf.index('sid     = "ReadTerraformState"') :]
    block = block[: block.index("}\n")]
    assert 'actions = ["s3:GetObject"]' in block
    assert block.count("terraform.tfstate") == 2
    assert "sandbox/terraform.tfstate" in block and "detector/terraform.tfstate" in block
    assert "s3:PutObject" not in tf


def test_detector_read_actions_are_explicit_and_cover_every_comparator_call() -> None:
    tf = _read("lambda_role.tf")
    needed = [
        "ec2:DescribeSecurityGroups",
        "ec2:DescribeInstances",
        "iam:GetRole",
        "iam:ListRolePolicies",
        "iam:GetRolePolicy",
        "iam:ListAttachedRolePolicies",
        "iam:GetPolicy",
        "iam:GetPolicyVersion",
        "s3:GetBucketPolicy",
        "s3:GetBucketPublicAccessBlock",
        "s3:GetBucketVersioning",
        "s3:GetEncryptionConfiguration",
        "lambda:GetFunctionConfiguration",
        "route53:ListResourceRecordSets",
    ]
    for action in needed:
        assert f'"{action}"' in tf, action
    assert not re.search(r'"[a-z0-9]+:\*"', tf)
    assert not re.search(
        r'"[a-z0-9]+:(Put|Delete|Create|Update|Attach|Detach)',
        tf.replace("dynamodb:PutItem", "")
        .replace("sqs:SendMessage", "")
        .replace("logs:CreateLogStream", "")
        .replace("logs:PutLogEvents", ""),
    )


def test_async_failures_are_retried_twice_then_dead_lettered() -> None:
    tf = _read("lambda.tf")
    assert 'resource "aws_lambda_function_event_invoke_config" "detector"' in tf
    assert "maximum_retry_attempts       = 2" in tf
    assert "dead_letter_config" in tf
    rules = _read("rules.tf")
    assert rules.count("maximum_retry_attempts       = 2") == 2 and "dead_letter_config" in rules


def test_lambda_reads_both_state_files() -> None:
    tf = _read("lambda.tf")
    assert "CLICKOPS_STATE_LOCATIONS" in tf
    assert "sandbox/terraform.tfstate" in tf and "detector/terraform.tfstate" in tf


def test_runtime_config_is_not_committed() -> None:
    root = DETECTOR.parent.parent
    assert "clickops.yaml" in (root / ".gitignore").read_text().split()
    assert "clickops.yaml" in (root / "scripts" / "build_lambda.sh").read_text()
