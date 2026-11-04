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
