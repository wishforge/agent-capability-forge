# Phase 9-C.10 — Industry Cross-check

基线：`a70a433`。只复用 Phase 9-B.2 已有 archaeology（in-toto / SLSA / Cosign /
Sigstore Policy Controller / DSSE，见 phase9b2/02-06），不重新做大范围 research。

## 1. 对照表：本地 vs 行业不可变决策节点

| 行业节点 | 本地对应 | 状态 |
|---|---|---|
| provenance（subject/digest） | frozen record artifact_digest + authority immutable_artifact_refs | CLOSED（9-B.1/9-B.3） |
| attestation（签名 payload） | seal_digest（v2 含 schema/version，DSSE PAE 等价） | CLOSED（9-B.3 R3）；无密码学签名 = 已知边界 |
| immutable reference（digest-pinned） | authority.seal_digest + run_request 四元组锚定 | CLOSED（9-B.5） |
| admission decision（最终运行对象） | anchored run_request + adopt + verify_at_mount | CLOSED（canonical） |
| tag/name 只作 locator | run_request.name / b3_entry / registry name | CLOSED（9-B.5） |

## 2. 唯一曾有的行业差异

9-B.4.1 判定：本地“运行意图对象”没有签名或锚定（b3_entry 等价于未签名 in-toto
link；Policy Controller 强制 digest 引用而本地用 name 定位）。该差异已被 9-B.5
Option A 关闭：run_request 进入 anchored store_digest，registry/b3_entry 只作
locator/cache。

## 3. 新 gap 检查

- provenance：authority.provenance 绑定 decision/run/immutable_artifact_refs，闭环。
- subject：seal_digest 覆盖 frozen core + artifact/manifest/tests，且锚定于
  authority；无独立 subject 漂移点。
- attestation：无密码学签名是既有 GAP-3（issuer 字符串边界），不是本阶段新发现。
- immutable reference：anchor 是 digest 文件；未 seal 或 anchor 可写属部署契约
  （77/78 号报告 UNKNOWN）。
- admission decision：唯一选择者是 anchored run_request。

## 4. 结论

```text
No new industry-derived gap
```

（可选后续：issuer 密码学化、anchor 物理写保护，均属既有开放项，不阻断 canonical
trust closure。）
