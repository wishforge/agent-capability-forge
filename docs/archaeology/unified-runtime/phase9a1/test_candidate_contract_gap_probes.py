"""Phase 9-A.1 adversarial review probes (offline, stdlib).

Each probe documents an invariant the v1 contract states (or implies) but the
offline validator does NOT enforce. Probes assert CURRENT validator behavior
so the gaps stay machine-readable; production code was not modified.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from validate_capability_candidate_contract import (
    governance_projection,
    intake,
    SCHEMA_VERSION,
)

D = "sha256:" + "d" * 64
E = "sha256:" + "e" * 64


def base_candidate() -> dict:
    return {
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
        "manifest": {
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
                "forged_artifact_digest": E,
                "forge_timestamp": "2026-08-18T00:00:00.000Z",
            },
        },
        "provenance": {
            "created_at": "2026-08-18T00:00:00.000Z",
            "source_revision": D,
            "build_ref": "bundle:bundle-1",
            "request_id": "req-1",
        },
    }


class CandidateContractGapProbes(unittest.TestCase):
    """Probes: current validator ACCEPTS these; each is a stated v1 gap."""

    def test_probe_top_level_version_not_bound_to_manifest(self):
        cand = base_candidate()
        cand["version"] = 2
        # gap: governance projection would say v2 while manifest.capability.version=1
        self.assertEqual(intake(cand)["intake"], "INTAKE_ACCEPTED")

    def test_probe_top_level_name_not_bound_to_manifest(self):
        cand = base_candidate()
        cand["name"] = "different-name"
        # gap: candidate name and manifest.capability.name disagree
        self.assertEqual(intake(cand)["intake"], "INTAKE_ACCEPTED")

    def test_probe_artifact_ref_not_bound_to_digest(self):
        cand = base_candidate()
        cand["artifact"]["artifact_ref"] = "artifact:sha256:" + "f" * 64
        # gap: artifact_ref may point at a different digest than artifact_digest
        self.assertEqual(intake(cand)["intake"], "INTAKE_ACCEPTED")

    def test_probe_requester_request_id_not_bound_to_provenance(self):
        cand = base_candidate()
        cand["requester"]["request_id"] = "req-a"
        cand["provenance"]["request_id"] = "req-b"
        # gap: requester lineage and provenance lineage disagree
        self.assertEqual(intake(cand)["intake"], "INTAKE_ACCEPTED")

    def test_probe_missing_manifest_forged_digest_accepted(self):
        cand = base_candidate()
        del cand["manifest"]["provenance"]["forged_artifact_digest"]
        # gap: contract says forged digest must equal artifact_digest;
        # absence is silently accepted
        self.assertEqual(intake(cand)["intake"], "INTAKE_ACCEPTED")

    def test_probe_governance_projection_carries_source_type(self):
        cand = base_candidate()
        # gap: source independence is weaker than "no source_type" -
        # the whole source object (with source_type) is passed to consumers
        self.assertEqual(governance_projection(cand)["source"]["source_type"], "agent")

    def test_probe_duplicate_identity_not_detectable(self):
        a, b = base_candidate(), base_candidate()
        # gap: same candidate_id + capability_id accepted twice; no store-level
        # uniqueness check exists in the offline contract
        self.assertEqual(intake(a)["intake"], "INTAKE_ACCEPTED")
        self.assertEqual(intake(b)["intake"], "INTAKE_ACCEPTED")

    def test_probe_requester_optional_for_agent_source(self):
        cand = base_candidate()
        del cand["requester"]
        # gap: agent-produced capability needs no request lineage
        self.assertEqual(intake(cand)["intake"], "INTAKE_ACCEPTED")


if __name__ == "__main__":
    unittest.main()
