import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "render_example_alerts", ROOT / "scripts" / "render_example_alerts.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_example_alert_doc_is_up_to_date() -> None:
    assert load().main(["--check"]) == 0


def test_examples_show_both_headline_alerts() -> None:
    text = (ROOT / "docs" / "alert-examples.md").read_text()
    assert "🔴" in text and "🟠" in text
    assert "terraform apply -target=aws_security_group.admin" in text
    assert "+ tcp 22-22 0.0.0.0/0" in text
    assert "+ arn:aws:iam::aws:policy/AmazonS3FullAccess" in text
    assert text.count("Email subject:") == 1  # only the critical finding is emailed


def test_live_alert_script_checks_the_two_scenarios_and_needs_confirmation() -> None:
    script = (ROOT / "scripts" / "e2e_alerts.sh").read_text()
    assert 'CONFIRM:-}" != "yes"' in script
    assert "--expect-severity critical" in script and "--expect-severity warning" in script
    assert "AmazonS3FullAccess" in script and "0.0.0.0/0" in script
    assert "terraform apply -auto-approve" not in script  # reverting is left to the human
