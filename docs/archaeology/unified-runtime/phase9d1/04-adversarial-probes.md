# Phase 9-D.1.04 — Adversarial Probes

## 1. 方法

- 复用 phase9b5 的 `canonical_env` helper，在 `/tmp` 构建一次性 canonical
  registry（frozen candidate + authority + promotion + anchored run_request）。
- A = `main.py` 内容 `print('ARTIFACT_A')`；B = 内容 `print('ARTIFACT_B')`。
- 调用 production `verify_at_mount(..., expected_digest, expected_identity,
  mount_source)`；ALLOW 后、`docker_launch` 前执行替换。
- 容器内计算 `sha256(/artifact/main.py)` 并打印内容；比较 A/B digest。
- Docker image 与 harness 相同：`python:3.12-slim`；挂载 `ro`。

## 2. 结果

| Probe | verify | 替换方式 | inode 变化 | 容器观察 | exit |
|---|---|---|---|---|---|
| Control（无攻击） | ALLOW (A) | - | - | A | 0 |
| P1 directory replacement | ALLOW (A) | rm A; mkdir A; copy B | changed | **B** | 0 |
| P2 atomic rename swap | ALLOW (A) | rename A→swap; B→A; swap→B | changed | **B** | 0 |
| P3 symlink replacement | ALLOW (A) | rm A; ln -s B A | changed | **B** | 0 |
| P4 in-place content mutation | ALLOW (A) | 直接改写 A/main.py | same | **B** | 0 |
| P4b atomic file replace | ALLOW (A) | os.replace 新文件到 A/main.py | same (dir) | **B** | 0 |

每次 verify 返回的 digest 都是 A（`f519e626...` 对应的 canonical digest），
容器内观察到的都是 B 文件 digest（`dc25393d...`），退出码 0。

## 3. 补充 probe

### Symlink at check time（布局是否允许 symlink）

```text
A -> symlink 指向字节与 A 完全相同的目录
verify_at_mount -> ALLOW
verified_artifact_dir = resolve() 后的目标目录
```

结论：checker 接受 artifact path 本身为 symlink（`rglob`/`is_file`/`read_bytes`
都会跟随 symlink）。因此 symlink attack 不是被 layout 检查排除的。

### Post-mount replacement（window 结束点）

```text
容器已运行 -> host 侧 rename swap A/B -> docker exec 读取 /artifact
容器仍观察到 A
```

结论：mount 完成后对象被 pin；window 在容器创建时关闭。

### Natural race（无 barrier）

```text
攻击线程每 ~2 ms 原子交换 A/B
40 次尝试 -> 18 次 verify ALLOW -> 9 次容器观察到 B
```

结论：无需人工停顿即可赢下竞态。

## 4. 可靠性说明

- 所有替换都发生在 verify ALLOW 之后、docker_launch 之前
  （timing 表见 03 文件）。
- verify 失败（B 在 check 前就位）不会计入；只有 ALLOW 之后才攻击。
- 临时 probe 位于 `/tmp`，运行后已清理，未进入 Git。

