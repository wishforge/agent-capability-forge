"""Phase 9-A.1 - CapabilityCandidate v1 contract tests (offline, stdlib)."""

from __future__ import annotations

import unittest

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from validate_capability_candidate_contract import (
    intake,
    validate_candidate,
    governance_projection,
    SCHEMA_VERSION,
)

D = "sha256:" + "d" * 64
E = "sha256:" + "e" * 64


def manifest(forged_digest: str = E) -> dict:
    return {
        "manifest_version": "0.1",
        "capability": {"name": "csv-clean-statistical-report",
                       "description": "demo", "version": 1},
        "entrypoint": {"command": ["python", "main.py"], "workdir": "artifact"},
        "contract": {"input": {"files": ["data/*.csv"]},
                     "output": {"files": ["report.md"], "exit_code": 0}},
        "tests": [{"id": "t1", "input": {"files": ["data/data.csv"]},
                   "expected": {"files": ["report.md"]}}],
        "sandbox": {"permissions": {"network": False, "fs_write": ["/output"]},
                    "limits": {"timeout_seconds": 120, "output_bytes": 1048576}},
        "provenance": {
            "source_bundle_id": "bundle-1",
            "source_artifact_digest": D,
            "forged_artifact_digest": forged_digest,
            "forge_timestamp": "2026-08-18T00:00:00.000Z",
        },
    }


def make_candidate(**overrides) -> dict:
    cand = {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": "cand-1",
        "capability_id": "cap-1",
        "name": "csv-clean-statistical-report",
        "version": 1,
        "requester": {"kind": "human", "id": "operator-1", "request_id": "req-1"},
        "producer": {"kind": "agent", "id": "codex-artifact-builder-v0"},
        "source": {
            "source_type": "agent",
            "source_reference": "rollout:run-1",
            "resolved_revision": D,
        },
        "artifact": {"artifact_digest": E, "artifact_ref": f"artifact:{E}"},
        "manifest": manifest(),
        "provenance": {
            "created_at": "2026-08-18T00:00:00.000Z",
            "source_revision": D,
            "build_ref": "bundle:bundle-1",
            "request_id": "req-1",
        },
        "extensions": {
            "codex": {"applicability": "agent source",
                      "session_id": "sess-1", "thread_id": "thread-1"},
        },
    }
    cand.update(overrides)
    return cand


class CapabilityCandidateContractTests(unittest.TestCase):
    def test_valid_candidate_accepted(self):
        cand = make_candidate()
        self.assertEqual(intake(cand)["intake"], "INTAKE_ACCEPTED")
        self.assertEqual(validate_candidate(cand)["verdict"], "CANDIDATE_CONTRACT_VALID")

    def test_missing_candidate_identity_rejected(self):
        result = intake(make_candidate(candidate_id=None))
        self.assertEqual(result["intake"], "INTAKE_REJECTED")
        self.assertTrue(any(v["code"] == "MISSING_CORE_FIELD" for v in result["violations"]))

    def test_missing_capability_identity_rejected(self):
        cand = make_candidate()
        del cand["capability_id"]
        result = intake(cand)
        self.assertEqual(result["intake"], "INTAKE_REJECTED")
        self.assertTrue(any(v["code"] == "MISSING_CORE_FIELD" for v in result["violations"]))

    def test_missing_source_rejected(self):
        cand = make_candidate()
        del cand["source"]
        result = intake(cand)
        self.assertEqual(result["intake"], "INTAKE_REJECTED")
        self.assertTrue(any(v["code"] == "SOURCE_MISSING" for v in result["violations"]))

    def test_missing_artifact_rejected(self):
        cand = make_candidate()
        del cand["artifact"]
        result = intake(cand)
        self.assertEqual(result["intake"], "INTAKE_REJECTED")
        self.assertTrue(any(v["code"] == "ARTIFACT_MISSING" for v in result["violations"]))

    def test_missing_artifact_digest_rejected(self):
        cand = make_candidate()
        del cand["artifact"]["artifact_digest"]
        result = intake(cand)
        self.assertEqual(result["intake"], "INTAKE_REJECTED")
        self.assertTrue(any(v["code"] == "ARTIFACT_DIGEST_MISSING"
                            for v in result["violations"]))

    def test_missing_producer_rejected(self):
        cand = make_candidate()
        del cand["producer"]
        result = intake(cand)
        self.assertEqual(result["intake"], "INTAKE_REJECTED")
        self.assertTrue(any(v["code"] == "PRODUCER_MISSING" for v in result["violations"]))

    def test_requester_and_producer_are_separate(self):
        cand = make_candidate(requester={"kind": "workflow", "id": "req-flow-9"})
        self.assertEqual(intake(cand)["intake"], "INTAKE_ACCEPTED")
        projection = governance_projection(cand)
        self.assertNotEqual(projection["producer"]["id"], projection["requester"]["id"])
        self.assertIn("requester", projection)
        self.assertIn("producer", projection)

    def test_evidence_is_separate_object(self):
        cand = make_candidate(evidence={"evidence_id": "ev-1"})
        result = intake(cand)
        self.assertEqual(result["intake"], "INTAKE_REJECTED")
        self.assertTrue(any(v["code"] == "OBJECT_BOUNDARY_VIOLATION"
                            for v in result["violations"]))

    def test_policy_is_separate_object(self):
        cand = make_candidate(policy={"policy_id": "pol-1"})
        result = intake(cand)
        self.assertEqual(result["intake"], "INTAKE_REJECTED")
        self.assertTrue(any(v["code"] == "OBJECT_BOUNDARY_VIOLATION"
                            for v in result["violations"]))

    def test_decision_is_separate_object(self):
        cand = make_candidate(decision={"value": "PROMOTE"})
        result = intake(cand)
        self.assertEqual(result["intake"], "INTAKE_REJECTED")
        self.assertTrue(any(v["code"] == "OBJECT_BOUNDARY_VIOLATION"
                            for v in result["violations"]))

    def test_extension_does_not_pollute_core(self):
        polluted = make_candidate(pr_number=42)
        self.assertEqual(intake(polluted)["intake"], "INTAKE_REJECTED")
        self.assertTrue(any(v["code"] == "UNKNOWN_CORE_FIELD"
                            for v in intake(polluted)["violations"]))
        clean = make_candidate(
            extensions={"git": {"applicability": "git source", "pr_number": 42}})
        self.assertEqual(intake(clean)["intake"], "INTAKE_ACCEPTED")

    def test_git_oci_agent_source_compatibility(self):
        git_sha = "a" * 40
        sources = {
            "git": {"source_type": "git",
                    "source_reference": "https://github.com/acme/cap.git",
                    "resolved_revision": git_sha},
            "oci": {"source_type": "oci",
                    "source_reference": "registry.example/acme/cap:tag",
                    "resolved_revision": D},
            "agent": {"source_type": "agent",
                      "source_reference": "rollout:run-1",
                      "resolved_revision": D},
        }
        projections = []
        for source_type, source in sources.items():
            cand = make_candidate(source=source,
                                  extensions={source_type: {"applicability": "fixture"}})
            if source_type == "git":
                cand["provenance"]["source_revision"] = git_sha
            self.assertEqual(validate_candidate(cand)["verdict"], "CANDIDATE_CONTRACT_VALID",
                             source_type)
            projections.append(set(governance_projection(cand)))
        self.assertEqual(len(set(tuple(sorted(p)) for p in projections)), 1)

    def test_governance_independent_of_source(self):
        for source_type in ("git", "oci", "agent", "future_source_xyz"):
            cand = make_candidate(source={"source_type": source_type,
                                          "source_reference": "ref",
                                          "resolved_revision": D})
            self.assertEqual(validate_candidate(cand)["verdict"], "CANDIDATE_CONTRACT_VALID")
            projection = governance_projection(cand)
            self.assertNotIn("source_type", projection)
            self.assertEqual(
                sorted(("artifact_digest", "candidate_id", "candidate_version",
                        "capability_id", "manifest", "name", "producer",
                        "requester", "source")),
                sorted(projection),
            )

    def test_phase8_compatibility(self):
        report = validate_candidate(make_candidate())
        phase8 = report["phase8_compatibility"]
        self.assertEqual(
            sorted(phase8["supplies_authority_fields"]),
            sorted(["candidate_id", "candidate_version", "artifact_digest"]),
        )
        projection = report["governance_projection"]
        self.assertEqual(projection["candidate_id"], "cand-1")
        self.assertEqual(projection["candidate_version"], "v1")
        self.assertEqual(projection["artifact_digest"], E)

    def test_invalid_raw_input_rejected(self):
        for raw in (None, [], "not-a-candidate", {}, {"candidate_id": "x"}):
            result = intake(raw)
            self.assertEqual(result["intake"], "INTAKE_REJECTED")
            self.assertEqual(validate_candidate(raw)["verdict"], "CANDIDATE_CONTRACT_INVALID")

    def test_provenance_source_revision_mismatch_rejected(self):
        cand = make_candidate()
        cand["provenance"]["source_revision"] = "sha256:" + "f" * 64
        result = intake(cand)
        self.assertEqual(result["intake"], "INTAKE_REJECTED")
        self.assertTrue(any(v["code"] == "PROVENANCE_SOURCE_MISMATCH"
                            for v in result["violations"]))

    def test_manifest_forged_digest_semantics_conflict_rejected(self):
        cand = make_candidate(manifest=manifest(forged_digest="sha256:" + "a" * 64))
        result = intake(cand)
        self.assertEqual(result["intake"], "INTAKE_REJECTED")
        self.assertTrue(any(v["code"] == "ARTIFACT_DIGEST_SEMANTICS_CONFLICT"
                            for v in result["violations"]))


if __name__ == "__main__":
    unittest.main()
