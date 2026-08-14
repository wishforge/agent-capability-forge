# Pilot Minimal Implementation Design

- 状态：DESIGN ONLY（不写代码；不修改 `docs/*`、`src/*`、P0 Contract、Experiment Design、Architecture Decision、Pilot Architecture）
- 日期：2026-08-14
- 目标：定义 24-run Pilot（3 families × 4 arms × 2 校准 formation tasks）所需的最小实现
- 冻结输入：
  - `research/experiments/pilot-architecture.md`（Option B Reconnected = PASS）
  - `research/experiments/experiment-readiness.md`（Pilot Readiness = NOT READY；本设计解决 P0 阻塞项）
  - `research/experiments/capability-forge-vs-skill.md`（v0.2 Final Correction，Pilot 节）
  - `research/artifact-contract/verified-task-artifact-bundle-v0.md`（P0 FROZEN）
  - `docs/capability-forge-mvp-spec.md`（v0.3，P1-P5 阶段划分）

## Pilot 范围裁决（本设计自决，不改冻结文档）

- **R1（formation 规模）**：Pilot 每族用 2 个校准 formation tasks → 1 个 artifact（B1/B2/B3）。这是 `experiment-readiness.md` P1-8 在 Pilot 层级的裁决；main-study 冻结的 `3 train → 1 artifact` 不变。
- **R2（trap 验证）**：Pilot 目标 6 需要 trap 触发验证。冻结的 24-run 公式只计 formation runs；本设计额外定义 3 个 Pilot-scoped trap fixtures + 12 次 trap probe runs（每族 4 arms × 1 trap）。若坚持严格 24 runs 总数，目标 6 只能降级为"wrong-invoke 记录路径可运行"，无法验证"触发"。
- **R3（共享 generation input）**：每族 B2/B3 各自跑 2 个 calibration tasks（24 runs 成立）；B2/B3 的 LLM generation input = 同一份 `generation_input.json`，含 B2+B3 共 4 个 Bundle refs + 固定 prompt 模板 + model config。LLM **每族只调用一次**，response 存为 `llm_proposal.json`，B2 冻结为 skill，B3 作为 Capabilityizer proposal。这是"完全一致"的唯一可验证实现。

---

# 1. Goal

实现能跑通 24-run Pilot 的最小可执行闭环，让 Pilot 的 8 个目标全部有记录证据：

1. oracle 稳定
2. 任务难度校准（B0 success ∈ [0.2, 0.8]）
3. B1 human cost 可记录
4. B2/B3 共享同一 generation input
5. Bundle 足够支撑 B3
6. trap 能触发错误复用（R2：Pilot-scoped trap probes）
7. NV 可计算
8. V / δ_NV sensitivity 可运行

非目标（沿用冻结 Non-Goals，明确不实现）：

- Generic RuntimeAdapter interface、第二 Runtime Adapter
- Production Registry（SQLite、多版本、discovery 健康态）
- Full P2 Validator、Full P3 Evaluation Platform、P4 Registry
- Dynamic Capability Plugin、Revoke、Rollback、Scope、Composition、Marketplace、MCP、Multi-tenant

Pilot 结果不进入 main-study 效应估计；main-study 21-task manifest 在 Pilot PASS 后另行锁定。

---

# 2. Architecture

```text
                     Experiment Harness (EXPERIMENT_ONLY)
                     ─ 启动 codex exec / 建沙箱 / 记录 run / 跑 oracle / 汇总 cost
                                  │  只消费 run metadata + Bundle + arm-specific result
        ┌─────────────┬───────────┼──────────────┬──────────────┐
        ▼             ▼           ▼              ▼              ▼
       B0            B1          B2             B3          Trap probes
        │             │           │              │              │
        │    human skill ────────►│              │              │
        │             │    freeze/inject         │              │
        │             │           └──► LLM proposal (shared) ◄──┘
        │             │                │         │
        │             │                ▼         ▼
        │             │         generated skill   Capabilityizer
        │             │              │            │
        │             └──────────────┼────────────┤
        │                       skill 目录        │
        │                            │            ▼
        │                            │   deterministic validation (minimal)
        │                            │            ▼
        │                            │   minimal evaluation
        │                            │            ▼
        │                            │   promote/reject → experimental registry (EXPERIMENT_ONLY)
        │                            │            ▼
        │                            └──────────► invoke
        └────────────────────────────────────────► Results (oracle + run records + costs)

B2/B3 共享生产层（不共享的只有 Bundle 之后的处理）：
Codex Runtime
    ↓
Codex Runtime Adapter（唯一解析 Codex native format 的模块）
    ↓
VerifiedTaskArtifactBundle（P0 FROZEN，runtime/forge 唯一 API boundary）
    ↓
Runtime-neutral Forge Experimental Slice（Capabilityizer → validation → evaluation → promote → registry → invoke）
```

冻结 invariants 全部沿用（pilot-architecture §9）：

1. Runtime-specific complexity stops at Adapter。
2. Bundle 是 runtime/forge API boundary。
3. Forge Slice 是 runtime-neutral。
4. Experiment Harness 不是 Forge Core。
5. Codex Adapter 是共享基础设施，不是 B3 treatment。
6. B2/B3 difference 从 Bundle 之后开始。
7. Adapter + Artifact Builder 逻辑边界保持可见（本设计拆两个模块、一个 CLI 入口）。
8. 未来第二 Runtime = 新增 Adapter，不改 Forge Slice / Harness。

---

# 3. Components

13 个模块。每个模块回答：是否必须、是否复用、是否一次性、输入、输出、依赖、最小 API / data contract、测试。

## M1 — Experiment Harness

- **必须为 Pilot 实现**：是（readiness P0-1）。
- **复用未来实现**：否。Harness 是实验编排（arms / runs / 顺序），产品中没有对应物。
- **一次性 Experiment Harness**：是，全模块标记 `EXPERIMENT_ONLY`。
- **输入**：`pilot_config.json`（model/config 锁定、超时、output/tool limits、价格、seed）、`task_manifest.json`、arm 定义、skill/capability artifact。
- **输出**：每 run 一个 `run_record`；每族一个 `generation_input.json`；pilot 汇总报告。
- **依赖**：M13 sandbox launcher、`codex exec` CLI、M2 manifest、M3 oracle、M11 run record、M12 cost、M4 adapter CLI。
- **最小 API / data contract**：`python -m pilot.harness --config pilot_config.json --phase formation|probe|report`。一个 CLI、一个 config 文件、一个 state 目录 `pilot/state/`。Harness 与 Codex 的唯一交互是 `codex exec`（黑盒）+ adapter CLI；**不得 import 任何 rollout 解析代码**。
- **测试**：用 fake `codex`（touch 文件的脚本）dry-run 全流程，验证 orchestration、run records、顺序记录；再跑 1 次真实 B0 run/族。

## M2 — Task Fixture / Manifest

- **必须**：是（readiness P0-2）。
- **复用**：manifest schema 复用（main-study 用同一 schema 换内容）；Pilot 内容本身是 Pilot-scoped。
- **一次性**：fixture 内容是一次性的；schema 不是。
- **输入**：冻结实验设计的族定义（F+ CSV→报告、F− 迁移缺陷修复、F0 Markdown→HTML）。
- **输出**：`task_manifest_v1.json`（git 提交、sha256 记录） + `pilot/fixtures/<family>/<task_id>/`（输入文件 + expected output）。
- **依赖**：无（纯文件）。
- **最小 API / data contract**：
  ```json
  {
    "schema_version": "task_manifest_v1",
    "families": [
      {
        "family": "F+",
        "role": "calibration",
        "tasks": [
          {
            "task_id": "fplus-cal-1",
            "prompt": "...",
            "fixture_ref": "fixtures/F+/fplus-cal-1",
            "oracle": {"kind": "check_command", "command": ["bash", "check.sh"]},
            "limits": {"timeout_seconds": 1800, "output_bytes": 1048576},
            "value": {"low": 50, "mid": 100, "high": 200}
          }
        ]
      }
    ],
    "traps": [{"task_id": "trap-fplus", "family": "F+", "looks_like": "F0", "..."}]
  }
  ```
  6 calibration fixtures（3 × 2）+ 3 trap fixtures（R2）。V_low/mid/high 与 δ 档（5%/10%/20%）在 manifest 内 pre-register（P1-9 落地）。
- **测试**：manifest schema 校验；每个 oracle 在 golden fixture 上 PASS、在已知坏输出上 FAIL。

## M3 — Deterministic Oracle Runner

- **必须**：是。
- **复用**：是。同一确定性 check 同时用于：harness 判任务成功、B3 golden/Novel Input Test 比较。
- **一次性**：否。
- **输入**：task 的 `oracle` 定义、task fixture（只读）、run 输出目录。
- **输出**：`{verdict: PASS|FAIL, reason, evidence_stdout, evidence_stderr, exit_code}`。
- **依赖**：M13 sandbox（oracle 也在隔离沙箱跑，网络关）。
- **最小 API / data contract**：`oracle(task_id, fixture_dir, output_dir, sandbox) -> verdict`。实现约定：`check.sh <fixture_dir> <output_dir>`，exit 0 = PASS；输出比较用 diff 或 check 命令，非确定性输出（时间戳/行序）由 fixture 自带 normalized comparator。
- **测试**：golden PASS fixture、篡改输出 FAIL fixture，每类 oracle 至少一对。

## M4 — Codex Runtime Adapter

- **必须**：是（readiness P0-3；B2/B3 共享输入生产层）。
- **复用**：是。这就是 P1 Artifact Builder 的 runtime-specific 部分；Pilot 实现即未来实现的最小可用版本。
- **一次性**：否。
- **输入**：run 的 rollout JSONL（从沙箱 `docker cp` 出来）、run workspace（最终文件）、run metadata（harness 写 `run.json`：task_id、arm、时间、model config）。
- **输出**：
  1. `normalized_execution.json`（packets/facts/identity/review/verification/diff——不含 Codex 私有结构）；
  2. `runtime_metrics.json`（tokens、tool calls、latency，供 M12；同样来自 rollout 但已归一化）；
  3. 调用 M5 产出 sealed Bundle。
- **依赖**：M5、rollout 文件、workspace、artifact store。
- **最小 API / data contract**：`codex-adapter build --rollout <path> --workspace <path> --run-meta run.json --store <store> --out run_artifacts.json`。`run_artifacts.json = {bundle_id, validation: {ok, errors}, gaps, runtime_metrics}`。**这是全仓唯一解析 Codex native runtime format 的模块**（requirement B 的强制边界）。
- **实现边界**：Pilot 不需要 runtime 修改。`final_phase` 无 runtime authority → 恒为 `null` + `provenance.gaps`；verification evidence 无 trace → `status=unknown` + gaps；`source_task_id`/replay/dependency manifest → null + gaps。全部按冻结契约诚实留空，不伪造。若 `CODEX_ROLLOUT_TRACE_ROOT` 可用则填充 evidence（EVENT_CAPTURE），不可用则维持 unknown。
- **测试**：golden rollout fixture → Bundle schema 合法、digest 重算一致、gaps 齐全；篡改 rollout → validation FAIL；未知 key → FAIL。

## M5 — VerifiedTaskArtifactBundle Producer

- **必须**：是（requirement E：B2/B3 唯一共享输入）。
- **复用**：是。这是 P1 Artifact Builder 的 runtime-neutral 部分；完整实现 P0 FROZEN v0 schema + storage layout + 13 条 validation rules 的可执行子集。
- **一次性**：否。
- **输入**：M4 的 `normalized_execution.json` + workspace snapshot（diff 路径文件）+ artifact store。
- **输出**：`bundles/<bundle_id>/`（`bundle.json` sealed + `artifacts/files/<sha256>` + `execution/rollout.jsonl` + `environment/snapshot.json`）+ validation 结果。
- **依赖**：M4、store 路径。
- **最小 API / data contract**：`seal_bundle(normalized, store) -> bundle_id` + `validate_bundle(bundle_dir) -> {ok, errors}`。contract = 冻结的 `verified-task-artifact-bundle-v0`，逐字段不变；digest 算法（§12.2）严格实现；Rules 1-7、9-13 完整执行；Rule 8 的 phase ordering 执行，final-phase authority 部分恒 null。**不引入任何 Pilot 专用字段**。
- **测试**：13 条规则各一正一反用例；canonical digest 算法（key 排序、紧凑、无尾随换行）单元测试。

## M6 — B1 Skill Freeze / Inject

- **必须**：是（readiness P1-6；Pilot 目标 3）。
- **复用**：freeze/inject 脚本在 main-study B1 复用；底层机制用 Codex 原生 skill 目录，不新造 skill 引擎。
- **一次性**：编排胶水是一次性的；机制是原生能力。
- **输入**：人类写的 skill 文档（harness 外完成）、human minutes（operator 输入）、arm 标识。
- **输出**：`skills/frozen/<arm-family>/`（不可变副本，sha256 记录）+ `skill_ref.json {path, digest, frozen_at, human_minutes}`。
- **依赖**：Codex 原生 skill 发现/注入（`CODEX_HOME` 或 config 指向 skill 目录）、M11、M12。
- **最小 API / data contract**：`freeze-skill --source <file> --arm B1-F+ --human-minutes N --out <dir>`；inject = 把 frozen skill 目录挂进沙箱并设置 skill 路径。B1 不经过 Adapter/Bundle 管道（冻结架构）。
- **测试**：frozen 目录 digest 不可变；沙箱内 `codex exec` 能看到该 skill。

## M7 — B2 Generated Skill

- **必须**：是（Pilot 目标 4；H2 主对照臂）。
- **复用**：是。B2 就是 main-study B2 臂的实现（LLM 从共享 input 生成 skill + freeze + inject）。
- **一次性**：否（臂定义本身）。
- **输入**：`generation_input.json`（M1 每族写一份：4 个 bundle refs + task prompts + 固定 prompt 模板 + model config）+ LLM 端点。
- **输出**：`llm_proposal.json`（每族一份，B2/B3 共享）+ frozen skill（走 M6 机制）。
- **依赖**：M5 bundle store、LLM 端点（model/config 锁定）、M6、M11、M12。
- **最小 API / data contract**：`generate-skill --input generation_input.json --out llm_proposal.json`。**B2 对 LLM 的输出零加工**：skill = `llm_proposal.json` 原文 freeze。generation input 的 sha256 写入 B2/B3 各自 run record（requirement D 的验证点）。
- **测试**：同一 `generation_input.json` 只产生一次 LLM 调用；B2 与 B3 的 `generation_input_digest`、`proposal_digest` 相等（integration assert）。

## M8 — B3 Capabilityizer

- **必须**：是（implementation blocker）。
- **复用**：是。这是 P1 Capabilityizer 的最小实现；Candidate/Manifest 语义与 spec §7.2 / Manifest v0.1 完全一致（requirement E）。
- **一次性**：否。
- **输入**：同一 `generation_input.json` 指向的 4 个 Bundle + immutable workspace snapshot refs + 共享 `llm_proposal.json`（LLM Proposal）+ `confirm.json`（operator 显式确认可复用）。
- **输出**：`candidates/<family>/`：`manifest.json`（v0.1）、`implementation/`（参数化 forged artifact，白名单复制）、`tests/`（golden tests）、`provenance/`。
- **依赖**：M5、LLM proposal、M13。
- **最小 API / data contract**：`capabilityize --bundles <4 dirs> --proposal llm_proposal.json --confirm confirm.json --out candidates/<family>`。确定性变换：entrypoint = proposal 中的 command + workdir；参数化 = 硬编码输入路径替换为 contract input；private-state removal = 只复制声明文件；静态扫描拒绝原 workspace 绝对路径 / session 引用 / 临时文件引用。LLM 只 propose，合法性由 M9 决定。
- **测试**：golden bundle fixture → 合法 Candidate；proposal 引用原 workspace 路径 → 静态检查 FAIL。

## M9 — B3 Minimal Validation / Evaluation

- **必须**：是（B3 pipeline 核心；readiness P0-3）。
- **复用**：是。这是 P2 Validator + P3 Evaluator 的最小种子。
- **一次性**：否。
- **输入**：Candidate、M2 fixtures（golden + Novel Input）、M13。
- **输出**：`validation.json`（PASS/FAIL + 原因）、`evaluation.json`（spec §7.6：golden pass_rate、novel_input_test、regression、independent_reuse、verdict、promotion_rule）。
- **依赖**：M13、M3、M2、M11、M12。
- **最小 API / data contract**：
  - `validate --candidate <dir> --sandbox <launcher> --fixtures <dir>`：manifest schema；entrypoint 存在可执行；private-state 静态检查（S0 部分）；golden tests 全过；permissions ⊆ 允许集；timeout/output limits。
  - `evaluate --candidate <dir> --novel-input <dir>`：golden regression + ≥1 Novel Input Test + independent reuse scenario（fresh sandbox、新 input、按 entrypoint 调用）。
  - promotion rule（冻结常量）：golden 100% + novel 100% + regression PASS + independent reuse PASS → eligible；promote 仍需 operator 显式确认。
- **测试**：合法 Candidate → PASS；坏 entrypoint → FAIL；任务私有 Candidate → novel/independent reuse FAIL。

## M10 — B3 Experimental Registry / Invoke

- **必须**：是（B3 tail）。
- **复用**：否。**明确标记 `EXPERIMENT_ONLY`**（requirement F）：不实现 SQLite、多版本、discovery 健康态、revoke。P4/P5 另行实现。
- **一次性**：是。
- **输入**：validated Candidate + evaluation PASS + promote 确认；invoke 的输入 fixture。
- **输出**：`pilot/state/registry/<family>/<name>.json` + forged artifact 副本；`invoke.json {exit_code, outputs, sandbox_cost}`。
- **依赖**：M13、M9、M11、M12。
- **最小 API / data contract**：`experimental_registry_v1`：`{capability_id, name, version: 1, artifact_dir, manifest, evaluation, state: promoted|rejected}`；`invoke(name, input_fixture) -> invoke.json`。promote/reject 二态，无 revoke；重名拒绝。
- **测试**：promote → discover → invoke golden input → 正确输出；invoke wrong-family input → 记录 wrong-capability cost；reject → 不可 discover。

## M11 — Run Record

- **必须**：是（readiness P0-4）。
- **复用**：是。schema/writer 在 main-study 原样复用。
- **一次性**：否。
- **输入**：harness 事件（run 起止、task、arm、order、seed、sandbox_id）、oracle verdict、bundle_id、skill/capability usage、M12 cost。
- **输出**：`pilot/state/run_records.jsonl`（每 run 一行）+ `run_id`（UUIDv7）。
- **依赖**：M3、M12、M4（bundle_id/metrics）。
- **最小 API / data contract**：`run_record_v1`：`{run_id, task_id, family, arm, formation_id, model, seed, order, sandbox_id, started_at, ended_at, oracle, bundle_id, skill_used, capability_used, invoke_result, trap, regression, false_promotion, cost}`。字段全集按 readiness §9。
- **测试**：schema 校验；每 run 恰好一行；必需字段齐全。

## M12 — Cost Collector（含 NV / sensitivity）

- **必须**：是（readiness P0-4；Pilot 目标 3、7、8）。
- **复用**：是。指标公式冻结，main-study 复用。
- **一次性**：否。
- **输入**：run records、M4 `runtime_metrics.json`、B1 human minutes、sandbox 时长、价格（config）、V/δ 档位（manifest）。
- **输出**：`cost.json`（每 run：tokens/tool_calls/latency/human_min/sandbox_min + USD 折算 + formation/validation/maintenance/wrong-capability 分类）、`nv_report.json`（NV_arm = Σ TaskValue − execution − formation − validation − maintenance − wrong_capability；V_low/mid/high × δ 5%/10%/20% sensitivity 表）。
- **依赖**：M11、M4、M2。
- **最小 API / data contract**：`collect(run_records, prices, manifest) -> {cost, nv_report}`；公式逐字对应 frozen design §9；结论翻转或进入等价带 → 标记 `value-sensitive`。
- **测试**：已知记录手工核算 NV；sensitivity 翻转被标记；B0 FAIL/B3 PASS 与 B0 PASS/B3 FAIL 两个 delta 方向正确。

## M13 — Docker Sandbox Launcher

- **必须**：是（readiness P1-7；spec §15 fail-closed）。
- **复用**：是。P2/P5 sandbox 的原型：harness 每 run fresh sandbox、oracle、B3 validation/evaluation/invoke 共用同一实现。
- **一次性**：否。
- **输入**：锁定 image（`python:3.12-slim` 基线，F− 族挂 fixture repo）、mounts（fixture 只读、输出可写）、network=off、timeout、output limit、command。
- **输出**：`{sandbox_id, exit_code, stdout, stderr, elapsed_s}`（截断到 output limit）。
- **依赖**：Docker daemon（29.1.3 可用）。无容器运行时 → 一律 FAIL（fail-closed，不降级裸进程）。
- **最小 API / data contract**：`launch(image, mounts, cmd, limits) -> result`。网络默认关；artifact 目录只读；仅 contract 输出目录可写。
- **测试**：只读挂载拒绝写；网络关闭（curl 失败）；timeout 硬杀；stdout 截断。

---

# 4. Code Ownership

## 4.1 建议布局（Pilot 实现时的落点）

```text
src/forge/                  # 可复用生产路径（P1-P3 种子，非 EXPERIMENT_ONLY）
  codex_adapter/            # M4：唯一解析 Codex native format 的模块
    main.py                 # CLI: codex-adapter build
    rollout_parser.py
    metrics.py
  bundle_producer.py        # M5：P0 FROZEN schema + validation rules
  capabilityizer.py         # M8
  validator.py              # M9
  evaluator.py              # M9
  sandbox.py                # M13
pilot/                      # EXPERIMENT_ONLY
  harness.py                # M1
  manifest.json             # M2（fixtures/ 同目录）
  fixtures/                 # M2
  oracles/                  # M3
  run_record.py             # M11
  cost.py                   # M12（含 nv_report）
  registry.py               # M10 EXPERIMENT_ONLY
  skills/frozen/            # M6/M7
  state/                    # run records / bundles 引用 / 汇总
```

## 4.2 Codex Adapter 与 Forge Slice 的代码边界（requirement A）

- **Adapter（M4）知道 Codex**：rollout JSONL、session/thread/turn 身份、`codex exec` 输出目录、`CODEX_ROLLOUT_TRACE_ROOT`。它负责 rollout 解析、runtime-only capture、workspace snapshot、归一化 + Bundle assembly/sealing。
- **Forge Slice（M8/M9/M10）不知道 Codex**：只消费 `VerifiedTaskArtifactBundle` + 引用的 immutable artifacts + `llm_proposal.json` + confirm。不得 import `codex_adapter`，不得接触 rollout 路径。
- **验证方式**：import 边界用结构检查（M8/M9/M10 的 import 表不允许 `codex_adapter`、`rollout_parser`）；M5 `seal_bundle` 的输入是 M4 产出的 normalized JSON，不是 rollout。

## 4.3 Experiment Harness 不得解析 Codex native runtime format（requirement B）

- Harness 只消费三类输入：
  1. run metadata（自己写的 run records）；
  2. `VerifiedTaskArtifactBundle`（经 M4/M5 产出）；
  3. arm-specific result（oracle verdict、skill/capability usage、invoke result）。
- Harness 与 Codex 的接触面只有：启动 `codex exec`、从沙箱拷出 rollout 文件并**原样转交 M4**、记录进程退出状态。
- 任何 token/tool/latency 数据必须来自 M4 的 `runtime_metrics.json`，不得由 harness 解析 rollout。
- 强制手段：结构检查（harness 代码库不 import rollout 解析模块）+ code review checklist 一项。

## 4.4 B2/B3 同一 Adapter production path（requirement C）

- 每族只有一个 `build_bundle` 调用方：M4 CLI。B2 的 2 个 run 和 B3 的 2 个 run 都调用**同一个** `codex-adapter build`，写**同一个** store。
- B2/B3 的 `generation_input.json` 由 M1 从同一 store 的 bundle refs 构造；两个臂读同一文件，不各自拼装。
- 验证：B2/B3 run record 中的 `bundle_ids` 交集 = 4；`generation_input_digest` 相等（integration assert）。

---

# 5. Data Flow

## 5.1 B0 / B1（不经过 Adapter/Bundle）

```text
Harness → fresh sandbox → codex exec(task fixture) → oracle → run record → cost
B1 额外：human 基于同一 2 个 calibration runs 写 skill → freeze（human minutes 入 cost）
```

## 5.2 B2 / B3（共享生产层）

```text
每族（B2 arm）：
  run t1 → codex exec → oracle → codex-adapter build → bundle B2-t1 + metrics
  run t2 → 同上 → bundle B2-t2
每族（B3 arm）：
  run t1 → codex exec → oracle → codex-adapter build → bundle B3-t1 + metrics
  run t2 → 同上 → bundle B3-t2

每族共享：
  generation_input.json = {4 bundle refs, task prompts, prompt template, model config}
  LLM call ×1 → llm_proposal.json
  B2: llm_proposal.json 原文 freeze → skill inject
  B3: capabilityize(4 bundles + proposal + confirm) → Candidate
      → validate → evaluate → promote/reject → experimental registry → invoke

所有 run：oracle verdict + run record + cost（formation/validation/wrong-capability 分类）
```

## 5.3 数据边界汇总

| 组件 | 可读 | 不可读 |
|---|---|---|
| Harness | run metadata、Bundle、arm result | Codex native format（rollout 原样转交 M4） |
| Adapter | rollout、workspace、run metadata | Forge Slice 内部 |
| Forge Slice | Bundle + immutable artifacts + proposal | rollout、live session/workspace |
| Oracle | fixture + output dir | rollout |

---

# 6. B2/B3 Fairness

冻结约束（pilot-architecture §5）逐一落实：

| 维度 | 机制 |
|---|---|
| 相同 formation tasks | 每族同一 2 个 calibration tasks，B2/B3 各自 fresh run |
| 相同 train inputs / Bundles | `generation_input.json` 含 B2+B3 共 4 个 bundles，两臂读同一文件 |
| 相同 LLM model/config | 单份 `pilot_config.json` 锁定 model、温度、seed、timeout、output/tool limits |
| 相同 generation prompt/input | 单份 prompt 模板 + 单份 `generation_input.json`（sha256 入 run record） |
| 相同 generation output | LLM 每族只调用一次，`llm_proposal.json` 两臂共享 |

Treatment difference 只发生在 Bundle 之后：

- B2：proposal 原文 freeze → skill 目录注入（无验证、无评估、无 gate）。
- B3：proposal 作为 LLM Proposal → Capabilityizer → deterministic validation → minimal evaluation → promote/reject → experimental registry → invoke。

B2/B3 的对比 = governed/validated pipeline vs naive execution-derived self-generation（H2 对齐）。Adapter → Bundle 不是 treatment difference。

验证点（integration asserts）：

1. `B2.generation_input_digest == B3.generation_input_digest`
2. `B2.proposal_digest == B3.proposal_digest`
3. B2/B3 的 `bundle_ids` 集合一致
4. B2/B3 的 model/config 哈希一致（来自 run record）

---

# 7. Reusable vs Experiment-only

| 模块 | 复用未来 P1/P2/P3 | 一次性 | 标记 |
|---|---|---|---|
| M1 Harness | 否（编排是实验概念） | 是 | `EXPERIMENT_ONLY` |
| M2 Manifest | schema 复用，内容 Pilot-scoped | 内容是 | 内容 `PILOT_SCOPE` |
| M3 Oracle | 是（main-study + B3 evaluator 共用） | 否 | — |
| M4 Codex Adapter | 是（P1 Artifact Builder runtime 侧） | 否 | — |
| M5 Bundle Producer | 是（P1 Artifact Builder neutral 侧，完整 P0 契约） | 否 | — |
| M6 B1 freeze/inject | 脚本复用；机制用 Codex 原生 skill | 胶水是 | 胶水 `EXPERIMENT_ONLY` |
| M7 B2 Generator | 是（main-study B2 臂） | 否 | — |
| M8 Capabilityizer | 是（P1） | 否 | — |
| M9 Validation/Evaluation | 是（P2/P3 种子） | 否 | — |
| M10 Experimental Registry | 否（P4/P5 另行实现） | 是 | `EXPERIMENT_ONLY` |
| M11 Run Record | schema/writer 复用 | 否 | — |
| M12 Cost Collector | 公式复用 | 否 | — |
| M13 Sandbox Launcher | 是（P2/P5 原型） | 否 | — |

**requirement E**：不引入实验特供 Capability semantics。Bundle 用冻结 v0 契约；Candidate/Manifest 用 spec §7.2 / Manifest v0.1；唯一 `EXPERIMENT_ONLY` 语义是 M10 的实验 registry（扁平目录二态，无生产生命周期）。

**requirement F**：所有一次性 mock 均显式标记 `EXPERIMENT_ONLY`。当前清单：M1 harness、M10 registry、M6 胶水、trap fixtures（`PILOT_SCOPE`）。

---

# 8. Task Sequence

## 8.1 Fixture 规模（R1 + R2）

- 6 calibration fixtures：3 families × 2（F+、F−、F0）。
- 3 trap fixtures：每族 1 个，表面相似另一族、契约不同（按冻结 trap 规则设计，仅 Pilot 用，main-study trap 另行锁定）。
- 合计 9 fixtures；V_low/mid/high 与 δ 档在 manifest 中 pre-register。

## 8.2 Runs

**Formation phase（24 runs，冻结公式）**：每族 4 arms × 2 tasks：

| 臂 | 每族 runs | 行为 |
|---|---|---|
| B0 | 2 | 无 artifact，从零解决 |
| B1 | 2 | 无 artifact 执行 + human 写 skill + freeze（human cost） |
| B2 | 2 | 执行 → adapter → bundle → 共享 LLM proposal → skill freeze |
| B3 | 2 | 执行 → adapter → bundle → 共享 LLM proposal → capabilityize → validate → evaluate → promote/reject → registry → invoke |

每族顺序：B0 → B1 → B2 → B3（臂内 task1 → task2），保证 B2/B3 的 4 个 bundle 齐了再生成。

**Probe phase（12 runs，R2）**：每族 formation 完成后：

| 臂 | trap run | 行为 |
|---|---|---|
| B0 | 1 | trap task 无 artifact 跑（baseline） |
| B1 | 1 | curated skill 已注入，观察错误复用 |
| B2 | 1 | generated skill 已注入，观察错误复用 |
| B3 | 1 | registry discover 可用，观察错误复用 + wrong-capability cost |

## 8.3 阶段顺序

```text
1. pre-register：manifest（tasks/oracles/V/δ）+ pilot_config（model/config/limits/价格/seed）
2. 单族 rehearsal（F+ 全流程）→ 通过后
3. 24 formation runs（3 families）
4. 12 trap probes
5. NV + V/δ sensitivity 计算
6. Pilot report + READY/NOT READY gate
```

顺序/seed 全部记录；rehearsal 结果不计入 pilot 数据。

---

# 9. Parallel Tasks

- **默认串行**：run 间有依赖（formation → artifact → probe），且同一模型端点与 Docker 资源下串行最可复现。24 runs × ≤30 min ≈ 12h 上限。
- **可选族级并行**：3 族无相互依赖，`--workers 3` 时按族并行；臂内仍然串行。并行度、sandbox 起止时间写入 run record，cost 按实际 sandbox_min 计，不受并行影响。
- **B3 内部**：validation/evaluation 的多个 test sandbox 可并行（默认 ≤2），timeout/output limit 不变。
- **约束**：B2/B3 的 LLM 调用保持每族一次、串行于该族 4 个 bundle 之后；不并发共享同一 generation input 的构造。

---

# 10. Test Strategy

## 10.1 Unit（stdlib unittest，无框架依赖）

| 模块 | 用例 |
|---|---|
| M5 | 13 条 validation rules 各一正一反；canonical digest 重算一致 |
| M3 | golden PASS / 篡改 FAIL |
| M2 | manifest schema 校验 |
| M8 | 合法 proposal → Candidate；私有路径引用 → 静态 FAIL |
| M9 | 坏 entrypoint FAIL；任务私有 Candidate → novel/reuse FAIL |
| M12 | 手工核算 NV；sensitivity 翻转标记 |
| M13 | 只读挂载、网络关、timeout、截断 |

## 10.2 Integration / Boundary

1. **Harness 不解析 rollout**：结构检查（harness 代码库 import 表不含 rollout 解析模块）+ review checklist。
2. **同一 Adapter path**：B2/B3 run record 的 `bundle_ids` 交集 = 4。
3. **generation input 完全一致**：B2/B3 的 `generation_input_digest`、`proposal_digest` 相等（requirement D）。
4. **Bundle 足够支撑 B3**：B3 slice 在只读 Bundle store + proposal 上跑通（requirement C/E）。

## 10.3 E2E / Rehearsal

- **F+ 单族 rehearsal**（gate）：1 次真实 B0 run → B1 skill freeze → B2 全链 → B3 全链（capabilityize → validate → evaluate → promote → invoke）→ 1 次 trap probe → NV 计算。rehearsal 通过后才放行 24-run Pilot。
- **Pilot E2E**：36 runs 全量 + 报告（见 §11）。

---

# 11. Pilot E2E

以 F+ 为例的端到端：

1. manifest 冻结：2 calibration + 1 trap fixture、oracle、V_low/mid/high、δ 5/10/20%。
2. **B0**：fresh sandbox → `codex exec`（CSV 清洗 + 报告）→ oracle → run record + cost。
3. **B1**：同样 2 runs（human 参考 trajectory）→ 人类写 curated skill → freeze + human minutes。
4. **B2**：2 runs → `codex-adapter build` → 2 bundles + metrics。
5. **B3**：2 runs → 同一 adapter → 2 bundles + metrics。
6. 共享 `generation_input.json`（4 bundles + prompt + model）→ LLM ×1 → `llm_proposal.json`。
7. B2 freeze proposal 为 skill；B3 capabilityize → validate → evaluate → operator promote → experimental registry。
8. 4 arms × trap probe（F+ trap，表面像 F0）→ 观察错误复用 / wrong-capability cost。
9. F−、F0 重复 1-8。
10. 汇总：36 runs 的 run records + costs → NV（V_low/mid/high × δ 5/10/20%）→ Pilot report。

Pilot report 输出：

- 每 oracle 的 PASS/FAIL 复现性（目标 1）
- 每族 B0 success ∈ [0.2, 0.8] 校准表（目标 2）
- B1 human minutes 记录（目标 3）
- B2/B3 generation input digest 相等断言（目标 4）
- B3 全链在只读 Bundle 上跑通（目标 5）
- trap probe 的 wrong-reuse 观测 + wrong-capability cost（目标 6）
- NV 表（目标 7）+ sensitivity 表（目标 8）

---

# 12. Definition of Done

Pilot 实现完成，当且仅当：

1. 24 formation runs + 12 trap probes 全部执行，每 run 恰好一条 `run_record_v1`，字段完整。
2. B2/B3 每族 4 个 Bundle 全部通过 M5 可执行 validation rules；gaps 覆盖全部 OPEN_NULLABLE，无伪造字段。
3. B2/B3 的 `generation_input_digest` 与 `proposal_digest` 每族相等（requirement D）。
4. B3 每族至少完成一次 capabilityize → validate → evaluate → promote/reject → registry → invoke（promote 或 reject 均有记录）。
5. B1 每族产出 frozen skill + human minutes 记录。
6. 每族 1 个 trap probe 触发错误复用观测（B1/B2/B3）与 B0 baseline；wrong-capability cost 入账。
7. NV + V_low/mid/high × δ 5/10/20% sensitivity 表产出；翻转标记 `value-sensitive`。
8. oracle 所有 verdict 可复跑且稳定（每 oracle 复跑一次，结果一致）。
9. Docker sandbox fail-closed 验证通过（无 daemon 时 validation/invoke 全部 FAIL）。
10. F+ rehearsal 通过；Pilot report 产出，给出 main-study READY / NOT READY gate。

---

**Pilot Minimal Implementation Design = READY**

前提（三个 Pilot 范围裁决被接受）：R1 每族 2 formation → 1 artifact（main-study 3→1 不变）；R2 增加 3 trap fixtures + 12 probe runs 以满足 Pilot 目标 6；R3 每族一次共享 LLM 调用保证 B2/B3 generation input/output 完全一致。若 R2 不被接受，严格 24 runs 下目标 6 只能验证记录路径、无法验证触发，设计降级为 NOT READY。

实现就绪度不受本设计影响：`experiment-readiness.md` 的结论保持——Pilot 可运行性仍是 NOT READY，直到上述模块按本设计实现并通过 §10 rehearsal gate。
