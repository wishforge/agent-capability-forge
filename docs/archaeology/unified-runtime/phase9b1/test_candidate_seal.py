"""Phase 9-B.1 RED tests: production Candidate Seal / Frozen Candidate."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from forge.capabilityizer import (  # noqa: E402
    FROZEN_CORE_KEYS,
    artifact_digest,
    bind_evaluation,
    freeze_candidate,
    get_artifact_digest,
    get_seal_digest,
    load_frozen_candidate,
    verify_frozen,
)

D = "sha256:" + "d" * 64
SCHEMA_VERSION = "capability-candidate-v1"


def make_candidate(**overrides) -> dict:
    cand = {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": "cand-a",
        "capability_id": "cap-x",
        "name": "csv-clean-report",
        "version": 1,
        "requester": {"kind": "human", "id": "operator-1", "request_id": "req-1"},
        "producer": {"kind": "agent", "id": "codex-artifact-builder-v0"},
        "source": {"source_type": "agent", "source_reference": "rollout:r1",
                   "resolved_revision": D},
        "artifact": {"artifact_digest": None, "artifact_ref": None,
                     "files": ["main.py"]},
        "manifest": {
            "manifest_version": "0.1",
            "capability": {"name": "csv-clean-report", "description": "demo",
                           "version": 1},
            "entrypoint": {"command": ["python", "main.py"], "workdir": "artifact"},
            "contract": {"input": {"files": []}, "output": {"files": ["report.md"]}},
            "tests": [{"id": "t1"}],
            "sandbox": {"permissions": {"network": False, "fs_write": ["/output"]},
                        "limits": {"timeout_seconds": 120, "output_bytes": 1048576}},
            "provenance": {"source_bundle_id": "bundle-1",
                           "source_artifact_digest": D,
                           "forged_artifact_digest": None,
                           "forge_timestamp": "2026-08-18T00:00:00Z"},
        },
        "provenance": {"created_at": "2026-08-18T00:00:00Z",
                       "source_revision": D,
                       "build_ref": "bundle:bundle-1",
                       "request_id": "req-1"},
        "extensions": {"codex": {"session_id": "s1"}},
    }
    cand.update(overrides)
    return cand


def bind_digests(cand: dict, root: Path) -> dict:
    d = artifact_digest(root / "artifact", cand["artifact"]["files"])
    cand["artifact"]["artifact_digest"] = d
    cand["artifact"]["artifact_ref"] = f"artifact:{d}"
    cand["manifest"]["provenance"]["forged_artifact_digest"] = d
    return cand


def write_layout(root: Path, artifact_files: dict[str, bytes]) -> None:
    for rel, data in artifact_files.items():
        p = root / "artifact" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    (root / "tests" / "t1").mkdir(parents=True)
    (root / "tests" / "t1" / "data.csv").write_text("id\n")
    (root / "tests" / "t1" / "expected.json").write_text("{}")


class CandidateSealTests(unittest.TestCase):
    def test_freeze_creates_record_and_verify_passes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = root / "store"
            write_layout(root, {"main.py": b"print(1)\n"})
            cand = bind_digests(make_candidate(), root)
            frozen = freeze_candidate(cand, root / "artifact", root / "tests", store)
            self.assertTrue(frozen["ok"], frozen["violations"])
            self.assertEqual(frozen["verdict"], "FROZEN")
            self.assertEqual(get_artifact_digest(store, cand["candidate_id"]),
                             frozen["record"]["artifact_digest"])
            self.assertEqual(get_seal_digest(store, cand["candidate_id"]),
                             frozen["record"]["seal_digest"])
            loaded = load_frozen_candidate(store, cand["candidate_id"])
            self.assertEqual(loaded["candidate_id"], cand["candidate_id"])
            verify = verify_frozen(store, cand["candidate_id"])
            self.assertTrue(verify["ok"], verify["violations"])
            self.assertEqual(verify["verdict"], "FROZEN_CANDIDATE_UNCHANGED")

    def test_freeze_same_content_is_idempotent_allow(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = root / "store"
            write_layout(root, {"main.py": b"print(1)\n"})
            cand = bind_digests(make_candidate(), root)
            first = freeze_candidate(cand, root / "artifact", root / "tests", store)
            second = freeze_candidate(cand, root / "artifact", root / "tests", store)
            self.assertTrue(first["ok"])
            self.assertTrue(second["ok"])
            self.assertEqual(second["verdict"], "ALLOW")
            self.assertEqual(get_seal_digest(store, cand["candidate_id"]),
                             first["record"]["seal_digest"])

    def test_freeze_different_content_conflicts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = root / "store"
            write_layout(root, {"main.py": b"print(1)\n"})
            cand = bind_digests(make_candidate(), root)
            first = freeze_candidate(cand, root / "artifact", root / "tests", store)
            (root / "artifact" / "main.py").write_bytes(b"print(2)\n")
            cand2 = bind_digests(make_candidate(), root)
            second = freeze_candidate(cand2, root / "artifact", root / "tests", store)
            self.assertFalse(second["ok"])
            self.assertEqual(second["verdict"], "FROZEN_CANDIDATE_CONFLICT")
            self.assertTrue(any(
                v["code"] == "FROZEN_CANDIDATE_CONFLICT"
                for v in second["violations"]))
            self.assertEqual(get_seal_digest(store, cand["candidate_id"]),
                             first["record"]["seal_digest"])

    def test_artifact_mutation_after_seal_requires_new_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = root / "store"
            write_layout(root, {"main.py": b"print(1)\n"})
            cand = bind_digests(make_candidate(), root)
            freeze_candidate(cand, root / "artifact", root / "tests", store)
            snap = store / "frozen" / cand["candidate_id"] / "artifact" / "main.py"
            snap.chmod(0o644)
            snap.write_bytes(b"print(2)\n")
            verify = verify_frozen(store, cand["candidate_id"])
            self.assertFalse(verify["ok"])
            self.assertEqual(verify["verdict"], "NEW_CANDIDATE_REQUIRED")
            self.assertTrue(any(
                v["code"] == "ARTIFACT_DIGEST_MISMATCH" for v in verify["violations"]))

    def test_manifest_mutation_after_seal_requires_new_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = root / "store"
            write_layout(root, {"main.py": b"print(1)\n"})
            cand = bind_digests(make_candidate(), root)
            freeze_candidate(cand, root / "artifact", root / "tests", store)
            manifest = store / "frozen" / cand["candidate_id"] / "candidate.json"
            data = json.loads(manifest.read_text())
            data["manifest"]["capability"]["version"] = 2
            manifest.chmod(0o644)
            manifest.write_text(json.dumps(data))
            verify = verify_frozen(store, cand["candidate_id"])
            self.assertFalse(verify["ok"])
            self.assertEqual(verify["verdict"], "NEW_CANDIDATE_REQUIRED")
            self.assertTrue(any(
                v["code"] == "MANIFEST_CHANGED_AFTER_SEAL"
                for v in verify["violations"]))

    def test_tests_mutation_after_seal_requires_new_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = root / "store"
            write_layout(root, {"main.py": b"print(1)\n"})
            cand = bind_digests(make_candidate(), root)
            freeze_candidate(cand, root / "artifact", root / "tests", store)
            snap = store / "frozen" / cand["candidate_id"] / "tests" / "t1" / "data.csv"
            snap.chmod(0o644)
            snap.write_bytes(b"id,tampered\n")
            verify = verify_frozen(store, cand["candidate_id"])
            self.assertFalse(verify["ok"])
            self.assertEqual(verify["verdict"], "NEW_CANDIDATE_REQUIRED")
            self.assertTrue(any(
                v["code"] == "TESTS_CHANGED_AFTER_SEAL" for v in verify["violations"]))

    def test_immutable_identity_fields_after_seal_require_new_candidate(self):
        mutations = {
            "producer": {"kind": "agent", "id": "someone-else"},
            "source": {"source_type": "git", "source_reference": "other",
                       "resolved_revision": D},
            "requester": {"kind": "human", "id": "operator-2", "request_id": "req-2"},
            "provenance": {"created_at": "2026-08-18T00:00:00Z",
                           "source_revision": D, "build_ref": "bundle:other",
                           "request_id": "req-2"},
            "extensions": {"codex": {"session_id": "tampered"}},
            "capability_id": "cap-tampered",
        }
        for key, value in mutations.items():
            with self.subTest(key=key):
                with tempfile.TemporaryDirectory() as td:
                    root = Path(td)
                    store = root / "store"
                    write_layout(root, {"main.py": b"print(1)\n"})
                    cand = bind_digests(make_candidate(), root)
                    freeze_candidate(cand, root / "artifact", root / "tests", store)
                    cand_path = store / "frozen" / cand["candidate_id"] / "candidate.json"
                    data = json.loads(cand_path.read_text())
                    data[key] = value
                    cand_path.chmod(0o644)
                    cand_path.write_text(json.dumps(data))
                    verify = verify_frozen(store, cand["candidate_id"])
                    self.assertFalse(verify["ok"])
                    self.assertEqual(verify["verdict"], "NEW_CANDIDATE_REQUIRED")

    def test_evidence_files_do_not_change_seal_identity(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = root / "store"
            write_layout(root, {"main.py": b"print(1)\n"})
            cand = bind_digests(make_candidate(), root)
            frozen = freeze_candidate(cand, root / "artifact", root / "tests", store)
            (root / "evaluation.json").write_text('{"verdict": "PASS"}\n')
            store.chmod(0o755)
            (store / "evaluation.json").write_text('{"verdict": "PASS"}\n')
            (store / "validation.json").write_text('{"ok": true}\n')
            store.chmod(0o555)
            verify = verify_frozen(store, cand["candidate_id"])
            self.assertTrue(verify["ok"], verify["violations"])
            self.assertEqual(get_seal_digest(store, cand["candidate_id"]),
                             frozen["record"]["seal_digest"])

    def test_frozen_core_excludes_evidence_and_governance(self):
        for key in ("evaluation", "validation", "promotion", "decision", "authority"):
            self.assertNotIn(key, FROZEN_CORE_KEYS)

    def test_artifact_ref_must_equal_artifact_digest(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_layout(root, {"main.py": b"print(1)\n"})
            cand = bind_digests(make_candidate(), root)
            cand["artifact"]["artifact_ref"] = "artifact:" + "sha256:" + "f" * 64
            frozen = freeze_candidate(cand, root / "artifact", root / "tests")
            self.assertFalse(frozen["ok"])
            self.assertTrue(any(
                v["code"] == "ARTIFACT_REF_BINDING_MISMATCH"
                for v in frozen["violations"]))

    def test_forged_artifact_digest_mismatch_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_layout(root, {"main.py": b"print(1)\n"})
            cand = bind_digests(make_candidate(), root)
            cand["manifest"]["provenance"]["forged_artifact_digest"] = \
                "sha256:" + "f" * 64
            frozen = freeze_candidate(cand, root / "artifact", root / "tests")
            self.assertFalse(frozen["ok"])
            self.assertTrue(any(
                v["code"] == "ARTIFACT_DIGEST_SEMANTICS_CONFLICT"
                for v in frozen["violations"]))

    def test_evaluation_binding_requires_all_three_references(self):
        evaluation = {"evaluation_id": "eval-1", "verdict": "PASS",
                      "candidate_id": "cand-a"}
        bound = bind_evaluation(evaluation, "cand-a",
                                "sha256:" + "a" * 64, "sha256:" + "b" * 64)
        self.assertEqual(bound["candidate_id"], "cand-a")
        self.assertEqual(bound["artifact_digest"], "sha256:" + "a" * 64)
        self.assertEqual(bound["seal_digest"], "sha256:" + "b" * 64)
        self.assertEqual(bound["verdict"], "PASS")
        self.assertEqual(bound["evaluation_id"], "eval-1")


if __name__ == "__main__":
    unittest.main()
