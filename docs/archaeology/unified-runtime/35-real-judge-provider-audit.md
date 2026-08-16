# 35 — Real Judge Provider Audit（Phase 6-B）

> 阶段：Phase 6-B。接入真实 LLM Judge 前的 Provider Boundary Audit。
> 审计方式：本地配置读取（不打印 secret）+ 真实 API probe（2026-08-16）+ SDK
> 行为观察。状态词：AVAILABLE / PARTIAL / MISSING。

---

## 1. 当前可用 provider

**AVAILABLE。** DeepSeek，OpenAI 兼容接口：

- 配置来源：`~/.codex/config.toml`（既有配置，与
  `research/control-plane-loop/evaluate.py:29-36` 同一来源）。
- 端点：`https://api.deepseek.com/`。
- 进程 env 中存在 `DEEPSEEK_API_KEY` / `OPENAI_API_KEY`，本阶段只使用 DeepSeek
  现有配置；任何 key / token 未写入仓库、未打印。

## 2. model identity

**AVAILABLE。**

- `GET /models`：`deepseek-v4-flash`、`deepseek-v4-pro`。
- 实际使用：`deepseek-v4-flash`（现有配置 `model`）。
- provider 不暴露模型版本号 → `model_version=UNKNOWN`，不伪造。

## 3. API / SDK boundary

**AVAILABLE。**

- SDK：`openai` 2.45.0（已安装），`OpenAI(api_key, base_url)` +
  `chat.completions.create()`。
- Provider-specific 代码隔离在
  `docs/archaeology/deepseek-harness/evaluation/judge_provider.py`；
  `evaluator.py` / `llm_judge.py` 不 import provider SDK。

## 4. structured output 能力

**AVAILABLE（json_object）/ MISSING（json_schema）。**

- `response_format={"type": "json_object"}` 可用：probe 与 14 条 artifact runs
  全部成功解析。
- `json_schema` 不支持（既有本地记录：`research/control-plane-loop/evaluate.py:7-8`）。
- 实测发现：`max_tokens=2048` 时 reasoning tokens 与输出共享预算，导致 JSON
  截断（缺逗号 / 无 JSON object）；默认提高到 8192 后稳定。

## 5. temperature / seed / deterministic controls

**AVAILABLE。**

- `temperature` 接受 0.0 / 0.7；默认 0.0。
- `seed` 接受（probe 传 `seed=42` 无报错）。
- probe：`seed=42, temperature=0` 同一请求 3/3 输出完全一致；
  `temperature=0.7` 无 seed 3 次不完全一致（含 1 次空 content）。
- 结论：provider 支持 deterministic control，不标记
  `NON_DETERMINISTIC_PROVIDER`；但复杂 prompt 下的 seed 保证未由官方承诺。

## 6. timeout

**AVAILABLE（客户端可配）。** SDK client `timeout` 生效；实测 20s 触发
`httpx.ReadTimeout` → `APITimeoutError`。默认提高到 120s。

## 7. retry

**AVAILABLE（客户端级）。** `OpenAI(max_retries=...)` 生效，默认 0。实测
SDK 2.45 不接受请求级 `create(max_retries=...)`（`TypeError`），retry 只能配在
client 上。

## 8. token usage

**AVAILABLE。** `response.usage` 返回 prompt / completion / reasoning / cache
字段。14 条 artifact runs 合计约 74,097 tokens。

## 9. failure modes

| 现象 | 归一化 kind |
| --- | --- |
| `APITimeoutError` / `httpx` timeout | `TIMEOUT` |
| `RateLimitError` / 5xx | `TRANSIENT` |
| `APIConnectionError` | `UNAVAILABLE` |
| 4xx（auth / permission / not found / bad request） | `PERMANENT` |
| 非 JSON / 截断 JSON / schema 不符 / 空 content | `INVALID_OUTPUT` |

所有 provider failure 归一为 `JudgeProviderError`，不得当作 Agent failure；
Evaluation 层语义保持 INCONCLUSIVE。

