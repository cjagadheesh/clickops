from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _workflow() -> dict[str, Any]:
    loaded = yaml.safe_load((ROOT / ".github/workflows/terraform.yml").read_text())
    assert isinstance(loaded, dict)
    return loaded


def test_triggers_on_pr_and_main_push() -> None:
    on = _workflow()[True]  # YAML parses the bare key `on` as True
    assert "pull_request" in on
    assert on["push"]["branches"] == ["main"]


def test_plan_runs_for_sandbox_and_detector_only_on_pr() -> None:
    plan = _workflow()["jobs"]["plan"]
    assert plan["if"] == "github.event_name == 'pull_request'"
    assert plan["strategy"]["matrix"]["root"] == ["sandbox", "detector"]
    assert plan["permissions"]["pull-requests"] == "write"


def test_applies_are_main_only_and_limited_to_sandbox_and_detector() -> None:
    jobs = _workflow()["jobs"]
    applies = [name for name in jobs if name.startswith("apply")]
    assert applies == ["apply-sandbox", "apply-detector"]
    for name, root in (("apply-sandbox", "infra/sandbox"), ("apply-detector", "infra/detector")):
        job = jobs[name]
        assert "refs/heads/main" in job["if"]
        assert any(root == s.get("working-directory") for s in job["steps"])
    assert "scripts/build_lambda.sh" in str(jobs["apply-detector"]["steps"])
    assert "apply-sandbox" in jobs["apply-detector"]["needs"]


def test_aws_access_uses_oidc_only() -> None:
    text = (ROOT / ".github/workflows/terraform.yml").read_text()
    assert "role-to-assume" in text
    assert "AWS_ACCESS_KEY_ID" not in text
    jobs = _workflow()["jobs"]
    for name in ("plan", "apply-sandbox", "apply-detector"):
        assert jobs[name]["permissions"]["id-token"] == "write"
