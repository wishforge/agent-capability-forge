# Phase 9-D.1.07 — Industry Comparison（只复用 9-B.2 考古）

依据：`docs/archaeology/unified-runtime/phase9b2/02-06` +
`phase9b2/08-identity-drift-and-toctou-analysis.md` +
`phase9c/10-industry-cross-check.md`。未重新调研。

## 1. 成熟系统如何避免 “verified object -> later mutable object”

| 系统 | 机制 | 效果 |
|---|---|---|
| in-toto | MATCH 规则要求上一步 products 与下一步 materials 路径+hash 全等；DISALLOW 拒绝未消费 artifact | 链内步骤间；链外交付物替换仍需消费者绑 digest |
| SLSA | verifier 比对 subject.digest 与真实 artifact | 验证时刻；不保证验证后部署同一字节 |
| Cosign | 先 `ResolveDigest(tag)`，再按 digest 验证签名与 payload claim | 名字降级为初始定位器；验证后对象是 digest |
| Sigstore Policy Controller | mutating 把 tag 改写成 digest；validating 拒绝非 digest；Kubelet 按 digest 拉取 | **验证对象 == 运行对象**写进平台契约 |
| DSSE | payloadType 进 PAE；验证字节原样进应用层 | 防元数据层 type/rebinding |

## 2. 共同点

```text
验证时把名字解析/固定为 digest（content-addressed reference），
之后所有后续引用只用 digest，不再用名字。
```

Policy Controller 是唯一把“验证对象 == 运行对象”由平台强制（改写 spec +
按 digest 拉取）的系统。容器镜像本身就是不可变 content-addressed 对象，
拉取器按 digest 取得对象，不存在“验证后路径被换”的第二步解析。

## 3. 与本地对照

| 本地 | 行业对应 | 差异 |
|---|---|---|
| frozen record artifact_digest + run_request 四元组 | provenance / attestation / immutable reference | 等价，CLOSED（9-B.1/9-B.3/9-B.5） |
| adopt / verify_at_mount 重算 live digest | SLSA/Cosign 验证时刻 | 等价 |
| `verified_artifact_dir` path string → docker bind mount | 平台按 digest 拉取 | **本地 mount 仍按名字二次解析；行业平台按 digest 拉取** |

## 4. Application vs OS-level identity

```text
application-level identity : digest / provenance（本地已闭合）
OS/filesystem-level object : inode / fd / immutable object（本地未 pin）
```

行业（容器平台）通过“对象本身就是不可变 content-addressed 对象 + 按 digest
引用”把两层合并；本地 pilot 的 artifact 是普通可变目录 + path 引用，
因此两层分离，O1 属于第二层。

