# Phase 9-C.02 — Candidate Selection Authority Matrix

基线：`a70a433`。逐组件回答：谁能选择 Candidate、谁应该选择、实际行为。

## 1. Matrix（canonical path）

| Component | Can select candidate? | Should select? | Actual behavior | Evidence |
|---|---:|---:|---|---|
| Authority（issue_authority） | 否 | 否（只批准） | 记录 approval；不能改变 runtime 选择 | adoption_authority_producer.py:98-344 |
| Run Intent（store["run_request"]） | 是 | 是（唯一） | 决定 discover name + expected identity | runtime_adoption_guard.py:343-377；harness.py:698-705 |
| Registry（entry） | 否 | 否（只定位） | 按 run_request.name 解析；内容必须过 adopt 全链 | registry.py:254-260；harness.py:702 |
| b3_entry | 否 | 否（cache） | 只与 run_request 比对；不一致 REJECT | runtime_adoption_guard.py:380-413 |
| Frozen Candidate | 否 | 否（验证源） | 提供 seal_digest/artifact_digest 预期值 | capabilityizer.py:380-404 |
| Runtime request（arm="b3"） | 否 | 否（只选 arm） | arm 决定走哪条 phase，不决定候选 | harness.py:683-720 |
| Docker launch | 否 | 否（只执行） | 只接收已验证路径，无 name/身份输入 | sandbox.py:15-59；harness.py:786-791 |

## 2. Should NOT select but Can currently select

Canonical 路径：**无**。

Legacy 路径（历史兼容边界）：b3_entry + Registry 仍然实际选择候选：

```text
run_request 不存在（legacy store）
  -> b3_entry.name -> registry.discover -> entry -> adopt(legacy)
  -> docker_launch
```

（harness.py:706-718）。这是 Phase 9-B.2 O4 记录的 legacy 处置问题，不是 canonical
信任链的一部分；新候选无法走该路径（source_bundle_ids 阻止，见 08 号报告）。

## 3. 全仓选择点搜索

候选选择相关字段：`run_request`、`b3_entry`、`registry.discover`、`entry["artifact_dir"]`、
`frozen_root`、`name`。canonical 路径唯一入口：

```text
load_trusted_run_request (runtime_adoption_guard.py:343-377)
  -> run_request.name (harness.py:702)
  -> adopt(entry) (harness.py:768)
  -> verify_at_mount(expected_identity=run_request) (harness.py:778-784)
  -> docker_launch(verified_artifact_dir) (harness.py:786-791)
```

结论：`CANDIDATE_SELECTION = SINGLE_AUTHORITY`（anchored Run Intent）；legacy 兼容
路径单独成系，不作为 canonical 的多 authority 证据。
