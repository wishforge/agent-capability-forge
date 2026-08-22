# 07 — Execution Extension Contract

`ARCHAEOLOGY EVIDENCE`：已有边界文档支持 process/session/transport/tool/event/workspace primitives；以下 operation 输入输出与 non-ownership 是 `DESIGN DECISION`。

这是 Managed Runtime 与 Extension 的 logical internal contract，不是 API、SDK 或 wire format。

## Runtime → Extension input

- `BindingEpoch`（只读快照/reference）
- execution intent 与 operation identity（如 policy/tool contract 要求）
- capability requirements 与 compatibility decision reference
- isolation policy/requirements
- 可选 workspace、checkpoint、resume/fork lineage reference

Runtime 传递约束和意图，不把 Run/Attempt durable state 的写权限交给 Extension。

## Logical operations

```text
start execution(intent, epoch, policy)
observe execution(handle)
deliver tool request(operation)
receive event(handle)
terminate execution(handle, reason)
inspect execution handle(handle)
```

Extension 可以重启、重连、清理 live primitive，并返回 process/session/transport/tool/event/workspace 事实；不能决定 Run outcome、Attempt transition、epoch migration、artifact trust 或 recovery verdict。

## Extension → Runtime output

输出必须是可归因的 execution facts 或 references：启动/退出/断连/超时/cancellation observation、events、tool result、tool receipt/probe/undo capability、artifact reference/metadata、handle/session state 与 failure observation。输出应带 Attempt/epoch/operation correlation；若无法归因，Runtime 记录 observation gap/UNKNOWN，而不是猜测。

关键规则：`Extension reports facts; Runtime owns durable semantics.` Extension process/session/transport 丢失后，Runtime 必须能用 durable state 重建 semantic state；handle 只能被重建或标为 stale。
