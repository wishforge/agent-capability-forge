#!/usr/bin/env python3
"""Phase 7.5 static feasibility trace.

Read-only archaeology: real call chains, adoption points, decision-consumer
search, and bypass inventory. Parses source with ast only; never imports or
executes production code. Exits non-zero when an expected code fact no longer
holds (i.e. the proof is stale).
"""

from __future__ import annotations

import ast
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[4]

SCAN_GLOBS = (
    "pilot/*.py",
    "src/forge/*.py",
    "src/forge/codex_adapter/*.py",
    "research/control-plane-loop/*.py",
    "docs/archaeology/deepseek-harness/evaluation/*.py",
    "docs/archaeology/deepseek-harness/runtime/*.py",
    "docs/archaeology/deepseek-harness/runtime/backend/adapters/*.py",
    "docs/archaeology/python-cordis/kernel/*.py",
    "docs/archaeology/python-cordis/kernel/adapters/*.py",
    "docs/archaeology/python-cordis/kernel/semantic_layer/*.py",
)


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def parse(rel: str) -> ast.Module:
    return ast.parse(read(rel), filename=str(ROOT / rel))


def get_def(tree: ast.Module, name: str):
    return next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ),
        None,
    )


def param_names(fn) -> list[str]:
    args = fn.args
    return [p.arg for p in [*args.posonlyargs, *args.args, *args.kwonlyargs]]


def has_literal(node, value: str) -> bool:
    return any(isinstance(n, ast.Constant) and n.value == value for n in ast.walk(node))


def has_name(node, name: str) -> bool:
    return any(isinstance(n, ast.Name) and n.id == name for n in ast.walk(node))


def attr_calls(node, name: str) -> list[ast.Call]:
    return [
        c
        for c in ast.walk(node)
        if isinstance(c, ast.Call)
        and isinstance(c.func, ast.Attribute)
        and c.func.attr == name
    ]


def call_keywords(call: ast.Call) -> set[str]:
    return {k.arg for k in call.keywords if k.arg}


def py_files(globs: tuple[str, ...]) -> list[str]:
    out = []
    for pattern in globs:
        for p in sorted(ROOT.glob(pattern)):
            if ".pytest_cache" in p.parts or "__pycache__" in p.parts:
                continue
            out.append(p.relative_to(ROOT).as_posix())
    return out


def collect_facts() -> list[dict]:
    facts: list[dict] = []

    def fact(key: str, ok: bool, detail: str) -> None:
        facts.append({"key": key, "ok": bool(ok), "detail": detail})

    reg = parse("pilot/registry.py")
    promote = get_def(reg, "promote")
    discover = get_def(reg, "discover")
    fact(
        "registry.promote.has_no_decision_param",
        promote is not None
        and not ({"decision", "adoption", "adoption_request"} & set(param_names(promote))),
        "pilot/registry.py:17 promote() signature must not carry an adoption decision",
    )
    fact(
        "registry.promote.writes_state_promoted",
        promote is not None and has_literal(promote, "promoted"),
        "pilot/registry.py:36 writes state='promoted'",
    )
    fact(
        "registry.discover.checks_state_promoted_only",
        discover is not None
        and has_literal(discover, "promoted")
        and "decision" not in param_names(discover),
        "pilot/registry.py:64-69 discover() only checks state == 'promoted'",
    )

    harness = parse("pilot/harness.py")
    phase_b3 = get_def(harness, "phase_b3_build")
    phase_future = get_def(harness, "phase_future")
    fact(
        "harness.promote.call.has_no_decision",
        phase_b3 is not None
        and all(not ({"decision", "adoption"} & call_keywords(c)) for c in attr_calls(phase_b3, "promote")),
        "pilot/harness.py:593-600 calls registry.promote(...) without a decision",
    )
    fact(
        "runtime.invoke.trusts_discover_and_docker",
        phase_future is not None
        and bool(attr_calls(phase_future, "discover"))
        and has_name(phase_future, "docker_launch"),
        "pilot/harness.py:657-713 discover() -> docker_launch(entry['artifact_dir'])",
    )

    fact(
        "candidate.write.state_candidate",
        'state": "candidate' in read("src/forge/capabilityizer.py"),
        "src/forge/capabilityizer.py:117-118 writes candidate.json state='candidate'",
    )
    fact(
        "evaluation.writes_verdict",
        '"verdict"' in read("src/forge/evaluator.py") and "evaluation.json" in read("src/forge/evaluator.py"),
        "src/forge/evaluator.py:55,64,68 writes evaluation.json with verdict",
    )

    promo = parse("docs/archaeology/deepseek-harness/evaluation/promotion.py")
    decide = get_def(promo, "decide")
    policy_default_none = False
    if decide is not None:
        for i, arg in enumerate(decide.args.kwonlyargs):
            if arg.arg == "policy_ref":
                policy_default_none = i < len(decide.args.kw_defaults) and isinstance(
                    decide.args.kw_defaults[i], ast.Constant
                ) and decide.args.kw_defaults[i].value is None
    fact(
        "promotion.decide.policy_optional",
        decide is not None and policy_default_none,
        "docs/archaeology/deepseek-harness/evaluation/promotion.py:237 policy_ref defaults to None",
    )
    fact(
        "promotion.decide.uses_promoted_value",
        decide is not None and has_name(decide, "PROMOTED"),
        "docs/archaeology/deepseek-harness/evaluation/promotion.py:304 decision = PROMOTED",
    )
    fact(
        "promotion.decide.never_deploys",
        "Never deploys" in read("docs/archaeology/deepseek-harness/evaluation/promotion.py"),
        "promotion.py docstring: decision semantics only, never deploys/routes/writes",
    )

    bad_promote_calls = []
    for rel in py_files(SCAN_GLOBS):
        try:
            tree = parse(rel)
        except SyntaxError:
            continue
        for call in attr_calls(tree, "promote"):
            if {"decision", "adoption", "adoption_request"} & call_keywords(call):
                bad_promote_calls.append(f"{rel}:{call.lineno}")
    fact(
        "no.caller.passes.decision.to.promote",
        not bad_promote_calls,
        "no promote() call site in scanned code passes a decision/adoption argument"
        + (f"; found: {', '.join(bad_promote_calls)}" if bad_promote_calls else ""),
    )

    cp = read("research/control-plane-loop/promote.py")
    fact(
        "control_plane.writes.isActive.false",
        '"isActive": False' in cp,
        "research/control-plane-loop/promote.py:55 candidate registration is isActive=False",
    )

    mgr = parse("docs/archaeology/python-cordis/kernel/manager.py")
    register = get_def(mgr, "register")
    install = get_def(mgr, "install")
    fact(
        "manager.register.no_guard",
        register is not None
        and set(param_names(register)) <= {"self", "descriptor"}
        and "decision" not in param_names(register),
        "docs/archaeology/python-cordis/kernel/manager.py:52 register() has no adoption guard",
    )
    fact(
        "manager.install.no_guard",
        install is not None
        and set(param_names(install)) <= {"self", "capability_id"}
        and "decision" not in param_names(install),
        "docs/archaeology/python-cordis/kernel/manager.py:65 install() has no adoption guard",
    )
    cap = parse("docs/archaeology/python-cordis/kernel/capability.py")
    cap_install = get_def(cap, "install")
    fact(
        "capability.install.transitions_to_active",
        cap_install is not None
        and has_name(cap_install, "ACTIVE")
        and has_name(cap_install, "INSTALLING"),
        "docs/archaeology/python-cordis/kernel/capability.py:76-88 INSTALLING -> ACTIVE",
    )

    tr = parse("docs/archaeology/deepseek-harness/runtime/tool_runtime.py")
    tr_register = get_def(tr, "register")
    tr_src = read("docs/archaeology/deepseek-harness/runtime/tool_runtime.py")
    fact(
        "tool_runtime.register.no_adoption_guard",
        tr_register is not None
        and set(param_names(tr_register)) <= {"self", "registration"}
        and "decision" not in param_names(tr_register),
        "docs/archaeology/deepseek-harness/runtime/tool_runtime.py:76 register() has no adoption guard",
    )
    fact(
        "tool_runtime.approval.default_allow",
        "if self.approval is None:" in tr_src and "return True" in tr_src,
        "docs/archaeology/deepseek-harness/runtime/tool_runtime.py:255-258 approval=None => allow",
    )

    gate = parse("research/control-plane-loop/gate_calibration.py")
    gate_decide = get_def(gate, "gate_decide")
    gate_src = read("research/control-plane-loop/gate_calibration.py")
    fact(
        "second_consumer.gate_verdict_only",
        gate_decide is not None
        and has_literal(gate_decide, "verdict")
        and ".promote(" not in gate_src
        and "requests.post" not in gate_src,
        "research/control-plane-loop/gate_calibration.py:524 gate_decide() outputs verdict only",
    )

    lang = read("docs/archaeology/control-plane/langfuse/03-improvement-promotion.md")
    fact(
        "langfuse.label.manual_pointer",
        "唯一的部署指针" in lang and "无 eval gate" in lang,
        "Langfuse archaeology: label is the only deploy pointer; label move is manual/API, no eval gate",
    )
    return facts


def adoption_points() -> list[dict]:
    return [
        {
            "id": "pilot_registry_promote",
            "path": "pilot/registry.py:17,36",
            "operation": "WRITE / STATE TRANSITION",
            "current_authority": "caller of registry.promote() (pilot/harness.py:600)",
            "guard": "none",
        },
        {
            "id": "pilot_runtime_execute",
            "path": "pilot/registry.py:64,69 + pilot/harness.py:657,713",
            "operation": "READ / EXECUTE",
            "current_authority": "state=='promoted' + docker_launch of artifact_dir",
            "guard": "none",
        },
        {
            "id": "capability_manager_install",
            "path": "docs/archaeology/python-cordis/kernel/manager.py:52,65 + capability.py:88",
            "operation": "WRITE / STATE TRANSITION",
            "current_authority": "caller of register()+install()",
            "guard": "none",
        },
        {
            "id": "tool_runtime_register",
            "path": "docs/archaeology/deepseek-harness/runtime/tool_runtime.py:76,98,255",
            "operation": "WRITE / EXECUTE",
            "current_authority": "caller of ToolRuntime.register(); approval=None => allow",
            "guard": "none",
        },
        {
            "id": "langfuse_label_active",
            "path": "docs/archaeology/control-plane/langfuse/03-improvement-promotion.md:20-26",
            "operation": "EXTERNAL STATE TRANSITION",
            "current_authority": "human/API operator moving label/isActive",
            "guard": "none (external, UNKNOWN)",
        },
    ]


def bypasses() -> list[dict]:
    return [
        {
            "id": "B1",
            "path": "pilot/registry.py:17",
            "status": "FACT",
            "detail": "promote() accepts any evaluation dict; no decision/policy/provenance check",
        },
        {
            "id": "B2",
            "path": "docs/archaeology/python-cordis/kernel/manager.py:52,65",
            "status": "FACT",
            "detail": "register()+install() activates a capability without an adoption decision",
        },
        {
            "id": "B3",
            "path": "docs/archaeology/deepseek-harness/runtime/tool_runtime.py:76,255",
            "status": "FACT",
            "detail": "ToolRuntime.register() accepts any fn; approval=None defaults to allow",
        },
        {
            "id": "B4",
            "path": "pilot/state/candidates/F+/*/{candidate,validation,evaluation}.json",
            "status": "FACT",
            "detail": "flat JSON files are overwritable; no write-once provenance store",
        },
        {
            "id": "B5",
            "path": "research/control-plane-loop/promote.py:46-55",
            "status": "FACT / UNKNOWN",
            "detail": "repo sends isActive=False; direct Langfuse label/isActive activation is external",
        },
        {
            "id": "B6",
            "path": "src/forge/sandbox.py:12 + pilot/harness.py:713",
            "status": "FACT",
            "detail": "docker_launch mounts any host dir; runtime never verifies artifact digest/decision",
        },
        {
            "id": "B7",
            "path": "research/control-plane-loop/gate_calibration.py:524",
            "status": "FACT",
            "detail": "gate returns verdict only; no promotion write path",
        },
        {
            "id": "B8",
            "path": "docs/archaeology/deepseek-harness/evaluation/promotion.py:230,237,304",
            "status": "FACT",
            "detail": "decide() can emit PROMOTED with policy_ref=None; no consumer exists",
        },
    ]


def chains() -> dict:
    return {
        "pilot": [
            {"step": "capabilityize", "path": "src/forge/capabilityizer.py:54,117", "op": "WRITE"},
            {"step": "validate", "path": "src/forge/validator.py:69,96", "op": "WRITE"},
            {"step": "evaluate", "path": "src/forge/evaluator.py:24,55,68", "op": "WRITE"},
            {"step": "harness decide", "path": "pilot/harness.py:593-600", "op": "AUTHORIZATION (none)"},
            {"step": "registry.promote", "path": "pilot/registry.py:17,36", "op": "WRITE / STATE TRANSITION"},
            {"step": "registry.discover", "path": "pilot/registry.py:64,69", "op": "READ"},
            {"step": "docker_launch", "path": "pilot/harness.py:713 + src/forge/sandbox.py:12", "op": "EXECUTE"},
        ],
        "control_plane": [
            {"step": "policy frozen check", "path": "provider_probe.py:1337,1684-1690", "op": "AUTHORIZATION (evaluation layer)"},
            {"step": "promotion gate", "path": "provider_probe.py:1541", "op": "WRITE evidence"},
            {"step": "PromotionDecision", "path": "promotion.py:230,304", "op": "AUTHORIZATION (no consumer)"},
            {"step": "candidate registration", "path": "research/control-plane-loop/promote.py:46-55", "op": "WRITE isActive=False"},
            {"step": "Langfuse label", "path": "docs/archaeology/control-plane/langfuse/03-improvement-promotion.md:20-26", "op": "EXTERNAL STATE TRANSITION (manual)"},
        ],
        "capability_runtime": [
            {"step": "manager.register", "path": "docs/archaeology/python-cordis/kernel/manager.py:52", "op": "WRITE"},
            {"step": "manager.install", "path": "docs/archaeology/python-cordis/kernel/manager.py:65", "op": "AUTHORIZATION (none)"},
            {"step": "Capability.install", "path": "docs/archaeology/python-cordis/kernel/capability.py:76,88", "op": "STATE TRANSITION INSTALLING->ACTIVE"},
            {"step": "ToolRuntime.register/execute", "path": "docs/archaeology/deepseek-harness/runtime/tool_runtime.py:76,98,255", "op": "WRITE / EXECUTE (approval default allow)"},
        ],
    }


def build_report() -> dict:
    facts = collect_facts()
    all_ok = all(f["ok"] for f in facts)
    return {
        "schema": "phase7.5_trace_v1",
        "root": str(ROOT),
        "facts": facts,
        "adoption_points": adoption_points(),
        "bypasses": bypasses(),
        "chains": chains(),
        "verdict": "PRODUCTION_BOUNDARY_READY_WITH_UNKNOWN" if all_ok else "PRODUCTION_BOUNDARY_INVALID",
    }


def main() -> int:
    report = build_report()
    json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0 if report["verdict"] != "PRODUCTION_BOUNDARY_INVALID" else 1


if __name__ == "__main__":
    sys.exit(main())
