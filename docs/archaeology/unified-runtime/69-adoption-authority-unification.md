# 69 — Adoption Authority Unification（Phase 7.6）

> 阶段：Phase 7.6（Adoption Path 统一建模 / Authority 设计 / 绕过路径
> 收敛 / 最小统一契约；代码考古 + 设计，不实现 production Guard）。
> 基线：68（Phase 7.5，PRODUCTION_BOUNDARY_READY_WITH_UNKNOWN）、67
> （Phase 7.4.1）、66（Phase 7.4）、65（Phase 7.3.1）、64（Phase 7.3）、
> 57（Phase 7）。
> 约束遵守：未修改 E.5–E.7.1、48/51/52/53、Phase 7 / 7.1 / 7.2 / 7.3 /
> 7.4 / 7.4.1 / 7.5 冻结文件；未修改真实 Registry / Runtime / Langfuse；
> 未实现 production AdoptionGuard；未做 E.8；未做 production rollout；
> 未连接 live provider；未 commit / push。
> 本阶段只允许新增：本文件、`phase7.6/inventory_adoption_paths.py`、
> `phase7.6/validate_adoption_authority.py`、
> `phase7.6/test_adoption_authority.py`。

## 1. Executive Summary

回答本阶段核心问题：

> 一个 Agent 存在 3 条上线路径时，是否可能出现 Registry 不允许、Runtime
> 允许、Langfuse 允许？

**可以。** 这是当前代码的事实（FACT）：

```text
registry.promote() 写 state="promoted"（pilot/registry.py:36）
  -> 不读任何 decision
PluginManager.install() 完成 INSTALLING -> ACTIVE
  （docs/archaeology/python-cordis/kernel/capability.py:88）
  -> 不读 registry，也不读 decision
Langfuse label / isActive 指针（人工/API 移动）
  -> 不读 registry / runtime / decision
```

三条路径各自独立、互不消费对方状态，也没有任何代码消费
PromotionDecision。因此三种状态可以同时不一致：Registry BLOCK、Runtime
ALLOW、Langfuse ALLOW 完全可能。当前“谁拥有采用能力”= 每个写点的调用者
（harness、register/install 调用者、Langfuse 人工操作者）。

本阶段结论：

```text
ADOPTION_AUTHORITY_VALID_WITH_UNKNOWN
```

```text
FACT      exhaustive adoption path inventory 完成：21 条真实路径，其中
          8 条 ADOPTION、8 条 PREPARATION、4 条 METADATA、1 条
          NON_ADOPTION。
FACT      offline unified authority contract 可机械验证（17 项测试通过）。
UNKNOWN   production authority enforcement：真实 Registry / Runtime /
          Langfuse 未接入；decision/revocation 持久化不存在；Langfuse
          服务端 enforcement 不可见。
```

推荐 authority 一句话：

```text
AdoptionAuthority = 绑定
  candidate_id + candidate_version + promotion_decision_id +
  evaluation_run_id + policy_version + artifact_digest + provenance
  的统一可验证凭证；Registry / Runtime / External 各自用同一 authority
  做 fail-closed 验证；任何 mismatch 或任何系统 BLOCK -> ADOPTION_BLOCKED。
```

## 2. Adoption Path Inventory

考古范围：`pilot/`、`src/forge/`、`research/control-plane-loop/`、
`docs/archaeology/python-cordis/`、`docs/archaeology/deepseek-harness/`、
`docs/archaeology/control-plane/langfuse/` 的全部写点与选择点，覆盖：

```text
active / promoted / installed / enabled / registered / selected /
loaded / activated / adopted / default version / current version /
pointer swap
```

完整机器清单见 `phase7.6/inventory_adoption_paths.py`（21 条），下表为
摘要。

| path_id | system | entrypoint（写操作） | state mutated | 实际效果 | 当前授权 | bypass | 分类 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P-REG-01 | pilot registry | `registry.promote()` pilot/registry.py:17,36 | entry.state=promoted + artifact copy | capability 可被 B3 采用 | harness（verdict PASS + confirm.json） | HIGH | ADOPTION |
| P-RT-01 | pilot runtime | `phase_future(b3)` harness.py:656-713 discover→docker_launch | run record treatment | capability 实际运行 | state==promoted | HIGH | ADOPTION |
| P-RT-02 | capability runtime | `PluginManager.register()` manager.py:52 | in-memory record REGISTERED | 描述符可见 | caller | MEDIUM | PREPARATION |
| P-RT-03 | capability runtime | `PluginManager.install()` manager.py:65 + capability.py:88 | INSTALLING→ACTIVE | 实例可调用 | caller | HIGH | ADOPTION |
| P-RT-04 | tool runtime | `ToolRuntime.register()` tool_runtime.py:76 | tool registry | 工具可调用 | caller | MEDIUM | PREPARATION |
| P-RT-05 | tool runtime | `ToolRuntime.execute()` tool_runtime.py:98,255-258 | session event log | 工具调用实际执行 | approval=None → allow | HIGH | ADOPTION |
| P-RT-06 | agentscope adapter | `register_tool/register_service` agentscope.py:30,95 | AgentScope registry | 工具/服务可见 | caller | MEDIUM | PREPARATION |
| P-RT-07 | deepseek runtime | `CodexAdapter(rollout_path)` codex.py:69-74 | session stream | 从任意 rollout 开始工作 | caller | HIGH | ADOPTION |
| P-EXT-01 | Langfuse | `promote.py:46-55` POST isActive=False | external prompt 候选 | 生产指针不变 | LANGFUSE_* 凭据 | LOW | PREPARATION |
| P-EXT-02 | Langfuse | label / isActive 指针移动（人工/API） | external production pointer | 生产 prompt 切换 | 人工/API 操作者 | HIGH | ADOPTION |
| P-CFG-01 | pilot pointer | `phase_b3_build` harness.py:601 写 b3_entry.json | b3_entry.json | 选择 registry entry | 同 promote caller | MEDIUM | METADATA |
| P-CFG-02 | pilot pointer | `phase_b2_freeze` harness.py:545 写 skill_ref.json | skill_ref.json + frozen 副本 | B2 未来任务使用该 skill | freeze caller | HIGH | ADOPTION |
| P-CFG-03 | pilot pointer | `phase_b1_freeze` harness.py:634 写 b1_skill_ref.json | b1_skill_ref.json + frozen 副本 | B1 未来任务使用该 skill | b1_curated_skill.json | HIGH | ADOPTION |
| P-CFG-04 | pilot config | 冻结 skill 副本写入 | frozen 文件 | 仅字节可用，无选择 | freeze caller | LOW | PREPARATION |
| P-CFG-05 | pilot config | `confirm.json` 读取 harness.py:560 | 无 | 当前“人审批”记录 | 手工编辑 | HIGH | METADATA |
| P-CFG-06 | pilot candidate | capabilityizer.py:117 / validator.py:96 / evaluator.py:68 | candidate/validation/evaluation.json | 候选+证据存在 | pipeline | MEDIUM | PREPARATION |
| P-CFG-07 | control plane | provider_probe.py:1337,1541,1684 + promotion-policy.json | policy/gate evidence | evaluation 层授权 | E.7 frozen policy | LOW | PREPARATION |
| P-CFG-08 | second consumer | `gate_decide()` gate_calibration.py:524 | verdict JSON | 无 adoption 写路径 | gate 逻辑 | NONE | METADATA |
| P-CFG-09 | control plane | `decide()` promotion.py:230 | in-memory PromotionDecision | 决策记录，无消费端 | decide() gates | HIGH | METADATA |
| P-CFG-10 | bundle store | bundle_producer.py:440-455 Rule 13 | sealed bundle | 候选锻造输入；禁止 adoption state | bundle producer | LOW | PREPARATION |
| P-CFG-11 | env/config | pilot/config.json、LANGFUSE_*、CODEX_HOME | 无 | 进程配置，无 pointer 语义 | operator | NONE | NON_ADOPTION |

判定：

```text
ADOPTION（真正让 Agent 开始干活）      = 8 条
PREPARATION（上传/注册/缓存/证据）     = 8 条
METADATA（只记录信息）                 = 4 条
NON_ADOPTION（环境/配置）              = 1 条
```

## 3. Adoption vs Preparation vs Metadata

三条判据：

```text
Adoption Path   = 写操作后，Agent 会以该对象开始工作
Preparation     = 只上传 / 注册 / 缓存 / 产生证据，不产生采用效果
Metadata        = 只记录信息或派生指针，不独立产生采用效果
```

关键区分（不做“register == adopt”）：

```text
PluginManager.register()                 = PREPARATION
PluginManager.install() -> ACTIVE        = ADOPTION
ToolRuntime.register()                   = PREPARATION
ToolRuntime.execute()                    = ADOPTION
Langfuse POST isActive=False             = PREPARATION
Langfuse label/isActive 移动到生产指针   = ADOPTION
registry.promote()                       = ADOPTION（状态迁移）
b3_entry.json / skill_ref.json           = METADATA 指针 / ADOPTION 指针
```

`b3_entry.json` 单独只是派生指针（METADATA），但它与 `discover` +
`docker_launch` 构成 P-RT-01 的采用链；`skill_ref.json` /
`b1_skill_ref.json` 直接决定未来 Codex 运行使用哪个 skill，因此归类
ADOPTION。

## 4. Current Authority Sources

当前真实 authority（全部是“写点调用者”，不是统一 authority）：

```text
pilot 路径：
  registry.promote() 的调用者（pilot/harness.py:600）
  -> 只凭 evaluation["verdict"] == "PASS" + confirm.json
capability runtime：
  PluginManager.register()+install() 的调用者
  -> 无 decision / policy / digest 参数
tool runtime：
  ToolRuntime.register() 的调用者；approval=None 默认放行
deepseek runtime：
  CodexAdapter 调用者传入任意 rollout_path
Langfuse：
  人工/API 操作者移动 label / isActive
控制面：
  decide() 产出 PromotionDecision，但没有任何消费端
```

结论（FACT）：

```text
当前没有一个写点验证统一 authority；
PromotionDecision 不能约束任何真实 Adoption Path；
因此“Registry 不允许但 Runtime/Langfuse 允许”不仅可能，且是当前默认
行为——runtime 和 Langfuse 根本不知道 registry 说了什么。
```

## 5. Authority Options

| 候选 | 可验证性 | 不可伪造性 | 生命周期 | 撤销 | 跨系统能力 | 与现有代码契合度 |
| --- | --- | --- | --- | --- | --- | --- |
| A. PromotionDecision | 字段可离线验证（FACT） | 生产 UNKNOWN（无持久化/签名） | created_at + stale 规则存在 | 无存储，UNKNOWN | 无消费端，需新建传递 | 高（字段已在 promotion.py:87-101） |
| B. Registry state | 只查 state==promoted | 低（flat JSON 可覆盖） | 无多版本/无 revoke | 无 | 只覆盖 pilot 路径 | pilot 高；runtime/Langfuse 不可见 |
| C. Signed AdoptionToken | 需新建验签基础设施 | 依赖签名信任锚，仓库无 | 需新建 | 需新建 | 强但需全链路改造 | 低（无签名代码） |
| D. CandidateVersion + Decision tuple | 可验证 | 同 A | 同 A | 同 A | 需作为整体传递 | 高 |
| E. AdoptionAuthority（binding 投影） | 可验证 | 同 A（依赖底层记录完整性） | issued_at=decision.created_at；expires_at 当前 UNKNOWN | revocation_reference 当前 UNKNOWN | 同一 contract 在每个边界重验 | 最高：全部字段已存在于现有记录 |

比较结论：

```text
A 和 D 是成分，不是完整凭证；B 是单路径状态，无法跨系统；
C 需要仓库中不存在的签名/信任锚（当前无），本阶段不选。
推荐 E：AdoptionAuthority 不是新存储，而是把已有 decision / run /
policy / candidate / digest / provenance 统一成一份可机械验证的 binding，
每个系统用同一 contract 重验。
```

## 6. Recommended Adoption Authority

```text
ADOPTION_AUTHORITY_RECOMMENDED = AdoptionAuthority（binding 投影）
```

```text
FACT       全部最小字段在现有代码/离线快照中存在：
           candidate_id / candidate_version / promotion_decision_id
           （Phase 7.4 decision_id）/ evaluation_run_id（run_id）/
           policy_version / artifact_digest（Phase 7.4.1）/
           provenance（Phase 7.2-7.4）。
INFERENCE  AdoptionAuthority 作为统一凭证能被 Registry / Runtime /
           External 共同验证（设计判断，从 FACT 推导）。
UNKNOWN    生产持久化 / 签名 / revocation / expiry 支持。
```

最小语义：

```text
authority_id
candidate_id
candidate_version
promotion_decision_id
evaluation_run_id
policy_version
artifact_digest
provenance            {policy, evidence_manifest, run_ids,
                        immutable_artifact_refs}
issued_at             = decision.created_at（存在时校验一致）
expires_at            当前仓库无 TTL 语义 -> UNKNOWN，不默认存在
revocation_reference  当前仓库无 revocation 存储 -> UNKNOWN，
                       存在时必须解析到 revocations[]，否则 BLOCK
```

不是：

```text
不是 registry state
不是 signed token（无签名基础设施）
不是 candidate 本身
不是 evaluation verdict
```

## 7. Authority Binding

每条 AdoptionPath 必须最终绑定同一组身份：

```text
candidate_id          authority == decision == run
candidate_version     authority == decision == run == candidate.version
promotion_decision_id authority -> decision（必须存在且 value==PROMOTE）
evaluation_run_id     authority == decision.run_id
policy_version        authority == decision == run == policy.version
artifact_digest       authority == decision == run ==
                      candidate.forged_artifact_digest
provenance            authority 携带四要素，run_id 必须在 run_ids 内
```

任意 mismatch：

```text
ADOPTION_BLOCKED
```

离线 validator（`validate_adoption_authority.py`）覆盖全部 binding，并
额外覆盖：`DECISION_NOT_PROMOTE`（decision.value == "PROMOTED" 视为
NOT_PROMOTE）、`GATE_NOT_PASS`、`RUN_MISSING / RUN_MISMATCH`、
`POLICY_NOT_REGISTERED / POLICY_NOT_FROZEN / RUN_POLICY_MISMATCH`、
`PROVENANCE_INCOMPLETE`、`DECISION_TAMPERED / EVIDENCE_TAMPERED`、
`MISSING_LIFECYCLE / INVALID_LIFECYCLE / CANDIDATE_REJECTED`、
`REVOKED_DECISION`、`STALE_DECISION`、`MISSING_DECISION_TIMESTAMP`、
`PROMOTED_WITHOUT_DECISION`、`AUTHORITY_ISSUED_AT_MISMATCH`。

## 8. Cross-System Validation

每个系统用同一个 AdoptionAuthority 在自己边界重验，不做 distributed
transaction / distributed lock / event bus：

```text
Registry（primary state transition）
  validate authority against pre-state（lifecycle == PROMOTABLE）
  -> PROMOTABLE -> PROMOTED，entry 记录 authority binding

Runtime（final defensive verification）
  validate same authority against post-state（lifecycle == PROMOTED，
  且 registry_promoted 存在匹配的 decision 记录）
  -> 激活前重算 artifact_digest

External（Langfuse）
  只能通过同一 authority 的 guarded wrapper 移动 label / isActive；
  服务端 enforcement 不可见 -> 明确标记 EXTERNAL_UNCONTROLLABLE
```

一致性协议（最小）：

```text
同一 authority_id + 同一组 binding 字段
+ decision.created_at（issued_at）
+ artifact_digest 在激活时重新计算
+ revocation_reference / revocations[] 在同一读取快照内检查
任何系统本地缓存都必须保留 authority_id 并在激活/迁移前重新验证；
stale cache 等价于缺失验证 -> BLOCK。
```

当前仓库一致性事实（FACT）：

```text
pilot：discover() 读取与 docker_launch() 使用之间存在 TOCTOU，
      无 CAS / version check（harness.py:657,713）。
capability runtime：register/install 是 in-memory 状态，无持久化
      （manager.py）。
Langfuse：guard 检查后 label 仍可能被外部移动（UNKNOWN）。
```

## 9. Conflict Resolution

所有组合 fail closed：

```text
Registry ALLOW + Runtime BLOCK        -> BLOCK
Registry BLOCK + Runtime ALLOW        -> BLOCK
External ALLOW + Registry BLOCK       -> BLOCK
任何系统 UNKNOWN / 缺失 verdict        -> BLOCK
```

禁止：

```text
latest fallback
previous fallback
last known good fallback
legacy state trust（“state=promoted 就算数”）
manual active fallback
```

离线验证器用 `SYSTEM_<SYSTEM>_BLOCKED` / `SYSTEM_<SYSTEM>_UNKNOWN` /
`FALLBACK_NOT_AUTHORITY` 把这些规则变成机器可检查的 ADOPTION_BLOCKED
reason（Phase 7.6 测试覆盖）。

## 10. Human Approval → Automatic Adoption

目标路径：

```text
Candidate
  -> Evaluation（evidence）
  -> Promotion Gate（policy frozen + PASS）
  -> Human Approval（只在“是否授权采用”发生）
  -> PromotionDecision（持久化）
  -> AdoptionAuthority（统一凭证）
  -> Registry Guard（自动验证 + state transition）
  -> Runtime Guard（自动验证 + activation）
  -> External guarded pointer（自动验证，或明确外部不可控）
```

人审批之后，Registry / Runtime / External 全部自动验证同一 authority；
人不再手工修改 `state` / `active` / version pointer。

当前支持度：

```text
FACT   pilot/confirm.json 只有 operator 字符串，无 approved_at /
       policy_version / decision_id（pilot/confirm.json）。
FACT   PromotionDecision 有 authorized_principal / owner_ref /
       created_at 字段，但 optional 且无持久化消费端
       （promotion.py:87-101）。
FACT   registry entry 不保存 approved_by / approved_at / decision_id /
       policy_version（pilot/registry.py:28-41）。
UNKNOWN 持久化 approval + decision store 是否存在（当前不存在）。
```

结论：不能把 confirm.json 或 in-memory PromotionDecision 当作生产审批
记录；落地前必须新增 durable approval/decision 存储。

## 11. Break-glass

只做统一模型，不实现：

```text
BreakGlassAuthority
  explicit identity
  reason
  scope（candidate_id + version + run + policy 限定）
  expiry（自动过期）
  audit trail（全量记录）
```

Break-glass 不是“绕开 Guard 直接改状态”；它本身必须经过 policy 批准的
例外通道，并且同样落入 AdoptionAuthority binding（decision 记录 +
break-glass 授权）。

当前仓库支持度：

```text
FACT    pilot/confirm.json 只有 operator，无 expiry / scope / reason /
        audit event。
UNKNOWN 是否存在 break-glass 审批存储 / API / 自动过期机制。
```

结论：break-glass 需要新建；在仓库没有能力前保持 UNKNOWN，不实现。

## 12. Bypass Closure

| # | 绕过路径 | 状态 | 由谁闭合 |
| --- | --- | --- | --- |
| B1 | `registry.promote()` 接受任意 evaluation 直接写 promoted | FACT | Registry Guard：promote 必须验证 AdoptionAuthority + 记录 binding；write-once storage UNKNOWN |
| B2 | `PluginManager.register()+install()` 无 decision 直接 ACTIVE | FACT | Runtime install Guard：INSTALLING->ACTIVE 前验证同一 authority |
| B3 | `ToolRuntime.register()` 任意 fn；approval=None 默认放行 | FACT | register/execute Guard + approval=None fail closed |
| B4 | candidate/validation/evaluation JSON 直接覆盖写 | FACT | write-once provenance store + immutable artifact refs（UNKNOWN） |
| B5 | Langfuse 直接移动 label / isActive | FACT/UNKNOWN | guarded external activation wrapper，或标记 EXTERNAL_UNCONTROLLABLE（服务端 UNKNOWN） |
| B6 | `docker_launch` 直接跑任意目录 | FACT | runtime 激活前重算 artifact_digest + 验证 authority |
| B7 | `CodexAdapter(rollout_path)` 接受任意 replay | FACT | rollout selection 必须带已验证 authority 或明确非生产 replay |
| B8 | `skill_ref.json` / `b1_skill_ref.json` 指针直接编辑 | FACT | 指针写必须绑定同一 authority contract 或明确 experiment-only |
| B9 | `decide()` 无 policy 也能产出 decision，且无消费端 | FACT | PromotionDecision 强制 policy_ref + durable store + authority consumer |
| B10 | Gate 只输出 verdict，无 promotion 写路径 | FACT | decision consumer：Gate -> PromotionDecision -> Registry Guard |

残余绕过（本阶段无法闭合，UNKNOWN）：

```text
- 直接编辑磁盘上的 registry / candidate / artifact（需 write-once 存储）
- Langfuse 服务端直写 active prompt（外部 enforcement 不可见）
- 任何不经 guarded API 的新 runtime 入口
```

## 13. FACT / INFERENCE / UNKNOWN

```text
FACT
  - 21 条 adoption-ish 路径全部被考古并分类（inventory 脚本自动校验）。
  - registry.promote() 无 decision 参数，直接写 state="promoted"
    （pilot/registry.py:17,36）。
  - discover() 只检查 state=="promoted"（pilot/registry.py:64-71）。
  - harness 只凭 evaluation verdict + confirm.json 调 promote
    （pilot/harness.py:560,593-601）。
  - phase_future(b3) discover -> docker_launch，无 digest/decision 验证
    （pilot/harness.py:656-713）。
  - PluginManager.register/install 无 adoption guard
    （manager.py:52,65；capability.py:88）。
  - ToolRuntime.register 无 guard；approval=None 默认放行
    （tool_runtime.py:76,255-258）。
  - CodexAdapter 接受任意 rollout_path（codex.py:69-74）。
  - skill_ref.json / b1_skill_ref.json / b3_entry.json 是真实选择指针
    （harness.py:545,601,634,648-659）。
  - promote.py 只写 isActive=False（research/control-plane-loop/promote.py:55）。
  - Langfuse label 是唯一部署指针，无 eval gate
    （langfuse/03-improvement-promotion.md:20-26）。
  - decide() 无消费端；policy_ref 可选；decision 值 PROMOTED 与系统状态
    同名（promotion.py:237,304）。
  - bundle Rule 13 禁止 bundle 内出现 promotion/capability state
    （bundle_producer.py:440-455）。
  - offline unified authority contract 17 项测试全部通过。

INFERENCE
  - 推荐 AdoptionAuthority（binding 投影）能闭合 B1/B2/B3/B5/B6/B7/B8/B9
    （在对应路径接入 guard 的前提下）。
  - Registry 是 state transition 的 primary authority；Runtime 是 final
    defensive veto；External 必须受同一 authority 约束或明确不可控。
  - Langfuse API 可能存在直接 active prompt 路径（payload shape 推导）。

UNKNOWN
  - production authority enforcement（真实 Registry / Runtime /
    Langfuse 未接入）。
  - decision / approval / revocation 持久化存储。
  - write-once / CAS 存储能力。
  - Langfuse 服务端 enforcement。
  - expires_at / TTL 语义（当前仓库没有，不默认存在）。
  - 真实 Agent Runtime 是否另有外部保护。
```

## 14. MVP Boundary

本阶段只做：

```text
真实代码考古（21 条路径）
Adoption / Preparation / Metadata 分类
Authority 候选比较 + 推荐
统一 AdoptionAuthority contract
Authority Binding
跨系统 fail-closed 冲突规则
人审批 -> 自动 adoption 路径设计
Bypass closure 清单
离线验证（inventory + validator + 17 tests）
```

本阶段不做（不实现）：

```text
production AdoptionGuard
Registry 集成 / promote() 改造
Runtime 集成 / PluginManager / ToolRuntime / CodexAdapter 改造
Langfuse 集成 / guarded wrapper
decision / approval / revocation 持久化
write-once 存储
E.8 / production rollout
```

落地顺序建议（未来阶段，本阶段不执行）：

```text
1. durable decision/approval store + AdoptionAuthority 签发
2. Registry Guard（pilot promote）
3. Runtime Guard（capability install / tool execute / rollout select）
4. skill_ref/b1_skill_ref 指针绑定 authority
5. Langfuse guarded wrapper 或 EXTERNAL_UNCONTROLLABLE 标记
6. write-once / revocation（当前 UNKNOWN）
```

## 15. Open Questions

```text
1. 生产 Registry 是哪个？pilot registry 明确 EXPERIMENT_ONLY。
2. 目标生产 Runtime 是 pilot slice、capability manager、tool runtime，
   还是 Langfuse 消费侧？
3. AdoptionAuthority 由谁签发、谁持久化、如何保证 authorized_principal
   真实？
4. skill 采用（B1/B2）是否与 capability 采用共用同一 contract，还是
   显式 experiment-only？
5. Langfuse 服务端是否允许 / 记录直接 active prompt 创建？
6. revocation / supersession 存储由谁实现？
7. expires_at 是否引入 TTL？当前只有“最新决策”规则。
8. write-once 信任锚形态（SQLite 约束 / WORM / signed hash chain）？
9. break-glass 审批存储 / 自动过期是否存在？
```

## Final Verdict

```text
ADOPTION_AUTHORITY_VALID_WITH_UNKNOWN
```

```text
FACT:
  adoption paths discovered from code（21 条，8 ADOPTION）；
  offline authority contract validated（17 passed）；
  fail-closed 冲突规则与 no-fallback 规则可机械检查。

UNKNOWN:
  production authority enforcement（Registry / Runtime / Langfuse
  未接入；持久化 / revocation / expiry / Langfuse 服务端 enforcement）。
```

不是 `ADOPTION_AUTHORITY_VALID`：production enforcement 全部 UNKNOWN。
不是 `ADOPTION_AUTHORITY_PARTIAL`：本阶段要求的是“路径枚举 + 统一建模 +
最小契约”，这些已完整达成。
不是 `ADOPTION_AUTHORITY_INVALID`：所有推荐落点都有真实代码路径支撑。

## Offline Proof

```text
python3 docs/archaeology/unified-runtime/phase7.6/inventory_adoption_paths.py
  -> ADOPTION_PATH_INVENTORY_VALID（21 条路径全部分类，
     8 条 ADOPTION 全部带 target authority requirement）

python3 docs/archaeology/unified-runtime/phase7.6/validate_adoption_authority.py
  -> ALLOW（valid authority, registry pre-state + runtime/external post-state）

python3 -m pytest docs/archaeology/unified-runtime/phase7.6 -q
  -> 17 passed

python3 -m py_compile docs/archaeology/unified-runtime/phase7.6/*.py
  -> COMPILE_OK
```

覆盖矩阵：

| 场景 | 结果 |
| --- | --- |
| valid authority 全链路 | ALLOW |
| candidate id mismatch | ADOPTION_BLOCKED / CANDIDATE_ID_MISMATCH |
| candidate version mismatch | ADOPTION_BLOCKED / CANDIDATE_VERSION_MISMATCH |
| policy mismatch | ADOPTION_BLOCKED / POLICY_VERSION_MISMATCH |
| artifact mismatch | ADOPTION_BLOCKED / ARTIFACT_DIGEST_MISMATCH |
| missing decision | ADOPTION_BLOCKED / MISSING_DECISION |
| Registry ALLOW + Runtime BLOCK | ADOPTION_BLOCKED / SYSTEM_RUNTIME_BLOCKED |
| Registry BLOCK + Runtime ALLOW | ADOPTION_BLOCKED / SYSTEM_REGISTRY_BLOCKED |
| External ALLOW + Registry BLOCK | ADOPTION_BLOCKED / SYSTEM_REGISTRY_BLOCKED |
| system verdict UNKNOWN | ADOPTION_BLOCKED / SYSTEM_*_UNKNOWN |
| use_latest / use_previous / use_active / use_manual | ADOPTION_BLOCKED / FALLBACK_NOT_AUTHORITY |

Stop：不 commit、不 push、不接真实 Registry / Runtime / Langfuse、不做
E.8、不做 production rollout、不修改 E.5–E.7.1 与 Phase 7–7.5 冻结文件。
