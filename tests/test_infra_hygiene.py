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
