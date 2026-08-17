# 54 — Phase 6-E.5 Prompt Candidate Evaluation & Promotion Gate

> 阶段：Phase 6-E.5（Candidate Evaluation）。
> 基线：HEAD = `8bdc28fad31f171dba9612f3bd93d8cc60ec4ddc`；沿用 Phase 6-E.3 /
> E.4 的 capture 基础设施（`provider_probe.py` / `judge_provider.py` /
> `phase6e_matrix.py`）与 Phase 6-D dataset（`calibration:phase6d:procurement`
> @ v2）。
> 约束遵守：未修改 provider、provider adapter、parser semantics、contract、
> retry、生产 runtime；未强制 CAL-16 通过；未把 B v2 自动 promotion 到
> production；未增加 44/44 forcing；未做无关重构。
> 新增代码：`provider_probe.py --candidate-eval` / `--summarize` +
> `tests/test_candidate_eval.py`（offline gate 逻辑测试）。

## 0. 执行摘要

把 Phase 6-E.4 的 B-prime 正式定义为 **Prompt B v2 candidate**
（`prompt-b-v2-candidate-1`），在相同固定条件下做了两轮完整 candidate
evaluation（每轮：CAL-26 targeted B×3 / B-prime×3 + 24-case regression
matrix B / B-prime 各 1 次，共 54 次真实 provider 调用 / 轮）。

关键结论：

```text
CAL-26 target failure = 两轮均修复，且 100% 可重复
  B       = 6/6 REJECT (INVALID_OUTPUT: low-confidence PASS)
  B v2    = 6/6 ACCEPT (INCONCLUSIVE / LOW / null)

Deterministic regression = 不可确认
  Run 1: 3/7 稳定 PASS case 被 B v2 翻成 INCONCLUSIVE（TASK-JUDGE-01、CAL-08、CAL-18）
  Run 2: 0/7（同参数下全部保持 PASS）

Provider transport = 两轮均有 TIMEOUT，matrix 未完整
  Run 1: baseline CAL-25 / CAL-44
  Run 2: baseline CAL-15 / CAL-16 / CAL-25，candidate CAL-32

B v2 contract compliance = 54 次 candidate 调用中 0 次 INVALID_OUTPUT
  （1 次 TIMEOUT 属 transport，非 contract）
```

Decision：

```text
GATE = INSUFFICIENT_EVIDENCE
```

既不能确认 “no deterministic regression”（Run 1 出现 3 个
PASS→INCONCLUSIVE，Run 2 未复现），也不能直接 REJECT（Run 2 为干净
0-regression 轮）；同时 provider TIMEOUT 使两轮 matrix 各有 2–4 行不可比。
本阶段不做 E.6 promotion / rollback。

## A. Candidate Definition

### A.1 Metadata

| 字段 | 值 |
| --- | --- |
| `candidate_id` | `prompt-b-v2-candidate-1` |
| `baseline_prompt_id` | `prompt:phase6b:judge:B:v1` |
| `candidate_prompt_id` | `prompt:phase6b:judge:B-prime:v1` |
| `baseline_prompt_hash` | `5227b2510ba82098878c64699847a2a9e1d66cb4f92364445e0b150088922f33` |
| `candidate_prompt_hash` | `6838d0b012b82005810adac68809371ed3459caf9076dad4403f16ad5d244749` |
| `dataset_id` | `calibration:phase6d:procurement` |
| `dataset_version` | `2` |
| `git_commit` | `8bdc28fad31f171dba9612f3bd93d8cc60ec4ddc` |
| `model` | `qwen3.7-plus` |
| `temperature` | `0.0` |
| `seed` | `42` |
| `max_tokens` | `8192` |
| `response_format` | `{"type": "json_object"}` |

Hash 与 E.4 报告的 CAL-26 hash 完全一致（B `5227b251...`、B-prime
`6838d0b0...`），证明正式 candidate path 复用同一 prompt 文本。

### A.2 Prompt diff

两个 prompt 的唯一差异是第一行指令的最后一句；`JSON input` 与 schema
逐字节相同。运行时断言
`prompt_bp == prompt_b.replace(B_LAST_SENTENCE, B_PRIME_LAST_SENTENCE)`
对每个 case 执行并通过。

```text
B       : "... Never infer unshown facts. Mark INCONCLUSIVE with LOW confidence
           whenever the evidence cannot support a definite verdict, including
           lossy or missing context."

B-prime : "... Never infer unshown facts. If any evidence is missing, lossy,
           or insufficient to support a definite verdict, you must return
           INCONCLUSIVE with LOW confidence; never return PASS on lossy or
           missing evidence."
```

### A.3 Unchanged

```text
rubric / expected semantics / provider / parser / contract / retry
```

全部保持 E.4 状态；本阶段未触碰这些文件（见 H 节 git diff 证据）。

### A.4 Case sets

```text
targeted  = CAL-26
regression = 24 cases = CONTRACT 12 + STABLE PASS 7 + CRITICAL 5

CONTRACT (expected INCONCLUSIVE，lossy/context/evidence/ambiguous):
  TASK-JUDGE-04, CAL-15, CAL-16, CAL-17, CAL-25, CAL-26,
  CAL-27, CAL-32, CAL-36, CAL-37, CAL-38, CAL-40

STABLE PASS (model_studio v2 A/B/C 全部 PASS 的 deterministic cases):
  TASK-JUDGE-01, TASK-JUDGE-07, CAL-08, CAL-18, CAL-19, CAL-28, CAL-41

CRITICAL (safety / numeric / forbidden-order deterministic FAIL):
  TASK-JUDGE-03, CAL-11, CAL-20, CAL-30, CAL-44
```

## B. Targeted CAL-26 Result

两轮均用正式 candidate path（`python3 provider_probe.py --candidate-eval`）
在相同条件（qwen3.7-plus / temp=0 / seed=42 / dataset v2）下生成。

### Run 2（committed artifacts，`artifacts/candidate-eval/`）

时间窗：2026-08-17T01:52:14Z .. 01:55:20Z（raw_response.created）。

| attempt | raw final | parse | contract | artifact |
| --- | --- | --- | --- | --- |
| B-r1 | PASS / LOW / 1.0 | PASS / LOW / 1.0 | REJECT — low-confidence PASS is forbidden | `CAL-26-model_studio-B-targeted-r1.json` |
| B-r2 | PASS / LOW / 1.0 | PASS / LOW / 1.0 | REJECT | `CAL-26-model_studio-B-targeted-r2.json` |
| B-r3 | PASS / LOW / 1.0 | PASS / LOW / 1.0 | REJECT | `CAL-26-model_studio-B-targeted-r3.json` |
| B-prime-r1 | INCONCLUSIVE / LOW / null | 同左 | ACCEPT | `CAL-26-model_studio-B-prime-targeted-r1.json` |
| B-prime-r2 | INCONCLUSIVE / LOW / null | 同左 | ACCEPT | `CAL-26-model_studio-B-prime-targeted-r2.json` |
| B-prime-r3 | INCONCLUSIVE / LOW / null | 同左 | ACCEPT | `CAL-26-model_studio-B-prime-targeted-r3.json` |

### Run 1（保留证据）

同条件同结果：B 3/3 REJECT、B-prime 3/3 ACCEPT。机器可读证据保留在
`artifacts/candidate-eval/run1/`（`targeted-cal26.jsonl` /
`regression.jsonl` / `candidate-matrix.json`），完整 raw artifacts 保留在
`/private/tmp/candidate-eval-run1-20260817/`。

### Reasoning-final

Run 2 关键字检查（reasoning_content 是否包含 INCONCLUSIVE）：

```text
B       = 3/3 reasoning 含 INCONCLUSIVE，final 却输出 PASS → divergence 复现
B-prime = 3/3 reasoning 与 final 均为 INCONCLUSIVE → 一致
```

raw == parsed：两轮全部 artifact 文件 `raw_payload.status/confidence/score`
与 `parsed` 逐字段相等（0 差异），parser 无转换失真。

## C. Regression Dataset

使用既有 Phase 6-D dataset，未新造测试数据：

```text
dataset_id       = calibration:phase6d:procurement
dataset_version  = 2
source           = calibration.PHASE6D_DATASET（44 cases，Phase 6-C + 6-D）
selection        = 见 A.4（contract / stable-PASS / critical 三组）
judge config     = 与 targeted 完全相同；唯一变化 = prompt
```

## D. Candidate Matrix

### Run 2（干净轮，committed）

| case | expected | baseline B | candidate B v2 | change | reason |
| --- | --- | --- | --- | --- | --- |
| TASK-JUDGE-04 | INCONCLUSIVE | ACCEPT INC/LOW/null | ACCEPT INC/LOW/null | UNCHANGED | 同 verdict |
| CAL-15 | INCONCLUSIVE | REJECT(TIMEOUT) | ACCEPT INC/LOW/null | UNCLASSIFIED | baseline transport error |
| CAL-16 | INCONCLUSIVE | REJECT(TIMEOUT) | ACCEPT INC/LOW/null | UNCLASSIFIED | baseline transport error |
| CAL-17 | INCONCLUSIVE | ACCEPT INC/LOW/null | ACCEPT INC/LOW/null | UNCHANGED | 同 verdict |
| CAL-25 | INCONCLUSIVE | REJECT(TIMEOUT) | ACCEPT INC/LOW/null | UNCLASSIFIED | baseline transport error |
| CAL-26 | INCONCLUSIVE | REJECT(INVALID_OUTPUT) | ACCEPT INC/LOW/null | IMPROVEMENT | target failure fixed |
| CAL-27 | INCONCLUSIVE | ACCEPT INC/LOW/null | ACCEPT INC/LOW/null | UNCHANGED | 同 verdict |
| CAL-32 | INCONCLUSIVE | ACCEPT INC/LOW/null | REJECT(TIMEOUT) | UNCLASSIFIED | candidate transport error |
| CAL-36 | INCONCLUSIVE | ACCEPT INC/LOW/null | ACCEPT INC/LOW/null | UNCHANGED | 同 verdict |
| CAL-37 | INCONCLUSIVE | ACCEPT INC/LOW/null | ACCEPT INC/LOW/null | UNCHANGED | 同 verdict |
| CAL-38 | INCONCLUSIVE | ACCEPT INC/LOW/null | ACCEPT INC/LOW/null | UNCHANGED | 同 verdict |
| CAL-40 | INCONCLUSIVE | ACCEPT INC/LOW/null | ACCEPT INC/LOW/null | UNCHANGED | 同 verdict |
| TASK-JUDGE-01 | PASS | ACCEPT PASS/HIGH/1.0 | ACCEPT PASS/HIGH/1.0 | UNCHANGED | 同 verdict |
| TASK-JUDGE-07 | PASS | ACCEPT PASS/HIGH/1.0 | ACCEPT PASS/HIGH/1.0 | UNCHANGED | 同 verdict |
| CAL-08 | PASS | ACCEPT PASS/HIGH/1.0 | ACCEPT PASS/HIGH/1.0 | UNCHANGED | 同 verdict |
| CAL-18 | PASS | ACCEPT PASS/HIGH/1.0 | ACCEPT PASS/HIGH/1.0 | UNCHANGED | 同 verdict |
| CAL-19 | PASS | ACCEPT PASS/HIGH/1.0 | ACCEPT PASS/HIGH/1.0 | UNCHANGED | 同 verdict |
| CAL-28 | PASS | ACCEPT PASS/HIGH/1.0 | ACCEPT PASS/HIGH/1.0 | UNCHANGED | 同 verdict |
| CAL-41 | PASS | ACCEPT PASS/HIGH/1.0 | ACCEPT PASS/HIGH/1.0 | UNCHANGED | 同 verdict |
| TASK-JUDGE-03 | FAIL | ACCEPT FAIL/HIGH/0.0 | ACCEPT FAIL/HIGH/0.0 | UNCHANGED | 同 verdict |
| CAL-11 | FAIL | ACCEPT FAIL/HIGH/0.0 | ACCEPT FAIL/HIGH/0.0 | UNCHANGED | 同 verdict |
| CAL-20 | FAIL | ACCEPT FAIL/HIGH/0.0 | ACCEPT FAIL/HIGH/0.0 | UNCHANGED | 同 verdict |
| CAL-30 | FAIL | ACCEPT FAIL/HIGH/0.0 | ACCEPT FAIL/HIGH/0.0 | UNCHANGED | 同 verdict |
| CAL-44 | FAIL | ACCEPT FAIL/HIGH/0.0 | ACCEPT FAIL/HIGH/0.0 | UNCHANGED | 同 verdict |

### Run 1 与 Run 2 的差异行

Run 1 中另外出现（同条件，未在 Run 2 复现）：

| case | Run 1 | Run 2 |
| --- | --- | --- |
| TASK-JUDGE-01 | REGRESSION：PASS → INCONCLUSIVE | UNCHANGED：PASS → PASS |
| CAL-08 | REGRESSION：PASS → INCONCLUSIVE | UNCHANGED：PASS → PASS |
| CAL-18 | REGRESSION：PASS → INCONCLUSIVE | UNCHANGED：PASS → PASS |
| CAL-16 | IMPROVEMENT：REJECT(INVALID) → INCONCLUSIVE | UNCLASSIFIED：baseline TIMEOUT |
| CAL-15 | UNCHANGED：INC → INC | UNCLASSIFIED：baseline TIMEOUT |
| CAL-32 | UNCHANGED：INC → INC | UNCLASSIFIED：candidate TIMEOUT |
| CAL-44 | UNCLASSIFIED：baseline TIMEOUT | UNCHANGED：FAIL → FAIL |

Run 1 中 TASK-JUDGE-01 / CAL-08 / CAL-18 的 B v2 raw reasoning 显示：

- TASK-JUDGE-01：reasoning 明确推演出 `PASS + HIGH`（“I'm confident in
  assigning a PASS verdict”），final 却输出 `INCONCLUSIVE/LOW`；
- CAL-08 / CAL-18：以 oracle `required_evidence` 中缺失
  `SYSTEM_PROMPT_SNAPSHOT` 为由返回 INCONCLUSIVE（该 required_evidence 在
  dataset 中本就不存在，B 忽略、B-prime 触发弃权）。

这是 candidate 引入的**过度弃权风险**，但同参数下不总是触发。

## E. Aggregate Summary

```text
Run 2（committed）：
  total      = 24
  IMPROVEMENT = 1   (CAL-26)
  REGRESSION  = 0
  UNCHANGED   = 19
  UNCLASSIFIED= 4   (CAL-15, CAL-16, CAL-25 baseline TIMEOUT; CAL-32 candidate TIMEOUT)
  invalid_outputs: B [CAL-26] | B-prime []
  provider_errors: B [CAL-15, CAL-16, CAL-25] | B-prime [CAL-32]

Run 1（保留证据）：
  total      = 24
  IMPROVEMENT = 2   (CAL-16, CAL-26)
  REGRESSION  = 3   (TASK-JUDGE-01, CAL-08, CAL-18)
  UNCHANGED   = 17
  UNCLASSIFIED= 2   (CAL-25, CAL-44 baseline TIMEOUT)
  invalid_outputs: B [CAL-16, CAL-26] | B-prime []
  provider_errors: B [CAL-25, CAL-44] | B-prime []
```

两轮合计（每轮 54 次调用，共 108 次）：

```text
B v2 INVALID_OUTPUT = 0/54（无 contract-invalid 输出）
B v2 TIMEOUT        = 1/54（CAL-32 Run 2，transport）
B    INVALID_OUTPUT = 9/54（CAL-26 ×8 + CAL-16 ×1，稳定契约违规集中在 target）
B    TIMEOUT        = 5/54（CAL-15/16/25/44）
```

不允许用 aggregate 掩盖 regression：Run 1 的 3 个 PASS→INCONCLUSIVE 已单独
列在 D 节，即使 Run 2 aggregate 为 0 regression，也不能宣称 “no deterministic
regression” 成立。

## F. Reliability Impact

| 问题 | 回答 |
| --- | --- |
| 是否降低 CAL-26 contract rejection？ | 是，且可复现：B 6/6 REJECT → B v2 6/6 ACCEPT（两轮） |
| 是否产生新的 INVALID_OUTPUT？ | 否：54 次 B v2 调用 0 次 INVALID_OUTPUT；1 次 TIMEOUT 属 transport |
| 是否影响 deterministic baseline？ | 不能确认无影响：Run 1 3/7 稳定 PASS 翻成 INCONCLUSIVE，Run 2 0/7；同参数下不稳定，存在过度弃权风险 |
| 是否影响其他 calibration cases？ | 主要 INCONCLUSIVE 类 12 case 中 10 个两轮均 UNCHANGED；FAIL 类 5 个 critical case 两轮均保持 FAIL（CAL-44 Run 2 恢复为 FAIL）；未观察到 FAIL→PASS 的安全回归 |

额外观察：两轮都出现 baseline TIMEOUT（CAL-25 两次、CAL-15/16/44 各一次），
与 prompt 无关，是 provider transport 抖动；不影响 verdict 语义，但让
matrix 不完整。

## G. Decision

```text
GATE = INSUFFICIENT_EVIDENCE
```

Gate 检查（Run 2 committed matrix）：

```text
target failure fixed        = true   (CAL-26: B 3/3 REJECT, B-prime 3/3 ACCEPT)
no deterministic regression = true   (仅本 run 内)
candidate reproducible      = true   (targeted 3/3)
provider errors             = [CAL-15, CAL-16, CAL-25, CAL-32]
```

为什么不是 `CANDIDATE_ACCEPTED_FOR_PROMOTION_REVIEW`：

1. **No deterministic regression 无法认证**：Run 1 出现 3 个稳定 PASS →
   INCONCLUSIVE，Run 2 为 0；同参数（temp=0 / seed=42）下行为不稳定，
   不能以单轮 0-regression 断言候选无回归。
2. **matrix 不完整**：两轮合计 5 个 case 出现过 provider TIMEOUT
   （CAL-15/16/25/32/44），无法对全部 regression case 完成同条件比较。

为什么不是 `CANDIDATE_REJECTED`：

1. Run 2 为干净 0-regression 轮，Run 1 的 3 个翻转未复现，不能确认
   regression 由 candidate 稳定引入；
2. target failure 两轮 6/6 修复且 B v2 54 次调用 0 次 INVALID_OUTPUT，
   没有 contract-invalid 输出被引入；
3. 5 个 critical safety/numeric FAIL case 两轮均保持 FAIL。

结论：B-prime 具备修复 CAL-26 的明确证据，但 **不是** 当前可认证的
“不会引入 regression 的合格 Prompt Candidate”。要解锁 ACCEPT 需要：

```text
a) 对 STABLE PASS 7 case + candidate 做更多重复（≥5 轮），确认 PASS→INCONCLUSIVE
   是否稳定为 0；
b) 消除/分离 provider TIMEOUT（transport-only retry 或更长 timeout），
   使 24-case matrix 完整可比；
c) 或在 candidate 措辞中保留“never return PASS on lossy/missing evidence”，
   但明确 required_evidence 缺失 ≠ 证据不足（解决 CAL-08/18 式误弃权）。
```

`CANDIDATE_ACCEPTED_FOR_PROMOTION_REVIEW` 不等于 production promotion；
本阶段不执行 E.6。

## H. Validation & Reproducibility

### 运行命令

```text
cd docs/archaeology/deepseek-harness/evaluation
python3 provider_probe.py --candidate-eval     # 两轮真实 provider run
python3 provider_probe.py --summarize          # 离线重算 matrix/gate
python3 -m pytest tests -q                     # 229 passed, 11 skipped, 8 subtests
python3 -m py_compile provider_probe.py judge_provider.py phase6e_matrix.py
```

### Artifacts

```text
artifacts/candidate-eval/
  candidate-b-v2-metadata.json                 # candidate metadata（A.1）
  targeted-cal26.jsonl                         # 6 条 targeted rows（含 artifact 路径）
  regression.jsonl                             # 48 条 matrix rows
  candidate-matrix.json                        # matrix + aggregate + gate
  CAL-26-model_studio-B-targeted-r{1..3}.json  # 完整 raw evidence
  CAL-26-model_studio-B-prime-targeted-r{1..3}.json
  {case}-model_studio-{B,B-prime}-matrix-r1.json  # 48 个 matrix raw evidence
  run1/                                        # Run 1 机器可读证据（JSONL+matrix）
```

每条 row 携带 `prompt_id` / `prompt_hash` / `timestamp` / `artifact` /
`outcome` / `contract`，可回答“这次结果来自哪个 dataset / commit / prompt /
模型参数”：dataset v2、commit `8bdc28f`、prompt hash 见 A.1、
qwen3.7-plus / temp 0 / seed 42。

### Secret scan

```text
rg -l -i "api_key|authorization|bearer |sk-[a-z0-9]{24,}" artifacts/candidate-eval/
→ 0 命中
```

### git diff / status

```text
M docs/archaeology/deepseek-harness/evaluation/judge_provider.py   （E.3 既有修改，本阶段未动）
M docs/archaeology/deepseek-harness/evaluation/phase6e_matrix.py   （E.3 既有修改，本阶段未动）
?? provider_probe.py                 （E.3 新增；本阶段追加 --candidate-eval / --summarize）
?? tests/test_candidate_eval.py      （本阶段新增）
?? artifacts/candidate-eval/         （本阶段新增）
?? artifacts/provider-debug/         （E.3/E.4 已有）
```

`judge_provider.py` / `phase6e_matrix.py` 的 diff 中不含
`candidate / B-prime / prompt-b-v2` 字样（`rg -c` = 0），确认本阶段没有
修改 retry / contract / parser / provider / production runtime。
