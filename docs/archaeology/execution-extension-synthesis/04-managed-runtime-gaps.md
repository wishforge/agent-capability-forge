# Managed Runtime Gaps

| Candidate | Why required | Evidence | Failure if absent | Can live outside Execution Extension? |
| --- | --- | --- | --- | --- |
| Durable Extension Binding | Resume/restart 必须知道实际装配了哪个 extension artifact/config | 五项目均无一等 binding；DeepSeek 明确 NOT FOUND | 恢复时可静默换实现、session 与 side effect 失配 | Yes; Control Plane/Runtime record, shared contract |
| Artifact integrity/provenance | version 只说明发布语义，不证明 bytes/source/build | Pi/Claude 无 digest；DeepSeek package id 无 digest；Codex/OpenHands 仅 version/commit metadata | TOCTOU、不可审计、不可证明 exact artifact | Yes; Runtime trust boundary, extension supplies descriptor |
| Cross-layer execution identity | event/tool/process/binding 需要可关联 | Codex turn、DeepSeek pluginRun、OpenHands conversation 各自 domain | 无法审计一次 execution 的完整因果链 | Yes; Runtime owns, extension propagates |
| Durable Attempt | retry/crash/resume 需要明确生命周期 | NOT FOUND/仅局部近似 | 重试与恢复无法区分，side effect 归属不明 | Yes; Runtime owns |
| Capability compatibility decision | DI/feature flags 不是 semantic compatibility | DeepSeek 明确 NOT FOUND；Codex static caps；Claude feature discovery | 绑定或升级后能力不兼容仍运行 | Shared: extension declares, runtime decides/persists |
| Supervisor/reconciliation | 发现 worker 不存在并对 desired state 作决定 | 所有项目 supervisor NOT FOUND | 进程死后无人重建、状态悬挂 | Yes; outside extension mechanism |
| Side-effect-aware recovery | unknown tool outcome 不能盲重试 | DeepSeek crash-tail marks UNKNOWN；其余无 checkpoint | 重复扣款/写入/命令副作用 | Yes; Runtime policy + tool/provider contract |
| Isolation policy | in-process/VM/container 的安全等级不同 | 各项目均 PARTIAL | 扩展越权或隔离假象 | Yes; Runtime owns policy, extension declares needs |

这些是 `[DESIGN REQUIREMENT]`，不是“OSS 已有”。最小 v1 不需要把所有 recovery algorithm 放入 Extension；只需定义 ownership、identity 与 decision handoff。
