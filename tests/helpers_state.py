"""Build small Terraform state indexes for comparator tests."""

from __future__ import annotations

from typing import Any

from clickops.state import StateIndex, build_index


def resource(type_: str, name: str, /, **attrs: Any) -> dict[str, Any]:
    return {
        "mode": "managed",
        "type": type_,
        "name": name,
        "provider": 'provider["registry.terraform.io/hashicorp/aws"]',
        "instances": [{"attributes": attrs}],
    }


def index_of(*resources: dict[str, Any]) -> StateIndex:
    return build_index([{"version": 4, "resources": list(resources)}])
