# 78 — Production Trust Boundary / MVP Closure（Phase 8.5）

> 阶段：Phase 8.5（Production Trust Boundary / MVP Closure）。
> 基线：77（Phase 8.4.3，TRUST_ANCHOR_PARTIAL）、76（8.4.2）、75（8.4.1）、
> 74（8.4）、73（8.3）、72（8.2）、71（8.1）、70（8）、69（7.6）、
> 68 / 67 / 66（7.5 / 7.4.1 / 7.4）、65 / 64（7.3.1 / 7.3）、63 / 62（7.2）、
> 61（7.1）。
> 约束遵守：未修改生产代码；未修改 Phase 7–8.4.3 历史 artifacts；未触碰
> codex/、control-plane/、openhands/、48/51/52/53；未 commit / push。
> 只允许新增：本文件、`phase8.5/`。

## 1. Executive Summary

本阶段不做新安全代码，只回答四个问题：

```text
哪些安全能力必须由 Agent Capability Forge 平台保证？
哪些安全能力必须由客户部署环境保证？
哪些能力属于 Enterprise Hardening？
当前系统是否已经达到一个可以定义清楚边界的 MVP？
```

结论：**已经可以定义清楚边界**。采用三层模型：

```text
Layer 1  Platform Governance   —— 平台代码保证（evaluation 证据绑定、
                                  promotion gate、authority 签发、
                                  registry guard、runtime guard、
                                  fail-closed）
Layer 2  Deployment Boundary   —— 客户部署环境保证（文件权限、只读挂载、
                                  进程隔离、governance store 写保护、
                                  凭据保护）
Layer 3  Enterprise Hardening  —— 后续增强（密码学 issuer、HSM/KMS/PKI、
                                  WORM、immutable storage、open-by-handle、
                                  外部 attestation、分布式信任）
```

最终判定：

```text
MVP_SECURITY_BOUNDARY_VALID_WITH_UNKNOWN
```

理由（摘要）：

```text
FACT   MVP Security Contract 第 1–8 条都有 pilot/ 真实代码证据：
       producer 签发 authority、registry.promote() 要求 authority +
       store + ledger + anchor、runtime adopt() / verify_at_mount() 在
       docker_launch 前 fail-closed、revoked/superseded 阻断、
       binding/digest 不一致阻断、写一次 ledger、锚定 manifest。
FACT   Phase 7.2–8.4.3 回归 240 passed；8.4.3 对抗矩阵 PASS。
FACT   本文件明确区分 Platform / Deployment / Enterprise，没有把
       “OS 权限”或“host/root 防护”伪装成平台保证。
UNKNOWN 第 9 条（Agent 进程不能修改 governance store）依赖部署契约：
        当前仓库没有部署环境，无法验证实际文件权限 / 只读挂载 /
        anchor 物理写保护。
UNKNOWN OS 级 TOCTOU（verify_at_mount 与 bind-mount 解析之间的微窗口）、
        同 OS 用户删除 store+anchor、密码学 issuer 真实性。
```

不是 `MVP_SECURITY_BOUNDARY_VALID`：部署契约尚未在真实部署环境中验证，
anchor 是否位于受保护路径仍 UNKNOWN。
不是 `MVP_SECURITY_BOUNDARY_PARTIAL`：核心边界没有冲突，关键责任归属
清晰，剩余缺口都是已命名的部署 / 企业责任，不是平台责任模糊。
不是 `MVP_SECURITY_BOUNDARY_INVALID`：契约 1–8 有可运行测试支撑。

本阶段不是“证明绝对安全”。平台层保证的是 governance semantics；
tamper resistance 的物理部分由部署边界提供。

## 2. Current Architecture

### 2.1 真实调用链（pilot 切片）

```text
Candidate 目录
  -> harness.phase_b3_build() 执行 validation + evaluation
  -> evaluation["verdict"] == "PASS"
  -> producer.issue_authority()          pilot/adoption_authority_producer.py:86
       （要求 confirm.json confirm=true；持久化 decision/run/policy/
         candidate/lifecycle/evidence；写 authority ledger；刷新 anchor）
  -> registry.promote()                  pilot/registry.py:57
       （要求 adoption_authority + adoption_store.json + anchor +
         ledger；任何缺失/mismatch -> ADOPTION_BLOCKED）
  -> runtime_guard.mark_promoted()       pilot/runtime_adoption_guard.py:375
       （lifecycle PROMOTABLE -> PROMOTED）

运行期（唯一真实执行路径 phase_future("b3")，pilot/harness.py:652）：
  -> runtime_guard.adopt()               pilot/harness.py:721
  -> runtime_guard.verify_at_mount()     pilot/harness.py:727
  -> docker_launch() 只读挂载 artifact   pilot/harness.py:729
       （(artifact_dir, "/artifact", True) 只读；sandbox network=false，
         pilot/config.json）
```

### 2.2 Governance Store 形态

```text
<registry_root>/adoption_store.json
  policies / candidates / runs / evidence / provenance / decisions /
  lifecycle / revocations / authorities / store_metadata

<registry_root>/authorities/<authority_id>.json
  write-once authority ledger（O_EXCL 等价 CAS，pilot/adoption_authority.py:307）

<registry_root>/authorities/<authority_id>.events.jsonl
  append-only REVOKED / SUPERSEDED 事件（pilot/adoption_authority.py:374）

<external>/<registry_root>.integrity-anchor.json 或 ${PILOT_INTEGRITY_ANCHOR}
  operator-sealed 外部 manifest（pilot/adoption_authority.py:180,246）
```

### 2.3 当前 enforcement 点

| 位置 | 强制内容 | 代码证据 |
| --- | --- | --- |
| Authority 签发 | confirm + evaluation + decision + digest + ledger | `issue_authority()`，producer.py:86 |
| Registry Guard | authority 缺失 / store 缺失 / anchor 不一致 / binding mismatch / ledger 缺失 → BLOCK | `promote()`，registry.py:57–106 |
| Runtime Guard | state / authority / binding / digest / lifecycle / policy / provenance / revocation / stale → BLOCK | `adopt()`，runtime_adoption_guard.py:285 |
| Mount 前 recheck | 最新 digest + 最新 revocation，紧贴 docker_launch | `verify_at_mount()`，harness.py:727 |
| Revocation | 只 append events，不重写 ledger；store 副本为 load-bearing | `revoke_authority()`，adoption_authority.py:374 |
| Trust Anchor | sealed store 下 anchor 缺失 / 篡改 → INTEGRITY_STORE_CORRUPTED | `integrity_anchor_violations()`，adoption_authority.py:123 |

### 2.4 已完成的 Phase 7.2–8.4.3 结论

```text
7.2  CONTRACT_VALID_WITH_EXTENSIONS
7.3  ENFORCEMENT_BOUNDARY_PARTIAL -> 7.3.1 修复
7.4  ADOPTION_GUARD_DESIGN_VALID_WITH_UNKNOWN
7.5  PRODUCTION_ADOPTION_GUARD_FEASIBLE（设计）
7.6  ADOPTION_AUTHORITY_VALID_WITH_UNKNOWN
8    MINIMAL_ENFORCEMENT_VALID_WITH_UNKNOWN
8.1  AUTHORITY_PRODUCER_VALID_WITH_UNKNOWN
8.2  RUNTIME_ADOPTION_GUARD_VALID_WITH_UNKNOWN
8.3  AUTHORITY_STORAGE_HARDENING_VALID_WITH_UNKNOWN
8.4  INTEGRITY_HARDENING_VALID_WITH_UNKNOWN
8.4.1 INTEGRITY_HARDENING_VALID_WITH_UNKNOWN（P1/P2 修复）
8.4.2 INTEGRITY_HARDENING_VALID_WITH_UNKNOWN（hardened marker）
8.4.3 TRUST_ANCHOR_PARTIAL
```

## 3. Platform Responsibilities

平台代码必须保证（MUST）：

```text
1. Evaluation 证据绑定 Candidate / Version / Run / Policy
2. Promotion Policy 注册 + frozen 校验
3. Promotion Gate 结果必须是 PASS 才能进入 adoption
4. PromotionDecision 持久化且与 Candidate / Version / Run / Digest 绑定
5. AdoptionAuthority 只能由合法 decision 签发（deterministic + ledger）
6. Registry Guard：没有合法 authority + store + ledger + anchor 不能 PROMOTED
7. Runtime Guard：没有合法 authority 不能执行
8. Candidate / Version / Artifact Digest 不一致必须 BLOCK
9. revoked / superseded 必须 BLOCK
10. historical evidence / authority binding 不允许正常流程覆盖
11. Fail-closed：任何缺失 / 篡改 -> ADOPTION_BLOCKED，状态不变
12. Provenance semantics 完整性校验
```

代码证据：producer.py:86、registry.py:57–106、runtime_adoption_guard.py:285、
adoption_authority.py:513（violations_for_authority）。

平台不保证（明确 OUT_OF_SCOPE）：

```text
- host / root 权限边界
- 文件系统 ACL / 只读挂载 / WORM
- 密码学签名 / HSM / KMS / PKI
- 容器逃逸防护（沙箱本身是部署能力）
- 外部服务（Langfuse 等）的权限模型
```

## 4. Deployment Responsibilities

客户部署环境必须保证（MUST）：

```text
1. filesystem permissions（governance store 目录仅受限用户可写）
2. protected volume / read-only mounts
3. process isolation（governance process 与 agent runtime 分离）
4. UID/GID separation
5. container isolation（agent runtime 沙箱）
6. artifact storage protection（runtime 只读）
7. Authority Store write permissions（只有 governance 进程可写）
8. deployment credentials / secret protection
9. trust anchor 物理写保护（独立目录 / 只读挂载 / 外部服务）
10. OS-level TOCTOU 闭合（open-by-handle / immutable refs / 只读挂载）
```

这些能力当前在 pilot/ 中没有实现代码，也不应伪装成平台能力。
仓库考古确认：pilot/ 没有 chmod / ACL / flock / fcntl / O_PATH 逻辑，
文件权限完全依赖部署（FACT）。

## 5. Enterprise Hardening

后续增强项（SHOULD / OPTIONAL / OUT_OF_SCOPE 见矩阵）：

```text
- Cryptographic Issuer（签名 authority / attestation）
- HSM / KMS（密钥托管）
- PKI / CA（issuer 身份真实性）
- WORM（write-once read-many 存储）
- Immutable Object Storage（artifact 内容寻址）
- OS-level open-by-handle（闭合 mount 前 TOCTOU 微窗口）
- External Trusted Attestation（独立 attestation service）
- Distributed Trust（多写者 / 多 runtime 共识）
- Advanced Tamper Resistance（防回滚 / 防删除）
```

Enterprise 是产品路线图边界，不是 MVP 退出条件。

## 6. Threat Model

威胁分级与平台判定（不声称平台可防 host/root）：

| 威胁 | 能力描述 | 平台能否防 | 判定 |
| --- | --- | --- | --- |
| T0 | 普通 Agent / 普通调用方 | 不能伪造 authority、不能跳过 registry/runtime guard；governance store 由部署契约保护 | PROTECTED（平台 + 部署契约） |
| T1 | 恶意 Capability（artifact 内容恶意） | digest 绑定 + runtime guard + 只读挂载 + 沙箱执行；沙箱逃逸取决于部署 | PARTIALLY_PROTECTED（内容 gate 平台保证；沙箱是部署） |
| T2 | 恶意调用者，无 host/root | 无 authority 不能 PROMOTED / 不能执行；不能写 governance store（部署权限） | PROTECTED（平台 + 部署契约） |
| T3 | 具有 registry filesystem 写权限 | sealed store 下篡改 store/ledger/events 被 anchor 检测；同一用户同时改 anchor + seal 标记则不可检测 | PARTIALLY_PROTECTED（anchor 受保护时；同用户全写 = NOT_PROTECTED） |
| T4 | 具有 host/root 权限 | 平台无法阻止 root 改文件 / 删 anchor / 改进程 | NOT_PROTECTED（部署层可缓解：容器 / 卷 / 只读） |
| T5 | 部署基础设施完全被攻破 | 任何应用层治理都失效 | OUT_OF_SCOPE |

补充：

```text
未 seal / legacy store 下，T3 = NOT_PROTECTED：
  store 被编辑后无 anchor 可比对。
已 seal + anchor 受部署写保护下，T3 = PROTECTED：
  任何 store/ledger/events 篡改都会 anchor mismatch -> BLOCK。
```

## 7. MVP Security Contract

定义：只有以下全部成立，才可说 `MVP SECURITY VALID`：

| # | 契约 | 当前证据 | 判定 |
| --- | --- | --- | --- |
| 1 | 非法 Candidate 不能通过 Promotion Gate | `issue_authority()` 要求 evaluation PASS + confirm + policy frozen + gate_result PASS + 全绑定一致（producer.py:86；adoption_authority.py:513） | FACT / PROTECTED |
| 2 | 没有合法 PromotionDecision 不能产生有效 Authority | decision 缺失 / value != PROMOTE / gate != PASS / binding mismatch → AUTHORITY_ISSUANCE_BLOCKED；authority_id 确定性绑定 decision | FACT / PROTECTED |
| 3 | Registry 没 Authority 不能 PROMOTED | `promote()` 无 authority → MISSING_AUTHORITY；无 store → MISSING_ADOPTION_STORE；anchor/ledger 不一致 → BLOCK（registry.py:62–106） | FACT / PROTECTED |
| 4 | Runtime 没 Authority 不能执行 | `adopt()` 在 docker_launch 前强制全量校验，任何失败 → ADOPTION_BLOCKED（harness.py:721–729） | FACT / PROTECTED（仅 pilot B3 路径） |
| 5 | Candidate/version/digest 不一致必须 BLOCK | CANDIDATE_ID_MISMATCH / CANDIDATE_VERSION_MISMATCH / ARTIFACT_DIGEST_MISMATCH（adoption_authority.py:513；runtime_adoption_guard.py:80） | FACT / PROTECTED |
| 6 | revoked / superseded 必须 BLOCK | REVOKED_DECISION：events + store 副本 + anchor manifest 三重（adoption_authority.py:374,484；runtime_adoption_guard.py:80） | FACT / PROTECTED |
| 7 | historical evidence / authority binding 不允许正常流程覆盖 | write-once ledger（adoption_authority.py:307）；无 overwrite API；重复 issue 不同 binding → BLOCK；decision/evidence tamper 校验 | FACT / PROTECTED（正常流程）；OS 级删除 UNKNOWN |
| 8 | Fail Closed | 所有 guard 缺失即 ADOPTION_BLOCKED，state 不变；sealed store 无 legacy fallback | FACT / PROTECTED |
| 9 | 正常部署权限模型下，Agent 进程不能修改 governance store | **Deployment Contract**：平台代码不做 OS 权限；由部署保证（见 §8） | CONTRACT DEFINED；实际部署 UNKNOWN |

注意：第 9 条不是平台代码承诺。缺少部署条件时标注
`DEPLOYMENT_CONTRACT_VIOLATION`，不继续堆应用层 workaround。

## 8. Deployment Security Contract

MVP 自托管至少要求：

```text
1. Authority Store 目录由受限用户拥有
2. Agent Runtime 不拥有 Authority Store 写权限
3. Artifact Store 对 Runtime 只读
4. Governance process 拥有写权限
5. Runtime process 只能读取 Authority
6. Operator 可以执行受控 revoke / recovery
7. Host / volume 不允许普通 Agent 进程直接修改治理文件
```

任何一条缺失：

```text
DEPLOYMENT_CONTRACT_VIOLATION
```

而不是“继续依赖应用层 workaround”。

当前仓库状态：

```text
FACT      部署契约已在本文件定义，可机械核对。
UNKNOWN   本仓库没有部署环境（无 compose / 系统服务 / 卷定义），
          7 条均未在真实部署中验证。
```

## 9. Trust Anchor Boundary

最终定位（不再向 pilot/ 内继续堆 anchor）：

```text
如果 adoption_store.json + anchor 都被同一个 OS user 修改：

平台还能保证什么？
  -> 应用层 governance semantics 仍然成立：
     sealed store 下的篡改会导致 anchor mismatch（除非 seal 标记
     与 anchor 一起被删，进程内不可检测）。

平台不能保证什么？
  -> tamper resistance 依赖 deployment boundary。
     同目录 sibling 文件不是独立 trust domain。
```

分级：

```text
MVP       deployment-protected trust boundary
          = anchor 位于受保护路径（不同用户 / 只读挂载 / 外部服务），
            由部署契约提供物理写保护
Enterprise cryptographically verifiable external trust anchor
          = 签名 / KMS / HSM / 外部 attestation
```

代码事实：

```text
FACT      anchor 路径强制在 registry_root 之外（adoption_authority.py:90）。
FACT      seal 是 create-only 显式 operator 动作（adoption_authority.py:246）。
FACT      sealed store 下 14 项对抗攻击全部 INTEGRITY_STORE_CORRUPTED
          （phase8.4.3 验证矩阵 PASS）。
INFERENCE anchor 位于受保护路径时才是真正的不同 trust domain。
UNKNOWN   同 OS 用户同时删除 seal 标记 + anchor（进程内不可检测）。
```

```text
sibling 默认文件                -> NOT_A_TRUST_ANCHOR（仅测试/迁移便利）
外部路径 + 部署写保护           -> 真正 trust anchor（INFERENCE）
```

不要把同目录 sibling 文件称为真正独立 trust domain。

## 10. Human Approval → Automatic Adoption

MVP 自动化链（正式定义）：

```text
Candidate
  -> Evaluation（机器）
  -> Regression（机器）
  -> Promotion Gate（机器）
  -> Human Approval（risk-dependent，人）
  -> PromotionDecision（机器持久化）
  -> AdoptionAuthority（机器签发）
  -> Registry Guard（机器）
  -> PROMOTED
  -> Runtime Guard（机器）
  -> RUN
```

责任划分：

```text
人只负责：high-risk authorization
机器负责：evidence、gating、authority issuance、registry adoption、
          runtime verification
```

当前支持度：

```text
FACT    pilot/confirm.json 只有 operator 字符串 + confirm=true，
        无 approved_at / policy_version / decision_id（pilot/confirm.json）。
FACT    issue_authority() 以 confirm + evaluation 构造持久化 decision，
        但 approval 本身不是 durable audit record（issuer_id 取自
        confirm/operator，无签名）。
INFERENCE 生产 approval 需要 durable approval record（approved_by /
          approved_at / scope / expiry），当前缺失。
```

## 11. Risk Tiers

只定义框架，不发明具体企业规则：

| 级别 | 自动化程度 | 控制 |
| --- | --- | --- |
| LOW RISK | 自动 Promotion / Adoption | evidence-gated 全自动链 |
| MEDIUM RISK | 自动 Evaluation + Gate；人工 Approval | 人工授权 + 持久化 decision |
| HIGH RISK | 人工 Approval + 强化 Policy | 额外审批 / 双人 / 独立 governance 通道 |

风险分级的具体阈值（什么能力算 HIGH）由客户 policy 定义，不属于本阶段。

## 12. GitHub Reference Model

GitHub 是 reference architecture，不是复制对象：

| GitHub | Forge |
| --- | --- |
| PR | Candidate |
| Checks | Evaluation / Regression |
| Branch Protection | Promotion Policy / Gate |
| Merge Queue | Adoption Guard（最终 revalidation） |
| Merge | Registry adoption（PROMOTED） |
| CI artifact attestation | Capability Attestation / Provenance |

四个可借鉴原则：

```text
1. Required Checks
   = evidence-gated state transition（没有全部 checks 通过不能合并）
   -> Forge：没有合法 evaluation + gate PASS + authority 不能 PROMOTED

2. Trusted Check Source / GitHub App
   = Trusted Issuer（只有受信任的 app 能报告 check）
   -> Forge：PILOT_TRUSTED_ISSUERS + write-once ledger 限定 issuer

3. Merge Queue final validation
   = final adoption / runtime revalidation（合并前重新跑一遍最新状态）
   -> Forge：verify_at_mount() 在 docker_launch 前重新验证 digest +
      revocation

4. Artifact Attestation
   = Capability Attestation / Provenance（构建产物带签名证明）
   -> Forge：artifact digest + provenance manifest；密码学版本属于
      Enterprise
```

## 13. Cordis Reference Model

Cordis（python-cordis 生命周期）：

```text
Install -> Load -> Activate -> Deactivate -> Unload
```

解决：**Runtime Capability Lifecycle**。

Forge：

```text
Evaluate -> Promote -> Authorize -> Adopt -> Revoke
```

解决：**Capability Governance Lifecycle**。

组合边界：

```text
Governance（Forge）
  -> Runtime（Cordis）

只有 PROMOTED + valid Authority 才允许 Runtime Activate。
```

当前仓库状态：

```text
FACT    python-cordis 生命周期代码存在于 docs/archaeology/python-cordis/。
FACT    pilot B3 是唯一已接 runtime guard 的真实执行路径。
UNKNOWN Cordis / ToolRuntime 尚未接入 Forge adopt()（未实现，不在 MVP）。
```

## 14. Capability Abstraction

核心架构结论：MVP 不绑定具体实现类型。

```text
统一对象：Capability

Capability implementation 可以是：
  Skill / Plugin / Tool / MCP / Workflow / Prompt / Agent Extension
```

Forge 治理对象是统一 Capability（identity / version / digest / authority /
lifecycle），实现层负责如何加载和执行。

当前代码支持度：

```text
FACT    pilot registry 以 family/name/capability_id/artifact_dir 统一
        描述 entry（registry.py:129–150），不绑定 Skill/Plugin 字段。
FACT    pilot 切片实际能力是 skill 形态（csv-clean-statistical-report），
        运行时是 artifact 目录 + main.py。
INFERENCE 统一 Capability + 实现适配器可覆盖 Skill/Plugin/Tool/MCP/
          Workflow/Prompt/Agent Extension。
UNKNOWN 各实现的加载 / 激活适配器均未实现（Multi-Runtime 边界）。
```

## 15. Product Boundary

Agent Capability Forge **不是**：

```text
- GitHub clone（不做源码托管 / CI）
- Plugin Manager clone（不做通用插件安装器）
- Langfuse clone（不做 trace / 可观测性存储）
- Evaluation-only platform（评估只是 evidence，不是终点）
```

是：

```text
Capability Governance + Adoption Control Plane
```

配合关系：

| 系统 | 角色 |
| --- | --- |
| GitHub | source / development（PR/Checks reference） |
| Cordis / Runtime | execution（runtime lifecycle） |
| Langfuse | observability（外部指针，不在平台控制内） |
| Forge | capability governance + adoption control plane |

## 16. FACT / INFERENCE / UNKNOWN

```text
FACT      producer 持久化 decision/run/policy/candidate/lifecycle/
          evidence 并签发确定性 authority（producer.py:86）。
FACT      registry.promote() 要求 authority + store + anchor + ledger，
          任何缺失/不一致 ADOPTION_BLOCKED（registry.py:57–106）。
FACT      runtime guard 在唯一真实执行路径 docker_launch 前强制
          adopt() + verify_at_mount()（harness.py:721–729）。
FACT      write-once authority ledger + append-only revocation events
          （adoption_authority.py:307,374）。
FACT      sealed store 下 14 项对抗攻击全部 fail-closed（8.4.3）。
FACT      Phase 7.2–8.4.3 回归 240 passed；compileall clean；
          validate_integrity_trust_anchor.py PASS。
FACT      pilot/ 无 chmod / ACL / flock / fcntl / O_PATH 代码，
          OS 权限未由平台实现。

INFERENCE anchor 位于受保护路径时构成真正独立 trust domain。
INFERENCE 统一 Capability + 实现适配器可覆盖 Skill/Plugin/Tool/MCP/
          Workflow/Prompt/Agent Extension。
INFERENCE 生产 approval 需要 durable approval record（approved_by /
          approved_at / scope / expiry），当前 confirm.json 不够。

UNKNOWN   部署环境实际文件权限 / 只读挂载 / anchor 写保护（契约已定义，
          未验证）。
UNKNOWN   同 OS 用户同时删除 store + anchor（进程内不可检测）。
UNKNOWN   verify_at_mount() 与 bind-mount 解析之间的 OS 级微窗口。
UNKNOWN   密码学 issuer 真实性（无签名 / PKI / KMS）。
UNKNOWN   Cordis / ToolRuntime / Langfuse / 多 Runtime 未接入。
```

## 17. Residual Risks

```text
1. 同 OS 用户可同时删除 trust_anchor_sealed + anchor
   -> 进程内被解释为“从未 seal”的 legacy store（部署契约闭合）。
2. 默认 sibling anchor 与 store 同级可写，不是真 trust anchor；
   生产必须设置 PILOT_INTEGRITY_ANCHOR 到受保护路径。
3. 无密码学 issuer 签名；authority 真实性是 deterministic binding +
   ledger，不是签名。
4. flat adoption_store.json 仍是 last-writer-wins：
   并发写可能丢记录，但丢失会 fail-closed（ledger/store 不一致 -> BLOCK），
   不会静默放行。
5. verify_at_mount 与 bind-mount 解析之间的 OS 级微窗口（open-by-handle
   属于 Enterprise）。
6. artifact promote 后没有内容寻址不可变副本；运行时重新 digest 校验，
   但 OS 级可改（部署 / Enterprise）。
7. pilot 只有 B3 一条真实 runtime 路径；其他 runtime 未接 guard。
8. Langfuse 人工 label 移动没有被平台拦截（外部服务边界）。
9. confirm.json 的 operator 字符串不是 durable approval record。
```

## 18. MVP Exit Criteria

定义“可以说 MVP SECURITY VALID”的退出条件：

| # | 条件 | 当前状态 |
| --- | --- | --- |
| 1 | Platform / Deployment / Enterprise 三层边界文档化且无冲突 | DONE（本文件） |
| 2 | MVP Security Contract 1–8 有实际代码证据 | DONE（240 tests + 本阶段 validator） |
| 3 | 第 9 条明确为 Deployment Contract，不伪装成平台保证 | DONE |
| 4 | Deployment Security Contract 7 条在真实部署中验证 | NOT_DONE（部署方执行） |
| 5 | trust anchor 部署在受保护路径（非 sibling） | NOT_DONE（部署方执行） |
| 6 | 无平台层 UNKNOWN 阻塞剩余边界 | PARTIAL（OS TOCTOU / 同用户删除属部署/企业） |
| 7 | Enterprise 能力明确 OUT_OF_SCOPE | DONE |

只有 1–7 全部完成才升级为 `MVP_SECURITY_BOUNDARY_VALID`。
当前满足 1、2、3、7；4、5 是部署验证项，6 的剩余项归属明确 -> 判定
`MVP_SECURITY_BOUNDARY_VALID_WITH_UNKNOWN`。

本阶段验证（实际运行）：

```text
python3 -m pytest docs/archaeology/unified-runtime/phase7.2 \
  docs/archaeology/unified-runtime/phase7.3 \
  docs/archaeology/unified-runtime/phase7.4 \
  docs/archaeology/unified-runtime/phase8 \
  docs/archaeology/unified-runtime/phase8.1 \
  docs/archaeology/unified-runtime/phase8.2 \
  docs/archaeology/unified-runtime/phase8.3 \
  docs/archaeology/unified-runtime/phase8.4 \
  docs/archaeology/unified-runtime/phase8.4.3 -q
  -> 240 passed

python3 -m compileall -q pilot docs/archaeology/unified-runtime/phase8.4.3
  -> COMPILEALL_OK

python3 docs/archaeology/unified-runtime/phase8.4.3/validate_integrity_trust_anchor.py
  -> TRUST_ANCHOR_PARTIAL: sealed-store adversarial matrix PASS

python3 -m pytest docs/archaeology/unified-runtime/phase8.5 -q
  -> 5 passed

合并回归：245 passed（Phase 7.2–8.4.3 240 + Phase 8.5 5）。

python3 docs/archaeology/unified-runtime/phase8.5/validate_mvp_boundary.py
  -> MVP_SECURITY_BOUNDARY_VALID_WITH_UNKNOWN: documented boundary + code facts OK
```

## 19. Phase 9 Recommendations

按需执行，不堆代码：

```text
1. Deployment contract verification kit（部署检查脚本 / 清单），
   验证 §8 的 7 条 + anchor 受保护路径；这是从 VALID_WITH_UNKNOWN
   升级到 VALID 的唯一必要条件。
2. 若业务需要可审计人工授权：新增 durable approval record
   （approved_by / approved_at / scope / expiry / decision_id），
   替换 confirm.json 字符串语义。
3. 若需要闭合 promote 后 artifact 可变：content-addressed immutable
   artifact copy + chmod 只读（应用层，不依赖 OS WORM）。
4. 密码学 issuer 只在真实 secret store / KMS 存在时引入；
   仓库当前没有自然落点。
5. Multi-Runtime：把同一 adopt() 语义接到 Cordis / ToolRuntime，
   复用最小共享 adapter；在第二个真实 runtime 接入前不扩展。
6. 外部 provider（Langfuse）指针拦截仅当产品边界包含外部 adoption
   pointer 时评估。
7. 继续维护 Phase 8 测试套件作为 MVP Security Contract 的回归基线。
```

## 停止条件

本阶段已完成：

```text
1. Threat Model（§6）
2. Platform vs Deployment boundary（§3/§4/§8）
3. MVP Security Contract（§7）
4. Enterprise Hardening boundary（§5）
5. Trust Anchor final positioning（§9）
6. GitHub reference（§12）
7. Cordis reference（§13）
8. Capability abstraction（§14）
9. Human Approval -> Automatic Adoption（§10/§11）
10. MVP Exit Criteria（§18）
11. Phase 9 recommendation（§19）
```

STOP：不进入 8.5.1；不继续堆安全代码；不接第二 Runtime / Langfuse /
Cordis；不 commit / push。
