"""Resolvers turn a normalized event into the resources it changed.

Each service module exposes ``resolve(event) -> list[ResourceRef]`` and is registered here by the
CloudTrail event source.
"""

from __future__ import annotations

import logging

from clickops.models import NormalizedEvent, ResourceRef
from clickops.resolvers import ec2, iam, lambda_fn, route53, s3, sg
from clickops.resolvers.base import Resolver

logger = logging.getLogger("clickops")

# Event source -> resolvers. ec2.amazonaws.com carries both security group and instance events.
REGISTRY: dict[str, list[Resolver]] = {
    "ec2.amazonaws.com": [sg.resolve, ec2.resolve],
    "iam.amazonaws.com": [iam.resolve],
    "s3.amazonaws.com": [s3.resolve],
    "lambda.amazonaws.com": [lambda_fn.resolve],
    "route53.amazonaws.com": [route53.resolve],
}

_logged_unknown: set[tuple[str, str]] = set()


def resolve(event: NormalizedEvent) -> list[ResourceRef]:
    """Resources changed by the event. An unwatched event gives an empty list, never an error."""
    refs: list[ResourceRef] = []
    for resolver in REGISTRY.get(event.source, []):
        refs.extend(resolver(event))
    if not refs:
        ident = (event.source, event.name)
        if ident not in _logged_unknown:
            _logged_unknown.add(ident)
            logger.debug("no resolver output for %s %s", event.source, event.name)
    return refs
