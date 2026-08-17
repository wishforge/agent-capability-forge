# 70 — Minimal Production Adoption Enforcement（Phase 8）

> 阶段：Phase 8（第一次真实代码 Enforcement，只接入一个真实 Adoption
> Path：pilot / `registry.promote()`）。
> 基线：69（Phase 7.6，ADOPTION_AUTHORITY_VALID_WITH_UNKNOWN）、68
> （Phase 7.5）、67 / 66（Phase 7.4 / 7.4.1）、65（Phase 7.3.1）、64
> （Phase 7.3）。
> 约束遵守：未修改 Runtime activation、Cordis PluginManager、Langfuse、
> E.5-E.7.1、Phase 7-7.6 文档/历史 artifacts、PromotionDecision
> semantics、Evaluation / Regression / Attribution / Promotion Gate；未做
> E.8；未做生产 rollout；未接多个 adoption path；未 commit / push。

## 1. Scope

本阶段只改：

```text
pilot/registry.py                真实 Registry 代码（唯一被改的 production）
pilot/adoption_authority.py      production AdoptionAuthority contract adapter
docs/archaeology/unified-runtime/phase8/test_registry_enforcement.py
docs/archaeology/unified-runtime/70-minimal-production-adoption-enforcement.md
```

只接入一个真实 Adoption Path：`pilot/registry.promote()`。

不改：

```text
Runtime activation（pilot/harness.py phase_future）
Cordis PluginManager / ToolRuntime / CodexAdapter
Langfuse
E.5-E.7.1、48/51/52/53、Phase 7 / 7.1-7.6 artifacts
PromotionDecision semantics、Evaluation、Regression、Attribution、
Promotion Gate
```

## 2. Existing Registry Path

考古结果（`rg` 全仓扫描 `state.*promoted` / `promote(` / `PROMOTED` /
`registry.promote`）：

```text
FACT   唯一写 state="promoted" 的代码路径是 pilot/registry.py:48 promote()
       （entry JSON 写 state="promoted"，原 36 行，Phase 8 后迁移到
       promote() 内部）。
FACT   pilot/harness.py:600 是 registry.promote() 的唯一调用方：
       registry.promote("F+", name, cand, evaluation, self.registry_root)
       —— 不带任何 decision / authority。
FACT   pilot/registry.py:160 discover() 只检查 entry["state"] == "promoted"，
       不验证 adoption binding。
FACT   src/forge/bundle_producer.py:443 Rule 13 禁止 bundle 内出现
       "promoted" 等 adoption state（只禁，不写）。
FACT   pilot/state/registry/F+/csv-clean-statistical-report.json 是一份
       Phase 8 之前已经写好的 state="promoted" 历史数据文件；它不是代码
       写路径，但 discover() 仍会把它当作 promoted 返回。
```

结论：修改 `promote()` 后，pilot 路径内不再有第二个代码写点直接写
`state="promoted"`。但“直接编辑磁盘 JSON”和“历史已 promoted 数据”仍是
数据级绕过（§9）。

## 3. AdoptionAuthority Integration

复用 Phase 7.6 的 AdoptionAuthority 定义（`69-adoption-authority-unification.md`
§6），不重新定义 semantics：

```text
authority_id
candidate_id
candidate_version
promotion_decision_id
evaluation_run_id
policy_version
artifact_digest
provenance {policy, evidence_manifest, run_ids, immutable_artifact_refs}
issued_at（可选，存在时必须 == decision.created_at）
```

`promote()` 保持原有 5 个位置参数兼容旧调用，新增 keyword-only：

```text
adoption_authority: dict | None = None
```

旧 5 参数调用（无 authority）→ `ADOPTION_BLOCKED`（`MISSING_AUTHORITY`），
不能 promoted。

### 最小 integration boundary（IMPLEMENTED vs UNKNOWN）

Production validator（`pilot/adoption_authority.py`）从
`<registry_root>/adoption_store.json` 读取 records：

```text
policies / candidates / runs / decisions / lifecycle / provenance / evidence
```

```text
IMPLEMENTED  验证逻辑本身（decision / run / policy / candidate / lifecycle /
             digest / provenance / stale / tamper / revoke 检查）。
IMPLEMENTED  成功 entry 记录 adoption binding（§10）。
UNKNOWN      真实仓库当前没有任何 producer 写 adoption_store.json；
             pilot/harness.py 旧调用因此现在会
             ADOPTION_BLOCKED（MISSING_ADOPTION_STORE）。
             这是 Enforcement 的预期后果：没有 decision store 就没有
             promotion，而不是伪造一个 decision。
```

没有从 `docs/archaeology/` 离线 harness import 任何代码：production
validator 是自包含的最小 contract adapter，与 Phase 7.6 语义一致但
不依赖 archaeology 代码。

## 4. Registry Primary Guard

`promote()` 现在是：

```text
1. authority 存在？（无 -> MISSING_AUTHORITY）
2. adoption_store.json 存在？（无 -> MISSING_ADOPTION_STORE）
3. 计算待复制 artifact 目录的真实 sha256（dir_digest）
4. validate(adoption_authority, store, actual_digest)
   - load decision / run / policy / candidate / lifecycle
   - 校验全部 binding + digest + provenance + stale/tamper
5. 任一失败 -> AdoptionBlocked（ADOPTION_BLOCKED + reason codes）
6. entry 已存在且 binding 相同 -> 幂等返回（§7）
7. entry 已存在且 binding 不同 -> ENTRY_BINDING_CONFLICT
8. 只有全部通过才 copytree artifact + 写 state="promoted"
```

禁止的 fallback 全部不存在：没有 latest / previous / active /
candidate-state fallback，没有 implicit allow。

## 5. Failure-Closed

以下任一情况都是 `ADOPTION_BLOCKED`（生产 validator 与 Phase 7.6
离线 validator 同码）：

```text
MISSING_AUTHORITY / MISSING_ADOPTION_STORE
REQUEST_METADATA_MISSING
MISSING_DECISION / DECISION_NOT_PROMOTE / GATE_NOT_PASS
RUN_MISSING / RUN_MISMATCH
CANDIDATE_ID_MISMATCH / CANDIDATE_VERSION_MISMATCH
POLICY_VERSION_MISMATCH / POLICY_NOT_REGISTERED / POLICY_NOT_FROZEN
RUN_POLICY_MISMATCH
ARTIFACT_DIGEST_MISMATCH（含真实 artifact 字节与 authority digest 不一致）
PROVENANCE_INCOMPLETE
DECISION_TAMPERED / EVIDENCE_TAMPERED
MISSING_LIFECYCLE / INVALID_LIFECYCLE / CANDIDATE_REJECTED
REVOKED_DECISION（revocations key 存在时）
STALE_DECISION / MISSING_DECISION_TIMESTAMP
AUTHORITY_ISSUED_AT_MISMATCH
ENTRY_BINDING_CONFLICT
```

decision 三态保持 Phase 7.4/7.6 语义：

```text
PROMOTE      = decision.value（授权）
PROMOTABLE   = lifecycle.status（可被采用）
PROMOTED     = registry entry state（已采用）
```

`decision.value == "PROMOTED"` 一律 `DECISION_NOT_PROMOTE`；registry
不能 `PROMOTE -> PROMOTED`，必须是
`value==PROMOTE + lifecycle==PROMOTABLE + 合法 AdoptionAuthority ->
PROMOTED`。

## 6. State Safety

所有 BLOCK case 在 `promote()` 写任何文件之前抛出：

```text
authority/store 验证失败       -> 不 copytree、不写 entry
entry 已存在但 binding 不同     -> 不覆盖、不写任何状态
旧调用无 authority             -> 不写任何状态
```

测试中每个 BLOCK case 断言：

```text
registry/<family>/<name>.json 不存在
registry/<family>/<name>/artifact 不存在
（对已 promoted 的 entry：再次非法请求后 entry 文件内容不变）
```

## 7. Idempotency

同一合法 AdoptionAuthority 重复调用：

```text
第二次调用重新走完整验证；
entry 已存在且 adoption binding 全部一致 -> 直接返回已有 entry；
不创建第二个 entry / 不改写已写入的 binding / 不产生第二个 decision；
最终 state 保持 "promoted"。
```

同一 name 但不同 binding → `ENTRY_BINDING_CONFLICT`，原 entry 不动。
测试覆盖：`test_same_valid_adoption_twice_is_idempotent`、
`test_existing_entry_different_binding_blocked`。

## 8. TOCTOU

当前最小设计：

```text
1. 读取 adoption_store.json（check）
2. 验证 authority / digest（check）
3. copytree artifact
4. 通过 os.link(tmp, entry_path) 独占创建 entry（create-if-absent）
```

`os.link` 是 flat-file 下最小的 CAS：两个并发 promote 对同一 name 竞争时，
只有一个能创建 entry；另一个 re-read 后要么幂等返回（binding 相同），
要么 `ENTRY_BINDING_CONFLICT`（binding 不同）。这防止“两个不同 authority
并发写同一 entry、后者覆盖前者”。

```text
UNKNOWN  step 1 读取的 store 本身没有事务边界：验证之后、写 entry 之前，
         decision/policy/lifecycle JSON 仍可被外部修改。flat JSON
         没有 DB transaction / CAS，本阶段不假装解决。
UNKNOWN  artifact 目录在 copytree 后仍可被修改；runtime 不重新验证 digest
         （discover() 未改）。
```

## 9. Bypass Paths Remaining

```text
BYPASS_REMAINS  直接编辑磁盘上的 registry JSON（把任意 entry 改成
                state="promoted" 或改 adoption binding）。
BYPASS_REMAINS  历史数据文件 pilot/state/registry/F+/
                csv-clean-statistical-report.json 已是 promoted，
                无 adoption binding；discover() 仍返回它。
BYPASS_REMAINS  直接编辑 artifact 目录字节（promoted 后无 digest 复查）。
BYPASS_REMAINS  b3_entry.json / skill_ref.json / b1_skill_ref.json
                指针仍可手工编辑（P-CFG-01/02/03，Phase 7.6 已分类）。
BYPASS_REMAINS  pilot/harness.py:600 仍按旧签名调用 -> 现在被
                MISSING_AUTHORITY / MISSING_ADOPTION_STORE 挡在真实
                路径外；直到 harness 携带持久化 AdoptionAuthority。
BYPASS_REMAINS  Runtime / Cordis / ToolRuntime / Langfuse 完全未接
                （Phase 8 范围外）。
```

因此：本阶段只证明“registry.promote() 这一个写点 fail-closed”，不宣称
整个系统安全。

## 10. Audit / Provenance

成功 promotion 的 entry 增加 `adoption` 块：

```text
adoption.candidate_id
adoption.candidate_version
adoption.promotion_decision_id
adoption.evaluation_run_id
adoption.policy_version
adoption.artifact_digest
adoption.provenance
adoption.adopted_at
```

```text
IMPLEMENTED  以上字段随 entry JSON 持久化。
UNKNOWN      持久化“不可变性”：entry / adoption_store 都是 flat JSON，
             可被直接编辑或覆盖，不是 write-once / immutable audit log。
             不要把 flat JSON 记录称为“不可变审计”。
```

## 11. Runtime / Langfuse still out of scope

```text
未改 phase_future() / docker_launch（P-RT-01）
未改 PluginManager.register()/install()（P-RT-03）
未改 ToolRuntime.register()/execute()（P-RT-05）
未改 CodexAdapter(rollout_path)（P-RT-07）
未改 Langfuse label / isActive 指针（P-EXT-02）
```

Registry 的 PROMOTED 不再等于“runtime 会安全执行”；runtime 侧 digest /
authority 复查仍是下一阶段。

## 12. FACT / INFERENCE / UNKNOWN

```text
FACT      pilot/registry.py:48 promote() 现在要求 adoption_authority +
          adoption_store.json，任何缺失/非法/mismatch ->
          ADOPTION_BLOCKED，且 state 不变（18 项真实路径测试覆盖）。
FACT      唯一代码写 state="promoted" 的路径是 promote()；仓库中没有
          其他代码路径直接写 state="promoted"。
FACT      合法 AdoptionAuthority（decision/run/policy/candidate/
          lifecycle/digest/provenance 全匹配 + 真实 artifact digest
          匹配）-> state="promoted"。
FACT      同一合法 authority 重复调用幂等；不同 binding 不覆盖。
INFERENCE 只要 store 有 producer，harness 或任何调用方带 authority 即可
          promotion；当前 harness 旧调用不带 -> 被挡。
UNKNOWN   adoption_store.json 持久化 / producer / write-once。
UNKNOWN   TOCTOU：store 读取与 entry 写入之间无事务边界。
UNKNOWN   audit 不可变性（flat JSON 可编辑）。
```

## 13. MVP Limitations

```text
- 没有 decision/policy/lifecycle 的 producer：真实 pilot 路径现在
  fail-closed（无 store -> MISSING_ADOPTION_STORE），不是“自动恢复”。
- flat JSON 无 CAS（仅 entry 创建用 os.link 独占）；store 本身无事务。
- discover() 不验证 adoption binding，历史 promoted entry 仍可见。
- artifact 复制后无不可变引用，promote 后字节可被改。
- 只接 registry.promote() 一个 adoption path。
```

## 14. Next Step

```text
1. 为 adoption_store.json 增加 producer（PromotionDecision 持久化 ->
   decision/run/policy/lifecycle records）。
2. harness phase_b3_build 改为从持久化 decision 构造 AdoptionAuthority
   再调用 promote()。
3. discover() / runtime activation 前重算 artifact digest 并验证同一
   authority（P-RT-01 次级 guard）。
4. 评估 write-once / append-only store，闭合 flat JSON 可编辑绕过。
5. 之后才谈 Runtime / Langfuse / E.8。
```

## Validation

```text
python3 -m pytest docs/archaeology/unified-runtime/phase7.2 \
  docs/archaeology/unified-runtime/phase7.3 \
  docs/archaeology/unified-runtime/phase7.4 \
  docs/archaeology/unified-runtime/phase7.5 \
  docs/archaeology/unified-runtime/phase7.6 \
  docs/archaeology/unified-runtime/phase8 -q
  -> 125 passed

python3 -m compileall -q pilot \
  docs/archaeology/unified-runtime/phase7.2 \
  docs/archaeology/unified-runtime/phase7.3 \
  docs/archaeology/unified-runtime/phase7.4 \
  docs/archaeology/unified-runtime/phase7.5 \
  docs/archaeology/unified-runtime/phase7.6 \
  docs/archaeology/unified-runtime/phase8
  -> clean
```

未运行 live LLM / provider。

## Final Verdict

```text
MINIMAL_ENFORCEMENT_VALID_WITH_UNKNOWN
```

```text
registry.promote() 已经 fail-closed：
没有 AdoptionAuthority + adoption_store 或任何 binding/missing/非法
输入 -> ADOPTION_BLOCKED，state 不变；
只有合法 AdoptionAuthority（含真实 artifact digest 匹配）-> PROMOTED。
TOCTOU / store 持久化 / audit 不可变性仍 UNKNOWN。
```
