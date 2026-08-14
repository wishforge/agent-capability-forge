# DeepSeek Harness Capability 源码考古报告

研究范围：仅 `deepseek-harness/` 当前 checkout 的源码、测试与随仓库发布的组合配置。

证据等级：

- `[FACT]`：源码/测试直接证明。
- `[INFERENCE]`：由多个源码 FACT 推导。
- `[HYPOTHESIS]`：合理推测，无源码证明。
- `[UNKNOWN]`：源码无法证明。
- `[NOT_FOUND]`：明确搜索但没有找到对应实现。

路径均相对于仓库根 `deepseek-harness/`。行号来自当前 commit。

---

## 1. Repository Baseline

| 项 | 值 |
|---|---|
| commit | `47f943859bef60e4160492346772ded9b24f765a` |
| branch | `master` |
| dirty/clean | clean（`git status --short --branch` 无输出） |
| 语言/框架 | TypeScript pnpm monorepo；运行时基于 vendored Cordis（`vendor/cordis`） |
| 测试 | Vitest unit/integration/e2e，分布在 `packages/*/tests`、`apps/*/tests`、`examples/*/tests` |

## 2. Directory Map

只列与本轮研究相关的目录。

| 目录 | 角色 |
|---|---|
| `packages/skill/skill` | Skill Service Definition：`SkillProvider` / `SkillRegistry` / Candidate / Definition / Validation |
| `packages/skill/skill-filesystem` | 本地 Markdown Skill Provider：frontmatter 解析、根目录发现、watcher、`fs/observed` 失效 |
| `packages/skill/tool-skill` | Model-facing `skill` 工具、会话 skill catalog、用户 `/name` 注入 |
| `packages/skill/skill-badge` | 静态 bundled Skill Provider 示例 |
| `packages/core/scope` | ScopeKey、createScope、bindScopeParent、ScopedLayers/NamedEntries |
| `packages/core/tools` | Tool Runtime：按 scope 分层的工具注册、可见性解析、执行管线 |
| `packages/core/agent-loop` | Agent 创建时 `createScope(loopCtx, this)` |
| `packages/preset/agent-presets` | Preset 发现、standing mount、`mountPreset`、agent scope 与 preset scope 绑定 |
| `packages/extensions/cordis-host-runner` | 动态 Cordis Plugin：define/run/stop/undefine、注册表、VM sandbox、guard |
| `packages/extensions/tool-cordis` | Model-facing `cordis_define` / `cordis_run` / `cordis_stop` / `cordis_undefine` 等工具 |
| `packages/extensions/cordis-client-runner` | 动态 Plugin 浏览器半边的加载/卸载 |
| `vendor/cordis` | Service / Context / Fiber / effect / reflect.provide 底层 |
| `packages/host/plugin-inventory` | Loader 条目只读投影（不是 capability 注册表） |

---

## 3. Capability Data Model

结论先行：**DeepSeek Harness 中不存在一个统一的 “Capability” 对象。** 本轮找到两个并行模型：

1. **Skill**：artifact 驱动的指令能力（Markdown + frontmatter → Candidate → Definition）。
2. **Dynamic Cordis Plugin**：代码驱动的可运行能力（模型写的 JS 字符串 → Package → Plugin → Run/Fiber）。

二者共享底层 Cordis `Service` / `Fiber` / `effect` 机制，但数据模型和注册表完全不同。

### 3.1 Skill 数据模型

全部是 TypeScript interface + plain object，不是 class：

- `SkillSummary`：`name`、`description`、`whenToUse?`、`invocation`、`source`、`provider`、`resourceBase?`（`packages/skill/skill/src/index.ts:56-71`）。
- `SkillCandidate extends SkillSummary`：加 `rank`、`locator`（opaque provider 句柄）、`path?`、`metadata?`（`packages/skill/skill/src/index.ts:74-83`）。
- `SkillDefinition extends SkillSummary`：加 `content`、`path?`、`metadata?`（`packages/skill/skill/src/index.ts:86-93`）。
- `SkillRegistration`：`ctx.skills.register()` 的输入，省略 `invocation`/`provider` 时有默认值（`packages/skill/skill/src/index.ts:96-101`）。
- `SkillProvider`：`{ name, list(), get() }`（`packages/skill/skill/src/index.ts:248-268`）。
- `SkillRegistry extends Service`：注册表本体（`packages/skill/skill/src/index.ts:357-661`）。

最小数据结构的回答：

| 问题 | 答案 | 证据 |
|---|---|---|
| 最小数据结构 | `SkillCandidate`（发现期）/ `SkillDefinition`（加载期） | `packages/skill/skill/src/index.ts:74-93` |
| class/interface/dict | TS interface + plain object；注册表是 class | 同上 |
| 谁创建 Candidate | Provider `list()` 返回；filesystem provider 从文件 parse | `packages/skill/skill/src/index.ts:260`；`packages/skill/skill-filesystem/src/index.ts:719-747` |
| 谁创建 Definition | Provider `get(candidate)` 返回；filesystem provider 再读文件 | `packages/skill/skill/src/index.ts:267`；`packages/skill/skill-filesystem/src/index.ts:206-222` |
| 谁持有 | `SkillLayer.providers`（NamedEntries）与 `SkillLayer.runtime`（Map） | `packages/skill/skill/src/index.ts:328-344` |
| name | 有；kebab-case grammar `/^[a-z0-9]+(?:-[a-z0-9]+)*$/` | `packages/skill/skill/src/index.ts:20` |
| identity | `name` 是唯一地址；provider 名在同一 layer 内唯一 | `packages/skill/skill/src/index.ts:391-429` |
| version | **NOT_FOUND**：Skill 没有 version 字段；只有不可比较的 `rank` | `packages/skill/skill/src/index.ts:74-101` |
| dependency | **NOT_FOUND**：Skill 自身无依赖声明；Provider 可借用 `SkillProviderControl.signal/invalidate` | `packages/skill/skill/src/index.ts:271-276` |
| metadata | 有可选 `metadata`（frontmatter `metadata:` 解析而来） | `packages/skill/skill/src/index.ts:82,92`；`packages/skill/skill-filesystem/src/index.ts:1031-1037` |
| permission | `invocation.modelInvocable/userInvocable`；来源 `source`；无 per-skill ACL | `packages/skill/skill/src/index.ts:48-53,38-39` |
| scope | 注册时由调用 context 的 `scopeOf` 决定 layer；读取时由 `scope` chain 决定可见性 | `packages/core/scope/src/index.ts:154-156`；`packages/skill/skill/src/index.ts:346-356` |
| runtime state | **NOT_FOUND**：Skill 无运行中状态；只有注册/未注册 | `packages/skill/skill/src/index.ts:328-344` |

结论：**Skill 是多个层次同时存在**：Provider 是来源，Candidate 是发现期元数据+locator，Definition 是加载后的完整指令体，Registry entry 是注册表内状态。不是同一个对象。

### 3.2 Dynamic Cordis Plugin 数据模型

- `DynamicCordisDefinition`（Package）：`packageId`、`name`、`purpose`、`hostCode?`、`clientCode?`（`packages/extensions/cordis-host-runner/src/registry.ts:37-48`）。
- `DynamicCordisPlugin`：`pluginId`、`sessionId`、`packages`（Map）、`approvedClientPackages`、`currentPackageId?`、`nextPackageId?`、`run?`、`latestRun?`（`packages/extensions/cordis-host-runner/src/registry.ts:51-70`）。
- `DynamicCordisRun`：`pluginRunId`、`packageId`、`fiber?`、`handlers`、`handlerDisposers`（`packages/extensions/cordis-host-runner/src/registry.ts:17-34`）。
- `DynamicCordisRunAttempt`：显式状态机 `CordisRunStatus`（`packages/extensions/cordis-host-runner/src/types.ts:105-114,143-162`）。
- 三个 branded identity：`CordisDynamicPluginId` / `CordisDynamicPackageId` / `CordisDynamicPluginRunId`（`packages/extensions/cordis-host-runner/src/types.ts:10-16`）。

与 Skill 的关键差异：**这里有真正的版本、运行态、批准态和卸载语义**。

---

## 4. Provider / Registry 深挖

### 4.1 SkillProvider 如何创建与注册

调用链：

```
plugin apply()
  -> ctx.skills.registerProvider(create)
  -> create(control) 同步返回 SkillProvider
  -> layers.effect(ctx, layer => layer.providers.insert(name, {provider, order}))
  -> 返回 Cordis effect disposer
```

源码：

- `SkillRegistry.registerProvider()`：`packages/skill/skill/src/index.ts:391-429`
- `NamedEntries.insert()`：`packages/core/scope/src/store.ts:43-54`
- `ScopedLayers.effect()`：`packages/core/scope/src/store.ts:226-266`
- filesystem provider 注册：`packages/skill/skill-filesystem/src/index.ts:130-143`
- badge provider 注册：`packages/skill/skill-badge/src/index.ts:58-59`

规则：

- Provider 名在同一 layer 内唯一，重名抛错；`"runtime"` 是保留名（`packages/skill/skill/src/index.ts:406-408`）。
- `registerProvider` 是同步的；远程初始化/鉴权放在 `list()` 里（`packages/skill/skill/src/index.ts:386-390`）。
- 注册时分配 service-wide 单调递增 `nextProviderOrder`（`packages/skill/skill/src/index.ts:369,410-411`）。

### 4.2 Registry 保存什么

`SkillRegistry` 保存：

- `ScopedLayers<SkillLayer>`：`global` + per-scope `SkillLayer`（`packages/skill/skill/src/index.ts:363-366`）。
- 每个 `SkillLayer` 两张表：`providers: NamedEntries<RegisteredProvider>` 和 `runtime: Map<string, SkillDefinition>`（`packages/skill/skill/src/index.ts:328-344`）。
- `collectCache`：按 `(cwd, scope chain, revision)` 缓存已合并的 winner map（`packages/skill/skill/src/index.ts:367,644-646`）。
- `revision`：每次注册/注销/失效递增（`packages/skill/skill/src/index.ts:368,622-626`）。

### 4.3 Registry 的 scope 语义

- 注册：`scopeOf(ctx)` 决定进入 global layer 还是某个 scope layer（`packages/core/scope/src/store.ts:231-247`）。
- 读取：`collectFresh()` 合并 `[global, ...chainLayers(scope)]`（`packages/skill/skill/src/index.ts:552-566`）。
- Registry 是 **process 内唯一 host service**；Agent scope 不是独立 registry，而是 registry 中的一个 layer。测试证据：`packages/skill/skill/tests/skill.spec.ts:1108-1139`。

### 4.4 register 返回值与 disposer 语义

- `registerProvider` 返回 `ScopedLayers.effect()` 返回的精确 disposer（`packages/skill/skill/src/index.ts:412-424`）。
- `register` 返回同样的 effect disposer；同 layer 同名 runtime skill 是 first-wins，重复注册 log warning 并返回 no-op disposer，因此不能删除 winner（`packages/skill/skill/src/index.ts:440-460`）。
- Disposer 做的事：
  1. `NamedEntries` 删除该 provider/runtime entry；
  2. 若 layer 变空则从 `scoped` Map 删除；
  3. `invalidateCache()`（revision++、清 collectCache、emit `skills/change`）；
  4. provider 的 `control.signal` abort（`packages/skill/skill/src/index.ts:417-421`；`packages/core/scope/src/store.ts:257-262`）。
- Disposer **不是** install/mount/activate；它只撤销注册表 entry。**已在进行中的 `provider.list()` / `provider.get()` 不会被 disposer 取消**（registry 没有 in-flight execution 表；只有 `options.signal` 由调用方控制）。这是 `[FACT]`：`registerProvider` disposer 只调用 `undo()` 与 `lifecycle.abort`，没有等待或取消 provider 调用（`packages/skill/skill/src/index.ts:417-421`）。
- Disposer 幂等：Cordis `effect` 的 disposer 单次执行，再次调用返回同一 disposal task（`vendor/cordis/src/fiber.ts:427-442`）。

### 4.5 Service 注册底层

`SkillRegistry extends Service`，构造函数 `super(ctx, 'skills')` 调用 `ctx.reflect.provide(name, self, check)`（`vendor/cordis/src/service.ts:42-58`）。`ctx.reflect.provide` 把实现记录到 fiber 所有，返回 disposer（`vendor/cordis/src/reflect.ts:277-305`）。

---

## 5. Validation 深挖

存在**多个 validation boundary**，职责不同，不能归纳为“双重校验”。

### Boundary 1：Artifact 解析（filesystem provider）

- `parseFrontmatter()`：只接受首行 `---`，YAML 必须是 object，找不到 closing `---` 则忽略（`packages/skill/skill-filesystem/src/index.ts:909-935`）。
- `parseSkillFile()`：要求 `name`、`description` 非空，`name` 必须通过 `isSkillName`，`invocation` 必须可解析；失败只 log warning 并跳过该文件，不影响兄弟文件（`packages/skill/skill-filesystem/src/index.ts:793-835`）。
- `parseInvocationPolicy()`：接受 `disable-model-invocation` / `user-invocable` 的多种 boolean 拼写；legacy key（`disableModelInvocation`、`modelInvocable`、`userInvocable`）直接拒绝（`packages/skill/skill-filesystem/src/index.ts:992-1002`）。
- 测试：`packages/skill/skill-filesystem/tests/skill-filesystem.spec.ts:236-364`。

### Boundary 2：Provider 输出校验（registry）

`validateCandidate()` 在每个 provider `list()` 的每个 candidate 上执行（`packages/skill/skill/src/index.ts:613-617,708-740`）：

- `name` 必须是 string 且匹配 kebab-case；
- `description` 非空 string；
- `invocation` 形状（两个 boolean）；
- `whenToUse`、`source`、`rank`、`provider`、`path` 类型；
- `candidate.provider` 必须等于 provider 自己的 name。

失败时该 provider 的整个 `list()` 调用抛错，registry 捕获后 log warning、`cacheable=false`，**跳过该 provider 但保留其他 provider 的结果**（`packages/skill/skill/src/index.ts:600-619`）。测试：`packages/skill/skill/tests/skill.spec.ts:191-270`。

### Boundary 3：加载 Definition 校验

`validateDefinition()` 在 `provider.get()` 返回值上执行，额外要求 `content` 是 string（`packages/skill/skill/src/index.ts:501-517,749-768`）。若返回的 `definition.name` 与 winner candidate 不同，registry 使该 entry 失效并返回 `undefined`（`packages/skill/skill/src/index.ts:513-516`）。测试：`packages/skill/skill/tests/skill.spec.ts:499-559`。

### Boundary 4：Consumer 边界（tool-skill）

- catalog 只发布 `isModelInvocable` 的 skill（`packages/skill/tool-skill/src/index.ts:226`）。
- `skill` 工具在 load 前和 load 后各检查一次 `isModelInvocable`（`packages/skill/tool-skill/src/index.ts:138-147`）。
- 用户 `/name` 注入只扫描 `source.kind === 'user'` 的消息，且只注入 `isUserInvocable` 的已加载 Definition（`packages/skill/tool-skill/src/index.ts:177-204`）。
- 测试：`packages/skill/tool-skill/tests/tool-skill.spec.ts:861-886,888-960`。

### Boundary 5：Dynamic Plugin guard（cordis-host-runner）

这是与 Skill 完全不同的验证栈：

- `define` 时 `precheckCode()` 只编译不执行（`packages/extensions/cordis-host-runner/src/sandbox.ts:206-214`）；run 时才 `evaluateHostCode()`（`packages/extensions/cordis-host-runner/src/sandbox.ts:227-238`）。
- `sandboxDefineTool()` 做跨 realm JSON clone、schema 白名单、参数 DSL 归一化，并打 dynamic marker（`packages/extensions/cordis-host-runner/src/guard.ts:551-592`）。
- `guardedPlugin()` 把真实 ctx 换成 whitelist façade：只允许 `effect/on/once/provide/timeout/...`，只允许 `ctx.get()` 与已声明 `inject` 的 service 属性访问，拒绝任何 service 返回 Context（`packages/extensions/cordis-host-runner/src/guard.ts:636-781,802-819`）。
- `harness.registerTool()` 只接受 marker 验证过的动态 tool（`packages/extensions/cordis-host-runner/src/guard.ts:626-629`）。
- 测试：`packages/extensions/cordis-host-runner/tests/runner.spec.ts:124-134`。

Validation 是否修改 artifact：**否**。所有 validation 只产生内存中的 normalized 对象（`ParsedSkill`、`SkillDefinition`、`ToolDefinition`）；文件本身不被改写。

Validation 是否检查权限/依赖/runtime 兼容：

- Skill：检查 invocation policy，不检查依赖；`candidate.provider === providerName` 是归属检查（`packages/skill/skill/src/index.ts:731-736`）。
- Dynamic plugin：检查 `inject` 声明是否被白名单接受，不检查 service 当前是否真的存在（存在时 fiber 会 `waiting`）；无“runtime compatibility”检查（`packages/extensions/cordis-host-runner/src/lifecycle.ts:47-57`）。

---

## 6. Scope / Layer / Rank / Winner

### 6.1 Scope 如何创建与继承

- `createScope(ctx, key, {parent})` 创建带 `kScope` 标记的 context，parent 通过 `bindScopeParent` 绑定（`packages/core/scope/src/index.ts:137-147,72-82`）。
- Agent 自身是 scope key：`ReactLoopAgent` 构造时 `this.scope = createScope(loopCtx, this)`（`packages/core/agent-loop/src/agent.ts:94`）。
- Preset standing scope 由 `AgentPresets.ensureStanding()` 创建，agent 的 scope key 通过 `bindScopeParent(agentKey, standing.key)` 挂到 preset key 下（`packages/preset/agent-presets/src/index.ts:513-524,275-288`）。
- `scopeChainOf(key)` 返回 `[key, parent, grandparent, ...]`（`packages/core/scope/src/index.ts:98-102`）。

### 6.2 Skill Layer / Rank 语义

- 每个 scope 一个 `SkillLayer`；global layer 恒存在（`packages/core/scope/src/store.ts:159-170`）。
- layer 内排序：`compareIndexedCandidates` = `rank` 升序 → `providerOrder` 升序 → `localOrder` 升序（`packages/skill/skill/src/index.ts:807-811`）。
- 跨 layer：`collectFresh()` 按 global → farthest ancestor → nearest 顺序 `merged.set(name, entry)`，**nearest layer 的同名 entry 直接覆盖，不看 rank**（`packages/skill/skill/src/index.ts:552-566`）。
- filesystem provider 的 root rank：project-dsh=100、project-agents=200、custom=300、user-dsh=400、user-agents=500、bundled=600；runtime skill rank=250（`packages/skill/skill-filesystem/src/index.ts:36-40`；`packages/skill/skill/src/index.ts:24`）。

### 6.3 真实例子

设：

- Provider A（global）：`name=shared-name`, rank=10。
- Provider B（preset layer）：`name=shared-name`, rank=900。
- Agent scope 挂在 preset scope 下。

结果：

- Agent 视图：**B 赢**，因为 nearest layer 直接覆盖，rank 不参与跨 layer 比较（`packages/skill/skill/tests/skill.spec.ts:1141-1170`）。
- 无 scope 的 global 视图：**A 赢**。
- 若 A、B 在同一 layer：A（rank 10）赢 B（rank 900）；同 rank 时先注册的 provider（providerOrder 小）赢；同 provider 内 localOrder 决定。

同 layer 内 shadowed provider 仍留在注册表里，只是 collect 时被 `seen` 集合过滤并 log warning（`packages/skill/skill/src/index.ts:571-582`）。winner 被 dispose 后，下一次 collect 会看到 shadowed entry——这是 `[FACT]`：collect 每次从 live layer 重建，过滤发生在 collect 结果上，不是注册表删除。

跨 layer shadow 也可恢复：preset layer 被 dispose 后，global entry 重新可见（`packages/skill/skill/tests/skill.spec.ts:1212-1233`）。

### 6.4 Agent 最终看到什么

Skill 的 agent-visible 对象是 **`SkillSummary`（catalog 行）+ 按需加载的 `SkillDefinition`**，不是 provider，也不是 SkillLayer。`tool-skill` 的 pre-step listener 用 `scope: agent` 调 `ctx.skills.snapshot()`（`packages/skill/tool-skill/src/index.ts:213-251`）。

Tool 层同理：`ToolRuntime.view(scope)` 合并 global + scope chain，nearest layer 的 `ToolDefinition` 覆盖远处，`tools.schemas(scope)` 喂给 system prompt（`packages/core/tools/src/index.ts:1152-1193,832`）。

---

## 7. Mount 深挖

**`SkillRegistry` 没有 `mount` 方法。** 源码里“mount”出现在两个地方，语义都不同于“注册”。

### 7.1 Preset Mount（agent 能力组合）

- `mountPreset(agentCtx, preset)`：在 agent scope context 下 `agentCtx.plugin(PresetTree, config)`，加载整个 composition 子树，检查每个 row 可用，检查没有 service 泄漏到 root realm，然后记录 `PresetMount`（`packages/preset/agent-presets/src/mount.ts:332-381`）。
- 子树里的 `skill-filesystem`、`tool-skill` 等 row 的 `apply()` 通过继承 scope tag 的 context 执行，所以 `ctx.skills.registerProvider()` / `ctx.tools.register()` 全部落进 **preset layer**（`packages/preset/agent-presets/src/mount.ts:5-13`；`packages/core/scope/src/store.ts:231-247`）。
- 失败时 `handle.dispose()` 回滚整个子树（`packages/preset/agent-presets/src/mount.ts:369-379`）。
- standing mount 单飞，按 composition 文件 stamp 决定是否换代（`packages/preset/agent-presets/src/index.ts:491-534`）。

状态变化（mount 前 → 后）：

1. `SkillRegistry` 的 preset scope layer 增加 provider/runtime entries（如果 preset 挂 `skill-filesystem` / 有 runtime skill 行）。
2. `ToolRuntime` 的 preset layer 增加 tool definitions。
3. Agent scope key 的 parent 指向 preset key，agent 的读取链因此包含 preset layer。
4. 没有“Agent 对象”被修改；可见性由 scope chain 推导。

### 7.2 Dynamic Plugin Mount（run）

- `cordis_define` 只把 Package 放进 registry，**不执行**（`packages/extensions/cordis-host-runner/src/index.ts:151-202`）。
- `run` 才是 mount：`startFresh()` 先 retract 旧 run，然后 `startHostHalf()` 在 `cordis-dynamic` group fiber 下 `group.ctx.plugin(guardedPlugin(...))`（`packages/extensions/cordis-host-runner/src/index.ts:823-881`；`packages/extensions/cordis-host-runner/src/lifecycle.ts:22-45`）。
- mount 输出是 `DynamicCordisRun`（`fiber` + `handlers`），并 emit `cordis/dynamic-package`（`packages/extensions/cordis-host-runner/src/index.ts:844-862`）。
- Client half 由 `DynamicCordisPackageRunner` 在浏览器侧加载，作为 Client Loader entry（`packages/extensions/cordis-client-runner/src/client/runtime.ts:176-180`）。

结论：

- mount ≠ register：register 只改注册表；mount 创建 Fiber/subtree，并让 plugin 的 effects 生效。
- mount 会失败：preset mount 失败回滚；dynamic run 失败会 dispose 已启动的 host fiber（`packages/extensions/cordis-host-runner/src/lifecycle.ts:30-43`）。
- mount 不执行“Capability”本身；dynamic run 只执行 `apply`，业务动作仍由 model 后续调用工具/handler 触发。

---

## 8. Invocation / Execution

### 8.1 Skill 的 Agent 使用路径

1. **发现**：`tool-skill` 在 `agent/pre-step` 注入 `<available_skills>` catalog（`packages/skill/tool-skill/src/index.ts:213-251`）。
2. **Model 调用**：`skill` 工具 `execute` 用 `{ cwd, signal, scope: exec.agent }` 调 `ctx.skills.list()` → `ctx.skills.get()`（`packages/skill/tool-skill/src/index.ts:127-156`）。
3. **加载**：`SkillRegistry.get()` 选择 winner，把 candidate 的 opaque `locator` 传回 `provider.get()`（`packages/skill/skill/src/index.ts:501-518`）。
4. **观察**：`renderSkillContent()` 产出 `<skill_content>` 文本块作为 tool result（`packages/skill/skill/src/index.ts:171-184`；`packages/skill/tool-skill/src/index.ts:125`）。
5. **用户直接调用**：`/name` 手势只从 `source.kind === 'user'` 消息解析，注入渲染后的 `<skill_content>` 作为 instructions-form user message（`packages/skill/tool-skill/src/index.ts:177-204`）。

Skill invocation 没有 stdout/stderr、没有独立 process；它是**指令加载**，不是可执行程序。

### 8.2 Dynamic Plugin 的 Agent 使用路径

- 动态 plugin 通过 `harness.defineTool`/`harness.registerTool` 注册 model-facing tool（`packages/extensions/cordis-host-runner/src/guard.ts:551-629`）。
- 注册后的 tool 进入 `ToolRuntime`；model 下一轮可通过 `ctx.tools.execute` 调用，经过 pre-execute/approval/guards/post-execute 管线（`packages/core/tools/src/index.ts:1342-1362`）。
- `harness.handle` 注册 Host handler，Client 通过 `host.call` 经 `@Remote('invoke')` 调用（`packages/extensions/cordis-host-runner/src/index.ts:740-766`）。
- 错误：tool 错误返回 `isError`；handler 错误返回 `{ok:false, code:'handler-error'}` 并 steering 给 agent（`packages/extensions/cordis-host-runner/src/index.ts:755-765,1070-1093`）。
- 超时：`ToolDefinition.timeoutMs` 由可选的 `timeout-policy` guard 强制（`packages/guard/timeout-policy/src/index.ts:51-77`）；核心 `ToolRuntime` 本身只校验字段不执行超时（`packages/core/tools/src/index.ts:1046-1049`）。
- 取消：调用方 `AbortSignal` 贯穿 `ToolExecution`、`SkillLookupOptions.signal`、`DynamicCordisRunner.run`（`packages/core/tools/src/types.ts:337`；`packages/skill/skill/src/index.ts:819-842`；`packages/extensions/cordis-host-runner/src/index.ts:248-263`）。

---

## 9. Disposer / Unmount / Revoke

三种机制必须分开。

### 9.1 Effect Disposer（注册撤销）

- 范围：撤销一次 `registerProvider` / `register` / `tools.register` / `ctx.provide` 产生的注册表 entry。
- Skill 的 disposer 删除 entry、失效 cache、emit `skills/change`；不停止已开始的 provider 调用（`packages/skill/skill/src/index.ts:417-421`；`packages/core/scope/src/store.ts:257-262`）。
- Cordis effect disposer 是单次执行且可 await（`vendor/cordis/src/fiber.ts:427-560`）。

### 9.2 Stop（暂停，不删除）

- `DynamicCordisRunner.stop()`：取消 pending approval，`retract(plugin)` 删除 `plugin.run`、执行 handler disposers、`fiber.dispose()`、emit `cordis/dynamic-retract`；保留 packages/current/next（`packages/extensions/cordis-host-runner/src/index.ts:456-471,1219-1230`）。
- 测试证明 stop 后同一 Package 可重新 run，且得到新 `pluginRunId`（`packages/extensions/cordis-host-runner/tests/runner.spec.ts:421-444`）。

### 9.3 Undefine（删除）

- 先 stop（若在跑），再 `registry.delete(pluginId)`，删除所有 packages、approval、version 指针（`packages/extensions/cordis-host-runner/src/index.ts:210-218`）。
- 测试：`packages/extensions/cordis-host-runner/tests/runner.spec.ts:472-487`。

### 9.4 Rollback（失败恢复）

- 动态 update 失败时保留 `currentPackageId`、记录 `nextPackageId`，`activeRun` 被清掉；用 `mode:"run"` 可回滚到旧版（`packages/extensions/cordis-host-runner/src/index.ts:981-992`；`packages/extensions/cordis-host-runner/tests/versioning.spec.ts:7-39`）。
- 启动失败时 host fiber 已启动也会被 dispose（`packages/extensions/cordis-host-runner/src/lifecycle.ts:30-43`）。

### 9.5 明确区分

- Disposer = 撤销注册表 entry（幂等）。
- Stop = 卸载 active run，保留定义。
- Undefine = 删除定义与所有版本。
- Rollback = 失败后恢复 previous current。

它们不是同一个操作。Skill registry 没有 stop/rollback 概念。

---

## 10. Self-modification

核心问题：Agent 能否自己完成 生成 → 校验 → 注册 → mount → 使用 → 卸载？

| 环节 | 结论 | 证据 |
|---|---|---|
| A. Agent 可以生成 artifact？ | **[FACT]（mechanism）/ 无专门工具**。Model 可以用 `write`/`edit` 工具写 Markdown skill 文件（`packages/fs/tool-fs/src/write.ts:69-128`；`packages/fs/tool-fs/src/edit.ts:83-146`）；也可以用 `cordis_define` 提交 JS 源码字符串（`packages/extensions/tool-cordis/src/index.ts:149-238`）。没有名为 “create-skill” 的专用工具。 | |
| B. artifact 可以被 validation？ | **[FACT]**。Skill：frontmatter parse + `validateCandidate` + `validateDefinition`；Dynamic：`precheckCode` + guard。 | `packages/skill/skill-filesystem/src/index.ts:793-835`；`packages/skill/skill/src/index.ts:708-768`；`packages/extensions/cordis-host-runner/src/sandbox.ts:206-214` |
| C. artifact 可以被 registry？ | **[FACT]**。Skill：`registerProvider` 后 `list()` 的 candidate 进入 layer；Dynamic：`define` 把 Package 放入 `DynamicCordisRegistry`。 | `packages/skill/skill/src/index.ts:391-429`；`packages/extensions/cordis-host-runner/src/index.ts:151-202` |
| D. artifact 可以 mount？ | **[FACT]（语义不同）**。Skill 没有独立 mount；preset composition 挂 provider/tool 后 agent 可见。Dynamic：`cordis_run` → `startHostHalf` 创建 fiber。 | `packages/preset/agent-presets/src/mount.ts:332-381`；`packages/extensions/cordis-host-runner/src/index.ts:823-881` |
| E. mount 后可以被 agent 使用？ | **[FACT]**。Skill：catalog + `skill` tool；Dynamic：动态注册的 tool 进入 ToolRuntime。 | `packages/skill/tool-skill/src/index.ts:127-156`；`packages/extensions/cordis-host-runner/src/guard.ts:626-629` |
| F. agent 可以自行触发整个链路？ | **[FACT]（Dynamic Plugin）**。`cordis_define → cordis_run → cordis_stop/undefine` 是 agent 可调用的完整闭环，有测试。**Skill 链路无专门闭环**：agent 可用通用文件工具写 skill，provider 通过 watcher/`fs/observed` 发现（`packages/skill/skill-filesystem/src/index.ts:139-143,332-337`），但源码中没有 “agent 生成 skill → 自动注册 → 自动 mount” 的专用 API 或 e2e。 | `packages/extensions/tool-cordis/src/index.ts:148-379`；`packages/extensions/cordis-host-runner/tests/runner.spec.ts:150-176,421-487` |

结论：**源码证明 dynamic Cordis plugin 存在完整 self-generation → registration → mount → stop → undefine 链路；源码没有证明一个专门的 “Skill self-generation → registration → mount” 链路。** Skill 的机制（写文件 + watcher + catalog）使该链路在机械上可行，但只有机制测试，没有 agent 完整跑通的证据。

---

## 11. Persistence

| 项 | 结论 | 证据 |
|---|---|---|
| SkillRegistry 状态 | **memory-only**。`SkillLayer`、`collectCache` 都是内存对象；无 DB/文件读写。 | `packages/skill/skill/src/index.ts:363-372` |
| Skill artifact | **persistent**（用户自己维护的文件）。filesystem provider 每次 `list()` 重新读目录。 | `packages/skill/skill-filesystem/src/index.ts:182-198` |
| `ctx.skills.register()` 的 runtime skill | **memory-only**；重启消失。 | `packages/skill/skill/src/index.ts:440-461` |
| Dynamic plugin registry | **memory-only**。错误消息明说 “lost on DSH restart”。 | `packages/extensions/cordis-host-runner/src/index.ts:1248-1249`；测试 `packages/extensions/cordis-host-runner/tests/runner.spec.ts:489-495` |
| Scope / layer / mount state | **memory-only**。scope parent 是 WeakMap。 | `packages/core/scope/src/index.ts:39,98-102` |
| Preset 文件 | **persistent**；standing mount 是 process-local 缓存。 | `packages/preset/agent-presets/src/index.ts:537-555` |
| Skill catalog / tool calls | **persistent as session events**（`skill-catalog` 与 `skill-invocation` 都是 session message source）。 | `packages/skill/tool-skill/src/index.ts:34-41,271-276` |
| Skill/Plugin audit 表 | **NOT_FOUND**：没有 skill 注册或 plugin 定义的审计表。 | 搜索 `packages/session`、`packages/storage` 无命中 |

---

## 12. Lifecycle State Machine

### 12.1 Skill（隐式状态，无 enum）

源码中没有 `SkillState` 枚举。可证明的状态点：

```
文件存在（磁盘）
  → 被 provider.list() 发现并 parse（ParsedSkill）      [FACT]  skill-filesystem:793-835
  → Candidate 通过 validateCandidate                    [FACT]  skill:708-740
  → 进入 layer 的 collect 结果（winner）                [FACT]  skill:552-583
  → get() 时 provider 加载 Definition 并通过校验        [FACT]  skill:501-518
  → 注册表 entry 被 disposer 删除                      [FACT]  skill:417-421
```

`PROMOTED`、`ROLLED_BACK`、`REVOKED` 等状态在 Skill 源码中 **NOT_FOUND**。

### 12.2 Dynamic Plugin（显式状态）

`CordisRunStatus`：`awaiting-approval | starting-host | client-pending | running | waiting | rejected | failed | cancelled | stopped`（`packages/extensions/cordis-host-runner/src/types.ts:105-114`）。

生命周期（源码证明）：

```
defined（Package 入 registry，未运行）
  → run(): awaiting-approval / starting-host
  → activate(): client-pending
  → commitActivation(): running / waiting
  → stop(): stopped（定义保留）
  → undefine(): 删除
  → 失败路径: rejected / failed / cancelled
  → update 失败: current 保留，next 记录，可 rollback
```

`FiberState`：`PENDING | LOADING | ACTIVE | FAILED | UNLOADING | DISPOSED`（`vendor/cordis/src/fiber.ts:147-154`）。

---

## 13. 测试证据

### Skill Registry

- `packages/skill/skill/tests/skill.spec.ts:60-161`：provider 注册、rank/providerOrder winner、重复 provider 名、`runtime` 保留名、disposer 后可见性。
- `packages/skill/skill/tests/skill.spec.ts:467-497`：runtime registration 保真（resourceBase/metadata/provider 默认值）。
- `packages/skill/skill/tests/skill.spec.ts:499-559`：loaded Definition 每个标量字段的拒绝。
- `packages/skill/skill/tests/skill.spec.ts:625-705`：collect cache、失败 provider 跳过、incomplete observation 不缓存。
- `packages/skill/skill/tests/skill.spec.ts:707-765`：`control.invalidate` 只对精确注册有效；dispose 后 late callback 被忽略；`skills/change` 计数。
- `packages/skill/skill/tests/skill.spec.ts:1022-1043`：runtime duplicate first-wins。
- `packages/skill/skill/tests/skill.spec.ts:1108-1270`：scope layer 隔离、nearest layer 覆盖 rank、scope chain rebind、per-layer provider 唯一性、scope dispose 后可见性回退、scoped control 失效。

### Skill Filesystem

- `packages/skill/skill-filesystem/tests/skill-filesystem.spec.ts:170-206`：root 优先级与 bundled。
- `packages/skill/skill-filesystem/tests/skill-filesystem.spec.ts:208-234`：project > runtime > custom/user。
- `packages/skill/skill-filesystem/tests/skill-filesystem.spec.ts:236-364`：frontmatter parse/filter、boolean 拼写、legacy key 拒绝。
- `packages/skill/skill-filesystem/tests/skill-filesystem.spec.ts:667-702`：`fs/observed` 只接受 `write`/`edit` actor，且只接受潜在 skill 路径。
- `packages/skill/skill-filesystem/tests/skill-filesystem-watcher.spec.ts:120-360`：add/change/unlink/rename/recreate 都触发 catalog 更新。

### Tool-Skill

- `packages/skill/tool-skill/tests/tool-skill.spec.ts:159-185`：工具注册/卸载与 catalog 同步。
- `packages/skill/tool-skill/tests/tool-skill.spec.ts:643-678`：agent scope 解析 layered registry。
- `packages/skill/tool-skill/tests/tool-skill.spec.ts:709-746`：restrict 掉 `skill` 后 catalog 消失；scoped same-name tool 不继承 catalog。
- `packages/skill/tool-skill/tests/tool-skill.spec.ts:861-886`：unknown/invalid/model-disabled 都返回 isError。
- `packages/skill/tool-skill/tests/tool-skill.spec.ts:888+`：policy 在 load 前/后各检查一次。

### Dynamic Cordis

- `packages/extensions/cordis-host-runner/tests/runner.spec.ts:50-147`：define 只记录不运行、id 不复用、parse 失败不入 registry、session 归属。
- `packages/extensions/cordis-host-runner/tests/runner.spec.ts:150-176`：host-only package run 立即执行。
- `packages/extensions/cordis-host-runner/tests/runner.spec.ts:178-268`：client approval、拒绝、异步失败、host 回滚。
- `packages/extensions/cordis-host-runner/tests/runner.spec.ts:421-508`：stop 保留定义、undefine 删除、runner dispose 全部卸载。
- `packages/extensions/cordis-host-runner/tests/versioning.spec.ts:7-39`：update 失败保留 current、rollback 清 next。

### Preset / Agent 集成

- `apps/cli/tests/web-agent-presets.e2e.ts:261-285`：`cordis` preset 挂载动态工具集，`editing-cordis-compositions` 只出现在 agent scope。
- `apps/cli/tests/web-agent-presets.e2e.ts:342-385`：global skill layer + preset 本地 discovery 合并；`skill` 工具可加载 global-layer skill。
- `apps/cli/tests/web-agent-presets.e2e.ts:387-401`：minimal preset 能看到 global layer 但没有 `tool-skill`，证明“可见”和“可用”分离。

---

## 14. Call Graphs

### A. Registration

```
Skill artifact (SKILL.md / flat .md)
  -> FileSystemSkillProvider.list()                        skill-filesystem:182-198
  -> discoverRoot() -> parseSkillFile()                    skill-filesystem:719-835
  -> SkillCandidate[]                                      skill-filesystem:732-745
  -> SkillRegistry.collect()/collectFresh()                skill:520-566
  -> listLayerCandidates(): validateCandidate()            skill:585-620,708-740
  -> collectLayer(): rank/order 排序 + 去重               skill:568-583
  -> merged Map<name, IndexedCandidate>                    skill:557-565
  -> SkillLayer.providers / runtime                        skill:328-344
```

Dynamic 对应链：

```
model JS string
  -> cordis_define (tool)                                  tool-cordis:217-236
  -> DynamicCordisRunnerService.define(): precheckCode     cordis-host-runner:151-202
  -> DynamicCordisRegistry.add(plugin) / packages.set      registry:189-193
  -> DynamicCordisDefinition (Package)                     registry:37-48
```

### B. Mount

```
Agent create
  -> ReactLoopAgent: createScope(loopCtx, this)            agent-loop:94
  -> setup: agentPresets.mount(agentCtx, id)               agent-presets:275-288
  -> ensureStanding(): createScope(preset key)             agent-presets:491-534
  -> mountPreset(scope.ctx, preset)                        mount:332-381
  -> PresetTree: agentCtx.plugin(...)                      mount:350
  -> rows apply: skill-filesystem/tool-skill               bundle base:237-248
  -> ctx.skills.registerProvider / ctx.tools.register      skill:391-429; tools:1037-1062
  -> bindScopeParent(agentKey, standing.key)               agent-presets:286
  -> Agent 读取链: global + chainLayers(agent)             skill:552-566
```

Dynamic 对应链：

```
define 后的 Package
  -> cordis_run (tool)                                     tool-cordis:240-327
  -> DynamicCordisRunnerService.run()                      cordis-host-runner:248-312
  -> startFresh() -> startHostHalf()                       cordis-host-runner:823-881
  -> group.ctx.plugin(guardedPlugin(...))                  lifecycle:22-45
  -> Fiber (host half) + DynamicCordisRun                  registry:17-34
  -> harness.registerTool -> ctx.tools.register            guard:626-629
```

### C. Dispose

```
Active capability (provider registration / runtime skill / tool)
  -> returned effect disposer()                           skill:412-424; tools:1057-1061
  -> ScopedLayers.effect disposer: undo() + layer 回收     store:257-262
  -> invalidateCache(): revision++, clear collectCache     skill:622-626
  -> emit skills/change / tools/change                     skill:649-660; tools:812-813
  -> 下次 list/get 不再包含该 entry

Dynamic active run
  -> cordis_stop / cordis_undefine                        cordis-host-runner:456-471,210-218
  -> retract(): delete plugin.run; handler disposers; fiber.dispose()   cordis-host-runner:1219-1230
  -> emit cordis/dynamic-retract                          cordis-host-runner:1225-1229
  -> client runner retract                                client-runtime:304-310
  -> undefine: registry.delete(pluginId)                  registry:207-209
```

Skill 的 ACL/权限层在 dispose 链中 **NOT_FOUND**：没有 `revoke` 表，删除 entry 只是让未来查找 miss。

---

## 15. Capability Lifecycle Matrix

| 阶段 | 实际实现 | 核心 Symbol | 状态变化 | 持久化 | 可失败 | 可恢复 | Evidence |
|---|---|---|---|---|---|---|---|
| Discover | Skill：provider `list()` 扫描磁盘根 | `FileSystemSkillProvider.list` | 无注册表变化 | 文件本身持久 | 是（provider 失败被跳过） | 是（下次 list 重试） | skill-filesystem:182-198 |
| Parse | YAML frontmatter + body | `parseSkillFile` | 内存 ParsedSkill | 否 | 是（坏文件忽略） | 是（改文件后重现） | skill-filesystem:793-835 |
| Validate | Candidate/Definition 校验；Dynamic guard | `validateCandidate`/`validateDefinition`/`sandboxDefineTool` | 无 | 否 | 是（抛错） | 是 | skill:708-768；guard:551-629 |
| Register | layer insert / registry.add | `registerProvider`/`register`/`define` | 注册表增加 entry | 否（内存） | 是（重名/无效抛错） | 否（失败不落表） | skill:391-461；cordis-host-runner:151-202 |
| Resolve | layer merge + rank/order | `collectFresh`/`compareIndexedCandidates` | 只影响查询结果 | 否（collectCache 内存） | 否 | 是 | skill:552-583 |
| Mount | preset subtree / dynamic run fiber | `mountPreset`/`startHostHalf` | scope layer 或 fiber 出现 | 否 | 是（mount 失败回滚） | 是 | mount:332-381；lifecycle:22-45 |
| Invoke | skill load + catalog；tool dispatch | `SkillRegistry.get`/`ToolRuntime.execute` | 无注册表变化 | session event | 是（isError） | 是（下轮重试） | tool-skill:127-156；tools:1342-1362 |
| Dispose | effect disposer | `ScopedLayers.effect` disposer | 注册表 entry 删除 | 否 | 是（disposer 抛错被 log） | 否 | store:257-262；fiber:675-696 |
| Revoke | Dynamic `stop`/`undefine` | `retract`/`registry.delete` | run 删除 / plugin 删除 | 否 | 是 | stop 可再 run；undefine 不可 | cordis-host-runner:456-471,1219-1230 |
| Rollback | 动态 update 失败保留 current | `commitActivation`/`failAttempt` | current 不变、next 记录 | 否 | 否 | 是（mode:"run" 回滚） | versioning.spec:7-39 |
| Promote | **NOT FOUND**（Skill）；动态 current/next 近似 | `commitActivation` | currentPackageId 更新 | 否 | 是 | 是 | cordis-host-runner:981-992 |

---

## 16. Capability Runtime Contract

### Skill

| 项 | 谁创建 | 谁拥有 | 谁注册 | 谁解析 | 谁挂载 | 谁执行 | 谁观察 | 谁卸载 | 错误恢复 |
|---|---|---|---|---|---|---|---|---|---|
| Candidate | provider `list()` | provider（locator 不透明） | `SkillRegistry` collect 进 layer | registry（rank/order） | 无单独 mount；preset composition | provider `get()` | tool-skill catalog | provider disposer | 坏 provider 跳过，下次重试 |
| Definition | provider `get()` | provider 返回的 plain object | registry 不存 Definition（按需加载） | registry winner | 同上 | `renderSkillContent` → model | tool result | N/A（无运行对象） | validateDefinition 失败 → get 抛错 |
| Provider | plugin `apply()` 内 factory | 调用 context 的 fiber | `registerProvider` | registry layer | preset/subtree fiber | `list/get` | registry | effect disposer | 注册失败即抛错，signal abort |

### Dynamic Cordis Plugin

| 项 | 谁创建 | 谁拥有 | 谁注册 | 谁解析 | 谁挂载 | 谁执行 | 谁观察 | 谁卸载 | 错误恢复 |
|---|---|---|---|---|---|---|---|---|---|
| Package | `define()` | 创建它的 session（`sessionId`） | `DynamicCordisRegistry.packages` | runner `resolvePlan` | `run()` | host half `apply` / client half | `inventory/snapshot/inspect` | `undefine()` | define 失败不入表 |
| Run | `run()` | plugin record（`plugin.run`） | 无（非注册表） | `resolvePlan` | `startHostHalf` | fiber effects / handlers | `cordis/dynamic-package` / inspect | `stop()` | 启动失败自动 dispose fiber |
| Host half | sandbox evaluate | group fiber | `ctx.plugin` | Cordis inject | `startHostHalf` | `apply` | `missingServices` | `fiber.dispose` | failed 状态 + steering |
| Tool | `harness.defineTool` | dynamic plugin fiber | `harness.registerTool` | ToolRuntime layer | plugin mount | `ToolRuntime.execute` | model | plugin retract | tool error isError |

---

## 17. FACT / INFERENCE / HYPOTHESIS / UNKNOWN / NOT_FOUND

- `[FACT]` SkillRegistry 是 process 内单实例 + global/per-scope layer，注册 context 的 scope 决定 layer，读取 scope chain 决定 winner。（`packages/skill/skill/src/index.ts:346-356,552-566`）
- `[FACT]` Skill 的 winner 规则：同 layer 内 rank → providerOrder → localOrder；跨 layer 时 nearest layer 直接覆盖，不看 rank。（`packages/skill/skill/src/index.ts:807-811,552-566`；测试 `skill.spec.ts:1141-1170`）
- `[FACT]` `registerProvider`/`register` 返回 Cordis effect disposer，只撤销注册表 entry 并失效 cache；不取消已开始的 provider 调用。（`packages/skill/skill/src/index.ts:412-424`）
- `[FACT]` Skill 没有 mount 方法；agent 能力组合通过 `mountPreset` 把 provider/tool rows 挂进 scope layer。（`packages/preset/agent-presets/src/mount.ts:332-381`）
- `[FACT]` Dynamic Cordis plugin 具备完整 define → run → stop → undefine 闭环，模型可用 `cordis_*` 工具触发。（`packages/extensions/tool-cordis/src/index.ts:148-379`；`runner.spec.ts:150-176,421-487`）
- `[FACT]` Dynamic plugin registry 是 memory-only，重启丢失；错误消息明确写 “lost on DSH restart”。（`cordis-host-runner/src/index.ts:1248-1249`；`runner.spec.ts:489-495`）
- `[INFERENCE]` 动态 plugin 的 host-half fiber 挂在 host `cordis-dynamic` group 下（unscoped context），因此 `harness.registerTool` 注册的工具进入 global tool layer；plugin 记录本身按 session 归属，但工具可见性不由 session 过滤。依据：`requireGroup()` 用 `rootCtx.plugin`（`cordis-host-runner/src/index.ts:1237-1240`），guard 的 `ctx.tools.register` 直接调真实 ctx 的 `tools.register`（`guard.ts:626-629`），而 `tools.register` 按 `scopeOf(ctx)` 分层（`tools/src/index.ts:1057-1060`）。
- `[HYPOTHESIS]` 一个 model 在标准 preset 中可以用 `write`/`edit` 创建 skill 文件并在下一轮通过 catalog 使用；机制每一环都有 FACT，但仓库中没有 “agent 自己生成 skill → 下一轮使用” 的端到端测试，因此整体标为 HYPOTHESIS 而非 FACT。
- `[UNKNOWN]` Client-side dynamic plugin 的 slot/theme 注册细节未在本报告展开（属于 browser 半边），不影响 host 链路结论。
- `[NOT_FOUND]` Skill version 字段、Skill 依赖声明、Skill 持久化 registry、Skill 专用 self-generation API、Skill audit 表。
- `[NOT_FOUND]` Skill 的 `PROMOTED` / `ROLLED_BACK` / `REVOKED` 状态。

---

## 18. 最终 10 问

1. **Capability 的最小运行时抽象是什么？** 没有统一抽象。Skill 的最小抽象是 `SkillCandidate`（发现期）和 `SkillDefinition`（加载期）这两个 plain object；Dynamic Plugin 的最小抽象是 `DynamicCordisDefinition`（Package）。两者之上是各自的注册表（`SkillRegistry` / `DynamicCordisRegistry`）。
2. **Registration 和 Mount 的本质区别？** Registration 只改变注册表（layer entry / registry Map）；Mount 创建 Fiber/plugin subtree 或 preset composition，并让 plugin 的 effects（provider、tool、service）真正生效。`cordis_define` 是注册，`cordis_run` 才是 mount；skill 没有 mount 方法，mount 语义由 `mountPreset` 承担。
3. **Provider 和 Capability 的本质区别？** Provider 是来源（`SkillProvider.list/get`），Capability 是 provider 暴露的候选/定义/运行对象。Provider 注册进 registry；Skill 本身不是 Provider。
4. **Scope 解决什么问题？** 让同一个 process 内 registry 能同时服务 host 和每个 agent：注册者所在的 context scope 决定 entry 落在哪一层，读取者通过 scope chain 决定合并哪些层，实现 per-preset/per-agent 可见性隔离与继承。
5. **Winner / rank / priority 解决什么问题？** 同名冲突。同 layer 内用 rank → providerOrder → localOrder 决定唯一 winner；跨 layer 用 nearest-layer-wins 决定唯一 winner。Shadowed entry 保留在注册表，winner 移除后可恢复。
6. **Disposer 到底提供什么生命周期能力？** 只提供“撤销一次注册”的能力：删除 entry、失效 cache、通知变化、幂等。它不是 stop、不是 revoke、不是 rollback；dynamic plugin 的 stop/undefine/rollback 是另一套 API。
7. **是否真正实现了 Self-generating Capability？** 对 Dynamic Cordis Plugin：是，源码和测试完整证明 `define → run → stop → undefine` 模型可自触发。对 Markdown Skill：机制上可行（写文件 → watcher/fs/observed → catalog → tool），但没有专门的 self-generation 链路证明。
8. **是否有持久化 Capability Registry？** 没有。SkillRegistry 和 DynamicCordisRegistry 都是内存；只有 skill 文件、preset 文件和 session event log 会落盘。
9. **是否有完整 Validation → Registration → Mount → Execution → Revoke 生命周期？** Dynamic Plugin 有完整显式生命周期；Skill 有 Validation → Registration（catalog）→ Load/Invocation，但没有独立 Revoke/Rollback 状态，卸载即 disposer 删 entry。
10. **哪些已实现，哪些是未来 Forge 要补齐的？** 已实现：双层 skill registry、scope 继承与 winner 解析、catalog/loader、文件 watcher、动态 plugin 的版本化 define/run/stop/undefine、sandbox/guard、approval。未实现（NOT_FOUND）：skill version、skill dependency、skill 持久化 registry、skill 专用 self-generation API、统一的 revoke/rollback 状态机。
