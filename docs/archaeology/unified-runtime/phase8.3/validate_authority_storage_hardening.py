"""Phase 8.3 - minimal append-only / CAS AdoptionAuthority store model (offline proof).

This models the hardening boundary proposed in
73-authority-storage-trust-hardening.md. It is NOT the current
adoption_store.json behavior and NOT production code:

  - authority records are write-once: issue = create-if-absent keyed by
    authority_id; update / delete / recreate are blocked.
  - status changes are append-only revocation events (REVOKED / SUPERSEDED);
    the authority record itself is never rewritten.
  - every issue / revocation must carry a TrustedIssuer identity
    (issuer_id in an explicit allowlist) plus issued_at / decision_id /
    authority_id. No cryptographic signature is modeled (UNKNOWN).
  - activation verifies against a snapshot, then re-verifies at mount time
    against the latest store and the exact artifact digest.
"""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass, field

AUTHORITY_BINDING_FIELDS = (
    "candidate_id",
    "candidate_version",
    "promotion_decision_id",
    "evaluation_run_id",
    "policy_version",
    "artifact_digest",
    "provenance",
)
ISSUER_FIELDS = ("issuer_id", "issued_at", "decision_id", "authority_id")
REVOCABLE_STATUSES = ("REVOKED", "SUPERSEDED")


def authority_id_for(candidate_id: str, candidate_version: str, decision_id: str) -> str:
    raw = f"{candidate_id}|{candidate_version}|{decision_id}"
    return "auth-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def blocked(code: str, message: str) -> dict:
    return {"verdict": "ADOPTION_BLOCKED", "allowed": False,
            "code": code, "message": message}


def allowed(authority_id: str) -> dict:
    return {"verdict": "ALLOW", "allowed": True, "authority_id": authority_id}


@dataclass
class StoreView:
    version: int
    authorities: dict[str, dict]
    revocations: list[dict]


@dataclass
class AuthorityStore:
    trusted_issuers: frozenset[str]
    _authorities: dict[str, dict] = field(default_factory=dict)
    _revocations: list[dict] = field(default_factory=list)
    _version: int = 0

    def snapshot(self) -> StoreView:
        return StoreView(
            self._version,
            copy.deepcopy(self._authorities),
            copy.deepcopy(self._revocations),
        )


def _validate_record(store: AuthorityStore, record: dict) -> dict | None:
    missing = [
        f for f in AUTHORITY_BINDING_FIELDS + ISSUER_FIELDS
        if record.get(f) in (None, "", {})
    ]
    if missing:
        return blocked("REQUEST_METADATA_MISSING", f"missing={','.join(missing)}")
    if record.get("issuer_id") not in store.trusted_issuers:
        return blocked("UNTRUSTED_ISSUER", f"issuer={record.get('issuer_id')}")
    if record.get("decision_id") != record.get("promotion_decision_id"):
        return blocked(
            "AUTHORITY_BINDING_MISMATCH",
            "issuer decision_id must equal promotion_decision_id",
        )
    expected = authority_id_for(
        record.get("candidate_id"),
        record.get("candidate_version"),
        record.get("promotion_decision_id"),
    )
    if record.get("authority_id") != expected:
        return blocked(
            "AUTHORITY_ID_MISMATCH",
            f"authority_id={record.get('authority_id')} expected={expected}",
        )
    status = record.get("status")
    if status in REVOCABLE_STATUSES:
        return blocked("REVOKED_DECISION", f"authority status={status}")
    if status != "ISSUED":
        return blocked("INVALID_AUTHORITY_STATUS", f"status={status} expected=ISSUED")
    return None


def issue(store: AuthorityStore, record: dict,
          expected_version: int | None = None) -> dict:
    if expected_version is not None and expected_version != store._version:
        return blocked(
            "STALE_WRITE",
            f"expected_version={expected_version} actual={store._version}",
        )
    problem = _validate_record(store, record)
    if problem:
        return problem
    aid = record["authority_id"]
    existing = store._authorities.get(aid)
    if existing is not None:
        if existing == record:
            return allowed(aid)  # idempotent re-issue: no write
        return blocked(
            "AUTHORITY_BINDING_MISMATCH",
            f"authority={aid} exists with a different binding",
        )
    store._authorities[aid] = copy.deepcopy(record)
    store._version += 1
    return allowed(aid)


def delete(store: AuthorityStore, authority_id: str) -> dict:
    return blocked(
        "AUTHORITY_DELETE_BLOCKED",
        "write-once: delete is not a supported operation",
    )


def update(store: AuthorityStore, authority_id: str, changes: dict) -> dict:
    return blocked(
        "AUTHORITY_BINDING_MUTATION",
        "write-once: authority records are immutable",
    )


def revoke(store: AuthorityStore, event: dict,
           expected_version: int | None = None) -> dict:
    if expected_version is not None and expected_version != store._version:
        return blocked(
            "STALE_WRITE",
            f"expected_version={expected_version} actual={store._version}",
        )
    if event.get("issuer_id") not in store.trusted_issuers:
        return blocked("UNTRUSTED_ISSUER", f"issuer={event.get('issuer_id')}")
    if event.get("status") not in REVOCABLE_STATUSES:
        return blocked(
            "INVALID_AUTHORITY_STATUS",
            f"status={event.get('status')} expected=REVOKED|SUPERSEDED",
        )
    record = store._authorities.get(event.get("authority_id"))
    if record is None:
        return blocked("MISSING_AUTHORITY", f"authority={event.get('authority_id')}")
    if any(
        record.get(k) != event.get(k)
        for k in ("candidate_id", "candidate_version", "promotion_decision_id")
    ):
        return blocked(
            "AUTHORITY_BINDING_MISMATCH",
            "revocation event does not match the issued binding",
        )
    if any(r.get("revocation_id") == event.get("revocation_id")
           for r in store._revocations):
        return blocked("REVOCATION_DUPLICATE", f"revocation_id={event.get('revocation_id')}")
    store._revocations.append(copy.deepcopy(event))
    store._version += 1
    return allowed(event["authority_id"])


def verify_activation(store: AuthorityStore, view: StoreView, authority_id: str,
                      artifact_digest: str) -> dict:
    """Check before activation: the authority must exist, be trusted, be
    ISSUED, not be revoked, and bind the artifact digest being validated."""
    record = view.authorities.get(authority_id)
    if record is None:
        return blocked("MISSING_AUTHORITY", f"authority={authority_id}")
    problem = _validate_record(store, record)
    if problem:
        return problem
    if any(
        r.get("authority_id") == authority_id
        and r.get("status") in REVOCABLE_STATUSES
        for r in view.revocations
    ):
        return blocked("REVOKED_DECISION", f"authority={authority_id}")
    if record.get("artifact_digest") != artifact_digest:
        return blocked(
            "ARTIFACT_DIGEST_MISMATCH",
            f"expected={record.get('artifact_digest')} actual={artifact_digest}",
        )
    return allowed(authority_id)


def verify_at_mount(store: AuthorityStore, authority_id: str,
                    artifact_digest: str) -> dict:
    """Recheck immediately before the artifact is mounted: latest store +
    digest, so a stale snapshot or post-validation replacement fails closed."""
    return verify_activation(store, store.snapshot(), authority_id, artifact_digest)
