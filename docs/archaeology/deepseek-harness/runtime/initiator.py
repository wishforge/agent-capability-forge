"""Phase 4-A ambient initiator: process-local causal identity.

contextvars.ContextVar propagates through same-process async chains only.
It is not persistent lineage, not ownership, not authorization (16 §1/§9).
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InitiatorContext:
    agent_id: str
    agent_name: str = ""


_current: contextvars.ContextVar[InitiatorContext | None] = contextvars.ContextVar(
    "dsah_initiator",
    default=None,
)


def current_initiator() -> InitiatorContext | None:
    return _current.get()


def require_initiator() -> InitiatorContext:
    initiator = _current.get()
    if initiator is None:
        raise RuntimeError(
            "no initiator in context: require_initiator() must run inside "
            "with_initiator()",
        )
    return initiator


@contextmanager
def with_initiator(initiator: InitiatorContext | str):
    if isinstance(initiator, str):
        initiator = InitiatorContext(initiator)
    token = _current.set(initiator)
    try:
        yield
    finally:
        _current.reset(token)
