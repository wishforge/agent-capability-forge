# 58 — Phase 7 Second Consumer Validation Plan

> 阶段：Phase 7（第二消费者验证；语义验证，非平台实现）。
> 冻结基线：`57-evaluation-promotion-control-plane-synthesis.md`（E.5–E.7.1 结论冻结，
> 对应 commits `ca06a9a` / `22890c1` / `f0ae41f`）。
> 约束遵守：不修改 E.5 / E.6 / E.7 / E.7.1；不修改 `promotion-gate/*`、
> `candidate-eval/*`、`regression-attribution/*`；不建 schema / database / service /
> API / CRD / controller；不做 E.8；不跑 live provider；不把 PROMOTE 连到生产。

## 1. 目的与范围

本计划回答一个核心业务问题：

> 第一套 Agent Capability（model_studio / qwen3.7-plus 的 judge prompt 候选
> B → B-prime）已经走通 Evaluation → Regression → Attribution → Promotion →
> Provenance 安全闸门；第二套完全不同的 Agent Capability 能否在不复制第一套
> 专属逻辑的前提下，再走通一次？

本阶段只做：

- 第二消费者选择（基于现有 archaeology，不写代码先行）；
- Generic vs Consumer-specific 机制分类（文档 59）；
- 最小离线验证设计（本文档）；
- 最小第二消费者验证（离线 replay，只读消费方数据）；
- 复用评估（文档 60）。

## 2. 消费者选择

### 2.1 选择的第二消费者

**第二消费者 = swe-planner plan-writer capability**
（`research/control-plane-loop/` S7.1–S7.3 实验 + `docs/archaeology/control-plane/s7/`
 报告，FACT）。

它与第一消费者的差异足以构成“完全不同的 Agent Capability”：

| 维度 | 第一消费者（Phase 6-E） | 第二消费者（control-plane-loop S7.3） |
| --- | --- | --- |
| 被改变的能力 | LLM judge 的 prompt 文本（B → B-prime） | swe_planner 生成实现计划的 instruction |
| provider / model | Model Studio / `qwen3.7-plus` | DeepSeek / `deepseek-v4-flash` |
| dataset | `calibration:phase6d:procurement` v2（44 cases） | `gold-v2`（33 条真实 swe_planner trace） |
| outcome 形态 | PASS / FAIL / INCONCLUSIVE + contract verdict | L0 / L1 / L2 + 连续 score + evaluation status |
| 失败语义 | INVALID_OUTPUT（低置信 PASS）、TIMEOUT 等 | JUDGE_EMPTY_RESPONSE / JUDGE_TRUNCATED / JUDGE_INVALID_JSON / JUDGE_MISSING_SCORE / JUDGE_INVALID_SCORE / JUDGE_ERROR / INSUFFICIENT_JUDGE_EVIDENCE |
| 评估代码 | `docs/archaeology/deepseek-harness/evaluation/` | `research/control-plane-loop/` |
| 实验规模 | E.5 2×24-case matrix、E.6 3×5 paired replay、E.7 8 case × 10/5 rounds | 5 个候选 × 5 repeats × 33 samples = 25 个 append-only runs |
| gate 输出 | PROMOTE / HOLD / REJECT | PASS / FAIL / INCONCLUSIVE（`gate_decide()`） |

第二消费者已经拥有与协议同构的事实结构：候选有稳定 ref + 内容 hash
（`data/candidates/*.jsonl` + `plan_sha256`，FACT）；baseline / candidate 在
相同 dataset（gold-v2）上按 repeat 配对（FACT）；每个 attempt 的原始 judge
响应与失败分类全部落盘（`results.jsonl`，FACT）；失败不计分（score=None，
FACT）；run 目录 append-only、唯一 run_id（FACT）。因此不需要新造实验即可做
最小语义验证。

### 2.2 未选择的候选（含原因）

| 候选 | 未选择原因 |
| --- | --- |
| Codex archaeology（`docs/archaeology/codex/`） | 只有源码考古，无本地评估/回归 artifacts，无法构造 baseline–candidate 配对证据 |
| OpenHands archaeology（`docs/archaeology/openhands/`） | 同上；本地无 EvalOutput 产物 |
| pilot F+ rehearsal | 只有 2 个 future task、无 repeat 配对；事实结构不足以区分归因类别（会整体落到 UNKNOWN / INSUFFICIENT_EVIDENCE），留作未来第三消费者（UNKNOWN） |

## 3. 哪些 evidence 必须 immutable

按 57 号文档 §11 的协议要求，逐项映射到第二消费者的现有 artifacts：

| 协议要求 immutable | 第二消费者对应产物 | 现状 |
| --- | --- | --- |
| Attempt 级原始事实（raw + parsed + contract + failure） | `data/evals/run-*/results.jsonl`（raw_judge_responses、failure_categories、score、judge_config） | FACT：run 目录唯一、`open("x")` 创建、不覆盖 |
| 派生统计（matrix / stats / gate / runs） | `run.json` summary + `s73-matrix-*` / `s73-stability-*` / `s73-perturbation-*` | FACT：分析文件用唯一文件名（`write_unique`） |
| dataset 冻结 | `data/gold-v0/v1/v2.jsonl` + body/plan sha256 + 拒绝覆盖断言 | FACT：冻结后加载 5 次逐字节一致 |
| candidate 内容冻结 | `data/candidates/*.jsonl` + `plan_sha256` | PARTIAL：文件存在且带 hash；但 `finalize-candidates --force` 允许重建同一 version 文件，无 manifest 证明历史上未重建 |
| registered policy 字节冻结 | 无独立 policy 文件；gate 规则只存在于 `gate_calibration.py` 的 `GATE_CONFIG_VERSION = "s73-v1"` 字符串 | UNKNOWN / 缺失：无 policy bytes、无 commit ref；且 repeat noise 由本次实验数据事后校准 |
| Decision / GateResult 冻结 | s73 matrix 输出为 append-only 文件 | PARTIAL：文件不覆盖，但无 git commit 锚点 |

结论（INFERENCE）：第二消费者的“证据不可变”习惯与协议一致，但“registered
policy 先冻结”与“manifest + commit 锚点”两类 governance 证据缺失。

## 4. 第一消费者专属字段：禁止进入通用协议

以下字段/值来自第一消费者，协议层不得硬编码（列表供 59 与绑定审计使用）：

- case id：`CAL-26`、`TASK-JUDGE-01/03/04/07`、`CAL-08/11/15/16/17/18/19/20/25/27/28/30/32/36/37/38/40/41/44`；
- case 分层假设：CONTRACT 12 / STABLE PASS 7 / CRITICAL 5、24-case / 44-case matrix；
- prompt id：`prompt:phase6b:judge:B:v1` / `B-prime:v1`、`prompt-b-v2-candidate-1`；
- prompt 专属机制：B 与 B-prime 的唯一语句差异、`SYSTEM_PROMPT_SNAPSHOT` 弃权机制；
- outcome 专属语义：`INVALID_OUTPUT` 作为唯一 contract 失败标签、“低置信 PASS 禁止”契约；
- judge confidence（HIGH/LOW）作为必填通用字段（57 §4.5 把 confidence 列为
  Outcome 最小字段，这是第一消费者推断，第二消费者无该事实，见 59）；
- 统计专属值：Wilson 95% / z=1.96、8/10、9/10、-0.1、-0.2、CI lower 0.5、
  N=10/N=5、transport bound 2/1；
- provider 专属参数：model_studio、qwen3.7-plus、temp=0、seed=42、max_tokens=8192；
- policy / commit 实例：`promotion-policy-e7-v1(-final)`、`ca06a9a` 等。

第二消费者若为了使用协议而必须读取上述任一字段，即判定
`PROTOCOL_INVALID`（协议绑定第一消费者）；若只需提供协议中对应的通用字段
（policy 值、固定条件值），则不是绑定。

## 5. 最小验证设计

全部离线，不调用任何 live provider。只读消费
`research/control-plane-loop/data/`，产出只写入
`docs/archaeology/deepseek-harness/evaluation/artifacts/phase7-second-consumer/`。

### A. Candidate effectiveness（能定义“候选解决了目标问题”）

- 协议侧：policy 必须声明 target / success definition（57 §4.8，Generic）。
- 第二消费者现状：无显式 target case；只有 dataset 级 median。
- 验证方式：replay policy 声明 target = “gold-v2 上计划质量 median 相对
  baseline 提升”，success = median delta > baseline repeat noise
  （0.0447，只由 baseline 5 次 run 校准）。该定义是 replay 用
  `REPLAY_ONLY` policy，不追溯认证原 S7.3 实验。
- 预期结果：4 个候选均无“协议可认证”的 effectiveness（good_v1 无提升，
  bad_v1 的 PASS 是 judge 盲区而非目标修复；FACT 见 s7/09）。

### B. Regression safety（baseline + candidate + paired replay）

- 复用第二消费者已有 5 对 repeat 配对（baseline repeat i vs candidate
  repeat i，相同 gold-v2），FACT。
- 规则顺序（与 57 §8/§9 一致，值来自 replay policy）：
  1. dataset / sample_ids 不一致 → HOLD；
  2. 任一侧存在 ERROR_STATUSES（JUDGE_ERROR / JUDGE_PARSE_ERROR /
     JUDGE_TRUNCATED / INSUFFICIENT_JUDGE_EVIDENCE / INVALID_INPUT）
     → HOLD（insufficient_evidence）；
  3. candidate L0 / agent failure rate 上升 → REJECT（critical regression）；
  4. median delta < -noise 且全部可比 repeat 稳定为负 → REJECT
     （rate-level candidate regression）；
  5. |delta| <= noise → HOLD（variance_too_large）；
  6. delta > noise → gate PASS，最终 PROMOTE 还需 effectiveness +
     governance 同时成立。

### C. Attribution（四类必须可区分或显式 UNKNOWN）

第二消费者的事实结构支持：

- BASELINE_INSTABILITY：baseline 5 次 run median = 0.10/0.15/0.20/0.20/0.20，
  std 0.0447（FACT）；baseline 自身跨 repeat 波动可测；
- PROVIDER_NONDETERMINISM：同一候选 5 次 run median 波动 + S7.1 固定输入
  judge 重测 0.2–0.6 波动（FACT）；
- INSUFFICIENT_EVIDENCE：error statuses 存在（good_v1 每 run 2–4 个样本、
  baseline repeat 5 有 1 个样本，FACT）；
- CANDIDATE_REGRESSION：只能在“score-level 稳定负 delta”层面区分
  （bad_v2 5/5 median=0.0 vs baseline 0.10–0.20，FACT）；第一消费者的
  “per-case verdict 100% 翻转”规则不适用于连续 score 事实结构，该具体规则
  在第二消费者上标 UNKNOWN / not applicable。

### D. Promotion（PROMOTE / HOLD / REJECT）

- 第二消费者的 PASS / FAIL / INCONCLUSIVE 与协议三态一一映射
  （INFERENCE；s73 matrix 三种值都已产生，FACT）。
- 原 S7.3 实验没有 registered policy / commit 锚点 / manifest，因此其
  “PASS”不能升级为协议级 PROMOTE；所有候选只能落到 HOLD / REJECT
  （INFERENCE；由 replay 工具机械验证）。
- 不连接生产部署；不写 Langfuse；不修改任何 runtime。

## 6. 标注约定

与 57 一致：

```text
FACT      —— 在 54-56a / control-plane-loop artifacts / s7 报告中有机器可读证据
INFERENCE —— 从 FACT 推导的设计判断
UNKNOWN   —— 未被第二消费者验证、或当前事实结构无法区分
```

“Generic”不能因为第一消费者支持就标 FACT；只有第二消费者也走通后才升级为
`REUSE_CONFIRMED`。

## 7. 停止条件与 Git 边界

完成：Consumer Selection → Generic vs Consumer-specific analysis → Minimal
validation design → Minimal second-consumer validation → Reuse assessment。

然后 STOP。不做 schema / API / database / Kubernetes / production integration /
E.8；不 `git add .`；不 commit；不 push；不修改冻结基线。
