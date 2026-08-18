# Phase 9-B.3 Implementation Report — Candidate Identity Fail-Closed (R1 + R3 + R8)

- 日期：2026-08-18
- 基线：`9db2193`（Phase 9-B.2 Design Freeze 后）
- 实现范围：R1 + R3 + R8；未实现 R2 / R4 / O1 / O2
- 判定：**PASS_WITH_FINDINGS**

## Verdict

```text
PHASE 9-B.3 VERDICT

PASS_WITH_FINDINGS

R1 = IMPLEMENTED   b3_entry 携带四元组预期身份；canonical runtime fail-closed
R3 = IMPLEMENTED   seal v2 将 schema/seal_version 纳入 seal_digest；v1 兼容
R8 = IMPLEMENTED   verify_at_mount 绑定 verified_artifact_dir + mount_source 反例
R2 = NOT IMPLEMENTED（Phase 9-B.4）
R4 = NOT IMPLEMENTED（Phase 9-B.4）
O1 = OPEN（OS verify -> bind mount 竞态，本期不处理）
O2 = OPEN（b3_entry 不在 trust anchor 覆盖范围，同写者边界声明）
```

> 最终问题回答：**是。** 在应用层 contract 内，今天 Evaluation 批准 Candidate A，
> canonical Runtime 只能运行 Candidate A；A→B 在任何边界都 REJECT。残余仅剩
> O1（verify 返回与内核 bind mount 之间同权限写者的 OS 级窗口，UNKNOWN）与
> O2（b3_entry 同写者可改写，属于声明的信任边界），二者均为本期 Non-Goal。

## Identity Contract

统一四元组：

```text
ExpectedIdentity == ActualIdentity
  <=> candidate_id 相同
      AND candidate_version 相同
      AND artifact_digest 相同
      AND seal_digest 相同
缺少任何字段 -> REJECT（MISSING_IDENTITY）
```

| 分量 | 生成 | 持久化 | 读取/验证 | caller 可提供 | registry 可覆盖 | 可重算 | 丢失时 |
|---|---|---|---|---|---|---|---|
| candidate_id | `capabilityize` 内部 `uuid4` 生成（capabilityizer.py:656） | candidate.json / frozen record / authority / decision / run / entry.adoption | issue/promote/adopt 全链绑定 + R1 预期身份 | 否（内部生成） | 否（entry.adoption 必须等于 authority；BINDING_KEYS 全等） | 否（随机生命周期标签，write-once） | MISSING_FROZEN_CANDIDATE / MISSING_IDENTITY |
| candidate_version | manifest.capability.version 派生 `vN`（freeze/issue） | frozen record / authority / decision / run / entry.adoption | CANDIDATE_VERSION_MISMATCH 全链 + R1 预期身份 | 否（从 manifest 派生） | 否（entry 透传 authority 值） | 是（issue 时从 frozen candidate 重算） | REQUEST_METADATA_MISSING / MISSING_IDENTITY |
| artifact_digest | canonical digest（allowlist 字节，capabilityize/freeze） | frozen record / authority / decision / run / entry.adoption | issue/promote/adopt/verify 每次重算 + 六方全等 + R1 预期身份 | 否（永远从字节计算） | 否（adopt 重算 live digest，六方全等） | 是（每次校验重算） | ARTIFACT_DIGEST_MISMATCH / MISSING_IDENTITY |
| seal_digest | freeze 时计算；v2 payload 覆盖 schema/seal_version（R3） | frozen record / authority | verify_frozen 全量重算 + CANONICAL_IDENTITY_MISMATCH + R1 预期身份 | 否（从 record 计算） | 否（entry 不携带 seal；authority 为来源） | 是（verify_frozen 按 seal_version 分派重算） | CANONICAL_IDENTITY_MISMATCH / MISSING_IDENTITY |

### 与 Design Freeze 的代码事实差异（代码事实优先）

1. R1 的 b3_entry 在 freeze 文档列出
   `{name, capability_id, candidate_id, artifact_digest, seal_digest}`；本实现额外
   加入 `candidate_version`。依据：任务 §7 与 Design Freeze §3.2 均把
   `candidate_version` 冻结为身份分量（`authority_id_for` + version mismatch 依赖），
   缺少它无法区分同候选多版本决策。
2. 审计 Case B 的 Observed 错误码是 `UNISSUED_AUTHORITY`，而非 Design Freeze 预测的
   `ENTRY_BINDING_MISMATCH`。原因：hardened store 下 `adopt()` 先按
   `entry.adoption.promotion_decision_id` 解析 authority ledger，错配的 decision
   直接命中 ledger 缺失。两者均 fail-closed REJECT；代码事实优先。
3. R1 的“旧格式 b3_entry -> BLOCK”只施加于 canonical entry。任务 §10 明确要求保留
   合法 legacy 行为（historical legacy candidate -> legacy binding -> ALLOW），
   harness 因此仅对 `artifact_identity == CANONICAL_ARTIFACT_IDENTITY_V1` 的 entry
   传入 expected_identity；legacy path 保持原语义，canonical 永不降级。

## 实现内容

### R1 — 运行请求预期身份（pilot/harness.py）

```text
phase_b3_build ：
  b3_entry.json v2 = {name, capability_id, candidate_id, candidate_version,
                      artifact_digest, seal_digest}
  name / capability_id 仍是 Locator，不参与信任决策
phase_future("b3") ：
  canonical entry 必须通过 verify_at_mount(expected_identity=b3_entry)
  ExpectedIdentity != ActualIdentity -> AdoptionBlocked
  旧格式 b3_entry（缺任一身份字段）-> MISSING_IDENTITY -> REJECT
  legacy entry 保持 legacy binding ALLOW
```

### R3 — seal schema/version 进入 digest（src/forge/capabilityizer.py）

```text
SEAL_SCHEMA = "frozen-candidate-v2" / SEAL_VERSION = "v2"
seal_digest(..., seal_version=v2) 在 payload 增加
  payload["seal_schema"] / payload["seal_version"]
verify_frozen 按 record.seal_version 分派：
  v1 -> 旧 payload 重算（无 schema/version），v1 record 继续可验证
  v2 -> 新 payload 重算
  schema/version 组合不在 {(v1,v1),(v2,v2)} -> SEAL_SCHEMA_MISMATCH
  v1 改成 v2（或反之）且 digest 未重算 -> SEAL_DIGEST_MISMATCH
新候选（freeze_candidate / freeze_candidate_dir）从 v2 起；已有 v1 record 不迁移。
```

### R8 — 验证字节契约（pilot/runtime_adoption_guard.py）

```text
adopt() 报告新增 verified_artifact_dir（验证过的唯一路径）
verify_at_mount()：
  docstring 固化 contract：verified artifact_dir 是唯一合法 mount source；
  verify 与内核 bind mount 之间的 OS 竞态 = UNKNOWN
  mount_source != verified_artifact_dir -> RUNTIME_BINDING_MISMATCH -> REJECT
harness 用 mount["verified_artifact_dir"] 作为 docker_launch 唯一来源，
  verify 后不再二次解析路径。
```

### 结构化比较

`runtime_adoption_guard.identity_violations(expected, actual)` 对四字段逐一比较，
不做 partial match；错误码可区分：

```text
candidate_id       -> CANDIDATE_ID_MISMATCH
candidate_version  -> CANDIDATE_VERSION_MISMATCH
artifact_digest    -> ARTIFACT_DIGEST_MISMATCH
seal_digest        -> SEAL_DIGEST_MISMATCH
任一缺失            -> MISSING_IDENTITY
```

## Adversarial Results（A–H）

| # | 场景 | Before | After | Expected | Observed |
|---|---|---|---|---|---|
| A | Evaluation A → Promotion B | REJECT（`EVALUATION_BINDING_MISMATCH`，issue/promote 已有） | REJECT | REJECT | REJECT（`EVALUATION_BINDING_MISMATCH`） |
| B | Evaluation A → Registry B → Adopt | REJECT（hardened ledger 先解析 decision，`UNISSUED_AUTHORITY`） | REJECT | REJECT | REJECT（`UNISSUED_AUTHORITY`；代码事实优先，见上） |
| C | Promotion A → Runtime B | ALLOW（B 为完全合法候选时 adopt 完整验证并运行 B） | REJECT | REJECT | REJECT（`ARTIFACT_DIGEST_MISMATCH` + `CANDIDATE_ID_MISMATCH` + `SEAL_DIGEST_MISMATCH`） |
| D | Same digest, different identity | ALLOW（同 digest 的 B 被当成 A 运行） | REJECT | REJECT | REJECT（`CANDIDATE_ID_MISMATCH` + `SEAL_DIGEST_MISMATCH`；digest 相等） |
| E | Same path, changed content | REJECT（`ARTIFACT_DIGEST_MISMATCH`，adopt/verify 每次重算） | REJECT | REJECT | REJECT（`ARTIFACT_DIGEST_MISMATCH`） |
| F | Registry pointer swap（foo: A → B） | ALLOW（B 自身链完整时） | REJECT | REJECT | REJECT（`ARTIFACT_DIGEST_MISMATCH` + `CANDIDATE_ID_MISMATCH` + `SEAL_DIGEST_MISMATCH`） |
| G | Authority A, runtime B | REJECT（`ARTIFACT_DIGEST_MISMATCH`，已有） | REJECT | REJECT | REJECT（`ARTIFACT_DIGEST_MISMATCH`） |
| H | Missing identity component（旧格式 b3_entry） | ALLOW（预期身份不存在，name 指向 B 即运行 B） | REJECT | REJECT | REJECT（`MISSING_IDENTITY`） |

说明：A / B / E / G 在基线已 fail-closed，测试记录为 “Already satisfied”，没有伪造
RED；C / D / F / H 是 R1 修复的真实 gap（基线 adopt ALLOW 已用独立 repro 证明）。

## Tests

```text
Phase 9-B.3 targeted（phase9b3/test_candidate_identity_fail_closed.py）
  RED  ：15 failed + 1 passed（缺少 expected_identity / seal v2 / mount_source）
  GREEN：16 passed
  覆盖 A–J 全部场景 + R3 v1/v2 + R8 反例 + positive ALLOW

Phase 9-B.1 regression
  GREEN：53 passed + 6 subtests（+1 个 fixture 更新：
  test_phase_future_b3_activates_with_frozen_candidate 改用 v2 b3_entry，
  因旧格式按 R1 冻结为 BLOCK）

Full suite
  GREEN：847 passed, 11 skipped, 19 subtests passed
  （11 skipped 均为 APIConnectionError 外部服务不可达，与本阶段无关）

Production harness
  GREEN：HARNESS_LIVE_B3_PASS
  live phase_future("b3")，真实 Docker（python:3.12-slim，镜像已存在），
  临时 canonical state：
    fplus-future-1 oracle=PASS
    fplus-future-2 oracle=PASS
    两个 run 使用同一 verified digest
    sha256:5ac13b1a6dec0410eae7141013613e85399d650991ece2ef0cc10753d5086961
```

## Changed Files

```text
M src/forge/capabilityizer.py                    # R3：seal v2 + verify 分派
M pilot/runtime_adoption_guard.py                # R1/R8：identity_violations +
                                                 # verified_artifact_dir + mount_source
M pilot/harness.py                               # R1：b3_entry v2 + canonical
                                                 # expected identity + R8 单一路径
M docs/archaeology/unified-runtime/phase9b1/test_production_trust_chain.py
                                                 # b3_entry fixture v2（旧格式已冻结为 BLOCK）
A docs/archaeology/unified-runtime/phase9b3/test_candidate_identity_fail_closed.py
A docs/archaeology/unified-runtime/phase9b2/12-phase9b3-implementation-report.md
```

## Remaining Open

```text
O1 = OS verify -> bind mount 竞态：R8 保证应用层单一路径，但同权限写者在
     verify_at_mount 返回与内核 bind mount 之间仍可替换目录；UNKNOWN。
     R4（digest 命名不可变快照）缩小但不关闭。
O2 = b3_entry.json 在 harness state 目录，不在 R2 trust anchor 覆盖范围；
     本阶段显式声明为同写者信任边界（R2 在 Phase 9-B.4）。
```

新增 residual：

```text
1. 现有 gitignored pilot/state 是 Phase 9-B.1 之前的历史 legacy 状态：
   b3_entry.json 仍为旧格式且 registry entry 无 adoption 段。要跑新的 canonical
   B3 必须重新走 freeze -> evaluate -> issue -> promote（新状态），不能原地升级。
   由于已有 b3 run records，非 --force 的 phase_future("b3") 会跳过执行并保持
   HARNESS_LIVE_B3_PASS；--force 需要重建 canonical state。
2. R1 的 expected identity 来自同一 harness 写入的 b3_entry.json（O2）；同写者可
   同时改写 b3_entry 与 registry entry。应用层仍通过 authority/ledger/frozen
   锚定 actual identity，预期值本身的防篡改留给 R2。
3. Case B 的错误码与 Design Freeze 预测不同（UNISSUED_AUTHORITY 而非
   ENTRY_BINDING_MISMATCH）；REJECT 语义一致，已按代码事实记录。
```

## 最终验收映射

```text
Evaluation(A) -> Promotion(A) -> Authority(A) -> Adoption(A) -> Runtime(A)
  => 全链一致时 ALLOW（live harness 验证）
A -> B 在任何边界（evaluation/promotion/authority/registry/runtime）=> REJECT
same digest + different identity != same candidate（Case D 验证）
same name != same candidate（Case F 验证）
registry locator != security identity（R1 预期身份 + BINDING_KEYS 验证）
```
