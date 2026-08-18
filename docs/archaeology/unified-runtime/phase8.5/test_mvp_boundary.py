"""Phase 8.5 - minimal tests for validate_mvp_boundary.py.

Tests the boundary validator against synthetic repo trees so no production
logic is imported; one test also runs it against the real repo.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "docs/archaeology/unified-runtime/phase8.5"))

from validate_mvp_boundary import (  # noqa: E402
    DEPLOYMENT_CONTRACT_MARKERS,
    DOC_PATH,
    REQUIRED_SECTIONS,
    run_checks,
)


def _fake_doc() -> str:
    lines: list[str] = []
    for i, section in enumerate(REQUIRED_SECTIONS, 1):
        lines.append(f"## {i}. {section}")
        if section == "Deployment Security Contract":
            lines.extend(f"- {marker}" for marker in DEPLOYMENT_CONTRACT_MARKERS)
    return (
        "\n".join(lines)
        + "\n\nDEPLOYMENT_CONTRACT_VIOLATION NOT_A_TRUST_ANCHOR "
        + "NOT_PROTECTED OUT_OF_SCOPE\n"
    )


def fake_repo(tmp_path: pathlib.Path, runtime_guard: bool = True) -> pathlib.Path:
    root = tmp_path / "repo"
    (root / "pilot").mkdir(parents=True)
    (root / DOC_PATH).parent.mkdir(parents=True)
    (root / DOC_PATH).write_text(_fake_doc(), encoding="utf-8")
    (root / "pilot/adoption_authority_producer.py").write_text(
        "def issue_authority(\n", encoding="utf-8"
    )
    (root / "pilot/registry.py").write_text(
        "def promote(...):\n"
        "    if adoption_authority is None:\n"
        "        raise AdoptionBlocked\n"
        "    report = validate(adoption_authority, store, actual_digest, registry_root)\n"
        "    anchor_violations = integrity_anchor_violations(store, registry_root)\n",
        encoding="utf-8",
    )
    (root / "pilot/adoption_authority.py").write_text(
        "def write_authority_record(\n"
        "def seal_trust_anchor(\n",
        encoding="utf-8",
    )
    (root / "pilot/runtime_adoption_guard.py").write_text(
        '"REVOKED_DECISION"\n', encoding="utf-8"
    )
    harness = (
        "def phase_future(...):\n"
        "    adopted = runtime_guard.adopt(self.registry_root, entry, artifact_dir)\n"
    )
    if runtime_guard:
        harness += "    runtime_guard.verify_at_mount(\n"
    harness += (
        '    invoke = docker_launch(self.cfg["sandbox"]["image"], [\n'
        '        (artifact_dir, "/artifact", True),\n'
        "    ])\n"
    )
    (root / "pilot/harness.py").write_text(harness, encoding="utf-8")
    return root


def _failures(results) -> list[str]:
    return [name for name, ok, _ in results if not ok]


def test_real_repo_passes() -> None:
    failures = _failures(run_checks(ROOT))
    assert not failures, failures


def test_missing_runtime_mount_recheck_fails(tmp_path) -> None:
    root = fake_repo(tmp_path, runtime_guard=False)
    failures = _failures(run_checks(root))
    assert any("mount recheck before launch" in name for name in failures)
    assert len(failures) == 1


def test_missing_doc_section_fails(tmp_path) -> None:
    root = fake_repo(tmp_path)
    doc = root / DOC_PATH
    doc.write_text(
        doc.read_text(encoding="utf-8").replace("## 17. Residual Risks\n", ""),
        encoding="utf-8",
    )
    failures = _failures(run_checks(root))
    assert "doc section: Residual Risks" in failures


def test_doc_missing_out_of_scope_token_fails(tmp_path) -> None:
    root = fake_repo(tmp_path)
    doc = root / DOC_PATH
    doc.write_text(
        doc.read_text(encoding="utf-8").replace(" OUT_OF_SCOPE", ""),
        encoding="utf-8",
    )
    failures = _failures(run_checks(root))
    assert "doc boundary token: OUT_OF_SCOPE" in failures


def test_os_permission_code_in_pilot_fails(tmp_path) -> None:
    root = fake_repo(tmp_path)
    path = root / "pilot/adoption_authority.py"
    path.write_text(path.read_text(encoding="utf-8") + "os.chmod(...)\n", encoding="utf-8")
    failures = _failures(run_checks(root))
    assert "no OS-permission enforcement in pilot" in failures
