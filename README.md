# Vortex-U280

AI 智能体辅助的 Vortex-U280 GPGPU 与 PTX P0 子集兼容编译研究。

截至 **2026-11-11**，PTX copy、vadd、整数 affine 及三种合法等价源变体已通过 **SimX、处理器 RTL、NOXRT AFU、物理 U280 四路各 48/48 独立接收**。项目 runtime 支持单队列、参数副本、连续启动和缓冲区生命周期管理。

| 入口 | 内容 |
|---|---|
| [阶段成果](docs/PROJECT_PROGRESS_REPORT_20261111.md) | 当前可交付能力、证据与未完成项 |
| [当前状态](docs/STATUS.md) / [项目交接](docs/PROJECT_HANDOFF.md) | 最新结果、历史记录和后续工作 |
| [独立 E 接收](docs/E_RUNTIME_UNSEEN_ACCEPTANCE.md) | 先冻结输入与答案，再执行的 192 次新验证 |
| [C runtime](docs/C_RUNTIME_MERGE.md) / [接口 v2](configs/c_runtime/api_v2.json) | 模块、BufferSlice、event、生命周期和恢复限制 |
| [恢复实验](docs/RUNTIME_RECOVERY_20261111.md) | 三模型超时排空与设备故障封锁 |
| [服务器访问与目录](docs/SERVER_GUIDE.md) | 登录方式、工具环境、FPGA 成品和实验位置 |
| [PTX 范围](docs/PTX_COMPATIBILITY_PROFILE.md) / [合作协议](docs/COLLABORATION_PROTOCOL.md) | 语义、接口及接收约定 |
| [研究计划](docs/RESEARCH_PLAN.md) | 研究问题、五人分工、性能与 AI 对照实验 |

## 已验证与未完成

- 新独立语料四路共 **192 次执行、576 份全数组、192 组参数**通过；每路一个 context/queue、41 次模块装载和两轮缓冲区分配。
- 物理板测使用固定 D10/D12、HOST 256 MiB、实际 200 MHz；打开/关闭门禁、执行及 SSH 接收均通过。
- `sticky-device-fault-v1` 修复错误被底层清除后重试误放行的问题；三模型实际超时排空、旧句柄失效和故障封锁通过。
- **物理故障恢复仍 NOT_RUN，旧 DMA 停止/隔离依据 BLOCKED；TIMING-7 保持 OPEN。** 根 lock/caps 仍为 draft。
- 完整 P0、一般分支、浮点、shared/barrier 和完整 CUDA 不在当前接收结论内。性能、配置与 AI 协作对照实验尚未形成结论。

## 获取与检查

```bash
git clone --recurse-submodules https://github.com/slishysun974/Vortex-U280.git
cd Vortex-U280
python -B -m unittest discover -s tests -v
```

本地完整工作区最新运行器自测为 **268 通过、1 跳过**。该命令只验证 Python 运行器、前端及接收器行为，不能代替设备执行。公开副本缺少的历史大文件或运行环境会明确跳过对应检查；本次公开副本为 **237 通过、32 跳过**，四路已有输出各 48/48 离线重核通过，见 [发布验证](results/publication-check-20261111-v1/summary.json)。

设备复现使用 [E 接收文档](docs/E_RUNTIME_UNSEEN_ACCEPTANCE.md) 中的新 run_id 命令，需要固定工具链及对应 backend；板测还需获授权的服务器、匹配的 FPGA/runtime 与当次设备门禁。服务器入口是本地环境配置，不随代码授予设备权限。

## 目录

```text
configs/       目标锁、ABI、候选配置和冻结验收语料
scripts/       前端、模块、runtime、设备入口和独立接收器
native/        Vortex wrapper、原生基线与宿主审计程序
ptx/           P0 示例
tests/         Python 自测
docs/          研究、接口、状态和接收说明
results/       按 run_id 保存的验证证据
third_party/   固定来源与许可证明确的宿主兼容依赖
upstream/vortex/  固定提交的上游源码
```

全部命令从项目根目录运行。新实验使用新 run_id，不改写旧失败记录或冻结答案。公开仓库保留选定证据；完整工具包、FPGA 大文件、服务器访问材料和课程原件继续在本地保管。欢迎 Fork 后提交 Pull Request，并附验证命令、退出码与适用范围。
