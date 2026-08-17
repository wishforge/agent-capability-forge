# 68 — Production Adoption Guard Feasibility / Boundary（Phase 7.5）

> 阶段：Phase 7.5（Production Adoption Guard 可行性 / 边界；代码考古 +
> 真实调用链分析 + enforcement placement + 最小改造边界 + feasibility
> proof）。
> 基线：67（Phase 7.4.1）、66（Phase 7.4）、65（Phase 7.3.1）、64
> （Phase 7.3）、57（Phase 7）。
> 约束遵守：未修改 E.5–E.7.1、48/51/52/53、Phase 7 / 7.1 / 7.2 / 7.3 /
> 7.4 / 7.4.1 冻结文件；未修改真实 Registry / Runtime / Langfuse；未做
> production rollout；未做 E.8；未 commit / push。
> 本阶段只允许新增：本文件、
> `phase7.5/trace_adoption_path.py`、
> `phase7.5/test_adoption_feasibility.py`。

## 1. Executive Summary

回答 Phase 7.5 的核心问题：

> “Adoption Guard 到底应该接在哪里，谁拥有最终否决权，最小需要改哪些
> 真实代码路径，如何保证人审批后可以全自动采用，同时任何绕过路径都无法
> 进入真实 Runtime？”

```text
真实总电闸：当前没有一个全局总电闸；每条真实路径各有一个权威写点：
  pilot 路径       = registry.promote() 写 state="promoted"
                     （pilot/registry.py:36）
  capability runtime = PluginManager.register()+install()
                     （docs/archaeology/python-cordis/kernel/manager.py:52,65
                      -> capability.py:88 INSTALLING->ACTIVE）
  Langfuse 路径    = label / isActive 指针（人工/API 移动，仓库外）

最终否决权：
  当前 = 每个写点的调用者（harness、register/install 调用者、
         Langfuse 人工操作者）；没有任何代码消费 PromotionDecision。
  目标 = Registry 写前 Guard 是 authoritative state transition 的
         primary veto；Runtime activation 是 final defensive veto；
         Control Plane 只签发 Decision，不是写权限。

人审批一次 -> 自动上线：
  当前没有持久化的 who/when/decision_id/policy_version 记录
  （UNKNOWN）；设计路径为
  人审批 -> PromotionDecision（持久化）-> Registry Guard ->
  Runtime Guard -> 自动 adoption。

Registry / Runtime 各负责什么：
  Registry = PROMOTABLE -> PROMOTED 的唯一权威状态迁移；
  Runtime  = activation 前最后一次 legality verification，
             不做 evaluation / regression / scoring。
```

最小可行性结论（本阶段只做设计，不实现）：

```text
PRODUCTION_BOUNDARY_READY_WITH_UNKNOWN
```

```text
FACT      最小真实接入点与职责边界已经明确：
          pilot registry.promote 是 pilot 路径权威状态迁移；
          PluginManager.install 是 capability runtime 权威 activation；
          Langfuse label 是外部权威 pointer。
FACT      offline Adoption Guard contract 可机械验证（Phase 7.4.1，
          30 项测试；本阶段复用）。
UNKNOWN   production enforcement：
          真实生产 Registry 不存在（pilot registry 明确
          EXPERIMENT_ONLY，pilot/registry.py:1-2）；
          Langfuse 服务端是否允许直接 active prompt 不可见；
          write-once / revocation / break-glass 存储不存在。
```

不是 `PRODUCTION_BOUNDARY_READY`：真实生产 Registry / Runtime /
Langfuse 尚未接入 enforcement，production enforcement 仍 UNKNOWN。
不是 `PRODUCTION_BOUNDARY_PARTIAL`：本阶段不要求实现，要求的是“最小
真实接入点和职责边界已明确”，这一点已达成。
不是 `PRODUCTION_BOUNDARY_INVALID`：所有推荐落点均有真实代码路径支撑，
没有发现“设计对象在当前代码中不存在”的情况。

## 2. Current Real Code Path

### 2.1 Candidate creation（pilot / Capability Forge 切片）

```text
capabilityizer.capabilityize()
  src/forge/capabilityizer.py:54
  :117-118 写 candidate.json {candidate_id, name, state:"candidate"}
  [WRITE；之后没有任何代码更新该状态]
    ↓
validator.validate()
  src/forge/validator.py:69,96
  写 validation.json
  [WRITE]
    ↓
evaluator.evaluate()
  src/forge/evaluator.py:24,55,64,68
  写 evaluation.json {verdict: PASS/FAIL}
  [WRITE；authorization = evaluator 自己，无 decision]
```

### 2.2 Evaluation -> Promotion

```text
第一消费者（E.7 真实强制，FACT）：
  provider_probe.py:1337  _promotion_policy_frozen()
    mutable promotion-policy.json == promotion_policy() 才算 frozen
  provider_probe.py:1541  evaluate_promotion_gate()
    policy_frozen=False -> reject "policy_changed_post_hoc"
  provider_probe.py:1684-1690  _promotion_gate()
    policy 缺失/不一致 -> BLOCKED，不运行
  [AUTHORIZATION；只发生在 evaluation 层，不决定 adoption]

Decision 层（契约存在，无消费端，FACT）：
  docs/archaeology/deepseek-harness/evaluation/promotion.py:230 decide()
  :237 policy_ref 默认 None（policy gate 可 NOT_APPLICABLE）
  :304 decision = PROMOTED（命名冲突：decision 值 ≠ registry 状态）
  [AUTHORIZATION；没有任何代码消费 decision 去写 registry/runtime]
```

### 2.3 Registry

```text
pilot/registry.py:17  promote(family, name, candidate_dir, evaluation,
                              registry_root)
  :36 直接写 state="promoted"，拷贝 artifact
  [WRITE / STATE TRANSITION；authorization = 调用者，当前是 harness]

pilot/registry.py:64  discover(registry_root, family, name)
  :69 只检查 entry["state"] != "promoted"
  [READ；无 decision / provenance / digest 比对]

pilot/harness.py:593-600
  evaluation["verdict"] == "PASS" -> registry.promote(...)
  [AUTHORIZATION；没有 PromotionDecision]
```

### 2.4 Runtime

```text
pilot runtime：
  pilot/harness.py:657   registry.discover(...)
  :712-713               artifact_digest = _dir_digest(artifact_dir)
                         docker_launch(entry["artifact_dir"], ...)
  src/forge/sandbox.py:12 launch() 可挂载任意 host 目录
  [READ / EXECUTE；无 adoption guard]

capability runtime（真实 capability 生命周期）：
  docs/archaeology/python-cordis/kernel/manager.py:52  register()
    [WRITE registry record]
  docs/archaeology/python-cordis/kernel/manager.py:65  install()
    [AUTHORIZATION；无 decision 参数]
  docs/archaeology/python-cordis/kernel/capability.py:76,88
    Capability.install() -> INSTALLING -> ACTIVE
    [STATE TRANSITION；无 adoption guard]

tool runtime（DSH / AgentScope / Codex adapter）：
  docs/archaeology/deepseek-harness/runtime/tool_runtime.py:76
    ToolRuntime.register(registration)   [WRITE tool registry]
  :98 execute(call, ctx)
  :255-258 _approve(): approval is None -> return True
    [AUTHORIZATION；默认放行]
  docs/archaeology/deepseek-harness/runtime/backend/adapters/codex.py:69-74
    接受任意 rollout_path，无 registry / decision 检查
```

### 2.5 External system（Langfuse）

```text
research/control-plane-loop/promote.py:46-55
  POST /api/public/prompts
  labels=["control-plane-candidate"], isActive=False
  [WRITE candidate 注册；不是 production active]

docs/archaeology/control-plane/langfuse/03-improvement-promotion.md:20-26
  label 是唯一部署指针；创建带 label 的新版本会移除旧版本同名 label；
  无 eval gate；rollback = 人工把 label 移回旧版本
  [EXTERNAL STATE TRANSITION；authority = 人工/API 操作者]
```

### 2.6 第二消费者（S7.2 / S7.3）

```text
research/control-plane-loop/gate_calibration.py:524 gate_decide()
  只输出 PASS / FAIL / INCONCLUSIVE
  [无 promotion 写路径；Gate 不触发 promotion]
```

## 3. Authoritative Adoption Point

逐个判断四个候选：

### Candidate A：直接 Registry

```text
FACT   pilot 路径中，registry.promote() 是 state="promoted" 的唯一权威
       写点；discover() 只消费该状态。
结论   对 pilot 路径，Registry 是 authoritative state transition；
       但 pilot registry 是 EXPERIMENT_ONLY，不是生产 Registry。
```

### Candidate B：Control Plane Promotion

```text
FACT   PromotionDecision / gate JSON 只作为证据存在；
       没有任何代码消费 decision 去写 registry / runtime。
结论   Control Plane 不是 adoption point；它是 decision authority。
```

### Candidate C：Runtime activation

```text
FACT   capability runtime 中，PluginManager.register()+install() 才是
       真实 activation；Capability.install() 完成 INSTALLING -> ACTIVE。
       ToolRuntime.register() 是工具可见性的真实写点。
结论   对 capability runtime，总电闸是 register/install，不是 Registry。
```

### Candidate D：External provider activation

```text
FACT   仓库代码只写 isActive=False（research/control-plane-loop/promote.py:55）。
INFERENCE 基于 Langfuse API payload shape，存在直接创建 active prompt /
         移动 label 的路径。
UNKNOWN Langfuse 服务端是否允许、是否有独立 enforcement。
结论    Langfuse label / isActive 是外部 production adoption point。
```

### 结论

```text
当前没有单一全局总电闸。真实仓库内至少有三个权威 adoption/activation
点：pilot registry.promote、PluginManager.install、Langfuse label。
生产 Adoption Guard 必须同时覆盖这些点；否则任何一条路径都可绕过。
```

## 4. Enforcement Options

| 维度 | A：Registry Primary + Runtime Secondary | B：Control Plane Primary + Registry/Runtime Secondary | C：Runtime-only |
| --- | --- | --- | --- |
| 改动点 | registry.promote 写前 guard；runtime activation guard | decision 消费端（写 registry）+ registry/runtime guard | 只改 runtime activation / execute |
| 新增状态 | adoption record、lifecycle、decision binding | 同上 + approval record | runtime 侧 decision 引用（无 registry state） |
| 新增依赖 | durable decision/policy store；artifact digest store | durable decision/policy store；decision consumer | runtime 必须直接访问 decision/policy store |
| 可绕过路径 | 直接改 registry 文件（需 write-once 才闭合）；Langfuse label；未接 guard 的 runtime register/install | 同 A；任何不经 decision consumer 的 registry 直写仍可绕过 | registry 可被写坏/写假 promoted；Langfuse label；未接 guard 的其他 runtime 路径 |
| 一致性风险 | 低：一个权威状态写点 | 中：decision 签发与 registry 写入两段 | 高：registry state 与 runtime 实际采用可能长期不一致 |
| 回滚风险 | 中：改 registry entry + artifact | 中：同 A + decision 消费状态 | 低（runtime 可拒绝），但无法纠正已写坏的 registry |
| 运维复杂度 | 中 | 高 | 最低（单点），但 authority 最弱 |
| 与当前代码契合度 | pilot 路径高（promote 是唯一写点）；capability runtime 中 register/install 是替代 primary | 中（decision 无消费端，需新建） | 低（当前 runtime 不持有完整 decision 图） |

## 5. Recommended Architecture

```text
Control Plane（Decision Authority）
  PromotionDecision = PROMOTE + 全部 binding
        ↓ AdoptionRequest
Registry（Authoritative State Transition / Primary Guard）
  validate_adoption_contract -> Allowed/Blocked
        ↓ PROMOTABLE -> PROMOTED
Runtime（Final Defensive Verification / Secondary Guard）
  activation 前 legality verification -> ADOPTION_BLOCKED 或执行
        ↓
Langfuse / production pointer（外部）
  guarded activation（外部 enforcement UNKNOWN）
```

推荐：

```text
Primary Enforcement   = Registry（pilot 路径）或
                        PluginManager.register/install
                        （capability runtime 路径）
Secondary Defense     = Runtime activation / execute
Decision Authority    = Control Plane（只签发 decision，不拥有写权限）
```

标注：

```text
FACT      该结构继承 Phase 7.4 推荐（66 §11）。
FACT      pilot 路径中 registry.promote 是唯一权威状态写点。
UNKNOWN   生产 Registry 是否存在；capability runtime 是否是目标生产
          runtime；Langfuse 服务端 enforcement。
```

## 6. Registry Primary Guard

最小设计（不实现）：

```text
registry.promote(candidate, decision)
  ↓
validate_adoption_contract(adoption_request)
  ↓
All  -> state = "promoted"（只允许 PROMOTABLE -> PROMOTED）
Any fail -> ADOPTION_BLOCKED + reason code
```

`promote()` 必须接收并验证 AdoptionRequest 的全部字段（§8），而不是只收
`evaluation` dict。`discover()` 只允许返回“能映射到一个通过 Guard 的
AdoptionRequest”的 entry；否则 `PROMOTED_WITHOUT_DECISION` ->
`ADOPTION_BLOCKED`（复用 Phase 7.4 的 state-only trust 禁止规则）。

```text
FACT      当前 promote() 签名没有 decision / policy / provenance
          （pilot/registry.py:17-42）。
FACT      当前 entry 不存 candidate_id / decision_id / policy_version，
          只有 evaluation dict 可追溯。
UNKNOWN   生产 Registry 是否具备原子写 / write-once / CAS。
```

## 7. Runtime Secondary Guard

Runtime 在 activation 前只做 legality verification，不重新做 evaluation /
regression / scoring：

```text
activation 前验证：
  candidate_id
  candidate_version
  decision_id
  policy_version
  artifact_digest（与实际 artifact 计算值一致）
  provenance（policy / evidence_manifest / run_ids /
              immutable_artifact_refs）

任一失败 -> ADOPTION_BLOCKED
```

落点：

```text
pilot runtime       phase_future() 在 docker_launch 前
capability runtime  PluginManager.install() / Capability.install() 前
tool runtime        ToolRuntime.register() / execute() 前
Langfuse            fetch-by-label 后（外部，UNKNOWN）
```

Runtime 不做：

```text
- evaluation
- regression
- scoring
- 重新签发 decision
```

```text
FACT      当前 pilot runtime 在 discover() 后直接 docker_launch
          （pilot/harness.py:657,713）。
FACT      ToolRuntime._approve() 在 approval=None 时默认放行
          （tool_runtime.py:255-258）。
```

## 8. PromotionDecision Contract

复用 Phase 7.4 / 7.4.1 语义，不重新定义：

```text
decision_id
candidate_id + candidate_version（immutable version）
evaluation_run_id（= decision.run_id）
policy_ref + policy_version（registered + frozen）
artifact_digest（decision == run == candidate.forged_artifact_digest）
gate_result == PASS
value == PROMOTE（不是 "PROMOTED"）
created_at（缺失 -> MISSING_DECISION_TIMESTAMP）
recorded_hash / current_hash（篡改 -> DECISION_TAMPERED）
provenance
```

命名冲突必须保留 Phase 7.4 的切断语义：

```text
PROMOTE      = decision 值（授权）
PROMOTABLE   = lifecycle 状态（可被采用）
PROMOTED     = registry / runtime 已采用（系统状态）

decision.value == "PROMOTED" 在 adoption 边界一律视为
DECISION_NOT_PROMOTE（66 §6；Phase 7.4.1 测试覆盖）。
```

```text
FACT      Phase 5-N PromotionDecision dataclass 有 decision_id /
          candidate_ref / regression_ref / created_at /
          authorized_principal / owner_ref（promotion.py:87-101）。
UNKNOWN   生产环境是否有持久化 decision store；字段映射
          （candidate_id / candidate_version / run_id / policy_version /
          artifact_digest）是否可机械消费。
```

## 9. Human Approval → Automatic Adoption Path

### 风险分层

```text
低风险：auto promote / auto adopt
  Decision = PROMOTE -> Registry Guard -> Runtime -> 自动 adoption

中风险：Promotion Gate + human approval
  human approval -> PromotionDecision -> Registry Guard -> Runtime
  -> automatic adoption

高风险：human approval + stronger guard
  human approval -> 额外审批 / 签名 -> Registry Guard -> Runtime
  -> manual break-glass only if policy allows
```

### 当前真实保存了什么

```text
pilot/confirm.json
  {"operator": "rehearsal-runner", "confirm": true, "note": "..."}
  -> 只有 operator 字符串，无时间戳 / policy version / decision id
     （FACT）

PromotionDecision
  authorized_principal / owner_ref / created_at 字段存在，
  但 optional 且没有任何持久化消费端（FACT）

registry entry
  不保存 approved_by / approved_at / decision_id / policy_version
  （FACT）

Langfuse
  label 移动是人工/API 操作；服务端 audit 是否存在 = UNKNOWN
```

结论：

```text
“谁批准、何时批准、绑定哪个 candidate/version/policy/decision”的持久化
记录当前不存在 -> UNKNOWN。生产落地前必须新增 approval + decision 存储，
不能假设 confirm.json 或 PromotionDecision 对象够用。
```

设计路径（不实现）：

```text
human approval event:
  approved_by, approved_at, scope, expiry, reason
        ↓
PromotionDecision（持久化）:
  decision_id, candidate_id, candidate_version, run_id,
  policy_version, artifact_digest, approved_by, approved_at
        ↓
Registry Guard（自动）:
  validate_adoption_contract -> state = promoted
        ↓
Runtime Guard（自动）:
  legality verification -> activation
```

## 10. TOCTOU / Consistency

当前真实竞态：

```text
pilot:
  discover() 读 entry（check）
  -> 之后 docker_launch(entry["artifact_dir"])（use）
  registry JSON 和 artifact 目录在两步之间可被修改；
  无 CAS / version check / immutable ref（FACT）。

capability runtime:
  register() / install() 是 in-memory 状态；
  无持久化，无 decision 检查；并发 install/unload 由 task 去重，
  但不解决“检查后状态被改”的 adoption 竞态（FACT）。

Langfuse:
  guard 检查通过后，label / isActive 可能被外部移动（UNKNOWN）。
```

最小事务性设计（不实现数据库锁）：

```text
Registry：原子 CAS / 单文件原子替换
  写 entry 前断言当前 state == PROMOTABLE 且 expected decision binding
  未变；写后 entry 只允许追加 adoption record。

Artifact：immutable content-addressed ref
  artifact 必须以 digest 寻址；guard 验证 digest 等于 decision/run/
  candidate digest；runtime 在执行前重新计算 digest。

Decision / revocation：append-only
  decision 与 revocation 只追加，不原地改；runtime activation 时
  在同一读取快照内检查 decision + revocation + policy frozen。
```

```text
FACT      上述竞态在现有代码中真实存在（discover -> docker_launch；
          register -> install）。
UNKNOWN   生产存储是否支持 CAS / write-once；本阶段不实现。
```

## 11. Failure-Closed

任何以下情况默认 `ADOPTION_BLOCKED`：

```text
missing decision            MISSING_DECISION
decision != PROMOTE         DECISION_NOT_PROMOTE
candidate id mismatch       CANDIDATE_ID_MISMATCH
candidate version mismatch  CANDIDATE_VERSION_MISMATCH
run missing                 RUN_MISSING
run mismatch                RUN_MISMATCH
policy unregistered         POLICY_NOT_REGISTERED
policy not frozen           POLICY_NOT_FROZEN
run-policy mismatch         RUN_POLICY_MISMATCH
artifact digest mismatch    ARTIFACT_DIGEST_MISMATCH
provenance incomplete       PROVENANCE_INCOMPLETE
invalid lifecycle           MISSING_LIFECYCLE / INVALID_LIFECYCLE
candidate rejected          CANDIDATE_REJECTED
stale decision              STALE_DECISION
missing timestamp           MISSING_DECISION_TIMESTAMP
revoked                     REVOKED_DECISION（存储不存在，UNKNOWN）
tampered                    DECISION_TAMPERED / EVIDENCE_TAMPERED
```

禁止：

```text
fallback latest
fallback previous
fallback last known good
fallback active
fallback manual
```

除明确经过 policy 批准的 break-glass（§12）外，任何 unknown / missing /
inconsistent 都不得放行。

## 12. Break-glass

如果 Adoption Guard 自身故障，禁止自动绕过。最小 break-glass 设计：

```text
- explicit human identity
- reason
- expiry（自动过期）
- scope（candidate_id + version + run + policy 限定）
- audit event（全量记录）
- automatic expiration（过期后立即失效）
```

当前仓库支持度：

```text
FACT      pilot/confirm.json 只有 operator 字符串，
          无 expiry / scope / reason / audit event。
UNKNOWN   是否存在 break-glass 审批存储 / API / 自动过期机制。
```

结论：break-glass 需要新建，不能复用现有 confirm.json。

## 13. Bypass Closure

| # | 绕过路径 | 状态 | 由谁闭合 |
| --- | --- | --- | --- |
| B1 | `registry.promote()` 接受任意 evaluation，直接写 promoted | FACT | Registry Primary Guard + write-once registry（storage UNKNOWN） |
| B2 | `PluginManager.register()+install()` 无 decision 直接 ACTIVE | FACT | Runtime install Guard（register/install 前验证） |
| B3 | `ToolRuntime.register()` 任意 fn；approval=None 默认放行 | FACT | ToolRuntime.register/execute Guard + fail-closed approval |
| B4 | candidate/evaluation JSON 直接覆盖写 | FACT | write-once provenance store + immutable artifact refs（UNKNOWN） |
| B5 | Langfuse 直接移动 label / isActive | FACT/UNKNOWN | guarded Langfuse activation API 或 fetch 后 runtime 验证（外部 UNKNOWN） |
| B6 | `docker_launch` 直接跑任意目录 | FACT | runtime 在执行前验证 artifact_digest 与 AdoptionRequest |
| B7 | Gate 只输出 verdict，无 promotion 写路径 | FACT | decision consumer：Gate -> PromotionDecision -> Registry Guard |
| B8 | `decide()` 无 policy 也能产出 PROMOTED，且无消费端 | FACT | PromotionDecision 强制 policy_ref + durable decision store |

残余绕过（本阶段无法闭合）：

```text
- 直接编辑磁盘上的 registry / candidate / artifact（需要 write-once
  存储；UNKNOWN）
- Langfuse 服务端直写 active prompt（UNKNOWN）
- 任何不经 guarded API 的新 runtime 入口（UNKNOWN）
```

## 14. Minimal Implementation Boundary

未来落地时需要改动的真实位置（本阶段未改）：

```text
pilot/registry.py
  promote() 增加 AdoptionRequest + validate_adoption_contract；
  discover() 只返回有合法 adoption binding 的 entry。

pilot/harness.py:593-600
  调用 promote() 时携带 PromotionDecision / AdoptionRequest。

docs/archaeology/python-cordis/kernel/manager.py:52,65
  register() / install() 增加 adoption legality verification。

docs/archaeology/python-cordis/kernel/capability.py:76
  Capability.install() 在 INSTALLING -> ACTIVE 前验证。

docs/archaeology/deepseek-harness/runtime/tool_runtime.py:76,98,255
  register() / execute() 增加 guard；approval=None 必须 fail closed。

decision / policy / revocation 存储
  新增（当前不存在；UNKNOWN）。

Langfuse 集成
  label / isActive 写路径的 guarded wrapper（外部）。
```

本阶段新增：

```text
docs/archaeology/unified-runtime/68-production-adoption-guard-feasibility.md
docs/archaeology/unified-runtime/phase7.5/trace_adoption_path.py
docs/archaeology/unified-runtime/phase7.5/test_adoption_feasibility.py
```

本阶段未动：

```text
E.5-E.7.1
Phase 7 / 7.1 / 7.2 / 7.3 / 7.4 / 7.4.1
codex/ control-plane/ openhands/
48* 51* 52* 53*
真实 Registry / Runtime / Langfuse
```

## 15. FACT / INFERENCE / UNKNOWN

```text
FACT
  - pilot/registry.py:17-42 promote() 无 decision 参数，直接写 promoted。
  - pilot/registry.py:64-71 discover() 只检查 state=="promoted"。
  - pilot/harness.py:593-600 只凭 evaluation verdict 调 promote。
  - pilot/harness.py:657,713 discover -> docker_launch(artifact_dir)。
  - capability manager register/install 无 adoption guard
    （manager.py:52,65；capability.py:76,88）。
  - ToolRuntime.register 无 adoption guard；approval=None 默认放行
    （tool_runtime.py:76,255-258）。
  - promotion.decide() 无消费端；policy_ref 可选；decision 值 PROMOTED
    与系统状态同名（promotion.py:237,304）。
  - control-plane promote.py:55 只写 isActive=False。
  - Langfuse label 是唯一部署指针，无 eval gate
    （langfuse/03-improvement-promotion.md:20-26）。
  - gate_calibration.py:524 gate_decide() 只输出 verdict。
  - pilot/confirm.json 只有 operator 字符串。
  - Phase 7.4 / 7.4.1 offline contract 30 项测试通过。

INFERENCE
  - PluginManager.install() 是 capability runtime 的权威 activation 点。
  - ToolRuntime.register() 是工具可见性的权威写点。
  - 推荐架构（Registry Primary + Runtime Secondary）能闭合 B1/B2/B3/B6
    （在对应路径接入 guard 的前提下）。
  - Langfuse 可能存在直接 active prompt 的 API 路径。

UNKNOWN
  - 生产 Registry 是否存在 / 是否 write-once / 是否支持 CAS。
  - 哪个 runtime 是目标生产 runtime（pilot / capability runtime /
    Langfuse）。
  - PromotionDecision 的持久化与字段映射。
  - revocation / break-glass 存储。
  - Langfuse 服务端 enforcement。
```

## 16. Open Questions

```text
1. 生产 Registry 是哪个？当前 pilot registry 明确 EXPERIMENT_ONLY。
2. 目标生产 Runtime 是 pilot slice、capability manager，还是 Langfuse
   prompt 消费侧？
3. PromotionDecision 由谁签发、谁持久化、如何保证 authorized_principal
   真实？
4. Langfuse 服务端是否允许 / 记录直接 active prompt 创建？
5. write-once provenance 存储是否可落地？
6. revocation 存储与 supersession 语义由谁实现？
7. break-glass 审批存储 / 自动过期是否存在？
```

## Feasibility Proof

```text
python3 docs/archaeology/unified-runtime/phase7.5/trace_adoption_path.py
  -> 19 项静态代码事实全部 OK
  -> PRODUCTION_BOUNDARY_READY_WITH_UNKNOWN

pytest docs/archaeology/unified-runtime/phase7.5 -q
  -> 5 passed

pytest docs/archaeology/unified-runtime/phase7.4 -q
  -> 30 passed（未修改，回归确认）
```

proof 内容：

```text
- 真实调用链静态验证（pilot / control plane / capability runtime）
- decision consumer 搜索（无 caller 向 promote 传 decision）
- adoption point 验证（5 个真实点）
- bypass path inventory（B1-B8）
- minimal contract validation（15 个 blocked reason 复用 Phase 7.4
  validator，全部 ADOPTION_BLOCKED）
```

## Final Verdict

```text
PRODUCTION_BOUNDARY_READY_WITH_UNKNOWN
```

```text
真正的 Adoption 总电闸在哪里？
  pilot 路径：registry.promote()（state="promoted" 写点）。
  capability runtime：PluginManager.register()+install()。
  Langfuse：label / isActive 指针。
  当前没有跨路径的单一总电闸。

谁拥有最终否决权？
  当前：每个写点的调用者。
  目标：Registry Guard（primary state transition veto）
        + Runtime Guard（final activation veto）。
  Control Plane 只有 decision authority，没有写权限。

人审批一次之后，后面的自动上线怎么走？
  人审批 -> 持久化 PromotionDecision -> Registry Guard 自动验证 ->
  Runtime Guard 自动验证 -> 自动 adoption。
  当前缺 who/when/decision/policy 的持久化记录（UNKNOWN）。

Registry 和 Runtime 各负责什么？
  Registry：PROMOTABLE -> PROMOTED 的唯一权威状态迁移。
  Runtime：activation 前 legality verification（decision / binding /
           digest / provenance），不做 evaluation。

还有哪些地方可能绕过？
  B1-B8 全部仍可绕过；其中 B4/B5 需要 write-once 存储与 Langfuse
  外部 enforcement（UNKNOWN）才能闭合。
```

STOP：

```text
未实现 production AdoptionGuard。
未修改真实 Registry / Runtime / Langfuse。
未做 E.8。
未 commit / push。
```
