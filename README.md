# Vortex-U280

AI 智能体辅助的 Vortex-U280 GPGPU 与 PTX 子集兼容编译研究。

本仓库是 Vortex-U280 截至 2026-11-09 D13 的公开快照，范围为 Vortex、PTX P0 与 U280。

## 从这里开始

| 入口 | 用途 |
|---|---|
| [项目交接](docs/PROJECT_HANDOFF.md) | 当前目标、真实进度、阻塞与下一步 |
| [当前状态](docs/STATUS.md) | 按证据区分 PASS、FAIL、BLOCKED、NOT_RUN |
| [研究计划与五人分工](docs/RESEARCH_PLAN.md) | 研究边界、A—E 分工与 30 天安排 |
| [A/B 执行计划](docs/AB_EXECUTION_PLAN.md) | 架构与平台的个人任务和验收 |
| [合作接口协议](docs/COLLABORATION_PROTOCOL.md) | V01—V08、ABI、模块与接收契约 |
| [PTX 兼容性规范](docs/PTX_COMPATIBILITY_PROFILE.md) | P0 白名单、语义和边界测试 |
| [PTX 前端首版](docs/PTX_FRONTEND_PROGRESS.md) | 解析、typed IR、参数布局、生成 C++ 与宿主语义自测 |
| [启动清单](docs/STARTUP.md) | 启动关口与环境核查 |
| [首轮推进与复跑](docs/AB_D1_PROGRESS.md) | 已有产物、阻塞证据和更新后的命令 |
| [D2 推进与暂停交接](docs/AB_D2_PROGRESS.md) | 独立 Linux、固定工具包、真实 SimX demo 与保留的失败 |
| [D3 推进](docs/AB_D3_PROGRESS.md) | 同配置复跑、固定 Verilator、处理器 RTL 与 AFU 模型 |
| [D4 原生边界回归](docs/AB_D4_PROGRESS.md) | 4w×4t 基线，三路各 140 次原生 u32 启动 |
| [D5 B=32 候选](docs/AB_D5_PROGRESS.md) | 8w×4t 候选，三路各 152 次启动与 U280 网络实测 |
| [上游基线审查](docs/UPSTREAM_BASELINE_REVIEW.md) | 固定源码/工具包及 U280 前置条件 |
| [平台盘点](docs/PLATFORM_INVENTORY.md) | 宿主事实与缺项 |
| [交接与 AI 任务模板](docs/HANDOFF_TEMPLATE.md) | 后续实施和接收记录 |
| [Codex 项目接入](docs/CODEX_SETUP.md) | 新项目目录选择与首条消息 |
| [拆分与验证说明](docs/PROJECT_MIGRATION.md) | 保留范围、路径修改和迁移证据 |

## 当前完成范围

- 原生 Vortex 整数程序已通过 SimX、处理器 RTL 和本地 NOXRT AFU 模型验证。独立 8w×4t 候选含 B=32，每路 152 次启动通过。结果覆盖实施者自测。
- PTX 前端已实现解析、类型与参数检查和 C++ 语义代码生成，661 个 CPU 宿主语义用例通过。设备 wrapper、vxbin 打包、项目运行时和 PTX 设备执行仍待完成。
- U280 已完成 200 MHz 目标下的 FPGA 镜像构建，以及配套服务器运行库编译和依赖解析。D13 静态审阅 53/53 检查通过，HOST 配置与 TIMING-7 仍阻塞。加载后的实际频率和板上功能均待验证。

[阶段进展报告](docs/PROJECT_PROGRESS_REPORT_20261109.md)汇总各层验证范围。[证据索引](results/README.md)列出公开记录及脱敏范围。

## 获取与贡献

```bash
git clone --recurse-submodules https://github.com/slishysun974/Vortex-U280.git
cd Vortex-U280
python -B -m unittest discover -s tests -v
```

也可从 GitHub 的 **Code → Download ZIP** 下载本仓库文件，固定上游通过 Git 子模块单独取得。欢迎 Fork，在自己的分支上编辑或上传文件，再提交 Pull Request。提交时请说明验证命令、退出码和范围。服务器脚本中的地址、账号与本机路径是示例，实际连接需使用获授权的环境配置。

依赖本地 D8 输入、服务器 runtime 输入或完整 Vivado 报告的历史复核测试会在缺少对应材料时跳过。未初始化子模块时，依赖固定上游源码的测试也会跳过。

## 目录约定

```text
Vortex-U280/
  AGENTS.md       项目工作约定
  docs/           当前研究、协议、状态与交接
  configs/        候选配置和 draft lock/caps
  scripts/        源码核查、盘点、原生运行器与 PTX 前端/验证入口
  ptx/samples/    手写 P0 三类 kernel 与实施者语义探针
  native/ptx_host_check/ 生成代码的宿主访存审计程序
  tests/          Python 运行器与 PTX 前端作者测试
  experiments/    已有 AI 任务记录
  results/        按 run_id 收录选定的验证记录
  upstream/vortex/ 固定上游及独立 Git 元数据
```

所有命令从本目录执行，不再加 `vortex_project/` 前缀。当前运行器自测：

```powershell
python -B -m unittest discover -s tests -v
```

该命令验证 Python 运行器和前端行为，不能作为 Vortex kernel 或 U280 通过的证据。前端生成代码的宿主编译/执行另由 `scripts/run_ptx_frontend_validation.py` 验证，仍不计作 SimX/RTL/U280 结果。新实验写入 `results/<新run_id>/`；已有日志、清单、配置哈希和原始资料不改写。上游保持独立检出，不在其中做混用配置的构建。
