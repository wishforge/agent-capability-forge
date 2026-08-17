# 71 — AdoptionAuthority Production（Phase 8.1）

> 阶段：Phase 8.1（PromotionDecision -> AdoptionAuthority Producer ->
> Persistent AdoptionAuthority -> Registry Guard 的最小生产接线）。
> 基线：70（Phase 8，MINIMAL_ENFORCEMENT_VALID_WITH_UNKNOWN）、69（Phase
> 7.6）、68 / 67 / 66（Phase 7.5 / 7.4.1 / 7.4）、65 / 64（Phase 7.3.1 /
> 7.3）、57（Phase 7）。
> 约束遵守：未修改 E.5–E.7.1、Phase 7–7.6 冻结 artifacts、48/51/52/53、
> codex/、control-plane/、openhands/；未接 Runtime / Cordis / Langfuse；
> 未做 E.8；未做 production-wide rollout；未运行 live LLM / provider；
> 未 commit / push。

## 1. Executive Summary

回答本阶段核心业务问题：

> Registry 已经会检查 AI 上岗许可证（AdoptionAuthority），但许可证由谁
> 签发、存在哪里、如何防伪造、Registry 如何拿到同一张许可证？

本阶段实现：

```text
Evaluation PASS + operator confirm
    -> PromotionDecision 记录（value=PROMOTE, gate_result=PASS）
    -> AdoptionAuthority Producer（pilot/adoption_authority_producer.py）
    -> adoption_store.json 持久化（decision/run/policy/candidate/
       lifecycle/provenance/evidence/authorities）
    -> 确定性 authority_id（内容绑定，非加密签名）
    -> registry.promote(adoption_authority)
    -> state="promoted"
```

最终判定：

```text
AUTHORITY_PRODUCER_VALID_WITH_UNKNOWN
```

```text
FACT      PROMOTE 现在能产生唯一、binding 完整的 AdoptionAuthority，
          持久化后可直接被 registry.promote() 采用（24 项 Phase 8.1
          tests + 18 项 Phase 8 tests 通过）。
UNKNOWN   issuer trust 只有确定性 id、无密码学签名；flat JSON 存储无
          write-once / CAS；authority 记录本身可被直接编辑。
```

## 2. Current PromotionDecision Path（考古结果）

全仓 `rg` `PromotionDecision|promotion.decide|decide(` 结果：

```text
FACT      唯一 PromotionDecision 生产者：
          docs/archaeology/deepseek-harness/evaluation/promotion.py:87
          class PromotionDecision（frozen dataclass）
          :230 decide() -> 返回 immutable PromotionDecision
FACT      decide() 无任何写路径：不写 DB / 不写 registry / 不写文件；
          决策只在内存中返回（P-CFG-09，69 §2）。
FACT      decide() 的 decision 取值是 REJECTED / CANARY / PENDING /
          PROMOTED（promotion.py:294-304），而 Phase 7.4/7.6/8 的
          adoption store 契约要求 decision.value == "PROMOTE"
          （70 §5；66 §6）。命名冲突不是同一语义：
          "PROMOTED" 在 Phase 8 一律 DECISION_NOT_PROMOTE。
FACT      pilot 真实路径从未调用 archaeology decide()：harness
          phase_b3_build 只凭 evaluation["verdict"]=="PASS" +
          confirm.json 调 registry.promote()（Phase 8 前）。
FACT      pilot/harness.py:600 是 registry.promote() 的唯一调用方，
          Phase 8 后旧 5 参数调用被 MISSING_AUTHORITY 挡住。
```

因此真实调用链（本阶段前）：

```text
Evaluation（forge/evaluator.py，verdict=PASS）
  -> harness phase_b3_build 自行判定
  -> registry.promote() 5 参数旧调用
  -> ADOPTION_BLOCKED（Phase 8 起）
```

不存在“Evaluation -> Gate -> PromotionDecision -> registry”的真实接线；
PromotionDecision 只有 archaeology 内存对象，无持久化、无消费端。

## 3. Authority Producer

新增生产模块：`pilot/adoption_authority_producer.py`。

```text
issue_authority(registry_root, candidate_dir, evaluation, *,
                confirm, policy, decision, run, provenance,
                evidence, lifecycle) -> dict
```

输入输出：

```text
成功：{"verdict": "AUTHORITY_ISSUED",
       "authority": AdoptionAuthority,
       "store_path": <registry_root>/adoption_store.json}
失败：{"verdict": "AUTHORITY_ISSUANCE_BLOCKED",
       "violations": [{"code", "message"}], "authority": None}
```

Producer 不做 Evaluation / Promotion 决策（Control Plane 仍是决策权威），
只把已批准采用的决定投影成可机械验证的凭证。默认 decision 从
`evaluation_id / evaluated_at / candidate.json / manifest.json /
artifact dir` 构造，`value=PROMOTE, gate_result=PASS`。

Producer 拒绝（全部 fail-closed，且 blocked 时不写 store）：

```text
HUMAN_CONFIRM_MISSING        confirm.json confirm != true
EVALUATION_MISSING           无 evaluation_id
EVALUATION_NOT_PASS          默认 decision 且 evaluation.verdict != PASS
CANDIDATE_METADATA_MISSING   candidate.json / manifest.json 缺失或损坏
DECISION_NOT_PROMOTE         decision.value == HOLD / REJECT / 其他
GATE_NOT_PASS                decision.gate_result != PASS
POLICY_NOT_REGISTERED        decision.policy_ref 不在 policies
POLICY_NOT_FROZEN            policy.frozen != true
RUN_MISSING / RUN_MISMATCH   run 缺失或与 decision 不一致
CANDIDATE_ID_MISMATCH / CANDIDATE_VERSION_MISMATCH
POLICY_VERSION_MISMATCH / RUN_POLICY_MISMATCH
ARTIFACT_DIGEST_MISMATCH     含真实 artifact 字节与 authority digest 不一致
PROVENANCE_INCOMPLETE        policy/evidence_manifest/run_ids/
                             immutable_artifact_refs 任一缺失
AUTHORITY_BINDING_MISMATCH   已存在 store 记录与本次请求冲突
REVOKED_DECISION / STALE_DECISION / DECISION_TAMPERED /
EVIDENCE_TAMPERED / INVALID_LIFECYCLE / CANDIDATE_REJECTED
```

以上不是 producer 重新实现的第二套校验：producer 在持久化前调用
`pilot/adoption_authority.py::validate()`（与 Registry 同一校验器），
任何 violation 都返回 `AUTHORITY_ISSUANCE_BLOCKED` 且不落盘。

## 4. Authority Store

沿用 Phase 8 的 `<registry_root>/adoption_store.json`（`load_store` /
`STORE_FILENAME` 复用，不新增 storage 类型）。Phase 8.1 新增 `authorities`
记录列表；其余 key 与 Phase 8 契约一致：

```text
policies     {policy_ref: {version, registered, frozen, content_ref}}
candidates   {candidate_id: {version, created_at, forged_artifact_digest}}
runs         [{run_id, candidate_id, candidate_version, artifact_digest,
               policy_ref, policy_version, status, created_at}]
evidence     [{evidence_id, run_id, recorded_hash, current_hash}]
provenance   {candidate_id: {policy, evidence_manifest, run_ids,
               immutable_artifact_refs}}
decisions    [{decision_id, candidate_id, candidate_version, run_id,
               policy_ref, policy_version, artifact_digest, value,
               gate_result, created_at, recorded_hash, current_hash}]
lifecycle    {candidate_id: {status, transitions}}
revocations  [{revocation_id, candidate_id, candidate_version,
               decision_id, status, reason}]
authorities  [AdoptionAuthority 完整记录]
```

Authority 记录字段：

```text
authority_id / candidate_id / candidate_version /
promotion_decision_id / evaluation_run_id / policy_version /
artifact_digest / provenance / issued_at / status
```

`issued_at` 使用真实来源 = `evaluation.evaluated_at`（即
decision.created_at），不伪造。`expires_at` / `revoked_at` 当前无真实
来源，不出现。写入采用同目录临时文件 + `os.replace`（原子替换）；这是
flat JSON 下的最小 crash-safety，不是 write-once / 事务（UNKNOWN，见
§14 / §15）。

## 5. Binding

Authority 是 Decision 的 binding projection，逐字段由 producer 从
decision 记录复制；producer 写入前用 `validate()` 验证：

```text
authority.candidate_id       == decision.candidate_id == run.candidate_id
authority.candidate_version  == decision == run == candidate.version
authority.promotion_decision_id -> decision 必须存在且 value=PROMOTE
authority.evaluation_run_id  == decision.run_id
authority.policy_version     == decision == run == policy.version
authority.artifact_digest    == decision == run ==
                               candidate.forged_artifact_digest
                               == 真实 artifact dir_digest
authority.provenance         run_id 必须在其 run_ids 内
```

任一不一致 -> `AUTHORITY_ISSUANCE_BLOCKED`；任何绕过 producer 直接构造
的 authority 在 Registry 重验时同样被挡。

注意（FACT）：capabilityizer 的
`manifest.provenance.forged_artifact_digest` 与 registry 的 `dir_digest`
canonical 形状不同（`{"files":[{path,digest}]}` vs `{path: digest}`），
两者字节不相等。Phase 8 validator 要求 candidate.forged_artifact_digest
== dir_digest，因此 store 内记录的是 registry 可重算的 `dir_digest`；
manifest 的 forged digest 仍保留为 evidence，但不作为 enforcement digest。

## 6. Idempotency

确定性 id：

```text
decision_id  = "dec-" + sha256(candidate_id|version|run_id)[:12]
authority_id = "auth-" + sha256(candidate_id|version|decision_id)[:16]
```

同一 candidate + version + decision（同一 run）重复 issue：

```text
第一次  -> 写 store，返回 AUTHORITY_ISSUED（唯一 authority）
第二次  -> 复用已存在记录，返回同一 authority_id，不产生第二个
           decision / authority
```

测试覆盖：`test_same_decision_twice_is_idempotent`（authorities 长度 1）。
已存在 store 记录与请求不一致 -> `AUTHORITY_BINDING_MISMATCH`，不覆盖。

## 7. Revocation / Supersession

仓库原本没有任何 revoked / superseded / expired / disabled 真实存储
（69 §6 已确认）。最小实现语义：

```text
authority 记录本身 immutable（status="ISSUED"，不直接改写）
状态变化 = append-only revocations 事件：
  {revocation_id, candidate_id, candidate_version, decision_id,
   status: "REVOKED" | "SUPERSEDED", reason}
Registry 通过既有 REVOKED_DECISION 检查阻止采用（70 §5）
```

`expired` 无 TTL 来源，不实现（UNKNOWN）。

## 8. Registry Integration

Registry 未被重写。`registry.promote(adoption_authority=...)` 仍是
Primary Enforcement（70 的全部检查保留）。本阶段只新增一处信任边界：

```text
pilot/adoption_authority.py
  authority_id_for(candidate_id, candidate_version, decision_id)
  violations_for_authority() 新增 AUTHORITY_ID_MISMATCH：
  authority_id 必须是该 binding 的确定性 producer id
```

因此随机 / 伪造 authority_id（如 "auth-1"、"auth-forged"）被 Registry
拒绝，即使其他 binding 字段都正确。Phase 8 的 `test_registry_enforcement.py`
fixture 相应改为确定性 id（2 处，属于 Phase 8 测试契约更新，非降级）。

完整链（IMPLEMENTED）：

```text
issue_authority -> 写 adoption_store.json -> registry.promote(authority)
  -> validate() 重验 -> state="promoted"
```

## 9. Human Approval -> Automatic Adoption

Pilot 的“人审批”记录是 `pilot/confirm.json`（capabilityize 已要求）。
Phase 8.1 把同一 confirm 作为 producer 的前置条件：

```text
confirm.confirm == true（缺失/为 false -> HUMAN_CONFIRM_MISSING）
```

人不再手工改 state / active / version：harness 在 evaluation PASS +
confirm 后自动 issue authority -> registry.promote -> PROMOTED。
没有实现 event bus；hook 边界 = `issue_authority()` 调用点
（IMPLEMENTED 于 pilot/harness.py phase_b3_build）。

## 10. Legacy Caller Migration

旧调用 `pilot/harness.py:600`
`registry.promote("F+", name, cand, evaluation, self.registry_root)`
迁移为：

```python
issued = producer.issue_authority(self.registry_root, cand, evaluation,
                                  confirm=confirm)
if issued["verdict"] != "AUTHORITY_ISSUED":
    raise RuntimeError("B3 authority issuance BLOCKED: " + ...)
entry = registry.promote("F+", name, cand, evaluation, self.registry_root,
                         adoption_authority=issued["authority"])
```

分类：

```text
IMPLEMENTED   producer integration（唯一旧调用方）
LEGACY_CALLER 5 参数 promote() 继续 fail-closed：
              MISSING_AUTHORITY（Phase 8 行为不变）
NOT_IMPLEMENTED fallback bypass（不存在；禁止为旧 caller 降级检查）
```

## 11. Issuer Trust

当前仓库没有签名 / JWT / 证书基础设施，本阶段不伪造。实现的信任边界：

```text
authority_id 是 binding 内容的确定性哈希投影
  -> Registry 拒绝任意 / 未知 authority_id
  -> 同一 binding 只能有唯一 id（幂等）
```

局限（UNKNOWN）：确定性哈希不是密码学签名；任何能读 store / 代码的人
都能算出同一 id。flat JSON 可整体编辑（改 binding + 改 id + 改 hash）。
真信任锚（签名私钥 / TPM / 外部 KMS）不在本仓库范围。

## 12. Failure-Closed

```text
任何 blocked 路径：
  producer 不写 adoption_store.json（store 文件字节不变）
  registry 不 copytree、不写 entry（70 §6 不变）
旧 5 参数 promote() 无 authority -> MISSING_AUTHORITY
无 store -> MISSING_ADOPTION_STORE
无 confirm / 无 decision / HOLD / REJECT / missing policy /
unfrozen policy / missing run / binding mismatch / missing provenance /
missing digest / forged authority_id -> 全部 blocked
```

Phase 8.1 每个 blocked 测试断言 store 快照与 registry entry 均不变。

## 13. FACT / INFERENCE / UNKNOWN

```text
FACT      唯一真实 PromotionDecision 生产者是 archaeology decide()
          （内存、无持久化、decision="PROMOTED" 与 store 契约不同）。
FACT      pilot 真实路径的 promotion 依据是 evaluation PASS + confirm；
          Phase 8.1 把它持久化为 value=PROMOTE 的 decision 记录。
FACT      issue_authority() 成功时写完整 adoption_store.json 并返回
          确定性 authority；registry.promote(authority) 通过后
          state="promoted"（integration test 通过）。
FACT      重复 issue 同一 candidate+version+decision 返回同一
          authority_id，store 只有一个 decision/authority。
FACT      REVOKED / SUPERSEDED revocation 使 Registry 阻断采用
          （REVOKED_DECISION）。
FACT      Registry 现在拒绝非确定性 authority_id（AUTHORITY_ID_MISMATCH）。
INFERENCE producer 的 validate() 与 Registry 的 validate() 是同一函数，
         因此 issuance 与 enforcement 语义一致。
UNKNOWN   flat JSON 持久化 durability：os.replace 原子但 last-writer-wins，
          无 CAS / 事务 / write-once。
UNKNOWN   密码学 issuer trust：无签名基础设施。
UNKNOWN   store 读取与 entry 写入之间仍有 TOCTOU（70 §8 不变）。
UNKNOWN   discover() 不重算 artifact digest（70 §9 不变）。
```

## 14. MVP Boundary

```text
IMPLEMENTED  AdoptionAuthority producer + adoption_store 持久化
IMPLEMENTED  确定性 authority_id + Registry AUTHORITY_ID_MISMATCH
IMPLEMENTED  harness 唯一旧调用迁移（producer integration）
IMPLEMENTED  REVOKED / SUPERSEDED -> Registry blocked
NOT_IMPLEMENTED Runtime / Cordis / Langfuse / E.8 / production rollout
NOT_IMPLEMENTED write-once / DB / event bus / signature
```

## 15. Remaining Unknowns

```text
1. flat JSON 可被直接编辑：改 decision + authority + hash 可绕过
   （write-once / DB / signed log 之前仍 UNKNOWN）。
2. store 并发写没有锁：两个并发 producer 最后一个 os.replace 赢
   （本仓库单进程 harness 路径不受影响）。
3. authority 没有 expires_at（无 TTL 来源）。
4. policy 记录是冻结规则的引用标记，producer 不重新计算 promotion
   rule；决策权威仍在 harness/evaluation（Control Plane 未实体化）。
5. discover() / runtime activation 不重验 digest 或 authority
   （Phase 8 已知 bypass 保留）。
```

## Validation

```text
python3 -m pytest docs/archaeology/unified-runtime/phase8.1 -q
  -> 24 passed
python3 -m pytest docs/archaeology/unified-runtime/phase8 -q
  -> 18 passed（fixture 更新为确定性 authority_id）
python3 -m pytest docs/archaeology/unified-runtime/phase7.2 \
  docs/archaeology/unified-runtime/phase7.3 \
  docs/archaeology/unified-runtime/phase7.4 \
  docs/archaeology/unified-runtime/phase7.5 \
  docs/archaeology/unified-runtime/phase7.6 -q
  -> 107 passed
python3 -m unittest discover -s tests -q
  -> 11 tests OK
python3 -m compileall -q pilot \
  docs/archaeology/unified-runtime/phase7.2 \
  docs/archaeology/unified-runtime/phase7.3 \
  docs/archaeology/unified-runtime/phase7.4 \
  docs/archaeology/unified-runtime/phase7.5 \
  docs/archaeology/unified-runtime/phase7.6 \
  docs/archaeology/unified-runtime/phase8 \
  docs/archaeology/unified-runtime/phase8.1 tests
  -> clean
```

未运行 live LLM / provider。

## Final Verdict

```text
AUTHORITY_PRODUCER_VALID_WITH_UNKNOWN
```

```text
PROMOTION PROMOTE 已能产生唯一、binding 完整的 AdoptionAuthority，
持久化到 adoption_store.json，并被 registry.promote() 直接采用；
REVOKED / SUPERSEDED / stale / 伪造 id / 全部 mismatch 均 fail-closed。
issuer trust（无签名）、persistence durability（flat JSON 无 CAS /
write-once）、authority 记录自身可编辑性仍 UNKNOWN。
```
