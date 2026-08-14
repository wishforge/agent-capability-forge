"""M9 - B3 minimal evaluation (P3 Evaluator seed).

golden regression + >=1 Novel Input Test + independent reuse scenario, then
verdict per the frozen promotion rule. Promote still requires operator confirm.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .validator import _run_test

PROMOTION_RULE = ("golden 100% + novel 100% + regression PASS + independent reuse PASS "
                  "-> eligible; promote requires operator explicit confirm")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def evaluate(cand_dir: Path, sandbox_launch, oracle_script: Path, output_root: Path,
             novel_fixtures: list[tuple[str, Path]], independent_fixtures: list[tuple[str, Path]]) -> dict:
    cand = Path(cand_dir)
    manifest = json.loads((cand / "manifest.json").read_text())
    limits = manifest["sandbox"]["limits"]
    artifact = cand / "implementation" / "artifact"

    def run_input(fixture: Path, tag: str) -> dict:
        out = output_root / f"{tag}-{uuid.uuid4().hex[:8]}"
        out.mkdir(parents=True)
        run = sandbox_launch(limits, [
            (artifact, "/artifact", True), (fixture / "input", "/input", True),
            (out, "/output", False),
        ], ["python", "/artifact/main.py", "/input/data.csv", "/output"])
        if run["exit_code"] != 0:
            return {"tag": tag, "ok": False, "reason": f"exit={run['exit_code']}: {run['stderr'][:500]}"}
        oracle = sandbox_launch(limits, [
            (fixture, "/fixture", True), (oracle_script, "/oracle/check.py", True),
            (out, "/output", True),
        ], ["python", "/oracle/check.py", "/fixture", "/output"])
        return {"tag": tag, "ok": oracle["exit_code"] == 0,
                "reason": oracle["stdout"].strip() or oracle["stderr"].strip()}

    golden = [_run_test(cand, t, sandbox_launch, oracle_script, output_root)
              for t in sorted((cand / "tests").glob("t*"))]
    novel = [run_input(f, tid) for tid, f in novel_fixtures]
    independent = [run_input(f, tid) for tid, f in independent_fixtures]
    pass_rate = sum(1 for g in golden if g["ok"]) / len(golden) if golden else 0.0
    regression = all(g["ok"] for g in golden)
    novel_ok = all(n["ok"] for n in novel)
    independent_ok = all(n["ok"] for n in independent)
    verdict = "PASS" if (regression and novel_ok and independent_ok) else "FAIL"
    evaluation = {
        "evaluation_id": "eval-" + uuid.uuid4().hex[:12],
        "candidate_id": json.loads((cand / "candidate.json").read_text()).get("candidate_id"),
        "test_cases": {"golden": golden, "novel_input_test": novel, "independent_reuse": independent},
        "pass_rate": pass_rate,
        "regression": "PASS" if regression else "FAIL",
        "novel_input_test": "PASS" if novel_ok else "FAIL",
        "independent_reuse": "PASS" if independent_ok else "FAIL",
        "verdict": verdict,
        "promotion_rule": PROMOTION_RULE,
        "evaluated_at": _now(),
    }
    (cand / "evaluation.json").write_text(json.dumps(evaluation, indent=2) + "\n")
    return evaluation
