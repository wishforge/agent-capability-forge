"""Phase 5-F Core Extensions: ExecutionAttempt + BackendEventRef + BackendMetadata.

These are extension semantics only (unified-agent-runtime-core-contract-v1
§13/§14/§15): the semantic core never reads them to decide Session/Turn/Step/
Ownership/Causality. Adapters translate backend facts into these neutral
containers; backend-specific fields never enter core objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

EXACT = "EXACT"
SYNTHETIC = "SYNTHETIC"
LOSSY = "LOSSY"
ADAPTER = "ADAPTER"
BACKEND_SPECIFIC = "BACKEND_SPECIFIC"
ADAPTER_DERIVED = "ADAPTER_DERIVED"

RUNNING = "RUNNING"
SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"
ABORTED = "ABORTED"


@dataclass(frozen=True, slots=True)
class InitiatorRef:
    """Stable logical initiator reference; never a Python object.

    Phase 5-H: the ref is the durable attribution identity. `source` records
    that the ref is assigned by the Unified runtime/adapter overlay rather
    than a backend-native identity. `parent_ref` is only written when real
    parent/child evidence exists.
    """

    ref: str
    source: str = ADAPTER_DERIVED
    parent_ref: str | None = None


@dataclass(frozen=True, slots=True)
class OwnerRef:
    """Durable owner reference: owner_type + owner_id (never a runtime object).

    Minimal types: capability / scope / effect. The current runtime derives
    owner_ref from ToolRegistration.owner and treats it as a capability id;
    that derivation is recorded in the assumptions doc, not claimed as a
    backend-native fact.
    """

    owner_type: str
    owner_id: str


@dataclass(frozen=True, slots=True)
class BackendEventRef:
    """Pointer to one raw backend event; never a copy of the raw event."""

    backend: str
    event_id: str | None = None
    event_type: str | None = None
    reference: dict[str, Any] | None = None
    quality: str = EXACT


@dataclass(frozen=True, slots=True)
class BackendMetadata:
    """Backend mapping/lossiness container. Core never reads it for decisions."""

    backend: str
    mapping_quality: str = ADAPTER
    missing_semantics: tuple[str, ...] = ()
    backend_event_ref: BackendEventRef | None = None
    backend_metadata: dict[str, Any] = field(default_factory=dict)
    source_event_type: str | None = None

    @property
    def raw_event_ref(self) -> dict[str, Any] | None:
        ref = self.backend_event_ref
        return ref.reference if ref is not None else None


@dataclass(frozen=True, slots=True)
class ExecutionAttempt:
    """One attempt of one logical Execution (1..N attempts per execution)."""

    execution_id: str
    attempt_id: str
    attempt_number: int
    parent_execution_id: str | None = None
    reason: str | None = None
    status: str = RUNNING
    started_at: str | None = None
    ended_at: str | None = None
    backend_event_ref: BackendEventRef | None = None
    backend_metadata: BackendMetadata | None = None


@dataclass(slots=True)
class Execution:
    """Runtime container: one logical execution with its attempts."""

    execution_id: str
    attempts: list[ExecutionAttempt] = field(default_factory=list)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "ABORTED",
    "ADAPTER",
    "ADAPTER_DERIVED",
    "BACKEND_SPECIFIC",
    "BackendEventRef",
    "BackendMetadata",
    "EXACT",
    "Execution",
    "ExecutionAttempt",
    "FAILED",
    "InitiatorRef",
    "LOSSY",
    "OwnerRef",
    "RUNNING",
    "SUCCEEDED",
    "SYNTHETIC",
    "utc_now",
]
