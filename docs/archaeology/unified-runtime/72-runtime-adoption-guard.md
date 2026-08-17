# 72 — Runtime Adoption Guard（Phase 8.2）

> 阶段：Phase 8.2（第一个真实 Runtime execution path 接入 Adoption
> Guard：pilot / `harness.phase_future(arm="b3")`）。
> 基线：71（Phase 8.1，AUTHORITY_PRODUCER_VALID_WITH_UNKNOWN）、70
> （Phase 8，MINIMAL_ENFORCEMENT_VALID_WITH_UNKNOWN）、69（Phase 7.6）。
> 约束遵守：未修改 Cordis Runtime、Langfuse、ToolRuntime、E.5–E.7.1、
> Phase 7–7.6、Phase 8 / 8.1 历史 artifacts（producer / registry /
> adoption_authority 均未改）；未做 E.8、production-wide rollout、
> write-once storage、full revocation service、event bus、break-glass；
> 未 commit / push。

## 1. Runtime Path Selected

```text
RUNTIME_PATH_SELECTED = pilot/harness.py phase_future(arm="b3")
```

```text
FACT   pilot/harness.py:720-725 是唯一真实执行路径：
       artifact_dir = Path(entry["artifact_dir"])
       -> docker_launch(artifact_dir 只读挂载到 /artifact,
                        ["python", "/artifact/main.py", ...])
       Candidate 的 artifact 在这里真正变成可执行状态。
FACT   registry.discover()（pilot/registry.py:160）只检查
       entry["state"] == "promoted"，不重验 authority / digest /
       lifecycle —— 这正是本阶段要关闭的 Runtime 侧缺口。
FACT   python-cordis PluginManager / ToolRuntime 在本仓库只有
       docs/archaeology/ 代码，不是真实运行路径；Cordis / Langfuse
       未接（保持范围外）。
```

## 2. Current Code Fact

接入前：

```text
registry.discover() -> entry["artifact_dir"]
  -> 计算 digest（仅用于 run-record evidence）
  -> docker_launch（无任何 authority / digest 前置检查）
```

接入后：

```text
registry.discover() -> entry["artifact_dir"]
  -> runtime_guard.adopt(registry_root, entry, artifact_dir)
       (pilot/harness.py:721)
  -> 任一检查失败 -> AdoptionBlocked（ADOPTION_BLOCKED）
     （在 output 目录创建、sandbox launch、run record 之前抛出）
  -> 全部通过 -> docker_launch
```

run-record evidence 的 `artifact_digest` 现在直接复用 adopt() 返回的
guard-verified digest（pilot/harness.py:724），不再是另一套 canonical
形状。

新增生产代码：

```text
pilot/runtime_adoption_guard.py
  adopt(registry_root, entry, artifact_dir)        # 激活前检查
  mark_promoted(registry_root, entry)              # promote 后 lifecycle 迁移
  violations_for_runtime_activation(...)           # 共享语义检查
```

## 3. Runtime Guard Responsibility

只回答一个问题：

```text
“我准备激活/执行 Candidate X Version Y，它是否持有合法 AdoptionAuthority？”
```

不做：Evaluation / Regression / Attribution / Promotion scoring /
Prompt optimization / Quality judging。

## 4. Registry vs Runtime Boundary

```text
Registry Guard（promote） = Primary state-transition enforcement
Runtime Guard（adopt）    = Secondary / final activation defense
```

Runtime 不单独相信 `state == "promoted"`；必须同时验证：

```text
state（registry entry）
+ authority（adoption_store authorities）
+ binding（entry.adoption == authority）
+ artifact digest（真实执行目录 == authority digest）
+ lifecycle（PROMOTED）
```

即使 Registry 已经是 PROMOTED，旧数据污染 / artifact 替换 / revoke /
supersede / version 替换 / stale cache / direct activation / Registry 与
Runtime 数据不一致，Runtime 仍会挡下。

## 5. Authority Loading

Runtime 不能自己构造 Authority：

```text
adopt() 用共享 load_store() 读取 adoption_store.json
  -> 按 entry.adoption.promotion_decision_id 在 store["authorities"]
     查找 authority
  -> 再验证 authority_id（确定性 binding id）与全部 binding 字段
```

```text
MISSING_ADOPTION_STORE -> ADOPTION_BLOCKED
MISSING_AUTHORITY      -> ADOPTION_BLOCKED
AUTHORITY_ID_MISMATCH  -> ADOPTION_BLOCKED
```

没有“找到 authority 就相信 promoted state”的路径；找不到就是 block。

## 6. Artifact Digest Verification

`adopt()` 对即将被 docker_launch 挂载的**同一个目录**计算
`dir_digest()`，并要求：

```text
authority.artifact_digest
== decision.artifact_digest
== run.artifact_digest
== candidate.forged_artifact_digest
== entry.adoption.artifact_digest
== runtime 实际计算的 artifact digest
```

run-record evidence 记录的就是这个 guard-verified digest（同一字符串）。

没有 fallback 到 filename / path / version / `state=="promoted"`。
Runtime 拿不到 digest（目录缺失 / 无法计算）→ `ADOPTION_BLOCKED`
（`ARTIFACT_DIGEST_MISMATCH`），不假装通过。

## 7. Lifecycle

Runtime activation 前严格要求：

```text
lifecycle.status == "PROMOTED"
+ transitions 含 PROMOTABLE -> PROMOTED
```

```text
DRAFT / EVALUATING / EVALUATED / REGRESSION_CHECKED /
PROMOTION_REVIEW / PROMOTABLE / HOLD / REJECTED
-> ADOPTION_BLOCKED（INVALID_LIFECYCLE / CANDIDATE_REJECTED）
```

Phase 8.1 的 producer 把 lifecycle 冻结在 `PROMOTABLE`（合法 registry
promotion 前置状态），而 `registry.promote()`（Phase 8 artifact，禁止
修改）只写 registry entry、不写 adoption_store lifecycle。因此本阶段在
Runtime 文件 `pilot/harness.py:611` 增加最小接线：

```text
promote() 成功 -> runtime_guard.mark_promoted()
  lifecycle PROMOTABLE -> PROMOTED（幂等，重复调用不写盘）
```

这是 pilot Runtime 的 adoption 迁移点；`mark_promoted()` 本身 fail-closed
（entry 不是 promoted / lifecycle 不是 PROMOTABLE 或没有迁移记录 ->
block），不会把任意状态标成 PROMOTED。

## 8. Revocation

Runtime 检查两处：

```text
1. authority.status in (REVOKED, SUPERSEDED)
2. store["revocations"] 中匹配 candidate/version/decision 的事件
```

任一命中 -> `REVOKED_DECISION` -> `ADOPTION_BLOCKED`。

```text
UNKNOWN   durable revocation：revocations 只是 flat JSON 里的 append 记录，
          没有 write-once / DB / 签名。Runtime 已具备验证接口，但
          durability 未证明（不伪造）。
```

## 9. Stale Authority

```text
authority.issued_at != decision.created_at   -> AUTHORITY_ISSUED_AT_MISMATCH
decision.created_at < candidate.created_at   -> STALE_DECISION
同 candidate+version 存在更晚 PROMOTE 决策   -> STALE_DECISION
同 candidate+version 存在更晚非 PROMOTE 决策  -> STALE_DECISION
```

没有 fallback latest / previous / active；stale 就是 block。

## 10. Fail Closed

任何 missing / mismatch / unknown / tampered / stale / revoked：

```text
MISSING_ADOPTION_STORE / MISSING_AUTHORITY / REQUEST_METADATA_MISSING
REGISTRY_STATE_NOT_PROMOTED / ENTRY_BINDING_MISSING / ENTRY_BINDING_MISMATCH
AUTHORITY_ID_MISMATCH / MISSING_DECISION / DECISION_NOT_PROMOTE /
GATE_NOT_PASS / RUN_MISSING / RUN_MISMATCH / CANDIDATE_ID_MISMATCH /
CANDIDATE_VERSION_MISMATCH / POLICY_VERSION_MISMATCH /
POLICY_NOT_REGISTERED / POLICY_NOT_FROZEN / RUN_POLICY_MISMATCH /
ARTIFACT_DIGEST_MISMATCH / PROVENANCE_INCOMPLETE / DECISION_TAMPERED /
EVIDENCE_TAMPERED / MISSING_LIFECYCLE / INVALID_LIFECYCLE /
CANDIDATE_REJECTED / REVOKED_DECISION / AUTHORITY_ISSUED_AT_MISMATCH /
MISSING_DECISION_TIMESTAMP / STALE_DECISION
```

全部 -> `AdoptionBlocked`（verdict `ADOPTION_BLOCKED`）。无 fallback、
无 manual activation。break-glass 只记录为 design gap，本阶段不实现。

## 11. TOCTOU

最小版本：

```text
adopt() 在 docker_launch 之前、对即将挂载的同一个 artifact 路径计算 digest
docker 挂载为只读（sandbox 执行期间 artifact 不会被写）
```

```text
UNKNOWN   digest 计算与真正 mount 之间仍有文件系统窗口：flat JSON /
          普通目录没有 immutable artifact ref / snapshot。检查后、挂载前
          artifact 仍可被替换。真 snapshot / 不可变 ref 是下一步。
```

本阶段不假装 atomic。

## 12. Idempotency

```text
adopt() 只读：重复合法调用返回同一 ALLOW，
          不创建新 authority、不改 binding、不产生多个 activation identity。
mark_promoted()：已 PROMOTED 时直接返回，store 字节不变。
phase_future("b3")：每次 run 请求只触发一次 docker_launch。
```

测试覆盖：`test_repeat_valid_activation_is_idempotent`、
`test_valid_request_activates_exactly_once`。

## 13. Bypass Paths Closed

```text
CLOSED   历史 state="promoted" 数据（无 authority / lifecycle）
         -> MISSING_AUTHORITY / INVALID_LIFECYCLE 挡住。
CLOSED   直接编辑 registry JSON 改成 state="promoted"
         -> 仍缺 authority / lifecycle，Runtime 挡住。
CLOSED   promote 后替换 artifact 字节
         -> Runtime 重算 digest 不匹配，挡住。
CLOSED   手工改 b3_entry.json 指向任意 name
         -> discover() 返回的 entry 必须通过完整 authority 检查，
            只指向旧/伪 entry 会被挡住。
CLOSED   stale cache / direct runtime activation
         -> 同一 adopt() 前置检查全部重新执行。
```

`discover()` 本身仍只查 state（未改），但 pilot 里唯一把 entry 变成真实
执行的消费端（phase_future b3）现在被 Guard 包住。

## 14. Bypass Paths Remaining

```text
BYPASS_REMAINS  Cordis PluginManager / ToolRuntime / Langfuse 未接。
BYPASS_REMAINS  任何绕过 phase_future b3 直接调用 docker_launch /
                forge.sandbox.launch 的代码（仓库内 oracle/validation/
                evaluation 属于非 adopted-candidate 沙箱，不在此 Guard
                范围；未来新增执行入口必须复用 adopt()）。
BYPASS_REMAINS  flat JSON 可整体编辑：同时改 authority + decision +
                全部 hash 仍可绕过（无 write-once / 签名 / DB）。
BYPASS_REMAINS  无密码学 issuer trust（authority_id 是确定性哈希）。
BYPASS_REMAINS  durable revocation / break-glass 未实现。
```

## 15. FACT / INFERENCE / UNKNOWN

```text
FACT      phase_future("b3") 是仓库唯一把 promoted artifact 真正执行的
          路径（docker_launch + python /artifact/main.py）。
FACT      runtime_guard.adopt() 已接在该路径 docker_launch 之前
          （pilot/harness.py:721），全部检查通过才执行。
FACT      promote() 成功后 mark_promoted() 把 lifecycle 迁到 PROMOTED
          （pilot/harness.py:611），Runtime 要求 PROMOTED。
FACT      非法 authority / digest mismatch / lifecycle != PROMOTED /
          revoked / superseded / stale / tampered 全部 fail-closed
          （40 项 phase8.2 tests 覆盖用户要求的 20 类场景）。
INFERENCE 对 pilot B3 路径，Registry ALLOW 后 Runtime 不再自动信任；
          同一张 AdoptionAuthority 在真正执行前被再次验证。
UNKNOWN   持久化 durability（flat JSON 无 CAS / write-once）。
UNKNOWN   revocation durability（append 记录可编辑）。
UNKNOWN   digest 检查与 mount 之间的 TOCTOU。
UNKNOWN   issuer cryptographic trust。
```

## 16. MVP Limitation

```text
- 只接了一个真实 Runtime 路径（pilot B3），不是 production-wide rollout。
- 没有写 Cordis / ToolRuntime / Langfuse / E.8。
- 没有 write-once storage / durable revocation service / event bus /
  break-glass。
- Runtime Guard 不能替代 Registry Guard；两者职责不同。
```

## 17. Next Step

```text
1. 把同一 adopt() 语义接到下一个真实 Runtime（Cordis PluginManager 或
   ToolRuntime），复用最小共享 adapter。
2. write-once / append-only store 或 signed authority，闭合 flat JSON
   整体编辑绕过。
3. immutable artifact ref / snapshot，闭合 digest 检查与 mount 之间的
   TOCTOU。
4. durable revocation service（REVOKED / SUPERSEDED 的真实持久化与
   传播）。
5. break-glass 设计（当前仅记录 gap，不实现）。
```

## Validation

```text
python3 -m pytest docs/archaeology/unified-runtime/phase8.2 -q
  -> 40 passed
python3 -m pytest docs/archaeology/unified-runtime/phase7.2 \
  docs/archaeology/unified-runtime/phase7.3 \
  docs/archaeology/unified-runtime/phase7.4 \
  docs/archaeology/unified-runtime/phase7.5 \
  docs/archaeology/unified-runtime/phase7.6 \
  docs/archaeology/unified-runtime/phase8 \
  docs/archaeology/unified-runtime/phase8.1 \
  docs/archaeology/unified-runtime/phase8.2 -q
  -> 189 passed
python3 -m unittest discover -s tests -q
  -> 11 tests OK
python3 -m compileall -q pilot \
  docs/archaeology/unified-runtime/phase7.2 \
  docs/archaeology/unified-runtime/phase7.3 \
  docs/archaeology/unified-runtime/phase7.4 \
  docs/archaeology/unified-runtime/phase7.5 \
  docs/archaeology/unified-runtime/phase7.6 \
  docs/archaeology/unified-runtime/phase8 \
  docs/archaeology/unified-runtime/phase8.1 \
  docs/archaeology/unified-runtime/phase8.2 tests
  -> clean
```

未运行 live LLM / provider / Docker。

## Final Verdict

```text
RUNTIME_ADOPTION_GUARD_VALID_WITH_UNKNOWN
```

```text
Runtime 在真正执行 AI 前已经验证同一张 AdoptionAuthority：
pilot B3 路径在 docker_launch 之前必须通过
state + authority + binding + artifact digest + lifecycle(PROMOTED) +
policy + provenance + revocation + stale 全部检查；
只要这张证不合法，AI 无法启动（ADOPTION_BLOCKED）。
persistence durability / revocation durability / TOCTOU /
issuer trust 仍 UNKNOWN，不代表 production 全面安全。
```
