# 27 — Phase 5-D Report：Real Codex Execution E2E

> 基线：openai/codex `279b93242cfef379e65da97e87e44b83c5934fd7`（2026-08-11）
> 状态：**PASS**（真实 Codex executable E2E + Semantic Core 零修改 +
> AgentScope 仍 PASS + Persistence/Replay 成功）
> 证据：`runtime/tests/fixtures/codex_real_golden.jsonl`（sha256
> `9f058361e2174729d2cac17eec43d92cd6728046908937a49372a92c3eaf010b`）+ 本报告。

---

## 1. Real Codex Binary / Checkout

| 项 | 值 |
| --- | --- |
| Checkout | `/Users/david/k8s/auto_swe_sys/codex` |
| Commit | `279b93242cfef379e65da97e87e44b83c5934fd7`（`git status` clean） |
| Build | `cargo build --manifest-path .../codex-rs/Cargo.toml -p codex-cli`（debug，41m57s） |
| Binary | `.../codex-rs/target/debug/codex` |
| rollout `cli_version` | `0.0.0`（dev build from pinned source） |

未升级 Codex、未修改 Codex source。

## 2. Execution Command / Protocol

真实运行使用 `codex exec --json`（non-interactive CLI → Responses wire API），
持久化 rollout JSONL。OpenAI 端点在本环境不可达（wss 超时/DNS 失败），
因此使用用户本机已配置的 DeepSeek provider（`~/.codex/config.toml` 的
`model_providers.deepseek`，`wire_api = "responses"`）；凭据从该 config 的
`experimental_bearer_token` 提取为进程级 `DEEPSEEK_API_KEY` env，未落盘、
未打印。OpenAI 直连失败与 stale env key 均不作为 fixture 替代依据。

临时配置（`$CODEX_HOME/config.toml`，无 secret）：

```toml
model_catalog_json = "/Users/david/.codex/models.json"
model_provider = "deepseek"
model = "deepseek-v4-flash"
preferred_auth_method = "api"
forced_login_method = "api"

[model_providers.deepseek]
name = "deepseek"
base_url = "https://api.deepseek.com/"
wire_api = "responses"
env_key = "DEEPSEEK_API_KEY"
```

实际命令：

```bash
CODEX_HOME=<tmp>/home \
DEEPSEEK_API_KEY=<process-env only> \
<binary>/codex exec --json --skip-git-repo-check --sandbox read-only \
  -C <tmp>/ws \
  "Read the file data.txt in this workspace and give a one-line summary of its contents. Do not modify any files."
```

Workspace `data.txt`：

```text
Q3 revenue: 42 units
Product: codex-harness
```

结果：exit 0；`duration_ms=4820`，`time_to_first_token_ms=1334`；
total tokens 19735（input 19554 / cached 9728，output 181 / reasoning 78）。

## 3. Real Run Trace

rollout：`rollout-2026-08-16T10-09-10-01a00854-805c-75d0-8a69-905166804da8.jsonl`（19 行）。

| line | item | 内容 |
| --- | --- | --- |
| 1 | `session_meta` | provider `deepseek`，cli `0.0.0`，cwd=workspace |
| 2 | `event_msg task_started` | turn_id，context_window 996147 |
| 3-8 | developer/user messages, world_state, turn_context | 系统上下文（adapter 忽略） |
| 9 | `response_item message user` | 实际 prompt |
| 11 | `response_item reasoning` | 模型推理（adapter 忽略） |
| 12 | `response_item function_call` | `name="exec_command"`，`call_id="call_00_7Mq3Bp92nwb9UtXJhZUU4713"`，`arguments={"cmd":"cat data.txt","workdir":"<ws>"}` |
| 13 | `response_item function_call_output` | Codex 原生 tool output：文件内容 |
| 17 | `response_item message assistant` | `phase=final_answer`：`data.txt contains two lines reporting Q3 revenue of 42 units for the product "codex-harness".` |
| 19 | `event_msg task_complete` | 同上 `last_agent_message` |

## 4. Unified Runtime Mapping（真实 rollout）

`CodexAdapter` → `AgentRuntime` → Unified EventStore，`delegates_tools=False`，
Unified ToolRuntime 注册 `exec_command`（只读命令白名单，`cat data.txt`），
执行结果与 Codex 原生输出一致。

Unified 事件序列（14 事件）：

```text
user/message → turn/start → step/start → agent/request →
assistant/message(tool_calls=[exec_command]) → tool/call → tool/result →
step/end → step/start → agent/request →
assistant/chunk → assistant/message(final) → step/end → turn/end
```

Step 构造：真实 trace 是 `reasoning → function_call → output → assistant message`，
即 tool call 出现在 assistant message 之前。Adapter 以 call-first 空 segment
构造 Step 1（tool），assistant final 构造 Step 2（answer）；两者均标
`mapping_quality=ADAPTER`，`step_metadata` 的 `raw_event_ref` 分别为
line 12（`function_call`）与 line 17（`message`）。

Mapping 质量：

| 项 | 值 |
| --- | --- |
| call_id | 保留为 Unified call_id（EXACT） |
| call↔output | `call_metadata` EXACT，`raw_event_ref` line 13，`function_call_output` |
| session/turn metadata | ADAPTER，line 1/2 |
| `missing_semantics` | 23 §2 六项清单不变（无新增损失） |

## 5. Persistence / Replay

`run → EventStore(JSONL) → close → reopen → rebuild_session → replay`：

- `last_seq`、Surface messages 与 close 前一致；
- `rebuild_session`：1 Turn / 2 Step；
- `replay`：turn end=completed，tool call id 与 result 内容一致，final answer 一致；
- replay 不二次执行工具（exec 计数保持 1）。

## 6. Cross-backend（AgentScope 2.0.2）

同一 golden path 用 AgentScope 2.0.2（真实库 + deterministic model，脚本由真实
rollout 的 segments 派生）运行：Unified 事件序列与 Codex 完全相同（14 事件），
final answer 相同，tool result 相同，Persistence/Replay 通过。模型侧允许
backend-specific 差异（AgentScope 脚本化 model vs 真实 DeepSeek model）。

## 7. Adapter 变更（Codex-specific，未触碰 Semantic Core）

`backend/adapters/codex.py` 三处小改：

1. 支持 `local_shell_call`（真实 schema 的 shell 工具路径；本 trace 实际走
   `function_call`，为防御性支持）；
2. 允许 tool call 出现在 assistant message 之前：call-first 时创建空 segment，
   不再抛错（真实 trace 的必要修复）；
3. call-first segment 的 `source_event_type` 标为真实 item type（如
   `function_call`），`raw_event_ref` 指向 call 行。

`runtime.py` / `model_adapter.py` / `events.py` / `event_store.py` /
`surface.py` / `compaction.py` / `tool_runtime.py` / `turn_step.py` /
`initiator.py` / `recovery.py` 均无 `codex` 命中；AgentScope adapter 与 DSH
contracts 零修改。

## 8. Fixture vs Real E2E 差异（为什么不能互相替代）

| 维度 | 5-C fixture | 5-D real |
| --- | --- | --- |
| 来源 | 手工构造 JSONL | 真实 executable + 真实 model 运行 |
| tool item | `custom_tool_call`（inventory.lookup） | `function_call`（exec_command） |
| 顺序 | assistant message 先于 tool call | tool call 先于 final assistant message |
| 上下文行 | 无 | session_meta/base_instructions/world_state/turn_context/reasoning/token_count |
| 工具执行 | Unified ToolRuntime 独立执行 | Codex 原生执行 + Unified ToolRuntime 再执行（结果一致） |
| 可验证性 | 确定、离线 | 依赖网络/凭据/provider，captured fixture 使其可离线重放 |

Fixture 验证的是“schema 翻译正确”；Real E2E 验证的是“pinned executable 从
进程真实产生该 schema 并贯通 Unified runtime”。二者不可互换。

## 9. Final Status

**PASS**：

- 真实 pinned Codex executable/process E2E 成功（exit 0，golden path 完整）；
- Semantic Core 零修改；
- AgentScope 2.0.2 既有测试仍 PASS（83/83 全绿，含新增 6 个 5-D 测试）；
- Persistence/Replay 成功，reconstructed shape == original shape。

已知限制（非本次新增，见 23 §2 / 26 §10）：Unified tool/result 由 Unified
ToolRuntime 执行（Codex 原生 output 仅 raw evidence）、无 ambient initiator、
`EXEC_FAILURE_STRUCTURED_SUCCESS` 等 lossiness 清单保持可见；subagent /
compaction / fork / rollback / sandbox 映射不在本阶段范围。
