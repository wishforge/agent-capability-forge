# Harbor ATIF Archaeology

> Baseline: `github.com/harbor-framework/harbor` `main` @ `ac398bbda7c4c1073461797d3b95c2455cc671b5` (2026-08-12). Local clone: `<tmp>/harbor-framework`. All paths below are repo-relative; all line numbers are from this commit.
>
> Tag convention: **[SPEC]** = RFC 0001 says it; **[IMPL]** = exists in current source; **[OPEN / SPEC-ONLY]** = written in RFC (or referenced there) but not implemented in the Pydantic models / runtime producers.

---

# 1. Executive Summary

ATIF (Agent Trajectory Interchange Format, RFC 0001, current v1.7) is a JSON schema for logging one agent execution as a **root `Trajectory` object**: agent configuration + an ordered `steps` array + optional metrics and subagent references. The reference implementation is a strict Pydantic model suite in `src/harbor/models/trajectories/`, with a file validator, runtime producers (Terminus 2, Claude Code, Codex, and other installed agents), consumers (viewer, dataset export, rewardkit, `harbor-atif2otel`), and a conversation-only replay path.

One execution is represented as:

`user/system step → agent step (message + reasoning + tool_calls) → observation (results keyed by source_call_id) → next agent step … → final answer`

where the "final answer" is simply the last `source: "agent"` step message; ATIF has **no dedicated final-answer / terminal-state field** ([IMPL] `harbor-atif2otel/src/harbor_atif2otel/convert.py:121-125`; RFC example `rfcs/0001-trajectory-format.md:385-462`).

Answers to the six questions:

**Q1. ATIF 的 root artifact 是什么？**
One JSON document validated by the Pydantic `Trajectory` model (`src/harbor/models/trajectories/trajectory.py:12-106`), normally persisted as `<trial>/agent/trajectory.json`. Required fields: `schema_version` (Literal `"ATIF-v1.0"`…`"ATIF-v1.7"`), `agent`, `steps` (min 1). Optional: `session_id`, `trajectory_id`, `notes`, `final_metrics`, `continued_trajectory_ref`, `extra`, `subagent_trajectories`.

**Q2. 一次 tool execution 的完整证据是什么？**
Within one agent step: `ToolCall.tool_call_id + function_name + arguments` and the matching `ObservationResult.source_call_id + content` in the same step's `observation.results`. The link is validated per-step by `Trajectory.validate_tool_call_references` (`trajectory.py:163-184`). Multiple tool calls per step are supported (`tool_calls: list[ToolCall]`).

**Q3. environment feedback 到底保存什么？**
Only an opaque `content` string (or `ContentPart[]`), optionally with `subagent_trajectory_ref` and producer-defined `extra`. There is **no first-class stdout / stderr / exit status / exit code field** anywhere in the schema ([SPEC] `rfcs/0001-trajectory-format.md:226-235`; [IMPL] `observation_result.py:11-42`). Those must go into `content` or `extra`.

**Q4. 文件/image/output 如何和 trajectory 关联？**
Images: separate files (or URLs) referenced by `ImageSource.path`; never base64-embedded ([SPEC] RFC:284-298; [IMPL] `content.py:11-25`). The file validator checks that local image paths exist (`trajectory_validator.py:50-104`). Other execution files are **not** part of ATIF; they live in the trial's separate `artifacts/` + `manifest.json` ([IMPL] `src/harbor/models/trial/paths.py:195-226`).

**Q5. trajectory 能不能独立 replay？**
Only as a **conversation seed, not a bit-for-bit environment replay**. `--load-trajectory` converts ATIF JSON to the target agent's native session format on the fly (`claude-code`, `codex`), restoring messages/tool calls/tool results but not files created by the original run ([IMPL] `docs/content/docs/run-jobs/load-trajectory.mdx:26-41`; `src/harbor/agents/installed/base.py:1044-1075`).

**Q6. 哪些设计值得 Capability Forge 直接借鉴？**
Versioned strict schema with `extra: forbid`; ordered steps with structured `tool_calls` + correlated observations; `source_call_id` validation; identity split (`session_id` run-scoped vs `trajectory_id` per-document); separate image files with existence validation; reward/evaluation kept **out** of the trajectory (in `result.json`); `is_copied_context` / `llm_call_count=0` for training-data hygiene; continuation chains via `continued_trajectory_ref`; fail-fast replay capability flags. Details in §12.

**A/B/C/D 边界（先给结论，证据见 §9-§10）:**

| Artifact | What it is | Where it lives |
| --- | --- | --- |
| A. Trajectory | Execution transcript (ATIF JSON) | `<trial>/agent/trajectory.json` (+ `trajectory.cont-N.json`, subagent files) |
| B. Execution Artifact | Files/images/verifier logs produced by the run | `<trial>/artifacts/`, `<trial>/verifier/`, referenced by path, never embedded |
| C. Evaluation Result | Rewards / scores / judge verdicts | `<trial>/result.json` (`TrialResult` + `VerifierResult.rewards`), `/logs/verifier/reward.{txt,json}` |
| D. Replay Configuration | Run-level "load this trajectory before first invocation" | `agent.load_trajectory` / `--load-trajectory` (`src/harbor/models/trial/config.py:110`) |

---

# 2. ATIF Root Object

**SPEC:** `rfcs/0001-trajectory-format.md:80-93` (root-level metadata), `:95-105` (AgentSchema), `:107-118` (FinalMetricsSchema).

**IMPL:** `src/harbor/models/trajectories/trajectory.py`

| Field | Type / default | Evidence |
| --- | --- | --- |
| `schema_version` | `Literal["ATIF-v1.0"…"ATIF-v1.7"]`, default `"ATIF-v1.7"` | `trajectory.py:15-27` |
| `session_id` | `str \| None = None`; run-scoped, may be shared across trajectory documents | `trajectory.py:28-45` |
| `trajectory_id` | `str \| None = None`; per-document id, required on embedded subagents | `trajectory.py:46-60` |
| `agent` | `Agent` (required) | `trajectory.py:61-64`; `agent.py:8-32` |
| `steps` | `list[Step]`, `min_length=1` | `trajectory.py:65-69` |
| `notes` | `str \| None` | `trajectory.py:70-73` |
| `final_metrics` | `FinalMetrics \| None` | `trajectory.py:74-77`; `final_metrics.py:8-40` |
| `continued_trajectory_ref` | `str \| None` (next continuation file) | `trajectory.py:78-81` |
| `extra` | `dict[str, Any] \| None` (custom root metadata) | `trajectory.py:82-85` |
| `subagent_trajectories` | `list[Trajectory] \| None` (embedded subagents, v1.7) | `trajectory.py:86-104` |

Strictness: `model_config = {"extra": "forbid"}` on `Trajectory` (`trajectory.py:106`) and on every nested model. Arbitrary producer metadata must go into `extra`, never new top-level keys — the validator converts unknown keys into errors (`src/harbor/utils/trajectory_validator.py:164-167`).

Serialization: `Trajectory.to_json_dict(exclude_none=True, mode="json")` (`trajectory.py:108-117`) is the single export path used by producers.

Agent config: `name` + `version` required; `model_name`, `tool_definitions` (OpenAI function-calling shape), `extra` optional (`src/harbor/models/trajectories/agent.py:8-32`; [SPEC] RFC:95-105).

---

# 3. Step Data Model

**SPEC:** RFC:120-142 (StepObject, incl. `llm_call_count` and `is_copied_context` normative rules).

**IMPL:** `src/harbor/models/trajectories/step.py:14-91`

| Field | Notes | Evidence |
| --- | --- | --- |
| `step_id` | `int`, `ge=1`, sequential from 1 enforced at root | `step.py:17-21`; `trajectory.py:119-129` |
| `timestamp` | ISO 8601 string, validated | `step.py:22-25`, `step.py:93-102` |
| `source` | `Literal["system","user","agent"]` | `step.py:26-29` |
| `model_name` | agent-only | `step.py:30-36` |
| `reasoning_effort` | `str \| float`, agent-only | `step.py:37-40` |
| `message` | `str \| list[ContentPart]` (multimodal since v1.6) | `step.py:41-47` |
| `reasoning_content` | agent-only | `step.py:48-51` |
| `tool_calls` | `list[ToolCall] \| None`, agent-only | `step.py:52-55` |
| `observation` | `Observation \| None` | `step.py:56-59` |
| `metrics` | `Metrics \| None`, agent-only | `step.py:60-63` |
| `is_copied_context` | `True` ⇒ must be filtered from SFT data | `step.py:64-73`; RFC:138-140 |
| `llm_call_count` | `0` on agent step = deterministic dispatch; `metrics`/`reasoning_content` forbidden then | `step.py:74-85`; RFC:137,142 |
| `extra` | step-level custom metadata | `step.py:86-89` |

Validators: agent-only field enforcement (`step.py:104-121`), `llm_call_count == 0` rule (`step.py:123-138`), `extra: forbid` (`step.py:91`).

**How one execution is represented (user → agent → tool → observation → next agent → final answer):**

- Step 1 is typically `source: "user"` (or `"system"` for the injected system/task prompt). Terminus 2 builds system/user steps from chat history (`terminus_2.py:1802-1860`).
- Each agent turn is one step with `message` (+ optional `reasoning_content`), `tool_calls`, and `observation` in the same step ([IMPL] `terminus_2.py:1430-1526`; RFC example `0001-trajectory-format.md:385-462`).
- The final answer is just the last `source: "agent"` step's `message`; there is no terminal field. Downstream tooling derives it by scanning backwards (`harbor-atif2otel/src/harbor_atif2otel/convert.py:121-125`). Terminus 2 marks task completion with a synthetic `mark_task_complete` tool call (`terminus_2.py:1467-1475`).

---

# 4. ToolCall Data Model

**SPEC:** RFC:144-153.

**IMPL:** `src/harbor/models/trajectories/tool_call.py:8-31`

| Field | Type | Notes | Evidence |
| --- | --- | --- | --- |
| `tool_call_id` | `str` (required) | correlation key with observation | `tool_call.py:11-14` |
| `function_name` | `str` (required) | tool/function name | `tool_call.py:15-18` |
| `arguments` | `dict[str, Any]` (required, may be `{}`) | | `tool_call.py:19-22` |
| `extra` | `dict \| None` | v1.7 custom metadata (timeout, retry, version) | `tool_call.py:23-29` |

**Result correlation:** `ObservationResult.source_call_id` must reference a `tool_call_id` from the **same step's** `tool_calls`; enforced by `Trajectory.validate_tool_call_references` (`trajectory.py:163-184`). `source_call_id = None` is allowed for non-standard actions / system-initiated operations ([SPEC] RFC:232; [IMPL] `observation_result.py:14-22`).

**Multiple tool calls:** yes. `tool_calls` is a list ([IMPL] `step.py:52-55`; [SPEC] RFC:133), the RFC example shows two simultaneous calls (`RFC:401-423`), and the validator collects the whole set before checking refs (`trajectory.py:170-183`).

**Producer reality check (Terminus 2):** one `ToolCall` per parsed bash command, with ids `call_{episode}_{i+1}` and `arguments = {keystrokes, duration}` (`terminus_2.py:1441-1453`). It is honest about batch linkage: when a step has multiple commands sharing one terminal output, the observation's `source_call_id` is `None` (`_terminal_observation_source_call_id`, `terminus_2.py:61-66`; usage at `terminus_2.py:1457-1464`).

**Interop:** installed-agent exporters convert native events into `ToolCall` (e.g., `codex.py:1144-1155`, `claude_code.py:1478-1491`); the replay converters render `tool_call_id`/`function_name`/`arguments` back into native tool events (`claude_code.py:293-302`, `codex.py:168-178`).

---

# 5. Observation Data Model

**SPEC:** RFC:218-261 (ObservationSchema, ObservationResultSchema).

**IMPL:**

- `Observation` = `{ results: list[ObservationResult] }`, `extra: forbid` (`observation.py:8-16`).
- `ObservationResult` (`observation_result.py:11-42`):
  - `source_call_id: str | None` — link to a `ToolCall` in the same step, or `None` for non-tool actions / system events (`observation_result.py:14-22`).
  - `content: str | list[ContentPart] | None` — the tool/action output (`observation_result.py:23-29`).
  - `subagent_trajectory_ref: list[SubagentTrajectoryRef] | None` — delegation refs (`observation_result.py:30-33`).
  - `extra: dict | None` — v1.7 custom result metadata (confidence, retrieval score, source doc id) (`observation_result.py:34-40`).

**What environment feedback actually stores:**

- Terminal output → one `content` string. Terminus 2: `observation_results.append(ObservationResult(source_call_id=…, content=observation))` (`terminus_2.py:1457-1464`).
- Parse errors → `ObservationResult(content=prompt)` with no `source_call_id` (`terminus_2.py:1376-1382`).
- No-command/no-completion turns → `ObservationResult(content=observation)` (`terminus_2.py:1483-1489`).
- System-initiated events (context compaction) → system step with an observation carrying subagent refs and `extra.context_management` (`terminus_2.py:1293-1315`; RFC:572-613).

**What it does NOT store:** `stdout`, `stderr`, `exit_code`, `exit_status` are not schema fields. A repo-wide search for these in `src/harbor/models/trajectories/` and the RFC finds only the example "exit status" under subagent-ref `extra` (RFC:308). Producers that need them must embed them in `content` or `extra`. Example: Claude Code's exporter keeps native tool-result metadata in `result.extra.tool_result_metadata.raw_tool_result` (`claude_code.py:225-232`).

---

# 6. Artifact / File / Image Boundary

**Design rule ([SPEC] RFC:286-298):** images are stored as separate files (conventionally an `images/` subdirectory next to `trajectory.json`) or URLs, referenced by path. Base64 embedding is explicitly avoided.

**IMPL:**

- `ImageSource { media_type: Literal["image/jpeg","image/png","image/gif","image/webp"], path: str }` — path may be relative, absolute, or URL (`content.py:11-25`).
- `ContentPart { type: Literal["text","image"], text?, source? }` with conditional validation (`content.py:28-48`, validator `content.py:50-62`).
- `Trajectory.has_multimodal_content()` scans steps for image parts (`trajectory.py:186-203`).
- The file validator resolves relative image paths against the trajectory's directory and errors when a local file does not exist; URLs are skipped (`trajectory_validator.py:38-48`, `:50-104`, `:198-200`).

**Non-image execution files are outside ATIF entirely.** The trial keeps them in `trial_dir/artifacts/` with `manifest.json` recording source paths (`src/harbor/models/trial/paths.py:195-226`); verifier logs go to `trial_dir/verifier/` (`paths.py:228-265`). ATIF references only images (and, via `extra`/`trajectory_path`, arbitrary strings).

**Custom metadata:** `extra` exists at root (`trajectory.py:82-85`), agent (`agent.py:27-30`), step (`step.py:86-89`), tool call (`tool_call.py:23-29`), observation result (`observation_result.py:34-40`), per-step metrics (`metrics.py:39-42`), final metrics (`final_metrics.py:35-38`), and subagent ref (`subagent_trajectory_ref.py:61-64`).

---

# 7. Identity Model

**`session_id` — run-scoped, optional since v1.7 ([IMPL] `trajectory.py:28-45`; [SPEC] RFC:85).**

Lifecycle in the reference producer:

1. Terminus 2: `self._session_id = self._user_provided_session_id or str(uuid.uuid4())` at run start (`terminus_2.py:1556`); subagent runs get derived ids like `{session}-summarization-{n}-summary|questions|answers` (`terminus_2.py:792-875`); continuation segments get `{base}-cont-{n}` (`terminus_2.py:1875-1878`).
2. Harbor trial runner overrides the agent's session id: `self.agent.session_id = f"{self.config.trial_name}__agent"` (`trial/trial.py:849`).
3. Installed-agent exporters use the native session id when writing ATIF (`claude_code.py:1480`, `codex.py:1146`).
4. Downstream, `harbor-atif2otel` strips `-cont-N` to build a stable trace id (`harbor-atif2otel/src/harbor_atif2otel/ids.py:18-20`, `:23-42`).

**`trajectory_id` — per-document, optional on standalone roots, REQUIRED + unique on embedded subagents ([IMPL] `trajectory.py:46-60`, `:131-161`; [SPEC] RFC:86,93).**

`trajectory_id` was added in v1.7 to make embedded-subagent refs resolvable without overloading `session_id` ([SPEC] RFC:299-317). **No Harbor runtime producer sets `trajectory_id` today**: a source search for `trajectory_id=` in `src/harbor` finds only the model definitions and validators. The embedded `subagent_trajectories` array is therefore supported by the schema, validators, and `harbor-atif2otel` consumers, but is **OPEN / SPEC-ONLY as a producer path**.

**`step_id` — ordinal, 1-based, sequential per document ([IMPL] `step.py:17-21`; `trajectory.py:119-129`).** Embedded subagents restart at 1 with their own sequence ([SPEC] RFC:93; test `tests/unit/models/test_trajectory.py:34-61`).

**Root/trial identity is separate from ATIF:** `TrialResult.id` (UUID), `trial_name`, `task_checksum`, `agent_info`, `config` (`src/harbor/models/trial/result.py:70-98`); trace export rows use `run_id`, `episode`, `trial_name` (`src/harbor/utils/traces_utils.py:15-36`).

---

# 8. Subagent Trajectory Model

**SPEC:** RFC:299-321 (SubagentTrajectoryRefSchema and resolution rules), RFC:93 (root `subagent_trajectories`).

**IMPL:** `src/harbor/models/trajectories/subagent_trajectory_ref.py:8-85`

| Field | Semantics | Evidence |
| --- | --- | --- |
| `trajectory_id` | Embedded-form resolution key; matches an entry in parent's `subagent_trajectories` | `subagent_trajectory_ref.py:29-38` |
| `session_id` | **Informational only**; run-scoped, never a resolution key | `subagent_trajectory_ref.py:39-49`; RFC:307,317 |
| `trajectory_path` | File-ref-form resolution key (file path, S3 URL, DB ref…) | `subagent_trajectory_ref.py:50-60` |
| `extra` | custom metadata (e.g. summary) | `subagent_trajectory_ref.py:61-64` |

Validator: a ref MUST set `trajectory_id` or `trajectory_path`; `session_id` alone fails (`subagent_trajectory_ref.py:68-84`). `content` may be omitted when a ref is present ([SPEC] RFC:321).

**Two resolution mechanisms:**

1. Embedded: `SubagentTrajectoryRef.trajectory_id` ↔ `Trajectory.trajectory_id` in `parent.subagent_trajectories` (self-referential list type, `trajectory.py:86-104`; uniqueness validator `trajectory.py:131-161`).
2. File-ref: `trajectory_path` points at a complete external ATIF file.

Both forms may be mixed ([SPEC] RFC:93). Consumers may choose either when both are set ([SPEC] RFC:315).

**What the production code actually does:** Terminus 2's summarization subagents are saved as **external files** (`trajectory.summarization-{n}-{suffix}.json`) and referenced with `session_id` + `trajectory_path` + `extra.summary` (`terminus_2.py:1735-1800`). The parent records the delegation as a **system step** observation carrying the refs (`terminus_2.py:1293-1315`). No runtime producer populates the embedded `subagent_trajectories` array — **OPEN / SPEC-ONLY** (consumers exist: `harbor-atif2otel/.../convert.py:144-150`, `:197`; tests `tests/unit/models/test_trajectory.py:32-253`).

`session_id` vs `trajectory_id`: siblings in the same logical run may share `session_id` (parent + subagents, continuations), so it cannot disambiguate; `trajectory_id` is the document-unique key (RFC:317; `trajectory.py:28-60`).

---

# 9. Metrics / Evaluation Boundary

**Per-step `Metrics` ([IMPL] `metrics.py:8-44`):**

| Field | Semantics |
| --- | --- |
| `prompt_tokens` | total input incl. cached ([SPEC] RFC:161-163) |
| `completion_tokens` | generated tokens |
| `cached_tokens` | subset of prompt_tokens that were cache hits |
| `cost_usd` | cost snapshot at execution time; no pricing table stored (RFC:198-204) |
| `prompt_token_ids` / `completion_token_ids` | token IDs to avoid retokenization drift for RL/SFT (RFC:165-166) |
| `logprobs` | per-completion-token logprobs (RFC:167) |
| `extra` | provider-specific metrics (e.g. `reasoning_tokens`, `cache_creation_input_tokens`) |

**`FinalMetrics` ([IMPL] `final_metrics.py:8-40`):** `total_prompt_tokens`, `total_completion_tokens`, `total_cached_tokens`, `total_cost_usd`, `total_steps` (may differ from `len(steps)` only if explained in `notes`, `final_metrics.py:27-34`), `extra`.

**Reward:**

- RFC says metrics "including RL-specific fields (reward, logprobs) if applicable" (RFC:135) and the comparison table mentions an optional `rl_experience (reward, log_probs)` (RFC:334). **No `reward` field exists in `Metrics` or `FinalMetrics`, and no `rl_experience` exists anywhere in `src/` or `packages/`.** → **OPEN / SPEC-ONLY** (the RFC mention is not even a defined schema section).
- Evaluation results are deliberately separated from the trajectory document: `VerifierResult.rewards: dict[str, float | int]` (`src/harbor/models/verifier/result.py:4-7`) is attached to `TrialResult.verifier_result` / `StepResult.verifier_result` (`src/harbor/models/trial/result.py:61-97`) and persisted to `<trial>/result.json` (`trial/trial.py:419`; `src/harbor/models/trial/paths.py:267-270`). Verifiers also emit `/logs/verifier/reward.txt` / `reward.json` (`paths.py:42-43`, `:252-265`).
- Consumers read rewards from `result.json`, not from the trajectory (`src/harbor/utils/traces_utils.py:398+`; `trial/regrade.py:246-251`).

**ATIF as evaluation input:** rewardkit formats trajectory JSON into a compact judge prompt (`packages/rewardkit/src/rewardkit/trajectory.py:77-133`) and reads `/logs/trajectory.json` directly for criteria such as tool-use checks (`packages/rewardkit/src/rewardkit/criteria/trajectory_tool_used.py:9-21`; `_trajectory.py:10-32`). The verdict lands back in the trial result, not in the trajectory file.

---

# 10. Persistence / Replay

**Who writes:**

- Terminus 2: `_dump_trajectory()` → `_dump_trajectory_with_continuation_index()` constructs a `Trajectory` and writes `logs_dir/trajectory.json` (or `trajectory.cont-N.json` in linear-history mode) via `format_trajectory_json(trajectory.to_json_dict())` (`terminus_2.py:1889-1959`); it dumps after every episode so a crash still leaves a file (`terminus_2.py:1528-1529`).
- Claude Code: `populate_context_post_run` converts the native session and writes `logs_dir/trajectory.json` (`claude_code.py:1493-1517`).
- Codex: same pattern (`codex.py:1159-1186`). Also `vibe.py:838-841`, `openclaw.py:851-854`, `cortex_code.py:738-741`, `grok_build.py:1056-1059`, `eve.py:997`, `dspy_rlm.py:355`.
- Upload: the trial archive is uploaded, plus a direct `trials/{trial_id}/trajectory.json`, and the path is recorded via `finalize_trial_artifacts(..., trajectory_path=...)` (`src/harbor/upload/uploader.py:623-658`). CLI download: `src/harbor/cli/hub.py:1128-1163`.

**Who reads / how it is validated:**

- Viewer API serves `agent/trajectory.json` raw (`src/harbor/viewer/server.py:2449-2472`).
- Trace extraction discovers only trials with `agent/trajectory.json`, follows `continued_trajectory_ref` chains, and skips subagent files (`src/harbor/utils/traces_utils.py:800-829`).
- Rewardkit criteria read `/logs/trajectory.json` inside the verifier environment (`trajectory_tool_used.py:14`).
- `harbor-atif2otel` validates then converts a trajectory to OpenTelemetry `ResourceSpans`, with deterministic trace/span ids from `session_id`/`trajectory_id` (`harbor-atif2otel/src/harbor_atif2otel/validate.py:6-76`; `convert.py:173-220`; `ids.py:8-55`). It filters `is_copied_context` steps before conversion (`convert.py:189-194`).
- `TrajectoryValidator` (Pydantic + image-path checks) is the canonical offline validator and CLI (`src/harbor/utils/trajectory_validator.py:106-202`, `:226-285`).

**Replay:**

- `--load-trajectory` is run-level (`src/harbor/models/trial/config.py:110`; `src/harbor/cli/jobs.py:587-590`), not part of the task. `.json` selects ATIF; `.jsonl` selects native (`docs/content/docs/run-jobs/load-trajectory.mdx:13`).
- Capability flags: `SUPPORTS_LOAD_NATIVE_TRAJECTORY` / `SUPPORTS_LOAD_ATIF_TRAJECTORY` (`src/harbor/agents/base.py:51-52`); today only `claude-code` and `codex` support both (`claude_code.py:44-45`, `codex.py:48-49`).
- ATIF is parsed with `Trajectory.model_validate_json` at construction (`src/harbor/agents/installed/base.py:967-989`); the trial fails fast before environment spend if the agent cannot honor the format (`trial/trial.py:853-870`).
- Conversion: `_seed_load_trajectory` → `atif_to_native_trajectory(trajectory, session_id)` produces a native Claude Code JSONL transcript (`claude_code.py:235-244`) or Codex rollout JSONL (`codex.py:168-178`); native file uploaded into the environment, then the agent resumes (`base.py:1044-1063`).
- What is restored: **only the conversation** — full prior message history as context; files created by the original run do not exist in the new environment (docs:37-41). Multi-step tasks load before step 1 only (`src/harbor/trial/multi_step.py:441`; docs:41).
- Example: `examples/tasks/hello-load-atif-trajectory/` demonstrates one ATIF file seeding either Claude Code or Codex (`task.toml:6-10`).

**Conclusion on replay:** ATIF is replayable as a *conversation seed* with conversion, not as a bit-for-bit execution replay. There is no stored environment snapshot, filesystem state, or command replay within ATIF itself.

---

# 11. Validation Rules

**Pydantic model validators (reference implementation):**

| Rule | Evidence |
| --- | --- |
| `schema_version` must be one of `ATIF-v1.0`…`ATIF-v1.7` | `trajectory.py:15-27` |
| `steps` non-empty | `trajectory.py:65-69` |
| `step_id` sequential from 1 (per document) | `trajectory.py:119-129` |
| embedded `subagent_trajectories`: `trajectory_id` required and unique | `trajectory.py:131-161` |
| `observation.results[].source_call_id` must exist in the same step's `tool_calls` | `trajectory.py:163-184` |
| step `timestamp` is ISO 8601 | `step.py:93-102` |
| `model_name`/`reasoning_effort`/`reasoning_content`/`tool_calls`/`metrics` only on `source: "agent"` | `step.py:104-121` |
| `llm_call_count == 0` on agent step ⇒ no `metrics`/`reasoning_content` | `step.py:123-138` |
| `ContentPart`: `type=text` ⇒ `text` required, `source` forbidden; `type=image` ⇒ `source` required, `text` forbidden | `content.py:50-62` |
| `SubagentTrajectoryRef` must set `trajectory_id` or `trajectory_path` | `subagent_trajectory_ref.py:68-84` |
| unknown fields rejected everywhere (`extra: forbid`) | each model's `model_config` |

**File/schema validator:** `TrajectoryValidator.validate()` collects all Pydantic errors plus local image-path existence checks (`trajectory_validator.py:50-104`, `:106-202`); CLI at `:226-285`. A second, dict-based consumer validator lives in `harbor-atif2otel/.../validate.py:6-76` (also enforces embedded `trajectory_id` uniqueness).

**Tests:** `tests/unit/models/test_trajectory.py` (embedded subagents, id rules, ref resolution), `tests/unit/test_trajectory_validator.py`, `tests/integration/test_trajectory_validation.py` (golden `*.trajectory.json` files), `tests/unit/trial/test_load_trajectory_validation.py`, installed-agent trajectory round-trip tests.

---

# 12. Capability Forge Relevance

Directly reusable design decisions (each with evidence):

1. **Versioned, strict schema.** A `schema_version` literal plus `extra: forbid` on every model makes format drift a validation error, not silent data corruption (`trajectory.py:15-27`, `:106`; `trajectory_validator.py:164-167`). Forge should ship its own versioned artifact schema with the same strictness.
2. **Minimal root + ordered steps.** Root = agent config + steps + optional metrics/refs; everything else is `extra`. This is enough for SFT, RL, viewing, and judging (RFC:14; `trajectory.py:12-106`).
3. **Tool call ↔ observation correlation in the same step, validated.** `source_call_id` + same-step reference check (`trajectory.py:163-184`) gives an auditable, machine-checkable evidence link per tool execution; multiple parallel calls are expressible (`tool_call.py:11-22`).
4. **Honest linkage degradation.** Terminus 2 sets `source_call_id=None` when a batch of commands shares one output rather than lying about which call produced it (`terminus_2.py:61-66`, `:1455-1464`). Forge should keep the same "unknown mapping" semantics instead of fabricating per-call results.
5. **Artifact boundary: references, not blobs.** Images are separate files with path/URL + media_type, and the validator checks existence (`content.py:11-25`; `trajectory_validator.py:50-104`). Keeps the transcript small and the artifact store addressable.
6. **Identity split.** Run-scoped `session_id` (may be shared by parent/subagents/continuations) vs per-document `trajectory_id` (required for embedded refs) (`trajectory.py:28-60`); continuation chains via `continued_trajectory_ref` (`trajectory.py:78-81`; `traces_utils.py:808-829`). Forge should not overload one id field for both run and document identity.
7. **Evaluation is separated from the transcript.** Trajectory files carry no reward; rewards live in `result.json` / `VerifierResult` (`verifier/result.py:4-7`; `models/trial/result.py:61-97`; `trial/trial.py:419`). This keeps one trajectory reusable across SFT, RL, and multiple judges, and avoids reward contamination. This matches the user's prior principle: trajectory validity and reward trustworthiness are separate gates.
8. **Training-data hygiene flags.** `is_copied_context=True` must be filtered by consumers (`step.py:64-73`; RFC:138-140; `atif2otel/convert.py:189-194`), and `llm_call_count=0` marks deterministic dispatches that SFT must drop (`step.py:123-138`; RFC:137). Forge's RL data pipeline needs the same explicit markers rather than heuristic detection.
9. **Context-management convention.** `step.extra.context_management {type, boundary}` lets downstream evaluation reconstruct the effective context after compaction/pruning/injection (`RFC:572-613`; producer `terminus_2.py:1293-1315`).
10. **Replay capability flags + fail-fast.** Agents declare `SUPPORTS_LOAD_*`, unsupported agents fail before environment spend (`agents/base.py:51-52`; `trial/trial.py:853-870`). Replay = conversation seed via format conversion, explicitly scoped and documented (`load-trajectory.mdx:26-41`).
11. **Downstream interchange.** `harbor-atif2otel` maps ATIF → OTel spans with deterministic ids (`ids.py:8-55`; `convert.py:173-220`) — a cheap observability bridge when a format must feed tracing, not just training.

---

# 13. What We Should NOT Copy

1. **No first-class stdout/stderr/exit status.** ATIF forces tool feedback into one opaque string or ad-hoc `extra`, so structured shell evidence (exit codes, stream separation, command timing) is lost unless every producer reinvents it (`observation_result.py:11-42`; RFC:226-235). Forge should model structured tool results from day one (or standardize the `extra` convention).
2. **No terminal-state / final-answer field.** The "final answer" is an implicit convention (last agent step; `atif2otel/convert.py:121-125`), and termination is producer-specific (`mark_task_complete` in Terminus 2 only, `terminus_2.py:1467-1475`). Forge should make final answer / termination explicit in its own artifact schema.
3. **RFC/implementation drift on reward.** RFC:135 and RFC:334 promise reward/`rl_experience` inside metrics; the implementation has no such field. Copying the RFC text without the models would reproduce a spec that cannot be validated (`metrics.py:8-44`). Keep reward strictly out of the trajectory, or define and implement it fully.
4. **Spec-supported but producer-unused features.** `trajectory_id` and embedded `subagent_trajectories` are fully modeled and validated but no Harbor producer writes them (`trajectory.py:86-104`; no `subagent_trajectories=` in `src/harbor` outside models). Do not ship a feature whose only consumers are tests and converters; either produce it or mark it unimplemented.
5. **Weak root identity.** `trajectory_id` is optional on standalone trajectories, and `session_id` can collide by design (`trajectory.py:28-60`); the format depends on external trial metadata for unique roots. Forge should require a document id at the boundary where it needs one.
6. **Filename-encoded continuation/subagent references.** `continued_trajectory_ref` and subagent `trajectory_path` are relative filenames (`terminus_2.py:1922-1926`, `:1781-1799`); broken refs are only caught when consumers follow them (`traces_utils.py:824-829`). Prefer explicit ids + checksums/registry.
7. **No content size limits.** A tool result or image can be arbitrarily large in `content` (`observation_result.py:23-29`); the only truncation happens at consume time (`rewardkit/trajectory.py:16-23`). Forge should cap/truncate at write time with an explicit marker.
8. **Replay is conversation-only.** ATIF has no environment/filesystem snapshot, so "replay" cannot reproduce the original run (`load-trajectory.mdx:37-41`). If Forge needs real execution replay, it must add environment state/commands separately; do not let "replayable" mean only "resumable conversation".
9. **Trajectory ≠ capability artifact.** ATIF is an execution transcript. Harbor keeps capabilities/tasks/verifiers outside the trajectory (`models/trial/result.py:70-98`; task config). Forge should not conflate one execution's transcript with a reusable capability definition, evaluation verdict, or training sample.

---

# 14. Evidence Index

Baseline: `main` @ `ac398bbda7c4c1073461797d3b95c2455cc671b5` (2026-08-12). Clone: `<tmp>/harbor-framework`.

| Path | Key lines | What it proves |
| --- | --- | --- |
| `rfcs/0001-trajectory-format.md` | 76-321 | Full ATIF v1.7 spec: root, agent, step, tool, metrics, observation, content/image, subagent refs |
| `rfcs/0001-trajectory-format.md` | 336-464 | Canonical multi-tool-call execution example |
| `rfcs/0001-trajectory-format.md` | 572-613 | `context_management` convention |
| `src/harbor/models/trajectories/trajectory.py` | 12-106 | Root `Trajectory` fields, id semantics, embedded subagents |
| `src/harbor/models/trajectories/trajectory.py` | 119-184 | Step-id, embedded-id, tool-call-reference validators |
| `src/harbor/models/trajectories/step.py` | 14-139 | Step model + agent-only / `llm_call_count=0` / timestamp validators |
| `src/harbor/models/trajectories/tool_call.py` | 8-31 | `ToolCall` fields |
| `src/harbor/models/trajectories/observation.py` | 8-16 | `Observation.results` |
| `src/harbor/models/trajectories/observation_result.py` | 11-42 | `source_call_id`, `content`, subagent refs, `extra` |
| `src/harbor/models/trajectories/content.py` | 11-62 | `ImageSource`/`ContentPart` + conditional validator |
| `src/harbor/models/trajectories/metrics.py` | 8-44 | Per-step token/cost/logprob metrics; no reward field |
| `src/harbor/models/trajectories/final_metrics.py` | 8-40 | Aggregate metrics |
| `src/harbor/models/trajectories/subagent_trajectory_ref.py` | 8-85 | Embedded vs file-ref resolution, session_id informational |
| `src/harbor/utils/trajectory_validator.py` | 50-202, 226-285 | File/schema/image-path validation + CLI |
| `src/harbor/agents/terminus_2/terminus_2.py` | 1430-1526 | Producer: tool_calls + observation in agent steps |
| `src/harbor/agents/terminus_2/terminus_2.py` | 1735-1800 | Producer: external-file subagent trajectories + refs |
| `src/harbor/agents/terminus_2/terminus_2.py` | 1889-1959 | Producer: trajectory.json / continuation file writing |
| `src/harbor/agents/terminus_2/terminus_2.py` | 1556, 1875-1878 | `session_id` lifecycle and `-cont-N` suffix |
| `src/harbor/agents/installed/claude_code.py` | 1478-1517, 225-244 | ATIF export + ATIF→native conversion |
| `src/harbor/agents/installed/codex.py` | 1144-1186, 168-178 | ATIF export + ATIF→Codex rollout conversion |
| `src/harbor/agents/installed/base.py` | 967-1075 | ATIF load validation, seeding, capability flags |
| `src/harbor/agents/base.py` | 51-52 | `SUPPORTS_LOAD_*` capability declarations |
| `src/harbor/trial/trial.py` | 849, 853-870 | Trial session id override; fail-fast load support |
| `src/harbor/models/trial/result.py` | 61-98 | `TrialResult`/`StepResult`; rewards on verifier result |
| `src/harbor/models/verifier/result.py` | 4-7 | `VerifierResult.rewards` |
| `src/harbor/models/trial/paths.py` | 195-270 | Artifacts manifest, verifier logs, reward files, result.json |
| `src/harbor/trial/trial.py` | 419 | Persists `result.json` |
| `src/harbor/upload/uploader.py` | 623-658 | Uploads archive + direct trajectory.json |
| `src/harbor/viewer/server.py` | 2449-2472 | Viewer reads `agent/trajectory.json` |
| `src/harbor/utils/traces_utils.py` | 15-36, 398+, 800-829 | Dataset export; result.json rewards; continuation chain |
| `packages/rewardkit/src/rewardkit/trajectory.py` | 77-133 | Trajectory → judge prompt formatting |
| `packages/rewardkit/src/rewardkit/criteria/trajectory_tool_used.py` | 9-21 | Evaluator reads `/logs/trajectory.json` |
| `packages/harbor-atif2otel/src/harbor_atif2otel/validate.py` | 6-76 | Dict-level ATIF validation incl. embedded trajectory_id |
| `packages/harbor-atif2otel/src/harbor_atif2otel/convert.py` | 121-125, 173-220 | Final answer convention; OTel conversion |
| `packages/harbor-atif2otel/src/harbor_atif2otel/ids.py` | 8-55 | Deterministic trace/span ids; `-cont-N` stripping |
| `docs/content/docs/run-jobs/load-trajectory.mdx` | 6-41 | Replay semantics: conversation-only, ATIF vs native |
| `examples/tasks/hello-load-atif-trajectory/` | task.toml, environment/trajectory.json | Cross-agent ATIF replay example |
| `tests/unit/models/test_trajectory.py` | 32-253 | Embedded subagent semantics and validation tests |
| `tests/integration/test_trajectory_validation.py` | 19-28 | Golden trajectory validation |

