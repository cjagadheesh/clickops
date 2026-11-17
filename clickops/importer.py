"""``clickops import``: write Terraform ``import`` blocks and let Terraform draft the config."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from clickops.resolvers.base import ROUTE53_RECORD, STATE_TYPES
from clickops.scan import ShadowResource

PLAN_SUMMARY = re.compile(r"Plan: \d+ to import.*")
PROVIDER_VERSION = "~> 5.81"

Runner = Callable[[Sequence[str], Path], "subprocess.CompletedProcess[str]"]


class ImporterError(Exception):
    """Terraform failed in a way that leaves nothing useful to show beyond its message."""


class TerraformMissing(ImporterError):
    """The terraform binary could not be run."""


@dataclass
class ImportResult:
    directory: Path
    imports_path: Path
    generated_path: Path | None = None
    plan_summary: str = ""
    validate_ok: bool | None = None
    errors: list[str] = field(default_factory=list)


# --- import blocks -----------------------------------------------------------------------------


def tf_type(resource: ShadowResource) -> str:
    return STATE_TYPES[resource.type]


def import_id(resource: ShadowResource) -> str:
    """The ID Terraform's import expects for this resource type.

    Names and ARNs are already the provider's import IDs for roles, policies, buckets, functions
    and instances; a record's ID is ``ZONEID_name_TYPE``; a security group rule would use its
    ``sgr-`` ID.
    """
    return resource.id


def tf_name(resource: ShadowResource, taken: set[tuple[str, str]]) -> str:
    """A valid, unique Terraform resource name derived from the resource's name or ID."""
    raw = resource.name or resource.id
    if resource.type == ROUTE53_RECORD:
        raw = f"{resource.name}_{resource.id.rsplit('_', 1)[-1]}"
    name = re.sub(r"[^a-z0-9_]+", "_", raw.lower()).strip("_") or "imported"
    if not re.match(r"[a-z_]", name):
        name = f"r_{name}"
    unique, n = name, 2
    while (tf_type(resource), unique) in taken:
        unique, n = f"{name}_{n}", n + 1
    taken.add((tf_type(resource), unique))
    return unique


def render_imports(resources: Sequence[ShadowResource]) -> str:
    taken: set[tuple[str, str]] = set()
    blocks = []
    for resource in resources:
        name = tf_name(resource, taken)
        blocks.append(
            "import {\n"
            f"  to = {tf_type(resource)}.{name}\n"
            f"  id = {json.dumps(import_id(resource))}\n"
            "}\n"
        )
    return "\n".join(blocks)


def write_imports(
    resources: Sequence[ShadowResource], base: Path = Path("imports"), now: datetime | None = None
) -> tuple[Path, Path]:
    """Write ``imports/<timestamp>/imports.tf``; returns the directory and the file."""
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    directory = base / stamp
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "imports.tf"
    path.write_text(render_imports(resources))
    return directory, path


# --- terraform ---------------------------------------------------------------------------------


def providers_tf(region: str) -> str:
    return (
        "terraform {\n"
        '  required_version = ">= 1.10"\n\n'
        "  required_providers {\n"
        "    aws = {\n"
        '      source  = "hashicorp/aws"\n'
        f'      version = "{PROVIDER_VERSION}"\n'
        "    }\n"
        "  }\n"
        "}\n\n"
        'provider "aws" {\n'
        f'  region = "{region}"\n'
        "}\n"
    )


def run_command(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(command), cwd=cwd, capture_output=True, text=True, timeout=900, check=False
        )
    except FileNotFoundError as exc:
        raise TerraformMissing(f"cannot run {command[0]}: install Terraform 1.10 or newer") from exc


def _tail(text: str, lines: int = 12) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


def _validate_errors(stdout: str) -> list[str]:
    try:
        diagnostics = json.loads(stdout).get("diagnostics", [])
    except ValueError:
        return [_tail(stdout) or "terraform validate produced no output"]
    return [
        f"{d.get('summary', 'error')}: {d.get('detail', '').strip()}".strip(": ")
        for d in diagnostics
        if d.get("severity") == "error"
    ]


def with_error_header(generated: str, errors: Sequence[str]) -> str:
    header = [
        "# clickops: `terraform validate` reported errors in this generated config.",
        "# It is a starting point; fix these before using it:",
    ]
    for error in errors:
        header.append("#   - " + " ".join(error.split()))
    return "\n".join(header) + "\n\n" + generated


def generate_config(
    imports_dir: Path,
    region: str,
    terraform: str = "terraform",
    runner: Runner | None = None,
) -> ImportResult:
    """Run init, ``plan -generate-config-out`` and validate in a temporary directory.

    The draft ``generated.tf`` is kept next to ``imports.tf``; nothing is applied.
    """
    runner = runner or run_command
    imports_path = imports_dir / "imports.tf"
    result = ImportResult(directory=imports_dir, imports_path=imports_path)
    with tempfile.TemporaryDirectory(prefix="clickops-import-") as tmp:
        work = Path(tmp)
        shutil.copy(imports_path, work / "imports.tf")
        (work / "providers.tf").write_text(providers_tf(region))

        init = runner([terraform, "init", "-input=false", "-no-color"], work)
        if init.returncode != 0:
            raise ImporterError(f"terraform init failed:\n{_tail(init.stderr or init.stdout)}")
        plan = runner(
            [terraform, "plan", "-input=false", "-no-color", "-generate-config-out=generated.tf"],
            work,
        )
        if plan.returncode != 0:
            raise ImporterError(f"terraform plan failed:\n{_tail(plan.stderr or plan.stdout)}")
        if match := PLAN_SUMMARY.search(plan.stdout):
            result.plan_summary = match.group(0)

        generated = work / "generated.tf"
        if not generated.exists():
            raise ImporterError("terraform plan did not generate any configuration")
        validate = runner([terraform, "validate", "-json", "-no-color"], work)
        text = generated.read_text()
        if validate.returncode != 0:
            result.validate_ok = False
            result.errors = _validate_errors(validate.stdout) or [_tail(validate.stderr)]
            text = with_error_header(text, result.errors)
        else:
            result.validate_ok = True
        result.generated_path = imports_dir / "generated.tf"
        result.generated_path.write_text(text)
    return result
