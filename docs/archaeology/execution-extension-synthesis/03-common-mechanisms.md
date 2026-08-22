# Common Mechanisms

## 真正跨项目重复的机制

1. **Scoped lifecycle composition**：Pi 的 extension runner、DeepSeek 的 Cordis Fiber、Claude 的 query/hooks、OpenHands 的 ACP process lifecycle 都把资源挂在明确 scope 上，并有 teardown/cancel/close 路径。[MULTI-PROJECT]
2. **Agent execution seam**：多个系统能在 turn/request/tool 前后观察或改变控制流；DeepSeek 最完整，Pi/Claude 有 hook，Codex/OpenHands 在 turn/process seam 上较窄。[MULTI-PROJECT]
3. **Tool mediation**：注册、暴露过滤/permission、取消、结果/错误观察是重复机制；这不是 capability negotiation。[MULTI-PROJECT]
4. **Session/event history**：UUID 或等价 session identity、追加事件/转录、resume；Pi/DeepSeek/Claude/Codex 是强证据，OpenHands 以 ACP session + mirror 实现。[MULTI-PROJECT]
5. **Explicit transport/process primitives**：OpenHands ACP、Codex exec-server、Pi RPC/Claude bridge 证明 transport/process 是可独立的 host mechanism，而不是 supervisor。[MULTI-PROJECT]
6. **Lifecycle cancellation/disposal**：Abort/cancel/close/cleanup 存在，但“资源释放”不等于“崩溃后的重新协调”。[MULTI-PROJECT]

## 不应合并的同名语义

| Name | Safer reading |
| --- | --- |
| Plugin | Cordis composition unit、Pi module factory、或静态 registry descriptor；不是统一 entity。[DEEPSEEK][PI][OPENHANDS] |
| Extension | 多个 execution seams 的组合/装配 boundary；没有项目证明一个独立 universal class。[PI][DEEPSEEK] |
| Session | durable history/address + 可能的 live coordinator；resume 通常重建 live runtime。[PI][DEEPSEEK][OPENHANDS][CLAUDE] |
| Run | 某次 execution/activation/process 语义，跨项目不稳定；不能直接当 managed identity。[DEEPSEEK][OPENHANDS][CODEX] |
| Attempt | 仅 DeepSeek dynamic activation 有 process-local 近似，Codex 有 batch counter；没有 durable cross-layer 共识。[DEEPSEEK][CODEX] |
| Recovery | crash-tail repair、retry、manual resume 各自存在；没有项目证明 supervisor + side-effect reconciliation。[MULTI-PROJECT] |

结论：v1 应复用 mechanisms，而不是把项目名词直接提升为平台对象。[INFERENCE]
