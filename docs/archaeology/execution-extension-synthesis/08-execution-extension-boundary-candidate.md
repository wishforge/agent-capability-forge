# Execution Extension Boundary Candidate v1

## Candidate shape

```text
Managed Agent Core
        |
        v
Execution Extension (runtime composition boundary)
        |
        +-- Extension Mechanism
        |     +-- scoped lifecycle / disposal
        |     +-- agent-loop seam
        |     +-- tool registration + interception
        |     +-- event seam
        |     +-- session association (not session ownership)
        |
        +-- Managed Binding (durable, outside extension object)
        |     +-- Agent + Session epoch + Extension Artifact
        |     +-- capability decision + isolation class
        |     +-- Execution / Run + current Attempt
        |
        v
Execution / Attempt facts and artifacts
        |
        v
Supervisor / Recovery / Reconciliation (outside extension)
```

## Required v1 boundary statements

1. **Extension 是 runtime boundary/composition，不是单一 universal entity。** DeepSeek 明确由 plugin registrations + agent/tool/event seams 组成；Pi 则证明 extension factory 可绑定到 AgentSession。Artifact 可以是一等实体，但 `ExecutionExtension` 不必是一个持久对象。[PI][DEEPSEEK]
2. **Binding 是一等实体。** 仅有 object IDs 或 session IDs 不足以证明恢复时的 exact composition。[MULTI-PROJECT][DESIGN REQUIREMENT]
3. **Attempt 独立于 Run。** Run 是 logical execution；Attempt 是一次实际 dispatch effort；crash 后原 attempt 进入 unknown/lost，后续由 supervisor 决定是否新 attempt。[INFERENCE][DESIGN REQUIREMENT]
4. **Artifact digest 是 shared contract，runtime trust owner。** Extension descriptor 声明 provenance；Runtime 验证 bytes、记录 digest 并在 resume/upgrade 检查。[DESIGN REQUIREMENT]
5. **Capability negotiation 是 shared process，runtime decision owner。** Extension declares；runtime evaluates and persists compatibility。[DESIGN REQUIREMENT]
6. **Supervisor 不属于 Execution Extension。** Extension 可有 teardown/recovery hooks；desired-vs-actual reconciliation、restart、compensation、UNKNOWN/stop 是 Runtime/Control Plane 职责。[MULTI-PROJECT][DESIGN REQUIREMENT]

## Explicit non-goals

本 candidate 不冻结 API method names、wire format、CRD、database schema、artifact build system、具体 retry/backoff、通用 side-effect compensation protocol。
