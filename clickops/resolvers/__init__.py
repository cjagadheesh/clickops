"""Resolvers turn a normalized event into the resources it changed.

Each service module exposes ``resolve(event) -> list[ResourceRef]`` and is registered here by the
CloudTrail event source.
"""

from __future__ import annotations

import logging

from clickops.models import NormalizedEvent, ResourceRef
from clickops.resolvers import iam, sg
from clickops.resolvers.base import Resolver

logger = logging.getLogger("clickops")

# Event source -> resolver. ec2.amazonaws.com also carries instance events (added later).
REGISTRY: dict[str, Resolver] = {
    "ec2.amazonaws.com": sg.resolve,
    "iam.amazonaws.com": iam.resolve,
}


def resolve(event: NormalizedEvent) -> list[ResourceRef]:
    """Resources changed by the event; an event no resolver knows gives an empty list."""
    resolver = REGISTRY.get(event.source)
    return resolver(event) if resolver else []
