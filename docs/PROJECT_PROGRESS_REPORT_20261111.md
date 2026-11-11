# Vortex-U280 阶段成果：2026-11-11

项目已建立 PTX P0 整数程序从前端、模块、runtime 到 SimX、处理器 RTL、NOXRT AFU 和物理 U280 的执行链。当前接收范围是 copy、vadd、整数 affine 及经过验证的等价源变体，不代表完整 CUDA 或任意 PTX 支持。

## 当前交付

| 工作 | 实际结果 | 入口 |
|---|---|---|
| C runtime 集成 | 模块、BufferSlice、单队列/event、参数副本、连续启动和资源生命周期已接入 | [实现与历史合入](C_RUNTIME_MERGE.md)、[当前接口 v2](../configs/c_runtime/api_v2.json) |
| 新合法语料独立接收 | 六份 PTX 源、12 份模块新构建；四路各 48/48，共 192 次执行通过 | [E 接收报告](E_RUNTIME_UNSEEN_ACCEPTANCE.md)、[机器签发](../results/e-runtime-unseen-acceptance-20261111-v1/result.json) |
| 输出与 ABI | 576 份完整数组、192 组参数的 576 份快照通过；每路一个 context/queue、41 次模块装载、两轮缓冲区分配 | [冻结输入与答案](../configs/acceptance/e-runtime-unseen-20261111-v1/manifest.json) |
| 物理 U280 | 固定 D10/D12、HOST 256 MiB、实际 200 MHz，打开/关闭门禁通过；48 条执行和 SSH/接收退出 0 | [板测记录](../results/e-u280-unseen-20261111-v1/result.json) |
| 超时与故障路径 | 三模型真实超时排空、旧句柄失效、新任务正确；CP 设备错误后持续封锁 | [恢复修复与限制](RUNTIME_RECOVERY_20261111.md) |
| 本地运行器自测 | 269 项中 268 通过、1 跳过，退出 0；不计为设备执行 | [源码快照与检查](../results/c-runtime-closeout-20261111-v1/summary.json) |

旧 v1 前端保留；runtime 显式采用 v1.2 与 `python36-integer-v1`。恢复补丁为 `sticky-device-fault-v1`：永久记录非 timeout 原生故障，避免底层 finish 清除错误后重复 recover 误放行；成功排空还需检查原始 event。根 lock/caps 仍为 draft，没有因样例通过而宣称完整 P0 已冻结。

## 尚未完成

- 物理 U280 故障恢复为 NOT_RUN，停止或隔离旧 DMA 的平台依据 BLOCKED，物理 `recover()` 保持 E_UNAVAILABLE。
- TIMING-7 保持 OPEN，正常执行成功没有关闭该静态审阅问题。
- 完整 P0 指令组合、更多地址边界和新语料的逐 lane 访存专项验证尚待扩充。
- 原生/PTX 性能对照、硬件配置对照和 AI 协作成对实验尚未完成；没有性能提升或协作效率结论。
- 本轮 E 为独立上下文的非作者 AI 验证方，不代替人类验收签名。

## 复现与阅读顺序

1. [当前状态](STATUS.md)与[项目交接](PROJECT_HANDOFF.md)：区分最新结论和历史阶段。
2. [合作协议](COLLABORATION_PROTOCOL.md)、[PTX 范围](PTX_COMPATIBILITY_PROFILE.md)与[当前 API](../configs/c_runtime/api_v2.json)。
3. [E 新语料接收](E_RUNTIME_UNSEEN_ACCEPTANCE.md)：新 run_id 的构建、三模型和板测入口。
4. [恢复实验](RUNTIME_RECOVERY_20261111.md)：仅限模型的故障实验与物理限制。

每次执行必须创建新 run_id，保留失败记录。公开仓库所含材料及脱敏规则见公开副本中的 `docs/PUBLICATION.md` 与 `results/README.md`；完整本地归档中的历史哈希不会因发布脱敏而改写。
