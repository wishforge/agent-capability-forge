# 99 Synthesis（最终结论）

基线：`034a3b2`。本目录全部为只读考古；未修改 production code，未 commit。

## 七个问题

### Q1 当前 Candidate Identity 是否从 Evaluation → Promotion → Authority → Adoption → Runtime 保持连续？

**是，字节级连续。** 证据：

```text
Evaluation   -> bind_evaluation 写入 candidate_id + artifact_digest + seal_digest
                （capabilityizer.py:465）
Promotion    -> registry.promote 重验 frozen/eval/layout，entry.adoption 透传同 digest
                （registry.py:69）
Authority    -> decision/run/authority 同 digest；authority_id 绑定
                candidate|version|decision（adoption_authority_producer.py:98）
Adoption     -> 六方 digest（authority/decision/run/candidate/entry/artifact）全等
                （runtime_adoption_guard.py:92）
Runtime      -> verify_at_mount 重算 + expected 比对后 docker_launch 同一 artifact_dir
                （runtime_adoption_guard.py:415; harness.py:742-750）
```

唯一非字节连续的是“运行意图”：`b3_entry.json` 只记名字（GAP-1）。

### Q2 Evaluation=A、Promotion=A、Runtime=B，系统能否检测？

**能检测“内容不同”的 B，不能检测“另一个合法候选”的 B。**

```text
B 与 A 字节不同  -> adopt/verify_at_mount 的 canonical digest 比对必然 BLOCK
B 是另一个合法 promoted 候选且字节不同 -> 同样 BLOCK（digest 不匹配）
B 是另一个合法候选且恰好是名字指针被改 -> 不 BLOCK；系统会验证并运行 B，
   所有记录一致指向 B。属于审计语义缺口（GAP-1），不是字节级漏洞。
```

### Q3 Registry 改名 / 重绑 / pointer swap 后，能否造成 identity drift？

**内容漂移不能；意图漂移可能。**

```text
改名/重绑到不同字节 -> ARTIFACT_DIGEST_MISMATCH / ENTRY_BINDING_MISMATCH BLOCK
pointer swap 到同 digest 内容 -> 字节等价，无安全问题
pointer swap 到另一合法候选 -> 验证全过（GAP-1）
同写者同时改 entry+store+ledger（未 seal/锚被写）-> 边界外（GAP-2）
```

### Q4 Artifact 内容改变但 candidate_id 不变，能否被检测？

**能。** `verify_frozen` 重算 artifact digest（capabilityizer.py:315）、
`frozen_artifact_violations` / `live_candidate_violations`（:408,428）在
issue/promote/adopt 全部执行；`ARTIFACT_DIGEST_MISMATCH` / `FROZEN_FIELD_CHANGED`。

### Q5 Artifact path 不变但内容改变，能否被检测？

**能。** adopt 和 verify_at_mount 对 `artifact_dir` 路径指向的目录重算 canonical
digest（runtime_adoption_guard.py:374,415）；内容变即 digest 变即 BLOCK。

### Q6 Runtime 执行对象是否重新进行 identity / digest verification？

**是。** 执行前两道：

```text
adopt()             完整验证（authority/store/ledger/frozen/eval/layout/digest）
verify_at_mount()   再次 adopt + expected digest 比对
随后 docker_launch 挂载同一路径（harness.py:742-750）
```

残余窗口：verify 返回与内核 bind mount 之间的 OS 级替换（UNKNOWN，phase9b1
已声明）；建议用内容寻址不可变快照消除（R4）。

### Q7 行业最佳实践中哪些机制值得进入 Agent Candidate contract？

```text
ADOPT：
  R1 运行时预期对象用 digest 记录（Policy Controller / SLSA）
  R2 trust anchor 覆盖范围显式化（Sigstore trusted root 原则）
  R3 seal schema/version 纳入 seal_digest（DSSE PAE）
  R4 执行对象内容寻址化（Policy Controller digest 固定）
ADAPT：
  R5 in-toto 式多产物 step continuity 清单
  R6 SLSA 式期望值/身份配对验证
  R7 Cosign 式 issuer+subject 身份策略（当前用 env 字符串）
  R8 DSSE 验证字节契约（防“验 A 用 B”）
DO NOT ADOPT：
  in-toto layout DSL / 阈值模型；SLSA L1-L3 平台模型；Sigstore 全套；
  Kubernetes webhook；DSSE envelope/(t,n) 编码
```

## ARCHAEOLOGY VERDICT

```text
A. CURRENT IMPLEMENTATION:
   Canonical identity + Frozen Candidate + seal + authority ledger + trust
   anchor + adopt/verify_at_mount 已经构成一条闭合的 digest 链：Evaluation 绑定
   seal digest，Promotion/Authority/Registry 透传同一 digest，Runtime 在 mount 前
   重算并比对。字节级 A == A 已成立；fail-closed 语义完整（无 legacy fallback）。

B. INDUSTRY PRACTICE:
   五个项目的共识是：artifact digest 是安全身份，名字是 locator；验证发生在
   digest 上，运行也发生在 digest 上（Policy Controller 最彻底：拒绝非 digest
   引用并把 tag 改写成 digest）；类型/过程标签必须与被认证内容绑定（DSSE PAE）；
   身份断言必须来自可信根（Cosign 证书链 / in-toto layout 签名）。

C. REAL GAP:
   1) 运行意图只记录 name（GAP-1，预期 digest 缺失）
   2) registry entry / frozen / b3_entry 不在 trust anchor 覆盖内（GAP-2）
   3) issuer 是字符串非密码学身份（GAP-3，单机边界内可接受）
   4) seal 的 schema/version 未进 seal_digest（GAP-4，小）
   5) 运行对象是可变目录而非内容寻址快照（GAP-5，TOCTOU 残余）
   6) 多 artifact allowlist 尚未成为 intake 契约（GAP-6，未来）

D. SAFE TO IMPLEMENT:
   YES（指 Phase 9-B.2 的最小 invariant 化，如 R1/R3/R8）；
   R4 属于 contract/存储变更，需先做设计评审，但不存在阻断性安全障碍。

E. RECOMMENDED NEXT PHASE:
   9-B.2 最小集 = R1（预期 digest 对账）+ R2（锚定范围声明/扩展）+
   R3（seal schema/version 入 digest）+ R4（内容寻址快照）+ R8（验证字节契约）。
   先以 contract/测试形式落 invariant，再决定实现方式；不引入外部签名体系。

F. SHOULD WE ADOPT EXTERNAL MODEL:
   PARTIAL。
   机制层面：消化 Policy Controller 的 digest 固定、DSSE 的类型认证、
   in-toto 的 step 清单（多产物时）。
   实现层面：不引入 Sigstore/OCI/Kubernetes/in-toto layout；
   当前 flat JSON + write-once ledger 模型对单机 pilot 是正确的规模。
```

## 本阶段边界

- 未修改 `pilot/*`、`src/forge/*`、测试或文档（除本目录新增考古报告）。
- 未 commit、未 push。
- 所有外部结论基于固定 commit 的源码/规范，见 `00-code-archaeology-plan.md`。
