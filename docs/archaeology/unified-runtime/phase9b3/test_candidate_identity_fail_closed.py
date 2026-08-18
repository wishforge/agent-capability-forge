"""Phase 9-B.3 RED tests: candidate identity fail-closed (R1 + R3 + R8).

Contract under test:
  ExpectedIdentity == ActualIdentity
    candidate_id AND candidate_version AND artifact_digest AND seal_digest
  -> ALLOW only when all four match; any mismatch / missing field -> REJECT.

R1 : b3_entry.json carries the expected four-field identity; runtime must
     reject when the resolved registry candidate differs (no name-only
     acceptance, no digest-only acceptance).
R3 : seal_digest of v2 frozen records covers schema + seal_version.
R8 : verify_at_mount binds the verified artifact_dir; a different mount
     source is rejected.
"""

from __future__ import annotations

import json
import pathlib
import tempfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[4]
import sys  # noqa: E402

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from forge.capabilityizer import (  # noqa: E402
    artifact_digest,
    bind_evaluation,
    freeze_candidate_dir,
    seal_digest,
    verify_frozen,
)
from pilot.adoption_authority_producer import issue_authority  # noqa: E402
from pilot.registry import AdoptionBlocked, promote  # noqa: E402
from pilot import runtime_adoption_guard as guard  # noqa: E402

CONFIRM = {"operator": "test", "confirm": True}


def build_candidate(tmp: pathlib.Path, cand_id: str, name: str, *,
                    main: bytes = b"print('A')\n", version: int = 1) -> pathlib.Path:
    cand = tmp / cand_id
    art = cand / "implementation" / "artifact"
    art.mkdir(parents=True)
    (art / "main.py").write_bytes(main)
    forged = artifact_digest(art, ["main.py"])
    (cand / "tests" / "t1").mkdir(parents=True)
    (cand / "tests" / "t1" / "data.csv").write_text("id\n")
    (cand / "tests" / "t1" / "expected.json").write_text("{}")
    manifest = {
        "manifest_version": "0.1",
        "capability": {"name": name, "description": "demo", "version": version},
        "entrypoint": {"command": ["python", "main.py"], "workdir": "artifact"},
        "contract": {"input": {"files": []}, "output": {"files": ["report.md"]}},
        "sandbox": {"permissions": {"network": False, "fs_write": ["/output"]},
                    "limits": {"timeout_seconds": 120, "output_bytes": 1048576}},
        "provenance": {
            "source_bundle_id": "bundle-1",
            "source_artifact_digest": "sha256:" + "a" * 64,
            "forged_artifact_digest": forged,
            "forge_timestamp": "2026-08-18T00:00:00Z",
        },
    }
    (cand / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (cand / "candidate.json").write_text(json.dumps(
        {"candidate_id": cand_id, "name": name, "state": "candidate",
         "source_bundle_ids": ["bundle-1"]}, indent=2) + "\n")
    return cand


def base_evaluation(evaluation_id: str) -> dict:
    return {"evaluation_id": evaluation_id, "verdict": "PASS",
            "evaluated_at": "2026-08-18T01:00:00Z"}


def canonical_env(tmp: pathlib.Path, *, cand_id: str, name: str,
                  main: bytes = b"print('A')\n", version: int = 1,
                  family: str = "F+") -> dict:
    registry_root = tmp / "registry"
    frozen_root = tmp / "frozen"
    registry_root.mkdir(parents=True, exist_ok=True)
    cand = build_candidate(tmp, cand_id, name, main=main, version=version)
    frozen = freeze_candidate_dir(cand, frozen_root, namespace=family,
                                  registry_root=registry_root)
    assert frozen["ok"], frozen
    evaluation = bind_evaluation(
        base_evaluation(f"eval-{cand_id}"),
        frozen["record"]["candidate_id"],
        frozen["record"]["artifact_digest"],
        frozen["record"]["seal_digest"])
    issued = issue_authority(registry_root, cand, evaluation, confirm=CONFIRM,
                             frozen_root=frozen_root)
    assert issued["verdict"] == "AUTHORITY_ISSUED", issued
    entry = promote(family, name, cand, evaluation, registry_root,
                    adoption_authority=issued["authority"],
                    frozen_root=frozen_root)
    guard.mark_promoted(registry_root, entry)
    return {
        "registry_root": registry_root,
        "frozen_root": frozen_root,
        "entry": entry,
        "artifact_dir": pathlib.Path(entry["artifact_dir"]),
        "identity": {
            "candidate_id": entry["adoption"]["candidate_id"],
            "candidate_version": entry["adoption"]["candidate_version"],
            "artifact_digest": entry["adoption"]["artifact_digest"],
            "seal_digest": issued["authority"]["seal_digest"],
        },
    }


def mount(env: dict, expected_identity: dict, *, mount_source=None) -> dict:
    return guard.verify_at_mount(
        env["registry_root"], env["entry"], env["artifact_dir"],
        expected_identity=expected_identity,
        mount_source=mount_source if mount_source is not None else env["artifact_dir"])


def blocked_codes(exc: AdoptionBlocked) -> set[str]:
    return {v["code"] for v in exc.violations}


def swap_entry(env: dict, other: dict) -> None:
    """Same-writer registry pointer swap: env's name now resolves `other`."""
    name = env["entry"]["name"]
    path = env["registry_root"] / "F+" / f"{name}.json"
    path.write_text(json.dumps(other["entry"], indent=2) + "\n")
    env["entry"] = other["entry"]
    env["artifact_dir"] = other["artifact_dir"]


def frozen_record(env: dict, cand_id: str) -> dict:
    return json.loads(
        (env["frozen_root"] / "frozen" / f"{cand_id}.json").read_text())


# --------------------------------------------------------------------------
# A-D: each identity field is compared; a single mismatch rejects.
# --------------------------------------------------------------------------

def test_a_candidate_id_mismatch_rejected() -> None:
    with tempfile.TemporaryDirectory() as td:
        env = canonical_env(pathlib.Path(td), cand_id="cand-A", name="foo")
        expected = dict(env["identity"], candidate_id="cand-other")
        with pytest.raises(AdoptionBlocked) as ei:
            mount(env, expected)
        assert "CANDIDATE_ID_MISMATCH" in blocked_codes(ei.value)


def test_b_candidate_version_mismatch_rejected_even_with_same_digest() -> None:
    with tempfile.TemporaryDirectory() as td:
        env = canonical_env(pathlib.Path(td), cand_id="cand-A", name="foo")
        expected = dict(env["identity"], candidate_version="v99")
        with pytest.raises(AdoptionBlocked) as ei:
            mount(env, expected)
        assert "CANDIDATE_VERSION_MISMATCH" in blocked_codes(ei.value)


def test_c_artifact_digest_mismatch_rejected() -> None:
    with tempfile.TemporaryDirectory() as td:
        env = canonical_env(pathlib.Path(td), cand_id="cand-A", name="foo")
        expected = dict(env["identity"],
                        artifact_digest="sha256:" + "c" * 64)
        with pytest.raises(AdoptionBlocked) as ei:
            mount(env, expected)
        assert "ARTIFACT_DIGEST_MISMATCH" in blocked_codes(ei.value)


def test_d_seal_digest_mismatch_rejected() -> None:
    with tempfile.TemporaryDirectory() as td:
        env = canonical_env(pathlib.Path(td), cand_id="cand-A", name="foo")
        expected = dict(env["identity"],
                        seal_digest="sha256:" + "d" * 64)
        with pytest.raises(AdoptionBlocked) as ei:
            mount(env, expected)
        assert "SEAL_DIGEST_MISMATCH" in blocked_codes(ei.value)


# --------------------------------------------------------------------------
# E-H: identity is the four-tuple; digest / name / registry locator never
# substitute for it.
# --------------------------------------------------------------------------

def test_e_same_digest_different_identity_rejected() -> None:
    main = b"print(1)\n"
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        env_a = canonical_env(tmp, cand_id="cand-A", name="foo", main=main)
        env_b = canonical_env(tmp, cand_id="cand-B", name="foo", main=main,
                              family="F+2")
        assert env_a["identity"]["artifact_digest"] == \
            env_b["identity"]["artifact_digest"]
        assert env_a["identity"]["candidate_id"] != \
            env_b["identity"]["candidate_id"]
        swap_entry(env_a, env_b)
        with pytest.raises(AdoptionBlocked) as ei:
            mount(env_a, env_a["identity"])
        codes = blocked_codes(ei.value)
        assert "CANDIDATE_ID_MISMATCH" in codes
        assert "SEAL_DIGEST_MISMATCH" in codes


def test_f_same_name_different_identity_rejected() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        env_a = canonical_env(tmp, cand_id="cand-A", name="foo")
        env_b = canonical_env(tmp, cand_id="cand-B", name="foo",
                              main=b"print('B')\n", family="F+2")
        assert env_a["entry"]["name"] == env_b["entry"]["name"]
        swap_entry(env_a, env_b)
        with pytest.raises(AdoptionBlocked) as ei:
            mount(env_a, env_a["identity"])
        assert "CANDIDATE_ID_MISMATCH" in blocked_codes(ei.value)


def test_g_registry_rebinding_rejected() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        env_a = canonical_env(tmp, cand_id="cand-A", name="foo")
        env_b = canonical_env(tmp, cand_id="cand-B", name="foo",
                              main=b"print('B')\n", family="F+2")
        # registry/foo -> Candidate A, then tampered to Candidate B
        assert env_a["entry"]["adoption"]["candidate_id"] == "cand-A"
        swap_entry(env_a, env_b)
        assert json.loads(
            (env_a["registry_root"] / "F+" / "foo.json").read_text()
        )["adoption"]["candidate_id"] == "cand-B"
        with pytest.raises(AdoptionBlocked) as ei:
            mount(env_a, env_a["identity"])
        assert "CANDIDATE_ID_MISMATCH" in blocked_codes(ei.value)


def test_h_promotion_a_runtime_b_rejected() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        env_a = canonical_env(tmp, cand_id="cand-A", name="foo")
        env_b = canonical_env(tmp, cand_id="cand-B", name="foo",
                              main=b"print('B')\n", family="F+2")
        swap_entry(env_a, env_b)  # runtime now resolves B
        with pytest.raises(AdoptionBlocked) as ei:
            mount(env_a, env_a["identity"])
        assert "CANDIDATE_ID_MISMATCH" in blocked_codes(ei.value)


def test_i_authority_a_runtime_b_rejected() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        env_a = canonical_env(tmp, cand_id="cand-A", name="foo")
        env_b = canonical_env(tmp, cand_id="cand-B", name="foo",
                              main=b"print('B')\n", family="F+2")
        # Authority A remains the store/ledger truth; runtime points at B's
        # artifact bytes. adopt() must already reject (ARTIFACT_DIGEST_MISMATCH).
        entry = json.loads(json.dumps(env_a["entry"]))
        entry["artifact_dir"] = str(env_b["artifact_dir"])
        with pytest.raises(AdoptionBlocked) as ei:
            guard.adopt(env_a["registry_root"], entry, env_b["artifact_dir"],
                        frozen_root=env_a["frozen_root"])
        assert "ARTIFACT_DIGEST_MISMATCH" in blocked_codes(ei.value)


# --------------------------------------------------------------------------
# J: missing identity component -> REJECT, never inferred.
# --------------------------------------------------------------------------

def test_j_missing_identity_component_rejected() -> None:
    fields = ("candidate_id", "candidate_version", "artifact_digest", "seal_digest")
    for field in fields:
        with tempfile.TemporaryDirectory() as td:
            env = canonical_env(pathlib.Path(td), cand_id="cand-A", name="foo")
            expected = {k: v for k, v in env["identity"].items() if k != field}
            with pytest.raises(AdoptionBlocked) as ei:
                mount(env, expected)
            assert "MISSING_IDENTITY" in blocked_codes(ei.value)


def test_j_old_b3_entry_format_without_identity_rejected() -> None:
    with tempfile.TemporaryDirectory() as td:
        env = canonical_env(pathlib.Path(td), cand_id="cand-A", name="foo")
        old_format = {"name": "foo", "capability_id": "cap-123"}
        with pytest.raises(AdoptionBlocked) as ei:
            mount(env, old_format)
        assert "MISSING_IDENTITY" in blocked_codes(ei.value)


# --------------------------------------------------------------------------
# Positive: full four-tuple match allows.
# --------------------------------------------------------------------------

def test_identity_match_allows() -> None:
    with tempfile.TemporaryDirectory() as td:
        env = canonical_env(pathlib.Path(td), cand_id="cand-A", name="foo")
        report = mount(env, env["identity"])
        assert report["verdict"] == "ALLOW"
        assert report["candidate_id"] == "cand-A"
        assert report["candidate_version"] == "v1"
        assert report["seal_digest"] == env["identity"]["seal_digest"]
        assert report["verified_artifact_dir"] == str(env["artifact_dir"].resolve())


# --------------------------------------------------------------------------
# R3: seal schema/version enter seal_digest for v2; v1 stays readable.
# --------------------------------------------------------------------------

def test_r3_new_seal_is_v2_and_schema_version_covered() -> None:
    with tempfile.TemporaryDirectory() as td:
        env = canonical_env(pathlib.Path(td), cand_id="cand-A", name="foo")
        record = frozen_record(env, "cand-A")
        assert record["schema"] == "frozen-candidate-v2"
        assert record["seal_version"] == "v2"

        # schema mutated (still valid v2 record shape would be impossible
        # without recomputing): verify must fail on schema and digest.
        mutated = json.loads(json.dumps(record))
        mutated["schema"] = "frozen-candidate-v3"
        rec_path = env["frozen_root"] / "frozen" / "cand-A.json"
        rec_path.write_text(json.dumps(mutated, indent=2) + "\n")
        check = verify_frozen(env["frozen_root"], "cand-A")
        assert not check["ok"]
        assert "SEAL_SCHEMA_MISMATCH" in {v["code"] for v in check["violations"]}


def test_r3_v2_record_cannot_be_relabeled_as_v1() -> None:
    with tempfile.TemporaryDirectory() as td:
        env = canonical_env(pathlib.Path(td), cand_id="cand-A", name="foo")
        record = frozen_record(env, "cand-A")
        mutated = json.loads(json.dumps(record))
        mutated["schema"] = "frozen-candidate-v1"
        mutated["seal_version"] = "v1"
        rec_path = env["frozen_root"] / "frozen" / "cand-A.json"
        rec_path.write_text(json.dumps(mutated, indent=2) + "\n")
        check = verify_frozen(env["frozen_root"], "cand-A")
        assert not check["ok"]
        assert "SEAL_DIGEST_MISMATCH" in {v["code"] for v in check["violations"]}


def test_r3_v1_record_still_verifies_with_old_payload() -> None:
    with tempfile.TemporaryDirectory() as td:
        env = canonical_env(pathlib.Path(td), cand_id="cand-A", name="foo")
        record = frozen_record(env, "cand-A")
        candidate = json.loads(
            (env["frozen_root"] / "frozen" / "cand-A" / "candidate.json")
            .read_text())
        old_digest = seal_digest(
            candidate, record["artifact_digest"], record["tests_digest"],
            seal_version="v1")
        v1 = json.loads(json.dumps(record))
        v1["schema"] = "frozen-candidate-v1"
        v1["seal_version"] = "v1"
        v1["seal_digest"] = old_digest
        rec_path = env["frozen_root"] / "frozen" / "cand-A.json"
        rec_path.write_text(json.dumps(v1, indent=2) + "\n")
        check = verify_frozen(env["frozen_root"], "cand-A")
        assert check["ok"], check

        # v1 record mutated to claim v2 without recompute -> digest mismatch.
        relabeled = json.loads(json.dumps(v1))
        relabeled["schema"] = "frozen-candidate-v2"
        relabeled["seal_version"] = "v2"
        rec_path.write_text(json.dumps(relabeled, indent=2) + "\n")
        check = verify_frozen(env["frozen_root"], "cand-A")
        assert not check["ok"]
        assert "SEAL_DIGEST_MISMATCH" in {v["code"] for v in check["violations"]}


# --------------------------------------------------------------------------
# R8: verified path is the only mount source.
# --------------------------------------------------------------------------

def test_r8_mount_source_must_equal_verified_artifact_dir() -> None:
    with tempfile.TemporaryDirectory() as td:
        env = canonical_env(pathlib.Path(td), cand_id="cand-A", name="foo")
        other = pathlib.Path(td) / "other"
        other.mkdir()
        with pytest.raises(AdoptionBlocked) as ei:
            mount(env, env["identity"], mount_source=other)
        assert "RUNTIME_BINDING_MISMATCH" in blocked_codes(ei.value)
