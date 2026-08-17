# 64 — Protocol Enforcement Boundary（Phase 7.3）

> 阶段：Phase 7.3（Enforcement Boundary；代码考古 + 架构边界 + 最小
> offline proof）。
> 基线：63（Phase 7.2，CONTRACT_VALID_WITH_EXTENSIONS）、61（Phase 7.1，
> Core + Extension + Governance Invariants）、57（Phase 7 Control Plane
> synthesis）、56/56a（E.7 / E.7.1）。
> 约束遵守：未修改 E.5–E.7.1、48/51/52/53、Phase 7 / 7.1 / 7.2 已冻结证据；
> 未做 E.8；未做 production promotion；未连接真实 Runtime；未运行 live
> provider；未 commit / push。

## 0. 执行摘要

本阶段回答：

> 如果有人绕过 Evaluation、伪造 Promotion Decision、使用未冻结 Policy、
> 或直接把未通过 Gate 的 Candidate 注册进 Runtime，系统能不能阻止？

代码考古结论（FACT，见 §1）：

```text
当前仓库没有单一权威的 adoption guard。
谁最终能让 Candidate 变成 promoted/adopted：
  - pilot 路径：调用 registry.promote() 的代码/进程（实际是 harness），
    它只依赖 evaluation dict 的 verdict == "PASS"，不校验 decision、
    policy、provenance；
  - 第一消费者控制面：gate 引擎产出 Decision，但没有任何代码消费
    Decision 去写 registry/runtime；最终采用 = 人工移动 Langfuse label /
    isActive；
  - runtime：只检查 registry entry.state == "promoted"，不校验 decision
    与 provenance。
```

因此把“合法采用”从“证据状态”中分离出来，是本阶段定义的最小边界：

```text
PROMOTE      !=  PROMOTABLE      !=  PROMOTED / ADOPTED
PROMOTE：Promotion Decision 的决策结果（gate 已通过）。
PROMOTABLE：Candidate 满足采用前置条件（Decision 已生成，等待触发）。
PROMOTED：系统已正式采用（registry 写入 / runtime active 指针）。
PROMOTE decision 不能直接等同于 PROMOTED adoption；
PROMOTABLE -> PROMOTED 之间必须存在 adoption enforcement boundary。
```

离线验证（FACT，§9 实际运行）：

```text
offline enforcement contract validated
  -> 26 passed（含新增 A-I 必测：candidate_id mismatch ×2 /
     DRAFT / EVALUATING / PROMOTION_REVIEW / missing lifecycle /
     valid PROMOTABLE transition / invalid transition / 全绑定一致；
     另有 RUN_MISSING 回归）
  -> py_compile COMPILE_OK
  -> compileall COMPILE_OK
  -> documentation consistency PASS
```

最终判定：

```text
ENFORCEMENT_BOUNDARY_PARTIAL
```

```text
FACT:
  offline enforcement contract validated（本阶段 26 个测试）；
  Evaluation 层存在 policy 冻结强制（provider_probe.py live runner，
  E.7）；
  Runtime / Registry 层当前没有 adoption guard；
  G5/G7 目前只有审计式检测/恢复，没有 write-once 存储强制。
UNKNOWN:
  production enforcement（真实 Runtime 未接入，本阶段不接）。
```

不是 ENFORCEMENT_BOUNDARY_VALID：真实 runtime/registry 未接入，且
bypass matrix 中多条路径当前可直达。
不是 ENFORCEMENT_BOUNDARY_INVALID：契约自洽且可机械检查，Evaluation 层
已有部分强制，adoption 边界可以落地。

---

## 1. 代码考古：谁真正有权让 Candidate 变成 Active / Promoted / Adopted

### 1.1 pilot 路径（Capability Forge 实验切片）

```text
capabilityizer.py:117-120
  candidate.json 写入 state="candidate"；之后没有任何代码更新该状态。

validator.py / evaluator.py
  validation.json、evaluation.json 直接写入 candidate 目录；
  evaluation["verdict"] = PASS/FAIL 由 evaluator 计算。

harness.py:594-604（phase_b3_build）
  evaluation["verdict"] == "PASS"
    -> registry.promote("F+", name, cand, evaluation, registry_root)
  else -> registry.reject(...)
  没有 PromotionDecision 对象，没有 policy 绑定，没有 provenance 检查。

registry.py:17-42（promote）
  参数是 (family, name, candidate_dir, evaluation, registry_root)；
  把 evaluation dict 原样存入 entry，state 直接写 "promoted"。
  不验证 evaluation 是否属于该 candidate、verdict 是否 PASS、
  是否存在合法 decision。

registry.py:44-62（reject）
  同样只写 state="rejected"，不记录终态语义。

harness.py:655-659（B3 future invoke，即 runtime 采用路径）
  entry = registry.discover(...)          # 只检查 state == "promoted"
  artifact_dir = entry["artifact_dir"]    # 直接跑 artifact
  artifact_digest 只用于 treatment evidence，不与 manifest/decision 比对。
```

结论（FACT）：

```text
pilot 路径的最终否决权 = registry.promote() 的调用者。
协议上应当由合法 PromotionDecision 授权，但代码里 decision 根本不存在。
```

### 1.2 第一消费者控制面（Phase 6-E / E.7）

```text
provider_probe.py:1685-1690（_promotion_gate，live runner）
  if not _promotion_policy_frozen():
      print("BLOCKED: promotion-policy.json missing or differs from
             promotion_policy(); run --write-promotion-policy first")
      return 1
  -> Evaluation 层存在“无 policy / policy 不一致则拒绝运行”的强制（FACT）。

provider_probe.py:1337-1341（_promotion_policy_frozen）
  mutable promotion-policy.json == promotion_policy()（registered 语义）。

evaluate_promotion_gate(...)
  policy_frozen=False 或 e6_decision != REGRESSION_SAFETY_CONFIRMED
  -> REJECT 条件（FACT）。

promotion.py（Phase 5-N 契约）
  PromotionDecision 是 frozen dataclass；
  decide() 校验 candidate.status == VALIDATED、baseline/regression refs、
  stable version、evidence_refs；
  但 policy_ref 是可选参数：_policy_gate(None) 返回 GATE_NOT_APPLICABLE，
  且 policy gate 不在 required gates 里 -> 无 policy 也能产出 PROMOTED
  （FACT，代码直接可见）。
  decide() 不部署、不路由、不写 registry（docstring，FACT）。

promote.py（S6，控制面候选注册）
  只把 candidate 写成 Langfuse prompt：
  label="control-plane-candidate"、isActive=False（FACT）。
  生产采用 = 人工把 label/isActive 移到目标版本
  （langfuse/03：label 是唯一部署指针，人工/API 操作，无 eval gate，
  FACT）。
```

结论（FACT）：

```text
第一消费者有“gate 计算”和“policy 冻结强制”，
但没有“Decision -> adoption”的消费端；
最终采用否决权目前落在人工 Langfuse label 操作者身上。
```

### 1.3 第二消费者（S7.2 / S7.3）

```text
gate_calibration.py / evaluation_result.py
  Gate 只输出 PASS / FAIL / INCONCLUSIVE（FACT）。
  S7.2 边界明确：Gate 不触发 promotion（s7/07，FACT）。
  S1-S6 输出全部以 "w" 覆盖写，历史 run 不保留（s7/02 §1.9，FACT）。
  原实验没有 registered policy 文件 / commit 锚点 / manifest
  （58/60，FACT）-> 协议级 PROMOTE 不可达（61，FACT）。
```

结论（FACT）：

```text
第二消费者当前只有 evaluation evidence，没有 promotion 写路径。
```

---

## 2. Enforcement Layers

```text
Layer A — Evaluation Enforcement
Layer B — Promotion Control Plane Enforcement
Layer C — Runtime / Registry Enforcement
Layer D — Audit-only
```

| 维度 | A Evaluation | B Promotion Control Plane | C Runtime / Registry | D Audit-only |
| --- | --- | --- | --- | --- |
| 谁检查 | live runner（policy frozen）、evaluate_promotion_gate、evaluator | promotion.decide()、gate 引擎、Decision 记录 | registry.discover / invoke（当前只查 state） | E.7.1 审计、phase7.2/7.3 离线 validator、tests |
| 最终否决权 | 可拒绝运行（E.7 FACT）；不能决定采用 | 当前无消费端；Decision 只是证据 | 当前 = registry.promote 调用者 / Langfuse 人工操作 | 无（事后检测） |
| 检查发生在哪一步 | live 运行前 / summary 时 | gate 计算与归档 | registry 写入时、invoke 时（当前缺失） | 任意事后时刻 |
| 绕过是否可能 | 是（直接调用 evaluator / 直接写 evaluation.json） | 是（decide() 可任意调用；policy_ref 可选；gate JSON 可覆盖） | 是（registry.promote 无 decision；直接写磁盘；Langfuse API） | 是（绕过检测即绕过） |
| 第二条写路径 | evaluation.json 直接写 candidate 目录 | 无独立写权限；结果文件 "w" 覆盖 | harness、registry 模块、磁盘编辑、Langfuse public API | N/A |
| 是否需要 Runtime 兜底 | 不需要（上游） | 需要：adoption 前必须重新校验 decision | 需要：这是最后一道闸门 | 不适用 |

---

## 3. G1–G7 逐条分层分析

| Invariant | A Evaluation | B Control Plane | C Runtime/Registry | D Audit | Runtime 兜底 |
| --- | --- | --- | --- | --- | --- |
| G1 no policy | 强制（E.7 runner BLOCKED，FACT） | gate 强制（policy_frozen，FACT） | 缺失（registry.promote 不查 policy） | 可检查（G1） | 需要 |
| G2 policy not frozen | 强制（runner BLOCKED，FACT） | gate 强制（REJECT，FACT） | 缺失 | 可检查（G2） | 需要 |
| G3 run-policy mismatch | 隐性（runner 按 registered bytes 运行，FACT）；显式检查在 validator | gate 的 policy_ref 固定，显式检查在 validator | 缺失 | 可检查（G3） | 需要 |
| G4 incomplete provenance | 部分（E.6 precondition + manifest tests） | 部分（manifest/provenance tests） | 缺失 | 可检查（G4） | 需要 |
| G5 historical evidence immutable | 检测（_promotion_policy_frozen）；无 write-once | 检测（gate 字节比对） | 缺失 | E.7.1 恢复 + 离线 hash（FACT） | 需要（存储层必须 write-once，否则只能事后发现） |
| G6 HOLD retry => new EvaluationRun | policy 声明（FACT）；无 runner 强制 | validator 强制（离线） | 缺失 | 可检查（G6） | 需要（adoption 只能接受新 run 的 decision） |
| G7 no overwrite | 检测；无存储强制 | 检测 | 缺失 | E.7.1 恢复 + 离线重复检测（FACT） | 需要（同 G5） |

结论：

```text
“检查规则”与“必须强制的边界”不是一回事：
G1-G4 在 adoption 边界（registry 写入 / runtime 采用前）必须强制；
G5-G7 必须由存储层强制（write-once / append-only / signed hash），
当前只有 Layer D 检测 -> 只算“检查”，不算“强制”。
```

---

## 4. Bypass Matrix

每条路径标记代码事实等级。

| # | 绕过路径 | 判定 | 代码/文档依据 |
| --- | --- | --- | --- |
| 1 | Candidate → Registry 直接写入 | **FACT** | registry.promote 只收 (candidate_dir, evaluation)，无 decision 校验；任何调用者可传任意 evaluation |
| 2 | Candidate → Runtime 直接采用 | **FACT**（repo 侧） | B3 invoke 只 discover state=="promoted" 后跑 artifact；docker_launch 可直接跑任意目录；repo 内 promote 路径只发送 isActive=False（FACT）。基于 API payload shape 推断可能存在直接建 active prompt 的路径（INFERENCE）。Langfuse 服务端是否允许外部直接创建 active prompt（UNKNOWN） |
| 3 | Registry API 不校验 PromotionDecision | **FACT** | registry.promote 签名没有 decision 参数 |
| 4 | Runtime 不校验 adopted version | **FACT** | discover 只查 state；invoke 不比对 artifact digest / manifest / decision |
| 5 | PromotionDecision 可以脱离 Policy | **FACT** | promotion.decide() policy_ref 可选；无 policy 时 _policy_gate 返回 NOT_APPLICABLE，仍可 PROMOTED |
| 6 | PolicyVersion 可以被覆盖 | **FACT** | mutable promotion-policy.json 曾在 E.7.1 前被改（56a）；S7.2 全部 "w"；无 write-once 存储。检测存在，阻止不存在 |
| 7 | Historical Evidence 可以被 update | **FACT** | E.7.1 audit 发现 matrix/stats/gate 被重写后逐字节恢复；S7.2 覆盖写 |
| 8 | HOLD candidate 可以被错误标记 Active | **FACT** | 无状态机代码；registry 条目可被任意写为 promoted；Langfuse isActive 人工可改 |
| 9 | REJECTED candidate 可以重新激活 | **FACT** | candidate.json 无终态；registry 重名拒绝只是偶发 guard；直接文件写可绕过；Langfuse 无 REJECTED 概念 |
| 10 | stale PromotionDecision 可用于新 Candidate | **FACT** | 无 decision_id→candidate 绑定消费；无有效期；registry 不读 decision |
| 11 | Candidate lifecycle 状态永不迁移 | **FACT** | capabilityizer 写 state="candidate" 后再无任何更新 |

标注：

```text
FACT       —— 仓库代码/已归档审计直接可见。
INFERENCE  —— 由 FACT 推导，未被仓库代码直接证实。
UNKNOWN    —— 仓库外/服务端行为，本仓库无法看到。
```

---

## 5. Promotion vs Adoption Boundary

```text
Evaluation -> Evidence -> Gate -> Decision -> PROMOTABLE
                                                    |
                                              Adoption Boundary
                                                    |
                                              Registry / Runtime
                                              (PROMOTED / ADOPTED)
```

```text
PROMOTE：Promotion Decision 的决策结果 = “gate 通过，允许进入采用流程”。
PROMOTABLE：Candidate 满足采用前置条件 = “等待 adoption 触发”。
PROMOTED：Registry/Runtime 已实际采用 = “系统已经采用”。
```

三者不是同一个状态：

```text
PROMOTE 只产生 PROMOTABLE，不产生 PROMOTED；
PROMOTED 只能由 adoption transition（PROMOTABLE -> PROMOTED）触发。
```

两者必须分离，因为：

```text
1. Decision 是证据（frozen dataclass / gate JSON），不是写权限；
2. 当前没有任何消费端让 Decision 成为唯一写权限（FACT）；
3. 绕过路径 1/2/3/10 全部发生在 Decision 与 Registry/Runtime 之间。
```

最小边界 = adoption 请求必须重新验证 Decision 绑定，而不是信任
“有人已经把 evaluation.json 写进 candidate 目录”。

---

## 6. 最小 Enforcement Contract

### 6.1 PromotionDecisionContract

PROMOTE decision 必须绑定：

```text
decision_id
candidate_id + candidate_version
evaluation_run（run_id + run 的 policy 绑定）
promotion_policy_version（policy_ref + version）
provenance（evidence refs + hashes + immutable artifact refs）
gate_result == PASS
created_at
```

### 6.2 CandidateAdoptionContract

Registry 写入 / Runtime 采用前必须验证：

```text
decision.status == PROMOTE（离线 snapshot 字段为 value）
candidate_id == decision.candidate_id == run.candidate_id
candidate_version == decision.candidate_version == run.candidate_version
                  == candidate.version
decision 引用的 EvaluationRun 必须存在（run_id 绑定）
policy_version == decision.policy_version == run.policy_version
              == policy.version
decision provenance valid（G1-G4）
decision / evidence 未篡改（G5）
lifecycle.status == PROMOTABLE
lifecycle 中明确存在 PROMOTABLE -> PROMOTED 的 adoption transition
lifecycle 缺失 -> MISSING_LIFECYCLE（禁止“没有 lifecycle 就默认允许”）
decision 不是 stale（该 candidate_version 的最新 PROMOTE decision）
```

任何 mismatch：

```text
ADOPTION_BLOCKED + 具体原因码
```

原因码（离线 validator 实际产出，全部为 ADOPTION_BLOCKED）：

```text
DECISION_MISSING
DECISION_NOT_PROMOTE
GATE_NOT_PASS
CANDIDATE_ID_MISMATCH
CANDIDATE_VERSION_MISMATCH
RUN_MISSING
POLICY_VERSION_MISMATCH
POLICY_NOT_REGISTERED
POLICY_NOT_FROZEN
RUN_POLICY_MISMATCH
PROVENANCE_INCOMPLETE
EVIDENCE_TAMPERED
DECISION_TAMPERED
MISSING_LIFECYCLE
INVALID_ADOPTION_LIFECYCLE
STALE_DECISION
```

PROMOTE、PROMOTABLE、PROMOTED 是三个不同状态（§5）：PROMOTE 是
Decision 的决策结果；PROMOTABLE 是 Candidate 满足采用前置条件；
PROMOTED 是 Runtime / Registry 已实际采用。PROMOTE 不能直接等同于
PROMOTED，adoption 必须是 PROMOTABLE -> PROMOTED transition 的触发。

### 6.3 PolicyBindingContract

```text
policy registered + frozen + content_hash + commit_ref；
run / decision / adoption 三处的 policy version 必须一致；
recorded hash 不可变（G5/G7）。
```

### 6.4 ProvenanceContract

```text
policy provenance（bytes/hash/commit）
evidence manifest
run_ids（含 adoption 引用的 run）
immutable artifact refs
四要素齐全；任一缺失 -> PROVENANCE_INCOMPLETE -> ADOPTION_BLOCKED。
```

---

## 7. Candidate Lifecycle

```text
DRAFT
  -> EVALUATING
  -> EVALUATED
  -> REGRESSION_CHECKED
  -> PROMOTION_REVIEW
  -> PROMOTABLE / HOLD / REJECTED
  -> PROMOTED（仅从 PROMOTABLE，经 adoption boundary）

HOLD -> EVALUATING（必须开新 EvaluationRun）
REJECTED / PROMOTED 为终态
```

PROMOTE decision 只把 Candidate 推进到 PROMOTABLE（证据状态），
不会产生 PROMOTED；PROMOTED 必须由 adoption 触发
PROMOTABLE -> PROMOTED transition。

代码事实：

```text
FACT      状态机只在文档与离线 validator 中存在；
FACT      capabilityizer 后 candidate.json 状态不再迁移；
FACT      pilot registry 的 promoted/rejected 是 registry entry 状态，
          不是 candidate lifecycle 状态。
```

---

## 8. Runtime 的最终责任

Runtime 不负责：

```text
- judging
- evaluation
- regression attribution
- promotion scoring
```

Runtime 的最小责任（governance guard）：

```text
“如果有人给我一个 candidate version 要采用，
 我是否能够验证它已经获得合法 Promotion Decision？”

不能验证 -> ADOPTION_BLOCKED。
```

Runtime 不能因为“文件在 registry 里 / evaluation.json 存在”就放行；
必须独立重新校验 Decision 绑定（§6.2）。当前仓库没有任何 runtime 实现
这个 guard（FACT）。

---

## 9. 最小 Offline Proof

新增：

```text
docs/archaeology/unified-runtime/64-protocol-enforcement-boundary.md
docs/archaeology/unified-runtime/65-phase7.3-enforcement-contract-fix.md
docs/archaeology/unified-runtime/phase7.3/validate_enforcement_contract.py
docs/archaeology/unified-runtime/phase7.3/test_enforcement_contract.py
```

validator 复用 Phase 7.2 的 `validate_protocol_contract.py`（G1-G7、
lifecycle、extension isolation），在其上增加 `adoptions[]` 与
`validate_adoption_contract()`；不连接真实 Runtime。

覆盖矩阵：

| 场景 | 结果（ADOPTION_BLOCKED code） |
| --- | --- |
| valid PROMOTE + PROMOTABLE + transition | allowed（ENFORCEMENT_BOUNDARY_VALID） |
| adoption.candidate_id != decision.candidate_id | CANDIDATE_ID_MISMATCH |
| decision.candidate_id != run.candidate_id | CANDIDATE_ID_MISMATCH |
| decision 引用不存在的 run | RUN_MISSING |
| lifecycle DRAFT / EVALUATING / PROMOTION_REVIEW | INVALID_ADOPTION_LIFECYCLE |
| lifecycle missing | MISSING_LIFECYCLE |
| PROMOTE + 无 PROMOTABLE->PROMOTED transition | INVALID_ADOPTION_LIFECYCLE |
| no policy | POLICY_NOT_REGISTERED |
| unfrozen policy | POLICY_NOT_FROZEN |
| policy mismatch（adoption/decision/run） | POLICY_VERSION_MISMATCH / RUN_POLICY_MISMATCH |
| candidate version mismatch | CANDIDATE_VERSION_MISMATCH |
| incomplete provenance | PROVENANCE_INCOMPLETE |
| HOLD / REJECTED | DECISION_NOT_PROMOTE / INVALID_ADOPTION_LIFECYCLE |
| stale decision | STALE_DECISION |

额外覆盖：GATE_NOT_PASS、DECISION_TAMPERED、EVIDENCE_TAMPERED、
无 adoption = PARTIAL、文档一致性（64 号报告列出全部拦截码）。

验证命令（本阶段实际运行，结果见 §10）：

```text
python3 -m pytest docs/archaeology/unified-runtime/phase7.3 -q
python3 -m py_compile docs/archaeology/unified-runtime/phase7.3/validate_enforcement_contract.py
python3 -m compileall -q docs/archaeology/unified-runtime/phase7.3
```

---

## 10. 验证结果

```text
offline tests           = 26 passed（含 doc consistency）
py_compile              = COMPILE_OK
compileall              = COMPILE_OK
documentation consistency = PASS（test_doc_lists_all_adoption_block_codes）
```

事实等级：

```text
FACT      离线 enforcement contract 可机械检查且本阶段测试通过。
FACT      Evaluation 层存在 policy 冻结强制（E.7 runner BLOCKED）。
FACT      Runtime / Registry 层没有 adoption guard；bypass 1-11 成立。
FACT      G5/G7 只有审计式检测/恢复，没有存储层强制。
UNKNOWN   production enforcement（真实 Runtime 未接入）。
```

---

## 11. Governance Invariants：检查 vs 强制

| Invariant | 当前状态 | 必须成为强制的位置 |
| --- | --- | --- |
| G1 no policy | Evaluation 层强制；adoption 层缺失 | Runtime/Registry 写入前 |
| G2 unfrozen policy | Evaluation 层强制；adoption 层缺失 | Runtime/Registry 写入前 |
| G3 run-policy mismatch | 离线检查；adoption 层缺失 | Runtime/Registry 写入前 |
| G4 incomplete provenance | 离线检查；adoption 层缺失 | Runtime/Registry 写入前 |
| G5 immutable evidence | 仅审计检测/恢复 | 存储层（write-once / append-only） |
| G6 HOLD => new run | 仅离线检查 | adoption 边界（decision 必须引用新 run） |
| G7 no overwrite | 仅审计检测/恢复 | 存储层 |

谁拥有最终否决权：

```text
当前代码事实：registry.promote() 调用者 / Langfuse 人工操作者。
协议目标：AdoptionGuard（Runtime/Registry 写入前的最后一个校验点），
         decision 是唯一授权凭证。
```

Agent Runtime 在最后一道闸门上负责什么：

```text
只验证“candidate version 是否携带合法 Promotion Decision”，
不判断质量、不解释证据、不做归因。
验证失败即 ADOPTION_BLOCKED。
```

---

## 12. UNKNOWN / Open Questions

```text
1. write-once 信任锚点形态（SQLite 约束 / WORM / signed hash chain）
   未实现；G5/G7 要变成“强制”必须落在存储层。
2. Langfuse 人工 label 移动能否被 gate 接管（API 层拦截）未实现。
3. Decision 有效期 / 撤销 / supersede 语义未定义（stale 只按
   “同一 candidate_version 的最新 PROMOTE decision”判断）。
4. pilot registry 只有 version=1 单版本；多版本 adopted-version 指针
   未实现。
5. REJECTED 后重新提案的“新 Candidate 版本从 DRAFT 开始”未落地
   （candidate.json 状态不迁移）。
6. pilot 路径与 E.7 控制面的统一 decision 形态未实现；
   registry.promote 尚未接受 decision 参数。
7. 真实 Agent Runtime（Codex / 其他）是否另有外部保护，本仓库无法看到。
```

---

## 13. 最终判定

```text
ENFORCEMENT_BOUNDARY_PARTIAL
```

理由：

```text
1. 离线 enforcement contract validated（FACT，26 passed）；
   本次修复（65 号报告）只提升 offline enforcement contract 的正确性
   （candidate/decision/run 绑定 + adoption transition 校验），
   不改变本 Gate。
2. Evaluation 层已有 policy 冻结强制（FACT，E.7 runner）；
3. Runtime / Registry 层 adoption guard 未实现（FACT，bypass 1-11）；
4. G5/G7 只有检测/恢复，没有存储层强制（FACT）；
5. production enforcement = UNKNOWN（真实 Runtime 未接入）。
```

STOP：不 commit、不 push、不运行 live provider、不做 E.8、
不做 production promotion、不修改 Phase 6-E / Phase 7 / 7.1 / 7.2
已冻结产物。
