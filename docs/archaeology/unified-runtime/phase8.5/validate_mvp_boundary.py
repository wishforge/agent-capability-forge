#!/usr/bin/env python3
"""Phase 8.5 - read-only MVP Security Boundary validator.

Checks that the 78 report's boundary claims are supported by current pilot
code facts, and that the report does not claim platform-level protection
for deployment / enterprise responsibilities. Does not import or run
production logic. Exits non-zero on the first failed check.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[4]
DOC_PATH = "docs/archaeology/unified-runtime/78-production-trust-boundary-mvp-closure.md"

CODE_FACTS: list[tuple[str, str, str]] = [
    ("promotion gate / authority issuer",
     "pilot/adoption_authority_producer.py", "def issue_authority("),
    ("registry requires authority",
     "pilot/registry.py", "if adoption_authority is None:"),
    ("registry validates authority",
     "pilot/registry.py",
     "report = validate(adoption_authority, store, actual_digest, registry_root)"),
    ("registry anchor check",
     "pilot/registry.py",
     "anchor_violations = integrity_anchor_violations(store, registry_root)"),
    ("runtime adopt before launch",
     "pilot/harness.py",
     "adopted = runtime_guard.adopt(self.registry_root, entry, artifact_dir)"),
    ("mount recheck before launch",
     "pilot/harness.py", "runtime_guard.verify_at_mount("),
    ("read-only artifact mount",
     "pilot/harness.py", '(artifact_dir, "/artifact", True)'),
    ("revocation fail-closed",
     "pilot/runtime_adoption_guard.py", '"REVOKED_DECISION"'),
    ("write-once ledger",
     "pilot/adoption_authority.py", "def write_authority_record("),
    ("operator seal anchor",
     "pilot/adoption_authority.py", "def seal_trust_anchor("),
]

REQUIRED_SECTIONS = [
    "Executive Summary",
    "Current Architecture",
    "Platform Responsibilities",
    "Deployment Responsibilities",
    "Enterprise Hardening",
    "Threat Model",
    "MVP Security Contract",
    "Deployment Security Contract",
    "Trust Anchor Boundary",
    "Human Approval",
    "Risk Tiers",
    "GitHub Reference Model",
    "Cordis Reference Model",
    "Capability Abstraction",
    "Product Boundary",
    "FACT / INFERENCE / UNKNOWN",
    "Residual Risks",
    "MVP Exit Criteria",
    "Phase 9 Recommendations",
]

REQUIRED_BOUNDARY_TOKENS = [
    "DEPLOYMENT_CONTRACT_VIOLATION",
    "NOT_A_TRUST_ANCHOR",
    "NOT_PROTECTED",
    "OUT_OF_SCOPE",
]

DEPLOYMENT_CONTRACT_MARKERS = [
    "Authority Store 目录",
    "Agent Runtime",
    "Artifact Store",
    "Governance process",
    "Runtime process",
    "Operator",
    "Host / volume",
]

OS_PERMISSION_RE = re.compile(r"\b(os\.chmod|chmod|flock|fcntl|O_PATH|/proc/self/fd)\b")


def _heading_matches(line: str, needle: str) -> bool:
    text = re.sub(r"^#+\s*", "", line.strip())
    text = re.sub(r"^\d+\.\s*", "", text)
    return needle.lower() in text.lower()


def _section_text(text: str, title: str) -> str:
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if _heading_matches(ln, title)), None)
    if start is None:
        return ""
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].strip().startswith("#")),
        len(lines),
    )
    return "\n".join(lines[start:end])


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
    body = text.lower()
    for token in REQUIRED_BOUNDARY_TOKENS:
        ok = token.lower() in body
        results.append((f"doc boundary token: {token}", ok, ""))
    section8 = _section_text(text, "Deployment Security Contract")
    for marker in DEPLOYMENT_CONTRACT_MARKERS:
        ok = marker.lower() in section8.lower()
        results.append((f"deployment contract marker: {marker}", ok, ""))
    return results


def _code_checks(root: pathlib.Path) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []
    for name, rel, needle in CODE_FACTS:
        path = root / rel
        ok = path.is_file() and needle in path.read_text(encoding="utf-8")
        results.append((f"code fact: {name}", ok, ""))
    os_hits: list[str] = []
    for path in sorted((root / "pilot").glob("*.py")):
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if OS_PERMISSION_RE.search(line):
                os_hits.append(f"{path.name}:{lineno}")
    results.append(
        ("no OS-permission enforcement in pilot", not os_hits, ", ".join(os_hits))
    )
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
        print(f"\n{failed} check(s) failed -> boundary claims NOT supported")
        return 1
    print("\nMVP_SECURITY_BOUNDARY_VALID_WITH_UNKNOWN: documented boundary + code facts OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
