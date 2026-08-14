# Harbor Runtime Adapter Archaeology

> Baseline: `github.com/harbor-framework/harbor` `main` @ `ac398bbda7c4c1073461797d3b95c2455cc671b5` (2026-08-12). Local clone: `<tmp>/harbor-framework`. All paths are repo-relative; all line numbers are from this commit.
>
> Scope: how Codex / Claude Code / SWE-agent (and other installed agents) plug into Harbor's runtime-neutral core. ATIF schema internals are deliberately not repeated here — see `harbor-atif-archaeology.md` for the trajectory data model.
>
> Tag convention: **[IMPL]** = exists in current source.

---

# 1. Executive Summary

Harbor treats an Agent Runtime as a **black box behind a five-method contract**. Harbor Core never imports Codex, Claude Code, or SWE-agent types; it only sees `BaseAgent`/`BaseInstalledAgent` instances, an `AgentContext` value object, and a `trajectory.json` file in ATIF. Each runtime adapter owns everything runtime-specific: installation, CLI invocation, native-log parsing, and native↔ATIF conversion.

Answers to the eight questions:

| # | Question | Answer |
| --- | --- | --- |
| 1 | Harbor Core 是否依赖 Codex 类型？ | **No.** The only reference is a string `"codex"` in the `AgentName` enum and a string import path `"harbor.agents.installed.codex:Codex"` in `AgentFactory._AGENT_MAP`. No production code outside `codex.py` imports the `Codex` class ([IMPL] `src/harbor/models/agent/name.py:15`; `src/harbor/agents/factory.py:34`). |
| 2 | Codex-specific logic 在哪里？ | One file: `src/harbor/agents/installed/codex.py` (1481 lines). It contains Codex CLI flags, `codex exec` command construction, auth/config handling, rollout JSONL→ATIF conversion, and trajectory loading. Nothing else in Harbor Core knows these details. |
| 3 | Adapter 的统一接口是什么？ | `BaseAgent` (abstract: `name`, `version`, `setup`, `run`) plus capability flags; `BaseInstalledAgent` adds `install`, declarative `CLI_FLAGS`/`ENV_VARS`, error classification, and native↔ATIF conversion hooks ([IMPL] `src/harbor/agents/base.py:21-264`; `src/harbor/agents/installed/base.py:310-1098`). |
| 4 | Adapter 最终输出什么？ | (a) `AgentContext` (tokens/cost, optional `rollout_details`/`metadata`), (b) `<trial>/agent/trajectory.json` in ATIF, (c) native log files (sessions, stdout transcripts), (d) `AgentInfo` via `to_agent_info()`. |
| 5 | Harbor Core 消费什么？ | Only the interface: `setup/run/resume/load/populate_context_post_run`, capability flags, `AgentContext`, `AgentInfo`, and the ATIF file at `<trial>/agent/trajectory.json`. |
| 6 | 替换 Codex 是否需要修改 Harbor Core？ | **No.** Swap `--agent codex` for `--agent claude-code`, `--agent swe-agent`, `--agent acp:<id>`, or `--agent my.module:MyAgent`. Core code paths are identical. |
| 7 | 添加一个新 Runtime 最少改哪些地方？ | One file: `src/harbor/agents/installed/<name>.py` implementing `BaseInstalledAgent`; run it via `--agent <module.path>:<Class>` with **zero source changes**, or add 2 lines (enum + factory map) for a first-class `--agent <name>` ([IMPL] `AGENTS.md:339-343`). |
| 8 | Runtime adapter 与 ATIF 的关系是什么？ | The adapter is the **only ATIF producer and consumer**. It converts its native transcript (Codex rollout JSONL, Claude stream-json, SWE-agent `.traj`, ACP events) into `trajectory.json` and, for load/resume, converts ATIF back to the runtime's native session format. Harbor Core never parses native formats. |

---

# 2. Runtime-neutral Boundary Diagram

```
User / CLI / SDK / config.json
        │
        ▼
AgentConfig (runtime-neutral: name | import_path | model_name | env | kwargs | skills)
   src/harbor/models/trial/config.py:61
        │
        ▼
AgentFactory._AGENT_MAP: AgentName → "module.path:Class" string        (factory.py:25-72)
   └─ on-demand import via import_class()                              (factory.py:74-84)
   └─ custom agent: name containing ":" is treated as import_path      (factory.py:147-153)
   └─ "acp:<id>[@version]" resolves to the generic AcpAgent            (factory.py:155-174)
        │
        ▼
╔════════════════════════════════════════════════════════════════════╗
║  THE SEAM — BaseAgent / BaseInstalledAgent (base.py:21; installed/base.py:310)   ║
║  setup(env) · run(instruction, env, AgentContext) · resume/load     ║
║  populate_context_post_run(context) · to_agent_info()               ║
║  capability flags: SUPPORTS_ATIF / _RESUME / _LOAD_* / _HANDOFF / _CONFIG ║
╚════════════════════════════════════════════════════════════════════╝
        │                     │                     │                     │
        ▼                     ▼                     ▼                     ▼
 Codex adapter           ClaudeCode             SweAgent               AcpAgent
 codex.py:36            claude_code.py:41      swe_agent.py:182      acp.py:307
 install: nvm/codex     install: npm/claude    install: venv+sweagent generic ACP runner
 run: codex exec --json run: claude stream-json run: sweagent run    run: ACP JSON-RPC stdio
 native: rollout-*.jsonl native: sessions/*     native: *.traj        native: acp-events.jsonl
        └───────────────┬───────────────────────┴──────────────┬──────┘
                        ▼                                      ▼
        populate_context_post_run()  ── native → ATIF conversion
                        │                                      │
                        ▼                                      ▼
             AgentContext (tokens/cost)              <trial>/agent/trajectory.json (ATIF)
             → result.json                           → viewer / traces export / atif2otel / hub
```

The vertical line from `AgentFactory` down is the only place any runtime name is known; everything below the seam is adapter-owned, everything above is runtime-neutral.

---

# 3. Q1 — Harbor Core 是否依赖 Codex 类型？

**No.** Verified by import graph:

- The only production imports of `codex.py`/`claude_code.py`/`swe_agent.py` are **string paths** in `AgentFactory._AGENT_MAP`, imported lazily on demand (`factory.py:25-72`, `74-84`). No `from harbor.agents.installed.codex import Codex` exists outside tests.
- Core modules (`trial/trial.py`, `models/trial/config.py`, `models/trial/result.py`, `environments/*`, viewer, traces export) reference agents only through `BaseAgent`/`BaseInstalledAgent`, `AgentName`, `AgentFactory`, `AgentConfig`, `AgentContext`, `AgentInfo`.
- The only `codex` tokens in Core are: the enum value `AgentName.CODEX = "codex"` (`models/agent/name.py:15`), CLI help prose, and telemetry env detection (`CODEX_SANDBOX`) — all strings, not types.
- `cli/adapter_review.py` runs a local `codex` binary directly, but that is a developer parity-check tool, not part of trial execution.

The consequence: Core's dependency graph is `BaseAgent → AgentContext/AgentInfo/BaseEnvironment`, never `Trial → Codex`.

---

# 4. Q2 — Codex-specific logic 在哪里？

Everything Codex-specific is inside `src/harbor/agents/installed/codex.py`:

| Concern | Location |
| --- | --- |
| Capability declaration (`SUPPORTS_ATIF`, resume, load, config, `MODEL_CONNECTION`) | `codex.py:37-52` |
| Declarative CLI flags (`-c model_reasoning_effort`, `-c web_search`, …) | `codex.py:63-84` |
| Native rollout validation + upload for load/resume | `codex.py:101-126` |
| ATIF → Codex rollout conversion (`atif_to_native_trajectory`) | `codex.py:168-306` |
| Version detection, install (`nvm`/`codex`, `install()`), version pinning | `codex.py:318-385` |
| Native session JSONL → ATIF conversion | `codex.py:546-1157` |
| Post-run: write `trajectory.json`, fill `AgentContext` metrics | `codex.py:1160-1197` |
| `run()`: build `codex exec` command, auth/config upload, session copy-back | `codex.py:1333-1481` |

The same shape repeats for every installed agent (Claude Code: `claude_code.py:41-1799`; SWE-agent: `swe_agent.py:182-474`; ~35 others). The recurring pattern is: **declare capabilities → install → invoke CLI headlessly → copy native artifacts to `/logs/agent` → convert native → ATIF in `populate_context_post_run()`**.

---

# 5. Q3 — Adapter 的统一接口是什么？

## BaseAgent (`src/harbor/agents/base.py`)

The mandatory contract is tiny — four methods:

- `name() -> str` (static, `:174`)
- `version() -> str | None` (`:178`)
- `async setup(environment: BaseEnvironment) -> None` (`:189`)
- `async run(instruction: str, environment: BaseEnvironment, context: AgentContext) -> None` (`:205`)

Everything else is optional capability machinery, gated by class flags that Core reads for fail-fast and feature routing:

- `SUPPORTS_ATIF` — trajectory export allowed (`:47`)
- `SUPPORTS_RESUME`, `SUPPORTS_LOAD_NATIVE_TRAJECTORY`, `SUPPORTS_LOAD_ATIF_TRAJECTORY` (`:50-52`)
- `SUPPORTS_HANDOFF`, `SUPPORTS_CONFIG`, `SUPPORTS_WINDOWS` (`:54-62`)
- `MODEL_CONNECTION: ModelConnectionSpec | None` — declarative provider/credentials spec (`:64`; `agents/model_connection.py:117-139`)
- `resume()`, `load()`, `handoff()`, `populate_context_post_run()` — default to NotImplemented/no-op (`:231-261`)
- `to_agent_info() -> AgentInfo` — version + parsed `provider/model` (`:153-172`)

## BaseInstalledAgent (`src/harbor/agents/installed/base.py`)

The installed-agent refinement adds the parts that ~90% of CLI runtimes share, so each adapter doesn't re-implement them:

- `async install(environment)` — abstract, runtime-specific (`:921`)
- Declarative `CLI_FLAGS`/`ENV_VARS` descriptors → auto-built flags/env (`:694-758`)
- `ERROR_PATTERNS` regex → typed API/network/auth/safety error classification (`:212-287`, `:774-809`)
- `SYSTEM_PACKAGES` + `ensure_system_dependencies()` for container provisioning (`:313-465`, `:615-677`)
- `exec_as_root` / `exec_as_agent` helpers with logging and pipefail (`:811-888`)
- Trajectory loading: `atif_to_native_trajectory()` abstract hook (`:1065-1074`), `_seed_load_trajectory()` (`:1044-1063`)
- `@with_prompt_template` decorator for prompt-template rendering (`:169-180`)

The interface is deliberately **contract-shaped, not runtime-shaped**: no Codex/Claude/OpenAI types appear in it. The only shared runtime-neutral data types are `AgentContext`, `AgentInfo`, `BaseEnvironment`, and `Trajectory` (ATIF).

---

# 6. Q4 — Adapter 最终输出什么？

After `run()` (in-environment) and `populate_context_post_run()` (on host after log sync), each adapter produces four outputs:

1. **`AgentContext`** — `n_input_tokens`, `n_cache_tokens`, `n_output_tokens`, `cost_usd`, optional `rollout_details`, `metadata` ([IMPL] `models/agent/context.py:8-29`). Filled by the adapter's post-run hook, e.g. Codex reads `FinalMetrics` (`codex.py:1188-1197`), Claude Code reads its stream metrics (`claude_code.py:1515-1528`), SWE-agent reads `.traj` `info` (`swe_agent.py:346-353`).
2. **`<trial>/agent/trajectory.json`** — ATIF, written by the adapter (`codex.py:1178-1186`; `claude_code.py:1503-1512`; `swe_agent.py:356-361`; `acp.py:1482-1494`). This is the **only runtime-neutral artifact** produced by execution.
3. **Native logs** — Codex session JSONLs + `codex.txt`, Claude session dir + `claude-code.txt`, SWE-agent `.traj` + `swe-agent.txt`, ACP events/summary. These are archived and used for native resume/handoff, never parsed by Core.
4. **`AgentInfo`** — name/version/model into `result.json` (`trial.py:414`, `739`).

`run()` itself is **fire-and-forget from Core's perspective**: it may populate `context` opportunistically, but the guaranteed path is post-run (`trial.py:719` calls `_download_agent_logs()` then `_populate_agent_context()`).

---

# 7. Q5 — Harbor Core 消费什么？

Harbor Core (`src/harbor/trial/trial.py`) consumes only the seam:

| Core step | What it calls | Evidence |
| --- | --- | --- |
| Construction | `AgentFactory.create_agent_from_config(config.agent, ...)` | `trial.py:843-861` |
| Setup | `agent.setup(environment=...)` under timeout + default user | `trial.py:1243-1260` |
| Execution | `agent.run / resume / load(instruction, environment, context)` under timeout + network policy | `trial.py:450-507` |
| Post-run | `_download_agent_logs()` then `agent.populate_context_post_run(agent_result)` | `trial.py:712-720` |
| Result | `agent.to_agent_info()` → `result.json` | `trial.py:414`, `739` |
| Feature gates | `SUPPORTS_ATIF`, `SUPPORTS_RESUME`, `SUPPORTS_LOAD_*`, `SUPPORTS_WINDOWS` | `trial.py:845-855`, `1229-1241` |

Downstream consumers consume the **files**, not the runtime:

- Viewer serves `<trial>/agent/trajectory.json` ([IMPL] `viewer/server.py:2449-2472`)
- `harbor traces export` reads `agent/trajectory.json`, builds conversations/HF datasets; it **rejects agents with `SUPPORTS_ATIF=False`** rather than parsing their native logs ([IMPL] `utils/traces_utils.py:468-556`, `1237-1247`)
- `harbor traces export --format otel` hands trial dirs to the external `harbor-atif2otel` package (`cli/traces.py:197-260`)
- `harbor hub` can download only `trajectory.json` from a trial (`cli/hub.py:1148-1160`)

Core never reads `rollout-*.jsonl`, Claude session JSON, or `.traj` files directly.

---

# 8. Q6 — 替换 Codex 是否需要修改 Harbor Core？

No. Replacement is a **config-level operation**:

```bash
harbor run --path examples/tasks/hello-world --agent codex --model openai/gpt-5.4
harbor run --path examples/tasks/hello-world --agent claude-code --model anthropic/claude-sonnet-4-5
harbor run --path examples/tasks/hello-world --agent swe-agent --model openai/gpt-4o
harbor run --path examples/tasks/hello-world --agent acp:opencode@1.3.9 --model openai/gpt-5.4
harbor run --path examples/tasks/hello-world --agent my_pkg.agent:MyAgent
```

The trial runner, verifier, environments, result model, viewer, and dataset export all take the same path for every runtime. The only Core-visible differences are the capability flags (e.g. `swe-agent` cannot `resume`, so `resume_trajectory: true` fails fast at config validation — `trial.py:845-855`).

---

# 9. Q7 — 添加一个新 Runtime 最少改哪些地方？

**Minimal (zero source modification):** implement `BaseInstalledAgent` in any importable module and run with `--agent module.path:AgentClass`. The factory treats any `name` containing `:` as an import path (`factory.py:147-153`); docs describe this as "integrating your own agent without having to modify Harbor source code" (`docs/content/docs/agents/index.mdx`).

**First-class name (2 small additions):**

1. Add a value to `AgentName` enum (`src/harbor/models/agent/name.py`)
2. Add one entry to `AgentFactory._AGENT_MAP` (`src/harbor/agents/factory.py:25-72`)

That is exactly the in-repo checklist ([IMPL] `AGENTS.md:339-343`): create `installed/<name>.py` → extend `BaseInstalledAgent`/`BaseAgent` → register enum. No changes to trial, models, CLI parsing, viewer, export, or docs are required for a basic adapter.

The required adapter work per runtime:

- `install(environment)` — provision the CLI inside the container
- `run(...)` — invoke the CLI headlessly, write native artifacts under `/logs/agent`
- `populate_context_post_run(context)` — convert native transcript → `trajectory.json` + fill `AgentContext`
- optional: capability flags, `CLI_FLAGS`/`ENV_VARS`, `atif_to_native_trajectory()` for load

---

# 10. Q8 — Runtime adapter 与 ATIF 的关系是什么？

The adapter is the **sole owner of native↔ATIF translation**, in both directions:

- **Produce (run → export):** each adapter converts its runtime's native transcript into ATIF after execution — Codex rollout JSONL (`codex.py:783-1157`), Claude `stream-json` events (`claude_code.py:959-1492`), SWE-agent `.traj` via a standalone converter (`swe_agent.py:29-180`), ACP protocol events (`acp.py:1154-1480`). The output is always the same file contract: `<trial>/agent/trajectory.json`.
- **Consume (load → run):** `SUPPORTS_LOAD_ATIF_TRAJECTORY` + `atif_to_native_trajectory()` re-serialize an ATIF file back into the runtime's native session format (Codex: `codex.py:168-306`; Claude: `claude_code.py:235-359`), and `_seed_load_trajectory()` places it where the runtime expects sessions (`installed/base.py:1044-1063`).
- **Boundary rule:** Core validates ATIF (`Trajectory` Pydantic model, `trajectory_validator`) and consumes it downstream, but **never writes it and never reads native formats**. The conversion seam is exactly the adapter boundary; a runtime that doesn't support ATIF simply declares `SUPPORTS_ATIF = False` and is excluded from trace export (`traces_utils.py:1246-1247`).

This is why ATIF is "runtime-neutral": it is the one interchange artifact each adapter voluntarily agrees to produce, rather than a schema Core imposes on runtime internals.

---

# 11. 为什么 Harbor 能够支持多个 Runtime 而不把 Core 绑定到具体 Agent Runtime？

Five design decisions, in order of importance:

1. **A narrow behavioral contract instead of a type hierarchy.** Core depends on `BaseAgent`'s five methods and a handful of capability booleans, not on any concrete adapter. Trial orchestration is written once against the seam (`trial.py:450-507`, `1243-1260`); new runtimes only add implementations.
2. **String-based lazy registration.** `AgentFactory._AGENT_MAP` maps names to import-path strings, and `create_agent_from_config` additionally accepts arbitrary `module:Class` paths and `acp:` shorthand (`factory.py:25-72`, `135-214`). Core never needs a compile-time import of any runtime; even first-class agents are imported on demand.
3. **Runtime-specific code is physically quarantined.** Each `installed/<name>.py` file contains the full lifecycle of one runtime — install, CLI invocation, transcript parsing, ATIF conversion. The files form a repeating template, so adding runtime #36 is copy-shape work, not Core surgery.
4. **The runtime-neutral outputs are value objects and one file.** Core consumes `AgentContext` (numbers), `AgentInfo` (strings), and ATIF `trajectory.json` (validated schema) — all produced by the adapter itself. Native formats never cross the boundary, so a runtime can change its internals (Codex rollout format, Claude stream schema) without Core noticing.
5. **One generic protocol adapter covers the long tail.** `AcpAgent` runs any Agent Client Protocol-registered agent through a single adapter (`acp.py:307-1598`; `docs/content/docs/agents/acp.mdx`), proving the seam is not a per-vendor shim pattern but a genuine runtime-neutral contract: any runtime that can speak ACP is a Harbor agent with one generic implementation.

The one structural cost of this design is that "capability" knowledge is duplicated — Core reads flags (`SUPPORTS_*`) instead of probing the runtime — and richer runtimes (resume, handoff, config, native load) must each implement the optional hooks. That is the deliberate trade for never binding Core to a vendor.

---

# 12. Evidence Index

| Fact | Evidence |
| --- | --- |
| BaseAgent interface + capability flags | `src/harbor/agents/base.py:21-264` |
| BaseInstalledAgent shared machinery | `src/harbor/agents/installed/base.py:310-1098` |
| Agent registry (string import paths) | `src/harbor/agents/factory.py:25-84` |
| Custom agent via import_path / acp shorthand | `src/harbor/agents/factory.py:135-214` |
| AgentName enum | `src/harbor/models/agent/name.py` |
| Runtime-neutral AgentConfig | `src/harbor/models/trial/config.py:61-110` |
| AgentContext / AgentInfo | `src/harbor/models/agent/context.py:8-29`; `src/harbor/models/trial/result.py:39-57` |
| Codex adapter (install/run/convert/export) | `src/harbor/agents/installed/codex.py:36,345,1160,1333` |
| Claude Code adapter | `src/harbor/agents/installed/claude_code.py:41,425,1494,1601` |
| SWE-agent adapter | `src/harbor/agents/installed/swe_agent.py:29,182,250,333,366` |
| Generic ACP adapter | `src/harbor/agents/installed/acp.py:307,1154,1510,1570` |
| Core orchestration calls the seam | `src/harbor/trial/trial.py:450-507,712-720,843-861,1243-1260` |
| ATIF consumed by viewer | `src/harbor/viewer/server.py:2449-2472` |
| ATIF consumed by trace export | `src/harbor/utils/traces_utils.py:468-556,1237-1247` |
| ATIF consumed by OTel export | `src/harbor/cli/traces.py:197-260` |
| New-agent checklist | `AGENTS.md:339-343` |
| Custom-agent docs (no source change) | `docs/content/docs/agents/index.mdx` |
