# 05 b3_entry 与成熟项目对照（复用 Phase 9-B.2 结论）

本阶段不重做完整 archaeology，只对照 "runtime intent / deployment metadata /
admission object" 的绑定方式。来源：`docs/archaeology/unified-runtime/phase9b2/`
02（in-toto）、03（SLSA）、04（Cosign）、05（Sigstore Policy Controller）、06（DSSE）。

| 项目 | 处理 runtime intent 的方式 | 对照结论 |
|---|---|---|
| in-toto | Link 元数据包含 `expected_materials` / `expected_products`，由 functionary 私钥签名；消费者把实际运行对象绑定到已验证 link | 本地没有签名过的 "运行意图" 对象；b3_entry 等价于未签名的 link |
| SLSA | 把 "expected package name"（expectations）与 "provenance 里的 artifact digest" 分离；下载/安装时按 digest 验证 | 本地四元组 = digest 侧（已闭合）；"预期运行谁" 没有独立于 b3_entry 的锚点 |
| Cosign | 先 `ResolveDigest`，验证后只接受 digest 引用，tag 漂移不再影响运行对象 | 本地 adopt 每次重算 digest 等效；但 "选哪个对象" 仍由可变 name 决定 |
| Policy Controller | admission 验证的对象 == 最终运行对象，因为规格里是 content-addressed digest；非 digest 引用直接拒绝 | 最关键的差异：本地运行请求（b3_entry）本身不是 digest 引用，而是可被一致改写后仍然自洽的 JSON |
| DSSE | PAE 把 payloadType 纳入被签名输入；"验证字节" 与 "消费字节" 必须一致 | 本地四元组比对是 "重验字段"，但预期字段来源（b3_entry）未经签名/锚定 |

## 一句话

成熟系统要求 **运行意图要么被签名（in-toto link / DSSE envelope），要么对象引用本身是
不可变 digest（Cosign / Policy Controller）**。本地 canonical runtime 已经做到
"验证对象 == 运行对象"（同一路径、同一 digest），但 "运行意图对象" 本身没有签名或锚定，
这是与行业做法唯一的实质差异点。

