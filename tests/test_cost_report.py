import importlib.util
import sys
from datetime import date
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "cost_report", ROOT / "scripts" / "cost_report.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def group(service: str, amount: str) -> dict:  # type: ignore[type-arg]
    return {"Keys": [service], "Metrics": {"UnblendedCost": {"Amount": amount, "Unit": "USD"}}}


def test_previous_month_by_default() -> None:
    module = load()
    assert module.month_bounds(None, date(2026, 11, 26)) == ("2026-10-01", "2026-11-01")
    assert module.month_bounds(None, date(2027, 1, 5)) == ("2026-12-01", "2027-01-01")


def test_explicit_month_including_december() -> None:
    module = load()
    assert module.month_bounds("2026-12") == ("2026-12-01", "2027-01-01")
    assert module.month_bounds("2026-03") == ("2026-03-01", "2026-04-01")


def test_summarize_sorts_and_totals() -> None:
    module = load()
    response = {
        "ResultsByTime": [
            {"Groups": [group("Amazon Route 53", "0.50"), group("Amazon EC2", "0.80")]},
            {"Groups": [group("Amazon Route 53", "0.25")]},
        ]
    }
    rows, total = module.summarize(response)
    assert rows == [("Amazon EC2", 0.80), ("Amazon Route 53", 0.75)]
    assert round(total, 2) == 1.55


def test_render_lists_services_and_total() -> None:
    module = load()
    text = module.render([("Amazon EC2", 0.75)], 0.75, "2026-10-01", "2026-11-01")
    assert (
        "Amazon EC2" in text
        and "0.75" in text
        and text.splitlines()[-1].strip().startswith("Total")
    )


def test_empty_response() -> None:
    assert load().summarize({}) == ([], 0.0)
