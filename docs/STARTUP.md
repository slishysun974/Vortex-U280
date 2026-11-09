# Vortex-U280 新路线启动清单

日期：2026-11-07。当前方向：AI 智能体辅助开发，基于 Vortex 的 U280 GPGPU 与 PTX 子集兼容编译。

先读 [研究计划与五人分工](RESEARCH_PLAN.md)、[合作接口协议](COLLABORATION_PROTOCOL.md)、[PTX 兼容性规范](PTX_COMPATIBILITY_PROFILE.md)。当前只使用本项目协议；旧 AEC 资料留在原项目。

## 当前起点

2026-11-07 A/B 已启动，以下旧起点按本段更新：源码位于 `upstream/vortex`，固定 `7fe19369587c087f902c3e2bc2add612aa910a95`；`configs/target_lock.json`、`target_caps.json` 仍是未执行验收的 draft。已完成源码身份/配置解析核验，尚未跑通原生 SimX/RTL。宿主存在 Ubuntu 20.04/glibc 2.31 与当前工具包的兼容阻塞；Docker 启动尝试超时。用户已确认暂时没有 U280 访问权限，后续提供。详细事实、运行脚本和下一步见 [AB_D1_PROGRESS](AB_D1_PROGRESS.md) 与 [平台盘点](PLATFORM_INVENTORY.md)。

- 当前已取得 Vortex 源码并实现运行预检入口；尚无跑通的 Vortex kernel、PTX→Vortex 编译器、U280 bitstream 或板上运行证据。
- 本项目不累计旧 AEC 的软件测试、向量加或局部 ALU RTL 结果；当前完成范围见 [STATUS](STATUS.md)。
- 可复用独立答案、种子、尾部哨兵、故障注入、原始日志、哈希和接收机制；不得将旧 AEC ISA/运行时接口改名当作 Vortex ABI。
- 用户已确认目前没有 U280 访问权限；后续提供。先做不依赖板卡的版本、SimX、编译器与用例准备。
- 课程服务器可执行历史局部 ALU 仿真，不代表已满足完整 Vortex 的 Verilator/工具链/资源要求；当前不自动启动新远程作业。

## 48—72 小时交付

| 人员 | 任务 | 接收产物 |
|---|---|---|
| A | 比较可复现的配套版本；跑原生 SimX；确定 RTL 最小配置 | target lock/caps、原生日志、RTL 构建入口 |
| B | 核实板卡、工具与平台；提前安排长时间 FPGA 构建 | 平台盘点、依赖/阻塞单、构建和恢复方案 |
| C | 建立 native 程序编译/装载入口；固定后端与设备 wrapper | 原生模块包、统一 runtime 草案、参数 packer 样例 |
| D | 冻结 P0 输入白名单；建立 parser/类型/诊断 | PTX 正例/拒绝样例、typed IR/生成代码契约 |
| E | 三类 kernel 独立答案与边界；实验任务配对 | 冻结验收集、接收人、AI 任务与预算记录 |

关口 G0：固定版本的原生 kernel 至少在 SimX 运行；源码和工具版本可追溯；能力/ABI 文件有可核查值。G1：copy/vadd 经自研 PTX 前端与同一后端运行通过。没有 G0 就不把平台失败归咎于 PTX 前端。

## 环境核查表

| 项目 | 必须记录 | 负责人 |
|---|---|---|
| Vortex/工具链 | commit、子模块、补丁、LLVM/VOLT/runtime 配对、XLEN、SIMT 特性 | A/C |
| Linux 构建环境 | 系统、编译器、Verilator 与依赖版本、磁盘/内存、实际命令 | A/B/C |
| U280 | 卡型/BDF、shell 标识、可用权限、平台名称、排期 | B |
| FPGA/XRT | 实际 Vitis/Vivado、XRT/驱动、platform 与固件匹配、许可 | B |
| 版本相关平台需求 | 所选版本的 host-memory/命令路径、内存映射、恢复方式 | B/C |
| 参数/地址 | PTX 地址位宽、目标 XLEN、设备 pointer、物理内存映射分别记录 | A/C/D |
| 测试 oracle | CPU 独立答案；有 NVIDIA 设备则增加 PTX 对照，否则 NOT_RUN | E |
| 可复现标识 | Git commit；没有 Git 时完整文件 SHA-256 清单 | 各人；C 汇总 |

旧赛题的 Vivado/Vitis 2022.2、XRT 2.13.479、AEC golden/ISA JSON、正式模型数据不再是本路线的固定依赖。实际版本由所选 Vortex 与已安装 U280 平台决定。[上游 FPGA 指南](https://github.com/vortexgpgpu/vortex/blob/master/docs/fpga_setup.md)

## 新代码组织建议

本目录即独立项目根目录，文档位于 `docs/`。下表中的 compiler/runtime/kernels 是后续实现建议，目前未创建，也不表示功能已完成。

```text
Vortex-U280/
  docs/          当前计划、协议、规范与状态（已整理）
  upstream/       固定上游 checkout/补丁记录
  configs/        target_lock、caps、profile、ABI
  compiler/      PTX 前端、IR、lowering、后端适配
  runtime/       host 封装和设备 wrapper
  kernels/       PTX 与原生对照
  tests/         单元、语义、拒绝、集成与独立 oracle
  scripts/       构建、运行、归档入口
  experiments/   AI 任务卡、分组与记录
  results/       每轮独立运行证据，子目录为 run_id
```

当前可用入口为 `scripts/capture_target.py`、`scripts/platform_inventory.py` 和 `scripts/run_native_smoke.py`，命令见 [复跑说明](AB_D1_PROGRESS.md)。Python 单元测试只验证运行器行为，不证明 Vortex kernel 通过。
