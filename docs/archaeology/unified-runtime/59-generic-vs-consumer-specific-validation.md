# 59 — Generic vs Consumer-specific Validation Matrix（Phase 7）

> 阶段：Phase 7。基线：57（E.5–E.7.1 冻结）。消费者：第一消费者 =
> model_studio/qwen3.7-plus judge prompt（Phase 6-E）；第二消费者 =
> swe-planner plan-writer（control-plane-loop S7.3）。
> 标注：FACT（有机器可读证据）/ INFERENCE（设计推断）/ UNKNOWN（未验证）。
> 升级规则：机制只有在第二消费者验证通过后才标 `REUSE_CONFIRMED`；
> 仅第一消费者支持 ≠ Generic FACT。

## 1. 机制分类矩阵

| 57 号机制 | 分类 | 第一消费者证据 | 第二消费者证据 | 结论 |
| --- | --- | --- | --- | --- |
| Candidate 稳定身份 + artifact hashes | Generic（对象） | FACT：`prompt-b-v2-candidate-1` + prompt hash（54） | FACT：`candidate_*_v1` + `plan_sha256`（candidates/*.jsonl）；缺显式 `baseline_ref` / `git_commit` 字段（additive） | REUSE_CONFIRMED（对象结构）；字段补充为扩展 |
| EvaluationRun：固定条件 + 唯一 run_id + append-only | Generic | FACT：E.5/E.6/E.7 run 目录（54-56） | FACT：`run-<id>/` 唯一目录、`open("x")`、metadata 含 candidate/dataset/repeat（evaluation_result.py） | REUSE_CONFIRMED |
| Paired replay（baseline/candidate 同条件按轮配对） | Generic | FACT：E.5/E.6/E.7 arm 交替（54-56） | FACT：5 对 repeat 同 gold-v2 配对；但未记录/未交替 arm order | REUSE_CONFIRMED（配对机制）；arm 交替是可选设计，不是核心语义 |
| Attempt evidence（失败也是证据，raw 保留） | Generic | FACT：142 条 attempt、失败保留（56） | FACT：raw_judge_responses + failure_categories 全保留、失败 score=None（s7/03） | REUSE_CONFIRMED |
| 三层 outcome 编码（verdict / contract / transport） | Generic（语义） | FACT：ACCEPT ≠ INVALID_OUTPUT ≠ TIMEOUT（56） | FACT：OK ≠ JUDGE_* statuses ≠ JUDGE_ERROR；score=None 不记 0（s7/03） | REUSE_CONFIRMED（语义）；具体标签 consumer-specific |
| `INVALID_OUTPUT` 作为通用 outcome 标签 | Consumer-specific（第一消费者） | FACT：低置信 PASS 契约（54） | NOT FOUND：第二消费者用 JUDGE_PARSE_ERROR / JUDGE_TRUNCATED 等 | 不进入协议字段；协议只保留“contract-reject”类 |
| Outcome.confidence（HIGH/LOW） | Consumer-specific（第一消费者推断） | FACT：E.5 用 confidence 判契约（54） | NOT FOUND：第二消费者 judge 只输出 score + reasoning（s7/03） | 57 §4.5 的 confidence 需降级为 consumer-specific / optional（UNKNOWN 通用性） |
| Regression detection：paired delta + 显式 UNCLASSIFIED | Generic | FACT：E.5 matrix UNCLASSIFIED（54） | FACT：error status → INCONCLUSIVE；不可比显式标记（s7/06、s7/09） | REUSE_CONFIRMED |
| 两层回归语义（strict-stability vs rate-level） | Generic（分层） | FACT：E.6 vs E.7（55/56） | FACT：s72（样本间 std，保守）vs s73（repeat std，校准）是两层不同规则（s7/09） | REUSE_CONFIRMED（分层结构）；每层阈值是 policy 值 |
| strict-stability：per-case verdict 100% 稳定 | Consumer-specific（规则形态） | FACT：E.6 B.2（55） | UNKNOWN：第二消费者无 per-case 二值 verdict，只有连续 score；该规则不可直接套用 | 需 score-level strict-stability 扩展（见 §3 E1） |
| Attribution 四类（CANDIDATE_REGRESSION / PROVIDER_NONDETERMINISM / BASELINE_INSTABILITY / INSUFFICIENT_EVIDENCE） | Generic（分类集） | FACT：E.6（55） | FACT：三类可区分（baseline 波动 / 同 arm 波动 / evidence error）；CANDIDATE_REGRESSION 只能以 score-level 稳定负 delta 表达 | PARTIAL_REUSE（分类集通用；判定规则形态需扩展） |
| 预注册判定顺序 | Generic | FACT：E.6 B.2 预注册顺序（55） | NOT FOUND：无预注册 policy 对象；s73 的 noise 由同一实验事后校准（s7/09 §1） | 机制 REUSE_CONFIRMED；第二消费者原实验未遵守（合规缺口，非语义变更） |
| 三态 Gate（PROMOTE / HOLD / REJECT） | Generic | FACT：E.5 INSUFFICIENT_EVIDENCE / E.6 REGRESSION_SAFETY_CONFIRMED / E.7 HOLD（54-56） | FACT：PASS / FAIL / INCONCLUSIVE 三值都由 s73 matrix 产生（s7/09） | REUSE_CONFIRMED（三态语义 1:1 映射） |
| Gate 组合：effectiveness + safety + governance 缺一不可 | Generic | FACT：E.7 §2.5（56） | FACT：第二消费者无 target effectiveness 定义、无 governance 证据 → PASS 不能自动升级 PROMOTE（s7/09） | REUSE_CONFIRMED（协议要求成立）；consumer 侧缺口 |
| REJECT 触发器（confirmed regression / evidence integrity / policy 被改） | Generic | FACT：E.7 §2.5（56） | FACT：critical regression / stable lower score → FAIL（s7/09） | REUSE_CONFIRMED |
| Registered / Final policy 分离 | Generic | FACT：E.7.1（56a） | NOT FOUND：无 policy 文件与版本对象 | UNKNOWN（机制未在第二消费者验证） |
| ArtifactManifest + bytes 级 provenance（registered bytes == git show） | Generic | FACT：E.7.1（56a） | PARTIAL：evidence 文件 append-only + hash 字段存在；无 manifest、无 commit 锚点、无 recompute 等价性证明 | PARTIAL_REUSE（链结构通用；第二消费者未实现） |
| Evidence 不可覆盖（新 run / 新版本代替改写） | Generic | FACT：E.7.1 恢复审计（56a） | FACT：run 目录不可覆盖；`finalize-candidates --force` 允许重建候选文件（潜在违规） | PARTIAL_REUSE（run 层 OK；candidate 层存在改写入口） |
| Runtime / Control Plane 边界 | Generic（INFERENCE） | FACT：Phase 5-N decide() 不部署（28/57） | FACT：promote.py 只写 `control-plane-candidate` label、isActive=false（control-plane-loop/promote.py） | REUSE_CONFIRMED（边界语义） |
| Wilson / 8-of-10 / -0.1 / CI 0.5 等阈值 | Consumer-specific（值） | FACT：E.7 policy（56） | FACT：第二消费者用 median + repeat std（s7/09） | 阈值是 policy 值，不进入协议核心 |
| 24-case / 44-case matrix 与 case 分层 | Consumer-specific（实验结构） | FACT：E.5 A.4（54） | FACT：第二消费者用 33 样本 dataset，无 target/suspicious/control 分层 | 不进入协议核心；scope 是 policy 字段 |
| CAL-26 / TASK-JUDGE / B / B-prime 命名 | Consumer-specific（实例） | FACT | NOT FOUND | 不进入协议核心 |
| model_studio / qwen3.7-plus / temp=0 / seed=42 | Consumer-specific（固定条件值） | FACT | FACT：deepseek-v4-flash / temp=0（s7/08） | 固定条件是通用字段，值是 consumer 实例 |

## 2. 第一消费者绑定审计（重点检查项）

| 检查项 | 结果 |
| --- | --- |
| CAL-26 hard-coded | 第二消费者 artifacts / 映射层无 CAL-26（FACT，绑定审计 0 命中） |
| Judge-specific status（PASS/INC 契约） | 第二消费者 status 集合不同（JUDGE_* / INSUFFICIENT_JUDGE_EVIDENCE）；协议只要求三层语义，不要求同标签（FACT） |
| `INVALID_OUTPUT` 被当作通用 outcome | 否：已标 Consumer-specific（见 §1） |
| LLM judge confidence 被写死成通用字段 | 57 §4.5 确有该字段；第二消费者无此事实 → 必须降级（UNKNOWN 通用性） |
| `B / B-prime` naming | 未进入协议层（FACT） |
| 44-case matrix 假设 | 未进入协议层；第二消费者 33 samples 走通（FACT） |
| Wilson threshold 被误认为通用阈值 | 未进入协议核心；第二消费者用 median + repeat std 走通（FACT） |
| Model_Studio / qwen3.7-plus 专属参数 | 未进入协议层（FACT） |

## 3. 结论：Core + Extension

### Core（REUSE_CONFIRMED，第二消费者验证）

```text
Candidate（身份 + hash）
EvaluationRun（固定条件 + append-only 唯一 run）
Attempt / Evidence（失败保留，raw 落盘）
三层 outcome 语义（verdict / contract / transport）
Paired replay（同 dataset 按 repeat 配对）
Regression（paired delta + 显式不可比）
Attribution 分类集（四类；判定规则形态见 Extension）
三态 Gate（PROMOTE / HOLD / REJECT）
Runtime / Control Plane 边界
```

### Extension（consumer-specific，允许但不升为通用核心）

```text
E1. score-level strict-stability：连续分数事实下的“稳定负 delta = 
    CANDIDATE_REGRESSION”，替代/补充 verdict-level 100% 翻转规则；
    必须在 policy 中预注册。
E2. target effectiveness 定义：每个消费者必须声明 target + success
    定义（协议字段，consumer 值）。
E3. 预注册 + manifest + commit 锚点：协议已要求；第二消费者原 S7.3
    实验未执行（noise 事后校准），需在新 run 中补齐。
E4. outcome 标签映射：INVALID_OUTPUT ↔ JUDGE_* 等标签差异，映射表
    属于 adapter，不属于协议核心。
```

### UNKNOWN（未验证，不得升级）

```text
- Outcome.confidence 是否通用（第二消费者无该事实）
- Registered/Final PolicyVersion 与 Manifest 在第二消费者上的实现形态
- arm-order 交替对配对重放的必要性
- Wilson / 8-of-10 / -0.1 / CI 0.5 在第二消费者任务域的可迁移性
- candidate 文件 --force 重建是否实际发生过（无 manifest 无法证明）
```

**结论（INFERENCE）**：57 号协议没有绑定第一消费者；第二消费者可以不改核心
语义复用它。正式判定见文档 60。
