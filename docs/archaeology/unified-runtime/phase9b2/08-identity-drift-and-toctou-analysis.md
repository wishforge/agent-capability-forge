# 08 Identity Drift / TOCTOU / Tag-Name-ID 分析

固定版本见 `00-code-archaeology-plan.md`。

## 1. 抽象场景：Evaluation=A, Promotion=A, Runtime=B

```text
Candidate A
    ↓
Evaluation = PASS
    ↓
Promotion = A
    ↓
Authority = A
    ↓
Registry = B
    ↓
Adoption
    ↓
Runtime = B
```

### 各项目如何阻止

| 项目 | 机制 | 阻止的层 |
|---|---|---|
| in-toto | MATCH 规则要求上一步 products 与下一步 materials 路径+hash 全等；DISALLOW 拒绝未消费 artifact（verifylib.py:645,1014） | 链内步骤之间；链外交付物替换不阻止（消费者需绑定 digest） |
| SLSA | verifier 把 subject.digest 与真实 artifact 比对（verifying-artifacts.md Step 1.2）；期望值验证（Step 2） | 验证时刻；不保证验证后部署同一字节 |
| Cosign | 先 `ResolveDigest(tag)`，再按 digest 验证签名与 payload claim（verify.go:650, verifiers.go:33） | 把“名字”降级为初始定位器；验证后对象是 digest |
| Policy Controller | mutating 把 tag 改写成 digest；validating 拒绝非 digest；cosign ClaimVerifier 绑 digest（validator.go:1103,1309；validation.go:39） | admission 与运行之间；Kubelet 按 digest 拉取 |
| DSSE | payloadType 进 PAE；验证字节必须原样进应用层（protocol.md；envelope.md Security） | 元数据层 type/rebinding |

结论：**行业没有单一魔法**。共同做法是“验证时解析/固定到 digest，然后所有后续
对象引用都用 digest，不再用名字”。Policy Controller 是唯一把“验证对象==运行对象”
写进平台契约的（通过改写 spec + 平台按 digest 拉取）。

## 2. 本项目哪里可以证明 A == A

可以证明的位置（全部是真实代码路径）：

```text
Seal：freeze_candidate 用同一字节算 artifact_digest + seal_digest，写 frozen record
      （capabilityizer.py:205,315）
Evaluation：evaluate 运行 candidate 目录字节；bind_evaluation 强制
      candidate_id/artifact_digest/seal_digest == frozen record（capabilityizer.py:465）
Authority：issue_authority 先 frozen_checks + evaluation_binding_violations +
      live_candidate_violations，再写 decision/authority（adoption_authority_producer.py:98）
Promotion：registry.promote 重跑同一组校验，复制 artifact 到 registry
      （registry.py:69）
Adoption：frozen_artifact_violations 对 live registry artifact 目录重算 canonical
      digest；六方 digest（authority/decision/run/candidate/entry/artifact）全等
      （runtime_adoption_guard.py:92,297）
Mount：verify_at_mount 重跑 adopt + expected digest 比对，随后 docker_launch
      用同一 artifact_dir（runtime_adoption_guard.py:415; harness.py:742-750）
```

所以字节级 A == A 是**完整闭合**的：每个环节要么重算 digest，要么把 digest 写进
不可变记录，最终 mount 前再重算一次。

## 3. 哪些阶段只有字符串 ID，没有 digest / authority / provenance 证明

```text
1. b3_entry.json（harness.py:633 写入）
     {"name": ..., "capability_id": ...}
     没有 digest；phase_future(b3) 只按 name 做 registry.discover（harness.py:689）
     -> “系统打算运行谁”的唯一记录是名字。

2. registry entry 的 name / family / artifact_dir 路径（registry.py:69 写入）
     entry 本身不在 trust anchor digest 覆盖内（anchor 只覆盖 adoption_store.json +
     authorities/ + revocation events，adoption_authority.py:123）
     -> entry.artifact_dir 被同写者改指到另一个目录时，digest 验证仍会拦截
        “内容不同”，但“内容相同/另一个合法候选”不会被判定为 drift。

3. evaluation 的 candidate_id（evaluate 原始产物，evaluator.py:57）
     bind_evaluation 之后被 frozen record 覆盖；单独字符串阶段是 intake 边界。

4. authority_id（adoption_authority.py:45）
     是 candidate|version|decision 的确定性 hash，不是内容 digest，也不是签名。
```

这些点共同说明：**身份标签（谁）与内容身份（什么）已经绑定在
decision/authority/entry 记录里，但“运行意图”只存在于 name 指针中**。

## 4. Identity Continuity Gap

```text
GAP-1  Intended-candidate drift：
       如果 b3_entry.json 的 name 被改成另一个已 promote 的候选，
       runtime 会完整验证并运行 B；所有记录（run record、digest、authority）
       都一致地指向 B。系统检测不到“操作者原本要运行 A”。

GAP-2  Pointer 无锚定：
       registry entry / b3_entry.json / frozen_root 路径不在 integrity anchor
       内。应用层靠 digest 全等兜底，但同写者若同时改 entry + store + ledger
       （未 seal 或锚也被写），digest 一致性本身可被重写。

GAP-3  candidate_id 是标签：
       单个 candidate_id 不是安全身份；安全身份是
       candidate_id + version + artifact_digest + seal_digest。这本身是正确设计，
       但意味着任何只按 candidate_id 索引的界面都不能单独作信任决策。
```

### GAP-1 的行业对照

- SLSA：把“预期包名”与“provenance 的 artifact 身份”分开（expectations tied to
  package name, provenance tied to artifact，verifying-artifacts.md）。运行方应显式
  记录“我预期运行 A 的 digest”，而不是只记名字。
- Policy Controller：无“预期镜像”概念，但 policy 匹配本身就按镜像模式选择要验证的
  对象；验证通过的是策略允许集合内的任何 digest。与之等价，本地也是“任何通过
  全链验证的候选都可运行”。
- 结论：GAP-1 不是缺陷级的漏洞（运行 B 是完全合法、有完整 provenance 的），但
  是**审计语义缺口**：没有“预期引用”（expected candidate digest）可对账。

## 5. TOCTOU 分析

### 本地

```text
verify Candidate A（adopt，重算 digest）
        ↓
artifact changed（两函数之间）
        ↓
verify_at_mount 重跑 adopt + digest 比对（runtime_adoption_guard.py:415）
        ↓
artifact changed（verify_at_mount 返回 与 内核 bind mount 之间）
        ↓
runtime executes（docker_launch）
```

现状：

- pre-mount 替换窗口：**已关闭**（verify_at_mount 紧跟 docker_launch）。
- verify 与 mount 之间的 OS 级竞态：**UNKNOWN**（phase9b1 报告原文承认；
  bind-mount 发生前目录内容仍可被同权限进程替换）。
- registry pointer 变化：adopt 每次从 entry 读路径；entry 内容变化若导致 digest
  变化 -> 拦截；若指向合法候选 -> 不被视为错误（GAP-1）。
- store 变化：trust anchor 校验；sealed store 下改写 store 或 authorities/ -> 拦截。
- frozen record/snapshot：verify_frozen 全量重算；record+snapshot 非单一原子提交
  的窗口有 fail-closed 检测（phase9b1）。

### 行业

| 项目 | 是否解决 TOCTOU | 机制 |
|---|---|---|
| in-toto | 不解决运行时刻 | 验证的是元数据；最终 digest 由消费者绑定（verifylib in_toto_verify 不执行部署） |
| SLSA | 部分 | 要求“对实际使用的 artifact”验证；推荐 consumer 侧（verifying-artifacts.md） |
| Cosign | 部分 | 先解析 digest 再验证，验证结果绑定 digest；但 CLI 返回后仍由调用方决定拉取什么 |
| Policy Controller | 是（平台级） | spec 被改写为 digest；validating 拒绝 tag；Kubelet 按 digest 拉取（validator.go:1103,1309） |
| DSSE | 元数据级 | 强制“验证字节 == 应用层字节”（envelope.md） |

## 6. Tag / Name / ID vs Digest

| 字段 | 类型 | 能否作安全身份 | 证据 |
|---|---|---|---|
| `candidate_id` | 生命周期标签（随机） | 否（单独）；是（四元组一部分） | capabilityizer.py:656,392 |
| `capability_id` | 名字的确定性 hash | 否；只是派生标签 | capabilityizer.py:182 |
| `artifact_digest` | 内容身份 | **是** | 全链六方比对 |
| `seal_digest` | 内容身份（核心+digest） | **是** | capabilityizer.py:114 |
| `registry_name` (family/name) | locator | 否 | registry.py:254 按 name 查 |
| `runtime_reference` (artifact_dir) | 路径 locator | 否 | harness.py:741 |
| container tag | locator | 否 | policy-controller validator.go:1309 “must be an image digest” |
| image digest / subject digest | 内容身份 | **是** | cosign verifiers.go:33,59；SLSA verifying-artifacts.md Step 1.2 |
| certificate identity (SAN+issuer) | 经 CA 认证的身份 | 是（在 trusted root 下） | cosign verify.go:369,441 |
| DSSE keyid | 非认证提示 | 否 | protocol.md：KEYID Unauthenticated |

## 7. 结论：名字能不能作为安全身份？

**不能。** 五个项目一致：

```text
in-toto：       artifact 匹配按 hash 相等，step/keyid 只是授权标签
SLSA：          名字绑定“期望”，digest 绑定“制品”（Expectations 一节原文）
Cosign：        先解析 tag -> digest，之后全部按 digest
Policy Controller：非 digest 引用直接拒绝（“since the tag can move”）
DSSE：          keyid 被签名算法忽略，明确 MUST NOT 用于安全决策
```

本地已经遵循这一原则：`artifact_digest` / `seal_digest` 是安全身份，name /
candidate_id 单独不是。**唯一需要加强的是：把“预期运行对象”也用 digest 记录**
（GAP-1），使名字指针的漂移至少可审计。
