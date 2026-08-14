# Agent Capability Forge

> Turning successful agent executions into validated, reusable capabilities — and measuring whether capability formation is actually worth the cost.

**Project status:** Experimental / Research Engineering

- Runtime Boundary: Frozen
- VerifiedTaskArtifactBundle v0: Frozen
- Option B Runtime Adapter boundary: Implemented
- F+ Rehearsal: **PASS**
- Full Skill vs Capability Forge Pilot: **Not yet completed**
- Business value of Capability Forge: **Not yet established**

---

## 1. English

### What is this?

Agent Capability Forge is an experimental framework for studying whether a successful Agent execution can be transformed into a validated, reusable capability that creates more long-term value than simply generating a Skill.

The project does **not** assume that Capability Forge is better than Skills.

Instead, it asks an empirical question:

> After an Agent successfully completes a task, is it better to forget the experience, turn it into a Skill, or run it through a capability formation and validation pipeline?

### The Core Problem

Today, an Agent can solve a task successfully, but the useful experience from that task may disappear after the session ends.

A common alternative is to manually or automatically generate a Skill:

```text
Task
  ↓
Agent solves it
  ↓
Generate Skill
  ↓
Reuse later

Capability Forge explores a more governed path:

Agent Execution
      ↓
Runtime Adapter
      ↓
VerifiedTaskArtifactBundle
      ↓
Capability Formation
      ↓
Validation / Evaluation
      ↓
Promotion
      ↓
Reusable Capability

The goal is not to invent another Skill or Plugin format.

The goal is to determine whether execution-derived capability formation creates measurable incremental value.

2. Why does this matter?

The business question is simple:

Does the additional effort spent capturing, validating, evaluating, and governing a reusable capability produce more value than it costs?

In other words:

Value = Output - Input

Where:

Output

higher future-task success
less repeated work
lower token / runtime / human cost
fewer regressions and harmful reuse

Input

capability creation cost
validation and evaluation cost
runtime cost
maintenance cost
cost of incorrect capability reuse

If a simple Skill already provides the same value, Capability Forge should not exist.

3. Core Research Question

The main experiment compares four approaches:

Arm	Approach
B0	Agent only
B1	Agent + curated Skill
B2	Agent + generated Skill
B3	Agent + execution-derived Capability Forge

The experiment is explicitly designed to allow the conclusion:

Capability Forge is worth building
Skill is already sufficient
Capability Forge should be reduced to Skill generation / evaluation
4. Architecture

The project uses an Option B Runtime Adapter boundary:

Agent Runtime
      ↓
Runtime Adapter
      ↓
VerifiedTaskArtifactBundle
      ↓
Runtime-neutral Forge

For the current MVP, Codex is the first Runtime:

Codex Runtime
      ↓
Codex Runtime Adapter
      ↓
VerifiedTaskArtifactBundle
      ↓
Capability Forge

The important architectural rule is:

Runtime-specific logic stops at the Adapter boundary.

Forge Core does not import or parse Codex-specific runtime types.

This allows future Runtime integrations to follow the same pattern:

Codex       ──→ Codex Adapter ──┐
SWE-agent   ──→ SWE Adapter   ──┤
Claude      ──→ Claude Adapter ─┤
                               ↓
                 VerifiedTaskArtifactBundle
                               ↓
                         Forge Core

The current MVP intentionally does not introduce a generic RuntimeAdapter interface while there is only one implementation.

5. Current Experimental Pipeline

The current experimental B3 slice is:

Codex Runtime
    ↓
Codex Runtime Adapter
    ↓
VerifiedTaskArtifactBundle
    ↓
Capabilityizer
    ↓
Deterministic Validation
    ↓
Evaluation
    ↓
Promote / Reject
    ↓
Experimental Registry
    ↓
Invoke

B2 and B3 share the same execution-derived input:

Agent Execution
      ↓
Codex Adapter
      ↓
VerifiedTaskArtifactBundle
      ↓
     ┌───────────────┐
     │               │
     ▼               ▼
    B2              B3
Generated Skill   Capability Formation

This is important for the B2 vs B3 comparison.

6. Evidence So Far
F+ Rehearsal: PASS

The first F+ engineering rehearsal completed successfully.

It demonstrated that the following pipeline can run end-to-end:

Codex Runtime
→ Runtime Adapter
→ VerifiedTaskArtifactBundle
→ Generated Skill / Capability Candidate
→ Validation / Evaluation
→ Future Reuse

The rehearsal also verified that B2 and B3 shared the same generation input.

What this proves

It proves:

The engineering pipeline is executable.

What this does NOT prove

It does not prove:

Capability Forge is more valuable than Skill.

The full business-value experiment has not been completed yet.

7. Experiment Design

The current study uses three task families:

F+ — Forge-friendly

High reuse and stable input/output contracts.

Example:

data cleaning
normalization
report generation
F− — Forge-unfriendly

Low reuse, high variance, or task-private state.

Example:

repository-specific migration fixes
one-off incidents
F0 — Skill is enough

Tasks that can be fully described by instructions and do not require a substantial executable capability.

The main study uses:

3 task families
×
21 unique tasks
×
4 arms
=
84 runs

A smaller Pilot precedes the main study.

8. Decision Logic

The experiment separates three dimensions:

Economic
Net Value
Reliability
Future-task success
Safety
Trap / regression / harmful reuse

Capability Forge is considered worth building only when:

Economic Superiority
AND
Reliability Non-Inferiority
AND
Safety Non-Inferiority

A high economic benefit cannot compensate for a significant reliability or safety regression.

9. What This Project Is Not

This project is not:

another Skill marketplace
another Plugin framework
a replacement for Agent Runtime
a claim that Capability is better than Skill
a production-ready Agent Control Plane
a completed autonomous self-evolution system

Skills and Plugins are treated as possible capability delivery mechanisms, not the research goal itself.

10. Research Direction

The central hypothesis is:

A successful Agent execution may contain reusable behavior that can be systematically captured, validated, and promoted into a reusable capability.

The important question is whether doing so creates enough incremental value to justify the added complexity.

Possible outcomes are intentionally asymmetric:

Forge wins
    → continue Capability Forge


Skill is enough
    → stop / shrink Forge


Governed formation helps but full Capability Runtime does not
    → keep Skill Generator / Evaluator / Governance


Forge is worse
    → stop the direction

A negative result is considered a valid research outcome.

11. Repository Structure
agent-capability-forge/
├── docs/
│   └── Capability Forge specifications
├── research/
│   ├── archaeology/
│   ├── artifact-contract/
│   └── experiments/
├── src/
│   └── forge/
├── pilot/
└── tests/

The repository intentionally keeps research evidence, architecture decisions, implementation, and experimental results together.

12. Current Status
Architecture                    ✅
Artifact Contract               ✅
Runtime Adapter Boundary        ✅
F+ Engineering Rehearsal        ✅
Full Pilot                      ⏳
Main Study                      ⏳
Business Value                  ❓

The project is currently in the transition from:

Architecture / Archaeology
        ↓
Experimental Validation
