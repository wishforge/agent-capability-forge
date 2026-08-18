"""Phase 8.6 - minimal tests for validate_repository_structure.py.

Stdlib unittest only; validates the validator against synthetic repo trees
and once against the real repo.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "docs" / "architecture"))

from validate_repository_structure import (  # noqa: E402
    DEPENDENCY_MARKERS,
    DOC_PATH,
    OWNERSHIP_MARKERS,
    REQUIRED_SECTIONS,
    run_checks,
)


def _fake_doc() -> str:
    lines = [f"## {i}. {section}" for i, section in enumerate(REQUIRED_SECTIONS, 1)]
    return "\n".join(lines) + "\n\n" + " ".join(OWNERSHIP_MARKERS + DEPENDENCY_MARKERS)


def fake_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "repo"
    for d in ("src", "pilot", "tests", "research", "docs"):
        (root / d).mkdir(parents=True)
    doc = root / DOC_PATH
    doc.parent.mkdir(parents=True)
    doc.write_text(_fake_doc(), encoding="utf-8")
    (root / "src" / "core.py").write_text("import json\n", encoding="utf-8")
    (root / "pilot" / "harness.py").write_text(
        "from forge.sandbox import launch\n", encoding="utf-8"
    )
    (root / "research" / "exp.py").write_text("import requests\n", encoding="utf-8")
    return root


def _failures(results) -> list[str]:
    return [name for name, ok, _ in results if not ok]


class TestRepositoryStructure(unittest.TestCase):
    def test_real_repo_passes(self) -> None:
        self.assertEqual(_failures(run_checks(ROOT)), [])

    def test_missing_doc_section_fails(self) -> None:
        root = fake_repo(self._tmp())
        doc = root / DOC_PATH
        doc.write_text(
            doc.read_text(encoding="utf-8").replace("## 16. Migration Strategy\n", ""),
            encoding="utf-8",
        )
        failures = _failures(run_checks(root))
        self.assertIn("doc section: Migration Strategy", failures)

    def test_missing_candidate_owner_fails(self) -> None:
        root = fake_repo(self._tmp())
        doc = root / DOC_PATH
        doc.write_text(
            doc.read_text(encoding="utf-8").replace("src/forge/candidate/", ""),
            encoding="utf-8",
        )
        failures = _failures(run_checks(root))
        self.assertIn("ownership marker: src/forge/candidate/", failures)

    def test_src_import_of_archaeology_fails(self) -> None:
        root = fake_repo(self._tmp())
        (root / "src" / "bad.py").write_text(
            "from archaeology.unified_runtime import x\n", encoding="utf-8"
        )
        failures = _failures(run_checks(root))
        self.assertTrue(any("src has no pilot/research/archaeology" in name
                            for name in failures))

    def test_research_import_of_forge_fails(self) -> None:
        root = fake_repo(self._tmp())
        (root / "research" / "bad.py").write_text(
            "from forge import bundle_producer\n", encoding="utf-8"
        )
        failures = _failures(run_checks(root))
        self.assertTrue(any("research has no src/pilot/archaeology" in name
                            for name in failures))

    def test_pilot_missing_forge_dependency_fails(self) -> None:
        root = fake_repo(self._tmp())
        (root / "pilot" / "harness.py").write_text("import json\n", encoding="utf-8")
        failures = _failures(run_checks(root))
        self.assertIn("pilot imports forge (documented dependency)", failures)

    def _tmp(self) -> pathlib.Path:
        import tempfile

        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        return pathlib.Path(d.name)


if __name__ == "__main__":
    unittest.main()
