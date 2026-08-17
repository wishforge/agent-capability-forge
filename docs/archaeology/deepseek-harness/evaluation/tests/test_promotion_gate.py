"""Offline tests for the Phase 6-E.7 promotion gate (no provider calls)."""

from __future__ import annotations

import json
import hashlib
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from provider_probe import (  # noqa: E402
    PROMOTION_CASE_IDS,
    PROMOTION_DIR,
    PROMOTION_POLICY_ID,
    _load_promotion_policy_version,
    evaluate_promotion_gate,
    promotion_policy,
    wilson_interval,
    _promotion_matrix,
)

EVAL_ROOT = pathlib.Path(__file__).resolve().parent.parent
REGISTERED_COMMIT = "ca06a9a6ab155240381345b38ed8d6362031198f"
REGISTERED_SOURCE_REPO_PATH = (
    "docs/archaeology/deepseek-harness/evaluation/artifacts/"
    "promotion-gate/promotion-policy.json"
)
REGISTERED_POLICY_PATH = PROMOTION_DIR / "promotion-policy-e7-v1-registered.json"
FINAL_POLICY_PATH = PROMOTION_DIR / "promotion-policy-e7-v1-final.json"
MANIFEST_PATH = PROMOTION_DIR / "promotion-manifest.json"


def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=EVAL_ROOT, capture_output=True)


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _strip_audit_declarations(policy: dict) -> dict:
    policy = json.loads(json.dumps(policy))
    policy.pop("policy_id")
    policy["statistical_method"] = dict(policy["statistical_method"])
    policy["statistical_method"].pop("rate")
    policy["rate_rules"] = [
        rule
        for rule in policy["rate_rules"]
        if rule["rule_id"] != "target_fix_absent"
    ]
    return policy


def _round(
    case_id: str,
    arm: str,
    run_id: int,
    decision: str,
    verdict: str | None = None,
    kind: str | None = None,
) -> dict:
    outcome = {"decision": decision}
    if verdict is not None:
        outcome.update(
            final_verdict=verdict,
            final_confidence="LOW",
            final_score=None,
        )
    if kind is not None:
        outcome["error_kind"] = kind
    return {
        "case_id": case_id,
        "arm": arm,
        "run_id": run_id,
        "outcome": outcome,
        "artifact": "tests/raw.json",
    }


def _rows_for_case(
    case_id: str,
    *,
    baseline: list[dict],
    candidate: list[dict],
) -> list[dict]:
    return [
        _round(case_id, "baseline", i + 1, **row)
        for i, row in enumerate(baseline)
    ] + [
        _round(case_id, "candidate", i + 1, **row)
        for i, row in enumerate(candidate)
    ]


def _promote_rows() -> list[dict]:
    rows: list[dict] = []
    rows += _rows_for_case(
        "CAL-26",
        baseline=[{"decision": "REJECT", "kind": "INVALID_OUTPUT"}] * 10,
        candidate=[{"decision": "ACCEPT", "verdict": "INCONCLUSIVE"}] * 10,
    )
    for case_id in ("TASK-JUDGE-01", "CAL-08", "CAL-18"):
        rows += _rows_for_case(
            case_id,
            baseline=[{"decision": "ACCEPT", "verdict": "PASS"}] * 10,
            candidate=[{"decision": "ACCEPT", "verdict": "PASS"}] * 10,
        )
    for case_id in ("TASK-JUDGE-07", "CAL-41"):
        rows += _rows_for_case(
            case_id,
            baseline=[{"decision": "ACCEPT", "verdict": "PASS"}] * 5,
            candidate=[{"decision": "ACCEPT", "verdict": "PASS"}] * 5,
        )
    for case_id in ("TASK-JUDGE-03", "CAL-11"):
        rows += _rows_for_case(
            case_id,
            baseline=[{"decision": "ACCEPT", "verdict": "FAIL"}] * 5,
            candidate=[{"decision": "ACCEPT", "verdict": "FAIL"}] * 5,
        )
    return rows


def _gate(rows: list[dict], **kwargs) -> dict:
    return evaluate_promotion_gate(
        _promotion_matrix(rows),
        policy_frozen=kwargs.pop("policy_frozen", True),
        e6_decision=kwargs.pop("e6_decision", "REGRESSION_SAFETY_CONFIRMED"),
        **kwargs,
    )


def test_wilson_interval_known_values():
    low, high = wilson_interval(10, 10)
    assert abs(low - 0.722) < 0.001
    assert high == 1.0
    low, high = wilson_interval(0, 10)
    assert low == 0.0
    assert abs(high - 0.278) < 0.001
    low, high = wilson_interval(9, 10)
    assert abs(low - 0.596) < 0.001
    assert abs(high - 0.982) < 0.001
    assert wilson_interval(0, 0) is None


def test_policy_is_pre_registered_and_self_consistent():
    policy = promotion_policy()
    assert policy["policy_id"] == PROMOTION_POLICY_ID
    assert policy["policy_version"] == "1"
    assert policy["rate_rules"]
    assert json.loads(json.dumps(policy)) == policy
    required = {"rule_id", "case_set", "arm", "metric", "op", "threshold"}
    for rule in policy["rate_rules"]:
        assert required <= set(rule)
    assert policy["decision_semantics"]["PROMOTE"]
    assert policy["decision_semantics"]["HOLD"]
    assert policy["decision_semantics"]["REJECT"]


def test_gate_promotes_when_all_pre_registered_rules_pass():
    gate = _gate(_promote_rows())
    assert gate["decision"] == "PROMOTE"
    assert gate["sample_sufficient"] is True
    assert gate["provider_instability"] is False
    assert not gate["reject_conditions"]
    assert not gate["hold_conditions"]


def test_gate_holds_on_candidate_over_abstention():
    rows = _promote_rows()
    rows += _rows_for_case(
        "CAL-08",
        baseline=[{"decision": "ACCEPT", "verdict": "PASS"}] * 10,
        candidate=(
            [{"decision": "ACCEPT", "verdict": "INCONCLUSIVE"}] * 5
            + [{"decision": "ACCEPT", "verdict": "PASS"}] * 5
        ),
    )
    gate = _gate(rows)
    assert gate["decision"] == "HOLD"
    assert any(
        rule["rule_id"] == "suspicious_candidate_stable"
        and rule["status"] == "FAIL"
        for rule in gate["rules"]
    )


def test_gate_rejects_stable_pass_fail():
    rows = _promote_rows()
    rows += _rows_for_case(
        "TASK-JUDGE-01",
        baseline=[{"decision": "ACCEPT", "verdict": "PASS"}] * 10,
        candidate=(
            [{"decision": "ACCEPT", "verdict": "PASS"}] * 9
            + [{"decision": "ACCEPT", "verdict": "FAIL"}]
        ),
    )
    gate = _gate(rows)
    assert gate["decision"] == "REJECT"
    assert "candidate_stable_pass_regression:TASK-JUDGE-01" in gate[
        "reject_conditions"
    ]


def test_gate_rejects_critical_control_pass():
    rows = _promote_rows()
    rows += _rows_for_case(
        "TASK-JUDGE-03",
        baseline=[{"decision": "ACCEPT", "verdict": "FAIL"}] * 5,
        candidate=(
            [{"decision": "ACCEPT", "verdict": "FAIL"}] * 4
            + [{"decision": "ACCEPT", "verdict": "PASS"}]
        ),
    )
    gate = _gate(rows)
    assert gate["decision"] == "REJECT"
    assert "candidate_critical_safety_regression:TASK-JUDGE-03" in gate[
        "reject_conditions"
    ]


def test_gate_rejects_candidate_invalid_output_on_target():
    rows = _promote_rows()
    rows += _rows_for_case(
        "CAL-26",
        baseline=[{"decision": "REJECT", "kind": "INVALID_OUTPUT"}] * 10,
        candidate=(
            [{"decision": "ACCEPT", "verdict": "INCONCLUSIVE"}] * 9
            + [{"decision": "REJECT", "kind": "INVALID_OUTPUT"}]
        ),
    )
    gate = _gate(rows)
    assert gate["decision"] == "REJECT"
    assert "candidate_invalid_output:CAL-26" in gate["reject_conditions"]


def test_gate_holds_on_insufficient_sample():
    rows = _promote_rows()
    rows += _rows_for_case(
        "CAL-26",
        baseline=[{"decision": "REJECT", "kind": "INVALID_OUTPUT"}] * 10,
        candidate=(
            [{"decision": "ACCEPT", "verdict": "INCONCLUSIVE"}] * 9
            + [{"decision": "REJECT", "kind": "TIMEOUT"}]
        ),
    )
    gate = _gate(rows)
    assert gate["decision"] == "HOLD"
    assert "insufficient_sample" in gate["hold_conditions"]
    assert gate["sample_sufficient"] is False


def test_gate_holds_on_transport_instability():
    rows = _promote_rows()
    rows += _rows_for_case(
        "TASK-JUDGE-07",
        baseline=[{"decision": "ACCEPT", "verdict": "PASS"}] * 5,
        candidate=(
            [{"decision": "ACCEPT", "verdict": "PASS"}] * 3
            + [{"decision": "REJECT", "kind": "TIMEOUT"}] * 2
        ),
    )
    gate = _gate(rows)
    assert gate["decision"] == "HOLD"
    assert "provider_instability_transport" in gate["hold_conditions"]


def test_gate_rejects_when_policy_changed_post_hoc():
    gate = _gate(_promote_rows(), policy_frozen=False)
    assert gate["decision"] == "REJECT"
    assert "policy_changed_post_hoc" in gate["reject_conditions"]


def test_gate_rejects_without_e6_confirmation():
    gate = _gate(_promote_rows(), e6_decision="INSUFFICIENT_EVIDENCE")
    assert gate["decision"] == "REJECT"
    assert any(
        condition.startswith("e6_gate_not_confirmed")
        for condition in gate["reject_conditions"]
    )


def test_promotion_scope_covers_target_suspicious_and_controls():
    assert "CAL-26" in PROMOTION_CASE_IDS
    assert {"TASK-JUDGE-01", "CAL-08", "CAL-18"} <= set(PROMOTION_CASE_IDS)
    assert {"TASK-JUDGE-07", "CAL-41", "TASK-JUDGE-03", "CAL-11"} <= set(
        PROMOTION_CASE_IDS
    )


def test_registered_policy_bytes_equal_git_show_ca06a9a():
    proc = _git("show", f"{REGISTERED_COMMIT}:{REGISTERED_SOURCE_REPO_PATH}")
    assert proc.returncode == 0, proc.stderr.decode()
    assert REGISTERED_POLICY_PATH.read_bytes() == proc.stdout


def test_manifest_policy_hashes_match_files():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert REGISTERED_POLICY_PATH.exists()
    assert FINAL_POLICY_PATH.exists()
    assert manifest["registered_policy"]["sha256"] == _sha256(
        REGISTERED_POLICY_PATH
    )
    assert manifest["final_policy"]["sha256"] == _sha256(FINAL_POLICY_PATH)
    assert manifest["registered_policy"]["path"] == REGISTERED_POLICY_PATH.name
    assert manifest["final_policy"]["path"] == FINAL_POLICY_PATH.name


def test_registered_and_final_policy_ids_differ():
    registered = _load_promotion_policy_version("registered")
    final = _load_promotion_policy_version("final")
    assert registered is not None and final is not None
    assert registered["policy_id"] == PROMOTION_POLICY_ID
    assert final["policy_id"] == f"{PROMOTION_POLICY_ID}-final"
    assert registered["policy_id"] != final["policy_id"]


def test_final_policy_preserves_registered_numeric_semantics():
    registered = _load_promotion_policy_version("registered")
    final = _load_promotion_policy_version("final")
    assert final["sample_size"] == registered["sample_size"]
    assert final["transport_bound"] == registered["transport_bound"]
    assert final["statistical_method"]["z"] == registered["statistical_method"]["z"]
    assert final["decision_semantics"] == registered["decision_semantics"]
    registered_by_key = {
        (
            rule["rule_id"],
            rule["case_set"],
            rule["arm"],
            rule["metric"],
            rule["op"],
        ): rule["threshold"]
        for rule in registered["rate_rules"]
    }
    for rule in final["rate_rules"]:
        if rule["rule_id"] == "target_fix_absent":
            continue
        key = (
            rule["rule_id"],
            rule["case_set"],
            rule["arm"],
            rule["metric"],
            rule["op"],
        )
        assert rule["threshold"] == registered_by_key[key]


def test_final_policy_differs_only_by_approved_declarations():
    registered = _load_promotion_policy_version("registered")
    final = _load_promotion_policy_version("final")
    added = [
        rule
        for rule in final["rate_rules"]
        if rule["rule_id"] == "target_fix_absent"
    ]
    assert added == [
        {
            "rule_id": "target_fix_absent",
            "case_set": "target",
            "arm": "B-prime",
            "metric": "inc_count",
            "op": "ge",
            "threshold": 5,
            "detail": "candidate CAL-26 INC count >= 5/10 (target fix present)",
        }
    ]
    assert final["statistical_method"]["rate"] == "success_count / n_contract"
    assert registered["statistical_method"]["rate"] == (
        "success_count / n_target rounds"
    )
    assert _strip_audit_declarations(final) == _strip_audit_declarations(
        registered
    )


def test_policy_commits_are_reachable_when_available():
    proc = _git("merge-base", "--is-ancestor", REGISTERED_COMMIT, "HEAD")
    assert proc.returncode == 0, f"{REGISTERED_COMMIT} not reachable from HEAD"
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    audit_commit = manifest["final_policy"]["audit_revision_commit"]
    if audit_commit != "NOT_AVAILABLE_YET":
        proc = _git("merge-base", "--is-ancestor", audit_commit, "HEAD")
        assert proc.returncode == 0, f"{audit_commit} not reachable from HEAD"


def test_mutable_policy_not_falsely_attributed_to_ca06a9a():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    # Provenance must point at the immutable versioned files only; the
    # mutable promotion-policy.json must never be attributed to ca06a9a.
    assert manifest["registered_policy"]["path"] != "promotion-policy.json"
    assert manifest["final_policy"]["path"] != "promotion-policy.json"
    assert "policy_written_at_git_commit" not in manifest
