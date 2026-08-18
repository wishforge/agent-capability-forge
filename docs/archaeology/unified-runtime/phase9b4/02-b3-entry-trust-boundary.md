# 02 b3_entry trust boundary

## 当前 trust chain（真实关系）

```text
Trust Root
  = 外部 integrity anchor 文件（seal 后 store_metadata.trust_anchor_sealed=True）
    ↓ 仅覆盖 3 个 digest
Anchored State
  = adoption_store.json 字节 digest
  + authorities/*.json manifest digest
  + authorities/*.events.jsonl manifest digest
    ↓ 每条 AdoptionAuthority 从这里加载
Authority
  = store 内 authority 记录 + authorities/ 下 immutable ledger 记录（必须相等）
    ↓ BINDING_KEYS 全等 + artifact_digest / seal_digest 重验
Registry entry（未锚定，但被 adopt 重验）
    ↓ entry.artifact_dir 决定 mount source；字节再对 frozen digest 重算
Frozen Candidate（未锚定，但 seal_digest 必须等于 authority.seal_digest）
    ↓
b3_entry.json（未锚定；四元组只与 adopt report 比对）
    ↓ name 决定 discover 哪个 entry
Runtime（phase_future("b3")）
```

代码事实：

- anchor 只算 3 个 digest：`adoption_authority.py:123-177`
  `integrity_anchor_violations()` 的 `actual = {store_digest, authority_manifest_digest,
  revocation_manifest_digest}`。
- registry entry、frozen 目录、b3_entry 都不在 anchor 内；`adoption_authority.py:103-121`
  只列 authorities 目录。
- probe 实测（/tmp/o2_probe.py，结果见 03 号报告）：seal 后改写 b3_entry，
  `integrity_anchor_violations` 仍返回 `[]`；改写 store 或 authority 文件则返回
  `INTEGRITY_STORE_CORRUPTED`（positive control）。

## Authority → b3_entry 之间有什么

目前 **没有** 任何：

```text
signature / digest / hash / MAC / immutable reference / authority-derived ID
```

唯一连接是：b3_entry 的四元组必须等于 adopt report 的四元组，而 adopt report 来自
b3_entry 自己选中的 registry entry 所对应的 authority。这是一个 **自指校验**：
没有外部锚点记录 "操作者/权威原本打算运行 A"。

## b3_entry 语义分类

| 类别 | 是否属于 | 依据 |
|---|---|---|
| A. Security Authority | 否 | authority 记录在 store + ledger，b3_entry 只是引用 |
| B. Signed Attestation | 否 | 无签名 / MAC |
| C. Trusted State | 部分 | runtime 确实把它当 trusted run request 读取，但它无锚定 |
| D. Runtime Intent | **是（核心）** | name + 四元组表达 "本次运行谁" |
| E. Runtime Locator | 是（name/capability_id） | `registry.discover(name)` |
| F. Temporary Execution Metadata | 部分 | 每次 build 覆盖，但可被多次 future run 复用 |

## 结论

b3_entry 是 **Locator + Expected Identity 的混合体**。因为它携带四元组且 Runtime 用这些
字段决定执行对象，它已经属于 security-sensitive state；不能只因为名字叫 entry
就把它当纯配置。

