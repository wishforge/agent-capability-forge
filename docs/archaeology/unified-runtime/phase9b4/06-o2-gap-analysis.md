# 06 O2 Gap Model

## 判定

```text
O2 = REAL GAP（范围限定：已授权候选之间的运行意图漂移）
```

不是 FALSE POSITIVE：probe P1/P10b 实测一致替换 b3_entry 后 Runtime 对 B ALLOW。
不是 CLOSED：预期四元组只做自指校验，没有锚定来源。
不是 "必须把 b3_entry 加进 anchor" 的预设结论——最小修复见下。

## 已闭合的部分（不重复修）

- 单字段篡改 → REJECT（R1）。
- name-only / locator 篡改 → REJECT（P6）。
- artifact path / 内容替换 → REJECT（P11 + frozen digest 重算）。
- b3_entry 删除 / 损坏 / 旧格式 → 异常或 MISSING_IDENTITY，REJECT。
- 未授权代码执行：不可能。任何 ALLOW 的 B 都是 authority-approved、digest-verified 的
  已 promote 候选。

## 真实剩余 gap

```text
改变 b3_entry 的 name + 四元组（保持一致）
-> registry.discover 选中 B
-> adopt(B) 全链验证通过（B 自身 authority/frozen 都真实）
-> verify_at_mount 用 B 的四元组对 B 的 report，自洽
-> ALLOW，mount B 的 artifact
```

系统没有锚定 "操作者/权威原本打算运行 A"。A 的 authority 未被动过，但运行意图本身
丢失了。安全影响 = 已授权集合内的 **intent/policy drift**（例如 operator 指定 A，
攻击者改写成 B 且 B 是另一个已 promote 的候选）。

## Minimal Invariant

```text
运行意图（run request）必须与它声明的四元组共享同一个 trust root；
任何把 run request 从 A 改成 B 的操作必须可检测（REJECT）或不可能（锚定/不可变）。
```

## Minimal Change Boundary（推荐实现顺序，本阶段不实现）

Option A（推荐，改动最小且复用现有 anchor）：

- 在 adoption_store.json 增加一个 anchored `run_requests` 记录（或等价字段），
  promotion 时写入 `{name, capability_id, 四元组}`；
- `mark_promoted()` 写 store 后现有 `write_trust_anchor()` 自动把该记录纳入
  `store_digest`（零 anchor schema 变更）；
- `phase_future("b3")` 改为从 anchored store 读取 run request；b3_entry.json
  降级为纯 cache / locator，与 anchored record 不一致 → REJECT。

Option B（语义直白但改动面稍大）：

- 扩展 anchor 为一个新增 digest 字段（如 `state_entry_digest`），覆盖 b3_entry.json
  字节；任何改写 → `INTEGRITY_STORE_CORRUPTED`；
- 需要把 b3_entry 路径/配置传入 adoption_authority，且 seal/refresh 流程要覆盖
  harness 写入点。

## Required Regression Tests（若实现）

1. whole swap A→B（一致替换）→ REJECT。
2. 单字段 A→B → REJECT（已有，保持）。
3. b3_entry 删除 / 损坏 → REJECT。
4. stale version → REJECT（已有，保持）。
5. anchor sealed 后改写 run request → `INTEGRITY_STORE_CORRUPTED`（Option A/B 各自）。
6. 正向：合法 promotion 后 phase_future("b3") 仍 ALLOW A。
7. capability_id 仍为 inert field（文档化，不参与校验）。

## 边界声明

- 本阶段只考古与探针，未实现任何修复。
- 同写者可同时改写 b3_entry 与 registry entry（P10b）时，Option A/B 都依赖
  "anchor/store 不可被同写者改写" 的既有边界（seal + external anchor）；若同写者
  连 anchor 都能写，属于 Phase 9-B.2 GAP-2/GAP-3 的更大模型问题，不在 O2。

