"""Phase 8.3 tests: every illegal storage / trust / TOCTOU case -> ADOPTION_BLOCKED."""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pytest  # noqa: E402

from validate_authority_storage_hardening import (  # noqa: E402
    AuthorityStore,
    authority_id_for,
    delete,
    issue,
    revoke,
    update,
    verify_activation,
    verify_at_mount,
)

DIGEST_A = "sha256:aaa"
DIGEST_B = "sha256:bbb"
DEC = "dec-1"
AID = authority_id_for("cand-1", "v1", DEC)


def valid_record(**overrides) -> dict:
    record = {
        "authority_id": AID,
        "candidate_id": "cand-1",
        "candidate_version": "v1",
        "promotion_decision_id": DEC,
        "evaluation_run_id": "run-1",
        "policy_version": "1",
        "artifact_digest": DIGEST_A,
        "provenance": {
            "policy": True,
            "evidence_manifest": True,
            "run_ids": ["run-1"],
            "immutable_artifact_refs": ["artifact:" + DIGEST_A],
        },
        "issuer_id": "issuer-1",
        "decision_id": DEC,
        "issued_at": "2026-08-17T01:00:00Z",
        "status": "ISSUED",
    }
    record.update(overrides)
    return record


def store() -> AuthorityStore:
    return AuthorityStore(trusted_issuers=frozenset({"issuer-1"}))


def assert_blocked(report: dict, code: str) -> None:
    assert report["verdict"] == "ADOPTION_BLOCKED", report
    assert report["code"] == code, report


def revoke_event(revocation_id: str, status: str) -> dict:
    return {
        "revocation_id": revocation_id,
        "authority_id": AID,
        "candidate_id": "cand-1",
        "candidate_version": "v1",
        "promotion_decision_id": DEC,
        "status": status,
        "reason": "test",
        "issuer_id": "issuer-1",
        "revoked_at": "2026-08-17T02:00:00Z",
    }


def test_valid_issue_verify_and_mount_allow() -> None:
    s = store()
    assert issue(s, valid_record())["verdict"] == "ALLOW"
    assert verify_activation(s, s.snapshot(), AID, DIGEST_A)["verdict"] == "ALLOW"
    assert verify_at_mount(s, AID, DIGEST_A)["verdict"] == "ALLOW"


def test_authority_overwrite_attempt_blocked() -> None:
    s = store()
    assert issue(s, valid_record())["verdict"] == "ALLOW"
    assert_blocked(issue(s, valid_record(artifact_digest=DIGEST_B)),
                   "AUTHORITY_BINDING_MISMATCH")


def test_authority_delete_and_recreate_blocked() -> None:
    s = store()
    assert issue(s, valid_record())["verdict"] == "ALLOW"
    assert_blocked(delete(s, AID), "AUTHORITY_DELETE_BLOCKED")
    assert_blocked(issue(s, valid_record(artifact_digest=DIGEST_B)),
                   "AUTHORITY_BINDING_MISMATCH")


@pytest.mark.parametrize("status", ["REVOKED", "SUPERSEDED"])
def test_revoked_or_superseded_authority_blocked(status: str) -> None:
    s = store()
    assert issue(s, valid_record())["verdict"] == "ALLOW"
    assert revoke(s, revoke_event("rev-1", status))["verdict"] == "ALLOW"
    assert_blocked(verify_activation(s, s.snapshot(), AID, DIGEST_A),
                   "REVOKED_DECISION")
    assert_blocked(verify_at_mount(s, AID, DIGEST_A), "REVOKED_DECISION")


def test_authority_status_revoked_blocks() -> None:
    s = store()
    assert issue(s, valid_record())["verdict"] == "ALLOW"
    s._authorities[AID]["status"] = "REVOKED"
    assert_blocked(verify_at_mount(s, AID, DIGEST_A), "REVOKED_DECISION")


def test_unknown_issuer_blocked() -> None:
    s = store()
    assert_blocked(issue(s, valid_record(issuer_id="issuer-unknown")),
                   "UNTRUSTED_ISSUER")
    assert_blocked(revoke(s, revoke_event("rev-1", "REVOKED")
                          | {"issuer_id": "issuer-unknown"}),
                   "UNTRUSTED_ISSUER")


def test_forged_authority_id_blocked() -> None:
    s = store()
    assert_blocked(issue(s, valid_record(authority_id="auth-forged")),
                   "AUTHORITY_ID_MISMATCH")


def test_authority_binding_mutation_blocked() -> None:
    s = store()
    assert issue(s, valid_record())["verdict"] == "ALLOW"
    assert_blocked(update(s, AID, {"candidate_id": "cand-2"}),
                   "AUTHORITY_BINDING_MUTATION")


def test_concurrent_issue_cas_one_wins() -> None:
    s = store()
    assert issue(s, valid_record(), expected_version=0)["verdict"] == "ALLOW"
    # second writer still holds the old snapshot -> CAS rejects it
    assert_blocked(issue(s, valid_record(artifact_digest=DIGEST_B),
                         expected_version=0), "STALE_WRITE")
    # fresh reader that re-reads the store sees the conflict and is blocked
    assert_blocked(issue(s, valid_record(artifact_digest=DIGEST_B),
                         expected_version=1), "AUTHORITY_BINDING_MISMATCH")


def test_stale_read_recheck_blocked() -> None:
    s = store()
    assert issue(s, valid_record())["verdict"] == "ALLOW"
    stale = s.snapshot()
    assert verify_activation(s, stale, AID, DIGEST_A)["verdict"] == "ALLOW"
    assert revoke(s, revoke_event("rev-1", "REVOKED"))["verdict"] == "ALLOW"
    # activation may have used the stale snapshot, but mount rechecks latest
    assert_blocked(verify_at_mount(s, AID, DIGEST_A), "REVOKED_DECISION")


def test_artifact_replacement_after_validation_blocked() -> None:
    s = store()
    assert issue(s, valid_record())["verdict"] == "ALLOW"
    assert verify_activation(s, s.snapshot(), AID, DIGEST_A)["verdict"] == "ALLOW"
    # artifact replaced between validation and mount
    assert_blocked(verify_at_mount(s, AID, DIGEST_B), "ARTIFACT_DIGEST_MISMATCH")
