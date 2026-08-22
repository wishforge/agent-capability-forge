# 06 — Isolation Policy

## Definition

Isolation Policy 是 Managed Runtime 对一次 Attempt 所需约束与可接受风险边界的 durable decision，不是某个 sandbox 实现名。它至少覆盖 process、filesystem、workspace、network、credentials、tenant 与 tools。

```text
Policy -> Selection -> Enforcement -> Verification
```

- **Policy Owner：Managed Runtime**。根据 artifact trust、tenant、capability、credential、network 与风险要求选择并记录 policy。
- **Enforcement Owner：Infrastructure / Execution Extension host**。提供 process/container/VM、workspace mount、network filter、credential materialization、tool gate 等 primitive。
- **Verification Owner：Managed Runtime / Supervisor**。检查 attestation、observed facts 与 policy 是否匹配；不满足则拒绝 admission、标 stale/UNKNOWN 或终止。

**ARCHAEOLOGY EVIDENCE**：各项目分别有 process、container、workspace、tool permission、credential 等机制，但没有跨项目统一 levels 或 selection owner。

**DESIGN DECISION**：Execution Extension 只能执行被授予的 isolation primitive，不能自行提升 policy，也不能把“有一个 process”当成 filesystem/network/tenant isolation 的证明。

## Required dimensions

Policy 至少说明：进程边界、可写 workspace、文件系统可见性、网络 egress/ingress、credential scope/expiry、tenant boundary、允许的 tools，以及 enforcement/verification evidence。缺失维度不是默认 allow，而是 OPEN PARAMETER 或 admission failure。

**OPEN PARAMETER**：具体 isolation classes（trusted/untrusted、multi-tenant、networked、credentialed）、选择矩阵、attestation 格式与失败处置留给 implementation design。

