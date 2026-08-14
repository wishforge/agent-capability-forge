# Codex #32100 Worker Result Evidence

## Primary Sources

Official Issue:
https://github.com/openai/codex/issues/32100

Implementation:
https://github.com/yusing/codex

Primary implementation area:
codex-rs/core/src/session/orchestrated.rs

## Scope

Only study:

Worker
→ Worker Result
→ changed files
→ verification
→ execution facts
→ phase packet
→ Result Review
→ Root Synthesis
→ phase history retention

Do not infer Capability semantics.

## Verified Findings

### 1. Orchestrated phases

The orchestration flow contains phases including:

- TaskContract
- Explorer
- WorkerPlan
- PlanReview
- PlanEvidence
- WorkerExec
- ResultReview

### 2. Worker result representation

Worker execution produces a PhasePacket.

PhasePacket carries:

- text
- truncation information
- execution_facts

### 3. Execution facts

Worker execution facts are collected through the orchestrated execution ledger.

Relevant concepts include:

- changed files
- verification
- failures
- risks
- execution progress / facts

### 4. Result review

Worker execution is followed by ResultReview.

ResultReview acts as a gate for whether the current orchestration flow can proceed.

### 5. Context retention

Raw phase history is compacted into bounded phase packets.

The orchestrated phase history is replaced with retained packet state rather than keeping unlimited raw worker tool history.

### 6. Identity

The Worker Result / PhasePacket is associated with the current orchestration turn / phase context.

No independently defined Capability Identity has been established.

### 7. Version

No independently defined Capability Version has been established for Worker Result.

### 8. Registry

No Capability Registry for Worker Result has been established.

### 9. Re-invocation

No independent API has been established that allows a future task to directly invoke a previous Worker Result as a reusable Capability.

### 10. Future discovery

No established automatic path has been identified where:

Future Task
→ Capability Discovery
→ previous Worker Result
→ invoke

## Classification

Worker Result:

Verified Task Execution Artifact

NOT proven to be:

Capability
Capability Candidate
Capability Version
Capability Registry Entry
Reusable Runtime Capability

## Important Distinctions

Task Verification
!=
Capability Evaluation

Result Review
!=
Capability Promotion

Phase History Retention
!=
Capability Persistence

Task/Turn/Phase Identity
!=
Capability Identity
