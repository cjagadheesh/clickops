"""scripts/destroy.sh with stand-in aws, terraform, uv and build commands that only log calls."""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "destroy.sh"
ACCOUNT = "123456789012"

STUB = """#!/usr/bin/env bash
echo "$(basename "$0") $*" >> "$STUB_LOG"
if [ "$(basename "$0")" = aws ] && [ "$1" = sts ]; then echo "$STUB_ACCOUNT"; fi
if [ "$(basename "$0")" = aws ] && [ "$1" = ssm ] && [ -n "${STUB_SSM_FAIL:-}" ]; then exit 254; fi
exit 0
"""


@pytest.fixture
def sandbox(tmp_path: Path) -> dict[str, object]:
    """A copy of the repo layout the script needs, with stub commands first on PATH."""
    work = tmp_path / "repo"
    (work / "scripts").mkdir(parents=True)
    script = work / "scripts" / "destroy.sh"
    script.write_text(SCRIPT.read_text())
    script.chmod(0o755)
    build = work / "scripts" / "build_lambda.sh"
    build.write_text(
        "#!/usr/bin/env bash\n"
        'echo "build_lambda" >> "$STUB_LOG"\n'
        "mkdir -p dist\n"
        "touch dist/clickops-detector.zip\n"
    )
    build.chmod(0o755)
    for rel in (
        "infra/sandbox/backend.hcl",
        "infra/detector/backend.hcl",
        "infra/detector/detector.auto.tfvars",
        "infra/bootstrap/bootstrap.auto.tfvars",
    ):
        path = work / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("aws", "terraform", "uv"):
        stub = bin_dir / name
        stub.write_text(STUB)
        stub.chmod(0o755)
    log = tmp_path / "calls.log"
    log.write_text("")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "STUB_LOG": str(log),
        "STUB_ACCOUNT": ACCOUNT,
    }
    env.pop("DRY_RUN", None)
    env.pop("TF_DESTROY_ARGS", None)
    return {"work": work, "env": env, "log": log}


def run(box: dict[str, object], stdin: str = "", **extra: str) -> subprocess.CompletedProcess[str]:
    env = {**box["env"], **extra}  # type: ignore[dict-item]
    return subprocess.run(
        [str(box["work"] / "scripts" / "destroy.sh")],  # type: ignore[operator]
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        cwd=box["work"],  # type: ignore[arg-type]
        check=False,
    )


def calls(box: dict[str, object]) -> list[str]:
    return Path(str(box["log"])).read_text().splitlines()


def test_dry_run_prints_the_plan_and_changes_nothing(sandbox: dict[str, object]) -> None:
    result = run(sandbox, DRY_RUN="1")
    assert result.returncode == 0
    assert "DRY_RUN=1: nothing was changed." in result.stdout
    assert result.stdout.index("infra/sandbox") < result.stdout.index("infra/detector")
    assert result.stdout.index("infra/detector") < result.stdout.index("infra/bootstrap")
    assert calls(sandbox) == ["aws sts get-caller-identity --query Account --output text"]


@pytest.mark.parametrize("answer", ["", "yes", "destroy", "destroy 999999999999"])
def test_wrong_confirmation_aborts_before_any_change(
    sandbox: dict[str, object], answer: str
) -> None:
    result = run(sandbox, stdin=answer + "\n")
    assert result.returncode == 1
    assert "Aborted" in result.stderr
    assert len(calls(sandbox)) == 1  # only the identity lookup


def test_no_stdin_aborts(sandbox: dict[str, object]) -> None:
    assert run(sandbox).returncode != 0
    assert len(calls(sandbox)) == 1


def test_missing_local_file_is_reported_before_the_prompt(sandbox: dict[str, object]) -> None:
    (Path(str(sandbox["work"])) / "infra/detector/detector.auto.tfvars").unlink()
    result = run(sandbox, stdin=f"destroy {ACCOUNT}\n")
    assert result.returncode == 1
    assert "Missing infra/detector/detector.auto.tfvars" in result.stderr
    assert len(calls(sandbox)) == 1


def test_destroys_in_the_safe_order_emptying_each_bucket_first(
    sandbox: dict[str, object],
) -> None:
    result = run(sandbox, stdin=f"destroy {ACCOUNT}\n")
    assert result.returncode == 0, result.stderr
    log = calls(sandbox)
    interesting = [
        line
        for line in log
        if "destroy" in line or "empty_bucket" in line or "ssm" in line or "build_lambda" in line
    ]
    assert interesting == [
        f"uv run --quiet python scripts/empty_bucket.py clickops-sandbox-{ACCOUNT}",
        "terraform -chdir=infra/sandbox destroy",
        "build_lambda",
        f"uv run --quiet python scripts/empty_bucket.py clickops-trail-{ACCOUNT}",
        "terraform -chdir=infra/detector destroy",
        "aws ssm delete-parameter --name /clickops/slack-webhook --region ap-south-1",
        f"uv run --quiet python scripts/empty_bucket.py clickops-tfstate-{ACCOUNT}",
        "terraform -chdir=infra/bootstrap destroy",
    ]


def test_bootstrap_is_initialised_with_local_state(sandbox: dict[str, object]) -> None:
    run(sandbox, stdin=f"destroy {ACCOUNT}\n")
    log = calls(sandbox)
    assert "terraform -chdir=infra/bootstrap init -input=false" in log
    assert "terraform -chdir=infra/sandbox init -input=false -backend-config=backend.hcl" in log
    assert "terraform -chdir=infra/detector init -input=false -backend-config=backend.hcl" in log


def test_existing_zip_is_not_rebuilt(sandbox: dict[str, object]) -> None:
    dist = Path(str(sandbox["work"])) / "dist"
    dist.mkdir()
    (dist / "clickops-detector.zip").write_text("")
    run(sandbox, stdin=f"destroy {ACCOUNT}\n")
    assert "build_lambda" not in calls(sandbox)


def test_destroy_args_are_passed_through(sandbox: dict[str, object]) -> None:
    run(sandbox, stdin=f"destroy {ACCOUNT}\n", TF_DESTROY_ARGS="-auto-approve")
    destroys = [line for line in calls(sandbox) if " destroy" in line]
    assert destroys and all(line.endswith("-auto-approve") for line in destroys)


def test_a_missing_ssm_parameter_does_not_stop_the_teardown(sandbox: dict[str, object]) -> None:
    result = run(sandbox, stdin=f"destroy {ACCOUNT}\n", STUB_SSM_FAIL="1")
    assert result.returncode == 0
    assert "was already gone" in result.stdout
    assert calls(sandbox)[-1] == "terraform -chdir=infra/bootstrap destroy"


def test_a_failed_terraform_destroy_stops_before_later_roots(sandbox: dict[str, object]) -> None:
    fail = Path(str(sandbox["work"])).parent / "bin" / "terraform"
    fail.write_text(
        STUB.replace(
            "exit 0", '[ "$2" = destroy ] && [ "$1" = -chdir=infra/detector ] && exit 1\nexit 0'
        )
    )
    result = run(sandbox, stdin=f"destroy {ACCOUNT}\n")
    assert result.returncode != 0
    log = calls(sandbox)
    assert "terraform -chdir=infra/detector destroy" in log
    assert not any("bootstrap" in line or "tfstate" in line for line in log)


def test_makefile_target_runs_the_script() -> None:
    makefile = (ROOT / "Makefile").read_text()
    assert "destroy:\n\t./scripts/destroy.sh" in makefile
    assert "destroy" in makefile.splitlines()[0]
