#!/usr/bin/env python3
"""Phase 7.6 adoption path inventory (static archaeology, offline).

The inventory table is the record of exhaustive archaeology. The scanner
re-verifies the machine-checkable facts behind the ADOPTION rows and asserts
every discovered path is classified and every ADOPTION path carries a target
authority requirement. Parses source with ast only; never imports or executes
production code. Never touches a real Registry / Runtime / Langfuse.
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "phase7.5"))

import trace_adoption_path as tap  # noqa: E402

ROOT = tap.ROOT
CLASSIFICATIONS = ("ADOPTION", "PREPARATION", "METADATA", "NON_ADOPTION")


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _parse(rel: str):
    return tap.parse(rel)


def _extra_facts() -> list[dict]:
    facts: list[dict] = []

    def fact(key: str, ok: bool, detail: str) -> None:
        facts.append({"key": key, "ok": bool(ok), "detail": detail})

    harness = _parse("pilot/harness.py")
    freeze_b2 = tap.get_def(harness, "phase_b2_freeze")
    freeze_b1 = tap.get_def(harness, "phase_b1_freeze")
    build_b3 = tap.get_def(harness, "phase_b3_build")
    future = tap.get_def(harness, "phase_future")
    fact(
        "b2.skill_ref.pointer.write",
        freeze_b2 is not None and 'skill_ref.json"' in _read("pilot/harness.py"),
        "pilot/harness.py:545 phase_b2_freeze() writes state/skill_ref.json (b2 skill pointer)",
    )
    fact(
        "b1.b1_skill_ref.pointer.write",
        freeze_b1 is not None and 'b1_skill_ref.json"' in _read("pilot/harness.py"),
        "pilot/harness.py:634 phase_b1_freeze() writes state/b1_skill_ref.json (b1 skill pointer)",
    )
    fact(
        "b3.b3_entry.pointer.write",
        build_b3 is not None and 'b3_entry.json"' in _read("pilot/harness.py"),
        "pilot/harness.py:601 phase_b3_build() writes state/b3_entry.json (b3 capability pointer)",
    )
    fact(
        "b3.future.uses.discover.and.docker",
        future is not None
        and bool(tap.attr_calls(future, "discover"))
        and tap.has_name(future, "docker_launch"),
        "pilot/harness.py:656-713 phase_future(b3) reads b3_entry -> registry.discover -> docker_launch",
    )

    mgr = _parse("docs/archaeology/python-cordis/kernel/manager.py")
    fact(
        "capability.register.install.no.decision",
        tap.get_def(mgr, "register") is not None
        and tap.get_def(mgr, "install") is not None
        and "decision" not in tap.param_names(tap.get_def(mgr, "register"))
        and "decision" not in tap.param_names(tap.get_def(mgr, "install")),
        "PluginManager.register()/install() accept no adoption authority",
    )
    agentscope = _read("docs/archaeology/python-cordis/kernel/adapters/agentscope.py")
    fact(
        "agentscope.register.exists.without.guard",
        "def register_tool(" in agentscope and "def register_service(" in agentscope,
        "agentscope adapter registers tools/services without adoption checks",
    )
    codex_src = _read("docs/archaeology/deepseek-harness/runtime/backend/adapters/codex.py")
    fact(
        "codex_adapter.accepts.any.rollout_path",
        "rollout_path: str | Path" in codex_src
        and "self.rollout_path = Path(rollout_path)" in codex_src,
        "CodexAdapter accepts any rollout_path; no registry/decision check",
    )
    bundle_src = _read("src/forge/bundle_producer.py")
    fact(
        "bundle.rule13.forbids.adoption.state",
        '"forged_artifact_digest", "revoked", "promoted", "instance_id"}' in bundle_src,
        "src/forge/bundle_producer.py:443 Rule 13 forbids candidate/promotion state in bundles",
    )
    return facts


INVENTORY: list[dict] = [
    {
        "path_id": "P-REG-01",
        "system": "pilot registry",
        "entrypoint": "pilot/registry.py:17 (promote)",
        "write_operation": "WRITE state='promoted' + artifact copy (line 36)",
        "state_mutated": "registry entry state / artifact_dir",
        "reader": "pilot/harness.py:657 discover; :793 gate p6",
        "actual_effect": "capability becomes runnable for B3 future tasks",
        "current_authorization": "harness phase_b3_build (verdict PASS + confirm.json), no decision",
        "bypass_risk": "HIGH: any evaluation dict accepted; flat JSON overwritable",
        "classification": "ADOPTION",
        "target_authority_requirement": "promote() must validate AdoptionAuthority before PROMOTABLE->PROMOTED and record authority binding",
    },
    {
        "path_id": "P-RT-01",
        "system": "pilot runtime",
        "entrypoint": "pilot/harness.py:656-713 phase_future(b3)",
        "write_operation": "READ b3_entry pointer -> discover -> EXECUTE docker_launch",
        "state_mutated": "run record treatment.capability_used + invoke evidence",
        "reader": "run_record.py validate_treatment",
        "actual_effect": "the capability artifact actually runs on a future task",
        "current_authorization": "registry.state == 'promoted' only",
        "bypass_risk": "HIGH: docker_launch mounts any artifact_dir; digest not verified before launch",
        "classification": "ADOPTION",
        "target_authority_requirement": "pre-launch legality verification of same AdoptionAuthority + artifact digest",
    },
    {
        "path_id": "P-RT-02",
        "system": "capability runtime",
        "entrypoint": "docs/archaeology/python-cordis/kernel/manager.py:52 register()",
        "write_operation": "WRITE in-memory CapabilityRecord (REGISTERED)",
        "state_mutated": "manager.records[capability_id]",
        "reader": "manager.get/list/install",
        "actual_effect": "descriptor visible; no instance runs yet",
        "current_authorization": "caller, no decision",
        "bypass_risk": "MEDIUM: registration alone is not activation",
        "classification": "PREPARATION",
        "target_authority_requirement": "n/a (activation is the guarded boundary)",
    },
    {
        "path_id": "P-RT-03",
        "system": "capability runtime",
        "entrypoint": "docs/archaeology/python-cordis/kernel/manager.py:65 install() + capability.py:76,88",
        "write_operation": "WRITE / STATE TRANSITION INSTALLING -> ACTIVE",
        "state_mutated": "Capability.state, PluginScope lifecycle",
        "reader": "manager/unload/dependents",
        "actual_effect": "capability instance becomes ACTIVE and callable",
        "current_authorization": "caller of register()+install(), no decision",
        "bypass_risk": "HIGH: install() activates any registered descriptor",
        "classification": "ADOPTION",
        "target_authority_requirement": "install()/Capability.install() must verify same AdoptionAuthority before INSTALLING->ACTIVE",
    },
    {
        "path_id": "P-RT-04",
        "system": "tool runtime (DSH)",
        "entrypoint": "docs/archaeology/deepseek-harness/runtime/tool_runtime.py:76 register()",
        "write_operation": "WRITE tool registry",
        "state_mutated": "ToolRuntime._tools[name]",
        "reader": "execute()",
        "actual_effect": "tool becomes callable by the agent",
        "current_authorization": "caller, no decision",
        "bypass_risk": "MEDIUM: registration alone does not execute; execution is the guarded boundary",
        "classification": "PREPARATION",
        "target_authority_requirement": "n/a (execute is the guarded boundary)",
    },
    {
        "path_id": "P-RT-05",
        "system": "tool runtime (DSH)",
        "entrypoint": "docs/archaeology/deepseek-harness/runtime/tool_runtime.py:98 execute() + :255-258 _approve()",
        "write_operation": "EXECUTE registered fn; approval=None -> allow",
        "state_mutated": "session event log (TOOL_CALL/TOOL_RESULT)",
        "reader": "surface.py active projection",
        "actual_effect": "the agent's tool call actually executes",
        "current_authorization": "per-registration pre_execute/guard; approval defaults to ALLOW",
        "bypass_risk": "HIGH: approval=None fail-open; no adoption/decision check",
        "classification": "ADOPTION",
        "target_authority_requirement": "execute() must fail closed on missing authority; approval=None must not grant adoption",
    },
    {
        "path_id": "P-RT-06",
        "system": "capability runtime adapter",
        "entrypoint": "docs/archaeology/python-cordis/kernel/adapters/agentscope.py:30,95",
        "write_operation": "WRITE AgentScope Toolkit/Service dict",
        "state_mutated": "external AgentScope tool/service registry (in-process)",
        "reader": "AgentScope runtime",
        "actual_effect": "tool/service visible to AgentScope; execution still needs a call",
        "current_authorization": "caller, no decision",
        "bypass_risk": "MEDIUM: registration only",
        "classification": "PREPARATION",
        "target_authority_requirement": "n/a (activation/call boundary is the guarded one)",
    },
    {
        "path_id": "P-RT-07",
        "system": "deepseek runtime (replay)",
        "entrypoint": "docs/archaeology/deepseek-harness/runtime/backend/adapters/codex.py:69-74",
        "write_operation": "SELECT rollout_path -> load/replay execution",
        "state_mutated": "runtime session stream",
        "reader": "AgentRuntime",
        "actual_effect": "the agent starts working from an arbitrary rollout file",
        "current_authorization": "caller, no registry/decision check",
        "bypass_risk": "HIGH: any path accepted; replay input is unauthenticated",
        "classification": "ADOPTION",
        "target_authority_requirement": "rollout selection must carry a validated authority or be explicitly non-production replay",
    },
    {
        "path_id": "P-EXT-01",
        "system": "Langfuse (external)",
        "entrypoint": "research/control-plane-loop/promote.py:46-55",
        "write_operation": "POST /api/public/prompts isActive=False + label control-plane-candidate",
        "state_mutated": "external prompt record (candidate label, not active)",
        "reader": "Langfuse SDK fetch-by-label",
        "actual_effect": "candidate registered; production pointer unchanged",
        "current_authorization": "LANGFUSE_* env credentials",
        "bypass_risk": "LOW for this code path (isActive=False); external direct writes are UNKNOWN",
        "classification": "PREPARATION",
        "target_authority_requirement": "n/a (candidate registration only)",
    },
    {
        "path_id": "P-EXT-02",
        "system": "Langfuse (external)",
        "entrypoint": "docs/archaeology/control-plane/langfuse/03-improvement-promotion.md:20-26",
        "write_operation": "EXTERNAL STATE TRANSITION: label move / isActive pointer swap",
        "state_mutated": "external prompt label -> production pointer",
        "reader": "SDK fetch-by-label (src/integrations/langfuse.ts)",
        "actual_effect": "production prompt served to agents",
        "current_authorization": "human/API operator; no eval gate",
        "bypass_risk": "HIGH: server-side enforcement UNKNOWN; repo cannot see or block direct writes",
        "classification": "ADOPTION",
        "target_authority_requirement": "pointer move must go through a guarded wrapper validating same AdoptionAuthority, or be explicitly marked external-uncontrollable",
    },
    {
        "path_id": "P-CFG-01",
        "system": "pilot config pointer",
        "entrypoint": "pilot/harness.py:601 phase_b3_build()",
        "write_operation": "WRITE state/b3_entry.json {name, capability_id}",
        "state_mutated": "b3_entry.json (derived pointer)",
        "reader": "pilot/harness.py:656 phase_future(b3)",
        "actual_effect": "selects which promoted registry entry the runtime uses",
        "current_authorization": "same caller as promote; no independent check",
        "bypass_risk": "MEDIUM: direct edit changes selection; discover still gates on state",
        "classification": "METADATA",
        "target_authority_requirement": "pointer must be derived from a validated authority record, not hand-editable",
    },
    {
        "path_id": "P-CFG-02",
        "system": "pilot config pointer (b2)",
        "entrypoint": "pilot/harness.py:545 phase_b2_freeze()",
        "write_operation": "WRITE state/skill_ref.json {name, path, digest}",
        "state_mutated": "skill_ref.json + frozen skill copy",
        "reader": "pilot/harness.py:652 phase_future(b2)",
        "actual_effect": "future Codex runs use the generated frozen skill",
        "current_authorization": "phase_b2_freeze caller; no decision",
        "bypass_risk": "HIGH: pointer + frozen dir editable; skill adopted with no authority",
        "classification": "ADOPTION",
        "target_authority_requirement": "skill_ref write must bind to same AdoptionAuthority contract (candidate/version/decision/digest) or be explicitly experiment-only",
    },
    {
        "path_id": "P-CFG-03",
        "system": "pilot config pointer (b1)",
        "entrypoint": "pilot/harness.py:634 phase_b1_freeze()",
        "write_operation": "WRITE state/b1_skill_ref.json {name, path, digest}",
        "state_mutated": "b1_skill_ref.json + frozen skill copy",
        "reader": "pilot/harness.py:648 phase_future(b1)",
        "actual_effect": "future Codex runs use the operator-curated frozen skill",
        "current_authorization": "pilot/b1_curated_skill.json (human_minutes flag), no decision",
        "bypass_risk": "HIGH: pointer + frozen dir editable",
        "classification": "ADOPTION",
        "target_authority_requirement": "b1_skill_ref write must bind to same AdoptionAuthority contract or be explicitly experiment-only",
    },
    {
        "path_id": "P-CFG-04",
        "system": "pilot config",
        "entrypoint": "pilot/harness.py:529,614 frozen skill copies",
        "write_operation": "WRITE pilot/skills/frozen/... copies",
        "state_mutated": "frozen skill files on disk",
        "reader": "phase_future via skill_ref/b1_skill_ref",
        "actual_effect": "bytes available for a future run; no selection yet",
        "current_authorization": "freeze phase caller",
        "bypass_risk": "LOW alone; becomes effective through P-CFG-02/03",
        "classification": "PREPARATION",
        "target_authority_requirement": "n/a",
    },
    {
        "path_id": "P-CFG-05",
        "system": "pilot config",
        "entrypoint": "pilot/confirm.json",
        "write_operation": "READ operator confirm flag (harness.py:560)",
        "state_mutated": "none (read-only)",
        "reader": "phase_b3_build",
        "actual_effect": "today's 'human approval' record: operator string only",
        "current_authorization": "manual file edit",
        "bypass_risk": "HIGH as approval record: no identity detail/timestamp/policy/decision",
        "classification": "METADATA",
        "target_authority_requirement": "replace with persisted human approval event (approved_by/at/scope/reason) feeding PromotionDecision",
    },
    {
        "path_id": "P-CFG-06",
        "system": "pilot candidate store",
        "entrypoint": "src/forge/capabilityizer.py:117, validator.py:96, evaluator.py:68",
        "write_operation": "WRITE candidate.json / validation.json / evaluation.json",
        "state_mutated": "candidate lifecycle + evidence files",
        "reader": "harness phase_b3_build, registry.promote",
        "actual_effect": "candidate exists and has evidence; nothing runs yet",
        "current_authorization": "pipeline phases; no decision",
        "bypass_risk": "MEDIUM: flat JSON overwritable (write-once missing)",
        "classification": "PREPARATION",
        "target_authority_requirement": "n/a",
    },
    {
        "path_id": "P-CFG-07",
        "system": "control plane",
        "entrypoint": "provider_probe.py:1337,1541,1684 + promotion-policy.json",
        "write_operation": "WRITE policy/gate evidence (registered + frozen policy)",
        "state_mutated": "policy/gate evidence artifacts",
        "reader": "evaluate_promotion_gate / promotion.decide",
        "actual_effect": "evaluation-layer authorization only; does not adopt",
        "current_authorization": "E.7 runner policy-frozen enforcement",
        "bypass_risk": "LOW at evaluation layer; mutable policy copy was a historical gap (56a)",
        "classification": "PREPARATION",
        "target_authority_requirement": "n/a (policy is an input to the authority, not the authority)",
    },
    {
        "path_id": "P-CFG-08",
        "system": "second consumer gate",
        "entrypoint": "research/control-plane-loop/gate_calibration.py:524 gate_decide()",
        "write_operation": "WRITE verdict JSON (PASS/FAIL/INCONCLUSIVE)",
        "state_mutated": "verdict output only",
        "reader": "experiment reports",
        "actual_effect": "no adoption write path",
        "current_authorization": "gate logic",
        "bypass_risk": "NONE for adoption (verdict only)",
        "classification": "METADATA",
        "target_authority_requirement": "n/a",
    },
    {
        "path_id": "P-CFG-09",
        "system": "control plane decision object",
        "entrypoint": "docs/archaeology/deepseek-harness/evaluation/promotion.py:230 decide()",
        "write_operation": "WRITE in-memory PromotionDecision (no consumer)",
        "state_mutated": "none persisted",
        "reader": "none (no consumer found)",
        "actual_effect": "decision record only; never writes registry/runtime",
        "current_authorization": "decide() gates; policy_ref optional; value PROMOTED naming conflict",
        "bypass_risk": "HIGH as authority source: unenforced, no durable store",
        "classification": "METADATA",
        "target_authority_requirement": "PromotionDecision must become the seed of a durable AdoptionAuthority consumed by registry/runtime",
    },
    {
        "path_id": "P-CFG-10",
        "system": "pilot bundle store",
        "entrypoint": "src/forge/bundle_producer.py:440-455 Rule 13",
        "write_operation": "WRITE sealed bundles",
        "state_mutated": "bundle artifacts + digest",
        "reader": "capabilityizer",
        "actual_effect": "sealed inputs for candidate forging; Rule 13 forbids adoption state inside",
        "current_authorization": "bundle producer",
        "bypass_risk": "LOW: digest-sealed preparation input",
        "classification": "PREPARATION",
        "target_authority_requirement": "n/a",
    },
    {
        "path_id": "P-CFG-11",
        "system": "environment / config",
        "entrypoint": "pilot/config.json, LANGFUSE_* env, CODEX_HOME",
        "write_operation": "READ model/sandbox/credential/config inputs",
        "state_mutated": "none (process configuration only)",
        "reader": "harness, control-plane-loop scripts",
        "actual_effect": "shapes how work runs; never selects which capability/version is adopted",
        "current_authorization": "operator environment",
        "bypass_risk": "NONE for adoption identity (no pointer semantics)",
        "classification": "NON_ADOPTION",
        "target_authority_requirement": "n/a",
    },
]


def collect_facts() -> list[dict]:
    return tap.collect_facts() + _extra_facts()


def verify_inventory(facts: list[dict]) -> list[dict]:
    problems: list[dict] = []
    for entry in INVENTORY:
        missing = [
            k
            for k in (
                "path_id",
                "system",
                "entrypoint",
                "write_operation",
                "state_mutated",
                "reader",
                "actual_effect",
                "current_authorization",
                "bypass_risk",
                "classification",
            )
            if not entry.get(k)
        ]
        if missing:
            problems.append(
                {"path_id": entry.get("path_id"), "problem": f"missing fields: {','.join(missing)}"}
            )
        if entry.get("classification") not in CLASSIFICATIONS:
            problems.append(
                {
                    "path_id": entry.get("path_id"),
                    "problem": f"unclassified: {entry.get('classification')}",
                }
            )
        if entry.get("classification") == "ADOPTION" and not entry.get(
            "target_authority_requirement"
        ):
            problems.append(
                {"path_id": entry.get("path_id"), "problem": "ADOPTION path has no target authority requirement"}
            )
    for f in facts:
        if not f["ok"]:
            problems.append({"fact": f["key"], "problem": f["detail"]})
    return problems


def build_report() -> dict:
    facts = collect_facts()
    problems = verify_inventory(facts)
    counts: dict[str, int] = {}
    for entry in INVENTORY:
        counts[entry["classification"]] = counts.get(entry["classification"], 0) + 1
    return {
        "schema": "phase7.6_inventory_v1",
        "root": str(ROOT),
        "facts": facts,
        "inventory": INVENTORY,
        "classification_counts": counts,
        "problems": problems,
        "verdict": (
            "ADOPTION_PATH_INVENTORY_VALID"
            if not problems
            else "ADOPTION_PATH_INVENTORY_STALE"
        ),
    }


def main() -> int:
    report = build_report()
    json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0 if report["verdict"] == "ADOPTION_PATH_INVENTORY_VALID" else 1


if __name__ == "__main__":
    sys.exit(main())
