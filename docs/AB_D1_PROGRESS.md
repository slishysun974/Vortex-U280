# A/B 首轮推进记录与复跑

日期：2026-11-07，Asia/Shanghai。阶段：D1 启动。用户确认当前没有 U280 访问权限，后续提供；本轮不启动板上操作。

后续说明（2026-11-08）：本文保留 D1 当时的事实。D2 已建立独立宿主并跑通原生 SimX，当前状态与新命令见 [AB_D2_PROGRESS](AB_D2_PROGRESS.md)。下面的 `capture_target.py` 命令属于 draft-v1 初始化流程，会重写当前 configs；D2 后只读核验应使用 `run_native_smoke.py --check-only`。

## 当前结论

A 线已经从计划进入源码、配置与运行入口准备；**G0 尚未通过**。实际宿主为 Ubuntu 20.04.6 / glibc 2.31 / G++ 9.4，缺少 CMake 和配套 Vortex 工具链；候选工具包要求较新的系统库。已尝试启动现有 Docker Desktop，命令超时且引擎仍不可用，因此没有创建容器、下载大工具包或升级现有 WSL。

B 线已完成可访问本机的只读盘点，准备了后续可在板卡服务器执行的盘点入口。实际 U280、XRT、shell、platform、host-memory 通路和许可均未验收；等待访问条件。

## 本轮新增产物

| 产物 | 已完成范围 | 验证边界 |
|---|---|---|
| `upstream/vortex` | 官方 v3.0：`7fe19369587c087f902c3e2bc2add612aa910a95`；softfloat、ramulator 固定子模块已取 | 其余三个顶层子模块尚未取；Ramulator 的 FetchContent 依赖尚未准备 |
| [native_smoke.json](../configs/native_smoke.json) | RV64 / 1 cluster / 1 core / 4 warps / 4 threads 候选 | 共 16 个物理线程，仅用于最初的上游整数 demo |
| [target_lock.json](../configs/target_lock.json)、[target_caps.json](../configs/target_caps.json) | 源码、子模块、配置哈希、已知与未知字段分开 | `draft` / `frozen=false`；不能作为团队已验收能力 |
| [源码/配置证据 v2](../results/ab-d1-source-20261107-v2/result.json) | 3329 个实际源码文件 SHA-256、Git 命令输出、配置解析 | PASS 仅指身份与解析；SimX/RTL 执行仍 NOT_RUN |
| [原生运行器](../scripts/run_native_smoke.py) | Linux 预检、隔离构建、逐命令日志/退出码/超时、真实 demo 标记检查 | 未在具备完整依赖的宿主执行成功；不能把脚本自测当成 Vortex PASS |
| [平台盘点脚本](../scripts/platform_inventory.py) | 只读 Linux 工具、资源、路径、Xilinx PCI 可见性记录 | 默认不执行 XRT 设备查询；不变更设备、不安装软件 |
| Linux 实测 JSON（本地记录 `results/ab-d1-host-20261107/linux_inventory.json`） | Ubuntu、libc、CPU/内存/磁盘、真实工具版本/缺项 | 盘点采集成功不等于仿真/板卡可用 |
| 容器启动失败（本地记录 `results/ab-d1-container-20261107/result.json`） | Docker 启动命令、退出码、错误输出 | FAIL，不把仍不可访问的 daemon 当成备用环境 |
| [上游审查](UPSTREAM_BASELINE_REVIEW.md)、[平台报告](PLATFORM_INVENTORY.md) | 版本来源、下载规模、配置与平台前置条件 | 来源审查与本地运行结果分开 |
| [AI 任务记录](../experiments/AB_D1_20261107.json) | 委派职责、输入版本、边界与未提供的计量字段 | 未开展受控 AI 成对实验；人工接收 NOT_RUN |

运行器自测在 Ubuntu WSL 执行：6 项通过、1 项 Windows 专属测试跳过，覆盖原始退出码/日志保存、超时子进程组终止、目录防覆盖、路径限制和 PASS 判定；完整工具返回（本地记录 `results/ab-d1-validation-20261107/runner-tests.log`）。这些是脚本自测，不是 Vortex kernel 测试。首轮实际预检 summary.json（本地记录 `results/ab-d1-simx-preflight-20261107/summary.json`） 为 BLOCKED，且 `upstream_smoke=NOT_RUN`；同时记录了跨 NTFS 的 Git 检查超时，后续将身份检查上限增至 120 秒并保留旧结果。

最终版已在 WSL 完成复测：v2 预检证据（本地记录 `results/ab-d1-simx-preflight-20261107-v2/summary.json`）。3329 项源码哈希全部相符，Git 提交/源码差异/子模块检查退出 0，配置与 lock 哈希一致。最终状态仍为 **BLOCKED**，原因是真实的 glibc、CMake、Vortex 编译工具/库、Ramulator 三项离线依赖，以及宿主 C++20 编译探针失败；没有创建 Vortex build 目录或执行 demo。根目录 WSL 命令返回非零，脚本 JSON 保留每个子命令的实际退出码；两者分别记录。

源码快照由另一实施角色独立核对过提交和哈希关系，但这不是 C/E 的实际运行接收。第一版源码快照保留；v2 增加了“公共配置不含 backend 附加宏”的说明，当前 configs 对应 v2。

## 可以重跑的入口

在独立项目根目录 `D:\Vortex-U280`（Linux/WSL 对应 `/mnt/d/Vortex-U280`）执行。每次换新的 `run-id`，已有目录拒绝覆盖。

```powershell
# Windows：重新记录固定源码身份及候选配置，不能代替仿真。
python -B scripts/capture_target.py --run-id ab-source-NEW

# 在已获准使用的 WSL 中仅收集环境，输出文件不能已存在。
wsl -d Ubuntu-20.04-D --cd /mnt/d/Vortex-U280 -- python3 -B scripts/platform_inventory.py --output results/platform-NEW.json
```

仿真脚本需要 **Linux x86_64、glibc >= 2.35、可用 C++20 宿主编译器、CMake，以及固定候选工具包**。先在兼容宿主准备依赖；`--tooldir` 指向真实安装目录。脚本不会自行下载或安装组件。

```bash
# Linux 工作区根目录；先检查真实依赖，缺项写 BLOCKED。
python3 -B scripts/run_native_smoke.py \
  --backend simx --tooldir /absolute/vortex-tools \
  --run-id ab-simx-preflight-NEW --check-only

# 预检无阻塞后实际构建并运行；每轮保留独立 build 和原始日志。
python3 -B scripts/run_native_smoke.py \
  --backend simx --tooldir /absolute/vortex-tools \
  --run-id ab-simx-NEW

# 完整处理器 RTL 冒烟，另需已核实的 Verilator。
python3 -B scripts/run_native_smoke.py \
  --backend rtlsim --tooldir /absolute/vortex-tools \
  --run-id ab-rtlsim-NEW
```

工具包候选固定为 `8c64cf921d3c6c456e80f00d24482d0aa2153a82`，不能仅写会变动的 `v3.0.1` 标签。SimX 需要约 578.75 MiB 压缩下载，RTL 的 Verilator 增量约 108.61 MiB；实际解压与构建空间另计。固定下载来源与依赖列表见上游审查。Ramulator 的 yaml-cpp、spdlog、argparse 必须预先准备；运行器使用离线构建，避免构建时隐式下载。

## 下一轮按此顺序

1. A/C 先提供或建立可用的 Ubuntu 22.04+ x86_64 构建环境。可以是独立 VM/容器/服务器；无需升级已有 Ubuntu 20.04。当前 Docker 引擎未就绪，不继续用重复启动来掩盖问题。
2. 在隔离工具目录准备上述完整 SHA 的最小工具集，保存下载归档与实际二进制哈希、版本和依赖。重跑预检，再运行最小原生 SimX；失败保留首错和全部日志。
3. 同版本、同配置跑处理器 RTL；再补 XRT AFU 仿真。`rtlsim` 不覆盖整个 XRT 平台，不能计作 AFU 或上板通过。
4. 与 C/E 接入独立的 copy/vadd/affine u32 边界集；项目默认 B=32 使用另一个明确的配置候选，例如 1c4w8t，并重新验证。上游 signed-int demo 不证明模 2^32 溢出、尾线程或假谓词无访存。
5. B 在权限提供后，先运行盘点并核对 U280 `HBM[0:31]` 与 CP 的 `HOST[0]`。仅在工具/platform/内存通路事实齐备后确定 FPGA 配置与构建；FPGA 时序/资源、xclbin 和真实运行分别验收。

本轮没有实际 kernel 输出、周期性能、资源/时序报告或 xclbin，不填推测值。现有 Icarus 以及历史 AEC/FIFO 结果不计入本项目的功能证据。
