# SWE-agent Trajectory Persistence — Code Archaeology Report

> 研究对象：upstream [`SWE-agent/SWE-agent`](https://github.com/SWE-agent/SWE-agent)
> 研究版本：`v1.1.0`（`sweagent/__init__.py:15`），commit `3ea751c087f32b16e039a2233dd6eefecef325d5`（2026-07-16）
> 源码依据：本地 clean clone `<home>/k8s/auto_swe_sys/SWE-agent`
> 范围：仅 Execution Artifact / Trajectory Persistence；不改源码、不写业务代码

---

# 1. Executive Summary

SWE-agent 的一次运行（`RunSingle.run` → `DefaultAgent.run`）会在 `<output_dir>/<instance_id>/` 下沉淀一组独立文件：`<instance_id>.traj`（主产物）、`config.yaml`、`<instance_id>.{trace,debug,info}.log`、`<instance_id>.pred`，以及可选（run-batch 模式）的 `<instance_id>.patch`、`preds.json`、`results.json`。

核心结论：

- `.traj` 是单个 JSON 文件，顶层五个 key：`environment`（环境名，仅一个字符串）、`trajectory`（每步结构化记录）、`history`（喂给 LM 的完整消息序列）、`info`（提交/退出/成本元数据）、`replay_config`（完整 RunSingleConfig 的 JSON 序列化，用于 replay）。
- 每一步 `TrajectoryStep` 的真实字段：`action`、`observation`、`response`、`thought`、`execution_time`、`state`、`query`、`extra_info`。**没有 wall-clock timestamp**；`execution_time` 只是动作执行的耗时秒数。tool calls / thinking blocks 不在 `TrajectoryStep` 里，只在 `history` 里。
- 写盘由 Agent 自己完成：`DefaultAgent.save_trajectory()` 在 `DefaultAgent.run` 的每步循环里调用；`RetryAgent` 在每步、每次 attempt 收尾、全部结束后各写一次。写法是 `Path.write_text(json.dumps(data, indent=2))` —— **overwrite 整个文件，不是 append，也不是原子写**。
- replay（`sweagent run replay --traj_path xxx.traj`）是**重新执行**：从 `.traj` 的 `history` 提取 assistant actions，用 `ReplayModel` 按序把动作重新喂给一个**全新环境**（从 `replay_config` 重建 deployment/repo/base_commit），不是恢复保存的 observation/state。
- patch 不是 trajectory 之外的独立产出，但被**冗余存储**：`info.submission`（在 .traj 内）↔ `<instance_id>.pred`（`model_patch`）↔ `<instance_id>.patch` ↔ batch 汇总 `preds.json`。evaluation 只消费 `preds.json`，不读 `.traj`。
- 不存在名为 `ExecutionRecord` 的类或 symbol；最接近的运行时对象是 `AgentRunResult`（`types.py:100-102`），落盘后的“执行记录”是上面那一组文件。

速答：

| Q | 答案 |
|---|---|
| Q1. ExecutionRecord 是什么？ | SWE-agent 没有 `ExecutionRecord` 类。运行时执行记录 = `AgentRunResult{info, trajectory}`；持久化记录 = `.traj + .pred/.patch + config.yaml + logs` 这组 artifact。 |
| Q2. trajectory 是完整 source of truth 吗？ | 不是。它是**过程**（step + history + info）的 source of truth，但不是环境、评估、完整模型内部状态的 source of truth；tool_calls 只在 history 里，环境只存名字，环境规格在 replay_config 里。 |
| Q3. patch 是 trajectory 的一部分吗？ | 内容上是（`info.submission`，且提交步的 `observation` 也会被写成 patch 文本）；作为 artifact 又单独落 `.pred` / `.patch` / `preds.json`。 |
| Q4. replay 依赖什么？ | `.traj` 内的 `history + replay_config`，外加可重建的外部状态：deployment（镜像）、repo（URL/local path/base_commit）、问题文本、SWE-agent 自身代码与工具配置；不需要模型 API，但需要 Docker/SWE-ReX、网络、`GITHUB_TOKEN`（Github repo 时）。 |
| Q5. evaluation 依赖什么？ | 只依赖 `preds.json`（`instance_id` + `model_patch`）→ `sb-cli`（或外部 SWE-bench harness）；不读 `.traj`。 |
| Q6. 哪些可借鉴到 Capability Forge？ | 见第 10 节：每步持久化、process/history 分离、自描述 replay_config、评估只吃最小 prediction、attempt 聚合 + `best_attempt_idx`。 |

**查看/恢复路径**：`sweagent inspect` / `sweagent inspector` 看 `.traj`（`docs/usage/inspector.md`）；`sweagent run --config config.yaml` 用同一配置重跑；`sweagent run replay --traj_path x.traj` 重放动作；`preds.json` 直接送 SWE-bench 评估（`docs/usage/trajectories.md:55-100`）。

---

# 2. Agent Execution Data Model

运行时对象链（全部在 `sweagent/types.py` 定义）：

```text
StepOutput(types.py:15-42)
  └─ 单步内部对象：query / thought / action / output / observation /
     execution_time / done / exit_status / submission / state /
     tool_calls / tool_call_ids / thinking_blocks / extra_info

TrajectoryStep(types.py:44-58)   ← 落盘的每步（TypedDict，8 字段）
HistoryItem(types.py:56-79)      ← 落盘的 LM 消息（role/content/message_type + 可选扩展）
History = list[HistoryItem]      (types.py:77)
Trajectory = list[TrajectoryStep](types.py:78)
AgentInfo(types.py:82-98)        ← 落盘的元数据（TypedDict, total=False）
AgentRunResult(types.py:100-102) ← run() 的返回值 {info, trajectory}
```

`DefaultAgent.__init__`（`sweagent/agent/agents.py:477-489`）明确持有三份“同一次运行的不同视图”：

- `self.history = []`（agents.py:481）—— 面向模型的完整消息序列；
- `self._trajectory = []`（agents.py:482）—— 环境可验证的 step 记录；
- `self.info = AgentInfo()`（agents.py:483）—— 提交、退出状态、成本、hash 等元数据；
- `self.traj_path: Path | None`（agents.py:477）、`self._replay_config`（agents.py:487）。

单步数据流（`DefaultAgent.step`，agents.py:1235-1261）：

1. `forward_with_handling(self.messages)`（agents.py:1062）→ `forward`（agents.py:1006）：`step.query = copy.deepcopy(history)`（agents.py:1026），`step.output = model.query(...)`，然后 `parse_actions` 拆出 `thought/action`；
2. `handle_action`（agents.py:936 起）执行 `action`，得到 `observation`，`execution_time = perf_counter 差`（agents.py:960-990），并 `handle_submission`（agents.py:870）检查提交；
3. `add_step_to_history(step)`（agents.py:714）：assistant history 项的 `content` 是 **`step.output`（原始模型输出）**，另存 `thought/action/tool_calls/thinking_blocks`（agents.py:719-728）；
4. `info` 更新：`submission`、`exit_status`、`edited_files30/50/70`、`model_stats`（agents.py:1255-1258）；
5. `add_step_to_trajectory(step)`（agents.py:1220-1231）。

失败/重试语义：format error、blocked action、bash 语法错误等会 requery（`forward_with_handling`，agents.py:1062-1210）；期间产生的失败 step 也进 trajectory（`handle_error_with_retry` 里 `add_step_to_trajectory(step)`，agents.py:1088-1092），但**不进 history**（agents.py:1067 注释明确：trajectory 更新，history 不更新）。各类 exit 错误统一走 `attempt_autosubmission_after_error`（agents.py:823），尽力把当前 diff 作为 submission 收尾。

---

# 3. Trajectory Data Model

## 3.1 `TrajectoryStep` 真实定义

`sweagent/types.py:44-58`：

```python
class TrajectoryStep(TypedDict):
    action: str
    observation: str
    response: str
    state: dict[str, str]
    thought: str
    execution_time: float
    query: list[dict[str, Any]]
    extra_info: dict[str, Any]
```

写入点在 `DefaultAgent.add_step_to_trajectory`（`sweagent/agent/agents.py:1220-1231`），直接透传 `StepOutput` 字段。

## 3.2 每步问题逐项回答

| 你要问的 | 落盘位置 | 事实 |
|---|---|---|
| agent output | `response` | 模型原始输出（`step.output`），agents.py:1225 |
| action | `action` | 解析后的动作文本/命令，agents.py:1223 |
| command | `action` | 同一字段；真正执行前还会 `guard_multiline_input(...).strip()`（agents.py:961） |
| observation | `observation` | 环境执行输出；提交时会被替换成 patch 文本（agents.py:898） |
| environment feedback | `observation` + `state` + `exit_status` | `state` 是动作后的环境状态（如 open_file/working_dir/diff，agents.py:993 `tools.get_state`）；`exit_status` 只在 `info` 层（agents.py:1256），**不在每步** |
| timestamp | 无 | `TrajectoryStep` 没有时间戳字段；只有 `execution_time`（float 秒，动作耗时，agents.py:990）。文件 mtime 是唯一时间证据 |
| metadata | `extra_info` + `info` + `query` | 每步 `extra_info`（action sampler 等）；全局 `info`（submission/exit_status/model_stats/hash）；`query` 是该步喂给 LM 的精确输入（agents.py:1026） |

## 3.3 `history`：与 trajectory 平行的另一份数据

`HistoryItem`（types.py:56-79）必填 `role/content/message_type`，可选 `agent/is_demo/thought/action/tool_calls/tool_call_ids/tags/cache_control/thinking_blocks`。

- assistant 项：`content = step.output`（agents.py:719），`message_type="action"`；
- user/tool 项：observation 模板渲染结果（agents.py:675-712），`message_type="observation"`；
- system 项：system prompt（agents.py:608-616）。

因此 **tool_calls / thinking_blocks 等模型内部字段只在 `history` 里，`TrajectoryStep` 里没有**。replay 也从 `history` 取动作（run_replay.py:138-162），不从 `trajectory` 取。

## 3.4 `info` 真实定义

`AgentInfo`（types.py:82-98）：

```python
class AgentInfo(TypedDict, total=False):
    model_stats: dict[str, float]        # 与 models.py APIStats 同构
    exit_status: str | None
    submission: str | None
    review: dict[str, Any]               # ReviewerResult
    edited_files30: str
    edited_files50: str
    edited_files70: str
    summarizer: dict
    swe_agent_hash: str
    swe_agent_version: str
    swe_rex_version: str
    swe_rex_hash: str
```

运行时还会被追加：`DefaultAgent.step` 写入 submission/exit_status/edited_files/model_stats（agents.py:1255-1258）；`RetryAgent` 追加 `best_attempt_idx`、`rloop_model_stats`、`chooser`（agents.py:374-380）。

## 3.5 真实 JSON 示例

仓库自带（旧版 v0.7.0 格式，`trajectories/demonstrations/replay__marshmallow-code__marshmallow-1867__function_calling_replace__install-1/marshmallow-code__marshmallow-1867.traj`）：

```json
{
  "environment": "main",
  "trajectory": [
    {
      "action": "create reproduce.py",
      "observation": "[File: reproduce.py (1 lines total)]\r\n1:",
      "response": "Let's first start by reproducing the results of the issue...",
      "thought": "Let's first start by reproducing the results of the issue...",
      "execution_time": 0.238733730999229,
      "state": {"open_file": "/testbed/reproduce.py", "working_dir": "/testbed"}
    }
  ],
  "history": [
    {"role": "system", "content": "...", "agent": "main", "message_type": "system_prompt"},
    {"role": "assistant", "content": "...", "thought": "...", "action": "create reproduce.py",
     "agent": "main", "tool_calls": null, "message_type": "action", "thinking_blocks": null}
  ],
  "info": {
    "submission": "\ndiff --git a/src/marshmallow/fields.py b/src/marshmallow/fields.py\n...",
    "exit_status": "submitted",
    "edited_files30": "...",
    "edited_files50": "...",
    "edited_files70": "...",
    "model_stats": {"total_cost": 0, "instance_cost": 0, "tokens_sent": 0, "tokens_received": 0, "api_calls": 0}
  },
  "replay_config": {"env": {...}, "agent": {...}, "problem_statement": {...}, "output_dir": "...", "actions": {...}, "env_var_path": null}
}
```

**与当前 v1.1.0 源码的差异（必须记录）**：当前 writer（agents.py:762-777）在每步还会写 `query` 与 `extra_info`（`TrajectoryStep` 已定义），并把 `replay_config` 序列化为 **JSON 字符串**（`model_dump_json()`，agents.py:775）；仓库内这份 demo 是 dict 且缺 `query/extra_info`。`run_replay` 与 `traj-to-demo` 两种格式都兼容（run_replay.py:98-100、run_traj_to_demo.py:38-40）。

---

# 4. .traj Persistence

## 4.1 谁写、什么时候写

- `DefaultAgent.save_trajectory()`（agents.py:779-787）：
  - 数据：`get_trajectory_data()`（agents.py:762-777）= deepcopy `{trajectory, history, info}` + `replay_config` + `environment`；
  - 调用点：`DefaultAgent.run` 每完成一步就写一次（agents.py:1284-1286），最后一次覆盖；
  - `RetryAgent.save_trajectory(choose)`（agents.py:385-388）：每步 `choose=False`（agents.py:415）、每次 attempt 收尾后 `choose=False`（agents.py:427）、全部结束后 `choose=True`（agents.py:432）。
- 谁不写：`RunSingle` / `RunBatch` 不直接写 `.traj`，它们只建目录、写 config、跑 hooks、写 `.pred`（run_single.py:188-208、run_batch.py:333-372）。

## 4.2 文件格式 / 文件名 / 路径

- 格式：JSON（`json.dumps(data, indent=2)`），无 schema/version 字段。
- 文件名：`<instance_id>.traj`（agents.py:589）；instance_id 来自 ProblemStatement（Github issue → `owner__repo-i<issue_number>`，problem_statement.py:147；文本/文件 → sha256 前 6 位，problem_statement.py:86/119）。
- 路径：`output_dir / <instance_id> / <instance_id>.traj`（agents.py:589、run_single.py:196-197）。
  - `sweagent run` 默认：`cwd/trajectories/<user>/<config_stem>__<model_id>___<problem_id>/<instance_id>/<instance_id>.traj`（run_single.py:68-79）。
  - `sweagent run-batch` 默认：`TRAJECTORY_DIR/<user>/<config_stem>__<model_id>___<source_id><suffix>/...`，`TRAJECTORY_DIR` 可用 `SWE_AGENT_TRAJECTORY_DIR` 覆盖（`__init__.py:46-47`、run_batch.py:99-117）。

## 4.3 原子性 / append / overwrite

- **非原子**：`self.traj_path.write_text(...)`（agents.py:787、388）直接截断重写，无 temp file、无 `os.replace`、无 fsync。中途 kill 可能留下被截断的 JSON；`run_batch.should_skip` 会把读不了的旧文件删除重跑（run_batch.py:403-405）。
- **overwrite**：每步全量重写同一路径，不是 append。好处是崩溃后至少保留上一个成功 step 的完整快照；坏处是文件越大写盘越贵，且同一路径无法保留多版本。
- RetryAgent 模式下：当前 attempt 的逐步快照写到 `attempt_<i>/<id>.traj`（子 agent 自己的 save，agents.py:315-318 + 351-355），顶层 `.traj` 每步只包含**已 finalized 的 attempts**（agents.py:363-374）。

---

# 5. Config / Log / Patch Boundary

| Artifact | 写入者 | 内容 | 边界 |
|---|---|---|---|
| `config.yaml` | `RunSingle.run`（run_single.py:197） | `replay_config.model_dump_json()` 的 YAML（即完整 RunSingleConfig） | 可用来“以相同配置重跑”，不是 replay |
| `<id>.config.yaml` | `RunBatch._run_instance`（run_batch.py:343-345） | 单实例 RunSingleConfig | 同上，batch 版 |
| `run_batch.config.yaml` | `RunBatch.from_config`（run_batch.py:200） | 整个 batch 配置 | 复现 batch |
| `<id>.{trace,debug,info}.log` | `RunSingle.__init__`（run_single.py:143-148）/ `RunBatch`（run_batch.py:168、411-417） | 本实例日志 | 排查用；与 traj 不同步写 |
| `<id>.traj` | Agent（见第 4 节） | 过程记录 | 主产物 |
| `<id>.pred` | `save_predictions`（common.py:370-380） | `{model_name_or_path, instance_id, model_patch: info["submission"]}` | 单实例 prediction；SWE-bench 可读 |
| `<id>.patch` | `SaveApplyPatchHook._save_patch`（apply_patch.py:76-90） | `info["submission"]` 原文 | 给人 git apply 用；只在有 submission 时生成 |
| `preds.json` | `merge_predictions`（merge_predictions.py:13-46，batch 末尾 run_batch.py:252） | `{instance_id: pred}` | 评估入口；重复 instance_id 直接报错 |
| `results.json` | `SweBenchEvaluate.move_sb_cli_report`（swe_bench_evaluate.py:94-105） | sb-cli 报告改名 | 评估结果；inspector 显示 ✅/❌ 读它 |

文档对照（`docs/usage/trajectories.md:55-76`）：文档树里的 `instance_1.config.yaml` 对应 batch 命名；`sweagent run` 单实例写的是 `config.yaml`。文档说 `preds.json` 可直接送 SWE-bench 且 evaluation 是独立步骤（trajectories.md:90-100）——与源码一致。

---

# 6. Environment / Replay Boundary

## 6.1 环境边界

- `.traj` 只存 `environment: <name>`（agents.py:776），**不存环境快照**。
- 环境的可重建规格在 `replay_config.env`：`EnvironmentConfig`（deployment + repo + post_startup_commands，swe_env.py:21-43）；repo 规格含 `base_commit`（repo.py:21-27，默认 `HEAD`）。
- 环境不是“恢复”的，而是每次 `SWEEnv.start() → reset()`：`cd /`、复制/克隆 repo、`git restore . && git reset --hard && git checkout <base_commit> && git clean -fdq`（swe_env.py:135-147、repo.py:31-38）。

## 6.2 `replay_config` 到底是什么

- 类型：`RunSingleConfig`（pydantic BaseSettings，run_single.py:83-96），字段 `env / agent / problem_statement / output_dir / actions / env_var_path`。
- 何时写入：`RunSingle.from_config` 把 config 挂到 agent（run_single.py:170）；`DefaultAgent.get_trajectory_data` 序列化进 `.traj`（agents.py:775）；setter 会调用 `_strip_abspath_from_dict` 把绝对路径转成相对（agents.py:533-537、utils/config.py:30-44）——这是为跨机器 replay 做的可移植性处理。
- 旧 `.traj` 没有这个 key；replay 时 `KeyError` 会报 “Are you running on an old trajectory?”（run_replay.py:102-105）。

## 6.3 replay 是恢复还是重新执行？

**重新执行**。证据链：

1. `RunReplay._create_actions_file`（run_replay.py:138-162）：遍历 `traj["history"]` 里所有 assistant 项，取 `content`（+ function-calling 时的 `tool_calls`），写成临时 JSON 动作文件；
2. `_get_config_from_agent`（run_replay.py:96-120）：读 `replay_config`、合并 `update_config`，并把模型替换成 `ReplayModelConfig(replay_path=动作文件)`（run_replay.py:118-120）；
3. `ReplayModel.query`（models.py:464-525）：按序吐回保存的 assistant 消息，走正常 agent loop（parse → execute → observation），**保存的 observation/state 被丢弃**；动作耗尽则自动 submit（models.py:501-514）；
4. `RunReplay._get_env`（run_replay.py:173-180）创建全新 `SWEEnv`，且 **`post_startup_commands=[]`**（replay 不会重放原始 post-startup 命令）。

## 6.4 replay 需要哪些外部状态

- `.traj`（`history` + `replay_config`）——自描述输入；
- deployment：Docker 镜像等（`replay_config.env.deployment`；可用 `--deployment` 覆盖，run_replay.py:51-52）；
- repo：`base_commit` + 获取方式（Github URL 需网络与 `GITHUB_TOKEN`，repo.py:165-181；local path 需原机器上路径仍存在；SWE-bench 用预置镜像 + preexisting testbed）；
- 问题文本：`replay_config.problem_statement`（GitHub issue 会再次联网拉取，或直接存 text）；
- SWE-agent 自身版本/工具配置（`replay_config.agent`；agent.setup 会重新 `tools.install`，agents.py:577-580）；
- 不需要：模型 API key（模型被 ReplayModel 替换，models.py:204-216）。

**结论：trajectory 本身不足以 replay**——必须有 replay_config + 可重建的外部环境；保存的 observation 只是参考，不是恢复依据。

---

# 7. Retry / Attempt Semantics

## 7.1 单 agent（DefaultAgent）

- 一次 `run` = 一个 env + 一个 attempt + 一个 `<id>.traj`（agents.py:1265-1294）。
- 没有 attempt 区分字段；失败/autosubmission 只反映在 `info.exit_status`（如 `exit_format`、`exit_cost`、`exit_environment_error`、`submitted (...)`，agents.py:1074-1208、900-903）。

## 7.2 RetryAgent

- `RetryAgentConfig` 是 `agent_configs: list[DefaultAgentConfig] + retry_loop`（agents.py:193-198）。
- 每个 attempt：
  - 子 agent 输出目录 `attempt_<i>`（agents.py:315-318），子 agent 自己的 `save_trajectory()` 写到 `attempt_<i>/<id>.traj`（agents.py:351-355）；
  - `_finalize_agent_run` 把 `_agent.get_trajectory_data()` append 进 `_attempt_data`（agents.py:351-356）；
  - attempt 之间 `_env.hard_reset()`（agents.py:321-326、swe_env.py:128-133）——环境彻底重启，保证隔离；
- 顶层 `.traj` 最终形态（agents.py:358-381）：
  ```json
  {
    "attempts": [ <attempt_0 数据>, <attempt_1 数据>, ... ],
    "trajectory": ..., "history": ..., "info": {
      ..., "best_attempt_idx": N, "rloop_model_stats": {...}, "chooser": {...}
    },
    "replay_config": "...", "environment": "..."
  }
  ```
  `choose=True` 时把 best attempt 的数据 merge 到顶层（agents.py:374-376），`info.model_stats` 覆盖为所有 attempts 的总和（agents.py:377-378）。
- `run()` 里逐步 `save_trajectory(choose=False)`（agents.py:413-432）：中途只含已 finalized attempts；当前 attempt 的逐步快照在子目录。

## 7.3 batch 层的“失败/重试/重新执行”

- `should_skip`（run_batch.py:376-409）：`.traj` 已存在且 `info.exit_status` 非空 → skip；空文件/无法解析/无 exit_status → 删除后重跑；`--redo_existing=True` 强制全部重跑（run_batch.py:83-84、120-128）。
- `remove_unfinished`（remove_unfinished.py:13-44）：清理 `info.submission is None` 的目录。
- `merge-preds`（`sweagent merge-preds`）可把中断 batch 的 `.pred` 重新汇总（docs/usage/trajectories.md:92-93；merge_predictions.py:13-46）。

---

# 8. Evaluation Boundary

## 8.1 patch 从哪里来

- agent 执行 submit 命令后，`handle_submission`（agents.py:870-905）从容器内 `/root/model.patch` 读 patch（agents.py:887）：
  - `step.submission = patch`；`step.observation = patch`；`step.exit_status = "submitted"`；`step.done = True`（agents.py:897-903）；
  - 随后 `info["submission"]`（agents.py:1255）；
- 异常收尾时 `attempt_autosubmission_after_error` 先跑 `git add -A && git diff --cached > /root/model.patch`（agents.py:856），再走同一读取逻辑。

## 8.2 patch 的落盘链

```text
info.submission
  ├─ .traj（agents.py:775 所在 get_trajectory_data 打包）
  ├─ <id>.pred（common.py:370-380）
  ├─ <id>.patch（apply_patch.py:76-90，仅当有 submission）
  └─ preds.json（merge_predictions.py:13-46，batch 末尾 run_batch.py:252）
```

`.pred` 丢失时可用 `extract_pred` 从 `.traj` 的 `info.submission` 重新生成（extract_pred.py:12-19）。

## 8.3 evaluator 从什么数据判断成功

- **只读 `preds.json`**：`SweBenchEvaluate._get_sb_call` 拼 `sb-cli submit <subset> <split> --predictions_path preds.json`（swe_bench_evaluate.py:43-72），运行结束 `on_end` 提交 `preds.json`（swe_bench_evaluate.py:107-123），报告改名 `results.json`（swe_bench_evaluate.py:94-105）。
- 中间还会每 `continuous_submission_every` 秒提交 `tmppreds.json`（swe_bench_evaluate.py:74-92）。
- trajectory 不参与判定；`docs/usage/trajectories.md:100` 与 `docs/usage/batch_mode.md:211-225` 均明确：评估是独立步骤，`preds.json` 直接进 SWE-bench。
- inspector 的 ✅/❌ 从同目录 `results.json` 读取（docs/usage/inspector.md:86-95）。

---

# 9. Artifact Lifecycle

## 9.1 Artifact Boundary Diagram

```text
┌────────────────────────── RunSingleConfig ──────────────────────────┐
│  env (deployment/repo/base_commit) · agent · problem_statement ·   │
│  output_dir · actions · env_var_path                                │
└────────────────────────────────┬────────────────────────────────────┘
                                 │ agent.replay_config (run_single.py:170)
                                 ▼
                       ┌──────────────────┐
                       │ SWEEnv (fresh)   │
                       │ deployment + repo│
                       │ reset to base    │
                       └────────┬─────────┘
                                │ execute action
                                ▼
      ┌──────────────────────────────────────────────────┐
      │ DefaultAgent.run / RetryAgent.run                │
      │   history ← LM messages         (agents.py:714)  │
      │   trajectory ← verified steps   (agents.py:1220) │
      │   info ← submission/status/stats(agents.py:1255) │
      │   save_trajectory() 每步全量覆写  (agents.py:787) │
      └──────────────────────┬───────────────────────────┘
                             │
        ┌────────────────────┼────────────────────────────┐
        ▼                    ▼                            ▼
  <id>.traj            config.yaml / <id>.config.yaml    <id>.{trace,debug,info}.log
  (environment         (replay_config 的 YAML，          (排查日志)
   trajectory          run_single.py:197,
   history             run_batch.py:343-345)
   info
   replay_config)
        │
        ├── info.submission ──► <id>.pred (common.py:370) ──► preds.json (merge_predictions.py:13)
        │                          │                              │
        │                          └── <id>.patch (apply_patch.py:76)
        │                                                         ▼
        │                                              sb-cli / SWE-bench harness
        │                                                         │
        │                                                         ▼
        │                                                  results.json
        │                                              (swe_bench_evaluate.py:94-105)
        ▼
  Replay: sweagent run replay --traj_path <id>.traj
     history(assistant) + replay_config
     → ReplayModel 按序吐动作 (models.py:490)
     → 全新 SWEEnv 重新执行 (run_replay.py:173-180)
     → 产出新的 .traj / .pred
```

## 9.2 生命周期

1. 运行前：config 解析（CLI + yaml merge，common.py:120-319），`agent.replay_config` 注入；
2. 运行中：每步执行 → history/trajectory/info 更新 → `.traj` 全量覆写；logs 追加；
3. 结束：hooks（`.patch`）、`save_predictions`（`.pred`）、batch 末尾 merge（`preds.json`）；
4. 评估：外部 sb-cli 消费 `preds.json` → `results.json`；
5. 事后：inspect 查看；`traj-to-demo` 转 demo；`run replay` 重执行；`extract_pred` 反推 `.pred`。

---

# 10. Capability Forge Relevance

可借鉴的设计（每条都有源码锚点）：

1. **过程与面向模型的消息分离**：`trajectory`（环境可验证）与 `history`（模型视角）同写一份文件，但职责不同（agents.py:481-483、1220、714）。诊断、训练数据重建、审计可以各取所需。
2. **每步持久化 + 全量覆写**：崩溃后至少保留最后完整 step，batch 通过 `exit_status` 判断完成度并支持重跑/跳过（agents.py:1284-1286、run_batch.py:376-409）。Capability Forge 若要 resume，应在每步后落盘，并记录 completion marker。
3. **自描述 replay 配置**：把完整 RunSingleConfig 嵌入 artifact，replay 无需额外 CLI 参数（agents.py:775、run_replay.py:96-120）；路径做相对化以支持换机器（agents.py:533-537）。
4. **评估与过程解耦**：evaluator 只吃最小 prediction（`instance_id + model_patch`），不看 trajectory（common.py:370-380、swe_bench_evaluate.py:43-72）。这让评估结果不依赖记录完整性，也便于替换评测后端。
5. **Attempt 聚合**：`attempts` 数组 + `best_attempt_idx` + 每 attempt 独立子目录 + 环境 hard reset（agents.py:315-318、358-381、swe_env.py:128-133），天然支持多尝试归因。
6. **冗余但明确边界**：patch 同时存在 `.traj/.pred/.patch/preds.json`，各有消费方（查看/单实例评估/人肉应用/批量评估），且可从 `.traj` 反推 `.pred`（extract_pred.py:12-19）。
7. **工具输出与状态同时保存**：`state`（open_file/working_dir/diff）让 replot 和 demo 不依赖容器（agents.py:1228、run_traj_to_demo.py:35-55）。

---

# 11. What We Should NOT Copy

1. **非原子写盘**：`Path.write_text` 直接覆写（agents.py:787），无 temp+rename/fsync。崩溃会截断 JSON，且 read 端只能靠删文件重跑兜底（run_batch.py:403-405）。Capability Forge 应做原子写 + 版本化/append。
2. **无 schema/version 的 `.traj`**：读端靠 `KeyError` 判断“旧轨迹”（run_replay.py:102-105）；字段演进（query/extra_info/replay_config）没有迁移层。应在 artifact 顶层放 schema version。
3. **`replay_config` 字符串再序列化**：JSON 里嵌 JSON 字符串（agents.py:775），消费端必须双解析（run_replay.py:98-100、run_traj_to_demo.py:38-40）。直接存对象或分开文件更干净。
4. **`environment` 只存名字**：对恢复环境毫无用处（agents.py:776），真正的规格全靠 replay_config，二者冗余且不一致风险高。
5. **每步无时间戳**：只有 `execution_time` 秒数（agents.py:990），跨步延迟、推理耗时、系统时间无法分析。至少应加 `ts`/`step_started_at`。
6. **TrajectoryStep 丢字段**：tool_calls、thinking_blocks、done、exit_status 不在 step 级（types.py:44-58），要回看必须 cross-reference `history`/`info`，容易漏。
7. **评估绑定外部 sb-cli**：`subprocess.run("sb-cli submit ...")`（swe_bench_evaluate.py:107-123），离线/无账号即不可用；`merge_predictions` 遇重复 instance_id 直接 raise（merge_predictions.py:42-43）。
8. **replay 丢弃 post_startup_commands**（run_replay.py:173-180）：重放可能系统性偏离原始运行，且没有显式告警。
9. **绝对路径魔法**：`_strip_abspath_from_dict` 把“能解析成路径的字符串”全部改相对（utils/config.py:30-44），对文本型字段有误伤风险。
10. **文档滞后源码**：docs 示例是 v0.7.0（trajectories.md:37），缺 `query/execution_time/extra_info/replay_config`，且文档树命名只覆盖 batch 情形；研究/复现时不能只信文档。

---

# 12. Evidence Index

所有路径相对仓库根 `<home>/k8s/auto_swe_sys/SWE-agent`；commit `3ea751c`。

| Path:Line | Symbol / 语句 | 证据作用 |
|---|---|---|
| `sweagent/types.py:15-42` | `StepOutput` | 单步运行时对象全部字段 |
| `sweagent/types.py:44-58` | `TrajectoryStep` | `.traj` 每步 8 字段真实 schema |
| `sweagent/types.py:56-79` | `HistoryItem` / `History` | history 条目 schema（含 tool_calls/thinking_blocks） |
| `sweagent/types.py:82-102` | `AgentInfo` / `AgentRunResult` | info schema；无 ExecutionRecord 类 |
| `sweagent/agent/agents.py:477-489` | `DefaultAgent.__init__` | `history/_trajectory/info/traj_path/_replay_config` 定义 |
| `sweagent/agent/agents.py:529-537` | `replay_config` property/setter | replay_config 类型与绝对路径剥离 |
| `sweagent/agent/agents.py:561-601` | `DefaultAgent.setup` | `traj_path = output_dir/(id+".traj")`（589）、info hash 初始化 |
| `sweagent/agent/agents.py:675-712` | `_add_templated_messages_to_history` | observation 消息写入 history |
| `sweagent/agent/agents.py:714-746` | `add_step_to_history` | assistant history 项：`content=step.output`（719） |
| `sweagent/agent/agents.py:762-777` | `get_trajectory_data` | `.traj` 顶层数据组装；replay_config（775）、environment（776） |
| `sweagent/agent/agents.py:779-787` | `save_trajectory` | 非原子 `write_text(json.dumps(..., indent=2))`（787） |
| `sweagent/agent/agents.py:823-866` | `attempt_autosubmission_after_error` | 异常收尾：`git diff --cached > /root/model.patch`（856） |
| `sweagent/agent/agents.py:870-905` | `handle_submission` | patch 来源：读 `/root/model.patch`（887）；`observation=patch`（898） |
| `sweagent/agent/agents.py:1006-1026` | `forward` | `step.query = copy.deepcopy(history)`（1026） |
| `sweagent/agent/agents.py:1062-1210` | `forward_with_handling` | requery/autosubmit 分支；失败 step 进 trajectory（1088-1092）不进 history |
| `sweagent/agent/agents.py:1220-1231` | `add_step_to_trajectory` | TrajectoryStep 8 字段写入 |
| `sweagent/agent/agents.py:1235-1261` | `DefaultAgent.step` | info 更新（submission/exit_status/edited_files/model_stats） |
| `sweagent/agent/agents.py:1265-1294` | `DefaultAgent.run` | 每步 `save_trajectory()`（1284-1286）；返回 AgentRunResult（1294） |
| `sweagent/agent/agents.py:265-318` | `RetryAgent` 字段 / `_setup_agent` | `_attempt_data`（265）；`attempt_<i>` 子目录（315-318） |
| `sweagent/agent/agents.py:321-356` | `_next_attempt` / `_finalize_agent_run` | hard_reset + 子 agent 保存 + attempts append |
| `sweagent/agent/agents.py:358-381` | `RetryAgent.get_trajectory_data(choose)` | `attempts` 数组、`best_attempt_idx`、rloop stats |
| `sweagent/agent/agents.py:390-441` | `RetryAgent.run` | 每步 choose=False（415）、finalize（427）、retry（428-431）、最后 choose=True（432） |
| `sweagent/run/run_single.py:68-79` | `_get_default_output_dir` | 默认路径 `cwd/trajectories/<user>/<config>__<model>___<problem>` |
| `sweagent/run/run_single.py:83-96` | `RunSingleConfig` | replay_config 的运行时类型 |
| `sweagent/run/run_single.py:143-148` | log file handlers | 每实例日志落盘 |
| `sweagent/run/run_single.py:165-183` | `from_config` | `agent.replay_config = config`（170） |
| `sweagent/run/run_single.py:188-208` | `RunSingle.run` | `config.yaml` 写入（197）；`save_predictions`（206） |
| `sweagent/run/common.py:370-380` | `save_predictions` | `<id>.pred` = `{model_patch: info["submission"]}` |
| `sweagent/run/run_batch.py:99-117` | `set_default_output_dir` | batch 默认输出目录 |
| `sweagent/run/run_batch.py:200` | `run_batch.config.yaml` | batch 配置落盘 |
| `sweagent/run/run_batch.py:224-231` | `SweBenchEvaluate` hook 添加 | batch 内联评估入口 |
| `sweagent/run/run_batch.py:252` | `merge_predictions(... preds.json)` | 汇总预测 |
| `sweagent/run/run_batch.py:333-372` | `_run_instance` | `<id>.config.yaml`（343-345）；`agent.replay_config`（346）；`save_predictions`（372） |
| `sweagent/run/run_batch.py:376-409` | `should_skip` | 已有 `.traj` + exit_status 决定 skip/重跑；坏文件删除 |
| `sweagent/run/merge_predictions.py:13-46` | `merge_predictions` | `rglob("*.pred")`、重复 raise、写 preds.json |
| `sweagent/run/extract_pred.py:12-19` | `extract_pred` | 从 `.traj` 反推 `.pred` |
| `sweagent/run/remove_unfinished.py:13-44` | `remove_unfinished` | 按 `info.submission` 清理未完成运行 |
| `sweagent/run/hooks/apply_patch.py:76-90` | `_save_patch` | `<id>.patch` 落盘 |
| `sweagent/run/hooks/swe_bench_evaluate.py:43-72` | `_get_sb_call` | sb-cli 命令构造，输入是 preds 路径 |
| `sweagent/run/hooks/swe_bench_evaluate.py:74-123` | on_instance_completed / on_end / move_sb_cli_report | 评估提交与 `results.json` 产出 |
| `sweagent/run/run_replay.py:46-63` | `RunReplayConfig` | `traj_path`、deployment 覆盖、默认输出 `replay___<stem>` |
| `sweagent/run/run_replay.py:96-120` | `_get_config_from_agent` | 解析 `replay_config`（str/dict 兼容）；换 ReplayModel |
| `sweagent/run/run_replay.py:138-162` | `_create_actions_file` | 从 history 提取 assistant 动作 |
| `sweagent/run/run_replay.py:173-202` | `_get_env` / `main` | 新环境（post_startup_commands=[]）；重建 replay_config |
| `sweagent/agent/models.py:204-216` | `ReplayModelConfig` | replay 模型配置（`replay_path`） |
| `sweagent/agent/models.py:464-525` | `ReplayModel.query` | 按序重发动作；耗尽自动 submit |
| `sweagent/environment/swe_env.py:21-43` | `EnvironmentConfig` | 环境可重建规格 |
| `sweagent/environment/swe_env.py:128-147` | `hard_reset` / `reset` | attempt 间环境重建 |
| `sweagent/environment/repo.py:31-38` | `_get_git_reset_commands` | reset 到 base_commit 的命令 |
| `sweagent/environment/repo.py:165-181` | `GithubRepoConfig.copy` | clone 依赖 base_commit + GITHUB_TOKEN |
| `sweagent/utils/config.py:30-44` | `_strip_abspath_from_dict` | replay_config 路径相对化 |
| `sweagent/__init__.py:15` | `__version__ = "1.1.0"` | 研究版本 |
| `sweagent/__init__.py:46-47` | `TRAJECTORY_DIR` | batch 默认目录 + env 覆盖 |
| `docs/usage/trajectories.md:7-100` | trajectories 文档 | 文档与源码对照（旧示例 v0.7.0、preds/eval 独立） |
| `docs/usage/inspector.md:86-95` | inspector / results.json | 查看与评估结果展示 |
| `docs/usage/batch_mode.md:209-225` | preds.json | 评估入口文档 |
