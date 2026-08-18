"""Phase 9-B.1 RED tests: production CANONICAL_ARTIFACT_IDENTITY_V1.

These tests target the production implementation in src/forge/capabilityizer.py
and fail until the canonical identity + seal code lands.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from forge.capabilityizer import (  # noqa: E402
    CANONICAL_ARTIFACT_IDENTITY_V1,
    artifact_digest,
    artifact_layout,
    canonical_artifact_digest,
    frozen_artifact_report,
)


def write_files(root: Path, files: dict[str, bytes]) -> None:
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


class CanonicalArtifactIdentityTests(unittest.TestCase):
    def test_runtime_generated_files_do_not_change_digest_but_layout_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "artifact"
            write_files(root, {"main.py": b"print(1)\n"})
            base = artifact_digest(root, ["main.py"])
            for rel in ("__pycache__/main.cpython-313.pyc", "run.log",
                        "scratch.tmp", "generated/out.txt"):
                write_files(root, {rel: b"noise"})
                self.assertEqual(artifact_digest(root, ["main.py"]), base)
                report = frozen_artifact_report(root, ["main.py"])
                self.assertFalse(report["ok"])
                self.assertTrue(any(
                    v.startswith("UNDECLARED_ARTIFACT_FILE") for v in report["violations"]))

    def test_artifact_byte_change_must_change_digest(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "artifact"
            write_files(root, {"main.py": b"print(1)\n"})
            before = artifact_digest(root, ["main.py"])
            write_files(root, {"main.py": b"print(2)\n"})
            self.assertNotEqual(artifact_digest(root, ["main.py"]), before)

    def test_allowlist_missing_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "artifact"
            write_files(root, {"main.py": b"print(1)\n"})
            _, violations = artifact_layout(root, [])
            self.assertIn("ARTIFACT_ALLOWLIST_MISSING", violations)
            report = frozen_artifact_report(root, None)
            self.assertFalse(report["ok"])
            self.assertIn("ARTIFACT_ALLOWLIST_MISSING", report["violations"])

    def test_allowlist_duplicate_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "artifact"
            write_files(root, {"main.py": b"print(1)\n"})
            report = frozen_artifact_report(root, ["main.py", "main.py"])
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                v.startswith("ARTIFACT_ALLOWLIST_DUPLICATE") for v in report["violations"]))

    def test_absolute_path_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "artifact"
            write_files(root, {"main.py": b"print(1)\n"})
            report = frozen_artifact_report(root, [str((root / "main.py").resolve())])
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                v.startswith("ARTIFACT_ALLOWLIST_PATH_INVALID") for v in report["violations"]))

    def test_path_traversal_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "artifact"
            write_files(root, {"main.py": b"print(1)\n"})
            report = frozen_artifact_report(root, ["../main.py"])
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                v.startswith("ARTIFACT_ALLOWLIST_PATH_INVALID") for v in report["violations"]))

    def test_undeclared_actual_file_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "artifact"
            write_files(root, {"main.py": b"print(1)\n", "extra.py": b"x = 1\n"})
            report = frozen_artifact_report(root, ["main.py"])
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                v.startswith("UNDECLARED_ARTIFACT_FILE:extra.py") for v in report["violations"]))

    def test_declared_missing_file_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "artifact"
            write_files(root, {"main.py": b"print(1)\n"})
            report = frozen_artifact_report(root, ["main.py", "missing.py"])
            self.assertFalse(report["ok"])
            self.assertTrue(any(
                v.startswith("ARTIFACT_ALLOWLIST_FILE_MISSING:missing.py")
                for v in report["violations"]))

    def test_canonical_serialization_deterministic(self):
        d1 = "sha256:" + "a" * 64
        d2 = "sha256:" + "b" * 64
        expected = hashlib.sha256(json.dumps(
            {"a.py": d1, "b.py": d2}, sort_keys=True,
            separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
        self.assertEqual(canonical_artifact_digest({"b.py": d2, "a.py": d1}),
                         "sha256:" + expected)
        self.assertEqual(
            canonical_artifact_digest({"a.py": d1, "b.py": d2}),
            canonical_artifact_digest({"b.py": d2, "a.py": d1}))

    def test_posix_path_ordering_deterministic(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "artifact"
            write_files(root, {
                "sub/data.py": b"d\n",
                "main.py": b"m\n",
                "a.py": b"a\n",
            })
            allowlist = ["a.py", "main.py", "sub/data.py"]
            self.assertEqual(artifact_digest(root, allowlist),
                             artifact_digest(root, allowlist))
            files = {p: hashlib.sha256((root / p).read_bytes()).hexdigest()
                     for p in allowlist}
            self.assertEqual(
                artifact_digest(root, allowlist),
                canonical_artifact_digest({p: "sha256:" + files[p]
                                           for p in reversed(allowlist)}))

    def test_capabilityize_new_candidates_use_canonical_digest(self):
        from forge.capabilityizer import capabilityize  # noqa: E402

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            golden = root / "golden"
            (golden / "t1").mkdir(parents=True)
            (golden / "t1" / "data.csv").write_text("id\n")
            (golden / "t1" / "expected.json").write_text("{}")
            proposal = {
                "name": "csv-clean-report", "description": "clean csv",
                "skill_md": "# usage",
                "implementation": {"main.py": "import sys\nprint(1)\n"},
                "entrypoint": {"command": ["python", "main.py"], "workdir": "artifact"},
                "contract": {"input": {"files": ["data/*.csv"], "args": {}},
                             "output": {"files": ["report.md"], "stdout": "string",
                                        "exit_code": 0}},
                "tests": [],
            }
            made = capabilityize(
                [{"bundle_id": "b1", "bundle_digest": "sha256:" + "0" * 64,
                  "task_id": "t", "arm": "b3", "cwd": "/tmp/w"}],
                proposal, {"confirm": True}, golden, root / "cand")
            artifact = Path(made["candidate_dir"]) / "implementation" / "artifact"
            self.assertEqual(made["forged_artifact_digest"],
                             artifact_digest(artifact, ["main.py"]))


if __name__ == "__main__":
    unittest.main()
