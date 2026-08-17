# 62 — Protocol Contract Validation Plan（Phase 7.2）

> 阶段：Phase 7.2（Contract Validation；离线）。
> 基线：61（Core + Extension + Governance Invariants，Phase 7.1）、
> 57（Evaluation / Promotion Control Plane Synthesis）、
> 60（第二消费者验证报告，PARTIAL_REUSE）。
> 约束遵守：不修改 E.5–E.7.1、48/51/52/53、Phase 7 second-consumer
> artifacts；不做第三个 consumer / universal JSON Schema / API / DB /
> Kubernetes / production runtime / E.8 / production promotion；不运行
> live provider；不 commit / push。

## 1. 目的

把 61 定义的 Core + Consumer Extensions + Governance Invariants（G1–G7）
从“架构规则”验证为“可机械检查的协议契约”。

核心问题：

> 这些规则是否真的可以由机器机械检查，而不是靠人阅读文档？

每一条规则的分类：

```text
MACHINE_CHECKABLE        —— 由离线 validator + 测试证明（本阶段 FACT）
HUMAN_REVIEW_REQUIRED    —— 无法由快照机械判定
PARTIALLY_CHECKABLE      —— 部分条件可检查，其余需要人工
UNKNOWN                  —— 当前实现/证据无法确定
```

不为了得到 CONTRACT_VALID 而把无法证明的规则定义为 machine-checkable。

## 2. 复用基线

已有契约可复用，不重新造：

```text
FACT   57 §10–§13：provenance 链、evidence immutability、最小状态机
FACT   56a：registered/final policy 分离 + 字节级 provenance + 禁止覆盖
FACT   60：Core 跨两个消费者复用；extension 必须声明 applicability +
       provenance
FACT   61 §6–§8：G1–G7 + PROMOTE 必要条件 + 状态机转移规则
FACT   phase7/validate_second_consumer.py：离线 replay 工具与断言自检模式
```

本阶段不重写这些语义，只把它们表达成最小可执行 validator。

## 3. 最小 Conceptual Contract

每个 contract 只定义 required invariants / optional extension points /
forbidden states，不做大规模字段 schema：

| Contract | Required invariants（最小） | Extension points | Forbidden states |
| --- | --- | --- | --- |
| Candidate | 稳定身份；artifact hashes 记录；git_commit；基线/变更/dataset ref | consumer change metadata | 完成后改 hash；REJECTED 版本重提 |
| EvaluationRun | 唯一 run_id；candidate/policy ref；policy_version 绑定；recorded manifest hash；evidence refs | consumer run metadata | HOLD 重入复用 run_id；覆盖已完成 run |
| Attempt | attempt_id/run/case refs；prompt hash；raw/parsed/contract；failure_kind；artifact ref | consumer attempt metrics | 写入后改 raw |
| Evidence | evidence_id/run/case refs；outcome ref；prompt hash；policy_ref；recorded content hash | consumer outcome fields | 完成后改内容（G5）；改绑定的 run（G7） |
| Outcome | outcome_id；attempt/round ref；ACCEPT/REJECT；verdict 语义；contract vs transport 分离 | confidence、score、judge findings | Core 要求 extension 字段 |
| RegressionFinding | finding_id/case_id；baseline+candidate refs；delta；change class；evidence refs | score-level / verdict-level 判定标准 | 缺双侧证据却分类 |
| Attribution | attribution_id；evidence set refs；四类分类集；policy_ref | score-level 判定阈值 | 证据不足却归因 candidate |
| PromotionPolicy | policy_id/version；registered；frozen；content_hash；commit_ref | consumer 阈值/scope 值 | 未注册/未冻结用于 PROMOTE |
| PromotionGate | gate_id；policy_ref；evidence refs；precondition；rule results；blockers；decision | consumer rule 值 | 有 blocker 仍 PROMOTE |
| Decision | decision_id/type/value；policy_ref；evidence refs；reason；created_at；artifact ref | consumer reason 字段 | 无前置条件 PROMOTE；改写历史 decision |
| Provenance | provenance_id；registered policy bytes+hash+commit；evidence refs+hashes；fixed conditions；audit trail；recompute | consumer source refs | 不完整（G4）；retroactive rewrite |

## 4. G1–G7 检查设计

| Invariant | 机械检查方式 | 分类 |
| --- | --- | --- |
| G1 | decision.value == PROMOTE 时 policy 存在且 registered | MACHINE_CHECKABLE |
| G2 | 同上，policy.frozen == true | MACHINE_CHECKABLE |
| G3 | run.policy_version == policy.version（+ policy_ref 一致） | MACHINE_CHECKABLE |
| G4 | provenance.policy / evidence_manifest / run_ids / immutable_artifact_refs 齐全 | MACHINE_CHECKABLE |
| G5 | evidence recorded_hash vs current_hash；artifact hashes；manifest hashes | MACHINE_CHECKABLE（快照层；Git 不可变 ≠ 协议语义） |
| G6 | HOLD→EVALUATING 后必须出现不同 run_id 且 created_at 更新 | MACHINE_CHECKABLE |
| G7 | 重复 run_id / evidence_id / decision_id 内容不一致 → 覆盖 | MACHINE_CHECKABLE |

边界（报告必须写清）：

```text
- validator 检测“快照内的篡改”= recorded vs current hash 不一致；
- 它不证明 Git 是 immutable 存储；
- recorded hash 的信任锚点（写一次存储/签名）属于落地选择，本阶段
  只定义协议要求，UNKNOWN。
```

## 5. Validator 设计

新增单个文件：

```text
docs/archaeology/unified-runtime/phase7.2/validate_protocol_contract.py
```

输入：一个 JSON 形状的 protocol snapshot：

```text
policies / candidates / runs / evidence / provenance / decisions /
lifecycle / extensions
```

输出：violations 列表（code + invariant + message）+ verdict。

Failure semantics（不把所有错误叫 INVALID_OUTPUT）：

```text
CONTRACT_VIOLATION      结构引用 / G6 / gate 未过
GOVERNANCE_BLOCK        G1 / G2 / G3（PROMOTE 或 PROMOTABLE 前置缺失）
PROVENANCE_INCOMPLETE   G4
INVALID_TRANSITION      lifecycle 非法边 / REJECTED 非终态 / 无 PROMOTABLE
IMMUTABILITY_VIOLATION  G5 / G7
EXTENSION_SCHEMA_ERROR  extension 缺 applicability/provenance；
                        或 Core 要求 extension 字段
```

消息必须指出 invariant，例如 `RUN_POLICY_MISMATCH`、
`PROVENANCE_INCOMPLETE`。

Verdict 推导：

```text
无 violations 且无 extensions        -> CONTRACT_VALID
无 violations 且有 extensions        -> CONTRACT_VALID_WITH_EXTENSIONS
仅 extension schema violations       -> CONTRACT_PARTIAL
任何 core violation                 -> CONTRACT_INVALID
```

## 6. Offline Tests 设计

新增：

```text
docs/archaeology/unified-runtime/phase7.2/test_protocol_contract.py
```

覆盖矩阵：

```text
Governance    G1–G7（每个 invariant 至少一个违例 + 一个通过用例）
Lifecycle     非法转移 / HOLD 重入 / REJECTED 终态 / PROMOTABLE 前置 /
              PROMOTED 必须来自 PROMOTABLE
Core/Extension LLM Judge 无 confidence、swe-planner 无 judge findings
              均不失败 Core；extension 必须声明 applicability +
              provenance
Provenance    evidence hash / policy binding / run binding
Promotion     PROMOTE 需要全部前置条件
```

## 7. 验证命令

```text
python3 -m pytest docs/archaeology/unified-runtime/phase7.2 -q
python3 -m py_compile docs/archaeology/unified-runtime/phase7.2/validate_protocol_contract.py
```

不运行 live provider；不写 E.5–E.7.1 或 Phase 7 second-consumer artifacts。

## 8. 事实等级

```text
FACT      —— 离线测试本次实际运行通过（报告附输出）
INFERENCE —— 从 61/57/60 推导的设计判断
UNKNOWN   —— 未实现 / 无法由离线快照证明
```

“某 invariant 可以被实现检查”只有实际测试证据才能标 FACT。production
runtime 是否强制执行 = UNKNOWN（本阶段不接 runtime）。

## 9. 最终判定

只允许：

```text
CONTRACT_VALID
CONTRACT_VALID_WITH_EXTENSIONS
CONTRACT_PARTIAL
CONTRACT_INVALID
```

判定标准见报告 63；不为了好看选择 VALID。

## 10. Git 边界与停止条件

完成 Plan → Validator → Offline tests → Report → Final verdict 后 STOP。

不 commit、不 push、不 `git add .`。交付前输出：

```text
git status --short
git diff --stat
git diff --name-only
```

确保没有混入 `codex/`、`control-plane/`、`openhands/`、`48*`、`51*`、
`52*`、`53*`。
