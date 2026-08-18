# Phase 9-C.09 — O1 Boundary

基线：`a70a433`。O1 = verify（digest 重算）与 kernel bind mount 之间的 OS-level
TOCTOU。本阶段 DO NOT FIX，只记录 proven / not proven / 应用层契约为何仍有效。

## 1. 已证明（application-level）

```text
验证对象 == 运行对象（同一路径）：
  verify_at_mount 返回 report["verified_artifact_dir"]
  harness 只把该路径传给 docker_launch（harness.py:785-791）
  mount_source 反例 -> RUNTIME_BINDING_MISMATCH（runtime_adoption_guard.py:558-562）

验证内容 == 运行内容（同一字节，验证时刻）：
  frozen_artifact_violations 在 adopt 内对 live artifact 重算 canonical digest
  （capabilityizer.py:421-439）
  verify_at_mount 再执行一次 adopt（runtime_adoption_guard.py:538-541）
```

## 2. 未证明（OS-level）

```text
verify_at_mount 返回 与 docker 内核 bind mount 解析之间：
  同权限写者可替换 verified_artifact_dir 内的文件（路径不变、内容变）
  -> 容器实际挂载的内容可不同于验证时刻的 digest
```

这是同 OS 用户/同权限写者的微窗口，不是应用层逻辑错误；R4（digest 命名不可变
快照 / 只读挂载 / open-by-handle）是未来候选方案，但本阶段不实施、不声称已关闭。

## 3. 为什么当前应用层契约仍有效

1. O1 需要攻击者拥有与 harness 相同的文件系统写权限；该权限模型下攻击者本可
   篡改任何未锚定输入，应用层的价值是“锚定意图 + 验证字节”，而不是防同一主体。
2. 验证到 mount 的窗口是单个函数调用 + docker CLI 参数构造，无中间状态可被
   其他应用组件改写；残余窗口只在 OS 调度层面。
3. anchored run_request（9-B.5）为未来 O1 方案提供了不可变预期 digest，作为
   “验证后只接受 digest 引用”的前置条件，O1 方案可直接消费它。

## 4. 结论

```text
O1 = OPEN（唯一真实 Runtime execution-level 应用外 gap）
RUNTIME_BINDING = CLOSED（应用层）/ O1_OPEN（OS 层）
NEXT = O1 Closure Design（独立阶段）
```
