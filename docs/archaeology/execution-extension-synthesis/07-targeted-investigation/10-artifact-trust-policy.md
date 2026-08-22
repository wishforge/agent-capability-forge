# 10 — Artifact Trust Policy

## Evidence matrix

| Baseline | Artifact facts present | Missing trust fact |
|---|---|---|
| Pi | Session JSONL path/revision and extension/provider registrations; no enforced executable digest (`pi/execution-extension/09-resume-fork-recovery.md`, `12-final-verdict.md`). | byte identity and trust decision |
| DeepSeek | Package id/source strings, current/next package pointers, session persistence revision; no digest, manifest lock, or persisted dynamic registry (`deepseek-harness/execution-extension/01-plugin-boundary.md`, `07-identity-version-binding.md`). | exact artifact identity and reload verification |
| OpenHands | command/package pin, workspace path/container and credential materialization; no content-addressed executable or workspace artifact contract (`openhands/provider-registry/09-extension-registry-mapping.md`, `agent-server/05-workspace-runtime-boundary.md`). | immutable artifact/workspace proof |
| Codex | `cli_version`, provider/model metadata, rollout/session files; version is not a digest and is not enforced on resume (`codex/execution-extension/binding-host/01-binding-source-map.md`, `12-final-verdict.md`). | executable/configuration integrity |
| Claude | SDK reports version/model/capabilities; declarations expose no executable digest or snapshot verification (`claude/execution-extension/12-final-verdict.md`). | artifact verification |

## Semantic separation

The evidence supports two different predicates:

```text
artifact exists      = a path, package, version, workspace or checkpoint reference is present
artifact is trusted  = the bytes/provenance were verified against an accepted authority
```

Every baseline has examples of the first. No baseline proves the second for an execution extension, workspace snapshot, patch, checkpoint, or tool result. A version, URI, path, package id, or successful reload is not a digest or a trust decision.

## Required answers

| Question | Evidence-backed answer |
|---|---|
| Artifact identity | Project-local names/versions/paths/revisions; no common immutable content identity. |
| Artifact provenance | Partial metadata (session, package, command, workspace, provider); no complete creator→execution→Attempt chain. |
| Artifact verification | No cross-project verification on reload/recovery is proven. |
| Trust decision owner | OSS does not expose one. The negative evidence places this outside the Extension; a Managed Runtime trust boundary would have to own it, with Infrastructure/Provider supplying attestations where available. |

Digest algorithm, trust anchor, replacement/rollback policy, and minimum provenance are therefore `NOT_PROVEN`, not design decisions disguised as archaeology.

**Gate C: NOT CLOSED.**
