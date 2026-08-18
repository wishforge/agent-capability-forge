# Phase 9-B.5 Implementation Report — Anchored Run Intent (Option A)

- 日期：2026-08-18
- 基线：`9b81daa`（O2 Design Freeze）
- 范围：canonical Run Intent trust；b3_entry 降级为 derived cache / locator
- 改动：`pilot/runtime_adoption_guard.py`、`pilot/harness.py`、
  `docs/archaeology/unified-runtime/phase9b1/test_production_trust_chain.py`
  （回归用例适配新 cache 契约）、新增 Phase 9-B.5 RED 测试与本报告

## Verdict

```text
PASS
```

## Run Intent Contract

```text
Owner        = Adoption Store
Source       = adoption_store["run_request"]
Trust        = anchored（进入 store_digest，由 write_trust_anchor 覆盖）
Mutability   = per-promotion immutable；active record 仅由新 promotion 替换
B3 Entry     = derived cache / locator，无安全权威
```

写入点：`runtime_guard.mark_promoted()`（canonical entry 分支），与
lifecycle PROMOTED 同一 store 事务，随后刷新 trust anchor。同一 decision
重复写入 idempotent；新 promotion 的 run_request 不同则在同一事务中替换
active record 并刷新 anchor。

读取点：`harness.phase_future("b3")` -> `load_trusted_run_request()`（先
anchor 验证）-> `resolve_b3_cache()`（cache 比对 / 重建）-> discover 使用
`run_request.name` -> adopt -> `verify_at_mount(expected_identity=run_request)`。

## Exploit Results

RED 基线（实现前实测，`pytest` 之外的内联 probe）：

```text
whole swap          : ALLOW B（docker 挂载 B 的 artifact）
cache deletion      : FileNotFoundError
candidate_id 单字段  : BLOCKED CANDIDATE_ID_MISMATCH（语义错误）
sealed store tamper : BLOCKED INTEGRITY_STORE_CORRUPTED（已闭合）
missing run_request : ALLOW A（从 b3_entry 推断）
positive            : ALLOW A（已闭合）
```

| Scenario | Before | Attack | Expected | Observed | Result |
|---|---|---|---|---|---|
| A. whole b3_entry swap | Intent=A, cache=A, registry=A | b3_entry 五项全换 B（registry 同步 B） | REJECT | 实现前 ALLOW B；实现后 `RUN_REQUEST_CACHE_MISMATCH`，docker 未调用 | PASS |
| B. registry + b3 swap | Intent=A, Authority=A, registry/cache=B | 一致改写 registry+cache 为合法 B | REJECT | 实现前 ALLOW B；实现后 cache mismatch 先行 REJECT | PASS |
| C. cache deletion | Intent=A, cache=A | 删除 b3_entry.json | REBUILD → ALLOW A | 实现前 FileNotFoundError；实现后从 run_request 重建并 ALLOW A，重建文件与 intent 一致 | PASS |
| D. partial cache mismatch | Intent=A, cache=A | 单字段改 B（name/candidate_id/candidate_version/artifact_digest/seal_digest 各一） | `RUN_REQUEST_CACHE_MISMATCH` | 实现前为 `CANDIDATE_ID_MISMATCH` 等 artifact↔identity 码；实现后统一 cache↔intent 码 | PASS |
| E. run_request tampering | Intent=A（已 seal） | store.run_request A→B，不刷新 anchor | `INTEGRITY_STORE_CORRUPTED` | 实现前后均为 `INTEGRITY_STORE_CORRUPTED`（adopt 的 anchor 验证已闭合） | Already closed |
| F. positive canonical run | Intent/registry/cache/authority/frozen/artifact 全 A | 无 | ALLOW A | 实现前后均 ALLOW A | Already closed |
| G. rebuild + tamper | Intent=A，cache 删除后开始 rebuild | rebuild 结果写 B | REJECT | 实现前 FileNotFoundError；实现后 rebuild 后重读比对，`RUN_REQUEST_CACHE_MISMATCH`，docker 未调用 | PASS |
| H. missing run_request | canonical entry, cache=A | store 无 run_request | `MISSING_RUN_REQUEST` | 实现前 ALLOW A（从 b3_entry 推断）；实现后 REJECT，不 fallback legacy | PASS |
| I. legacy compatibility | legacy candidate, b3_entry v1 | 无 | ALLOW | 实现前后均 ALLOW（legacy 不要求 run_request） | PASS |

最终不变量成立：

```text
Trusted Run Intent = A；Registry = B；b3_entry = B  ->  REJECT
Trusted Run Intent = A；b3_entry = missing         ->  REBUILD from A -> ALLOW A
run_request A 被 tamper 成 B（sealed）              ->  INTEGRITY_STORE_CORRUPTED
```

## Error Semantics

| 错误码 | 触发条件 |
|---|---|
| `RUN_REQUEST_CACHE_MISMATCH` | b3_entry 存在但与 anchored run_request 不一致（name / candidate_id / candidate_version / artifact_digest / seal_digest 任一）；b3_entry 不可读 / 非对象；rebuild 结果被篡改后重读不一致 |
| `INTEGRITY_STORE_CORRUPTED` | trust anchor 验证失败：sealed 后 run_request 或其他 anchored store 内容被改写且 anchor 未刷新。先于 cache 比对触发 |
| `MISSING_RUN_REQUEST` | canonical entry（`artifact_identity == CANONICAL_ARTIFACT_IDENTITY_V1`）但 store 无 run_request；或 run_request 非对象 / 缺 name。禁止从 b3_entry/registry 推断 |
| `MISSING_IDENTITY` | run_request 存在但四元组缺字段（复用 Phase 9-B.3 语义） |

Phase 9-B.3 的 artifact↔identity 错误（`CANDIDATE_ID_MISMATCH` /
`CANDIDATE_VERSION_MISMATCH` / `ARTIFACT_DIGEST_MISMATCH` /
`SEAL_DIGEST_MISMATCH`）继续保留，用于 cache 一致之后对实际选中的
candidate/artifact 的验证，不被 cache mismatch 语义替代。

## Tests

| Suite | Result |
|---|---|
| Phase 9-B.5 targeted（`docs/archaeology/unified-runtime/phase9b5/test_anchored_run_intent.py`） | 12 passed |
| Phase 9-B.1 regression | PASS（含 1 处 b3_entry 用例按新 cache 契约补齐四元组） |
| Phase 9-B.3 regression | PASS |
| Phase 8.2 / 8.4.3 / tests/test_minimal.py | PASS |
| Full suite（`pytest -q`） | 859 passed, 11 skipped, 19 subtests passed |
| Live B3（真实 Docker daemon 29.1.3） | `HARNESS_LIVE_B3_PASS`：临时 canonical state，先写 cache 再删除以走 rebuild；Run Intent A -> Runtime A；oracle PASS；invoke exit 0；重建 b3_entry 与 run_request 一致 |

## Remaining Open

```text
O1 = OPEN（verify_at_mount 返回与内核 bind mount 的 OS 级 TOCTOU；本阶段不处理）
Q2-Q6（多 active run request、task/phase 入 intent、未 seal 保护边界、
      b3_entry 去留、legacy 最终处置）= OPEN（沿用 Design Freeze）
```

发现项（非本阶段引入）：当前 `pilot/state` 是 Phase 8.2 guard 之前的 legacy
fixture（entry.adoption=null、无 adoption_store.json）；对它直接运行
`phase_future("b3")` 会因 `adopt()` 要求 adoption_store 而
`MISSING_ADOPTION_STORE`，这是既有边界，本阶段未迁移该 state。

## Scope

`git diff --name-only` 仅包含：

```text
pilot/harness.py
pilot/runtime_adoption_guard.py
docs/archaeology/unified-runtime/phase9b1/test_production_trust_chain.py
```

新增（未跟踪）：

```text
docs/archaeology/unified-runtime/phase9b5/test_anchored_run_intent.py
docs/archaeology/unified-runtime/phase9b4/08-phase9b5-implementation-report.md
```

未修改 anchor schema；未新增数据库 / 服务 / 外部依赖；未处理 O1；未触碰
legacy trust model 与 registry promote/issue_authority 既有写路径。
