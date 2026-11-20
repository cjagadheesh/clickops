import importlib.util
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = (ROOT / "scripts" / "e2e.sh").read_text()


def load_report() -> ModuleType:
    spec = importlib.util.spec_from_file_location("e2e_report", ROOT / "scripts" / "e2e_report.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def scenario(label: str, severity: str = "critical", delay: int = 120, **extra: object) -> dict:  # type: ignore[type-arg]
    return {
        "label": label,
        "found": True,
        "delay_seconds": delay,
        "actor": "asha (cli-human)",
        "outcome": "managed-drift",
        "severity": severity,
        "problems": [],
        "expect_outcome": "managed-drift",
        "expect_severity": severity,
        **extra,
    }


def test_script_needs_confirmation_and_checks_the_six_scenarios() -> None:
    assert 'CONFIRM:-}" != "yes"' in SCRIPT
    expectations = re.findall(r"(\w+-\w+|managed-drift) (critical|warning|info) \"\$S\"", SCRIPT)
    assert [e[1] for e in expectations] == [
        "critical",
        "warning",
        "critical",
        "warning",
        "warning",
        "info",
    ]
    assert SCRIPT.count('check "') == 6
    for needle in (
        "AuthorizeSecurityGroupIngress",
        "AttachRolePolicy",
        "PutBucketPublicAccessBlock",
        "UpdateFunctionConfiguration",
        "ChangeResourceRecordSets",
        "CreateBucket",
        "shadow-create",
        "0.0.0.0/0",
        "AmazonS3FullAccess",
        "--timeout 25",
        "10.20.1.99",
    ):
        assert needle in SCRIPT, needle


def test_script_waits_up_to_ten_minutes_per_scenario() -> None:
    assert "E2E_TIMEOUT:-600" in SCRIPT


def test_script_reverts_with_cli_inverses_terraform_and_a_clean_plan_even_when_interrupted() -> (
    None
):
    assert "revoke-security-group-ingress" in SCRIPT and "detach-role-policy" in SCRIPT
    assert "delete-bucket" in SCRIPT and "terraform -chdir=infra/sandbox apply" in SCRIPT
    assert "plan -detailed-exitcode" in SCRIPT
    assert "trap 'revert' EXIT" in SCRIPT and "reverted=1" in SCRIPT
    assert "-auto-approve" not in SCRIPT.replace("TF_APPLY_ARGS=-auto-approve", "")


def test_report_renders_a_table_with_delays_and_the_revert_state() -> None:
    module = load_report()
    results = [
        scenario("SSH from the world", "critical", 100),
        scenario("Policy attached", "warning", 300),
        {"kind": "revert", "ok": True},
    ]
    text = module.render(results, datetime(2026, 11, 20, 4, 0, tzinfo=UTC))
    assert "Run on 2026-11-20 04:00 UTC." in text
    assert "| SSH from the world | managed-drift / critical | managed-drift / critical |" in text
    assert "| 100 s | pass |" in text
    assert "2 of 2 scenarios passed." in text
    assert "fastest 100 s, slowest 300 s, mean 200 s" in text
    assert "Revert: reverted, and `terraform plan` shows no changes." in text


def test_report_marks_failures_and_timeouts() -> None:
    module = load_report()
    wrong = scenario(
        "Wrong severity", "warning", problems=["severity is critical, expected warning"]
    )
    missing = {
        "label": "Never stored",
        "found": False,
        "waited_seconds": 600,
        "expect_outcome": "shadow-create",
        "expect_severity": "info",
        "problems": ["no finding stored before the timeout"],
    }
    text = module.render([wrong, missing, {"kind": "revert", "ok": False}])
    assert text.count("| FAIL |") == 2
    assert "| > 600 s | FAIL |" in text and "0 of 2 scenarios passed." in text
    assert "did not finish cleanly" in text


def test_report_main_writes_the_file_and_sets_the_exit_code(tmp_path: Path) -> None:
    module = load_report()
    results = tmp_path / "r.jsonl"
    out = tmp_path / "e2e-results.md"
    results.write_text(
        json.dumps(scenario("ok")) + "\n" + json.dumps({"kind": "revert", "ok": True}) + "\n"
    )
    assert module.main(["--results", str(results), "--out", str(out)]) == 0
    assert "1 of 1 scenarios passed." in out.read_text()
    results.write_text(json.dumps(scenario("bad", problems=["x"])) + "\n")
    assert module.main(["--results", str(results), "--out", str(out)]) == 1


def test_results_doc_exists_and_says_how_to_produce_it() -> None:
    text = (ROOT / "docs" / "e2e-results.md").read_text()
    assert "scripts/e2e.sh" in text


@pytest.mark.parametrize("name", ["e2e.sh", "e2e_alerts.sh"])
def test_live_scripts_never_apply_without_the_owner(name: str) -> None:
    text = (ROOT / "scripts" / name).read_text()
    assert "terraform apply -auto-approve" not in text


def test_alert_check_script_reverts_with_the_inverse_calls_not_terraform() -> None:
    text = (ROOT / "scripts" / "e2e_alerts.sh").read_text()
    assert "REVERT:-}" in text and "revoke-security-group-ingress" in text
    assert "detach-role-policy" in text
    assert "terraform apply" not in text.replace("`terraform apply`", "")
