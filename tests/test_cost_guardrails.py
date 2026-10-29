import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FORBIDDEN = [
    "aws_nat_gateway",
    "aws_lb",
    "aws_alb",
    "aws_elb",
    "aws_db_instance",
    "aws_rds_cluster",
    "aws_eks_cluster",
]


def test_no_costly_resources_in_infra() -> None:
    for tf in (ROOT / "infra").rglob("*.tf"):
        text = tf.read_text()
        for kind in FORBIDDEN:
            assert not re.search(rf'resource\s+"{kind}"', text), f"{tf} declares {kind}"


def test_sandbox_instance_is_held_stopped() -> None:
    text = (ROOT / "infra/sandbox/instance.tf").read_text()
    assert 'state       = "stopped"' in text
    assert "t4g.nano" in text
