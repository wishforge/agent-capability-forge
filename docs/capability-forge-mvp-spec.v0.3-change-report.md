# Capability Forge MVP Spec v0.3 — Change Report

## 1. Why v0.3

v0.2 把 “Verified Task Artifact” 当作 Capabilityizer 的现成输入，但三轮 code archaeology（Codex / Harbor ATIF / SWE-agent）证明：没有这样的现成对象。Codex 只有 rollout JSONL 中的 packet 文本、execution facts 片段与 unified diff；`result-review: approved` 是模型审查判断而非命令级验证。同时 v0.2 把 Trajectory、Artifact、Review、Verification、Evaluation、Replay、Candidate 的边界混在一起，导致 Capabilityizer 的输入契约无法冻结。v0.3 是一次证据驱动的边界修订：新增 Artifact Builder 与 VerifiedTaskArtifactBundle，重排 Review / VerificationEvidence，把 Replay 降级为 optional reference，并把 P0-P5 与 S0-S4 重新对齐。

## 2. Major Architecture Changes

v0.3 冻结以下流水线：

```text
Codex Runtime
  ↓
Artifact Builder
  ↓
VerifiedTaskArtifactBundle（immutable 输入边界）
  ↓
Capabilityizer（Bundle + workspace snapshot refs + user confirmation + LLM proposal）
  ↓
CapabilityCandidate
  ↓
Validator
  ↓
Evaluator
  ↓
Promotion
```

并显式分离七个对象：Trajectory ≠ ArtifactSet ≠ Review ≠ VerificationEvidence ≠ EvaluationResult ≠ ReplayConfig ≠ CapabilityCandidate。

## 3. Artifact Builder Boundary

Artifact Builder 是新增 Module，职责：解析 Codex rollout JSONL（packets / facts / identity）、获取 TurnDiff、turn 结束时捕获 runtime-only 数据、捕获最终 workspace snapshot / file references、捕获 verification evidence（能做则做）、计算 digest、原子写 Bundle。

Artifact Builder = Execution evidence reconstruction / capture；Capabilityizer = Capability extraction / transformation。Capabilityizer 不读取 live Codex session。

## 4. Bundle Boundary

VerifiedTaskArtifactBundle v0 结构：`schema_version / bundle_id / identity / execution / artifacts / review / verification_evidence / environment / replay_reference (optional) / provenance`，生成后 immutable。

Bundle 不允许：CapabilityCandidate、Capability Manifest、Promotion state、Evaluation Result、secrets、live workspace dependency、完整历史默认输入、无限 stdout/stderr。大对象一律 reference + digest（`artifacts.files[]` 含 path / status / digest / content_ref / media_type）。

## 5. Capabilityizer Boundary

Capabilityizer 输入：

- VerifiedTaskArtifactBundle
- immutable Workspace Snapshot / Artifact References
- User Confirmation
- LLM Proposal

Workspace Snapshot 是 Bundle 引用的 immutable artifact，不是 live dependency。禁止 Capabilityizer 访问原 Session、原 Agent Context、原 Workspace live path；Capabilityizer 在独立环境中完成。

## 6. Review vs Verification

Review：`worker_status`、`result_review_status`、`correction_owner`。

VerificationEvidence：`verification_command`、`exit_code`、`stdout/stderr reference`、`checker_result`、`evidence_digest`。

`result-review: approved` 只表示“模型 review 认可 Worker packet”，不等于 “Task verification PASS”。Codex 当前源码没有命令级 verification evidence，因此 VerificationEvidence 标记 `[OPEN QUESTION]`，不在文档中虚构。

## 7. P0-P5 Changes

| 阶段 | v0.2 | v0.3 |
|---|---|---|
| P0 | 无 | Artifact Contract：VerifiedTaskArtifactBundle v0 contract frozen |
| P1 | Capabilityization（输入假定为现成 artifact） | Artifact Builder + Capabilityizer：CapabilityCandidate Complete |
| P2 | Validator + Sandbox（S0 + S1） | Validator + Sandbox：S0 Independence + S1 Independent Validation |
| P3 | Registry + Persistence + Discovery（S2） | Evaluation：CapabilityEvaluation PASS |
| P4 | Runtime + Invoke（S3） | Registry + Persistence + Discovery：S2 |
| P5 | Revoke + E2E（S4） | Runtime + Invoke + Revoke + E2E：S3 + S4 |

## 8. S0-S4 Changes

- S0 Generalization / Independence → **S0 Independence**：Candidate 不依赖原 Task / Session / Agent Context / Workspace private state；Novel Input Test ≠ Statistical Generalization Proof，MVP 不声称统计泛化。
- S1 Independent Validation：Validator 可以 deterministic 地区分 valid / invalid candidate。
- S2 Persistent Discovery：Promoted capability 重启后仍可 discovery。
- S3 Independent Reuse：新 Task + 新 input 可以独立 invoke。
- S4 Revoke：revoke 后 discovery 和 invoke 都失败。

## 9. Remaining Open Questions

1. final file capture：最终文件全文的捕获点（Builder 运行期 vs workspace snapshot）。
2. verification evidence：Codex 无命令级证据；v0 定义是重跑验证命令还是捕获输出。
3. final phase authority：`run_phases` 状态机是唯一权威；Builder 需要 runtime 暴露最终 phase 状态。
4. secret scanning：facts 已脱敏，packet / diff 未脱敏；Bundle 写入前是否需要统一扫描。
5. replay：Codex 无 replay config；MVP 只保留 `replay_reference`。
6. reuse/generalization evidence：Novel Input Test 不构成统计泛化证明；跨任务复用需要 N 个 Bundle + evaluation。

另保留：容器运行时可用性、非确定性输出比较、discovery 匹配、`/forge` 集成面、promotion 确认形式。

## 10. Evidence Sources

- `research/codex-artifact/verified-task-artifact-archaeology.md`（yusing/codex @ `658630b`）
- `research/atif/harbor-atif-archaeology.md`（Harbor main @ `ac398bb`）
- `research/swe-agent/swe-agent-trajectory-archaeology.md`（SWE-agent v1.1.0 @ `3ea751c`）
- `research/artifact-boundary-comparison.md`

v0.2 的 DeepSeek Harness 证据不再使用（不在本轮证据宇宙内）。

---

## v0.3 是否已经可以进入 P0 implementation

**可以。** P0 的交付物本身就是 Bundle v0 契约（JSON schema、必填字段、immutable 规则、禁止字段、reference + digest 约定、gaps 记录），而不是 runtime 实现。Open Questions 1-6 正是 P0 需要解决的 targeted verification 项；P0 的退出条件是“契约冻结”，而不是“所有 OPEN 全部关闭”。只要 P0 把仍未解决的缺口以 `[OPEN QUESTION]` 显式写进契约的 `gaps`，P0 就可以开始。P1（Artifact Builder + Capabilityizer）必须等 P0 exit 后才能开始。
