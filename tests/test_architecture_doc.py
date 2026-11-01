from pathlib import Path

DOC = Path(__file__).resolve().parent.parent / "docs" / "architecture.md"


def test_architecture_has_event_flow_and_terraform_roots_diagrams() -> None:
    text = DOC.read_text()
    assert text.count("```mermaid") == 2
    for root in ("infra/bootstrap", "infra/sandbox", "infra/detector"):
        assert root in text
    for stage in ("events.py", "actors.py", "resolvers/", "state.py", "compare/", "rules.py"):
        assert stage in text
