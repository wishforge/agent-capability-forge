# 01 b3_entry 完整生命周期

日期：2026-08-18 ｜ 基线：`85f8328` ｜ 类型：CODE ARCHAEOLOGY

## 结论先行

`b3_entry.json` 是 **run request / runtime intent**：由 harness 在 B3 promotion 成功时创建，
phase_future("b3") 每次运行都从它读取 "这次要运行谁" 以及四元组预期身份。它没有签名、
没有 MAC、没有 write-once 保护、不在 trust anchor 覆盖内；它唯一的信任来源是
"位于 harness state 目录、由 harness 写入" 这一位置假设。

## 生命周期表

| 环节 | 文件 | 函数 / 行 | 行为 |
|---|---|---|---|
| 创建 | pilot/harness.py | `phase_b3_build` :636-641 | promotion 后 `write_text` 写 `{name, capability_id, candidate_id, candidate_version, artifact_digest, seal_digest}`；四个身份字段全部来自刚 promote 的 entry + authority |
| 幂等复用 | pilot/harness.py | `phase_b3_build` :561-568 | 已存在且非 `--force` 时只读 name 并 `registry.discover`，不重写 |
| 持久化 | pilot/state/b3_entry.json | — | 普通 JSON 文件；无 CAS / write-once / 签名；任何能写 state 的进程可改 |
| 读取 | pilot/harness.py | `phase_future` :698 | `json.loads((self.state / "b3_entry.json").read_text())`；文件缺失 -> `FileNotFoundError`，坏 JSON -> `JSONDecodeError`，均无 fallback |
| 定位 | pilot/harness.py | `phase_future` :699 | `registry.discover(self.registry_root, "F+", entry_meta["name"])`；`pilot/registry.py:254-260` 按 `F+/<name>.json` 读取，仅接受 `state == "promoted"` |
| 决定 artifact 路径 | pilot/harness.py | `phase_future` :750 | `artifact_dir = Path(entry["artifact_dir"])`（来自 registry entry，不来自 b3_entry） |
| 验证 | pilot/runtime_adoption_guard.py | `adopt` :326-446 + `verify_at_mount` :448-473 | adopt 对 entry/authority/store/anchor/frozen/digest 全链重验；verify_at_mount 再把 `b3_entry` 四元组与 adopt report 比对，并校验 `mount_source == verified_artifact_dir` |
| 最终 mount / execute | pilot/harness.py | `phase_future` :768-777 | `artifact_dir = Path(mount["verified_artifact_dir"])`，随后 `docker_launch([(artifact_dir, "/artifact", True), ...])` |

## 输入 / 输出

输入：`registry.promote()` 返回的 entry（`capability_id`、adoption 四元组）与
`issue_authority()` 返回的 authority（`seal_digest`）。
输出：`pilot/state/b3_entry.json` 的六字段 JSON。

## 谁修改

唯一写入者是 `Harness.phase_b3_build`（harness.py:636）。registry / guard / producer 都不读写它。
因此 "谁修改" = 任何拥有 harness state 写权限的进程（同写者边界），没有第二道防线。

## 与 canonical 四元组的关系

b3_entry v2 完整携带四元组（candidate_id / candidate_version / artifact_digest / seal_digest），
这是 Phase 9-B.3 R1 的产物。但四元组只被用来和 "它自己选中的 entry 的 adopt report" 比对：
预期值本身没有锚定来源，详见 02 号报告。

