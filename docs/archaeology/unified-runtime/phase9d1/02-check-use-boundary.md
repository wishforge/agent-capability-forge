# Phase 9-D.1.02 — Check / Use Boundary

## 1. Check（真正验证 Artifact A 的位置）

最终 Check = `verify_at_mount`（`pilot/runtime_adoption_guard.py:538-563`）内
第二次调用 `adopt`（`runtime_adoption_guard.py:549`）。

Canonical 分支中对 mount source 的字节验证：

```text
adopt()
  -> frozen_checks(frozen_root, candidate_id)        # 验证冻结快照（参考物）
  -> frozen_artifact_violations(record, candidate, artifact_dir)
       (runtime_adoption_guard.py:513)
  -> frozen_artifact_report(Path(artifact_dir), allowlist)
       (capabilityizer.py:431)
  -> artifact_layout(directory, allowlist)
       (capabilityizer.py:56-88)
  -> file_digest(directory / rel)
       (capabilityizer.py:47-53)
  -> path.read_bytes()                               # 最后读取 live artifact
       (capabilityizer.py:49)
```

验证内容：

- exact layout：实际文件集合必须等于 allowlist `["main.py"]`
  （`capabilityizer.py:56-88`）。
- canonical digest：`sha256(canonical({rel: sha256(file_bytes)}))`。
- digest 全等：authority / decision / run / candidate / entry / live artifact
  六方 digest 必须相等（`runtime_adoption_guard.py:463-468`）。

Check 语义：

- 验证的是 **path 下此刻的 bytes**；不是目录 inode、不是已 pin 的 object。
- digest 在 `read_bytes()` 时刻计算（capabilityizer.py:49）。
- 返回 `verified_artifact_dir` = `str(Path(artifact_dir).resolve())`
  （`runtime_adoption_guard.py:534`）——一个 **path string**。
- 不保留 fd；不返回 inode；不返回快照句柄。

## 2. Use（真正用于 bind mount 的位置）

```text
harness.phase_future("b3")
  -> artifact_dir = Path(mount["verified_artifact_dir"])   (harness.py:785)
  -> docker_launch(image, [(artifact_dir, "/artifact", True), ...], cmd)
       (harness.py:786)
  -> sandbox.launch
       -v f"{Path(host)}:{cont}:ro"                        (sandbox.py:28)
  -> subprocess.run(["docker", "run", ...])                (sandbox.py:32)
  -> Docker daemon（VM 内）解析 host path 并 bind mount
```

Use 语义：

- mount source 来自 verify 返回值（`verified_artifact_dir`），没有重新解析或
  重新计算 digest；`mount_source` 反例会被拒绝。
- 但 mount 本身由 Docker daemon 在容器创建时按 **path string 再次解析**。
- Python 侧在 verify 返回后不 stat、不 fstat、不比较 inode。

## 3. Level 1（application path binding）

```text
verified_path == mount_source        -> 由 RUNTIME_BINDING_MISMATCH 强制
                                       (runtime_adoption_guard.py:558-562)
```

Level 1 = CLOSED（与 9-B.5 一致）。

## 4. PATH_BASED_RUNTIME

`rg "O_PATH|openat|os.open|fstat|st_ino|memfd|O_TMPFILE" pilot src`：

- runtime 路径中无任何 descriptor / inode / open-by-handle 用法；
- `os.open` 仅用于 authority ledger 写入（`pilot/adoption_authority.py:232,298,322,363`）；
- 结论：`PATH_BASED_RUNTIME = YES`。

