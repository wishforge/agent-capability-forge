# DeepSeek Harness Dynamic Cordis Plugin Runtime 源码考古报告

研究范围：仅 `deepseek-harness/` 当前 checkout 的源码、测试与随仓库发布的组合配置。
本轮只研究 Dynamic Cordis Plugin Runtime 的
`define → run → version → rollback → stop → undefine`。

证据等级：

- `[FACT]`：源码/测试直接证明。
- `[INFERENCE]`：由多个源码 FACT 推导。
- `[HYPOTHESIS]`：合理推测，无源码证明。
- `[UNKNOWN]`：源码没有足够证据。
- `[NOT_FOUND]`：明确搜索过，但没有找到实现。

路径均相对于仓库根 `deepseek-harness/`。行号来自当前 commit。
README/文档与源码冲突时，以源码为准（本报告 6.12 有一处已确认冲突）。

---

## 1. Repository Baseline

| 项 | 值 | 证据 |
|---|---|---|
| commit | `47f943859bef60e4160492346772ded9b24f765a` | `git rev-parse HEAD` |
| branch | `master` | `git branch --show-current` |
| dirty/clean | clean（`git status --porcelain` 无输出） | git status |
| 最近提交 | 2026-08-13 19:38:46 +0800，Merge pull request #2519 | `git log -1` |
| DeepSeek Harness version | `0.1.0-rc.5` | `package.json:3` |
| 语言/框架 | TypeScript pnpm monorepo；运行时基于 vendored Cordis（`@deepseek-ai/cordis`） | `package.json`、`vendor/cordis/package.json` |
| 测试框架 | Vitest | `package.json` scripts、`vitest.config.ts` |

相关 package：

| package | 目录 | 角色 |
|---|---|---|
| `@deepseek-ai/dsh-cordis-host-runner` | `packages/extensions/cordis-host-runner` | Host 侧动态 Package 注册表、VM sandbox、Host 半生命周期、invoke 表 |
| `@deepseek-ai/dsh-tool-cordis` | `packages/extensions/tool-cordis` | Model-facing `cordis_define/run/stop/undefine/inspect_*` 工具 |
| `@deepseek-ai/dsh-cordis-client-runner` | `packages/extensions/cordis-client-runner` | 浏览器半边：closure 求值、loader 装载/卸载、审批编排 |
| `@deepseek-ai/dsh-client-ui-cordis` | `packages/extensions/ui-cordis` | 运行控制面板（含 rollback 按钮） |
| `@deepseek-ai/cordis` | `vendor/cordis` | vendored Cordis：Context / Registry / Fiber / Service / Events |

---

## 2. Dynamic Cordis Runtime Directory Map

只列与本轮研究直接相关的文件。

| 关注点 | 文件 | 关键 symbol |
|---|---|---|
| define | `packages/extensions/cordis-host-runner/src/index.ts:151` | `DynamicCordisRunnerService.define()` |
| define precheck | `packages/extensions/cordis-host-runner/src/sandbox.ts:206` | `precheckCode()` |
| registry | `packages/extensions/cordis-host-runner/src/registry.ts:141` | `DynamicCordisRegistry` |
| package / definition | `packages/extensions/cordis-host-runner/src/registry.ts:37` | `DynamicCordisDefinition` |
| plugin | `packages/extensions/cordis-host-runner/src/registry.ts:51` | `DynamicCordisPlugin` |
| version（current/next 指针） | `packages/extensions/cordis-host-runner/src/registry.ts:65-70` | `currentPackageId` / `nextPackageId` |
| run | `packages/extensions/cordis-host-runner/src/index.ts:254` | `DynamicCordisRunnerService.run()` |
| run / attempt 类型 | `packages/extensions/cordis-host-runner/src/types.ts:267` | `DynamicCordisRunResponse` |
| runAttempt | `packages/extensions/cordis-host-runner/src/types.ts:143` | `DynamicCordisRunAttempt` |
| fiber | `vendor/cordis/src/fiber.ts:184` | `Fiber` |
| sandbox（host） | `packages/extensions/cordis-host-runner/src/sandbox.ts:129` | `createSandbox()` |
| sandbox（client） | `packages/extensions/cordis-client-runner/src/client/evaluator.ts:129` | `evaluateClientHalf()` |
| stop | `packages/extensions/cordis-host-runner/src/index.ts:456` | `stop()` |
| rollback | `packages/extensions/ui-cordis/src/client/CordisPanel.tsx:391` | 面板按钮；无独立 service API |
| undefine | `packages/extensions/cordis-host-runner/src/index.ts:210` | `undefine()` |
| tool（模型工具） | `packages/extensions/tool-cordis/src/index.ts:149,241,330,352` | `cordis_define/run/stop/undefine` |
| tool（动态注册） | `packages/extensions/cordis-host-runner/src/guard.ts:551,626` | `sandboxDefineTool()` / `sandboxRegisterTool()` |
| handler | `packages/extensions/cordis-host-runner/src/registry.ts:14` | `DynamicCordisHandler` |
| persistence | `packages/extensions/cordis-host-runner/src/registry.ts:142-145` | 仅 `Map`；无磁盘/DB |
| tests | `packages/extensions/cordis-host-runner/tests/runner.spec.ts` 等 | 见第 16 节 |

---

## 3. Object Model

源码中实际存在的对象（不是假设的模型）：

### 3.1 DynamicCordisDefinition —— “一个不可变代码包”

`packages/extensions/cordis-host-runner/src/registry.ts:37-49`

```ts
export interface DynamicCordisDefinition {
  packageId: CordisDynamicPackageId
  name: string
  purpose: string
  hostCode?: string
  clientCode?: string
}
```

`[FACT]` 定义后没有任何源码路径改写 `DynamicCordisDefinition` 的字段；define 写入一次后只被读取（`inspectPackage`、`getClientCode`、`startFresh`）。`[INFERENCE]`：它是不可变版本。

### 3.2 DynamicCordisPlugin —— “一个稳定 Plugin 实例”

`packages/extensions/cordis-host-runner/src/registry.ts:51-70`

```ts
export interface DynamicCordisPlugin {
  pluginId: CordisDynamicPluginId
  sessionId: SessionId
  packages: Map<CordisDynamicPackageId, DynamicCordisDefinition>
  approvedClientPackages: Set<CordisDynamicPackageId>
  clientVersionUpdatesApproved: boolean
  currentPackageId?: CordisDynamicPackageId
  nextPackageId?: CordisDynamicPackageId
  run?: DynamicCordisRun
  latestRun?: DynamicCordisRunAttempt
}
```

`[FACT]` `DynamicCordisPlugin` 没有 `name`、`version`、`hash`、`metadata` 字段；`name` 属于 Package（`DynamicCordisDefinition.name`）。

### 3.3 DynamicCordisRun —— “一次激活（运行实例）”

`packages/extensions/cordis-host-runner/src/registry.ts:17-35`

```ts
export interface DynamicCordisRun {
  pluginRunId: CordisDynamicPluginRunId
  packageId: CordisDynamicPackageId
  fiber?: Fiber
  handlers: Map<string, DynamicCordisHandler>
  handlerDisposers: (() => void)[]
  reportedRuntimeErrors: Set<string>
  renderFailure?: DynamicCordisRenderFailure
  startedForRequest?: ApprovalRequestId
}
```

`[FACT]` `DynamicCordisRun` 是“当前激活”的全部执行资源句柄：Host 半的 `Fiber`、invoke handler 表、渲染失败记录。

### 3.4 DynamicCordisRunAttempt —— “一次尝试（含状态与诊断）”

`packages/extensions/cordis-host-runner/src/types.ts:143-162`

`[FACT]` `pluginRunId` 与 `DynamicCordisRun.pluginRunId` 同源（都由 `mintPluginRunId()` 铸造，`registry.ts:173`），即一次尝试与它最终产生的运行实例共享同一身份。Attempt 是“跨运行保留”的：`plugin.latestRun` 在 stop/fail 后仍保留（`stop()` 只改 status，`index.ts:456-475`）。

### 3.5 其余相关对象

| 对象 | 位置 | 角色 |
|---|---|---|
| `DynamicCordisHandler` | `registry.ts:14` | `(args: unknown) => Promise<unknown>`，Host handler 类型 |
| `DynamicCordisPendingRequest` | `registry.ts:73-83` | 一个挂起的 model-driven 激活请求（审批） |
| `DynamicCordisDefineRequest` | `registry.ts:85-99` | define 的输入：session、plugin new/existing、name、purpose、code |
| `DynamicCordisDefineReceipt` | `registry.ts:101-113` | define 的输出 |
| `DynamicCordisRegistry` | `registry.ts:141` | 进程内 Plugin Map + pending 审批 Map + ID 计数器 |
| `DynamicCordisRunnerService` | `index.ts:124` | 生命周期服务，`ctx.dynamicCordisRunner` |
| `DynamicCordisPackage` | `types.ts:165-174` | 网络广播用的“正在运行”通告类型（不是 registry 中的 Package） |
| `DynamicCordisPackageInspection` | `registry.ts:123` | 含源码的只读 inspect 结果 |
| `Fiber` | `vendor/cordis/src/fiber.ts:184` | Cordis 插件运行时实例：PENDING/LOADING/ACTIVE/FAILED/DISPOSED/UNLOADING |
| `RegistryService` | `vendor/cordis/src/registry.ts:195` | Cordis 插件注册表：`plugin()` 创建 Fiber、`delete()` 卸载全部 Fiber |
| `Context` | `vendor/cordis/src/context.ts` | Proxy 上下文，`ctx.fiber`、`ctx.plugin()`、`ctx.reflect` |
| `createSandbox()` | `sandbox.ts:129` | 每个 Host 半求值时的 `node:vm` realm |
| `DynamicCordisPackageRunner` | `cordis-client-runner/src/client/runtime.ts:177` | 浏览器半加载引擎 |
| `CordisRunOrchestrator` | `cordis-client-runner/src/client/orchestrator.ts:121` | 页面侧审批/加载编排 |

### 3.6 核心问题回答

1. **Definition 是什么？** 一个不可变源码包：`DynamicCordisDefinition`（packageId + name + purpose + host/client 源码字符串）。`[FACT]`
2. **Plugin 是什么？** 一个稳定容器：`DynamicCordisPlugin`，持有多个 Package、版本指针、审批授权、当前运行。`[FACT]`
3. **Run 是什么？** 一次激活：`DynamicCordisRun`，持有 fiber/handlers/渲染失败。`[FACT]`
4. **RunAttempt 是什么？** 一次尝试：`DynamicCordisRunAttempt`，持有状态机与诊断，即使运行结束也保留在 `latestRun`。`[FACT]`
5. **哪个对象代表“持久/逻辑身份”？** 进程内 `DynamicCordisPlugin.pluginId`；跨运行不变。`[FACT]`
6. **哪个对象代表“运行实例”？** `DynamicCordisRun`（`plugin.run`），每次激活新建，stop/替换时 `delete plugin.run`。`[FACT]`
7. **哪个对象代表“一次尝试”？** `DynamicCordisRunAttempt`（`plugin.latestRun`）。`[FACT]`
8. **哪个对象真正拥有执行资源？** `DynamicCordisRun` 持有 `Fiber` 与 handler 表；真正执行与清理由 Cordis `Fiber`（disposers/effects）承担。`[FACT]`
9. **哪些对象可以跨 Run 复用？** `DynamicCordisPlugin`（含 `packages`、`currentPackageId`、`nextPackageId`、审批授权）与 `DynamicCordisDefinition`（源码）跨 Run 复用。`[FACT]`
10. **哪些对象只能存在于一次 Run？** `DynamicCordisRun`、`Fiber`、`handlers`/`handlerDisposers`、`reportedRuntimeErrors`、`startedForRequest` 都按激活新建/销毁。`[FACT]`

---

## 4. Identity Matrix

| Object | Identity Field | 生命周期 | 是否持久 | 是否变化 |
|---|---|---|---|---|
| Definition（Package） | `packageId`（`pkg-<n>`） | 从 define 到 undefine/进程重启 | 进程内存 | 不变 |
| Plugin | `pluginId`（`<prefix>-<n>`） | 从首次 define 到 undefine/进程重启 | 进程内存 | 不变 |
| Package = Version | 无独立对象；`packageId` 即版本身份 | 同上 | 进程内存 | 不变 |
| Run | `pluginRunId`（`run-<n>`） | 一次激活 | 进程内存 | 每次激活变化 |
| RunAttempt | `pluginRunId`（与 Run 同值） | 创建后保留在 `latestRun` | 进程内存 | 每次尝试变化 |
| Approval request | `approvalId`（`approval-<n>`） | 从 arm 到 claim/disarm | 进程内存 | 每次审批变化 |
| current 指针 | `currentPackageId` | 首次成功激活后始终存在 | 进程内存 | 成功激活后更新 |
| next 指针 | `nextPackageId` | 过渡期/失败后存在 | 进程内存 | 成功提交后删除 |

铸造点：`DynamicCordisRegistry.mintPluginId/mintPackageId/mintPluginRunId/mintApprovalRequestId`（`registry.ts:154-186`），计数器为 `nextPlugin/nextPackage/nextRun/nextApproval`（`registry.ts:146-151`）。测试证明 ID 不复用：`runner.spec.ts:98-123`（第一次 define 得 `dyn-1/pkg-1`，第二次得 `dyn-2/pkg-2`）。

**10 次连续运行同一个 Plugin：**

- `pluginId`：不变。`[FACT]`
- `packageId`：不变（若每次都 run 同一个 Package）。`[FACT]`
- `pluginRunId`：每次变化（`run-1` … `run-10`）。`[FACT]`
- `currentPackageId`：直到下一次成功激活才变化；10 次同包运行后仍指向该包。`[FACT]`
- `latestRun`：每次运行被新 Attempt 替换。`[FACT]`

---

## 5. Define Call Graph

### 5.1 调用链

```
cordis_define（模型工具）
  → tool-cordis/src/index.ts:149  cordis_define.parameters/execute
    → DynamicCordisRunnerService.define()   index.ts:151
      → precheckCode(code.host) / precheckCode(code.client)   sandbox.ts:206（只编译，不执行）
      → kind==='new'：registry.mintPluginId(prefix) + registry.add(plugin)   registry.ts:154,189
      → kind==='existing'：registry.get(pluginId)（校验 session 所有权）   registry.ts:198
      → registry.mintPackageId()   registry.ts:165
      → plugin.packages.set(packageId, definition)   registry.ts（对象字段）
      → 返回 DynamicCordisDefineReceipt   registry.ts:101
```

### 5.2 每一步的 Input / State Mutation / Output

| 步骤 | Input | State Mutation | Output |
|---|---|---|---|
| `cordis_define` 工具 | `plugin`（new/existing）、`name`、`purpose`、`code.host/client` | 无（仅工具调用本身会进 session log） | 工具结果（receipt JSON） |
| `define()` 校验 | 上述请求 | 无 | 校验失败抛 Error |
| `precheckCode()` | 源码字符串 + half 名 | 无（`new Script(...)` 只 parse） | 抛 SyntaxError 教学信息 |
| new 分支 | `idPrefix`（3-6 位小写字母） | `registry.add(plugin)`；`pluginId = <prefix>-<n>` | plugin 记录 |
| existing 分支 | `pluginId` | 无（只读已存在 plugin） | plugin 引用 |
| package mint | — | 计数器 `nextPackage++` | `pkg-<n>` |
| packages.set | definition | `plugin.packages` 增加一个不可变 Package | receipt：pluginId/packageId/name/purpose/hasHostHalf/hasClientHalf |

### 5.3 重点回答

1. **define 的输入**：`DynamicCordisDefineRequest`（`registry.ts:85-99`）：sessionId、plugin new/existing、name、purpose、code.host/client。`[FACT]`
2. **输入是 source code、package、manifest 还是其他？** 是**源码字符串**（两个可选字段 `host`/`client`），不是 package 文件、manifest 或对象。`[FACT]`
3. **define 是否执行代码？** 不执行。`precheckCode` 只用 `new Script(...)` 编译；注释明确 “Compile-only…runs nothing”（`sandbox.ts:206-225`）。`[FACT]`
4. **define 是否创建 Plugin？** `kind:'new'` 创建；`kind:'existing'` 只追加 Package。`[FACT]`（`index.ts:159-183`）
5. **define 是否创建 Package？** 是：`mintPackageId()` + `plugin.packages.set(...)`。`[FACT]`（`index.ts:183-192`）
6. **define 是否生成 ID？** 是：pluginId + packageId。`[FACT]`
7. **ID 从哪里来？** 进程内 `DynamicCordisRegistry` 计数器：`nextPlugin`、`nextPackage`（`registry.ts:146-151`）。`[FACT]`
8. **是否存在 name？** 存在，但属于 Package（`DynamicCordisDefinition.name`）；Plugin 本身无 name。`[FACT]`
9. **是否存在 version？** 没有 `version` 字段；版本身份就是 `packageId`，当前/目标由 `currentPackageId`/`nextPackageId` 表达。`[FACT]`
10. **是否存在 hash / digest？** `[NOT_FOUND]`：define 请求、definition、plugin 中均无 hash/digest 字段。
11. **是否存在 metadata？** 只有 `name` + `purpose`；无自由 metadata 字段。`[FACT]`
12. **是否存在 dependencies？** define 输入无 dependencies；运行时依赖是 Cordis `inject`（写在返回的 plugin 上，`guardedPlugin` 保留 `plugin.inject`，`guard.ts:802-836`）。`[FACT]`
13. **是否存在 permissions？** define 输入无 permissions。运行时授权是 `approvedClientPackages` Set + `clientVersionUpdatesApproved`（`registry.ts:56-57`），在 run/审批时写入。`[FACT]`
14. **是否存在 sandbox policy？** 无 policy 字段；唯一相关配置是 Service `Config.vmTimeoutMs`（`index.ts:131-133`）。`[FACT]`
15. **define 后 Registry 保存什么？** Plugin 记录 + `packages` Map（含源码）；current/next 为 undefined；审批集合为空。`[FACT]`
16. **define 是否持久化？** 否。registry 是 `Map`（`registry.ts:142-145`）；`missingPluginMessage` 明说 “lost on DSH restart”（`index.ts:1247-1249`）。`[FACT]`
17. **define 是否幂等？** 否。`kind:'new'` 每次都铸造新 pluginId；`kind:'existing'` 每次都追加新 packageId。`[FACT]`（测试 `runner.spec.ts:98-123`）
18. **同 ID 再 define 会发生什么？** `kind:'existing'` 且 session 匹配 → 在同一个 Plugin 上追加新 Package；`kind:'new'` 用同前缀 → 铸造新 pluginId（suffix 递增，不复用）。`[FACT]`
19. **define 失败会留下什么状态？** name/purpose/code/precheck 失败全部发生在任何 registry 写入之前（`index.ts:151-168`），测试 `runner.spec.ts:124-134` 证明失败后 registry 为空。`[FACT]`

---

## 6. Run Call Graph

### 6.1 Host-only（无 client 半）路径

```
cordis_run（模型工具）
  → tool-cordis/src/index.ts:241
    → DynamicCordisRunnerService.run(agent, pluginId, packageId, mode, signal)   index.ts:254
      → resolvePlan()    index.ts:768（校验 plugin/package/mode/transition）
      → createAttempt()  index.ts:1174（mint run-N；status='starting-host'）
      → plugin.nextPackageId = packageId; plugin.latestRun = attempt   index.ts:268-270
      → activate()   index.ts:810（`starting` Map 去重）
        → startFresh()   index.ts:823
          → 若 plugin.run 存在：await retract(plugin)   index.ts:1219（dispose fiber/handlers、发 retract 事件）
          → 构造 DynamicCordisRun（无 fiber）   index.ts:844-852
          → startHost()   index.ts:883
            → createSandbox(pluginId, { handle })   sandbox.ts:129
            → evaluateHostCode(sandbox, hostCode, pluginId, vmTimeoutMs)   sandbox.ts:227
            → isPlugin()   guard.ts:790
            → startHostHalf(group, guardedPlugin(...), reportGuardFailure)   lifecycle.ts:22
              → group.ctx.plugin(guardedPlugin(...))   vendor/cordis/src/registry.ts:316（创建 Fiber）
              → await fiber.await()   vendor/cordis/src/fiber.ts:704（apply 执行）
              → run.fiber = fiber   index.ts:917
          → plugin.run = run   index.ts:873
          → ctx.emit('cordis/dynamic-package', ...)   index.ts:874-880
          → 无 clientCode：commitActivation()   index.ts:981
            → currentPackageId = run.packageId；delete nextPackageId；attempt.status='running'/'waiting'   index.ts:981-992
      → runResponse()   index.ts:995 → 返回 { ok:true, status:'running', pluginId, packageId, pluginRunId, ... }
```

### 6.2 Client-bearing（需页面）路径

```
run()   index.ts:254
  → attempt.status = 'awaiting-approval' | 'starting-host'   index.ts:291-294
  → registry.armRequest(requestId, pending)   registry.ts:233
  → ctx.emit('cordis/request-run', {requestId, agentId, pluginId, packageId, mode, name, purpose, requiresApproval})   index.ts:304-314
  → 立即返回 { ok:true, status:'awaiting-approval'|'starting' }   index.ts:316-329

浏览器页面（CordisRunOrchestrator.drive）   client/orchestrator.ts:333
  → runHostHalf(agent, pluginId, packageId, mode, requestId, approveFutureVersions)   index.ts:332
    → 校验 pending/latestRun；必要时写 approvedClientPackages / clientVersionUpdatesApproved   index.ts:349-380
    → activate() → startFresh()（同上 host 路径）
    → attempt.status='client-pending'   index.ts:919-925
  → getClientCode(agent, pluginId, pluginRunId)   index.ts:388（只有 active run 才能取到 client 源码）
  → DynamicCordisPackageRunner.load(half)   client/runtime.ts:288
    → evaluateClientHalf()   client/evaluator.ts:129
    → modules.invalidate + __ModuleLoader__.load + loader.create   runtime.ts:365-376
    → fiber.await()   runtime.ts:379-388
  → resolveRequestRun(requestId, resolution)   index.ts:415
    → registry.claimRequest()   registry.ts:251
    → settleActivation()   index.ts:918
      → attempt.client.status = 'running'|'waiting'   index.ts:958-968
      → commitActivation()   index.ts:981
    → ctx.emit('cordis/request-run-resolved', ...)   index.ts:1010-1017
    → steerRunOutcome() 给 Agent 注入结果消息   index.ts:1019-1047
```

### 6.3 重点回答

1. **run 输入是什么？** `(agent, pluginId, packageId, mode, signal?)`，`mode: 'run' | 'update'`（`types.ts:91`）。`[FACT]`
2. **run 是否创建 Run？** 是：`startFresh()` 内构造 `DynamicCordisRun`，成功后写 `plugin.run`。`[FACT]`（`index.ts:844-873`）
3. **Run 是否绑定 Plugin？** 是：`plugin.run = run`；但 Run 对象本身不存 `pluginId`（通过 `plugin.run` 反向绑定）。`[FACT]`
4. **Run 是否绑定 Package Version？** 是：`run.packageId`。`[FACT]`（`registry.ts:19`）
5. **Run 是否创建 RunAttempt？** run 入口先 `createAttempt()`，再 `startFresh()`；Attempt 的 `pluginRunId` 就是 Run 的 `pluginRunId`。`[FACT]`（`index.ts:269,1174`）
6. **RunAttempt 什么时候创建？** 任何新激活开始时：`run()` 立即创建；`runHostHalf(requestId=null)` 在“不是 attach”时创建（`index.ts:356-370`）。`[FACT]`
7. **Fiber 什么时候创建？** host 半求值成功、`isPlugin` 通过后，在 `startHostHalf` 的 `group.ctx.plugin(...)` 中创建（`lifecycle.ts:22-52`；`registry.ts:316-334`）。`[FACT]`
8. **Sandbox 什么时候创建？** 每次 host 激活在 `startHost` 内创建（`index.ts:893-895` → `sandbox.ts:129`）。`[FACT]`
9. **Tool / Handler 什么时候注册？** `harness.handle` 可以在 host 代码顶层求值期间注册（`index.ts:884-895` 的 `handle` 闭包）；`harness.registerTool` 在 plugin `apply(ctx)` 执行期间通过 guarded ctx 注册（`guard.ts:626-634`）。`[FACT]`
10. **Plugin 什么时候真正开始执行？** `fiber.await()` 时执行 `apply`；`startHostHalf` 等待 `fiber.await()` 成功后才返回（`lifecycle.ts:22-52`；`fiber.ts:704-714`）。`[FACT]`
11. **run 返回什么？** `DynamicCordisRunResponse`：成功为 `{ok:true, status, pluginId, packageId, pluginRunId, waitingFor, currentPackageId?, nextPackageId?, mode}`；失败为 typed refusal（`types.ts:267-303`）。`[FACT]`
12. **run 返回的是 Plugin、Run、Attempt 还是 Result？** 都不是对象本身；返回的是**带身份字段的 JSON receipt**（tool 再渲染为文本）。`[FACT]`

### 6.4 文档冲突（以源码为准）

`cordis-host-runner/README.md` 声称 run 请求在“caller's AbortSignal”取消时退出；但源码 `run()` 只在入口检查一次 `signal?.aborted`（`index.ts:258-260`），没有对 signal 注册任何 listener；测试 `runner.spec.ts:380-400` 证明发布后的请求在 abort 后仍可被页面回答（`accepted: true`）。`[FACT]`：发布后的审批只能被 `stop()`/`undefine()`/后续页面回答终止，abort 本身不取消。

---

## 7. Version Model

### 7.1 版本是什么

`[FACT]` 没有独立 `Version` 对象。版本身份 = `CordisDynamicPackageId`（`pkg-<n>`，`types.ts:13`）；状态由 Plugin 上的两个指针表达：

- `currentPackageId`：最近一次**完整成功**激活的 Package（`registry.ts:65`）。
- `nextPackageId`：失败或进行中的过渡目标（`registry.ts:66`）。

### 7.2 重点回答

1. **一个 Plugin 是否可以有多个 Package？** 是：`packages: Map`，define 顺序追加（`registry.ts:55`）。`[FACT]`
2. **Package 是否就是 Version？** 是（源码层面）：不可变源码包即版本；没有版本号字符串。`[FACT]`
3. **currentPackageId 是什么？** “最近一次成功激活的版本”指针，只在 `commitActivation()` 更新（`index.ts:981-992`）。`[FACT]`
4. **nextPackageId 是什么？** 正在尝试/失败的过渡目标，在 `run()`/`startFresh()` 中写入（`index.ts:268,843`）。`[FACT]`
5. **current / next 如何产生？** 由运行尝试产生，不是 define 产生。首次 run：`next=目标`；成功：`current=目标, next=delete`。`[FACT]`
6. **update 是否创建新 Package？** 不创建。update 只是激活一个已 define 的 Package；创建发生在 define。`[FACT]`（`resolvePlan` 只查 `plugin.packages.get(packageId)`，`index.ts:779-783`）
7. **新版本何时成为 current？** 只有完整成功后才 `currentPackageId = run.packageId`；host-only 在 host 启动成功后；client 包在页面 `settleActivation` 成功后。`[FACT]`
8. **active Run 使用哪个 Package？** `plugin.run.packageId`（`registry.ts:19`）。`[FACT]`
9. **新 Run 使用哪个 Package？** 目标 Package，`startFresh` 构造 run 时写入（`index.ts:844-852`）。`[FACT]`
10. **更新期间旧 Run 怎么办？** `startFresh` 在启动新 Run 前 `await retract(plugin)` 停止旧 Run（`index.ts:835`）。`[FACT]`
11. **update 失败怎么办？** 旧 Run 不会恢复；`currentPackageId` 保持旧值、`nextPackageId` 保持目标值、`plugin.run` 为 undefined（`failAttempt` 只写 attempt，`index.ts:1191-1201`）。`[FACT]`
12. **next 是否会被删除？** 成功提交时 `delete plugin.nextPackageId`（`index.ts:983`）；undefine 时随 Plugin 删除。stop/失败不删除。`[FACT]`
13. **current 是否始终保留？** 在 Plugin 生命周期内始终保留最近成功值；stop/失败不清除；只有下一次成功激活覆盖或 undefine 删除。`[FACT]`

### 7.3 Version State Machine（源码可证明的转移）

```
[define]  pkg 进入 plugin.packages；current/next 不变
    ↓
[首次 run / update 开始]  nextPackageId = 目标
    ↓
[host 启动 + client 完成（完整成功）]
    currentPackageId = 目标；nextPackageId 删除
    ↓
[stop]  current 保留；next 保留；run 消失
    ↓
[run(currentPackageId, mode:'run') = rollback]
    current 不变；成功后 next 删除
    （失败：current/next 都不变，无 run）
```

`[FACT]`：每一步都对应 `index.ts:268,843,981-992,1219-1235` 与测试 `versioning.spec.ts:7-38`。

---

## 8. Rollback

### 8.1 结论

`[NOT_FOUND]`：**不存在 `rollback()` / `revert()` / `restore()` API**。

- Host runner service 中没有 rollback 方法（全文搜索 `rollback|revert|restore` 无 service 符号）。
- `cordis_run` 工具把 “rollback” 定义为 `mode:'run'` + `packageId=currentPackageId`（`tool-cordis/src/index.ts:243-259`）。
- 面板的 “Roll back” 按钮直接调用 `onRun({ packageId: currentPackageId, mode: 'run', ... })`（`ui-cordis/src/client/CordisPanel.tsx:391`）。
- 测试名本身把它写成 rollback：`versioning.spec.ts:7` “keeps currentPackageId when an update fails and clears nextPackageId after rollback”。

### 8.2 Rollback Call Graph

```
Before:
  plugin.currentPackageId = A
  plugin.nextPackageId = B（B 上次 update 失败）
  plugin.run = undefined
    ↓
cordis_run(pluginId, packageId=A, mode='run')
  → resolvePlan：mode='run' 且 current===A → 允许   index.ts:787-794
  → createAttempt（mint run-N）
  → startFresh：
      plugin.run 存在则 retract（这里没有）
      mode==='update' || current===undefined 才写 nextPackageId
      → rollback 是 mode='run' 且 current 已定义，所以**不写 nextPackageId**   index.ts:843
  → startHost(A) → fiber 新建
  → plugin.run = run(A)；emit dynamic-package
  → commitActivation：currentPackageId=A；delete nextPackageId   index.ts:981-992
    ↓
After:
  plugin.currentPackageId = A
  plugin.nextPackageId = undefined
  plugin.run = run-N（A 在跑）
  packages 里 B 仍在（未删除）
```

注意 `index.ts:843`：`if (mode === 'update' || plugin.currentPackageId === undefined) plugin.nextPackageId = definition.packageId`。rollback 走 `mode:'run'` 且 `current` 已存在，因此不会重写 next；残留的 next（如失败的 B）由成功后的 `commitActivation` 统一删除。

### 8.3 重点回答

1. **rollback 入口**：`cordis_run` 工具（`mode:'run'`）或面板按钮（`CordisPanel.tsx:391`）；都汇入 `run()`。`[FACT]`
2. **操作对象**：`DynamicCordisPlugin` 的 current/next 指针与 `plugin.run`。`[FACT]`
3. **是代码包 rollback？** 否：不删除、不覆盖目标 Package；旧 Package 一直还在 `packages` Map。`[FACT]`
4. **是 Registry rollback？** 否：registry 没有快照/恢复逻辑。`[FACT]`
5. **是 Runtime rollback？** 是：重新激活 current 版本，旧运行被 retract，新 fiber 启动。`[FACT]`
6. **active Run 是否停止？** 是：`startFresh` 先 `retract` 旧 run（`index.ts:835`）。`[FACT]`
7. **old Package 是否恢复？** 是：重新作为运行版本；`currentPackageId` 本来就没变，成功后仍指向它。`[FACT]`
8. **new Package 是否删除？** 否。`[FACT]`
9. **Run 是否重新创建？** 是：新 `pluginRunId`。`[FACT]`
10. **Fiber 是否重新创建？** 是：每次 startHost 都 `group.ctx.plugin(...)` 新建 Fiber。`[FACT]`
11. **rollback 是否幂等？** 服务层不是“无操作幂等”：对已 running 的 current 再 run 是 restart（新 run-N）；对 stopped 的 current run 是启动。`[FACT]`
12. **rollback 失败怎么办？** 与 run 失败相同：current 保持、next 保持（残留值）、无 run、attempt failed。`[FACT]`（`index.ts:1191-1201`）
13. **rollback 后 currentPackageId 是什么？** 仍是原 current（数值不变）；若 rollback 前 next 存在，成功后 next 被删除。`[FACT]`

### 8.4 四个概念的区分（源码事实）

| 概念 | 源码对应 |
|---|---|
| Rollback Package | `run(currentPackageId, mode:'run')`：重新激活旧版本，不删新版本 |
| Restart Run | `run(当前 packageId, mode:'run')`：同一版本新开 activation |
| Stop Run | `stop(pluginId)`：retract 当前 run，不激活任何版本 |
| Undefine Plugin | `undefine(pluginId)`：retract + 删除 Plugin 与全部 Package |

---

## 9. Stop Semantics

入口：`DynamicCordisRunnerService.stop(agent, pluginId)`（`index.ts:456-475`），面板 `stopFromPanel`（`index.ts:480`），模型工具 `cordis_stop`（`tool-cordis/src/index.ts:330`）。

```
stop(agent, pluginId)
  → owned() 校验 session 所有权   index.ts:1232
  → 若 pending request 存在：cancelPending()   index.ts:1159
      （claim request → latestRun.status='cancelled' → emit request-run-resolved cancelled）
  → 若 plugin.run 存在：await retract(plugin)   index.ts:1219
      delete plugin.run
      遍历 handlerDisposers 全部 dispose
      await run.fiber.dispose()（若 host 半存在）
      emit('cordis/dynamic-retract', {pluginId, packageId, pluginRunId})
  → latestRun.status='stopped'；host/client half status='stopped'   index.ts:469-474
```

### Stop Semantics 表

| 对象 | stop 影响 | 证据 |
|---|---|---|
| Plugin（registry 记录） | 保留 | `registry.ts:51-70`；stop 不调 delete |
| Package | 保留 | stop 不触碰 `packages` |
| currentPackageId / nextPackageId | 保留 | `index.ts:456-475` 无删除；`stopFromPanel` 消息明说 “currentPackageId is …” |
| Run | 删除（`delete plugin.run`） | `index.ts:1221` |
| Attempt | 保留为 `latestRun`，status→`stopped` | `index.ts:469-474` |
| Fiber | `await run.fiber.dispose()` | `index.ts:1228` |
| Handler | `handlerDisposers` 全部执行 | `index.ts:1224-1226` |
| Tool | 随 fiber dispose 卸载（tool 注册是 fiber effect） | `composition.spec.ts:160-171` |
| Sandbox（host） | 无独立对象可销毁；vm realm 随求值闭包/GC | `[UNKNOWN]`（无显式 sandbox 生命周期代码） |
| 页面 Client 半 | 通过 retract 事件卸载 | `client-runner/src/client/runtime.ts:309-317` |
| Registry 条目 | 保留 | `[FACT]` |

重点回答：

1. **stop 接受什么 ID？** 只接受 `pluginId`；没有 per-run stop。`[FACT]`
2. **stop 停止 Plugin 还是 Run？** Run；Plugin 记录与版本保留。`[FACT]`
3. **停止 Run 还是 RunAttempt？** Run（物理执行）被删除；RunAttempt 保留为历史状态。`[FACT]`
4. **Fiber 是否停止？** 是，`fiber.dispose()`。`[FACT]`
5. **Sandbox 是否销毁？** host 无显式销毁对象；client 页面通过 `teardown` 卸载（`runtime.ts:443-459`）。`[UNKNOWN]`（host realm GC 无源码证据）
6. **Tool 是否 unregister？** 是（fiber effects 级联）。`[FACT]`
7. **Handler 是否 unregister？** 是，`handlerDisposers`。`[FACT]`
8. **Registry 中的 Plugin 是否还存在？** 是。`[FACT]`
9. **Package 是否还存在？** 是。`[FACT]`
10. **Stop 后能否再次 Run？** 能，新 activation（测试 `runner.spec.ts:422-444`：stop 后 run 得 `run-2`）。`[FACT]`
11. **Stop 是否幂等？** service 层：无 run 且无 pending 时返回 `{ok:false, reason:'not-running'}`（`index.ts:462-465`）；工具层把 `not-running` 当作成功吞掉（`tool-cordis/src/index.ts:342-346`）。`[FACT]`
12. **Stop 失败怎么办？** 非运行直接返回 not-running；plugin 不存在返回 plugin-missing；无其他状态恢复逻辑。`[FACT]`

---

## 10. Undefine Semantics

入口：`DynamicCordisRunnerService.undefine(agent, pluginId)`（`index.ts:210-224`），面板 `undefineFromPanel`（`index.ts:227`），模型工具 `cordis_undefine`（`tool-cordis/src/index.ts:352`）。

```
undefine(agent, pluginId)
  → owned() 校验
  → wasRunning = plugin.run !== undefined
  → cancelPending(pluginId, "removed before approval")   index.ts:1159
  → 若 run 存在：await retract(plugin)   index.ts:1219
  → registry.delete(pluginId)   registry.ts:207
  → { ok:true, wasRunning }
```

### Undefine Semantics 表

| 对象 | undefine 影响 | 证据 |
|---|---|---|
| Plugin | 删除（含所有字段） | `registry.ts:207-211` |
| Package | 删除（随 Plugin Map） | 同上 |
| currentPackageId / nextPackageId | 删除（随 Plugin） | 同上 |
| Run | retract 后删除 | `index.ts:216-219,1219` |
| Attempt | 删除（随 Plugin） | `registry.ts:207` |
| Fiber | retract 中 dispose | `index.ts:1228` |
| Handler | retract 中 dispose | `index.ts:1224-1226` |
| Tool | 随 fiber dispose 卸载 | `composition.spec.ts:160-171` |
| Pending approval | cancelPending | `index.ts:216` |
| Client 页面 | retract 事件 → `teardown` | `client-runner/src/client/runtime.ts:309` |

重点回答：

1. **接受 Plugin ID 还是 Package ID？** Plugin ID。`[FACT]`
2. **undefine 前是否必须 stop？** 不必；undefine 自动 stop。`[FACT]`
3. **是否自动 stop？** 是：`wasRunning` 记录后调 `retract`。`[FACT]`
4. **active Run 怎么处理？** 被 retract（fiber dispose + handlers 清理 + retract 广播）。`[FACT]`
5. **Package 是否删除？** 是。`[FACT]`
6. **currentPackageId 是否清除？** 是（随对象删除）。`[FACT]`
7. **nextPackageId 是否清除？** 是（随对象删除）。`[FACT]`
8. **Registry entry 是否删除？** 是，`Map.delete`。`[FACT]`
9. **Tool / Handler 是否删除？** 是（retract）。`[FACT]`
10. **Fiber 是否清理？** 是。`[FACT]`
11. **Sandbox 是否清理？** host 无显式 sandbox 对象；client 页面 teardown。`[UNKNOWN]`
12. **undefine 后是否还能 run？** 不能，`run` 返回 `plugin-missing`（测试 `runner.spec.ts:472-488`）。`[FACT]`
13. **undefine 是否幂等？** 第二次返回 `{ok:false, reason:'plugin-missing'}`（`index.ts:212-214`；测试 `runner.spec.ts:489-496`）。`[FACT]`：安全但不是“成功幂等”。

### Stop vs Undefine

| | Stop | Undefine |
|---|---|---|
| Plugin 记录 | 保留 | 删除 |
| Packages | 保留 | 删除 |
| current/next | 保留 | 删除 |
| Run/Fiber/Handler/Tool | 停止 | 停止并删除 |
| 再次 run | 允许 | `plugin-missing` |
| 模型语义 | 临时停用，版本仍可用于 rollback | 永久移除 |

---

## 11. Failure / Recovery Matrix

先给结论：源码中的“恢复”是**指针保留 + 诊断 + 让模型重试**，不是自动恢复。没有任何自动重启旧版本、自动清理 next、重放请求的逻辑。

| Operation | Failure Point | State After Failure | Cleanup | Retry | Recovery |
|---|---|---|---|---|---|
| Define | name/purpose/code/precheck | 无 mutation | 无需 | 修复参数重调 | 无 |
| Run (host) | `evaluateHostCode` 抛错 / `fiber.await()` 抛错 | `plugin.run` 无；attempt failed；`nextPackageId` 保持；`currentPackageId` 不变 | `startHost` catch 中 dispose 全部 handlerDisposers；`startHostHalf` 对已建 fiber `dispose()` 后再抛 | `cordis_run` 重试（修复或 define 新包） | 无自动恢复；steer 消息指导重试 |
| Run (client approval) | 用户拒绝 | attempt rejected；无 run；current/next 不变 | 无 | 用户明确要求前禁止重试（steer 消息） | 无 |
| Run (client load/apply) | 页面 load 失败 | 若该页 ownsRun → retract；attempt failed(client-apply)；current 不变；next 保持 | `teardown`；styles dispose | 模型 inspect 后重试 | 无自动恢复 |
| Update | host/client 任一失败 | 旧 run 已被 retract（不恢复）；current=旧包；next=新包；无 run | 同 Run failure | `run(current,'run')` = rollback；或修复后 `run(new,'update')` | `currentPackageId` 保留作为回退锚点 |
| Rollback | host 启动失败 | current/next 不变；无 run；attempt failed | 同 Run failure | 重试 | 无 |
| Stop | 无 run / plugin missing | `not-running`/`plugin-missing`；无状态变化 | 无 | 工具层吞掉 not-running | 无 |
| Undefine | plugin missing | 无状态变化 | 无 | 无 | 无 |
| Invoke | handler 抛错 | run 保持运行；`reportedRuntimeErrors` 去重后 steer 一次 | 无 | 模型修复后 update | `claimRuntimeFailure` 防止重复骚扰（`index.ts:1120-1131`） |

关键源码点：

- `startHost` catch：`for (const dispose of run.handlerDisposers.splice(0)) dispose()`（`index.ts:925-928`）。
- `startHostHalf`：`catch { await fiber.dispose(); throw ... }`（`lifecycle.ts:32-50`）。
- 失败后 attempt：`failAttempt()` 写 `status:'failed'` + `phase` + half status（`index.ts:1191-1201`）。
- 不自动恢复旧版本：steer 文本明确 “Failure does not automatically restart the old version; retry next with update or roll back to current with run”（`tool-cordis/src/prompt.ts:46`）。
- “有 catch ≠ recovery”：`fiber._unload()` 的 disposer 失败只 `ctx.logger.error`（`vendor/cordis/src/fiber.ts:679-693`）；没有状态恢复。

---

## 12. Multi-Run Semantics

### 12.1 同一 Plugin 能否同时 Run 多次？

`[FACT]` **Host 侧一个 Plugin 同时最多一个 active Run**：

- `DynamicCordisPlugin.run` 是单值可选字段（`registry.ts:63`）。
- `startFresh` 启动新 Run 前 `await retract(plugin)`（`index.ts:835`）。
- `run()` 在已有 pending request 时拒绝 `transition-in-flight`（`index.ts:262-265`）。
- `resolvePlan` 在 `starting.has(pluginId)` 时拒绝（`index.ts:795-801`）。

### 12.2 并发保护（源码中的机制）

| 机制 | 位置 | 作用 |
|---|---|---|
| `starting: Map<pluginId, Promise<HostHalfResult>>` | `index.ts:134,810-821` | Host 半启动去重：并发 `runHostHalf` 共享同一次求值 |
| `pendingRequests: Map<approvalId, pending>` | `registry.ts:143,233-268` | 审批 arm/peek/claim/disarm；`claimRequest` 首答胜出 |
| `resolvePlan` transition-in-flight | `index.ts:795-801` | 启动中的 Plugin 拒绝新 run |
| `resolveRequestRun` 身份校验 | `index.ts:425-431` | stale/late 回答 `accepted:false` |
| Client `inFlight: Map<pluginId, Promise>` | `client/orchestrator.ts:128,312-330` | 页面侧每个 Plugin 一次编排 |
| Client `queues: Map<pluginId, Promise>` | `client/runtime.ts:334-341` | 页面 load/unload 按 Plugin 串行 |

`[NOT_FOUND]`：Host registry 没有 `Mutex`/`Lock`/`Queue` 类；串行化靠上述 Map + 状态检查。

### 12.3 相互影响

| 场景 | 结果 | 证据 |
|---|---|---|
| Plugin P 已有 run A，再 run B | A 被 retract，B 成为唯一 run | `index.ts:835`；`runner.spec.ts:247-269` |
| 两个页面并发 runHostHalf(P) | 共享同一个 activation（同一 `pluginRunId`，第二次 `startedHere:false`） | `index.ts:810-821,844-857`；`runner.spec.ts:289-302` |
| Stop P | 只影响 P 的当前 run；其他 Plugin 不受影响 | `stop()` 只操作 `owned(agent, pluginId)` |
| 旧请求 A 的回答来晚了 | `accepted:false`；不会停掉新 run B | `resolveRequestRun` 检查 `plugin.run.pluginRunId`（`index.ts:425-431`）；`runner.spec.ts:328-355` |
| Update/rollback 期间旧 run | 旧 run 先 retract，再启动新 run | `index.ts:835` |
| Undefine P 时 P 在跑 | retract + delete | `index.ts:210-224` |
| A stop 后 B 已启动 | stop 停的是当前 B，不是历史 A | 无 per-run stop API；`retract` 只处理 `plugin.run` |

### 12.4 图示

```
Plugin P
  ├── Run A（pluginRunId=run-1）
  └── Run B（pluginRunId=run-2）

startFresh(B) 时：
  Run A → retract（fiber dispose、handlers 清空、dynamic-retract 广播）
  Run B → 成为 plugin.run

随后 stop(P)：
  Run A 已不存在；Run B → retract；P 的 Packages/current/next 保留
```

---

## 13. Tool / Handler / Service Lifecycle

### 13.1 Handler（Host 方法）

- 注册：`harness.handle(method, fn)`（sandbox 全局）→ `normalizeHandler()`（`guard.ts:604-622`）→ `run.handlers.set()` + `run.handlerDisposers.push()`（`index.ts:884-895`）。
- 调用：Client `host.call(method, args)` → `invoke(pluginId, pluginRunId, method, args)`（`index.ts:746-772`），校验 plugin 在跑、runId 匹配、method 存在，最后 `await handler(args)`。
- 删除：retract 时 `handlerDisposers` 全部执行（`index.ts:1224-1226`）。

`[FACT]` Handler **属于 Run**：表存在 `DynamicCordisRun` 上，不是 Plugin/Package 级。

### 13.2 Tool（动态注册的模型工具）

- 定义：`harness.defineTool(options)`（`guard.ts:551-601`），JSON 规范化 + 校验 + marker。
- 注册：`harness.registerTool(ctx, tool)` → `ctx.tools.register(tool)`（`guard.ts:626-634`），在 guarded context 的 `tools` 白名单内（`guard.ts:648-667`）。
- 生命周期：注册发生在 plugin `apply` 执行时，属于该次 Fiber；stop/retract 时 fiber dispose 级联卸载。测试 `composition.spec.ts:160-171`：stop 后工具消失，下次 run 重新注册。

`[FACT]` Tool **属于 Run（activation）**，不跨 Run 共享；同一 Package 每次 run 都会重新注册。

### 13.3 Service（ctx.provide / inject）

- 动态代码通过 guarded `ctx.provide` 提供服务（`guard.ts:648,718-788`）；服务注册是 fiber effect（`vendor/cordis/src/reflect.ts:277-309`）。
- 跨 Package 依赖：consumer 声明 `inject`，provider 停止时 consumer 回到 PENDING 并卸载注册，provider 再 run 时 consumer 重新激活（`composition.spec.ts:42-85`）。
- `missingServices()` 把“settled 但未 active”的 fiber 解释为等待 `inject` 中缺失的服务（`lifecycle.ts:55-61`）。

### 13.4 回答

1. **Tool 属于 Plugin 还是 Run？** Run（activation）。`[FACT]`
2. **Handler 属于 Plugin 还是 Run？** Run。`[FACT]`
3. **Tool 是否随着 Run 创建？** 是（apply 期间注册）。`[FACT]`
4. **Tool 是否随着 Stop 删除？** 是。`[FACT]`
5. **Tool 是否随着 Undefine 删除？** 是（先 retract）。`[FACT]`
6. **Tool 是否绑定具体 Package？** 绑定的是该次 run 的 Package 源码；同一 Package 的新 run 会重新注册。`[FACT]`
7. **Tool 是否可以跨 Run 共享？** 否。`[FACT]`

---

## 14. Sandbox / Security

### 14.1 Host 半（`node:vm`）

- `createSandbox()`（`sandbox.ts:129-162`）：fresh vm realm；globals 只有 tagged console、`harness`、btoa/atob、TextEncoder/TextDecoder、Node-API traps。
- `NODE_API_REDIRECTS`（`sandbox.ts:96-108`）：`require`/`setTimeout`/`setInterval`/`setImmediate`/`fetch` 调用即抛教学错误；`process`/`Buffer` 保持 undefined。
- 测试 `sandbox.spec.ts:45-66`：sandbox 内无 `process`/`Buffer`，`globalThis` 写入不泄漏到 host。
- `vmTimeoutMs`：只限制同步求值（`sandbox.ts:227-244`；测试 `sandbox.spec.ts:138-144`）。
- **不是安全边界**：源码注释明确 “This keeps cooperative packages inspectable and disposable but is not containment: host-realm helper functions remain an escape route”（`sandbox.ts:8-11`）。

### 14.2 Client 半（闭包）

- `evaluateClientHalf()`（`client/evaluator.ts:129-177`）：`new Function(...parameters, ...)`，参数名覆盖 `setTimeout`/`fetch`/`require` 等全局（`closureTraps`，`evaluator.ts:55-76`）；`process`/`Buffer` 传 `undefined`。
- `harness` 在浏览器侧是 Proxy trap（`evaluator.ts:78-87`）。

### 14.3 权限 / 审批

| 问题 | 回答 | 证据 |
|---|---|---|
| Plugin 是否真正 sandbox？ | host 半有 vm 隔离但不是安全边界；client 半是闭包参数遮蔽 | `sandbox.ts:1-13`；`evaluator.ts:43-76` |
| Sandbox 生命周期绑定谁？ | host：每次 host 半求值新建（`startHost`）；client：每次 load 新建 styles/closure，teardown 时清理 | `index.ts:893-895`；`runtime.ts:343-459` |
| Sandbox 是 Plugin 级、Run 级还是 Attempt 级？ | Run 级（每次激活求值一次）；并发 attach 共享同一次求值 | `index.ts:810-821` |
| Stop 是否销毁 Sandbox？ | host 无显式销毁；client 页面 teardown；`[UNKNOWN]` host realm GC | — |
| Undefine 是否销毁 Sandbox？ | 同上 | — |
| 权限是静态还是动态？ | 动态：授权集合在 run/审批时写入 | `index.ts:349-380` |
| Approval 是 Define 时还是 Run 时？ | Run 时；仅 client-bearing 包需要 | `index.ts:277-298`；`tool-cordis/src/index.ts:243-259` |
| 失败后权限是否撤销？ | 不撤销：`approvedClientPackages`/`clientVersionUpdatesApproved` 只增不减，唯一删除路径是 undefine | `registry.ts:56-57`；无删除逻辑 `[FACT]` |

`[NOT_FOUND]`：define 请求无 permissions / sandbox policy / allowlist 字段（`registry.ts:85-99`）。

---

## 15. Persistence

### 15.1 源码事实

- `DynamicCordisRegistry` 只有两个 `Map` 和四个计数器（`registry.ts:141-151`）；host-runner 的 src 不 import 任何 fs/db/yaml/json 持久化模块。
- `missingPluginMessage` 明确：Plugin 不存在 “may have been removed or lost on DSH restart”（`index.ts:1247-1249`）。
- Client runner 注释：页面刷新后不自动恢复，重新 run 才重新装载（`client-runner/src/client/index.ts:6-12`）。

### 15.2 Persistence Matrix

| Object | Memory | Disk/DB | Restore | Evidence |
|---|---|---|---|---|
| Plugin | 是（`registry.plugins` Map） | 否 | 无 | `registry.ts:141-151`；`index.ts:1247-1249` |
| Package（Definition + 源码） | 是（`plugin.packages` Map） | 否 | 无 | `registry.ts:55` |
| Version 指针（current/next） | 是（Plugin 字段） | 否 | 无 | `registry.ts:65-66` |
| Run | 是（`plugin.run`） | 否 | 无 | `registry.ts:63` |
| RunAttempt | 是（`plugin.latestRun`） | 否 | 无 | `registry.ts:64` |
| 审批请求 | 是（`pendingRequests` Map） | 否 | 无 | `registry.ts:143` |

### 15.3 进程重启后

- Plugin：不在。`[FACT]`
- Package：不在。`[FACT]`
- Version：不在。`[FACT]`
- Run：不在。`[FACT]`
- Registry：不在。`[FACT]`

`[UNKNOWN]`：session log 是否记录 `cordis_define` 的元数据——该行为不在本 package 源码内（README 声称记录，但本轮未在源码中验证）。

---

## 16. Test Evidence

每个生命周期操作都有测试；以下只列与生命周期语义直接相关的证据。

### 16.1 Define

Test `runner.spec.ts:98` → Given 一个 setup 好的 runner → When 连续两次 define（host-only、client-only）→ Then 返回 `dyn-1/pkg-1`、`dyn-2/pkg-2`，`running()` 全 false（define 不运行）。

Test `runner.spec.ts:124` → Given `code.client='return { type: \'text\' as const }'` → When define → Then 抛 TypeScript 教学错误，registry 中无任何记录（失败不留状态）。

### 16.2 Run

Test `runner.spec.ts:150` → Given host-only Package → When `run(mode:'run')` → Then 返回 `{ok:true,status:'running',pluginRunId:'run-1'}`；`ctx.get('dynDoubler')` 有值；`invoke('double')` 返回 42；只广播 `cordis/dynamic-package`。

Test `runner.spec.ts:178` → Given client-bearing Package + 网关 approve → When `run` → Then 先返回 `awaiting-approval`；页面回答后 `latestRun.status='waiting'`（client waitingFor slots），广播顺序 `request-run → dynamic-package → request-run-resolved(approved)`。

Test `runner.spec.ts:402` → Given host 半抛错 → When run → Then `host-half-failed`，无广播，`invoke` 返回 `plugin-not-running`（失败不残留运行）。

### 16.3 Version / Update / Rollback

Test `versioning.spec.ts:7` → Given current=A，define B，run(B, 'update') 失败 → Then `currentPackageId=A, nextPackageId=B, activeRun=undefined`；再 `run(A, 'run')`（rollback）→ Then `currentPackageId=A, activeRun={A}`, `nextPackageId=undefined`。

### 16.4 Stop

Test `runner.spec.ts:422` → Given running host+client Package → When stop → Then `ctx.get('dynDoubler')` 消失，`invoke` 报 `plugin-not-running`，广播 `dynamic-retract`；再次 run 得 `run-2`（定义保留、可再运行）。

Test `runner.spec.ts:463` → Given 从未运行的 Plugin → When stop → Then `{ok:false,reason:'not-running'}`。

### 16.5 Undefine

Test `runner.spec.ts:472` → Given 运行中的 Plugin → When undefine → Then `{ok:true,wasRunning:true}`，服务消失，`run` 返回 `plugin-missing`。

Test `runner.spec.ts:489` → Given 不存在的 ID → When undefine → Then `plugin-missing`，消息含 “lost on DSH restart”（内存唯一性证据）。

### 16.6 并发 / attach

Test `runner.spec.ts:270` → Given 已运行 host 半 → When 再次 `runHostHalf` → Then `startedHere:false`，同一 `pluginRunId`（不重复求值）。

Test `runner.spec.ts:289` → Given 两个并发 `runHostHalf` → Then 两个结果相同（`starting` Map 去重）。

Test `runner.spec.ts:328` → Given 页面正在加载 run-1 时 stop → Then 该请求被 cancel；`resolveRequestRun` 返回 `accepted:false`；新 `runHostHalf` 得 `run-2`。

Test `versioning.spec.ts:75` → Given run-1 已 active，第二页 attach 后 client 加载失败 → Then 已有 run-1 不被 stop（`startedHere` 决定 unwind 权）。

### 16.7 Tool / Service 生命周期

Test `composition.spec.ts:59` → Given consumer 依赖 provider → When stop provider → Then consumer 回 PENDING、注册卸载；再 run provider → consumer 通过新 guard 重新激活。

Test `composition.spec.ts:160` → Given 动态工具已注册 → When stop → Then 工具消失；下次 run 重新注册。

### 16.8 Sandbox

Test `sandbox.spec.ts:45` → Given sandbox 内代码写 `globalThis` → When run → Then host 侧看不到写入；`process`/`Buffer` 为 undefined。

Test `sandbox.spec.ts:138` → Given `vmTimeoutMs` 很小 + 同步死循环 → When run → Then 求值被超时中止。

### 16.9 Client 半

Test `runner.client.spec.ts:302` → Given 页面已 load run-1 → When retract(run-1) → Then 卸载；`retract(run-2)`（旧版本）被忽略。

Test `runner.client.spec.ts:344` → Given 多个 live package → When runner dispose → Then 全部卸载。

---

## 17. Lifecycle State Machines

### 17.1 Run / Attempt 状态（源码枚举）

`CordisRunStatus`（`types.ts:105-114`）：

```
awaiting-approval
  → starting-host
    → client-pending
      → running | waiting
  → rejected | failed | cancelled | stopped
```

`CordisHalfState.status`（`types.ts:117-124`）：`absent | pending | stopped | running | waiting | failed`。

实际转移点：

| 转移 | 代码 |
|---|---|
| `awaiting-approval`（client 包需审批） | `index.ts:291-294` |
| `starting-host` | `createAttempt`（`index.ts:1174-1189`）/ `runHostHalf` |
| `client-pending`（host 半已启动） | `index.ts:919-925` |
| `running` / `waiting`（完整成功） | `commitActivation`（`index.ts:985-992`） |
| `rejected` | `settleActivation`（`index.ts:930-946`） |
| `failed` | `failAttempt`（`index.ts:1191-1201`）、`reportRenderFailure`（`index.ts:688-712`） |
| `cancelled` | `cancelPending`（`index.ts:1159-1170`） |
| `stopped` | `stop`（`index.ts:469-474`） |

### 17.2 Plugin 级生命周期

`[NOT_FOUND]`：registry 中没有 Plugin 级状态枚举。模型侧展示状态由 `selfState()` 从 `latestRun.status`/`activeRun`/`currentPackageId` 推导（`tool-cordis/src/index.ts:439-465`）：`defined | awaiting-approval | client-pending | stopped | running | waiting | failed`。该枚举是工具层推导，不是 registry 持久状态 `[FACT]`。

```
Defined（current=undefined）
  → Running（首次成功）
  → Stopped（stop，current 保留）
  → Running（再次 run）
  → Failed/Rejected/Cancelled（latestRun 记录，可重试）
  → Undefined（undefine）
```

### 17.3 Cordis Fiber 状态（vendored 底层）

`FiberState`（`vendor/cordis/src/fiber.ts:147-158`）：`PENDING → LOADING → ACTIVE`，失败 `FAILED`，卸载 `UNLOADING → DISPOSED`。`fiber.await()` 等待 inertia 并重抛启动错误（`fiber.ts:704-714`）；`dispose()` 由父 fiber effect 注册，逆序执行 disposers（`fiber.ts:265-311,415-560`）。

---

## 18. Four-Layer Object Model

### Layer 1 — Definition（“我是什么”）

| 项 | 值 |
|---|---|
| 对象 | `DynamicCordisDefinition`（`registry.ts:37`） |
| Identity | `packageId` |
| State | 无状态（不可变源码包） |
| Owner | `DynamicCordisPlugin.packages` |
| Persistence | 进程内存 |
| Lifecycle | define 创建；undefine/重启销毁 |
| Cleanup | 无独立 cleanup（随 Plugin 删除） |

### Layer 2 — Package / Version（“我是哪一个版本”）

| 项 | 值 |
|---|---|
| 对象 | 同一个 `DynamicCordisDefinition` + Plugin 指针 `currentPackageId`/`nextPackageId` |
| Identity | `packageId` |
| State | `defined → next → current`；无独立枚举，指针表达 |
| Owner | `DynamicCordisPlugin` |
| Persistence | 进程内存 |
| Lifecycle | define 入 Map；成功激活变 current；失败停在下一位；undefine 删除 |
| Cleanup | `commitActivation` 删 next；undefine 全删 |

### Layer 3 — Runtime Instance（“我现在正在运行什么”）

| 项 | 值 |
|---|---|
| 对象 | `DynamicCordisRun`（`registry.ts:17`） |
| Identity | `pluginRunId` |
| State | 通过 `plugin.latestRun.status` 观察；自身无状态枚举 |
| Owner | `DynamicCordisPlugin.run`（单值） |
| Persistence | 进程内存，仅 activation 期间 |
| Lifecycle | startFresh 创建；retract 删除 |
| Cleanup | `retract()`：handlerDisposers + `fiber.dispose()` + retract 事件 |

### Layer 4 — Run Attempt / Execution（“这一次具体执行是什么”）

| 项 | 值 |
|---|---|
| 对象 | `DynamicCordisRunAttempt`（`types.ts:143`） |
| Identity | `pluginRunId`（与 Run 相同） |
| State | `CordisRunStatus` + `CordisHalfState`（host/client） |
| Owner | `DynamicCordisPlugin.latestRun` |
| Persistence | 进程内存，run 结束后保留 |
| Lifecycle | 激活开始时创建；下次激活替换；stop 后保留为 stopped |
| Cleanup | 无独立 cleanup；随 Plugin 删除 |

---

## 19. 核心问题回答

> Dynamic Cordis Plugin 的源码，是否已经提供了一个“可被 Capability Forge 借鉴的最小 Runtime Object Model”？

基于源码逐项回答：

| 维度 | 状态 | 证据摘要 |
|---|---|---|
| 1. Definition | **已提供** | `DynamicCordisDefinition`（源码字符串 + name/purpose + packageId） |
| 2. Identity | **已提供** | 稳定 `pluginId`；每次激活 `pluginRunId`；版本 `packageId` |
| 3. Version | **已提供（最小形态）** | 不可变 package Map + `currentPackageId`/`nextPackageId`；无版本号、无 hash |
| 4. Registry | **已提供（进程内）** | `DynamicCordisRegistry`：Map + pending approvals + ID 铸造 |
| 5. Runtime Instance | **已提供** | `DynamicCordisRun` 持有 Fiber/handlers |
| 6. Execution Attempt | **已提供** | `DynamicCordisRunAttempt` + `CordisRunStatus`/诊断，运行后保留 |
| 7. Tool Exposure | **已提供** | `harness.defineTool/registerTool`；per-run 生命周期 |
| 8. Stop | **已提供** | `stop(pluginId)`：retract fiber/handlers，保留定义与版本 |
| 9. Rollback | **部分提供** | 无独立 API；以 `run(current,'run')` 实现；成功清除 next，失败保留指针 |
| 10. Undefine | **已提供** | `undefine(pluginId)`：cancel pending + retract + delete 全部版本 |
| 11. Persistence | **不存在** | 进程内存 only；无 disk/DB/restore |
| 12. Recovery | **不存在（有指针级回退锚点）** | `currentPackageId` 保留 + 诊断 + 模型重试；无自动恢复 |

结论：**是，但只是“最小”**——已覆盖 Definition/Identity/Version/Registry/Run/Attempt/Tool/Stop/Undefine 的对象骨架与状态转移；Persistence、自动 Recovery、独立 Rollback verb、并发多 Run 不在其中。

---

## 20. Final Runtime Object Model

```
DynamicCordisRegistry（进程内，唯一真源）
  └── DynamicCordisPlugin（pluginId, sessionId）
        ├── packages: Map<packageId, DynamicCordisDefinition>   ← 不可变版本
        ├── approvedClientPackages / clientVersionUpdatesApproved
        ├── currentPackageId / nextPackageId                    ← 版本指针
        ├── run?: DynamicCordisRun                              ← 当前激活
        │     ├── packageId
        │     ├── fiber?: Fiber（vendor/cordis，效果/清理树）
        │     ├── handlers: Map<string, DynamicCordisHandler>
        │     └── handlerDisposers / reportedRuntimeErrors / renderFailure
        └── latestRun?: DynamicCordisRunAttempt                 ← 最近尝试（跨运行保留）
              ├── status: CordisRunStatus
              ├── host/client: CordisHalfState
              └── error?: CordisRunDiagnostic

Host 半执行：
  createSandbox() → evaluateHostCode() → guardedPlugin() → group.ctx.plugin() → Fiber
  apply(ctx) 期间：
    harness.handle → run.handlers
    harness.registerTool → ctx.tools（fiber effect）

Client 半执行（页面）：
  getClientCode() → evaluateClientHalf() → loader entry → Fiber
  retract 事件 → teardown

广播：
  cordis/request-run / request-run-resolved
  cordis/dynamic-package / dynamic-retract
```

## Runtime Primitives Confirmed

以下 primitive 全部有源码证明：

- Dynamic Definition（源码字符串 Package：`registry.ts:37`）
- Stable Plugin Identity（`pluginId`：`registry.ts:51`、`types.ts:10`）
- Versioned Package（不可变 `packageId` Map：`registry.ts:37,55`）
- Version Pointers（`currentPackageId`/`nextPackageId`：`registry.ts:65-66`）
- Process Registry（`DynamicCordisRegistry`：`registry.ts:141`）
- Runtime Run（`DynamicCordisRun`：`registry.ts:17`）
- Run Attempt（`DynamicCordisRunAttempt`：`types.ts:143`）
- Fiber（`vendor/cordis/src/fiber.ts:184`）
- Host VM Sandbox（`sandbox.ts:129`，明确非安全边界）
- Client Closure Sandbox（`evaluator.ts:129`）
- Tool Registration（`guard.ts:551,626`）
- Handler Registration / Invoke（`guard.ts:604`、`index.ts:746`）
- Service Provide/Inject（`guard.ts:648`、`composition.spec.ts:29-141`）
- Stop（`index.ts:456`）
- Undefine（`index.ts:210`）
- Version Update（`mode:'update'`：`index.ts:254,768-808`）
- Rollback-as-run（`run(current,'run')`：`versioning.spec.ts:7`、`CordisPanel.tsx:391`）
- Approval Flow（`index.ts:277-329`、`registry.ts:233-268`）
- Failure Diagnostics（`CordisRunDiagnostic`：`types.ts:127`）
- Event Announcements（`cordis/dynamic-package`/`dynamic-retract`：`types.ts:379-390`）

以下 primitive 源码未能证明，不计入：

- 持久化 / restore / snapshot-to-disk
- 独立 rollback verb
- 自动 recovery / 自动重启旧版本
- 每 Plugin 多 Run 并发（Host 侧单 active run）
- Sandbox 安全隔离（源码自称非 containment）
- define 级 permissions / dependencies / hash / metadata
- 运行轮询超时（仅有 `vmTimeoutMs` 同步求值上限）
