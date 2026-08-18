# Phase 9-B.2 Code Archaeology Plan

- 日期：2026-08-18
- 基线 commit：`034a3b2`（fix(runtime): close canonical candidate legacy downgrade）
- 模式：只读考古；不修改 production code / runtime 逻辑，不加测试，不重构，不 commit。

## 1. 目标

回答一个核心问题：

> 一个对象在 Evaluation / Promotion / Authority / Adoption / Runtime 之间流转时，
> 如何保证“前面验证和批准的对象”与“最后真正运行的对象”是同一个对象？

方法：先读本地生产源码（`pilot/*`、`src/forge/*`、`phase9b1` 报告），建立当前
Identity Chain；再读五个开源项目源码/规范，提取机制，做差异对照。

## 2. 研究材料与固定版本

本地源码（工作区 HEAD `034a3b2`）：

| 文件 | 角色 |
|---|---|
| `src/forge/capabilityizer.py` | Candidate identity / canonical artifact digest / Frozen Candidate / seal / evaluation binding |
| `pilot/adoption_authority.py` | authority 契约、store、trust anchor、immutable ledger |
| `pilot/adoption_authority_producer.py` | issue_authority（decision + authority 签发） |
| `pilot/registry.py` | promote / reject / discover（registry entry） |
| `pilot/runtime_adoption_guard.py` | adopt / verify_at_mount（运行前验证） |
| `pilot/harness.py` | phase_b3_build / phase_future(b3)（真实执行路径） |
| `docs/archaeology/unified-runtime/phase9b1/` | 上一阶段生产报告 |

外部项目（shallow clone 固定 HEAD）：

| 项目 | commit | 说明 |
|---|---|---|
| in-toto/in-toto | `a8ce9ee2125ae5a4b041a4e37cc1cf10eed0da6b` | layout/link 验证源码 |
| slsa-framework/slsa | `1686afeba11a456e470235ecf50cfc0d2f9ecbc3` | SLSA v1.0 provenance 规范 |
| slsa-framework/slsa-github-generator | `bb91a05077afa6601a3d7538c4cbbdbf0abe7ed9` | 真实 builder 实现 |
| sigstore/cosign | `8b8c87b68a75f70c12e1adf25f9bb87f24abea7e` | 签名/证书/digest 验证 |
| sigstore/policy-controller | `e9dfc010306dacf9e563744e92e1f015c7418f1a` | admission 验证 |
| secure-systems-lab/dsse | `1d3370f62565bca041e97c8310b873ac340edc2e` | DSSE 协议/PAE |

## 3. 证据优先级

```text
真实源码 > 官方 specification > 官方 documentation > README > 博客 > 推断
```

凡无法从源码/规范证明的结论标注 `UNKNOWN`，不写 `probably`。

## 4. 输出

```text
00-code-archaeology-plan.md            本计划
01-agent-capability-identity-current-state.md   当前本地链
02-in-toto-code-archaeology.md         in-toto
03-slsa-code-archaeology.md            SLSA + slsa-github-generator
04-cosign-code-archaeology.md          Cosign
05-policy-controller-code-archaeology.md   Policy Controller
06-dsse-code-archaeology.md            DSSE
07-identity-continuity-comparison.md   跨项目对照矩阵
08-identity-drift-and-toctou-analysis.md  Identity Drift / TOCTOU / name vs digest
09-phase9b2-design-gaps.md             Problem / Evidence / Industry / Gap / Invariant
10-recommendations.md                  ADOPT / ADAPT / DO NOT ADOPT
99-synthesis.md                        7 问 + Verdict
```

## 5. 边界

- 不设计 Phase 9-B.2 实现（不写“新增 xxx.py / 增加 xxx field”），只给 invariant。
- 已有 archaeology 不覆盖；`phase9b2/` 为新目录，不触碰 `phase9b1/`。
