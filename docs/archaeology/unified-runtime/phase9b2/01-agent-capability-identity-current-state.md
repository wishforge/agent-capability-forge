# 01 当前 Agent Capability Forge Identity Chain（代码考古）

基线：`034a3b2`。所有结论以真实源码为准；引用的函数均给出文件与行号。

## 1. Candidate Identity

### Candidate identity 在哪里产生？

`src/forge/capabilityizer.py:656`：

```python
candidate_id = "cand-" + uuid.uuid4().hex[:12]
```

`capabilityize()`（:596）把 `candidate_id` 写入 `candidate.json`：
`{"candidate_id", "name", "state": "candidate", "source_bundle_ids"}`。

### identity 的格式是什么？

`cand-<24 hex chars>`：随机、不透明、内容无关的字符串。**不是 digest**。

### Candidate ID 和 artifact identity 是否是同一个概念？

不是。

- `candidate_id` = 生命周期标签（Evaluation/Decision/Authority/Registry 用它关联记录）。
- artifact identity = `CANONICAL_ARTIFACT_IDENTITY_V1`（常量 `capabilityizer.py:41`）+ 由
  `artifact_digest()`（:95）计算的内容 digest。
- 另有 `capability_id`：`capability_id_derivation(namespace, name)`（:182）对
  `{"namespace","name"}` 做确定性 hash，是 capability 级别标识，不是 candidate。

### 哪个字段代表“这个 Candidate 是谁”？

```text
语义上：candidate_id + candidate_version + artifact_digest + seal_digest 四元组。
```

证据：`evaluation_binding_violations()`（capabilityizer.py:392）要求 evaluation 的
`candidate_id / artifact_digest / seal_digest` 三字段与 frozen record 全等；
`authority_id_for()`（adoption_authority.py:45）对 `candidate_id|candidate_version|decision_id`
做确定性 hash。单独任何一个字段都不构成安全身份。

## 2. Artifact Identity

### artifact_identity / artifact_digest 在哪里计算？

- `artifact_layout(directory, allowlist)`（capabilityizer.py:54）：精确布局，实际文件集合必须
  与 allowlist 完全相等；`UNDECLARED_ARTIFACT_FILE` / `ARTIFACT_ALLOWLIST_FILE_MISSING` fail-closed。
- `canonical_artifact_digest(files)`（:49）：`sha256(canonical_json({rel_posix_path: sha256(file_bytes)}))`，
  路径字典序。
- `frozen_artifact_report()`（:89）/ `artifact_digest()`（:95）是上层入口。

### digest 覆盖什么？是否覆盖整个 Candidate？

覆盖**只声明文件**（allowlist-only）。Pilot 路径固定 allowlist = `["main.py"]`
（`freeze_candidate_dir`，:534 附近）。`__pycache__`、日志、生成物不改变 digest，
但精确布局校验会拒绝任何未声明文件。

整个 Candidate 由三层 digest 覆盖：

```text
artifact_digest = sha256(canonical({file: sha256(bytes)}))
manifest_digest = sha256(canonical(manifest))
tests_digest   = sha256(canonical({test file: sha256(bytes)}))
seal_digest    = sha256(canonical(frozen core + 上述三个 digest))
```

### 多 artifact 时如何处理？

当前 allowlist 支持多个文件（布局校验按列表处理），但 Pilot 只声明 `["main.py"]`。
多 artifact / 多目录的完整 intake schema 未实现（phase9b1 报告明确列为 UNKNOWN）。

### declared artifact inventory 在哪里定义？

`candidate["artifact"]["files"]`（allowlist），由 `freeze_candidate_dir` 构造；seal 时
`seal_violations`（:128）强制要求非空 allowlist。

## 3. Seal

### seal_digest 如何产生？覆盖哪些字段？

`seal_digest()`（capabilityizer.py:114）：

```python
payload = {k: candidate[k] for k in FROZEN_CORE_KEYS if k in candidate}
payload["artifact_digest"] = artifact_digest_value
payload["manifest_digest"] = manifest_digest(...)
payload["tests_digest"] = tests_digest_value
return sha256_bytes(canonical_json(payload))
```

`FROZEN_CORE_KEYS`（:53）包括 `schema_version, candidate_id, capability_id, name, version,
source, producer, requester, artifact, manifest, provenance, extensions`。

### seal 是否覆盖 identity + artifact digest？

是。`candidate_id` 在 FROZEN_CORE_KEYS 内，`artifact_digest` 显式加入 payload。
Evaluation / Decision / Authority 被刻意排除（它们是引用 seal 的 evidence）。

### seal 是否是独立 trust object？是否有 version/type？

是。Frozen Candidate = write-once record（`frozen/<candidate_id>.json`）+ snapshot 目录
（`freeze_candidate`，:205）。record 含 `schema: "frozen-candidate-v1"`、`seal_version: "v1"`
（`SEAL_SCHEMA` / `SEAL_VERSION`，:42-43）。

注意：record 级 `schema` / `seal_version` 在 `verify_frozen`（:315）里单独校验，**不进入
seal_digest payload**（DSSE 角度的小缺口，见 06/09）。

## 4. Authority

### authority record 在哪里生成？谁可以生成/修改？

`issue_authority()`（adoption_authority_producer.py:98）生成；条件：

```text
operator confirm == true
evaluation.evaluation_id 存在
issuer 在 PILOT_TRUSTED_ISSUERS allowlist（未设置时回退 deterministic 模式，UNKNOWN issuer）
canonical 新候选必须提供 frozen_root，并全过 frozen/eval/live layout 校验
```

写入不可变 ledger：`write_authority_record()`（adoption_authority.py:307）用
`os.link` 原子 create-if-absent，已有记录不同即 `AUTHORITY_BINDING_MISMATCH`，永不覆盖。
状态变更走 append-only events（`append_authority_event`，:360）。

### 哪些字段被 trust anchor 保护？

trust anchor（`integrity_anchor_violations`，adoption_authority.py:123）锚定：

```text
store_digest                = sha256(canonical(adoption_store.json))
authority_manifest_digest   = sha256({authority_id: sha256(canonical(record))})
revocation_manifest_digest  = sha256(events 文件字节)
```

anchor 是外部 JSON 文件（默认 registry 根的同级 sibling，可用 `PILOT_INTEGRITY_ANCHOR` 覆盖），
**不是密码学签名**；文档明确承认同文件系统写入者可达。

### authority 是否具有 provenance？

有。authority 记录 `provenance` 对象，`PROVENANCE_KEYS = policy, evidence_manifest,
run_ids, immutable_artifact_refs`；运行时缺失任一 key 即 `PROVENANCE_INCOMPLETE`
（runtime_adoption_guard.py:83）。

## 5. Evaluation

### Evaluation 记录什么？

`evaluate()`（src/forge/evaluator.py:24）产出 `evaluation_id, candidate_id, test_cases,
pass_rate, regression, novel_input_test, independent_reuse, verdict, promotion_rule,
evaluated_at`。Pilot B3 在 evaluate 后调用 `bind_evaluation()`（capabilityizer.py:465），
把 `candidate_id + artifact_digest + seal_digest` 三字段写入 evaluation。

### Evaluation 是否保存 identity / digest / seal / authority 引用？

- candidate identity：保存 `candidate_id`。
- artifact digest：保存 `artifact_digest`（绑定后）。
- seal：保存 `seal_digest`（绑定后）。
- authority 引用：不直接保存；通过 `evaluation_id == decision.run_id` 关联
  （producer 里 `run_id = evaluation["evaluation_id"]`）。

### Evaluation 和 Promotion 如何关联？

`issue_authority` 中 `decision["run_id"] = evaluation["evaluation_id"]`，
`decision_id` 由 `_decision_id(candidate_id, candidate_version, run_id)` 确定性派生；
authority 携带 `promotion_decision_id` 与 `evaluation_run_id`。运行时
`violations_for_runtime_activation` 交叉校验 authority/decision/run 三者的
`candidate_id / candidate_version / artifact_digest` 全等。

## 6. Promotion

### Promotion 是对 Candidate ID 还是 artifact？

两者都绑定。`registry.promote()`（registry.py:69）：

```text
canonical 路径：frozen_checks -> evaluation_binding_violations ->
live_candidate_violations -> validate(authority, store, actual_digest) ->
写 entry（adoption 段含 candidate_id/version/decision_id/evaluation_run_id/
policy_version/artifact_digest/provenance）+ copytree(artifact -> registry/.../artifact)
```

entry 的 `adoption` 段与 authority 逐字段一致（`BINDING_KEYS`，registry.py:44）。

### Promotion 是否重新验证 artifact？是否保存验证过的 digest？

是，两个都做：promote 前对 live candidate 目录重算 canonical digest + exact layout；
entry 保存 `adoption.artifact_digest`（= authority digest = frozen digest）。

### Promotion 是否能在 Candidate 内容变化后继续成立？

不能。`live_candidate_violations`（capabilityizer.py:428）在 promote 时重新比对
candidate.json / manifest / tests / artifact；任何变化 -> `FROZEN_CANDIDATE_MISMATCH` /
`ARTIFACT_DIGEST_MISMATCH` -> BLOCK。

## 7. Adoption

`runtime_guard.adopt()`（runtime_adoption_guard.py:297）：

```text
load_store -> integrity_anchor_violations
-> load store authority + immutable file authority（必须一致）
-> canonical 路由（authority.artifact_identity == CANONICAL_ARTIFACT_IDENTITY_V1）
   frozen_checks -> authority.seal_digest == frozen.seal_digest
   -> evaluation_binding_violations(entry.evaluation, frozen)
   -> frozen_artifact_violations(frozen, live artifact_dir)   # 重算 live digest
-> violations_for_runtime_activation(entry, authority, store, actual_digest)
   # 六方 digest 全等：authority/decision/run/candidate/entry/artifact
```

### adopt() 最终验证什么？

验证 authority 合法（确定性 id、issuer、未撤销、lifecycle、policy、provenance）且
**live artifact 字节 digest 等于全链记录的 digest**。

### adopt() 是否重新获取 Candidate？重新计算 digest？核对 authority？

是：frozen record + snapshot 从 `frozen_root` 重新读取并 `verify_frozen`；live
artifact 目录重新计算 canonical digest；authority 从 store + immutable ledger 双读核对。

### adopt() 是否验证 promotion / evaluation continuity？

是：`CANDIDATE_ID_MISMATCH` / `CANDIDATE_VERSION_MISMATCH` / `RUN_MISMATCH` /
`ENTRY_BINDING_MISMATCH` / `MISSING_DECISION` / `MISSING_RUN` / `STALE_DECISION` 等
检查覆盖 continuity。

## 8. Runtime

### Runtime 实际加载什么？

`harness.phase_future("b3")`（harness.py:673）：

```text
registry.discover("F+", b3_entry.json["name"])     # harness.py:689
artifact_dir = Path(entry["artifact_dir"])          # :741
runtime_guard.adopt(...)                            # :742
runtime_guard.verify_at_mount(...)                  # :748
docker_launch(image, [(artifact_dir, "/artifact", True), ...],
              ["python", "/artifact/main.py", ...]) # :750
```

实际运行字节 = **registry entry 的 artifact_dir 目录内容**（promote 时从 candidate
目录复制而来），以只读 bind mount 进入容器。`docker_launch`（src/forge/sandbox.py:22）
只是 `docker run -v host:container:ro`。

### Runtime 是否再做 identity verification？

是：`adopt` 在 mount 前做完整验证；`verify_at_mount`（runtime_adoption_guard.py:415）
再跑一次 `adopt` 并比对 expected digest，随即 `docker_launch`。验证与执行之间只剩
OS 级 bind-mount 竞态（phase9b1 报告标注 UNKNOWN）。

### Runtime 中有没有 candidate_id / artifact_digest / seal_digest？

有。运行记录（run record）写入 `artifact_digest` 与 `capability_id`；entry 持有
candidate_id/version/digest；adopt 全程使用 seal_digest 交叉比对。运行时记录没有再次写
`candidate_id`（record 的 treatment 只写 capability_id + digest），但验证链已经核对。

## 9. 当前真实 Identity Chain

```text
Evaluation (evaluation_id + candidate_id + artifact_digest + seal_digest)
    ↓ 传递：evaluation_id -> decision.run_id；candidate_id/version/digest 全量透传
    ↓ 验证：bind_evaluation 三字段绑定；issue_authority 再验 frozen + live layout
Promotion (decision: value=PROMOTE, gate_result=PASS, digest)
    ↓ 传递：decision_id -> authority.promotion_decision_id
    ↓ 验证：registry.promote 重验 frozen/eval/layout；store 冲突 fail-closed
Authority (authority_id = hash(candidate|version|decision), artifact_identity, seal_digest)
    ↓ 传递：authority 全字段 -> registry entry.adoption
    ↓ 锚定：write-once ledger + trust anchor（store/authority/revocation manifest digest）
Registry (family/name.json: artifact_dir, adoption 段)
    ↓ 传递：artifact_dir 路径 + adoption 绑定 -> runtime guard
    ↓ 验证：adopt 双读 authority、六方 digest 全等
Adoption (ALLOW + actual_digest)
    ↓ 传递：同一 artifact_dir + expected digest
    ↓ 验证：verify_at_mount 重新 adopt + digest 比对
Runtime (docker bind mount artifact_dir -> /artifact -> python main.py)
```

每段谁签名/锚定：

| 对象 | 锚定方式 |
|---|---|
| Frozen Candidate record | write-once `os.link` + `verify_frozen` 重算 |
| Evaluation / Decision | store 内 `recorded_hash/current_hash` 防篡改 + trust anchor |
| Authority | immutable ledger + trust anchor manifest digest |
| Registry entry | **无独立锚定**（不进入 trust anchor digest） |
| Live artifact | adopt/verify_at_mount 每次重算 canonical digest |

## 10. Stage 对照表

| Stage | Input Identity | Stored Identity | Verified Identity | Artifact Digest | Trust Source | Failure Mode |
|---|---|---|---|---|---|---|
| Capabilityize | bundle digest + proposal + confirm | `candidate_id`（随机）、`name`、`source_bundle_ids` | static scan + forged digest 计算 | `canonical(artifact allowlist)` | 本地文件系统 + 调用方 | candidate.json 篡改在 intake 信任边界外 |
| Seal | candidate.json + artifact + tests | frozen record（id/version/digests/seal_digest）+ snapshot | `verify_frozen` 全量重算 | allowlist-only canonical digest | write-once record + 引用感知 delete 防护 | record/snapshot 非单一原子提交（fail-closed 检测） |
| Evaluation | frozen record 引用 | evaluation.json（三字段绑定） | `bind_evaluation` / `evaluation_binding_violations` | digest 存于 evaluation | store evidence hash + anchor | 未绑定 digest 的历史 evaluation 仅 legacy 兼容 |
| Authority issuance | evaluation + confirm + frozen | decision/run/evidence/provenance/authority | `validate()` 全链交叉 | 必须 == frozen digest | 不可变 ledger + trust anchor | 攻击者可同时改写 anchor 场景 = 边界外 |
| Promotion | authority + live candidate | registry entry + 复制 artifact | frozen/eval/layout 重验 | 必须 == authority digest | entry 无独立锚定，靠 digest 全等 | entry.artifact_dir 被指到不同内容 -> digest 拦截；指到同 digest 内容 -> 语义等价 |
| Adoption | entry + authority + live dir | ALLOW 报告 | 六方 digest 全等 + lifecycle/policy/revocation | 重算 live digest | store + ledger + anchor | 未 seal 的 store / 同写者 anchor = 边界外 |
| Runtime mount | adopt 结果 + artifact_dir | run record（capability_id + digest） | `verify_at_mount` 二次 adopt | 重算 + expected 比对 | 同 adoption | OS bind-mount 竞态（UNKNOWN） |

## 11. 一句话结论

当前实现已经做到：**digest 从 Seal 一直透传到 Runtime，并在 mount 前重算比对；
Authority 由不可变 ledger + trust anchor 保护**。剩下的主要不确定性是：
registry entry / `b3_entry.json` 这类“指针/名字”不在 anchor 覆盖内，以及
candidate_id 本身只是标签（名字，不是安全身份）。
