"""Lambda function settings: live versus Terraform state.

Environment variable values are never read into the result, only the names.
"""

from __future__ import annotations

import boto3
from botocore.exceptions import ClientError

from clickops.compare.base import Comparison, changed
from clickops.models import ResourceRef
from clickops.state import StateIndex, StateResource


def _state_env_names(state: StateResource) -> list[str]:
    names: set[str] = set()
    for block in state.attributes.get("environment") or []:
        names.update((block.get("variables") or {}).keys())
    return sorted(names)


def compare(ref: ResourceRef, index: StateIndex, state: StateResource) -> Comparison:
    lam = boto3.client("lambda", region_name=ref.region)
    try:
        live = lam.get_function_configuration(FunctionName=ref.id)
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ResourceNotFoundException":
            return Comparison(exists=False)
        raise
    attrs = state.attributes
    live_env = sorted((live.get("Environment") or {}).get("Variables", {}).keys())
    changes = changed("runtime", attrs.get("runtime"), live.get("Runtime"))
    changes += changed("handler", attrs.get("handler"), live.get("Handler"))
    changes += changed("memory_size", attrs.get("memory_size"), live.get("MemorySize"))
    changes += changed("timeout", attrs.get("timeout"), live.get("Timeout"))
    changes += changed("role", attrs.get("role"), live.get("Role"))
    changes += changed("code_sha256", attrs.get("source_code_hash"), live.get("CodeSha256"))
    changes += changed("environment_variable_names", _state_env_names(state), live_env)
    return Comparison(changes=changes)
