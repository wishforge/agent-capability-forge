#!/usr/bin/env python3
"""Phase 8.6 - read-only Repository Architecture V1 validator.

Checks that repository-structure-v1.md documents the architecture rules and
that current code facts do not contradict them. Does NOT require target
directories to exist; validates that the architecture rules are explicit.
Exits non-zero on the first failed check.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
DOC_PATH = "docs/architecture/repository-structure-v1.md"

REQUIRED_SECTIONS = [
    "Executive Summary",
    "Current Repository Map",
    "Product vs Pilot vs Research vs Archaeology",
    "src/ vs pilot/",
    "tests/ ownership",
    "docs/ ownership",
    "research/ ownership",
    "CapabilityCandidate ownership",
    "Source Adapter ownership",
    "Governance ownership",
    "Registry ownership",
    "Runtime ownership",
    "Dependency Direction",
    "Core / Extension / Governance Invariants",
    "Target Repository Structure",
    "Migration Strategy",
    "FACT / INFERENCE / UNKNOWN",
    "Open Questions",
    "Phase 9 Readiness",
]

OWNERSHIP_MARKERS = [
    "src/forge/candidate/",
    "src/forge/sources/",
    "src/forge/governance/",
    "src/forge/registry/",
    "src/forge/runtime/",
    "src/forge/provenance/",
    "SRC_ROLE",
    "PILOT_ROLE",
]

DEPENDENCY_MARKERS = [
    "sources",
    "candidate",
    "governance",
    "registry",
    "runtime adapters",
]

FORBIDDEN_SRC_IMPORTS = ("pilot", "research", "archaeology", "docs")
FORBIDDEN_PILOT_IMPORTS = ("research", "archaeology", "docs")
FORBIDDEN_RESEARCH_IMPORTS = ("forge", "pilot", "archaeology", "docs")


def _heading_matches(line: str, needle: str) -> bool:
    text = re.sub(r"^#+\s*", "", line.strip())
    text = re.sub(r"^\d+\.\s*", "", text)
    return needle.lower() in text.lower()


def _doc_checks(root: pathlib.Path) -> list[tuple[str, bool, str]]:
    doc = root / DOC_PATH
    if not doc.is_file():
        return [("doc exists", False, str(doc))]
    text = doc.read_text(encoding="utf-8")
    headings = [ln for ln in text.splitlines() if ln.strip().startswith("#")]
    results: list[tuple[str, bool, str]] = [("doc exists", True, "")]
    for section in REQUIRED_SECTIONS:
        ok = any(_heading_matches(ln, section) for ln in headings)
        results.append((f"doc section: {section}", ok, ""))
    for marker in OWNERSHIP_MARKERS:
        ok = marker in text
        results.append((f"ownership marker: {marker}", ok, ""))
    for marker in DEPENDENCY_MARKERS:
        ok = marker in text
        results.append((f"dependency marker: {marker}", ok, ""))
    return results


def _import_violations(root: pathlib.Path, rel: str, forbidden: tuple[str, ...]) -> list[str]:
    hits: list[str] = []
    for path in sorted((root / rel).rglob("*.py")):
        if any(part in {".venv", "state", "__pycache__"} for part in path.parts):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if not stripped.startswith(("from ", "import ")):
                continue
            if any(stripped.startswith(f"from {f}") or stripped.startswith(f"import {f}")
                   for f in forbidden):
                hits.append(f"{path.relative_to(root)}:{lineno}: {stripped}")
    return hits


def _code_checks(root: pathlib.Path) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []
    for name, rel, forbidden in [
        ("src has no pilot/research/archaeology imports", "src", FORBIDDEN_SRC_IMPORTS),
        ("pilot has no research/archaeology imports", "pilot", FORBIDDEN_PILOT_IMPORTS),
        ("research has no src/pilot/archaeology imports",
         "research", FORBIDDEN_RESEARCH_IMPORTS),
    ]:
        hits = _import_violations(root, rel, forbidden)
        results.append((name, not hits, ", ".join(hits)))
    harness = root / "pilot" / "harness.py"
    text = harness.read_text(encoding="utf-8") if harness.is_file() else ""
    results.append(("pilot imports forge (documented dependency)",
                    "from forge.sandbox import" in text, ""))
    return results


def run_checks(root: pathlib.Path = ROOT) -> list[tuple[str, bool, str]]:
    return _doc_checks(root) + _code_checks(root)


def main() -> int:
    results = run_checks()
    failed = 0
    for name, ok, detail in results:
        suffix = f"  [{detail}]" if detail and not ok else ""
        print(f"{'PASS' if ok else 'FAIL':4} {name}{suffix}")
        failed += int(not ok)
    if failed:
        print(f"\n{failed} check(s) failed -> architecture rules NOT explicit/coherent")
        return 1
    print("\nREPOSITORY_ARCHITECTURE_VALID_WITH_UNKNOWN: rules documented + code facts OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
