# 03 — Artifact / Provenance

## Evidence

| Project / source | Primitive | Artifact finding | Status |
|---|---|---|---|
| Pi `packages/core/session/.../revision.ts` and dynamic Package records in `cordis-host-runner/src/registry.ts:36-48` | session revision/package id | Path/revision and package id exist; no content digest or immutable extension artifact binding. | PARTIALLY_PROVEN |
| DeepSeek `cordis-host-runner/src/registry.ts:36-48` | immutable Package version | Package identity is local metadata; no hash/digest or persisted manifest binding. | PARTIALLY_PROVEN |
| OpenHands ACP command/provider metadata (`agent-server/01-server-source-map.md`, `05-workspace-runtime-boundary.md`) | command, workspace, container | Version/command/workspace are observable; server does not enforce content-addressed artifact identity. | PARTIALLY_PROVEN |
| Codex `binding-host/03-artifact-version.md` | cli/model/version metadata | Version and commit metadata are not a digest and are not enforced on recovery. | PARTIALLY_PROVEN |
| Claude `sdk.d.ts` initialization result (`version`, `model`, `capabilities`) | observability | Reports version/model/capabilities, not immutable executable digest or workspace snapshot. | PARTIALLY_PROVEN |

## Judgment

**Does Managed Runtime require artifact identity beyond Extension primitives? YES.** Extension must provide a descriptor (source/build revision, URI, declared dependencies and optional workspace/checkpoint references). Managed Runtime is the trust owner: it computes/verifies a canonical digest, persists provenance, and rechecks it on bind/resume/upgrade. `version != integrity`; a version string cannot prove exact bytes.

Artifact identity covers extension artifact, workspace snapshot/patch, checkpoint, result and relevant tool output. A digest is required where the artifact participates in trust or recovery; human labels remain selection metadata. Recovery must be able to re-fetch or verify the digest, otherwise it cannot claim exact replay.

Status: negative OSS result `PROVEN`; digest algorithm, trust anchor, and rollback policy `NOT_PROVEN` and intentionally deferred to design.
