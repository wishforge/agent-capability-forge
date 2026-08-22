# 07 — Design Gate

## A. Execution Extension boundary

属于 Extension：process、session、transport、tool、event、workspace/execution-environment primitives；局部 cancellation/cleanup/reconnect；capability declarations；可观察的结果、状态、artifact references 和 tool-specific recovery hooks。

## B. Managed Runtime boundary

属于 Runtime：Run、Attempt、Binding/epoch、Artifact identity/provenance/integrity/trust、capability compatibility decision、durable outcomes、recovery semantics、isolation policy。

## C. Supervisor boundary

属于 Supervisor：desired-vs-actual reconciliation、restart/new Attempt、UNKNOWN resolution、verification/compensation orchestration、human gate、cleanup 与 termination。

## D. Durable entities

当前已明确：

```text
Run  Attempt  Binding  Artifact/Provenance
```

Compatibility decision 与 recovery/outcome record 是与这些实体关联的 durable facts，但本阶段不决定其存储形状。

## E. Recovery

当前已明确：

```text
UNKNOWN != FAILURE
receipt != execution result
verification precedes unsafe retry
compensation is conditional, not universal
Supervisor owns reconciliation
```

## F. Isolation

当前边界已明确：

- **policy owner**：Managed Runtime 选择并记录 isolation policy
- **enforcement owner**：Infrastructure/Extension host 提供 process、container、VM、workspace、network、credential 等机制
- **verification owner**：Managed Runtime/Supervisor 根据执行 attestations 和观测结果决定是否接受

## Open Decisions

1. Attempt 的完整状态机、lease、terminal transition 与 crash continuation 规则。
2. Binding epoch 的编号、继承、迁移原子性和 stale detection。
3. artifact digest/identity、trust anchor、最小 provenance、replacement/rollback policy。
4. receipt、operation identity、idempotency、verification、compensation 的 tool-class contract。
5. trusted/untrusted、multi-tenant、networked、credentialed extension 的 isolation classes 与选择矩阵。

这些是我们的语义决策，不再等待无边界 OSS 标准答案；在决策完成前不得把未定内容写成 API/CRD/DB contract。

## Logical architecture

```text
                    Managed Runtime
                           |
        +------------------+------------------+
        |                  |                  |
      Run              Binding            Artifact
        |
     Attempt
        |
        v
 Execution Extension
   /       |        \\
process  session   tool
   \\       |        /
        events
           |
           v
     Provider / Agent

        Supervisor
             |
      reconciliation
      restart
      UNKNOWN
      compensation
      termination
```

## Architecture Gate

```text
READY FOR CORE RUNTIME DESIGN
```

核心 ownership、durable entity 边界、UNKNOWN/receipt/reconciliation 责任和 isolation ownership 已足够明确，可以进入 core runtime semantics/design。API、CRD、DB 仍未定义，必须等 Open Decisions 收敛后另行设计。
