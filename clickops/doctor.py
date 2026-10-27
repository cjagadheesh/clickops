"""Environment checks behind ``clickops doctor``."""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from clickops.config import Config, ConfigError, load_config

MIN_TERRAFORM = (1, 10)


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str
    hint: str = ""


def check_credentials(region: str) -> CheckResult:
    name = "AWS credentials"
    try:
        ident = boto3.client("sts", region_name=region).get_caller_identity()
    except (BotoCoreError, ClientError) as exc:
        return CheckResult(
            name, False, str(exc), "Run `aws configure` or set AWS_PROFILE=clickops-admin."
        )
    return CheckResult(name, True, ident["Arn"])


def parse_terraform_version(output: str) -> tuple[int, ...] | None:
    try:
        version = json.loads(output)["terraform_version"]
    except (ValueError, KeyError, TypeError):
        match = re.search(r"Terraform v(\d+)\.(\d+)\.(\d+)", output)
        return tuple(int(p) for p in match.groups()) if match else None
    parts = re.match(r"(\d+)\.(\d+)\.(\d+)", str(version))
    return tuple(int(p) for p in parts.groups()) if parts else None


def check_terraform() -> CheckResult:
    name = "Terraform version"
    hint = "Install Terraform 1.10 or newer from https://developer.hashicorp.com/terraform."
    try:
        proc = subprocess.run(
            ["terraform", "version", "-json"], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CheckResult(name, False, f"terraform not runnable: {exc}", hint)
    version = parse_terraform_version(proc.stdout)
    if version is None:
        return CheckResult(name, False, "could not parse `terraform version` output", hint)
    text = ".".join(map(str, version))
    if version[:2] < MIN_TERRAFORM:
        return CheckResult(name, False, f"{text} is older than 1.10", hint)
    return CheckResult(name, True, text)


def check_config(path: Path) -> tuple[CheckResult, Config | None]:
    name = "Config"
    try:
        cfg = load_config(path)
    except ConfigError as exc:
        return CheckResult(
            name, False, str(exc), "Copy clickops.example.yaml to clickops.yaml and fix it."
        ), None
    return CheckResult(name, True, str(path)), cfg


def check_state_access(cfg: Config) -> list[CheckResult]:
    results = []
    for loc in cfg.state_locations:
        name = f"State s3://{loc.bucket}/{loc.key}"
        try:
            boto3.client("s3", region_name=loc.region).head_object(Bucket=loc.bucket, Key=loc.key)
        except (BotoCoreError, ClientError) as exc:
            results.append(
                CheckResult(
                    name,
                    False,
                    str(exc),
                    "Check the bucket and key, and that your role has s3:GetObject on it.",
                )
            )
        else:
            results.append(CheckResult(name, True, "readable"))
    return results


def run_checks(
    config_path: Path, terraform_check: Callable[[], CheckResult] = check_terraform
) -> list[CheckResult]:
    config_result, cfg = check_config(config_path)
    results = [check_credentials(cfg.region if cfg else "ap-south-1"), terraform_check()]
    results.append(config_result)
    if cfg is not None:
        results.extend(check_state_access(cfg))
    return results
