import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _tracked(pattern: str) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", pattern], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return out.stdout.split()


def test_no_state_or_tfvars_tracked() -> None:
    assert _tracked("*.tfstate*") == []
    assert _tracked("*.auto.tfvars") == []


def test_no_account_ids_or_keys_in_infra() -> None:
    patterns = [r"\b\d{12}\b", r"AKIA[0-9A-Z]{16}"]
    for path in _tracked("infra/**"):
        text = (ROOT / path).read_text()
        if path.endswith(".example"):
            text = re.sub(r"123456789012", "", text)
        for pat in patterns:
            assert not re.search(pat, text), f"{path} matches {pat}"


def test_no_slack_webhook_urls_are_tracked() -> None:
    for path in _tracked("*"):
        text = (ROOT / path).read_text(errors="ignore") if (ROOT / path).is_file() else ""
        assert "hooks.slack.com/services/" not in text, path


def test_webhook_script_reads_the_url_silently_and_never_echoes_it() -> None:
    script = (ROOT / "scripts" / "store_slack_webhook.sh").read_text()
    assert "read -r -s" in script
    assert 'echo "$URL"' not in script
