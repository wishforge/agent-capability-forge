"""Phase 6-E experiment matrix runner + analyzer (evaluation-side only).

Subcommands:
    offline   fake_judge x A/B/C x (44 cases + 2 probes)
    deepseek  DeepSeek x A/B/C x (44 cases + 2 probes)
    second    Model Studio (qwen3.7-plus) x A/B/C x (44 cases + 2 probes)
    analyze   compute metrics from persisted artifacts -> phase6e-summary.json

Provider failures are persisted as error records, never silently dropped.
No secrets are written to artifacts or printed.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import tomllib
from datetime import datetime, timezone
from typing import Any

EVAL = pathlib.Path(__file__).resolve().parent
for path in (EVAL, EVAL.parent / "runtime"):
    sys.path.insert(0, str(path))

from calibration import (  # noqa: E402
    PHASE6D_DATASET,
    PHASE6E_PROBES,
    append_calibration_run,
    calibration_run_record,
    probe_run_record,
)
from judge_provider import (  # noqa: E402
    PROMPT_TEMPLATES,
    DeepSeekJudgeProvider,
    provider_status,
)
from llm_judge import FAIL, INCONCLUSIVE, PASS, fake_judge  # noqa: E402

ARTIFACTS = EVAL / "artifacts"
DEBUG_DIR = ARTIFACTS / "provider-debug"
SECOND_PROVIDER_NAME = "Model_Studio_Token_Plan_Personal"
SECOND_MODEL = "qwen3.7-plus"
BACKENDS = ("fake", "deepseek", "model_studio")
PROMPTS = ("A", "B", "C")
FILE_PREFIX = {"fake": "offline", "deepseek": "deepseek", "model_studio": "second"}


class FakeJudgeProvider:
    backend_ref = "fake"
    last_usage = None
    last_payload = None

    def __init__(self, prompt_key: str) -> None:
        self.prompt_key = prompt_key

    def judge(self, jinput, *, prompt_key: str | None = None, rubric=None):
        template = PROMPT_TEMPLATES[prompt_key or self.prompt_key]
        return fake_judge(
            jinput,
            prompt_ref=template.prompt_ref,
            prompt_version=template.prompt_version,
        )


def _second_provider(prompt_key: str) -> DeepSeekJudgeProvider:
    cfg = tomllib.loads(
        pathlib.Path(os.path.expanduser("~/.codex/config.toml")).read_text(
            encoding="utf-8"
        ),
    )
    prov = cfg["model_providers"][SECOND_PROVIDER_NAME]
    api_key = os.environ.get(prov["env_key"])
    if not api_key:
        raise RuntimeError(f"BLOCKED: SECOND_BACKEND_UNAVAILABLE ({prov['env_key']!r} not set)")
    return DeepSeekJudgeProvider(
        model=SECOND_MODEL,
        base_url=prov["base_url"],
        api_key=api_key,
        backend_ref="model_studio",
        prompt_key=prompt_key,
        temperature=0.0,
        seed=42,
    )


def write_debug_evidence(evidence: dict, path: pathlib.Path) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _error_record(
    case_id: str,
    prompt_key: str,
    backend_ref: str,
    exc: Exception,
    *,
    provider: Any = None,
) -> dict:
    record = {
        "case_id": case_id,
        "prompt_key": prompt_key,
        "backend_ref": backend_ref,
        "provider_error": {
            "kind": getattr(exc, "kind", type(exc).__name__),
            "message": str(exc)[:300],
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    evidence = getattr(exc, "evidence", None)
    if evidence is not None and provider is not None:
        evidence = dict(evidence)
        evidence.update(
            case_id=case_id,
            prompt_key=prompt_key,
            timestamp=record["timestamp"],
        )
        path = write_debug_evidence(
            evidence,
            DEBUG_DIR / f"{case_id}-{backend_ref}-{prompt_key}.json",
        )
        try:
            record["debug_artifact"] = str(path.relative_to(EVAL))
        except ValueError:
            record["debug_artifact"] = str(path)
    return record


def _run_leg(
    provider: Any,
    prompt_key: str,
    backend_ref: str,
    out44: pathlib.Path,
    outprobes: pathlib.Path,
    case_ids: tuple[str, ...] | None = None,
) -> None:
    out44.write_text("", encoding="utf-8")
    outprobes.write_text("", encoding="utf-8")
    cases = (
        PHASE6D_DATASET.cases
        if case_ids is None
        else tuple(PHASE6D_DATASET.case(cid) for cid in case_ids)
    )
    for case in cases:
        try:
            result = provider.judge(case.jinput(), prompt_key=prompt_key)
            record = calibration_run_record(
                PHASE6D_DATASET,
                case,
                result,
                usage=getattr(provider, "last_usage", None),
                prompt_key=prompt_key,
                backend_ref=backend_ref,
                raw_payload=getattr(provider, "last_payload", None),
            )
        except Exception as exc:  # noqa: BLE001 - provider failures are evidence
            record = _error_record(
                case.case_id,
                prompt_key,
                backend_ref,
                exc,
                provider=provider,
            )
        append_calibration_run(out44, record)
    for probe in PHASE6E_PROBES:
        try:
            result = provider.judge(probe.jinput, prompt_key=prompt_key)
            record = probe_run_record(
                probe,
                result,
                usage=getattr(provider, "last_usage", None),
                prompt_key=prompt_key,
                backend_ref=backend_ref,
                raw_payload=getattr(provider, "last_payload", None),
            )
        except Exception as exc:  # noqa: BLE001
            record = _error_record(
                probe.case_id,
                prompt_key,
                backend_ref,
                exc,
                provider=provider,
            )
        append_calibration_run(outprobes, record)


def _load(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _pairwise_agreement(values: list[Any]) -> float:
    pairs = [(a, b) for i, a in enumerate(values) for b in values[i + 1 :]]
    return sum(a == b for a, b in pairs) / len(pairs) if pairs else 1.0


def _mean_pairwise_agreement(run_groups) -> float:
    groups = [list(group) for group in run_groups]
    per_case = [
        _pairwise_agreement(group)
        for group in groups
        if len(group) >= 2
    ]
    return sum(per_case) / len(per_case) if per_case else 1.0


def _condition_key(record: dict) -> tuple:
    return tuple(
        (item["condition_id"], item["status"])
        for item in record.get("condition_statuses", [])
    )


def _status_counts(records: list[dict]) -> dict:
    counts = {status: 0 for status in (PASS, FAIL, INCONCLUSIVE)}
    for record in records:
        status = record.get("final_verdict")
        if status in counts:
            counts[status] += 1
    return counts


def _expected_status(case_id: str) -> str | None:
    try:
        return PHASE6D_DATASET.case(case_id).expected_status
    except KeyError:
        for probe in PHASE6E_PROBES:
            if probe.case_id == case_id:
                return probe.expected_status
    return None


def _analyze() -> dict:
    records: list[dict] = []
    expected_case_ids = {case.case_id for case in PHASE6D_DATASET.cases}
    for backend in BACKENDS:
        for prompt in PROMPTS:
            prefix = FILE_PREFIX[backend]
            main = _load(ARTIFACTS / f"phase6e-{prefix}-44-{prompt}.jsonl")
            records += main
            missing = sorted(
                expected_case_ids
                - {r["case_id"] for r in main if "provider_error" not in r}
            )
            for suffix in ("-repro", "-retry", "-retry2", "-retry3"):
                if not missing:
                    break
                for record in _load(
                    ARTIFACTS / f"phase6e-{prefix}-44-{prompt}{suffix}.jsonl"
                ):
                    if record.get("case_id") in missing and "provider_error" not in record:
                        merged = dict(record)
                        merged["rerun_source"] = suffix.lstrip("-")
                        records.append(merged)
                        missing.remove(record["case_id"])
            main_probes = _load(
                ARTIFACTS / f"phase6e-{prefix}-probes-{prompt}.jsonl"
            )
            records += main_probes
            missing_probes = sorted(
                {"PROBE-S1", "PROBE-S2"}
                - {r["case_id"] for r in main_probes if "provider_error" not in r}
            )
            for suffix in ("-repro", "-retry", "-retry2"):
                if not missing_probes:
                    break
                for record in _load(
                    ARTIFACTS / f"phase6e-{prefix}-probes-{prompt}{suffix}.jsonl"
                ):
                    if record.get("case_id") in missing_probes and "provider_error" not in record:
                        merged = dict(record)
                        merged["rerun_source"] = suffix.lstrip("-")
                        records.append(merged)
                        missing_probes.remove(record["case_id"])
    probe_records = [r for r in records if r.get("case_id", "").startswith("PROBE-")]
    case_records = [r for r in records if not r.get("case_id", "").startswith("PROBE-")]
    errors = [r for r in records if "provider_error" in r]
    valid = [r for r in case_records if "provider_error" not in r]

    by_case: dict[str, list[dict]] = {}
    for record in valid:
        by_case.setdefault(record["case_id"], []).append(record)

    deterministic = {
        "cases": len(by_case),
        "rules_status_agreement": _mean_pairwise_agreement(
            [r["deterministic_status"] for r in runs] for runs in by_case.values()
        ),
        "evidence_agreement": _mean_pairwise_agreement(
            [r["evidence_sufficiency"] for r in runs] for runs in by_case.values()
        ),
        "behavioral_agreement": _mean_pairwise_agreement(
            [r["oracle_status"] for r in runs] for runs in by_case.values()
        ),
        "condition_agreement": _mean_pairwise_agreement(
            [_condition_key(r) for r in runs] for runs in by_case.values()
        ),
        "deterministic_verdict_agreement": _mean_pairwise_agreement(
            [r["deterministic_verdict"] for r in runs] for runs in by_case.values()
        ),
    }

    def _layer_agreement(field: str) -> dict:
        prompt_agreement: dict[str, float] = {}
        for prompt in PROMPTS:
            prompt_agreement[prompt] = _mean_pairwise_agreement(
                [
                    r[field]
                    for r in by_case[case_id]
                    if r.get("prompt_key") == prompt
                ]
                for case_id in by_case
            )
        backend_agreement: dict[str, float] = {}
        for backend in BACKENDS:
            backend_agreement[backend] = _mean_pairwise_agreement(
                [
                    r[field]
                    for r in by_case[case_id]
                    if r.get("backend_ref") == backend
                ]
                for case_id in by_case
            )
        overall = _mean_pairwise_agreement(
            [r[field] for r in runs] for runs in by_case.values()
        )
        return {
            "prompt_agreement": prompt_agreement,
            "backend_agreement": backend_agreement,
            "overall": overall,
        }

    judge_layer = _layer_agreement("final_verdict")
    unified_layer = _layer_agreement("unified_final_verdict")

    false_pass: dict[str, dict[str, int]] = {}
    false_fail: dict[str, dict[str, int]] = {}
    for backend in BACKENDS:
        false_pass[backend] = {}
        false_fail[backend] = {}
        for prompt in PROMPTS:
            group = [
                r
                for r in valid
                if r["backend_ref"] == backend and r["prompt_key"] == prompt
            ]
            false_pass[backend][prompt] = sum(
                _expected_status(r["case_id"]) not in (None, PASS)
                and r["final_verdict"] == PASS
                for r in group
            )
            false_fail[backend][prompt] = sum(
                _expected_status(r["case_id"]) == PASS
                and r["final_verdict"] == FAIL
                for r in group
            )

    score_cases: list[str] = []
    confidence_cases: list[str] = []
    score_pair_diffs = 0
    confidence_pair_diffs = 0
    reasoning_cases: list[str] = []
    for case_id, runs in by_case.items():
        scores = [r["score"] for r in runs if r.get("score") is not None]
        if len(scores) >= 2:
            pairs = [(a, b) for i, a in enumerate(scores) for b in scores[i + 1 :]]
            if any(a != b for a, b in pairs):
                score_cases.append(case_id)
                score_pair_diffs += sum(a != b for a, b in pairs)
        confidences = [r["confidence"] for r in runs]
        if len(confidences) >= 2:
            pairs = [
                (a, b)
                for i, a in enumerate(confidences)
                for b in confidences[i + 1 :]
            ]
            if any(a != b for a, b in pairs):
                confidence_cases.append(case_id)
                confidence_pair_diffs += sum(a != b for a, b in pairs)
        fallback = [r for r in runs if r.get("llm_fallback_used")]
        fallback_reasoning = [
            (r.get("reasoning_summary") or (r.get("raw_payload_normalized") or {}).get("reasoning_summary"))
            for r in fallback
        ]
        if len({text for text in fallback_reasoning if text}) > 1:
            reasoning_cases.append(case_id)

    transition_labels = (
        f"{a}->{b}"
        for a in (PASS, FAIL, INCONCLUSIVE)
        for b in (PASS, FAIL, INCONCLUSIVE)
        if a != b
    )
    transitions: dict[str, list[str]] = {label: [] for label in transition_labels}
    bypass: list[str] = []
    raw_parse_diffs: list[dict] = []
    for case_id, runs in by_case.items():
        for i, left in enumerate(runs):
            for right in runs[i + 1 :]:
                if left["final_verdict"] != right["final_verdict"]:
                    label = f"{left['final_verdict']}->{right['final_verdict']}"
                    if case_id not in transitions[label]:
                        transitions[label].append(case_id)
        for record in runs:
            if record.get("deterministic_verdict") in (FAIL, INCONCLUSIVE):
                if record["final_verdict"] == PASS:
                    bypass.append(case_id)
            raw = record.get("raw_payload_normalized") or {}
            if isinstance(raw, dict) and raw.get("status") is not None:
                if raw["status"] != record["final_verdict"]:
                    raw_parse_diffs.append(
                        {
                            "case_id": case_id,
                            "backend_ref": record["backend_ref"],
                            "prompt_key": record["prompt_key"],
                            "raw_status": raw["status"],
                            "final_verdict": record["final_verdict"],
                            "aggregation_source": record["aggregation_source"],
                        }
                    )

    probes: dict[str, dict] = {}
    for probe_id in ("PROBE-S1", "PROBE-S2"):
        group = [
            r
            for r in probe_records
            if r.get("case_id") == probe_id and "provider_error" not in r
        ]
        probes[probe_id] = {
            backend: {
                prompt: next(
                    (
                        {
                            "final_verdict": r["final_verdict"],
                            "score": r["score"],
                            "confidence": r["confidence"],
                            "aggregation_source": r["aggregation_source"],
                        }
                        for r in group
                        if r["backend_ref"] == backend and r["prompt_key"] == prompt
                    ),
                    None,
                )
                for prompt in PROMPTS
            }
            for backend in BACKENDS
        }

    error_counts: dict[str, int] = {}
    for record in errors:
        error_counts[record["backend_ref"]] = error_counts.get(record["backend_ref"], 0) + 1

    return {
        "second_backend_status": provider_status(SECOND_PROVIDER_NAME),
        "run_counts": {
            backend: {
                prompt: len(
                    [
                        r
                        for r in case_records
                        if r.get("backend_ref") == backend
                        and r.get("prompt_key") == prompt
                        and "provider_error" not in r
                    ]
                )
                for prompt in PROMPTS
            }
            for backend in BACKENDS
        },
        "provider_errors": error_counts,
        "deterministic": deterministic,
        "judge_layer": judge_layer,
        "unified_layer": unified_layer,
        "false_pass": false_pass,
        "false_fail": false_fail,
        "status_balance": {
            backend: {prompt: _status_counts([r for r in valid if r["backend_ref"] == backend and r["prompt_key"] == prompt]) for prompt in PROMPTS}
            for backend in BACKENDS
        },
        "score": {
            "disagreement_cases": sorted(score_cases),
            "disagreement_case_count": len(score_cases),
            "pair_diffs": score_pair_diffs,
        },
        "confidence": {
            "disagreement_cases": sorted(confidence_cases),
            "disagreement_case_count": len(confidence_cases),
            "pair_diffs": confidence_pair_diffs,
        },
        "reasoning_variance_cases": sorted(reasoning_cases),
        "transitions": transitions,
        "deterministic_bypass_cases": sorted(bypass),
        "raw_parse_diffs": raw_parse_diffs,
        "llm_fallback_cases": sorted(
            {
                case_id
                for case_id, runs in by_case.items()
                if any(r.get("aggregation_source") == "LLM_FALLBACK" for r in runs)
            }
        ),
        "probes": probes,
    }


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("offline", "deepseek", "second"):
        p = sub.add_parser(name)
        p.add_argument("--prompt", choices=PROMPTS, default=None)
        p.add_argument("--subset", default=None, help="comma-separated case_ids")
        p.add_argument("--suffix", default="", help="artifact filename suffix (e.g. repro-A)")
    sub.add_parser("analyze")
    args = parser.parse_args(argv)

    if args.command == "analyze":
        summary = _analyze()
        out = ARTIFACTS / "phase6e-summary.json"
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    prompts = PROMPTS if args.prompt is None else (args.prompt,)
    subset = tuple(part.strip() for part in args.subset.split(",")) if args.subset else None
    for prompt in prompts:
        suffix = args.suffix or ""
        out44 = ARTIFACTS / f"phase6e-{args.command}-44-{prompt}{suffix}.jsonl"
        outprobes = ARTIFACTS / f"phase6e-{args.command}-probes-{prompt}{suffix}.jsonl"
        if args.command == "offline":
            provider = FakeJudgeProvider(prompt)
        elif args.command == "deepseek":
            available, reason = provider_status("deepseek")
            if not available:
                print(f"BLOCKED: {reason}")
                return 1
            provider = DeepSeekJudgeProvider(prompt_key=prompt, backend_ref="deepseek")
        else:
            available, reason = provider_status(SECOND_PROVIDER_NAME)
            if not available:
                print(f"BLOCKED: SECOND_BACKEND_UNAVAILABLE: {reason}")
                return 1
            provider = _second_provider(prompt)
        print(f"running {args.command} prompt={prompt} subset={subset or 'all'} -> {out44}")
        _run_leg(
            provider,
            prompt,
            getattr(provider, "backend_ref", args.command),
            out44,
            outprobes,
            case_ids=subset,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
