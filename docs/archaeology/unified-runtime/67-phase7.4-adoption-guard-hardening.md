# 67 — Phase 7.4.1 Adoption Guard Contract Hardening

> 阶段：Phase 7.4.1（Adoption Guard 契约加固；offline only）。
> 基线：66（Phase 7.4）、65（Phase 7.3.1）、64（Phase 7.3）。
> 约束遵守：未修改 E.5–E.7.1、48/51/52/53、Phase 7 / 7.1 / 7.2 / 7.3
> 冻结文件；未接真实 Registry / Runtime / Langfuse；未做 write-once
> 存储；未做 E.8；未 commit / push。
> 本阶段只允许修改：66、本文件、phase7.4/validate_adoption_guard_design.py、
> phase7.4/test_adoption_guard_design.py。

## 1. Review Findings

```text
P1  artifact digest binding gap：
    原 validate_adoption_guard() 只要求 immutable_artifact_refs 非空，
    不验证 adoption / decision / run / candidate 的 artifact 身份一致；
    valid decision + different artifact 仍可能 adoption_allowed = true。
P2  fail-closed crash：
    decision.created_at 缺失时，stale 比较触发 TypeError，validator
    crash，不是 machine-readable ADOPTION_BLOCKED。
P3  离线测试缺口：
    RUN_MISSING / RUN_MISMATCH / POLICY_NOT_REGISTERED /
    RUN_POLICY_MISMATCH / DECISION_TAMPERED / EVIDENCE_TAMPERED /
    GATE_NOT_PASS / S4 stale 无真实 mutation 测试。
P4  文档不准确：
    discover() 行号写 64-76（实际 64-71）；
    S4 被描述为 Phase 7.4 新增（Phase 7.3 validator 已有）；
    66 未定义 artifact digest binding 与 missing timestamp 语义。
```

## 2. Artifact Digest Binding Fix

代码考古（字段名不凭空造）：

```text
FACT  pilot runtime 已有 artifact_digest（B3 invoke evidence，
      pilot/harness.py:732；run_record.py:103 校验）。
FACT  candidate manifest 已有 forged_artifact_digest
      （manifest.provenance，src/forge/capabilityizer.py:111）。
FACT  Phase 7.2/7.3 离线快照 candidate 只有
      recorded_artifact_hashes / current_artifact_hashes（dict），
      没有单值 digest。
FACT  Phase 7.4 离线 adoption / decision / run 没有 artifact digest
      字段，只有 refs + hash。
```

最小 contract extension（只扩展 Phase 7.4 离线快照，不改 Phase 7.2/7.3）：

```text
adoption.artifact_digest
decision.artifact_digest
run.artifact_digest
candidate.forged_artifact_digest（复用 capabilityizer 真实字段名）
```

正式规则：

```text
adoption.artifact_digest
== decision.artifact_digest
== run.artifact_digest
== candidate.forged_artifact_digest

任一缺失或不一致
  -> ARTIFACT_DIGEST_MISMATCH
  -> ADOPTION_BLOCKED
  -> adoptions_allowed = false
  -> 统一 blocked 语义 ADOPTION_GUARD_DESIGN_PARTIAL
```

`immutable_artifact_refs` 非空仍是 provenance 要求（G4），但不再足以
证明 artifact 身份；digest 一致性是独立的 artifact identity binding。

## 3. Fail-Closed Timestamp Fix

原行为：

```text
decision.created_at 缺失
  -> stale 比较 None < str
  -> TypeError
  -> validator crash
```

修复后：

```text
decision.created_at 缺失
  -> MISSING_DECISION_TIMESTAMP
  -> ADOPTION_BLOCKED
  -> adoptions_allowed = false
```

禁止：exception crash、implicit allow、fallback timestamp、
current time fallback。任何 invalid / incomplete adoption input 都必须
以 ADOPTION_BLOCKED 收尾。

## 4. Added Test Coverage

在 66 号报告 18 项测试之上新增 12 项（共 30 项）：

```text
RUN_MISSING                     missing run -> blocked
RUN_MISMATCH                    wrong run -> blocked
POLICY_NOT_REGISTERED           unregistered policy -> blocked
RUN_POLICY_MISMATCH             run/decision/request policy binding -> blocked
DECISION_TAMPERED               decision hash change -> blocked
EVIDENCE_TAMPERED               evidence hash change -> blocked
GATE_NOT_PASS                   gate_result != PASS -> blocked
S4 stale                        decision.created_at < candidate.created_at -> blocked
ARTIFACT_DIGEST_MISMATCH        different artifact digest -> blocked
MISSING_DECISION_TIMESTAMP      missing decision.created_at -> blocked
matching digests                all artifact digests match -> allowed
67 doc consistency              两个新 code 出现在 67 号报告
```

所有 blocked mutation 测试使用真实 snapshot mutation，并同时断言：

```text
adoptions_allowed == false
对应 reason code 存在
```

positive test 断言：

```text
all artifact digests match
  -> adoptions_allowed == true
  -> report["pass"] == true
```


## 5. Documentation Corrections

```text
1. pilot/registry.py discover() 行号
   64-76（错误）-> 64-71（实际代码范围，66 §2.1 / §12 两处）。
2. S4 stale rule 历史
   Phase 7.3 validator 已包含 decision.created_at < candidate.created_at；
   Phase 7.4 复用并强化（S2/S3 supersede 为 Phase 7.4 扩展）。
   不再声称 S4 是 Phase 7.4 新规则。
3. Artifact digest binding
   66 §7 新增正式 rule 14：ARTIFACT_DIGEST_MISMATCH，
   approval identity 必须与实际 adopted artifact identity 一致。
4. Missing timestamp
   66 §5 / §13 新增 MISSING_DECISION_TIMESTAMP -> ADOPTION_BLOCKED。
5. 14 项规则重新编号为 review 版本（decision exists / PROMOTE /
   candidate_id / candidate_version / run exists / run binding /
   policy registered / policy frozen / run-policy match /
   provenance / lifecycle / transition / stale+revoked / digest）。
```

## 6. Before / After Behavior

| 场景 | Before | After |
| --- | --- | --- |
| valid adoption + digests match | Allowed | Allowed（unchanged） |
| different artifact digest | Allowed（错误） | ADOPTION_BLOCKED / ARTIFACT_DIGEST_MISMATCH |
| missing decision.created_at | TypeError crash | ADOPTION_BLOCKED / MISSING_DECISION_TIMESTAMP |
| missing run | RUN_MISSING | RUN_MISSING（ADOPTION_BLOCKED） |
| wrong run | RUN_MISMATCH | RUN_MISMATCH（ADOPTION_BLOCKED） |
| unregistered / mismatched policy | blocked | blocked（unchanged） |
| stale / tampered / gate-not-pass | blocked | blocked（unchanged） |

所有非法情况 -> ADOPTION_BLOCKED；合法 adoption（PROMOTABLE +
valid transition + 全部 binding 一致，含 digest）-> adoptions_allowed
= true。

## 7. Why Verdict Remains ADOPTION_GUARD_DESIGN_VALID_WITH_UNKNOWN

```text
FACT      本次修复后，offline adoption guard contract 覆盖 14 项规则，
          可机械检查且 30 项测试通过。
FACT      Registry / Runtime / Langfuse 生产 enforcement 仍未接入，
          bypass 1-11 仍成立（66 §2 / §12）。
UNKNOWN   production enforcement（真实 Registry / Runtime /
          Langfuse 未接入，本阶段不接）。
```

不是 `ADOPTION_GUARD_DESIGN_PARTIAL`：本次是契约层 bug 修复，不是设计
缺口；offline 契约完整、可机械验证，缺的是落地层（66 §0 相同理由）。
不是 `ADOPTION_GUARD_DESIGN_VALID`：revocation / write-once / 真实
runtime 强制仍未实现。

## 8. FACT / INFERENCE / UNKNOWN（14 条规则审计）

| # | Rule | 状态 | 依据 |
| --- | --- | --- | --- |
| 1 | decision exists | FACT（offline）；UNKNOWN（production） | MISSING_DECISION；无生产消费端 |
| 2 | decision status == PROMOTE | FACT（offline）；UNKNOWN（production） | DECISION_NOT_PROMOTE；Phase 5-N 命名冲突 |
| 3 | candidate_id binding | FACT（offline）；UNKNOWN（production） | CANDIDATE_ID_MISMATCH（65 已修复） |
| 4 | candidate_version binding | FACT（offline）；UNKNOWN（production） | CANDIDATE_VERSION_MISMATCH |
| 5 | run exists | FACT（offline）；UNKNOWN（production） | RUN_MISSING |
| 6 | run candidate binding | FACT（offline）；UNKNOWN（production） | RUN_MISMATCH / CANDIDATE_ID_MISMATCH |
| 7 | policy registered | FACT（offline + E.7 evaluation）；UNKNOWN（registry/runtime） | POLICY_NOT_REGISTERED |
| 8 | policy frozen | FACT（offline + E.7 runner）；UNKNOWN（registry/runtime） | POLICY_NOT_FROZEN |
| 9 | run-policy match | FACT（offline）；INFERENCE（enforcement placement，66 §10） | RUN_POLICY_MISMATCH |
| 10 | provenance complete | FACT（offline）；UNKNOWN（production） | PROVENANCE_INCOMPLETE |
| 11 | lifecycle valid | FACT（offline）；UNKNOWN（production lifecycle 引擎缺失） | MISSING_LIFECYCLE / INVALID_LIFECYCLE |
| 12 | PROMOTABLE -> PROMOTED transition | FACT（offline）；UNKNOWN（production） | INVALID_LIFECYCLE |
| 13 | stale / revoked decision blocked | FACT（offline stale，Phase 7.3 已含 S4）；UNKNOWN（revocation 存储不存在） | STALE_DECISION / REVOKED_DECISION |
| 14 | artifact digest binding | FACT（offline，Phase 7.4.1 新增）；UNKNOWN（production） | ARTIFACT_DIGEST_MISMATCH |

总体：**生产 enforcement 仍然 UNKNOWN**；14 条规则的 offline
machine-checkability 是 FACT。

### 三态重新验证

```text
PROMOTE    = decision.value == "PROMOTE"（决策结果）
PROMOTABLE = lifecycle.status == "PROMOTABLE"（可被采用）
PROMOTED   = 系统已采用（registry / lifecycle promoted）

三者互不相等：
  decision.value == "PROMOTED" -> DECISION_NOT_PROMOTE（测试覆盖）
  lifecycle.status == "PROMOTED" 且无通过 guard 的 adoption
    -> PROMOTED_WITHOUT_DECISION（测试覆盖）

Adoption 只允许：
  PROMOTABLE
  + 有效 PROMOTABLE -> PROMOTED transition
  + 全部 binding 有效（candidate / version / run / policy /
    provenance / lifecycle / stale / digest）
  -> adoptions_allowed = true
其余 -> ADOPTION_BLOCKED
```

## 9. Validation Results

```text
pytest docs/archaeology/unified-runtime/phase7.4 -q
  -> 30 passed

pytest docs/archaeology/unified-runtime/phase7.2 \
       docs/archaeology/unified-runtime/phase7.3 \
       docs/archaeology/unified-runtime/phase7.4 -q
  -> 85 passed（29 + 26 + 30）

py_compile phase7.2 / phase7.3 / phase7.4 相关 .py
  -> COMPILE_OK
compileall -q phase7.2 phase7.3 phase7.4
  -> COMPILEALL_OK

documentation consistency
  -> PASS（66 列出全部 ADOPTION_BLOCKED codes；
     67 列出 ARTIFACT_DIGEST_MISMATCH / MISSING_DECISION_TIMESTAMP；
     test_hardening_doc_lists_new_codes 自动检查）
```

adversarial mutation 结果（真实 snapshot mutation，均
`adoptions_allowed == false` + `ADOPTION_BLOCKED`）：

```text
different artifact digest      -> ARTIFACT_DIGEST_MISMATCH
missing decision.created_at   -> MISSING_DECISION_TIMESTAMP
missing run                   -> RUN_MISSING
wrong run                     -> RUN_MISMATCH
wrong policy                  -> RUN_POLICY_MISMATCH
stale decision                -> STALE_DECISION
gate not pass                 -> GATE_NOT_PASS
tampered decision             -> DECISION_TAMPERED
tampered evidence             -> EVIDENCE_TAMPERED
```

合法 adoption（digests 全一致）-> `adoptions_allowed == true`。
被 blocked 的 snapshot 同时出现 `PROMOTED_WITHOUT_DECISION` 是预期行为：
registry_promoted 条目无法映射到通过 guard 的 adoption，state-only
trust 被禁止（66 §7）。

## 10. STOP

```text
no live runtime
no Registry integration
no Langfuse interception
no write-once storage
no E.8
no commit
no push
```
