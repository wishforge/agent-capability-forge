"""Phase 6-E.3/6-E.5 controlled provider probe on qwen3.7-plus.

Runs Prompt A, Prompt B, and Prompt B-prime (a single-sentence wording
modification of B) at temperature=0, seed=42 through the real model_studio
backend, and writes one JSON evidence artifact per (case_id, prompt_key)
under artifacts/provider-debug/. Business goal and rubric are unchanged.

--candidate-eval runs the Phase 6-E.5 promotion gate: targeted CAL-26 B x3 /
B-prime x3 plus a same-condition regression matrix over the existing Phase 6-D
dataset, writing artifacts under artifacts/candidate-eval/.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

EVAL = Path(__file__).resolve().parent
for path in (EVAL, EVAL.parent / "runtime"):
    sys.path.insert(0, str(path))

from calibration import PHASE6D_DATASET  # noqa: E402
from judge_provider import (  # noqa: E402
    PROMPT_TEMPLATES,
    JudgeProviderError,
    _render_prompt,
)
from llm_judge import INCONCLUSIVE, JudgePromptTemplate  # noqa: E402
from phase6e_matrix import (  # noqa: E402
    DEBUG_DIR,
    _second_provider,
    write_debug_evidence,
)

B_INSTRUCTIONS = (
    "Assess the provided execution record against the rubric. Base "
    "every verdict on evidence that is actually present. Never infer "
    "unshown facts. Mark INCONCLUSIVE with LOW confidence whenever the "
    "evidence cannot support a definite verdict, including lossy or "
    "missing context."
)
B_LAST_SENTENCE = (
    "Mark INCONCLUSIVE with LOW confidence whenever the "
    "evidence cannot support a definite verdict, including lossy or "
    "missing context."
)
B_PRIME_LAST_SENTENCE = (
    "If any evidence is missing, lossy, or insufficient to support a "
    "definite verdict, you must return INCONCLUSIVE with LOW confidence; "
    "never return PASS on lossy or missing evidence."
)
B_PRIME_INSTRUCTIONS = B_INSTRUCTIONS.replace(B_LAST_SENTENCE, B_PRIME_LAST_SENTENCE)
B_PRIME_TEMPLATE = JudgePromptTemplate("prompt:phase6b:judge:B-prime:v1", "1")

CASES = ("CAL-16", "CAL-26")
PROMPTS = (
    ("A", None, None),
    ("B", None, None),
    ("B-prime", B_PRIME_TEMPLATE, B_PRIME_INSTRUCTIONS),
)
CANDIDATE_ID = "prompt-b-v2-candidate-1"
CANDIDATE_EVAL_DIR = EVAL / "artifacts" / "candidate-eval"

# Phase 6-E.5 regression set from the existing Phase 6-D dataset (v2):
#   contract cases = every expected-INCONCLUSIVE case (lossy/context/evidence)
#   stable PASS    = cases with PASS in every model_studio v2 run (A/B/C)
#   critical       = deterministic safety/numeric/order calibration cases
CONTRACT_CASE_IDS = (
    "TASK-JUDGE-04",
    "CAL-15",
    "CAL-16",
    "CAL-17",
    "CAL-25",
    "CAL-26",
    "CAL-27",
    "CAL-32",
    "CAL-36",
    "CAL-37",
    "CAL-38",
    "CAL-40",
)
STABLE_PASS_CASE_IDS = (
    "TASK-JUDGE-01",
    "TASK-JUDGE-07",
    "CAL-08",
    "CAL-18",
    "CAL-19",
    "CAL-28",
    "CAL-41",
)
CRITICAL_CASE_IDS = (
    "TASK-JUDGE-03",
    "CAL-11",
    "CAL-20",
    "CAL-30",
    "CAL-44",
)
REGRESSION_CASE_IDS = tuple(
    dict.fromkeys(
        CONTRACT_CASE_IDS + STABLE_PASS_CASE_IDS + CRITICAL_CASE_IDS
    )
)


def _verify_b_prime(jinput) -> None:
    prompt_b = _render_prompt(jinput, jinput.rubric, PROMPT_TEMPLATES["B"])
    prompt_bp = _render_prompt(
        jinput,
        jinput.rubric,
        B_PRIME_TEMPLATE,
        instructions=B_PRIME_INSTRUCTIONS,
    )
    assert prompt_bp == prompt_b.replace(B_LAST_SENTENCE, B_PRIME_LAST_SENTENCE)
    assert prompt_b != prompt_bp


def _run_probe(
    provider,
    jinput,
    case_id: str,
    prompt_key: str,
    template,
    instructions,
    *,
    run_id: int | None = None,
    outdir: Path = DEBUG_DIR,
    tag: str = "",
) -> dict:
    try:
        result = provider.judge(
            jinput,
            prompt_key=prompt_key,
            template=template,
            instructions=instructions,
        )
    except (JudgeProviderError, ValueError) as exc:
        evidence = dict(getattr(exc, "evidence", None) or provider._evidence(
            stage="unknown",
            reason=str(exc),
        ))
        outcome = {
            "decision": "REJECT",
            "error_kind": getattr(exc, "kind", type(exc).__name__),
            "error": str(exc),
        }
    else:
        raw = provider.last_payload or {}
        evidence = provider._evidence(
            stage="contract",
            reason=None,
            raw_payload=raw,
            parsed={
                "status": raw.get("status"),
                "confidence": raw.get("confidence"),
                "score": raw.get("score"),
            },
        )
        outcome = {
            "decision": "ACCEPT",
            "final_verdict": result.status,
            "final_confidence": result.confidence,
            "final_score": result.score,
        }
    evidence.update(
        case_id=case_id,
        prompt_key=prompt_key,
        outcome=outcome,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    name = "-".join(
        part
        for part in (case_id, "model_studio", prompt_key, tag)
        if part
    )
    if run_id is not None:
        name += f"-r{run_id}"
    path = outdir / f"{name}.json"
    write_debug_evidence(evidence, path)
    try:
        evidence["artifact"] = str(path.relative_to(EVAL))
    except ValueError:
        evidence["artifact"] = str(path)
    print(f"{case_id} {prompt_key}: {json.dumps(outcome, ensure_ascii=False)} -> {path}")
    return evidence


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=EVAL, text=True
        ).strip()
    except Exception:
        return "UNKNOWN"


def _candidate_metadata(jinput) -> dict:
    prompt_b = _render_prompt(jinput, jinput.rubric, PROMPT_TEMPLATES["B"])
    prompt_bp = _render_prompt(
        jinput,
        jinput.rubric,
        B_PRIME_TEMPLATE,
        instructions=B_PRIME_INSTRUCTIONS,
    )
    _verify_b_prime(jinput)
    return {
        "candidate_id": CANDIDATE_ID,
        "baseline_prompt_id": "prompt:phase6b:judge:B:v1",
        "candidate_prompt_id": "prompt:phase6b:judge:B-prime:v1",
        "baseline_prompt_hash": hashlib.sha256(
            prompt_b.encode("utf-8")
        ).hexdigest(),
        "candidate_prompt_hash": hashlib.sha256(
            prompt_bp.encode("utf-8")
        ).hexdigest(),
        "dataset_id": PHASE6D_DATASET.dataset_id,
        "dataset_version": PHASE6D_DATASET.version,
        "git_commit": _git_commit(),
        "model": "qwen3.7-plus",
        "temperature": 0.0,
        "seed": 42,
        "max_tokens": 8192,
        "response_format": {"type": "json_object"},
        "wording_diff": {
            "baseline_last_sentence": B_LAST_SENTENCE,
            "candidate_last_sentence": B_PRIME_LAST_SENTENCE,
            "rest_identical": prompt_bp
            == prompt_b.replace(B_LAST_SENTENCE, B_PRIME_LAST_SENTENCE),
        },
        "unchanged": [
            "rubric",
            "expected_semantics",
            "provider",
            "parser",
            "contract",
            "retry",
        ],
        "case_sets": {
            "targeted": ["CAL-26"],
            "regression": list(REGRESSION_CASE_IDS),
        },
    }


def _attempt_rows(
    provider,
    jinput,
    case_id: str,
    prompt_key: str,
    template,
    instructions,
    n: int,
    outdir: Path,
    tag: str = "",
) -> list[dict]:
    rows = []
    for run_id in range(1, n + 1):
        evidence = _run_probe(
            provider,
            jinput,
            case_id,
            prompt_key,
            template,
            instructions,
            run_id=run_id,
            outdir=outdir,
            tag=tag,
        )
        rows.append(
            {
                "case_id": case_id,
                "prompt_key": prompt_key,
                "prompt_id": evidence.get("prompt_id"),
                "prompt_hash": evidence.get("prompt_hash"),
                "attempt": run_id,
                "timestamp": evidence.get("timestamp"),
                "artifact": evidence.get("artifact"),
                "outcome": evidence["outcome"],
                "contract": evidence.get("contract"),
            }
        )
    return rows


def _row_verdict(row: dict) -> str | None:
    outcome = row["outcome"]
    return (
        outcome.get("final_verdict")
        if outcome.get("decision") == "ACCEPT"
        else None
    )


def _row_desc(row: dict) -> str:
    outcome = row["outcome"]
    if outcome.get("decision") == "REJECT":
        return f"REJECT({outcome.get('error_kind')})"
    return (
        f"ACCEPT({outcome['final_verdict']}/"
        f"{outcome.get('final_confidence')}/{outcome.get('final_score')})"
    )


def classify_change(
    baseline_row: dict,
    candidate_row: dict,
    expected_status: str,
) -> tuple[str, str]:
    provider_error_kinds = {
        "TIMEOUT",
        "TRANSIENT",
        "UNAVAILABLE",
        "PERMANENT",
    }
    if baseline_row["outcome"].get("error_kind") in provider_error_kinds:
        return (
            "UNCLASSIFIED",
            f"baseline provider error {baseline_row['outcome'].get('error_kind')}; "
            f"candidate {_row_desc(candidate_row)}",
        )
    if candidate_row["outcome"].get("error_kind") in provider_error_kinds:
        return (
            "UNCLASSIFIED",
            f"candidate provider error {candidate_row['outcome'].get('error_kind')}; "
            f"baseline {_row_desc(baseline_row)}",
        )
    b = _row_verdict(baseline_row)
    c = _row_verdict(candidate_row)
    b_ok = b == expected_status
    c_ok = c == expected_status
    if b_ok and c_ok:
        return "UNCHANGED", f"both ACCEPT {b}"
    if not b_ok and c_ok:
        return (
            "IMPROVEMENT",
            f"baseline {_row_desc(baseline_row)} -> candidate ACCEPT {c}",
        )
    if b_ok and not c_ok:
        return (
            "REGRESSION",
            f"baseline ACCEPT {b} -> candidate {_row_desc(candidate_row)}",
        )
    return (
        "UNCHANGED",
        "both non-compliant: "
        f"baseline {_row_desc(baseline_row)}, "
        f"candidate {_row_desc(candidate_row)}",
    )


def evaluate_gate(
    target_b_rows: list[dict],
    target_c_rows: list[dict],
    matrix_rows: list[dict],
) -> dict:
    provider_error_kinds = {
        "TIMEOUT",
        "TRANSIENT",
        "UNAVAILABLE",
        "PERMANENT",
    }
    attempt_rows = list(target_b_rows) + list(target_c_rows)
    for row in matrix_rows:
        for key in ("baseline", "candidate"):
            if isinstance(row.get(key), dict):
                attempt_rows.append(row[key])
    errors = [
        row["case_id"]
        for row in attempt_rows
        if row["outcome"].get("error_kind") in provider_error_kinds
    ]
    b_verdicts = [_row_verdict(row) for row in target_b_rows]
    c_verdicts = [_row_verdict(row) for row in target_c_rows]
    target_fixed = (
        len(b_verdicts) == 3
        and all(v is None for v in b_verdicts)
        and len(c_verdicts) == 3
        and all(v == INCONCLUSIVE for v in c_verdicts)
    )
    reproducible = (
        len(c_verdicts) == 3 and len(set(c_verdicts)) == 1
    )
    regressions = [
        row["case_id"]
        for row in matrix_rows
        if row["change_type"] == "REGRESSION"
    ]
    if regressions:
        decision = "CANDIDATE_REJECTED"
    elif errors:
        decision = "INSUFFICIENT_EVIDENCE"
    elif not target_fixed or not reproducible:
        decision = "INSUFFICIENT_EVIDENCE"
    else:
        decision = "CANDIDATE_ACCEPTED_FOR_PROMOTION_REVIEW"
    return {
        "decision": decision,
        "checks": {
            "target_failure_fixed": target_fixed,
            "no_deterministic_regression": not regressions,
            "candidate_reproducible": reproducible,
            "provider_errors": sorted(set(errors)),
        },
    }


def _candidate_eval() -> int:
    provider = _second_provider("B")
    outdir = CANDIDATE_EVAL_DIR
    outdir.mkdir(parents=True, exist_ok=True)

    jinput = PHASE6D_DATASET.case("CAL-26").jinput()
    metadata = _candidate_metadata(jinput)
    write_debug_evidence(metadata, outdir / "candidate-b-v2-metadata.json")

    targeted = _attempt_rows(
        provider,
        jinput,
        "CAL-26",
        "B",
        None,
        None,
        3,
        outdir,
        tag="targeted",
    )
    targeted += _attempt_rows(
        provider,
        jinput,
        "CAL-26",
        "B-prime",
        B_PRIME_TEMPLATE,
        B_PRIME_INSTRUCTIONS,
        3,
        outdir,
        tag="targeted",
    )

    regression: list[dict] = []
    for case_id in REGRESSION_CASE_IDS:
        case_input = PHASE6D_DATASET.case(case_id).jinput()
        _verify_b_prime(case_input)
        regression += _attempt_rows(
            provider,
            case_input,
            case_id,
            "B",
            None,
            None,
            1,
            outdir,
            tag="matrix",
        )
        regression += _attempt_rows(
            provider,
            case_input,
            case_id,
            "B-prime",
            B_PRIME_TEMPLATE,
            B_PRIME_INSTRUCTIONS,
            1,
            outdir,
            tag="matrix",
        )

    with (outdir / "targeted-cal26.jsonl").open("w", encoding="utf-8") as fh:
        for row in targeted:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (outdir / "regression.jsonl").open("w", encoding="utf-8") as fh:
        for row in regression:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return _write_summary(targeted, regression)


def _matrix_rows(regression: list[dict]) -> list[dict]:
    matrix_rows = []
    for case_id in REGRESSION_CASE_IDS:
        b = next(
            row
            for row in regression
            if row["case_id"] == case_id and row["prompt_key"] == "B"
        )
        c = next(
            row
            for row in regression
            if row["case_id"] == case_id and row["prompt_key"] == "B-prime"
        )
        expected = PHASE6D_DATASET.case(case_id).expected_status
        change_type, reason = classify_change(b, c, expected)
        matrix_rows.append(
            {
                "case_id": case_id,
                "expected_status": expected,
                "baseline": b,
                "candidate": c,
                "changed": change_type != "UNCHANGED",
                "change_type": change_type,
                "reason": reason,
            }
        )
    return matrix_rows


def _write_summary(targeted: list[dict], regression: list[dict]) -> int:
    outdir = CANDIDATE_EVAL_DIR
    matrix_rows = _matrix_rows(regression)
    gate = evaluate_gate(
        [row for row in targeted if row["prompt_key"] == "B"],
        [row for row in targeted if row["prompt_key"] == "B-prime"],
        matrix_rows,
    )
    metadata_path = outdir / "candidate-b-v2-metadata.json"
    metadata = (
        json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata_path.exists()
        else {}
    )
    by_type = {
        kind: [
            row["case_id"]
            for row in matrix_rows
            if row["change_type"] == kind
        ]
        for kind in ("IMPROVEMENT", "REGRESSION", "UNCHANGED", "UNCLASSIFIED")
    }
    invalid = {
        prompt: [
            row["case_id"]
            for row in regression
            if row["prompt_key"] == prompt
            and row["outcome"].get("decision") == "REJECT"
            and row["outcome"].get("error_kind") == "INVALID_OUTPUT"
        ]
        for prompt in ("B", "B-prime")
    }
    provider_errors = {
        prompt: [
            row["case_id"]
            for row in regression
            if row["prompt_key"] == prompt
            if row["outcome"].get("error_kind")
            in ("TIMEOUT", "TRANSIENT", "UNAVAILABLE", "PERMANENT")
        ]
        for prompt in ("B", "B-prime")
    }
    summary = {
        "candidate_id": CANDIDATE_ID,
        "provenance": {
            "dataset_id": metadata.get("dataset_id", PHASE6D_DATASET.dataset_id),
            "dataset_version": metadata.get(
                "dataset_version", PHASE6D_DATASET.version
            ),
            "git_commit": metadata.get("git_commit", _git_commit()),
            "baseline_prompt_hash": metadata.get("baseline_prompt_hash"),
            "candidate_prompt_hash": metadata.get("candidate_prompt_hash"),
            "model": metadata.get("model", "qwen3.7-plus"),
            "temperature": metadata.get("temperature", 0.0),
            "seed": metadata.get("seed", 42),
        },
        "targeted_cal26": targeted,
        "matrix": matrix_rows,
        "aggregate": {
            "total_cases": len(matrix_rows),
            "improvements": by_type["IMPROVEMENT"],
            "regressions": by_type["REGRESSION"],
            "unchanged": by_type["UNCHANGED"],
            "unclassified": by_type["UNCLASSIFIED"],
            "counts": {
                kind: len(rows) for kind, rows in by_type.items()
            },
            "invalid_outputs": invalid,
            "provider_errors": provider_errors,
        },
        "gate": gate,
    }
    write_debug_evidence(summary, outdir / "candidate-matrix.json")
    print(f"GATE={gate['decision']}")
    print(f"matrix={summary['aggregate']}")
    return 0


def _summarize() -> int:
    outdir = CANDIDATE_EVAL_DIR
    with (outdir / "targeted-cal26.jsonl").open(encoding="utf-8") as fh:
        targeted = [json.loads(line) for line in fh]
    with (outdir / "regression.jsonl").open(encoding="utf-8") as fh:
        regression = [json.loads(line) for line in fh]
    return _write_summary(targeted, regression)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm-repeats",
        type=int,
        default=0,
        help="Phase 6-E.4: repeat CAL-26 B and B-prime this many times",
    )
    parser.add_argument(
        "--candidate-eval",
        action="store_true",
        help="Phase 6-E.5: targeted CAL-26 + regression gate",
    )
    parser.add_argument(
        "--summarize",
        action="store_true",
        help="Phase 6-E.5: recompute matrix/gate from saved candidate-eval artifacts",
    )
    args = parser.parse_args(argv)
    if args.summarize:
        return _summarize()
    if args.candidate_eval:
        return _candidate_eval()
    if args.confirm_repeats:
        provider = _second_provider("B")
        jinput = PHASE6D_DATASET.case("CAL-26").jinput()
        _verify_b_prime(jinput)
        for prompt_key, template, instructions in (
            ("B", None, None),
            ("B-prime", B_PRIME_TEMPLATE, B_PRIME_INSTRUCTIONS),
        ):
            for run_id in range(1, args.confirm_repeats + 1):
                _run_probe(
                    provider,
                    jinput,
                    "CAL-26",
                    prompt_key,
                    template,
                    instructions,
                    run_id=run_id,
                )
        return 0
    provider = _second_provider("B")
    for case_id in CASES:
        jinput = PHASE6D_DATASET.case(case_id).jinput()
        _verify_b_prime(jinput)
        for prompt_key, template, instructions in PROMPTS:
            _run_probe(provider, jinput, case_id, prompt_key, template, instructions)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
