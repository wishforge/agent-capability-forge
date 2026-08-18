# Phase 9-C.04 — Run Intent Continuity Audit

基线：`a70a433`。当前 `adoption_store["run_request"]` 是唯一 Run Intent source of
truth。逐条回答任务 §5 的 7 个问题。

## 1. 谁创建它？

`runtime_guard.mark_promoted()`（canonical entry 分支），调用点 `harness.phase_b3_build`
promotion 成功后（harness.py:633）。mark_promoted 与 lifecycle PROMOTED 同一次 store
写入，随后 `write_trust_anchor` 刷新 anchor（runtime_adoption_guard.py:566-625）。

## 2. 谁可以覆盖 active record？

不允许原地覆盖。同 decision 内重复写入 idempotent（`store.get("run_request") !=
run_request` 时才写）；不同内容 → 新 decision/authority + 新 promotion 才能替换
active record（mark_promoted 语义 + producer merge-conflict 模式）。

## 3. 新 promotion 如何替换旧 run intent？

新 promotion（`--force` 或新候选）→ issue_authority 新 decision → promote 新 entry
→ mark_promoted 以新 authority 生成新 run_request，并在同一次 store 写入 + anchor
refresh 中替换旧记录。旧 authority/decision 仍留在 store/ledger，可追溯。

## 4. Runtime 是否始终重新读取 trusted run_request？

是。每次 `phase_future("b3")` 先 `load_trusted_run_request`（先 anchor 验证），再
resolve b3 cache，再 discover（harness.py:698-705）。不缓存跨进程的 intent。

## 5. b3_entry 是否还能影响 candidate selection？

不能。canonical 路径中 b3_entry 只作为 cache：

```text
missing -> 从 run_request 重建（不改变目标）
equal   -> 继续
differ  -> RUN_REQUEST_CACHE_MISMATCH REJECT
```

（runtime_adoption_guard.py:394-413；phase9b5 测试 A-G）。discover 的 name 来自
run_request，不是 b3_entry。

## 6. Registry 是否还能影响 candidate selection？

不能改变候选，只能定位。discover(run_request.name)；即使 registry 同名 entry 被
换成完整合法 B，`verify_at_mount(expected_identity=run_request)` 仍 REJECT（本轮
probe3：`CANDIDATE_ID_MISMATCH + ARTIFACT_DIGEST_MISMATCH + SEAL_DIGEST_MISMATCH`，
docker 未调用）。

## 7. Runtime 是否存在直接从另一个 state 获取 candidate 的路径？

无。canonical 分支唯一来源是 run_request.name → registry entry → adopt report →
verified path。legacy 分支仍从 b3_entry 获取，但只对非 canonical entry 生效，且
canonical entry 在无 run_request 时直接 `MISSING_RUN_REQUEST`（harness.py:706-718）。

## 8. 旁路检查

```text
Trusted Run Intent A
        ↓
some mutable state（registry / b3_entry / artifact_dir / frozen）
        ↓
Candidate B
```

结果：不存在。mutable state 只能影响“被验证对象”，最终 expected identity 永远来自
anchored run_request；B 必然触发 cache mismatch 或 identity/digest mismatch。

```text
RUN_INTENT = CLOSED
```
