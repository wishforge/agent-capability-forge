# Capability / Supervisor / Recovery

## Capability

**模型：Extension declares; Runtime computes/decides; decision is persisted in Binding and rechecked at bind/resume/upgrade/downgrade.** `[DESIGN REQUIREMENT]`

Pi active tool filters、DeepSeek service injection、Codex feature/provider/sandbox flags、OpenHands `supports_*` gate、Claude initialization feature flags 分别是 exposure、dependency availability、static upper bound 或 protocol feature discovery；没有一个形成 portable semantic negotiation。[PI][DEEPSEEK][CODEX][OPENHANDS][CLAUDE]

因此：Dependency Injection ≠ Capability Negotiation。Bind、Resume、Upgrade、Downgrade 都应重新判断 compatibility；缺失/不兼容应 fail closed 或进入 explicit review，而非静默降级。[DESIGN REQUIREMENT]

## Semantic gradient

```text
Error -> Retry -> Resume -> Recovery -> Supervisor / Reconciliation
```

- Error：一次调用/turn 失败或取消；由 loop/tool/adapter 分类。[MULTI-PROJECT]
- Retry：同一 logical work 再 dispatch；DeepSeek request retry、Codex transport retry 属此层，不是 supervisor。[DEEPSEEK][CODEX]
- Resume：依据 durable session/history 重新建立 runtime；Pi/DeepSeek/OpenHands/Codex/Claude 都有不同程度证据，不等于恢复 side effect。[MULTI-PROJECT]
- Recovery：对 lost/unknown execution 重建并协调 binding、attempt、external state。[DESIGN REQUIREMENT]
- Supervisor/Reconciliation：读取 desired state，发现实际 worker/runtime 不存在或漂移，决定继续、重试、补偿、UNKNOWN、人审或终止。[DESIGN REQUIREMENT]

## Ownership answers

发现 execution 不存在：Supervisor。重新建立 Extension：Supervisor 调 Runtime bind/activation；Extension 只提供 lifecycle mechanism。判断 side effect 是否已发生：tool/provider 的 probe/idempotency/receipt + Runtime policy。决定继续/重试/补偿/UNKNOWN/终止：Managed Runtime/Control Plane policy；Extension 可提供 recovery hooks，但不拥有最终裁决。[INFERENCE]

Isolation 同理：Extension 声明需要的 capability/isolation，Runtime 选择并 enforce；VM、process、container 不能互称同等级隔离。[DEEPSEEK][OPENHANDS][PI]
