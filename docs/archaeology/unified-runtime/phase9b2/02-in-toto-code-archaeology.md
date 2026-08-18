# 02 in-toto 代码考古

仓库：`https://github.com/in-toto/in-toto`
固定 commit：`a8ce9ee2125ae5a4b041a4e37cc1cf10eed0da6b`（2026-05-19）
证据来源：真实源码（`in_toto/verifylib.py`、`in_toto/models/link.py`、`in_toto/in_toto_verify.py`）。

## 1. 核心模型

### Layout（信任根）

- `in_toto/models/layout.py`：`Layout` 含 `steps` / `inspect` / `keys`；
  `Step` 有 `name`, `pubkeys`（授权 functionary keyid 列表）, `expected_materials`,
  `expected_products`, `expected_command`。
- Layout 本身由 root key 签名：`verify_metadata_signatures(metadata, keys_dict)`
  （`verifylib.py:360`）要求 keys_dict 非空，且**每个传入 key** 都能验证 Layout 签名。

### Link（步骤证据）

- `in_toto/models/link.py`：`Link` 字段 `name`, `command`, `materials`, `products`,
  `byproducts`, `environment`。
- materials/products 是 `{artifact_path: {hash_algo: digest}}`：

```python
# models/link.py:52-64
materials: {
  "<material path>": {
    "<hash algorithm name>": "<hash digest of material>",
  }
}
products: {
  "<product path>": {
    "<hash algorithm name>": "<hash digest of product>",
  }
}
```

- 哈希在 `in_toto/runlib.py:69 record_artifacts_as_dict` 中计算（路径 + 文件字节 hash）。
- Link 由 functionary 签名；`verify_link_signature_thresholds`（`verifylib.py:402`）只接受
  “keyid 被 step.pubkeys 授权 + 签名有效”的 link，达到 threshold 才算通过。

## 2. 关键验证链

`in_toto_verify()`（`verifylib.py:1484`）的执行顺序（docstring 原文）：

```text
1. Verify layout signatures
2. Verify layout expiration date
3. Substitute placeholders in the layout
4. Load link metadata
5. Verify link signatures with keys in layout
6. Recurse into sublayout verification
7. Soft-verify alignment of reported and expected commands
8. Verify threshold artifact constraints
9. Process step product and material rules
10. Execute inspection commands and generate inspection links
11. Process inspection product and material rules
```

## 3. “Step N 输出 == Step N+1 输入”如何证明

### MATCH 规则（`verify_match_rule`，`verifylib.py:645`）

规则 `MATCH <pattern> [IN <source-path-prefix>] WITH (MATERIALS|PRODUCTS) [IN <dest-path-prefix>]
FROM <step>`：

```python
# verifylib.py:724-762（行为摘要）
# 1) 用 pattern 过滤 source 队列（path 前缀先剥离）
# 2) 从目标 link 取 dest_artifacts（materials 或 products）
# 3) 必须同时满足：
#      dest_artifacts[full_dest_path] 存在         # 路径匹配
#      source_artifact == dest_artifact             # 哈希匹配
# 4) 只有两边都匹配才 consumed；否则不消费
```

关键代码：

```python
try:
    dest_artifact = dest_artifacts[full_dest_path]
except KeyError:
    continue
if source_artifact != dest_artifact:
    continue
consumed.add(full_source_path)
```

### 队列 + DISALLOW/REQUIRE（`verify_item_rules`，`verifylib.py:1014`）

```text
所有 materials/products 放入 artifact queue；
规则按顺序消费；
“DISALLOW” 发现未被消费的 artifact -> RuleVerificationError；
“REQUIRE” 找不到要求的 artifact -> RuleVerificationError。
```

```python
# verifylib.py:1070-1076（注释原文）
# The consumption of artifacts by itself has no effects on the verification.
# Only through a subsequent "DISALLOW" rule ... is an exception raised.
# Similarly does the "REQUIRE" rule raise exception, if it does not find the
# artifact it requires, because it has falsely been consumed or was not there
# from the beginning.
```

这相当于“防火墙”：允许的路径被逐条放行，**没有被任何规则放行的路径默认拒绝**。

## 4. 我的理解

in-toto 的答案拆成三个独立机制：

1. **谁做的**：Layout（root 签名）声明每个 step 的 functionary；Link（functionary 签名）
   证明该 step 确实记录过这些 bytes。
2. **做过什么**：materials/products 是路径 + hash 字典；step 与 step 之间用 MATCH 规则
   把“上一步 products”与“下一步 materials”做**路径与哈希双重相等**。
3. **是否完整**：队列 + DISALLOW 默认拒绝，REQUIRE 反向保证；不依赖“信任字段名”。

注意：in-toto 验证的是**元数据记录的连续性**，不是部署时的字节。它不阻止验证通过后
攻击者替换最终交付物——它把最终产品的 digest（summary link products）交给消费者，
由消费者自己绑定到实际运行对象。这与 Agent Capability Forge 的
`adopt -> verify_at_mount -> docker_launch` 是互补关系。

## 5. 值得借鉴 / 不值得借鉴

### 值得借鉴

1. **materials -> products -> next-step input 的路径+哈希双匹配**。
   本地目前是“同一 digest 全链相等”，但没有 in-toto 那种“上一步产出物清单”作为
   下一步输入清单的显式断言。若 Candidate 流水线将来有多个产物/中间步骤，这正是
   step continuity 的模板。
2. **队列 + DISALLOW 默认拒绝**。本地 exact layout（actual == allowlist）已是等价物，
   无需再抄。
3. **authorized functionary keyid 绑定 step**。本地有 `issuer_id` +
   `PILOT_TRUSTED_ISSUERS` allowlist，但 issuer 是字符串而非密码学 keyid，且 allowlist
   未设置时是 deterministic 模式（UNKNOWN issuer）。

### 不直接借

1. **完整 layout model（steps/inspections/阈值/子布局）**。Agent Candidate 生命周期
   不是任意供应链 DAG；当前是单一线性链，layout DSL 是过度建模。
2. **GPG 生态集成 / key 管理系统**。本地是单机 pilot，不引入 GPG 复杂度。

原因：线性链用“同一 digest 全链相等”比 layout DSL 更短；但一旦链变成多输入多输出，
就需要 in-toto 式清单匹配。
