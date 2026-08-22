# Input Inventory

只使用已存在的专项报告；没有重做项目源码考古。

| Project | Evidence set | Scope used |
| --- | --- | --- |
| Pi | `docs/archaeology/pi/execution-extension/README.md`, `01-09`, `11-findings.md`, `12-final-verdict.md` | SDK Agent/AgentSession/ExtensionRunner、tool、model、RPC、session resume/fork |
| DeepSeek Harness | `docs/archaeology/deepseek-harness/execution-extension/README.md`, `01-12`；配套 `runtime/*` | Cordis Plugin/Fiber、dynamic package/run、agent waterfalls、tool runtime、event persistence、recovery gaps |
| OpenHands | `docs/archaeology/openhands/agent-server/README.md`, `01-12`; `provider-registry/README.md`, `01-10` | ACP external-process host、session/process/credential/event lifecycle、static provider registry/capabilities |
| Codex | `docs/archaeology/codex/execution-extension/binding-host/*`; related `01`, `03-08`, `20-25`, `99-synthesis.md` | provider/config binding、turn identity、exec-server process transport、version/artifact limits、resume |
| Claude | `docs/archaeology/claude/execution-extension/README.md`, `01-12` | Query/session、tool permission hook、transport、resume/fork、artifact/capability/recovery limits |

证据标签：`[PI] [DEEPSEEK] [OPENHANDS] [CODEX] [CLAUDE]` 为报告中的 source/test/experiment 结论；`[MULTI-PROJECT]` 只用于跨项目相同语义；`[INFERENCE]` 是归并推断；`[DESIGN REQUIREMENT]` 是 Managed Runtime 必要性判断，不表示 OSS 已实现。

排除：各项目完整源码、评价/训练控制平面、已有 unified-runtime 实现文件；这些不是本轮 Execution Extension 机制的直接输入。
