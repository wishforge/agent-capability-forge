# 03 b3_entry adversarial probes

## 方法

- 临时 probe：`/tmp/o2_probe.py` + `/tmp/o2_probe_results.json`（不进入仓库，不 commit）。
- 完全复刻 `harness.phase_future("b3")` 的真实路径：
  `b3_entry -> registry.discover(name) -> adopt(entry, artifact_dir) ->
  verify_at_mount(expected_identity=b3_entry, expected_digest, mount_source)`
  （harness.py:698-768）。
- 每个 case 在临时 canonical state 中构造：freeze -> issue_authority -> promote ->
  mark_promoted（与 phase9b3 测试同构）。
- Docker daemon 本阶段不可用，未执行容器启动；记录的是 mount 前 guard 决策。
  mount 对象由 harness.py:768-777 静态确定：`docker_launch([(verified_artifact_dir, ...)])`。

## 结果

### whole b3_entry swap（name + 四元组 → B）

| Before | Manipulation | Observed | Expected | Security Impact |
|---|---|---|---|---|
| A 已 promote，b3_entry = A | b3_entry 整体替换为 B 的 name + 四元组 | **ALLOW**，`entry_name=beta`，`verified_artifact_dir=.../beta/artifact` | 若 b3_entry 是信任边界对象应 REJECT | 运行 B（另一个已授权候选）；A 的 authority 未被修改，但不再是运行意图 |

### 单字段 tampering（entry 仍为 A）

| # | Manipulation | Observed | Expected | Security Impact |
|---|---|---|---|---|
| Case A | `candidate_id`: A→B | REJECT `CANDIDATE_ID_MISMATCH` | REJECT | 无 |
| Case B | `candidate_version`: A→v99 | REJECT `CANDIDATE_VERSION_MISMATCH` | REJECT | 无 |
| Case C | `artifact_digest`: A→B | REJECT `ARTIFACT_DIGEST_MISMATCH` | REJECT | 无 |
| Case D | `seal_digest`: A→B | REJECT `SEAL_DIGEST_MISMATCH` | REJECT | 无 |
| Case E | `name` 改 B，四元组仍 A | REJECT `CANDIDATE_ID_MISMATCH` + `ARTIFACT_DIGEST_MISMATCH` + `SEAL_DIGEST_MISMATCH` | REJECT | 无（locator 单独不能 rebind） |
| Case F | `capability_id` 改任意值 | **ALLOW** | ALLOW（字段未被 runtime 读取） | 无（inert field） |

### deletion / corrupt / stale

| # | Manipulation | Observed | Expected | Security Impact |
|---|---|---|---|---|
| Deletion | b3_entry.json 删除 | `FileNotFoundError`（无 fallback、无重建） | REJECT | 无执行 |
| Corrupt | b3_entry.json = `{` | `JSONDecodeError` | REJECT | 无执行 |
| Stale version | `candidate_version` = v0（authority 为 v1） | REJECT `CANDIDATE_VERSION_MISMATCH` | REJECT | 无 |
| Old format | 仅 name + capability_id | REJECT `MISSING_IDENTITY` ×4 | REJECT（canonical entry 上 R1 生效） | 无 |

### Authority / Registry vs b3_entry 冲突

| # | 构造 | Observed | 谁赢 |
|---|---|---|---|
| Authority vs b3_entry | Authority=A，b3_entry 单字段指向 B | REJECT | **Authority 赢**（adopt report 以 anchored authority 为真；b3_entry 必须匹配） |
| Registry vs b3_entry | registry alpha.json→B entry，b3_entry 仍 A | REJECT | **两者必须一致**；adopt 重验 entry 后仍以 authority 为真 |
| 一致改写（同写者） | registry alpha.json→B entry **且** b3_entry name=alpha+四元组=B | **ALLOW**（通过原 capability name 运行 B） | 无仲裁者：b3_entry 与 registry 互相自洽即可 |
| 整对象替换（仅 b3_entry） | b3_entry name=beta+四元组=B | **ALLOW** | b3_entry 的 name 决定 discover 目标 |

### locator / artifact 绑定

| # | 构造 | Observed | Security Impact |
|---|---|---|---|
| P11 | entry.artifact_dir 指向 B 的 artifact（identity 仍 A） | REJECT `ARTIFACT_DIGEST_MISMATCH`（frozen_artifact_violations 重算字节） | 无；identity→artifact 绑定闭合 |
| P12 | b3_entry 注入 `verified_artifact_dir=B`（identity 仍 A） | **ALLOW A**（字段被 harness 忽略） | 无；b3_entry 没有该字段，mount source 来自 adopt report |

### anchor 覆盖对照（positive control）

| 改写对象 | anchor 检测 |
|---|---|
| b3_entry.json（seal 后） | 无 violation（`[]`）—— **b3_entry 不在 anchor 内** |
| adoption_store.json | `INTEGRITY_STORE_CORRUPTED` |
| authorities/*.json | `INTEGRITY_STORE_CORRUPTED` |

## 三种问题的归类

1. **State Tampering（单字段）**：REJECT —— 已闭合（R1 四元组比对）。
2. **Identity Drift（整对象一致替换 A→B）**：ALLOW —— **REAL GAP**。
3. **Locator Rebinding（identity A + path B）**：REJECT —— 已闭合（digest 重算 + mount_source 校验）。

