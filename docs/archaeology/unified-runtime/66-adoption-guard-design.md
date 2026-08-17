# 66 — Adoption Guard Design（Phase 7.4）

> 阶段：Phase 7.4（Adoption Guard 设计；代码考古 + 架构设计 + 最小生产
> 边界 + 绕过分析 + 契约定义 + offline proof）。
> 基线：65 / 64（Phase 7.3，ENFORCEMENT_BOUNDARY_PARTIAL）、63（Phase 7.2）、
> 61（Phase 7.1）、57（Phase 7）。
> 约束遵守：未修改 E.5–E.7.1、48/51/52/53、Phase 7 / 7.1 / 7.2 / 7.3
> 已冻结文件；未修改生产 Runtime；未接真实 Registry；未接真实 Langfuse；
> 未做 E.8；未做 production rollout；未 commit / push。

## 0. 执行摘要

回答本阶段核心问题：

> 一个 Candidate 即使没有走完整 Evaluation / Promotion 流程，
> 有没有办法绕过系统，直接被 Registry / Runtime 采用？

代码考古结论（FACT，§2）：

```text
有。当前仓库没有任何一层验证“合法 PromotionDecision”：
  - pilot 路径：harness 只凭 evaluation["verdict"] == "PASS" 调
    registry.promote()，promote() 直接写 state="promoted"；
  - runtime 采用：discover() 只查 state=="promoted"，随后直接跑
    artifact；docker_launch 可运行任意目录；
  - 第一消费者控制面：decision 只作为证据存在，没有任何消费端把
    decision 变成写权限；Langfuse 生产采用 = 人工移动 label / isActive；
  - 第二消费者：gate 只输出 PASS/FAIL/INCONCLUSIVE，没有 promotion
    写路径。
```

> 如果没有绕过路径，谁拥有最终否决权？

当前事实：**没有人** —— 最终否决权事实上是 `registry.promote()` 的调用者
（harness）和 Langfuse 人工 label 操作者（FACT，§2 / §11）。

协议目标（本阶段设计，未实现）：

```text
Control Plane  = authoritative decision（PROMOTE / HOLD / REJECT）
Registry       = authoritative state transition（PROMOTABLE -> PROMOTED）
Runtime        = final defensive verification（activation 前最后一层）
```

最终推荐：**Primary Enforcement = Registry；Secondary Defense = Runtime；
Control Plane 是决策权威但不是写权限**。理由与不一致处理见 §11。

最终判定：

```text
ADOPTION_GUARD_DESIGN_VALID_WITH_UNKNOWN
```

```text
FACT      offline adoption guard contract 可机械检查且本阶段测试通过。
FACT      Evaluation 层存在 policy 冻结强制（E.7 runner）。
FACT      Registry / Runtime 当前没有 adoption guard；bypass 1-11 成立。
UNKNOWN   production enforcement（真实 Registry / Runtime / Langfuse
          未接入，本阶段不接）。
```

不是 `ADOPTION_GUARD_DESIGN_VALID`：revocation / write-once 存储 /
真实 runtime 强制均未实现。
不是 `ADOPTION_GUARD_DESIGN_PARTIAL`：设计契约完整且可机械验证，缺的是
落地层，不是设计层。

---

## 1. Business Problem

Agent 能力从 Candidate 到生产采用，业务上必须回答一个问题：

> “这个 Candidate Version 有没有合法采用资格？”

而不是：

> “这个 Candidate 有没有通过 Evaluation？”

二者不同：Evaluation 证据存在 ≠ 有合法采用资格。合法采用资格由
`PromotionDecision == PROMOTE` + 完整绑定（candidate / version / run /
policy / provenance / lifecycle / 非 stale）+ 系统实际状态迁移共同构成。

本阶段要防住的不是“质量差的 candidate 被采用” —— 那是 evaluation /
regression 的职责 —— 而是“**没有合法 Decision 的 candidate 被采用**”，
包括伪造、错绑、过期、被撤销、以及直接写状态绕过。

目标：

```text
合法 Candidate   -> Allowed
非法 Candidate   -> ADOPTION_BLOCKED
```

---

## 2. Current Code Fact（真实路径考古）

### 2.1 Pilot 路径（Capability Forge 实验切片）

```text
Candidate registration
  src/forge/capabilityizer.py:117-119
    capabilityize() 写 candidate.json {candidate_id, name, state:"candidate"}
    [write point；之后没有任何代码更新该状态]
    ↓
  src/forge/validator.py:69,96
    validate() 写 validation.json
    [write point]
    ↓
  src/forge/evaluator.py:24,55,68
    evaluate() 写 evaluation.json {verdict: PASS/FAIL}
    [write point；authorization = evaluator 自己，无 decision]
    ↓
  pilot/harness.py:593-605（phase_b3_build）
    evaluation["verdict"] == "PASS" -> registry.promote(...)
    else -> registry.reject(...)
    [authorization point；当前 = harness 进程，无 PromotionDecision]
    ↓
  pilot/registry.py:17-42（promote）
    参数 (family, name, candidate_dir, evaluation, registry_root)
    直接写 entry.state = "promoted"（line 36），拷贝 artifact
    [write point；authoritative state transition（当前）]
    ↓
  pilot/harness.py:655-659（B3 future invoke）
    registry.discover(...) -> 只检查 state == "promoted"
    [read point；无 decision / provenance / digest 比对]
    ↓
  forge.sandbox.launch（docker_launch，harness.py:35）
    直接运行 entry["artifact_dir"]
    [runtime activation；无 guard；docker_launch 本身可运行任意目录]
```

Registry 事实：

```text
FACT  pilot/registry.py:1
      docstring 明确 "EXPERIMENT_ONLY: flat two-state dir, no SQLite,
      no multi-version, no revoke"。
FACT  promote() 签名没有 decision / policy / provenance 参数（17 行）。
FACT  promote() 不验证 evaluation 是否属于该 candidate、verdict 是否
      PASS、是否有合法 decision（17-42 行）。
FACT  discover() 只返回 state=="promoted" 的 entry（64-71 行），
      不校验 adopted version / decision。
FACT  reject() 只写 state="rejected"，不记录终态语义（44-62 行）。
FACT  registry entry 不存 candidate_id，只有 evaluation dict 里的
      candidate_id 可追溯（promote() 的 entry 结构，36-42 行）。
```

### 2.2 第一消费者控制面（Phase 6-E / E.7）

```text
Evaluation 层（真实强制，FACT）：
  provider_probe.py:1337-1338  _promotion_policy_frozen()
    mutable promotion-policy.json == promotion_policy() 才算 frozen
  provider_probe.py:1541-1635  evaluate_promotion_gate()
    policy_frozen=False                    -> reject "policy_changed_post_hoc"
    e6_decision != REGRESSION_SAFETY_CONFIRMED -> reject
    -> Evaluation 层存在“无 policy / policy 不一致则拒绝运行/拒绝 PROMOTE”
       的强制（FACT，E.7）

Decision 层（契约存在，无消费端，FACT）：
  evaluation/promotion.py:230-237  decide()
    policy_ref 默认 None；_policy_gate(None) 返回 GATE_NOT_APPLICABLE
    （219-227 行），且 policy gate 不在 required gates（286 行）
    -> 无 policy 也能产出 decision（FACT）
  promotion.py:304  decision = PROMOTED
    -> 注意命名冲突：Phase 5-N 把“决策结果”命名为 PROMOTED，
       与“系统已采用”的 PROMOTED 同名（§6）
  decide() docstring：不部署、不路由、不写 registry（FACT）

Langfuse 路径：
  research/control-plane-loop/promote.py:55
    只 POST isActive=False + label control-plane-candidate（FACT）
  docs/archaeology/control-plane/langfuse/03-improvement-promotion.md §3
    label 是唯一部署指针；新版本打同名 label 会移除旧 label；
    label 移动是人工/API 操作，无 eval gate（FACT，已归档审计）
  INFERENCE 基于 API payload shape，可能存在直接创建 active prompt 的
    路径；UNKNOWN Langfuse 服务端是否允许。
```

### 2.3 第二消费者（S7.2 / S7.3）

```text
FACT  gate_calibration.py:524-531  gate_decide()
      只输出 PASS / FAIL / INCONCLUSIVE。
FACT  S7.2 边界（58/60）：Gate 不触发 promotion。
FACT  原实验没有 registered policy / manifest（58/60）-> 协议级 PROMOTE
      不可达（61）。
FACT  第二消费者当前只有 evaluation evidence，没有 promotion 写路径。
```

### 2.4 当前 authority 总结

```text
FACT  没有任何代码消费 PromotionDecision 去写 registry / runtime。
FACT  registry.promote() 不要求合法 PromotionDecision。
FACT  runtime 只依赖 promoted state。
FACT  Langfuse 生产采用 = 人工 label / isActive 操作。
因此：当前“谁能让 Candidate 变成 promoted/adopted” =
  registry.promote() 的调用者 / Langfuse 人工操作者。
```

---

## 3. Adoption Guard Responsibility

Adoption Guard **不负责**：

```text
- LLM judging
- evaluation
- regression scoring
- attribution
- prompt optimization
- candidate quality scoring
```

它只负责一件事：

```text
“这个 Candidate Version 有没有合法采用资格？”
```

最小职责 = 在每一次“把 Candidate 变成系统已采用状态”的写路径前，验证
§7 的 14 项检查；任一失败 -> `ADOPTION_BLOCKED` + machine-readable reason
code。

---

## 4. AdoptionRequest（最小 conceptual contract）

本阶段不定义 API，只定义概念契约。Registry / Runtime 的每一次采用请求
必须携带：

```text
adoption_id             采用事件唯一 id（审计用）
candidate_id            Candidate 稳定身份
candidate_version       不可变 Candidate 版本（必须绑定 immutable version）
artifact_digest         拟采用 artifact 的 digest（必须等于 decision /
                        run / candidate 的 artifact digest）
promotion_decision_id   授权采用的 PromotionDecision id
evaluation_run_id       该 Decision 引用的 EvaluationRun id
policy_version          Decision / Run / Policy 三方一致的 policy version
requested_by            请求方（进程 / 角色 / principal）
requested_at            请求时间
provenance              policy / evidence_manifest / run_ids /
                        immutable_artifact_refs 四要素
```

离线快照形状与 Phase 7.2/7.3 兼容（`adoptions[]` 逐项即为 AdoptionRequest；
`promotion_decision_id` 对应 Phase 7.3 的 `decision_id`，`evaluation_run_id`
必须等于 decision 的 `run_id`）。

---

## 5. AdoptionResult

```text
Allowed   -> 允许执行 PROMOTABLE -> PROMOTED 状态迁移
Blocked   -> ADOPTION_BLOCKED + reason code
```

Blocked 必须有 machine-readable reason code。本阶段契约的完整 code 集：

```text
REQUEST_METADATA_MISSING   AdoptionRequest 缺少必要字段
MISSING_DECISION           引用的 PromotionDecision 不存在
DECISION_NOT_PROMOTE       decision.value != PROMOTE
GATE_NOT_PASS              decision.gate_result != PASS
RUN_MISSING                decision 引用的 EvaluationRun 不存在
RUN_MISMATCH               request.evaluation_run_id != decision.run_id
CANDIDATE_ID_MISMATCH      request / decision / run 三方 candidate_id 不一致
CANDIDATE_VERSION_MISMATCH request / decision / run / candidate.version 不一致
POLICY_VERSION_MISMATCH    request.policy_version != decision.policy_version
POLICY_NOT_REGISTERED      policy 不存在或未 registered
POLICY_NOT_FROZEN          policy 未 frozen
RUN_POLICY_MISMATCH        run / decision / request 的 policy 绑定不一致
PROVENANCE_INCOMPLETE      provenance 四要素缺失
DECISION_TAMPERED          decision recorded_hash != current_hash
EVIDENCE_TAMPERED          该 run 的 evidence 被篡改
MISSING_LIFECYCLE          candidate 无 lifecycle 记录
INVALID_LIFECYCLE          lifecycle.status != PROMOTABLE，或缺少
                           PROMOTABLE -> PROMOTED transition
CANDIDATE_REJECTED         candidate 处于 REJECTED
REVOKED_DECISION           decision 已被显式撤销（当前系统无撤销存储，
                           UNKNOWN；契约已定义）
STALE_DECISION             decision 过期 / 被更新 decision 取代
PROMOTED_WITHOUT_DECISION  registry/lifecycle 出现 promoted 状态但没有
                           通过 Guard 的 adoption
ARTIFACT_DIGEST_MISMATCH   adoption / decision / run / candidate 的
                           artifact digest 不一致或缺失
MISSING_DECISION_TIMESTAMP decision.created_at 缺失（fail closed）
```

说明：`MISSING_DECISION` / `INVALID_LIFECYCLE` 与 Phase 7.3 冻结 code
`DECISION_MISSING` / `INVALID_ADOPTION_LIFECYCLE` 同义；Phase 7.4 契约
使用本文件 code 集，落地时以本文件为准。

---

## 6. PROMOTE / PROMOTABLE / PROMOTED（严格定义）

```text
PROMOTE      = PromotionDecision 的决策结果
               （decision.value == "PROMOTE"；gate 全部通过）
PROMOTABLE   = Candidate 已满足 adoption prerequisites
               （PROMOTE decision 已生成，等待 adoption 触发）
PROMOTED     = 系统真正采用
               （Registry 写入 / Runtime active 指针 / lifecycle 状态）
```

强制关系：

```text
PROMOTE -> PROMOTABLE -> [Adoption Guard] -> PROMOTED
```

禁止：

```text
PROMOTE 直接写成 PROMOTED
```

代码考古发现的命名冲突（FACT）：

```text
docs/archaeology/deepseek-harness/evaluation/promotion.py:304
  decide() 的 decision 值使用 "PROMOTED" 表示“promotion eligible”。
这与“PROMOTED = 系统已采用”同名，正是本阶段要切断的混淆。
Phase 7.2/7.3 离线快照使用 decision.value == "PROMOTE"（规范形态）。
```

Phase 7.4 契约规定：Adoption Guard 只接受 `decision.value == "PROMOTE"`；
旧契约的 `"PROMOTED"` 决策值在 adoption 边界一律视为
`DECISION_NOT_PROMOTE`（离线测试覆盖，§17）。旧 `PromotionDecision` 对象
可以继续作为 Phase 5-N 契约存在，但不能作为 Adoption Guard 的授权凭证。

---

## 7. Validation Rules（14 项）

Adoption Guard 在放行前必须同时满足：

```text
1.  PromotionDecision 存在（MISSING_DECISION）
2.  decision.value == PROMOTE（DECISION_NOT_PROMOTE）
3.  candidate_id binding：
    adoption.candidate_id == decision.candidate_id == run.candidate_id
    （CANDIDATE_ID_MISMATCH）
4.  candidate_version binding：
    adoption.candidate_version == decision.candidate_version
    == run.candidate_version == candidate.version
    （CANDIDATE_VERSION_MISMATCH）
5.  decision 引用的 EvaluationRun 存在（RUN_MISSING）
6.  run binding：
    adoption.evaluation_run_id == decision.run_id（RUN_MISMATCH）；
    run.candidate_id == decision.candidate_id == adoption.candidate_id
    （CANDIDATE_ID_MISMATCH，rule 3 同一检查）
7.  policy 已 registered（POLICY_NOT_REGISTERED）
8.  policy 已 frozen（POLICY_NOT_FROZEN）
9.  run-policy match：
    run.policy_ref == decision.policy_ref；
    run.policy_version == request.policy_version == policy.version
    （RUN_POLICY_MISMATCH）
10. provenance 完整（policy / evidence_manifest / run_ids /
    immutable_artifact_refs；PROVENANCE_INCOMPLETE）
11. lifecycle 记录存在且 status == PROMOTABLE
    （MISSING_LIFECYCLE / INVALID_LIFECYCLE）
12. lifecycle 明确存在 PROMOTABLE -> PROMOTED transition
    （INVALID_LIFECYCLE）
13. decision 不是 stale / 未被 revoked
    （STALE_DECISION / REVOKED_DECISION；§8 / §9）
14. artifact digest binding：
    adoption.artifact_digest == decision.artifact_digest
    == run.artifact_digest == candidate.forged_artifact_digest
    （ARTIFACT_DIGEST_MISMATCH）
```

任一失败：

```text
ADOPTION_BLOCKED + 具体 reason code
```

规则 1-13 在 Phase 7.2 / 7.3 契约与离线快照中已可机械检查（FACT）；
规则 14 是 Phase 7.4.1 新增的最小契约扩展：adoption / decision / run
增加 `artifact_digest`，candidate 复用真实字段名
`forged_artifact_digest`（src/forge/capabilityizer.py:111
`manifest.provenance.forged_artifact_digest`；pilot runtime 已有
`artifact_digest` 概念，pilot/harness.py:732）。
14 条规则的“生产 enforcement”（真实 Registry / Runtime 强制）仍全部
UNKNOWN（§15）。

另加一条 Registry 一致性规则（state-only trust 禁止）：

```text
任何 registry entry.state == "promoted" 或 lifecycle.status == "PROMOTED"
必须能映射到一个通过全部 14 项检查的 AdoptionRequest；
否则 PROMOTED_WITHOUT_DECISION -> ADOPTION_BLOCKED。
```

---

## 8. Stale Decision（生产最重要的问题之一）

先回答问题：

> Candidate v1 -> PROMOTE；之后 Candidate v2 -> HOLD / REJECT。
> 旧 v1 Decision 是否还能采用？

代码事实：

```text
FACT  pilot registry 只有 version=1，无多版本、无 adopted-version 指针
      （pilot/registry.py:1 docstring；promote 写 version: 1）。
FACT  当前没有 revocation / supersession 存储（同 docstring）。
FACT  Phase 7.3 的 stale 只按“同一 candidate_version 的最新 PROMOTE
      decision”判断（phase7.3/validate_enforcement_contract.py）。
FACT  Decision 字段没有“有效期”概念（evaluation/promotion.py PromotionDecision
      frozen dataclass）。
```

因此 Phase 7.4 定义 / 沿用以下可机械检查规则：

```text
Decision 必须绑定 immutable candidate_version。
不允许 Decision(candidate v1) 授权 adoption(candidate v2)。
```

加上四条可机械检查的 stale 规则：

```text
S1  adoption.candidate_version != decision.candidate_version
    -> CANDIDATE_VERSION_MISMATCH（不是 stale，是错绑；§7-3）
S2  同一 (candidate_id, candidate_version) 下，如果存在比本 decision
    更新的 PROMOTE decision，则本 decision 是 STALE_DECISION
S3  同一 (candidate_id, candidate_version) 下，如果存在比本 decision
    更新的 HOLD / REJECTED / REJECT / CANARY / PENDING decision，
    则本 decision 被 supersede，是 STALE_DECISION
S4  decision.created_at < candidate.created_at -> STALE_DECISION
```

历史说明：S4 **不是 Phase 7.4 新增**。Phase 7.3 validator 已经包含
`decision.created_at < candidate.created_at` 的 stale-timestamp 保护
（phase7.3/validate_enforcement_contract.py）；Phase 7.4 在 adoption
边界复用并强化该规则（S2 / S3 的 supersede 检查为 Phase 7.4 扩展；
S4 缺失 timestamp 时由 Phase 7.4.1 改为 `MISSING_DECISION_TIMESTAMP`
fail closed，禁止 TypeError crash）。

S3 的意义：v2 的 HOLD/REJECT 不改变 v1 的内容，但改变 v1 的**采用资格**；
“v1 质量没变”不是“v1 可以上线”的理由，因为系统已经对同一版本线给出
更新的否定决策。生产语义：同一 candidate_version 出现非 PROMOTE 新决策
后，旧 PROMOTE 立即失效，必须由新决策（或显式重新 PROMOTE）重新授权。

---

## 9. Revocation / Supersession

### 9.1 当前系统事实

```text
FACT  没有 version status / revoked / superseded / active version 存储。
FACT  pilot registry：单版本、无 revoke（docstring）。
FACT  Phase 5-N 只有 RollbackDecision（REQUESTED 状态），没有 rollback
      execution、没有 revocation 存储（promotion.py request_rollback）。
FACT  Langfuse 回滚 = 人工把 label 移回旧版本，无撤销记录语义。
```

结论：**当前系统没有 revocation**。不得假设有。

### 9.2 契约规则

```text
Supersession（机器可检查，FACT，已实现）：
  更新的非 PROMOTE decision 使旧 PROMOTE 失效（§8 S3）。

Revocation（契约已定义，生产 UNKNOWN）：
  若快照存在 revocations[]，且存在匹配
  (candidate_id, candidate_version, decision_id) 的记录，
  -> REVOKED_DECISION -> ADOPTION_BLOCKED。
  revocations[] 不存在 = 无撤销信息（UNKNOWN），Guard 不伪造撤销，
  但最终判定必须带 UNKNOWN。
```

### 9.3 如果 PROMOTE v1 后 v1 被撤销，Guard 如何知道？

```text
必须存在显式 revocation 记录（revocation_id / candidate_id /
candidate_version / decision_id / revoked_at / reason）。
当前系统没有该记录 -> UNKNOWN，Guard 无法知道；这是生产落地前的
必须缺口，不是可忽略细节。
```

---

## 10. Enforcement Placement Matrix

| Check | Evaluation | Control Plane | Registry | Runtime |
| --- | --- | --- | --- | --- |
| policy frozen | Primary（E.7 runner BLOCKED，FACT） | Primary（gate 要求 frozen，FACT） | Secondary（写前重验，设计） | Secondary（activation 前重验，设计） |
| policy binding | Audit-only（runner 按 registered bytes 运行；显式检查在离线 validator） | Primary（decision 必须携带 policy_ref/version，设计） | Secondary（request/decision/run 三方一致，设计） | Secondary（同左，设计） |
| candidate/version binding | Primary（run 记录 candidate/version，FACT） | Primary（decision 绑定 immutable version，设计） | Secondary（transition 请求必须匹配，设计） | Secondary（activation target 必须匹配，设计） |
| decision validity | Audit-only（evidence 供 decision 计算） | Primary（PROMOTE/HOLD/REJECT 的签发者） | Secondary（写前验证 status/gate/hash，设计） | Secondary（激活前验证，设计） |
| provenance | Primary（E.6 precondition + manifest，FACT） | Primary（G4 必须完整，FACT） | Secondary（写前重验，设计） | Secondary（激活前重验，设计） |
| lifecycle | Audit-only | Primary（把 candidate 推进到 PROMOTABLE；当前无引擎，设计） | Primary（PROMOTABLE -> PROMOTED 的权威迁移点，设计） | Audit-only（只消费 lifecycle，不修改） |
| staleness | Audit-only | Primary（签发新 decision 即 supersede，设计） | Secondary（写前查最新 decision，设计） | Secondary（激活前重查，设计） |
| revocation | Audit-only | Primary（唯一能撤销/恢复的地方，设计；当前无存储，UNKNOWN） | Secondary（拒绝已撤销 transition，设计） | Secondary（拒绝已撤销版本激活，设计） |
| final adoption | Audit-only | Audit-only（decision 是证据，不是写权限） | Primary（state transition 的权威执行者） | Secondary（激活前最后验证） |

角色定义：

```text
Primary   = 该检查的权威来源 / 必须强制的位置
Secondary = 防御性重验（不能替代 Primary，但能拦 Primary 被绕过）
Audit-only = 事后记录 / 检测，不构成 enforcement
```

---

## 11. 谁拥有最终否决权（三方案比较）

### 方案 A：Control Plane 是最终否决

```text
支持：decision 是唯一授权凭证；Evaluation 层已有强制（E.7，FACT）。
反对（FACT）：当前没有任何代码消费 decision 去写 registry/runtime；
  decision 只是证据。若 Control Plane 是最终否决，绕过 Registry 直接
  写文件 / 人工移动 Langfuse label 仍无法拦截。Control Plane 只能决定
  “什么可以”，不能决定“什么实际发生”。
```

### 方案 B：Registry 是最终否决

```text
支持（FACT）：repo 自身路径中，promoted 状态的唯一权威写点就是
  registry.promote()；在写入前校验 decision 可以一次性关闭
  bypass 1/3/4/8/9/10/11（repo 内路径）。
反对：Langfuse 人工 label 路径不经 registry；Runtime 直接激活路径
  不经 registry。Registry 拦不住它们。
```

### 方案 C：Runtime 是最终兜底

```text
支持：Runtime 是生产流量真正发生的地方，能拦“registry 被绕过但
  runtime 直接激活”。
反对：Runtime 看不到完整 decision 图 / write-once 存储；若 registry
  已经写了 promoted，runtime 只能拒绝激活，不能纠正状态。它适合做
  defense，不适合做 authority。
```

### 最终推荐

```text
Primary Enforcement   = Registry（authoritative state transition）
Secondary Defense     = Runtime（final defensive verification）
Decision Authority    = Control Plane（只签发 decision，不拥有写权限）
```

回答四个问题：

```text
谁拒绝错误 adoption？      Registry 写 guard（Primary）；
                           Runtime 激活 guard（Secondary）。
谁是最终 authority？       Registry 是“PROMOTED 状态”的最终 authority；
                           Control Plane 是“PROMOTE 决策”的最终
                           authority。两者不可互相替代。
谁只是防御性检查？         Runtime 只是防御性检查；它不能写状态，
                           不能纠正 registry。
两层结果不一致怎么办？     fail closed：
                           - Control Plane 说 PROMOTE、Registry 验证失败
                             -> 不迁移（decision 是证据不是写令牌）
                           - Registry 已 promoted、Runtime 验证失败
                             -> 不激活；视为生产事件，需要控制面
                             撤销/修正（revocation，UNKNOWN）
                           - Runtime 拦截后 registry 状态不自动纠正
                             -> 必须通过控制面 revocation 恢复一致性
```

这一推荐是 **INFERENCE**（从 §2 代码事实推导的设计判断），不是代码事实。

---

## 12. Bypass Closure Matrix（11 条）

| # | 绕过路径 | CURRENT FACT | TARGET CONTROL | REMAINING UNKNOWN |
| --- | --- | --- | --- | --- |
| 1 | Candidate → Registry 直接写入 | FACT：`registry.promote()` 无 decision 参数（pilot/registry.py:17-42）；任何调用者可传任意 evaluation | Registry 写 guard：只接受带合法 AdoptionRequest 的迁移；entry 必须记录 decision_id + adoption_id | write-once 存储未实现；直接编辑 entry JSON 无法由 app 逻辑拦截 |
| 2 | Candidate → Runtime 直接采用 | FACT（repo 侧）：`discover()` 只查 state（registry.py:64-71）；`docker_launch` 可跑任意目录（harness.py:35）；promote.py 只发 isActive=False（FACT）。INFERENCE：API 可能支持直接 active；UNKNOWN：Langfuse 服务端是否允许 | Runtime 激活 guard：无合法 decision 绑定则拒绝激活；digest 与 decision/run 比对 | 真实 Agent Runtime 是否另有外部保护，本仓库无法看到 |
| 3 | Registry API 不校验 PromotionDecision | FACT：promote 签名无 decision | Registry 写 guard：PROMOTED_WITHOUT_DECISION -> ADOPTION_BLOCKED | 同上（write-once） |
| 4 | Runtime 不校验 adopted version | FACT：discover 只查 state；invoke 不比对 artifact digest / manifest / decision | Runtime guard：验证 candidate/version + decision + artifact digest | 真实 Runtime 的激活边界 |
| 5 | PromotionDecision 可以脱离 Policy | FACT：promotion.py:237 policy_ref 可选；_policy_gate(None)=NOT_APPLICABLE；policy gate 不在 required（286 行） | Control Plane：PROMOTE 必须带 registered+frozen policy（G1/G2）；Registry/Runtime 重验（POLICY_NOT_REGISTERED / POLICY_NOT_FROZEN） | 旧 `PromotionDecision.decision="PROMOTED"` 的消费端迁移范围 |
| 6 | PolicyVersion 可以被覆盖 | FACT：mutable promotion-policy.json 曾在 E.7.1 前被改（56a）；S7.2 全 "w" 覆盖写；无 write-once | 存储层 write-once / append-only + hash 链；Guard 检测 POLICY_NOT_FROZEN / hash 变化 | write-once 信任锚点形态（SQLite 约束 / WORM / signed hash chain）未实现 |
| 7 | Historical Evidence 可以被 update | FACT：E.7.1 审计发现 matrix/stats/gate 被重写后逐字节恢复；S7.2 覆盖写 | 同 6（G5/G7 存储层强制）；Guard 检测 EVIDENCE_TAMPERED | 同上 |
| 8 | HOLD candidate 可以被错误标记 Active | FACT：无状态机代码；registry 条目可被任意写为 promoted；Langfuse isActive 人工可改 | Registry guard：只有 PROMOTABLE + 合法 decision 才迁移；Runtime：非 PROMOTED lifecycle 不激活 | Langfuse 服务端是否允许外部直接改 isActive |
| 9 | REJECTED candidate 可以重新激活 | FACT：candidate.json 无终态；registry 重名拒绝只是偶发 guard；Langfuse 无 REJECTED 概念 | CANDIDATE_REJECTED -> ADOPTION_BLOCKED；REJECTED 为终态；重新提案 = 新 candidate_version 从 DRAFT 开始 | 真实服务端是否存在 REJECTED 语义 |
| 10 | stale PromotionDecision 可用于新 Candidate | FACT：无 decision_id→candidate 绑定消费；无有效期；registry 不读 decision | Decision 绑定 immutable candidate_version；STALE_DECISION；registry/runtime 重查最新 decision | decision 有效期是否还需要引入（当前只有“最新决策”规则） |
| 11 | Candidate lifecycle 状态永不迁移 | FACT：capabilityizer 写 state="candidate" 后再无任何更新（capabilityizer.py:117-119） | 控制面 lifecycle 引擎（DRAFT→…→PROMOTABLE→PROMOTED）；缺失 lifecycle = MISSING_LIFECYCLE -> fail closed | lifecycle 引擎的存储与实现 |

---

## 13. Failure Closed Semantics

Adoption Guard 遇到以下任一情况：

```text
policy mismatch
decision missing
decision timestamp missing（MISSING_DECISION_TIMESTAMP）
provenance missing
stale decision
lifecycle invalid
artifact digest mismatch（ARTIFACT_DIGEST_MISMATCH）
registry promoted without decision
```

必须：

```text
fail closed -> ADOPTION_BLOCKED
```

禁止：

```text
- fallback to state（“registry 说 promoted 就算数”）
- fallback to latest version
- fallback to last known good
- fallback to manual active state
```

Break-glass 本阶段只讨论不实现：唯一可接受形态是“经过 policy 批准的、
有审计记录的显式覆盖机制”，且必须本身走 Guard 的例外通道（例如
policy 声明 break-glass 授权 + decision 记录），不能是“绕开 Guard 直接
改状态”。任何未定义的 break-glass = 不存在。

---

## 14. Runtime Boundary

Runtime 最后一层只负责：

```text
“我即将激活的 candidate version，是否携带合法 Promotion Decision？”
```

具体检查（与 §7 相同的最小集，可缓存但不可省略）：

```text
1. 激活目标 = 合法 adoption 记录的 candidate_id + candidate_version
2. decision.value == PROMOTE，且不是 stale / revoked
3. lifecycle == PROMOTED（且其 PROMOTABLE -> PROMOTED transition
   与 adoption 记录一致）
4. artifact digest 与 decision/run 记录的 hashes 一致
5. policy frozen + binding 一致
6. provenance 完整
```

Runtime 不负责：

```text
- 判断 quality / regression / attribution
- 解释证据
- 修改 registry / lifecycle 状态
- 代替 Control Plane 签发 decision
```

Runtime 无法验证 -> 拒绝激活（fail closed）。当前没有任何 runtime 实现
这个 guard（FACT，§2）。

---

## 15. FACT / INFERENCE / UNKNOWN

```text
FACT
  - pilot registry.promote() 无 decision 校验；discover 只查 state；
    capabilityizer 后 lifecycle 不再迁移（§2 文件行号）。
  - Evaluation 层存在 policy 冻结强制（E.7 runner）。
  - promotion.py policy_ref 可选；decision 值 "PROMOTED" 与采用状态
    同名（命名冲突）。
  - Langfuse label 是人工部署指针；repo 代码只发 isActive=False。
  - Phase 7.2/7.3 离线契约可机械检查（29 / 26 tests）。
  - 本阶段 offline adoption guard contract 可机械检查（§17 测试通过）。
  - Phase 7.4.1：artifact digest binding（ARTIFACT_DIGEST_MISMATCH）
    与 decision timestamp fail-closed（MISSING_DECISION_TIMESTAMP）
    已加入离线契约；candidate digest 复用
    `forged_artifact_digest`（src/forge/capabilityizer.py:111）。
  - Phase 7.3 已含 S4 stale-timestamp 保护；Phase 7.4 复用并强化。

INFERENCE
  - Control Plane = decision authority；Registry = state authority；
    Runtime = final defense（§11，从 FACT 推导）。
  - Langfuse API 可能存在直接 active 路径（从 payload shape 推导）。
  - 缺失 lifecycle 必须 fail closed 而非默认放行（从 65 修复推导）。

UNKNOWN
  - production enforcement（真实 Registry / Runtime / Langfuse 未接入）。
  - Langfuse 服务端是否允许外部直接创建 active prompt。
  - revocation / supersession 存储是否存在（当前无，必须显式建立）。
  - write-once 存储（G5/G7 的真正强制）未实现。
  - 真实 Agent Runtime 是否另有外部保护。
  - decision 是否还需要引入显式有效期（当前只有“最新决策”规则）。
```

---

## 16. MVP Boundary（本阶段不做）

```text
不做：
- 真实 Registry 接入 / registry.promote() 改造
- Runtime 改造 / activation guard 实现
- Langfuse API interception
- write-once storage implementation
- revocation 存储实现
- E.8 / production rollout
- 修改 E.5-E.7.1、Phase 7 / 7.1 / 7.2 / 7.3 冻结文件
```

落地顺序建议（未来阶段，本阶段不执行）：

```text
1. Registry 写 guard（决策验证 + decision_id 落库）
2. Control Plane 消费端（decision -> AdoptionRequest）
3. Runtime 激活 guard（final defense）
4. write-once / revocation 存储（G5/G7 + REVOKED_DECISION 落地）
5. Langfuse 侧拦截（人工 label 移动审计 / API 网关）
```

---

## 17. Offline Proof

新增：

```text
docs/archaeology/unified-runtime/66-adoption-guard-design.md
docs/archaeology/unified-runtime/phase7.4/validate_adoption_guard_design.py
docs/archaeology/unified-runtime/phase7.4/test_adoption_guard_design.py
```

覆盖矩阵（全部为 ADOPTION_BLOCKED 或 allowed）：

| 场景 | 结果 |
| --- | --- |
| valid adoption + registry 一致 | Allowed（ADOPTION_GUARD_DESIGN_VALID） |
| 无 revocations 键但其余合法 | Allowed（VALID_WITH_UNKNOWN） |
| missing decision | MISSING_DECISION |
| wrong candidate | CANDIDATE_ID_MISMATCH |
| wrong version | CANDIDATE_VERSION_MISMATCH |
| wrong policy | POLICY_VERSION_MISMATCH |
| unfrozen policy | POLICY_NOT_FROZEN |
| missing provenance | PROVENANCE_INCOMPLETE |
| DRAFT / missing lifecycle | INVALID_LIFECYCLE / MISSING_LIFECYCLE |
| 更新的 PROMOTE / HOLD 决策 | STALE_DECISION |
| REJECTED candidate | CANDIDATE_REJECTED |
| 显式 revocation 记录 | REVOKED_DECISION |
| registry state=promoted 无 decision | PROMOTED_WITHOUT_DECISION |
| 旧契约 decision.value == "PROMOTED" | DECISION_NOT_PROMOTE（命名冲突拦截） |
| request 缺 requested_by 等 | REQUEST_METADATA_MISSING |
| adoption/decision/run/candidate digest 不一致或缺失 | ARTIFACT_DIGEST_MISMATCH |
| decision.created_at 缺失 | MISSING_DECISION_TIMESTAMP |
| all artifact digests match | Allowed（VALID / VALID_WITH_UNKNOWN） |

验证命令（实际运行）：

```text
python3 -m pytest docs/archaeology/unified-runtime/phase7.4 -q
python3 -m py_compile docs/archaeology/unified-runtime/phase7.4/*.py
```

结果（见下节）：

```text
offline tests           = 30 passed
py_compile              = COMPILE_OK
documentation consistency = PASS（66 号报告列出全部 code）
```

注意：offline proof 证明“契约自洽、可机械检查”，不证明 production
enforcement。不要把 offline proof 说成 production enforcement。

---

## 18. Open Questions

```text
1. decision 是否需要显式有效期（TTL）？“最新决策”规则已可拦大部分
   stale，但“很久以前的唯一 PROMOTE”是否仍有效未定义。
2. revocation 存储形态（SQLite / append-only log / signed hash）未定。
3. Registry entry 需要新增 decision_id / adoption_id / candidate_id
   字段；与现有 entry 的兼容迁移未设计。
4. Langfuse 人工 label 移动如何被拦截或至少被审计（API 网关 vs
   webhook vs 只读 label 权限）未定。
5. 多版本 registry（adopted-version 指针）未实现；当前只有 version=1。
6. Runtime 激活 guard 与真实 Codex / 其他 runtime 的集成边界未定。
7. break-glass 的 policy 声明形态未设计（本阶段明确不实现）。
```

---

## 19. 最终判定

```text
ADOPTION_GUARD_DESIGN_VALID_WITH_UNKNOWN
```

```text
FACT:
  offline adoption guard contract 可机械检查（30 passed）；
  AdoptionRequest / AdoptionResult / 14 项规则 / stale / supersession /
  registry state-only trust 禁令已定义并可离线验证；
  Evaluation 层存在 policy 冻结强制；
  Registry / Runtime 当前仍无 adoption guard（bypass 1-11）。

UNKNOWN:
  production enforcement（真实 Registry / Runtime / Langfuse 未接入）；
  revocation / write-once 存储不存在；
  真实 Agent Runtime 外部保护。
```

Stop：不 commit、不 push、不接真实 Registry / Runtime / Langfuse、不做
E.8、不做 production rollout、不修改 Phase 6-E / 7 / 7.1 / 7.2 / 7.3
已冻结文件。
