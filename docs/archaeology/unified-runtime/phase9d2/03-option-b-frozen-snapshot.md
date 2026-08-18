# Phase 9-D.2.03 — Option B: Mount Frozen Snapshot

- 日期：2026-08-18
- 基线：`ee1c639`
- 模式：option archaeology；未实现

## 1. 当前 “frozen” 的真实语义

```text
frozen record   ：write-once（os.link create-if-absent，capabilityizer.py:213 附近）
                  -> 逻辑不可变
frozen snapshot ：frozen_root/frozen/<candidate_id>/{candidate.json,tests,artifact}
                  目录 0755、文件 0644、owner 为当前用户、无 chmod/chflags/写域隔离
                  -> OS 级可变
verify_frozen   ：每次全量重算 digest（capabilityizer.py:323）
                  -> 能检测“已发生”的篡改；不能防止 verify 后到 mount 之间的替换
```

结论：当前 frozen 只有**逻辑/元数据语义**，不是 OS 级 immutable execution
snapshot。把它当作 mount source 前必须升级。

## 2. 升级为 execution snapshot 的最小改造

```text
1. 发布前递归 chmod：目录 0555、文件 0444（freeze_candidate 内，os.replace 之前）
2. 写域隔离：snapshot store owner != runtime user（部署契约或特权创建路径）
3. 发布后无写路径：freeze 之后没有任何代码写 snapshot（构造保证）
4. parent 层级保护：frozen_root/frozen/ 对 runtime user 只读
   （否则整个 candidate 目录可被 rename 替换）
5. 维持 verify_frozen 全量重算作为检测兜底
```

## 3. 现有 frozen snapshot 的优势（为什么 B 是 lazy 选项）

1. 对象已存在：freeze 时已创建，不新增 store / 不新增复制步骤。
2. `entry["frozen_root"]` 已进入 entry / adopt / verify 链
   （registry.py:194；runtime_adoption_guard.py:437-438, 502）。
3. `shutil.copytree` 默认 `symlinks=False`：快照内 symlink 在 freeze 时被解析成
   普通文件（本轮实测：copytree symlinks=False 后 `is_symlink()=False`，
   内容为指向文件内容）——canonical snapshot 天然无 symlink。
4. `authority.seal_digest` 已绑定 frozen record；anchored run_request 已携带
   `artifact_digest` / `seal_digest`（9-B.5），digest 身份已经锚定。
5. 语义时间线正确：freeze 的字节 == 之后 validate / evaluate / promote 验证的
   字节（`live_candidate_violations`，capabilityizer.py:441），运行时只读它即可。

## 4. copy race / freeze race / GC race

与 Option A 相同（见 02 号文件），额外事实：

- freeze 发生在 evaluation/promotion **之前**；运行时只读 snapshot，不再依赖
  live registry 副本（registry 副本只作 locator / legacy 兼容）。
- 删除 / 替换 snapshot：引用期间禁止；`verify_frozen` fail-closed。
- crash：record 先、snapshot 后 -> `FROZEN_CANDIDATE_INCOMPLETE`。

## 5. Docker Desktop / macOS

- snapshot 是普通 host 目录，与当前 registry artifact 同构，mount 兼容
  （9-D.1 与本轮均用真实容器验证）。
- 共享层对文件内容实时可见（01 号文件新证据），所以**必须写域隔离**；
  与 A 的边界完全相同。

## 6. 与 Option A 的差异

```text
目录名   ：B = candidate_id；A = digest
安全身份 ：B = frozen record + authority + run_request（digest 字段）；
          不依赖目录名
digest 绑定：两者都必须 verify digest(E) == run_request.artifact_digest
```

目录名是否等于 digest 不改变安全属性；A 的 digest 命名是可选的审计增强。

## 7. 判定

```text
OPTION_B = 作为 object 层 ADOPT（复用现成 frozen snapshot，最小新增）
OPTION_B 闭合条件 = 写域隔离（同 A）
```

