"""Phase 9-A.1.1 - closure tests for the four hard blockers (offline, stdlib).

Covers CANONICAL_ARTIFACT_IDENTITY_V1, CANDIDATE_FREEZE_RULES_V1, governance
source independence, capability_id ownership, and the adversarial matrix.
"""

from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from validate_capability_candidate_closure import (  # noqa: E402
    artifact_digest,
    closure_intake,
    capability_id_derivation,
    freeze_candidate,
    frozen_artifact_report,
    governance_projection,
    modification_verdict,
    registry_capability_id_conflict,
    source_leak_violations,
    verify_frozen,
)
from validate_capability_candidate_contract import intake, SCHEMA_VERSION  # noqa: E402

D = "sha256:" + "d" * 64


def make_candidate(**overrides) -> dict:
    cand = {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": "cand-a",
        "capability_id": "cap-x",
        "name": "csv-clean-report",
        "version": 1,
        "requester": {"kind": "human", "id": "operator-1", "request_id": "req-1"},
        "producer": {"kind": "agent", "id": "codex-artifact-builder-v0"},
        "source": {"source_type": "agent",
                   "source_reference": "rollout:run-1",
                   "resolved_revision": D},
        "artifact": {"artifact_digest": None, "artifact_ref": None, "files": ["main.py"]},
        "manifest": {
            "manifest_version": "0.1",
            "capability": {"name": "csv-clean-report", "description": "demo", "version": 1},
            "entrypoint": {"command": ["python", "main.py"], "workdir": "artifact"},
            "contract": {"input": {"files": []}, "output": {"files": ["report.md"]}},
            "tests": [{"id": "t1"}],
            "sandbox": {"permissions": {"network": False, "fs_write": ["/output"]},
                        "limits": {"timeout_seconds": 120, "output_bytes": 1048576}},
            "provenance": {"source_bundle_id": "bundle-1",
                           "source_artifact_digest": D,
                           "forged_artifact_digest": None,
                           "forge_timestamp": "2026-08-18T00:00:00.000Z"},
        },
        "provenance": {"created_at": "2026-08-18T00:00:00.000Z",
                       "source_revision": D,
                       "build_ref": "bundle:bundle-1",
                       "request_id": "req-1"},
    }
    cand.update(overrides)
    return cand


def write_layout(root: Path, artifact_files: dict[str, bytes],
                 tests: dict[str, bytes] | None = None) -> None:
    for rel, data in artifact_files.items():
        p = root / "artifact" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    for rel, data in (tests or {"t1/data.csv": b"id\n", "t1/expected.json": b"{}"}).items():
        p = root / "tests" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


def bind_digests(cand: dict, root: Path) -> dict:
    d = artifact_digest(root / "artifact", cand["artifact"]["files"])
    cand["artifact"]["artifact_digest"] = d
    cand["artifact"]["artifact_ref"] = f"artifact:{d}"
    cand["manifest"]["provenance"]["forged_artifact_digest"] = d
    return cand


class CanonicalArtifactIdentityV1Tests(unittest.TestCase):
    def test_pycache_does_not_change_digest_but_layout_rejects_it(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_layout(root, {"main.py": b"print(1)\n"})
            allowlist = ["main.py"]
            clean = frozen_artifact_report(root / "artifact", allowlist)
            pyc = root / "artifact" / "__pycache__" / "main.cpython-313.pyc"
            pyc.parent.mkdir()
            pyc.write_bytes(b"\x00" * 64)
            with_pyc = frozen_artifact_report(root / "artifact", allowlist)
            self.assertEqual(clean["digest"], with_pyc["digest"])  # SAME_ARTIFACT_DIGEST
            self.assertTrue(clean["ok"])
            self.assertFalse(with_pyc["ok"])
            self.assertTrue(any(v.startswith("UNDECLARED_ARTIFACT_FILE")
                                for v in with_pyc["violations"]))

    def test_temp_and_log_files_do_not_change_digest_but_layout_rejects_them(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_layout(root, {"main.py": b"print(1)\n"})
            allowlist = ["main.py"]
            base = artifact_digest(root / "artifact", allowlist)
            for rel in ("tmp/x.tmp", "logs/run.log", "generated.out"):
                p = root / "artifact" / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"noise")
                self.assertEqual(artifact_digest(root / "artifact", allowlist), base)
                report = frozen_artifact_report(root / "artifact", allowlist)
                self.assertFalse(report["ok"])
                self.assertTrue(any(v.startswith("UNDECLARED_ARTIFACT_FILE")
                                    for v in report["violations"]))

    def test_artifact_byte_change_must_change_digest(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_layout(root, {"main.py": b"print(1)\n"})
            before = artifact_digest(root / "artifact", ["main.py"])
            (root / "artifact" / "main.py").write_bytes(b"print(2)\n")
            after = artifact_digest(root / "artifact", ["main.py"])
            self.assertNotEqual(before, after)  # MUST_CHANGE_DIGEST

    def test_missing_allowlist_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_layout(root, {"main.py": b"print(1)\n"})
            report = frozen_artifact_report(root / "artifact", ["main.py", "missing.py"])
            self.assertFalse(report["ok"])
            self.assertTrue(any(v.startswith("ARTIFACT_ALLOWLIST_FILE_MISSING")
                                for v in report["violations"]))

    def test_invalid_allowlist_path_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_layout(root, {"main.py": b"print(1)\n"})
            report = frozen_artifact_report(root / "artifact", ["../evil.py"])
            self.assertFalse(report["ok"])
            self.assertTrue(any(v.startswith("ARTIFACT_ALLOWLIST_PATH_INVALID")
                                for v in report["violations"]))


class CandidateFreezeRulesTests(unittest.TestCase):
    def _sealed(self, root: Path, cand: dict | None = None):
        write_layout(root, {"main.py": b"print(1)\n"})
        cand = bind_digests(make_candidate() if cand is None else cand, root)
        return cand, freeze_candidate(cand, root / "artifact", root / "tests")

    def test_seal_requires_byte_level_digest_match(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_layout(root, {"main.py": b"print(1)\n"})
            cand = make_candidate()
            d = artifact_digest(root / "artifact", cand["artifact"]["files"])
            cand["artifact"]["artifact_digest"] = d
            cand["artifact"]["artifact_ref"] = f"artifact:{d}"
            cand["manifest"]["provenance"]["forged_artifact_digest"] = d
            cand["artifact"]["artifact_digest"] = "sha256:" + "e" * 64  # lies about bytes
            frozen = freeze_candidate(cand, root / "artifact", root / "tests")
            self.assertFalse(frozen["ok"])
            self.assertTrue(any(v["code"] == "ARTIFACT_DIGEST_MISMATCH"
                                for v in frozen["violations"]))

    def test_manifest_change_after_seal_detected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cand, frozen = self._sealed(root)
            cand["manifest"]["capability"]["version"] = 2
            verify = verify_frozen(frozen["record"], cand, root / "artifact", root / "tests")
            self.assertFalse(verify["ok"])
            self.assertTrue(any(v["code"] == "MANIFEST_CHANGED_AFTER_SEAL"
                                for v in verify["violations"]))
            self.assertEqual(modification_verdict(verify), "NEW_CANDIDATE_REQUIRED")

    def test_tests_change_after_seal_detected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cand, frozen = self._sealed(root)
            (root / "tests" / "t1" / "data.csv").write_bytes(b"id,tampered\n")
            verify = verify_frozen(frozen["record"], cand, root / "artifact", root / "tests")
            self.assertFalse(verify["ok"])
            self.assertTrue(any(v["code"] == "TESTS_CHANGED_AFTER_SEAL"
                                for v in verify["violations"]))

    def test_requester_change_after_seal_detected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cand, frozen = self._sealed(root)
            cand["requester"]["id"] = "operator-2"
            verify = verify_frozen(frozen["record"], cand, root / "artifact", root / "tests")
            self.assertFalse(verify["ok"])
            self.assertTrue(any(v["code"] == "SEAL_DIGEST_MISMATCH"
                                for v in verify["violations"]))

    def test_producer_change_after_seal_detected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cand, frozen = self._sealed(root)
            cand["producer"]["id"] = "someone-else"
            verify = verify_frozen(frozen["record"], cand, root / "artifact", root / "tests")
            self.assertFalse(verify["ok"])
            self.assertTrue(any(v["code"] == "SEAL_DIGEST_MISMATCH"
                                for v in verify["violations"]))

    def test_artifact_change_after_seal_detected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cand, frozen = self._sealed(root)
            (root / "artifact" / "main.py").write_bytes(b"print(2)\n")
            verify = verify_frozen(frozen["record"], cand, root / "artifact", root / "tests")
            self.assertFalse(verify["ok"])
            self.assertTrue(any(v["code"] == "ARTIFACT_DIGEST_MISMATCH"
                                for v in verify["violations"]))

    def test_evidence_appended_after_seal_is_not_candidate_identity(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cand, frozen = self._sealed(root)
            (root / "evaluation.json").write_text('{"verdict":"PASS"}\n')
            verify = verify_frozen(frozen["record"], cand, root / "artifact", root / "tests")
            self.assertTrue(verify["ok"])  # evidence lives outside frozen identity

    def test_source_type_change_after_seal_detected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cand, frozen = self._sealed(root)
            cand["source"]["source_type"] = "git"
            verify = verify_frozen(frozen["record"], cand, root / "artifact", root / "tests")
            self.assertFalse(verify["ok"])
            self.assertTrue(any(v["code"] == "SEAL_DIGEST_MISMATCH"
                                for v in verify["violations"]))


class GovernanceSourceIndependenceTests(unittest.TestCase):
    def _projections(self, root: Path, sources: list[dict]) -> list[dict]:
        out = []
        for source in sources:
            cand = bind_digests(make_candidate(source=source), root)
            frozen = freeze_candidate(cand, root / "artifact", root / "tests")
            self.assertTrue(frozen["ok"], frozen["violations"])
            out.append(governance_projection(cand, frozen["record"]))
        return out

    def test_projection_identical_across_all_source_types(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_layout(root, {"main.py": b"print(1)\n"})
            sources = [
                {"source_type": t, "source_reference": f"ref:{t}",
                 "resolved_revision": D}
                for t in ("git", "oci", "agent", "marketplace", "future_source_xyz")
            ]
            projections = self._projections(root, sources)
            self.assertTrue(all(p == projections[0] for p in projections))

    def test_projection_has_no_source_keys_anywhere(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_layout(root, {"main.py": b"print(1)\n"})
            cand = bind_digests(make_candidate(), root)
            frozen = freeze_candidate(cand, root / "artifact", root / "tests")
            projection = governance_projection(cand, frozen["record"])
            self.assertEqual(source_leak_violations(projection), [])

    def test_source_reference_change_same_revision_keeps_projection(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_layout(root, {"main.py": b"print(1)\n"})
            a = bind_digests(make_candidate(
                source={"source_type": "git", "source_reference": "old-url",
                        "resolved_revision": D}), root)
            b = bind_digests(make_candidate(
                source={"source_type": "git", "source_reference": "new-url",
                        "resolved_revision": D}), root)
            fa = freeze_candidate(a, root / "artifact", root / "tests")
            fb = freeze_candidate(b, root / "artifact", root / "tests")
            self.assertEqual(governance_projection(a, fa["record"]),
                             governance_projection(b, fb["record"]))


class IdentityOwnershipTests(unittest.TestCase):
    def test_capability_id_stable_across_versions_and_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_layout(root, {"main.py": b"print(1)\n"})
            v1 = bind_digests(make_candidate(candidate_id="cand-a", version=1), root)
            v2 = bind_digests(make_candidate(candidate_id="cand-b", version=2), root)
            v2["manifest"]["capability"]["version"] = 2
            for cand in (v1, v2):
                self.assertEqual(closure_intake(cand, root / "artifact", root / "tests")["intake"],
                                 "INTAKE_ACCEPTED")
            self.assertEqual(v1["capability_id"], v2["capability_id"])
            self.assertNotEqual(v1["candidate_id"], v2["candidate_id"])

    def test_rejection_is_governance_state_not_identity(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_layout(root, {"main.py": b"print(1)\n"})
            rejected_v1 = bind_digests(make_candidate(candidate_id="cand-rejected"), root)
            self.assertEqual(closure_intake(rejected_v1, root / "artifact", root / "tests")["intake"],
                             "INTAKE_ACCEPTED")
            # v2 with the same capability_id is a fresh, valid intake:
            # rejection lives in governance lifecycle, not in the identity.
            v2 = bind_digests(make_candidate(candidate_id="cand-v2"), root)
            self.assertEqual(closure_intake(v2, root / "artifact", root / "tests")["intake"],
                             "INTAKE_ACCEPTED")

    def test_registry_reuses_candidate_capability_id_and_never_mints(self):
        self.assertIsNone(registry_capability_id_conflict("cap-a", None))
        self.assertIsNone(registry_capability_id_conflict("cap-a", "cap-a"))
        self.assertEqual(registry_capability_id_conflict("cap-a", "cap-b"),
                         "CAPABILITY_ID_CONFLICT")

    def test_deterministic_capability_id_is_replayable(self):
        self.assertEqual(capability_id_derivation("F+", "csv-clean-report"),
                         capability_id_derivation("F+", "csv-clean-report"))
        self.assertNotEqual(capability_id_derivation("F+", "csv-clean-report"),
                            capability_id_derivation("F+", "other-name"))
        self.assertNotEqual(capability_id_derivation("F+", "csv-clean-report"),
                            capability_id_derivation("G", "csv-clean-report"))


class ClosureIntakeInvariantTests(unittest.TestCase):
    def test_version_and_name_bound_to_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_layout(root, {"main.py": b"print(1)\n"})
            cand = bind_digests(make_candidate(), root)
            cand["version"] = 2
            self.assertEqual(closure_intake(cand, root / "artifact", root / "tests")["intake"],
                             "INTAKE_REJECTED")
            cand2 = bind_digests(make_candidate(), root)
            cand2["name"] = "different-name"
            self.assertEqual(closure_intake(cand2, root / "artifact", root / "tests")["intake"],
                             "INTAKE_REJECTED")

    def test_artifact_ref_bound_to_digest(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_layout(root, {"main.py": b"print(1)\n"})
            cand = bind_digests(make_candidate(), root)
            cand["artifact"]["artifact_ref"] = "artifact:" + "sha256:" + "f" * 64
            result = closure_intake(cand, root / "artifact", root / "tests")
            self.assertEqual(result["intake"], "INTAKE_REJECTED")
            self.assertTrue(any(v["code"] == "ARTIFACT_REF_BINDING_MISMATCH"
                                for v in result["violations"]))

    def test_requester_request_id_bound_to_provenance(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_layout(root, {"main.py": b"print(1)\n"})
            cand = bind_digests(make_candidate(), root)
            cand["requester"]["request_id"] = "req-a"
            cand["provenance"]["request_id"] = "req-b"
            result = closure_intake(cand, root / "artifact", root / "tests")
            self.assertEqual(result["intake"], "INTAKE_REJECTED")
            self.assertTrue(any(v["code"] == "REQUEST_ID_BINDING_MISMATCH"
                                for v in result["violations"]))

    def test_missing_forged_digest_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_layout(root, {"main.py": b"print(1)\n"})
            cand = bind_digests(make_candidate(), root)
            del cand["manifest"]["provenance"]["forged_artifact_digest"]
            result = closure_intake(cand, root / "artifact", root / "tests")
            self.assertEqual(result["intake"], "INTAKE_REJECTED")
            self.assertTrue(any(v["code"] == "MANIFEST_FORGED_DIGEST_MISSING"
                                for v in result["violations"]))

    def test_source_artifact_digest_bound_to_resolved_revision(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_layout(root, {"main.py": b"print(1)\n"})
            cand = bind_digests(make_candidate(), root)
            cand["manifest"]["provenance"]["source_artifact_digest"] = "sha256:" + "f" * 64
            result = closure_intake(cand, root / "artifact", root / "tests")
            self.assertEqual(result["intake"], "INTAKE_REJECTED")
            self.assertTrue(any(v["code"] == "SOURCE_REVISION_BINDING_MISMATCH"
                                for v in result["violations"]))

    def test_artifact_allowlist_required(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_layout(root, {"main.py": b"print(1)\n"})
            cand = bind_digests(make_candidate(), root)
            del cand["artifact"]["files"]
            self.assertEqual(closure_intake(cand, root / "artifact", root / "tests")["intake"],
                             "INTAKE_REJECTED")

    def test_capability_id_format(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_layout(root, {"main.py": b"print(1)\n"})
            cand = bind_digests(make_candidate(capability_id="not-a-cap"), root)
            result = closure_intake(cand, root / "artifact", root / "tests")
            self.assertEqual(result["intake"], "INTAKE_REJECTED")
            self.assertTrue(any(v["code"] == "CAPABILITY_ID_FORMAT"
                                for v in result["violations"]))


if __name__ == "__main__":
    unittest.main()
