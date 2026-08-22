# Execution Extension Cross-Project Synthesis

本目录把既有专项考古归并为一个最小的 Managed Agent Execution Extension Boundary v1 候选。它只做 Evidence → Synthesis → Boundary → Freeze candidate，不定义 API、CRD、数据库 schema，也不修改输入报告。

结论先行：OSS 已收敛到可插入的 lifecycle、agent-loop/tool/event seams、session history 与显式 transport/process primitives；Managed Runtime 仍需额外拥有 durable binding、artifact integrity/provenance、跨层 execution/attempt identity、capability compatibility decision、supervisor/reconciliation、side-effect-aware recovery 与 isolation policy。

最终建议：`NEEDS TARGETED INVESTIGATION`。Boundary 形状已经足够小且清晰，但 Attempt/Crash/Recovery 语义与 artifact trust policy 仍需针对目标 runtime 做定向证据确认，尚不应冻结 API。

输入清单见 [01-input-inventory.md](01-input-inventory.md)，主矩阵见 [02-cross-project-matrix.md](02-cross-project-matrix.md)。
