# Repository Architecture V1 — Agent Capability Forge

- 阶段：Phase 8.6（Repository Architecture V1 Archaeology & Convergence）
- 日期：2026-08-18
- 范围：只读考古 + ownership 映射 + 依赖边界分析 + 目标目录设计 + 迁移计划
- 未执行：未移动/重命名/删除文件，未修改 `src/`、`pilot/`、`tests/`、`docs/archaeology/`、`research/`，未 commit / push
- 最终判定：**REPOSITORY_ARCHITECTURE_VALID_WITH_UNKNOWN**

---

## 1. Executive Summary

当前仓库已经具备一个清晰、基本正确的五层职责分离：

| 层 | 路径 | 角色 |
| --- | --- | --- |
| Production candidate（runtime-neutral core） | `src/forge/` | Bundle 生产、Capabilityizer、Validator、Evaluator、Sandbox、Codex Adapter |
| Pilot / Reference Implementation | `pilot/` | EXPERIMENT_ONLY harness + 实验资产 + Governance 原型 |
| Product tests | `tests/` | 最小单元测试（src + pilot 语义） |
| External Research / Experiments | `research/` | 外部项目考古报告、实验设计、control-plane-loop 独立实验 |
| Archaeology / Historical Evidence | `docs/archaeology/` | 各阶段设计报告 + 历史验证代码/测试 + 冻结评估 artifacts |

依赖方向的事实核验结果：

- `src/` 不 import `pilot` / `research` / `docs.archaeology`（`rg` 零命中）。
- `pilot/` 只 import `src/forge`（仅 `pilot/harness.py:35-38`），不 import research / archaeology。
- `docs/archaeology/` 反向 import `pilot`（29 条 import），这是 archaeology 验证代码对生产候选实现的校验，符合"archaeology 可以引用 production code"的不变量。
- `research/control-plane-loop/` 自包含（只依赖外部包 + 自身模块），不 import src / pilot / archaeology。
- `tests/` import `src` 与 `pilot`，符合"tests 可以依赖 production code"。

两个真实的结构问题（INFERENCE）：

1. **契约放错了层**：`research/artifact-contract/verified-task-artifact-bundle-v0.md` 是 FROZEN P0 产品契约，被 `src/forge/bundle_producer.py` 实现，却放在 `research/` 下。目标应归 `docs/contracts/`。
2. **pilot/ 混合了两种 ownership**：`pilot/harness.py` 等是 EXPERIMENT_ONLY；`pilot/adoption_authority.py`、`adoption_authority_producer.py`、`registry.py`、`runtime_adoption_guard.py` 是 production-candidate governance 原型。这是 Stage 3 迁移的核心对象。

目标结构沿用 `src/forge/{candidate,governance,registry,runtime,provenance,sources}` 候选，但基于代码事实做两处修正：

- `CapabilityCandidate` 未来归属 `src/forge/candidate/`（平台 Core Object，runtime-neutral）。
- `Source Adapter` 未来归属 `src/forge/sources/`（extension），当前唯一实现是 `src/forge/codex_adapter/`。

## 2. Current Repository Map

### 顶层

| 路径 | 内容 | 证据 |
| --- | --- | --- |
| `README.md` / `README.zh-CN.md` | 项目 README，各 374 行；状态 = Experimental / Research Engineering | README §11 Repository Structure |
| `docs/` | MVP spec（878 行）+ v0.2 backup + v0.3 change report + `archaeology/` | `docs/capability-forge-mvp-spec.md` |
| `src/` | 10 个 Python 文件（含 2 个 `__init__.py`），`forge` package | `find src -name '*.py'` |
| `pilot/` | 13 个 Python 文件（不含 state）+ manifest/config/fixtures/skills/oracles + `state/`（58MB，gitignored） | `find pilot -name '*.py' -not -path '*/state/*'` |
| `tests/` | 1 个 Python 文件（`test_minimal.py`，200 行） | `tests/test_minimal.py` |
| `research/` | 外部考古 md、artifact contract、experiments、control-plane-loop（11 py + data 9.4MB + .venv 303MB） | `find research -name '*.py' -not -path '*/.venv/*'` |
| `docs/archaeology/` | 88 个 Python 文件 + 大量阶段报告 md + 3 个 archaeology tests 目录 | `find docs/archaeology -name '*.py'` |

### `src/forge/`

| 文件 | 行数 | 模块职责（docstring 证据） |
| --- | --- | --- |
| `__init__.py` | 1 | "Runtime-neutral Forge experimental slice (P1/P2/P3 seeds)" |
| `bundle_producer.py` | 455 | M5 VerifiedTaskArtifactBundle v0 producer + validator；docstring 声明实现 frozen P0 contract `research/artifact-contract/verified-task-artifact-bundle-v0.md` |
| `capabilityizer.py` | 121 | M8 Bundle + LLM Proposal + confirm → Candidate；runtime-neutral；静态扫描任务私有状态 |
| `validator.py` | 97 | M9 deterministic validation（P2 seed） |
| `evaluator.py` | 69 | M9 minimal evaluation（P3 seed）；`PROMOTION_RULE` = golden 100% + novel 100% + regression PASS + independent reuse PASS → eligible，promote 需 operator confirm |
| `sandbox.py` | 46 | M13 Docker sandbox launcher；fail-closed（无 daemon 即异常），`--network none` |
| `codex_adapter/__init__.py` | 1 | "the only module that parses Codex native format" |
| `codex_adapter/main.py` | 188 | CLI `python -m forge.codex_adapter.main build\|metrics`；build = rollout + workspace + run-meta → sealed Bundle |
| `codex_adapter/rollout_parser.py` | 167 | 解析 rollout JSONL → normalized identity/execution/review/environment/metrics |
| `codex_adapter/metrics.py` | 11 | runtime metrics（harness/cost 永不解析 rollout） |

### `pilot/`

| 文件 | 行数 | 模块职责（docstring 证据） |
| --- | --- | --- |
| `__init__.py` | 1 | "F+ rehearsal — EXPERIMENT_ONLY orchestration layer (M1/M2/M6/M7/M10/M11/M12)" |
| `harness.py` | 928 | M1 Experiment Harness，EXPERIMENT_ONLY；唯一真实执行路径 `phase_future("b3")`：`runtime_guard.adopt()` → `verify_at_mount()` → `docker_launch()` |
| `adoption_authority.py` | 723 | Phase 8 minimal production AdoptionAuthority contract adapter；fail-closed；自包含（"production runtime never imports docs/archaeology"） |
| `adoption_authority_producer.py` | 303 | Phase 8.1 authority 签发：decision → persistent authority |
| `runtime_adoption_guard.py` | 434 | Phase 8.2 Runtime Adoption Guard（激活前二次校验） |
| `registry.py` | 203 | M10 experimental registry，EXPERIMENT_ONLY；`promote()` 要求 AdoptionAuthority + store + anchor + ledger |
| `run_record.py` | 107 | M11 run_record_v1 writer + treatment attribution validation |
| `cost.py` | 92 | M12 cost collector + NV / V-delta sensitivity |
| `generate.py` | 79 | M7 B2/B3 共享 LLM proposal generation |
| `oracles/check.py` | 47 | M3 deterministic F+ oracle |
| `manifest.json` / `config.json` | — | F+ task manifest（V/delta/oracle/fixtures）+ pilot config（model/limits/sandbox/prices） |
| `fixtures/`, `skills/` | — | F+ 输入/期望、B1/B2 frozen skills |
| `state/` | 58MB（gitignored） | 4 个 sealed bundles、10 条 run records、F+ rehearsal gate PASS、registry entry、cost/NV |

### `tests/`

`tests/test_minimal.py`：11 个 unittest，覆盖：

- `src/forge/bundle_producer`（seal/validate/tamper detection）
- `src/forge/capabilityizer`（任务私有路径拒绝）
- `pilot/cost`（NV 算术）
- `pilot/run_record`（treatment attribution B0/B1/B2/B3）
- `pilot/oracles/check`（golden PASS / tampered FAIL）

### `docs/archaeology/`

- `codex/`、`control-plane/`、`openhands/`、`deepseek-harness/`、`python-cordis/`、`unified-runtime/`：阶段报告 + 支撑代码。
- 88 个 py：deepseek-harness 54、unified-runtime 23、python-cordis 11。
- 3 个 archaeology tests 目录：deepseek-harness/evaluation/tests（17）、deepseek-harness/runtime/tests（9）、python-cordis/kernel/tests（4）。
- `unified-runtime/phase7.2-8.5/`：contract / enforcement / adoption / integrity 验证脚本；Phase 8.5 报告（78）声明 Phase 7.2–8.4.3 回归 240 passed。
- 注意：git status 显示 `docs/archaeology/codex/`、`control-plane/`、`deepseek-harness/`、`openhands/`、`unified-runtime/48/51/52/53` 等为 untracked（未提交工作树材料）。

### `research/`

| 路径 | 内容 | 角色 |
| --- | --- | --- |
| `codex-artifact/`、`atif/`、`swe-agent/`、`codex-runtime-capture/`、`deepseek/`、`source-baseline.md` | 外部项目源码考古（Codex / Harbor ATIF / SWE-agent / DeepSeek Harness） | External research |
| `artifact-boundary-comparison.md` | 三项目 artifact boundary 对比 → P0 契约输入 | External research（契约推导） |
| `artifact-contract/` | `verified-task-artifact-bundle-v0.md`（FROZEN P0） | **产品契约（放错层）** |
| `experiments/` | `capability-forge-vs-skill.md`（FROZEN 实验设计）、`pilot-architecture.md`、`pilot-minimal-implementation-design.md`、`experiment-readiness.md`、`formal-pilot-gate-review.md` | 实验设计与评审 |
| `control-plane-loop/` | 11 py + requirements.txt + data/ + .venv/；自带 2 个测试文件；独立实验（judge variance、gate calibration、S7.2 experiments） | 独立实验（自包含） |

## 3. Product vs Pilot vs Research vs Archaeology

判定规则：

| 类别 | 定义 | 判定规则 |
| --- | --- | --- |
| Product Code | 未来用户真正调用的稳定代码 | 被 runtime entrypoint 调用 / 被 `tests/` 覆盖 / 不标 EXPERIMENT_ONLY / 不依赖 archaeology、research、pilot |
| Pilot / Reference Implementation | 当前实验、验证、原型实现 | docstring 标 EXPERIMENT_ONLY 或 M1-M13 实验模块 / 消费 src 产出实验 state / 只服务于实验 |
| Archaeology / Historical Evidence | 记录"为什么这么设计"和代码事实 | 位于 `docs/archaeology/`；报告 + 支撑验证脚本/测试；可引用 production code |
| External Research / Experiments | 研究外部项目、实验、数据 | 位于 `research/`；描述外部项目源码事实，或运行独立实验 |
| UNKNOWN | 无法确定 | 标注 UNKNOWN，不猜 |

逐目录判定（FACT）：

| 路径 | 类别 |
| --- | --- |
| `src/forge/bundle_producer.py` | Product Code（production candidate） |
| `src/forge/capabilityizer.py` | Product Code（production candidate） |
| `src/forge/validator.py` | Product Code（production candidate） |
| `src/forge/evaluator.py` | Product Code（production candidate） |
| `src/forge/sandbox.py` | Product Code（production candidate） |
| `src/forge/codex_adapter/*` | Product Code（source adapter；runtime-specific 边界） |
| `pilot/harness.py` | Pilot（EXPERIMENT_ONLY） |
| `pilot/generate.py` / `cost.py` / `run_record.py` / `oracles/` / `fixtures/` / `skills/` / `manifest.json` / `config.json` | Pilot |
| `pilot/adoption_authority.py` / `adoption_authority_producer.py` / `registry.py` / `runtime_adoption_guard.py` | Pilot（当前）/ production-candidate governance（目标） |
| `pilot/state/` | Pilot 冻结评估证据（gitignored，不动） |
| `tests/test_minimal.py` | Product tests |
| `docs/archaeology/*` | Archaeology（含 archaeology validation code/tests） |
| `research/*` 外部考古 md | External Research |
| `research/artifact-contract/*` | Contract（FROZEN P0；当前放错层） |
| `research/experiments/*` | Experiments / Design |
| `research/control-plane-loop/` | Experiments（自包含代码 + 数据 + 测试） |

## 4. src/ vs pilot/

### SRC_ROLE

**production candidate / reusable library（runtime-neutral core seeds）**。

FACT：

- `src/forge/__init__.py` 自述 "Runtime-neutral Forge experimental slice (P1/P2/P3 seeds)"。
- `src/` 全部 import 为 stdlib + 包内模块；`rg '^\s*(from|import)\s+(pilot|research|archaeology|docs)' src` 零命中。
- 唯一 CLI entrypoint：`src/forge/codex_adapter/main.py`（`python -m forge.codex_adapter.main build|metrics`）。
- `tests/test_minimal.py` 直接验证 `forge.bundle_producer` / `forge.capabilityizer`。
- 没有 `pyproject.toml` / `setup.py`；`src` 未安装为 package，import 依赖 sys.path 插入（`pilot/harness.py:33-34`、`tests/test_minimal.py:16-17`、`codex_adapter/main.py:17`）。

INFERENCE：

- `src/` 是当前 repo 中唯一 runtime-neutral 的实现层，是未来 product core 的种子；但不是 authoritative product（无 packaging、无正式集成测试、模块 docstring 自称 experimental slice）。

### PILOT_ROLE

**experimental implementation（实验编排 + governance 原型 + 实验资产）**。

FACT：

- `pilot/__init__.py` 自述 "F+ rehearsal — EXPERIMENT_ONLY orchestration layer"。
- `pilot/harness.py:35-38` 是 pilot → src 的唯一 import 点（sandbox / capabilityizer / validator / evaluator）。
- `pilot/registry.py` docstring：experimental registry，flat two-state dir，无 SQLite / 多版本 / revoke，"P4/P5 implement the production registry later"。
- `pilot/adoption_authority.py` docstring：minimal production AdoptionAuthority contract adapter，自包含。
- `pilot/state/` 含 F+ rehearsal 结果（gate PASS、4 bundles、10 run records、1 promoted capability）。

INFERENCE：

- `pilot/` 不是 authoritative implementation；其中 4 个 governance 模块是 production-candidate 原型，因实验进度暂时留在 pilot。
- "authoritative implementation" 目前不存在（整个项目处于 experimental / research engineering 状态，README 明示）。

## 5. tests/ ownership

当前测试分布（FACT）：

| 测试 | 位置 | 归属 | 验证的语义 |
| --- | --- | --- | --- |
| `test_minimal.py`（11 cases） | `tests/` | src + pilot | Bundle 密封/防篡改、Capabilityizer 私有状态拒绝、NV 算术、treatment attribution、oracle |
| F+ Rehearsal Gate（proofs 1-9） | `pilot/state/fplus_rehearsal_gate.json` | pilot | 实验 e2e：formation/bundle/shared input/skill/candidate/validation/evaluation/promotion/invoke/cost |
| Treatment Attribution Gate | `pilot/state/treatment_attribution_gate.json` | pilot | B1/B2/B3 复用治疗归属 |
| archaeology tests（30 files） | `docs/archaeology/{deepseek-harness,unified-runtime,python-cordis}/**/tests` | docs/archaeology | archaeology 契约/阶段回归（phase7.2-8.5；78 报告：240 passed） |
| `test_evaluation_result.py` / `test_gate_calibration.py` | `research/control-plane-loop/` | research | 独立实验回归 |

目标 ownership：

| 测试类别 | 目标位置 |
| --- | --- |
| product unit / integration（src + 迁移后的 governance/registry/runtime） | `tests/` |
| pilot integration / e2e（rehearsal gates） | `pilot/`（保持实验编排与 gate 同层） |
| archaeology validation / phase regression | `docs/archaeology/<phase>/tests`（与历史证据同层，不拆） |
| experiment regression | `research/experiments/...`（随实验代码） |
| security hardening | governance 代码迁移后随代码进入 `tests/`；archaeology 保留历史副本 |

不移动现有测试。

## 6. docs/ ownership

当前 docs/ 混合内容（FACT）：

| 文件 | 当前类别 | 目标类别 |
| --- | --- | --- |
| `docs/capability-forge-mvp-spec.md`（v0.3） | product MVP spec（含 architecture 内容） | `docs/product/` |
| `docs/capability-forge-mvp-spec.v0.2-backup.md` / `.v0.3-change-report.md` | 历史版本 | `docs/archaeology/`（历史证据）或 `docs/product/history/` |
| `docs/archaeology/` | 设计/考古报告 + 验证代码 | `docs/archaeology/`（保持） |
| `research/artifact-contract/verified-task-artifact-bundle-v0.md` | FROZEN P0 产品契约（放错层） | `docs/contracts/` |
| 本文件 | architecture | `docs/architecture/` |

目标设计：

```text
docs/
├── product/          # 用户可读 + MVP spec
├── architecture/     # ADR、repository structure、依赖边界
├── contracts/        # FROZEN 契约（Bundle v0、promotion rule、run record schema）
└── archaeology/      # 历史证据 + 验证（保持现状）
```

不执行迁移。

## 7. research/ ownership

当前 research/ 分类（FACT）：

| 当前路径 | 内容 | 目标路径 |
| --- | --- | --- |
| `codex-artifact/`、`atif/`、`swe-agent/`、`codex-runtime-capture/`、`deepseek/`、`source-baseline.md`、`artifact-boundary-comparison.md` | 外部项目考古 | `research/external/` |
| `experiments/` | 实验设计 / readiness / gate review | `research/experiments/`（已正确） |
| `control-plane-loop/` | 独立实验（代码 + data + .venv + tests） | `research/experiments/control-plane-loop/` |
| `artifact-contract/` | FROZEN P0 产品契约 | `docs/contracts/` |

目标设计：

```text
research/
├── external/        # 外部项目考古报告
├── experiments/     # 实验设计 + 实验代码/数据
└── evaluations/     # 未来正式评估平台/评估运行（当前无独立 owner）
```

不执行迁移；`research/control-plane-loop/data/` 与 `.venv/` 已 gitignored，属实验数据。

## 8. CapabilityCandidate ownership

判定：**`src/forge/candidate/`**。

FACT：

- MVP spec §6.1 把 CapabilityCandidate 定义为第七个分离对象（`[NEW DESIGN]`），永远在 Bundle 之外。
- `src/forge/capabilityizer.py` 当前产出 `candidate.json` + `manifest.json` + implementation + tests 的候选目录（`capabilityize()`）。
- `src/forge/validator.py` / `evaluator.py` 消费 Candidate 目录。
- Phase 7.1（docs/archaeology/unified-runtime/61）把 Candidate 列为 Core protocol 对象（两消费者验证）。
- `capabilityizer.py` 只 import `bundle_producer` 的 digest helpers，不依赖任何 source-specific 模块。

理由（INFERENCE）：

- 不选 `src/candidate/`：平台包名已统一为 `forge`，顶层再加 package 会分裂命名空间。
- 不选 `src/forge/contracts/`：contracts 是类型/接口；Candidate 是带实现 + tests 的 Core Object，需要自己的 package。
- 不变量：Candidate 定义不得依赖 GitHub / GitLab / OCI / Claude / Cordis；当前 `capabilityizer.py` 已满足。

当前实现文件（`src/forge/capabilityizer.py`）未来属于 `src/forge/candidate/`；Phase 9 新建 package，不做大爆炸迁移。

## 9. Source Adapter ownership

判定：**`src/forge/sources/`**，当前唯一实现 `src/forge/codex_adapter/` 是 sources 的第一个实例。

FACT：

- `src/forge/codex_adapter/__init__.py`："the only module that parses Codex native format"。
- `codex_adapter/main.py` 是唯一 CLI entrypoint（build / metrics）。
- `codex_adapter/metrics.py` 自述："kept separate so harness/cost never parse rollouts"。
- README §4 Option B：runtime-specific logic stops at the Adapter boundary；Bundle 是 runtime/forge 唯一 API boundary。

架构不变量（本文件必须遵守）：

- Source 是 extension；每个来源（git / OCI / agent output / marketplace / artifact registry / local / external）一个 adapter 目录。
- Evaluation / Promotion / Registry / Runtime 不得感知具体 Source 类型；它们只依赖统一对象与 provenance。

需要 Phase 9 裁决的语义 gap（UNKNOWN/OPEN QUESTION）：

- 现有冻结边界：Runtime Adapter 输出 `VerifiedTaskArtifactBundle`（research/artifact-contract + pilot-architecture §9 invariant 2）。
- 本阶段目标表述：Source Adapter 输出统一 `CapabilityCandidate`。
- 建议：保留 Bundle 作为 sealed 输入边界，Source Adapter 输出 Bundle，经 Capabilityizer 产出 Candidate；"统一对象"指下游只依赖 Candidate，不依赖 source 类型。此裁决不改变本文件 ownership。

Runtime 执行 adapter（Docker 等）不属于 sources；未来归 `src/forge/runtime/`。

## 10. Governance ownership

判定：**`src/forge/governance/`**。

FACT：

- `pilot/adoption_authority.py`：minimal production AdoptionAuthority contract adapter；fail-closed；AUTHORITY_FIELDS / BINDING_KEYS / integrity anchor / write-once ledger。
- `pilot/adoption_authority_producer.py`：issuer（confirm + evaluation + decision + digest + ledger）。
- `pilot/runtime_adoption_guard.py`：Runtime Guard（state / authority / binding / digest / lifecycle / policy / provenance / revocation / staleness）。
- `pilot/registry.py`：Registry Guard（promote 前置 authority + store + anchor + ledger）。
- Phase 8.5（78）把 Platform Governance 定义为 Layer 1；`docs/archaeology/unified-runtime/phase8.x` 提供验证。

INFERENCE：

- Governance 是 Core，不是 extension：Promotion Gate、AdoptionAuthority、Fail Closed、Artifact Binding、Provenance 语义必须由平台实现。
- Governance 不得依赖 source-specific adapter；当前 pilot governance 模块只依赖 pilot 内部 + 文件系统，满足。

## 11. Registry ownership

判定：**`src/forge/registry/`**。

FACT：

- `pilot/registry.py`：experimental registry（flat two-state dir），docstring 明示 P4/P5 才实现 production registry。
- `pilot/registry.py:57-106` `promote()`：adoption_authority 缺失 / store 缺失 / anchor 不一致 / binding mismatch / ledger 缺失 → `ADOPTION_BLOCKED`。
- 78 §2.2：governance store = `adoption_store.json` + `authorities/<id>.json`（write-once）+ events + external integrity anchor。

INFERENCE：

- Registry 依赖 Governance（authority 校验），Governance 不依赖 Registry。
- Registry Guard（promote 时强制 authority）是 Governance invariant 在 registry 边界的执行点，随 Registry 迁移到 `src/forge/registry/`。

## 12. Runtime ownership

判定：**`src/forge/runtime/`**。

FACT：

- `src/forge/sandbox.py`：确定性 Docker launcher，fail-closed，`--network none`；已是 runtime-neutral。
- 唯一真实激活路径：`pilot/harness.py` `phase_future("b3")`：`runtime_guard.adopt()` → `runtime_guard.verify_at_mount()` → `docker_launch()`（78 §2.1）。
- `pilot/runtime_adoption_guard.py`：激活前二次校验。

INFERENCE：

- Runtime 消费 Registry/Governance 的裁决结果，不感知 source 类型，不 import archaeology/research。
- 未来 runtime adapters（Docker / local / remote）在 `src/forge/runtime/` 下以 adapter 形式扩展；sandbox 是共享底层。

## 13. Dependency Direction

### 目标依赖

```text
sources
    ↓
candidate
    ↓
governance
    ↓
registry
    ↓
runtime adapters
```

附加不变量：

- governance 不依赖 source-specific adapter。
- runtime 不依赖 archaeology。
- production code 不依赖 research。
- tests 可以依赖 production code。
- archaeology 可以引用 production code，但 production code 不得 import archaeology。

### 实际依赖（import-level，FACT）

| 边 | 是否存在 | 证据 | 目标一致性 |
| --- | --- | --- | --- |
| src → pilot / research / archaeology / docs | 否 | `rg` src 零命中 | 一致 |
| pilot → src/forge | 是 | `pilot/harness.py:35-38` | 一致（pilot 消费 product core） |
| pilot → research / archaeology | 否 | `rg` pilot 零命中 | 一致 |
| archaeology → pilot | 是（29 条 import） | `docs/archaeology/unified-runtime/phase8*/test_*.py` | 一致（archaeology 验证允许） |
| archaeology → research data | 是 | `phase7/validate_second_consumer.py` 读 `research/control-plane-loop/data` | 一致（证据引用） |
| research → src / pilot / archaeology | 否 | `rg` research（排除 .venv）零命中 | 一致 |
| tests → src + pilot | 是 | `tests/test_minimal.py:16-19` | 一致 |
| src → research 契约（文档引用，非 import） | 是 | `bundle_producer.py` docstring 引用 `research/artifact-contract/...` | 不一致（契约应归 docs/contracts） |

结论：代码级依赖方向已与目标一致；唯一"概念依赖"是 P0 契约文件位于 research/，属文档层问题。

## 14. Core / Extension / Governance Invariants

### Core（平台必带，位于 src/forge core）

- CapabilityCandidate（`src/forge/candidate/`）
- Capability lifecycle（candidate → validated → evaluated → promoted → revoked；当前状态机证据：`pilot/registry.py` + `pilot/adoption_authority.py`）
- Governance contracts（PromotionGate / AdoptionAuthority / policy registration → `src/forge/governance/`）
- Provenance / digest / artifact binding（→ `src/forge/provenance/` + `bundle_producer` digest primitives）

### Extension（可选，按来源/交付/运行时扩展）

- GitHub / GitLab / OCI / Agent / Marketplace / Artifact Registry / local / external source adapters（→ `src/forge/sources/`）
- Skill / Plugin / MCP / Tool / Workflow（交付机制，不是 Core Object）
- Runtime adapters（→ `src/forge/runtime/`）

### Governance Invariants（现有代码已实现，映射如下）

| Invariant | 现有证据 | 未来归属 |
| --- | --- | --- |
| Promotion Gate | `src/forge/evaluator.py` `PROMOTION_RULE`；`adoption_authority_producer.py` 要求 confirm | governance + candidate |
| AdoptionAuthority | `adoption_authority.py`（deterministic id、ledger、anchor） | governance |
| Registry Guard | `pilot/registry.py:57-106` | registry + governance |
| Runtime Guard | `pilot/runtime_adoption_guard.py` | runtime + governance |
| Fail Closed | 任何缺失/篡改 → ADOPTION_BLOCKED，状态不变 | governance（横切） |
| Artifact Binding | `BINDING_KEYS`（candidate/version/decision/evaluation/policy/digest/provenance） | governance + provenance |
| Provenance | `PROVENANCE_KEYS`（policy、evidence_manifest、run_ids、immutable_artifact_refs） | provenance |

本文件不产生新的 runtime semantics。

## 15. Target Repository Structure

```text
agent-capability-forge/
├── README.md
├── README.zh-CN.md
├── src/
│   └── forge/
│       ├── candidate/        # CapabilityCandidate + capabilityizer（Core Object）
│       ├── governance/       # AdoptionAuthority / PromotionGate / policy / guards
│       ├── registry/         # production registry（promote/discover/revoke）
│       ├── runtime/          # runtime adapters + sandbox
│       ├── provenance/       # digest / binding / attestation primitives
│       └── sources/          # source adapters（codex 第一个；git/OCI/agent/... 扩展）
├── pilot/                    # 实验编排 + 实验资产（Stage 3 后仅剩 EXPERIMENT_ONLY）
├── tests/                    # product unit/integration
├── docs/
│   ├── product/
│   ├── architecture/
│   ├── contracts/
│   └── archaeology/
└── research/
    ├── external/
    ├── experiments/
    └── evaluations/
```

当前 → 目标映射（仅设计，不执行）：

| 当前 | 目标 |
| --- | --- |
| `src/forge/bundle_producer.py` | `src/forge/provenance/`（digest/seal）或保留 core |
| `src/forge/capabilityizer.py` | `src/forge/candidate/` |
| `src/forge/validator.py` / `evaluator.py` | `src/forge/candidate/`（或 evaluation 层） |
| `src/forge/sandbox.py` | `src/forge/runtime/` |
| `src/forge/codex_adapter/` | `src/forge/sources/codex/` |
| `pilot/adoption_authority*.py` | `src/forge/governance/` |
| `pilot/registry.py` | `src/forge/registry/` |
| `pilot/runtime_adoption_guard.py` | `src/forge/runtime/`（guard）+ `src/forge/governance/`（语义） |
| `pilot/harness.py` / `generate.py` / `cost.py` / `run_record.py` / `oracles/` / `fixtures/` / `skills/` | 留在 `pilot/` |
| `pilot/state/` | 留在 `pilot/state/`（gitignored 冻结证据） |
| `research/artifact-contract/` | `docs/contracts/` |
| `research/control-plane-loop/` | `research/experiments/control-plane-loop/` |
| `research/*-archaeology.md` 等外部考古 | `research/external/` |
| `docs/capability-forge-mvp-spec*.md` | `docs/product/`（backup → archaeology/history） |

不要求目标目录当前存在；本文件只锁定架构规则。

## 16. Migration Strategy

### Stage 1 — Documentation only（当前阶段）

- 发布本文件与验证脚本（`docs/architecture/`）。
- 后续文档更新：新 ADR 进 `docs/architecture/`，新契约进 `docs/contracts/`，新产品文档进 `docs/product/`。
- 不移动任何现有文件；契约路径问题用引用/别名解决，不切文件。

### Stage 2 — New code follows target structure

- 新模块直接写进 `src/forge/{candidate,governance,registry,runtime,provenance,sources}`。
- 新测试进 `tests/`（product）或随 archaeology 阶段目录（历史验证）。
- 新研究/实验进 `research/{external,experiments,evaluations}`。
- 旧路径不再新增生产代码。

### Stage 3 — Legacy pilot migration

- 逐个模块迁移 production-candidate governance：`adoption_authority.py` → `src/forge/governance/`，`registry.py` → `src/forge/registry/`，`runtime_adoption_guard.py` → `src/forge/runtime/` + governance。
- 每个模块迁移时同步迁移其 tests；`docs/archaeology/phase8.x` 中 import pilot 的 archaeology 测试保留为历史副本，并在迁移后指向新路径（或注明迁移 commit）。
- `harness.py` / `generate.py` / `cost.py` / `run_record.py` / `oracles/` / `fixtures/` / `skills/` 留在 `pilot/`（实验层）。
- 新 production registry 落地后，实验 registry（pilot/registry.py 的 flat JSON）退役。

### 不应该动

- Phase 7–8.5 历史 archaeology（`docs/archaeology/unified-runtime/*` 等）。
- 冻结评估 artifacts（`pilot/state/`、`docs/archaeology/**/evaluation/artifacts/`、`research/control-plane-loop/data/`）。
- 已发布 commit history；`docs/archaeology/` 中 untracked 材料先补齐版本记录，不做内容迁移。
- 避免大爆炸迁移：pilot + src 不同时移动；每个包迁移必须带测试。

## 17. FACT / INFERENCE / UNKNOWN

### FACT

- `src/` 不 import pilot / research / archaeology / docs。
- `pilot/harness.py:35-38` import `forge.sandbox` / `capabilityizer` / `validator` / `evaluator`；pilot 不 import research / archaeology。
- `docs/archaeology/` 有 29 条 import 指向 pilot（phase8.x 验证代码）。
- `research/control-plane-loop/` 不 import src / pilot / archaeology（排除 .venv）。
- `tests/test_minimal.py` 覆盖 src + pilot。
- `src/forge/codex_adapter/` 是唯一解析 Codex native format 的模块。
- `src/forge/bundle_producer.py` docstring 声明实现 `research/artifact-contract/verified-task-artifact-bundle-v0.md`（FROZEN P0）。
- `pilot/adoption_authority.py`、`adoption_authority_producer.py`、`registry.py`、`runtime_adoption_guard.py` 自称 production-candidate 或 EXPERIMENT_ONLY（见各 docstring）。
- 无 `pyproject.toml` / `setup.py`；src 未安装为 package。
- `pilot/state/`、`research/control-plane-loop/data/`、`.venv/` 已 gitignored。
- git status 显示 `docs/archaeology/codex/`、`control-plane/`、`deepseek-harness/`、`openhands/`、`unified-runtime/48/51/52/53` 等为 untracked。

### INFERENCE

- `src/` = production candidate / reusable library；`pilot/` = experimental implementation；当前不存在 authoritative product。
- `pilot/` 中的 governance 模块是 Stage 3 迁移对象；harness 等是实验层，永不进 src。
- P0 契约应归 `docs/contracts/`；外部考古报告应归 `research/external/`；control-plane-loop 应归 `research/experiments/`。
- Phase 9 可先建 `src/forge/candidate/` 与 `src/forge/sources/`，不需要先迁移 pilot。

### UNKNOWN

- Source Adapter 的对外统一对象到底是 Bundle（现有冻结边界）还是 Candidate（本阶段表述）——需 Phase 9 裁决。
- src 的 packaging / install 方式（无 pyproject）——生产化前必须决定。
- `docs/archaeology/` 中 untracked 材料的版本状态——补齐 git 记录前，历史 provenance 不完整。
- Formal Pilot 参数（temperature / seed / pricing / F− / F0 fixtures）——实验状态，不影响架构判定。
- 生产 registry 的具体存储（SQLite / 其他）与 revoke API——Phase 9+ 设计。

## 18. Open Questions

1. Source Adapter 输出契约：保持 Bundle（frozen）还是直接输出 CapabilityCandidate？建议保留 Bundle 中间边界。
2. `src/forge/bundle_producer.py` 拆到 `provenance/` 还是保持 core 单模块？拆分会改变 import 图，需在 Phase 9 第一个 package 落地时裁决。
3. `validator.py` / `evaluator.py` 属于 candidate 生命周期还是独立 evaluation 层（`research/evaluations/` 是评估平台，`src/forge/evaluator` 是 candidate 评估）？
4. `docs/archaeology/` 中大量 untracked 文件何时补提交？是否影响"历史证据"可信度。
5. pilot/state 中 58MB 实验证据的长期保留策略（gitignored 本地证据 vs 归档）。

## 19. Phase 9 Readiness

Phase 9 可以在不大规模重构的前提下开始：

- **可以开始**：新建 `src/forge/candidate/`（CapabilityCandidate Core Object）与 `src/forge/sources/`（Source Adapter 扩展点），因为当前 `src/` 已 runtime-neutral、无反向依赖。
- **前置裁决**：Source Adapter 输出契约（Bundle vs Candidate）。
- **前置决策**：src packaging（pyproject）与 import 边界从 sys.path 改为正式 package。
- **不动**：pilot harness、docs/archaeology、research、frozen evaluation artifacts。
- **与 Formal Pilot 的关系**：Formal Pilot NOT READY（参数未冻结）不影响 Phase 9 架构起步；架构工作独立于实验执行。

---

## Final Decision

**REPOSITORY_ARCHITECTURE_VALID_WITH_UNKNOWN**

职责边界已基本清晰，依赖方向与目标一致，目标结构合理；剩余 UNKNOWN 集中在：Source Adapter 输出契约的语义裁决、src packaging、pilot 内 governance 模块的迁移顺序、以及 archaeology 未提交材料的版本状态。这些不需要大爆炸重构即可进入 Phase 9。
