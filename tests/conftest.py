import json
from pathlib import Path
from typing import Any

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "cloudtrail"


def fixture_paths() -> list[Path]:
    return sorted(FIXTURE_DIR.rglob("*.json"))


def load_fixture(service: str, name: str) -> dict[str, Any]:
    data = json.loads((FIXTURE_DIR / service / f"{name}.json").read_text())
    assert isinstance(data, dict)
    return data
