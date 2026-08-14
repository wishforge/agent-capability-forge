"""Smallest runnable checks for the F+ rehearsal implementation (stdlib unittest)."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from forge.bundle_producer import (  # noqa: E402
    seal_bundle, validate_bundle, canonical_json, sha256_bytes, now_iso)
from forge.capabilityizer import capabilityize, CapabilityizeError  # noqa: E402
from pilot.run_record import validate_treatment  # noqa: E402


def _minimal_bundle(store: Path) -> Path:
    content = b"print(42)\n"
    digest = sha256_bytes(content)
    execution = {
        "rollout_ref": None,
        "phases": [],
        "final_phase": None,
        "root_synthesis": None,
    }
    artifacts = {
        "unified_diff": "diff --git a/main.py b/main.py\n+print(42)\n",
        "files": [{"path": "main.py", "previous_path": None, "status": "added",
                   "digest": digest, "content_ref": f"artifacts/files/{digest}",
                   "media_type": "text/x-python", "size_bytes": len(content),
                   "executable": False}],
    }
    bdir, _ = seal_bundle(
        store, identity={
            "bundle_id": None, "source_task_id": None,
            "source_execution_id": "exec-1", "session_id": "s1", "thread_id": "t1",
            "turn_id": "turn-1", "producer": "codex-cli-test", "producer_commit": "0.0.0",
            "generated_at": now_iso(),
        },
        execution=execution, artifacts=artifacts,
        review={"worker_status": "invalid", "result_review_status": "none",
                "correction_owner": None, "interpretation": "model_review_only"},
        verification_evidence={
            "status": "unknown", "command": None, "exit_code": None, "stdout_ref": None,
            "stderr_ref": None, "checker_result": None, "evidence_digest": None,
            "evidence_refs": [],
            "gaps": ["verification_evidence: no structured command-level evidence in Codex v0"],
            "captured_at": None},
        environment={
            "cwd": "/tmp/w", "workspace_roots": ["/tmp/w"], "network": None,
            "permission_policy": None, "environment_snapshot_ref": None,
            "dependency_manifest_ref": None},
        security={"secrets_policy": "no_inline_secrets", "scan_status": "not_scanned",
                  "scan_ref": None, "scan_digest": None},
        rollout_bytes=b"rollout\n", environment_snapshot={"cwd": "/tmp/w"},
        file_contents={digest: content}, producer_commit=None,
    )
    return bdir


class TestBundle(unittest.TestCase):
    def test_seal_validate_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as td:
            store = Path(td) / "store"
            bdir = _minimal_bundle(store)
            self.assertTrue(validate_bundle(bdir)["ok"], validate_bundle(bdir))
            # tamper content -> Rule 7 fails
            f = bdir / "artifacts" / "files"
            victim = next(f.iterdir())
            victim.write_bytes(b"tampered")
            self.assertFalse(validate_bundle(bdir)["ok"])


class TestOracle(unittest.TestCase):
    def test_golden_passes_tampered_fails(self):
        fixture = REPO / "pilot" / "fixtures" / "F+" / "fplus-cal-1"
        check = REPO / "pilot" / "oracles" / "check.py"
        expected = json.loads((fixture / "expected.json").read_text())
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            (out / "report.md").write_text("\n".join(f"{k}: {v}" for k, v in expected.items()) + "\n")
            self.assertEqual(subprocess.run(["python", str(check), str(fixture), str(out)],
                                            capture_output=True).returncode, 0)
            bad = dict(expected)
            bad["total_rows"] = int(bad["total_rows"]) + 1
            (out / "report.md").write_text("\n".join(f"{k}: {v}" for k, v in bad.items()) + "\n")
            self.assertNotEqual(subprocess.run(["python", str(check), str(fixture), str(out)],
                                               capture_output=True).returncode, 0)


class TestCapabilityizer(unittest.TestCase):
    PROPOSAL = {
        "name": "csv-clean-report", "description": "clean csv and report stats",
        "skill_md": "---\nname: csv-clean-report\n---\n# usage",
        "implementation": {"main.py": "import sys, os, csv\n# argv[1] input, argv[2] outdir\n"},
        "entrypoint": {"command": ["python", "main.py"], "workdir": "artifact"},
        "contract": {"input": {"files": ["data/*.csv"], "args": {}},
                     "output": {"files": ["report.md"], "stdout": "string", "exit_code": 0}},
        "tests": [],
    }

    def test_private_path_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            golden = root / "golden"
            (golden / "t1").mkdir(parents=True)
            (golden / "t1" / "data.csv").write_text("id,customer,date,category,amount\n")
            (golden / "t1" / "expected.json").write_text("{}")
            bad = json.loads(json.dumps(self.PROPOSAL))
            bad["implementation"]["main.py"] += "# /Users/redacted/big-wish/work\n"
            with self.assertRaises(CapabilityizeError):
                capabilityize([{"bundle_id": "b1", "bundle_digest": "sha256:" + "0" * 64,
                                "task_id": "t", "arm": "b3", "cwd": "/Users/redacted/big-wish"}],
                              bad, {"confirm": True}, golden, root / "cand")


class TestCost(unittest.TestCase):
    def test_nv_arithmetic(self):
        import pilot.cost as cost_mod
        family = {"formation_tasks": [{"task_id": "c1"}],
                  "future_tasks": [{"task_id": "f1"}, {"task_id": "f2"}],
                  "deltas": [0.05, 0.20]}
        records = [
            {"run_id": "r1", "arm": "b2", "task_id": "c1", "runtime_metrics": None,
             "sandbox_elapsed_s": 0, "oracle": {"verdict": "FAIL"}},
            {"run_id": "r2", "arm": "b3", "task_id": "c1", "runtime_metrics": None,
             "sandbox_elapsed_s": 0, "oracle": {"verdict": "PASS"}},
            {"run_id": "r3", "arm": "b2", "task_id": "f1", "runtime_metrics": None,
             "sandbox_elapsed_s": 0, "oracle": {"verdict": "PASS"}},
            {"run_id": "r4", "arm": "b3", "task_id": "f1", "runtime_metrics": None,
             "sandbox_elapsed_s": 0, "oracle": {"verdict": "PASS"}},
        ]
        prices = {"input_token_usd": 0, "output_token_usd": 0, "human_minute_usd": 0,
                  "sandbox_minute_usd": 0}
        out = cost_mod.collect(records, prices, family, [], {"low": 50, "mid": 100, "high": 200})
        # zero prices -> NV = task value; B2/B3 both 50 at V=low; delta 0 <= 0.05*tco(0)=0
        self.assertEqual(out["nv"]["b2"]["nv"]["low"], 50)
        self.assertEqual(out["nv"]["b3"]["nv"]["low"], 50)
        self.assertEqual(out["sensitivity"][0]["verdict"], "not_superior")


class TestTreatmentAttribution(unittest.TestCase):
    @staticmethod
    def _rec(arm: str, treatment: dict) -> dict:
        return {"run_id": "run-x", "task_id": "fplus-future-1", "arm": arm,
                "treatment": treatment}

    @staticmethod
    def _valid_b2() -> dict:
        d = "sha256:" + "a" * 64
        return {"type": "skill", "used": True, "ref": "csv-clean-statistical-report",
                "digest": d, "evidence": {"kind": "skill_injection",
                                          "mounted_digest": d, "expected_digest": d}}

    @staticmethod
    def _valid_b3() -> dict:
        d = "sha256:" + "b" * 64
        return {"type": "capability", "used": True, "ref": "cap-1", "digest": d,
                "evidence": {"kind": "capability_invoke", "capability_id": "cap-1",
                             "artifact_digest": d, "sandbox_id": "cbx-1"}}

    def test_b2_missing_skill_evidence_invalid(self):
        t = self._valid_b2()
        t["evidence"] = None
        self.assertTrue(validate_treatment(self._rec("b2", t)))

    def test_b2_skill_used_false_invalid(self):
        t = self._valid_b2()
        t["used"] = False
        self.assertTrue(validate_treatment(self._rec("b2", t)))

    def test_b3_missing_capability_invoke_invalid(self):
        t = self._valid_b3()
        t["evidence"] = {}
        self.assertTrue(validate_treatment(self._rec("b3", t)))

    def test_b3_wrong_capability_digest_invalid(self):
        t = self._valid_b3()
        t["evidence"]["artifact_digest"] = "sha256:" + "c" * 64
        self.assertTrue(validate_treatment(self._rec("b3", t)))

    def test_b0_treatment_none_valid(self):
        self.assertEqual(validate_treatment(
            self._rec("b0", {"type": "none", "used": False,
                             "ref": None, "digest": None, "evidence": None})), [])

    def test_valid_b2_attribution(self):
        self.assertEqual(validate_treatment(self._rec("b2", self._valid_b2())), [])

    def test_valid_b3_attribution(self):
        self.assertEqual(validate_treatment(self._rec("b3", self._valid_b3())), [])


if __name__ == "__main__":
    unittest.main()
