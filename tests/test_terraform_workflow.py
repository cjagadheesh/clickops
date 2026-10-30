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


def test_apply_is_main_only_and_sandbox_only() -> None:
    jobs = _workflow()["jobs"]
    applies = [name for name in jobs if name.startswith("apply")]
    assert applies == ["apply-sandbox"]
    job = jobs["apply-sandbox"]
    assert "refs/heads/main" in job["if"]
    assert any(s.get("working-directory") == "infra/sandbox" for s in job["steps"])


def test_aws_access_uses_oidc_only() -> None:
    text = (ROOT / ".github/workflows/terraform.yml").read_text()
    assert "role-to-assume" in text
    assert "AWS_ACCESS_KEY_ID" not in text
    jobs = _workflow()["jobs"]
    for name in ("plan", "apply-sandbox"):
        assert jobs[name]["permissions"]["id-token"] == "write"
