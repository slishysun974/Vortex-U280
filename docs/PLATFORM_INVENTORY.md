# A/B 平台盘点

2026-11-09 D7：**B 的两 CPU 小型 AFU 组件综合与实际 U280 综合许可 PASS，8 张卡的 XRT 查询 PASS**；采集时均 ready/空闲，HOST[0] 的 `host_mem_size` 均为 0。[184/184 收尾核验](../results/ab-d7-closeout-20261109-v1/result.json)退出 0，详见 [D7 记录](AB_D7_PROGRESS.md)。用户允许自行选择空闲卡和少量线程构建，无需固定分卡或书面额度；大型综合/布局布线前再确认资源与规则。当前待办是 HOST 通路、完整 FPGA 配置/构建与板上功能。

D6 已确认 CentOS 7.9/glibc 2.17、Vivado/v++ 2023.1、XRT/驱动 2.13.479 和已安装 U280 platform。D7 补实际 shell/接口 UUID、两 CPU 综合及许可证签出。当前目录 `/home/u280user/vortex-u280-probes/<run_id>` 可写；旧 D1–D6 未登录/待分卡陈述仅为当时事实。

基础盘点入口：`scripts/Collect-U280Inventory.ps1 -ToolChecks`；D7 卡状态与小型构建入口：`scripts/Invoke-U280Preflight.ps1`，在本机 SSH 提示输入密码。三轮均用独立 run_id、原始 stdout、采集器/环境脚本哈希和子命令退出码保留证据。以下 D1/D2/D5 的“未登录”“工具未盘点”等陈述仅描述历史，不作为最新状态。

2026-11-08 22:19 接续：用户在终端改用另一个密码，U280 `u280user` 密码认证 PASS；WLAN 绑定连接 `192.0.2.28:22`，`id -un && hostname` 返回 `u280user` / `localhost`、SSH 退出 0。工具和设备尚未盘点，获配卡待确认；见 当前登录状态（本地记录 `docs/U280_LOGIN_PROGRESS.md`）。下列较早网络和未登录结论保留为历史事实。

2026-11-08 D5 更新：专用 WSL 已完成三路原生 B=32 候选回归，各 152/152 次启动 PASS，见 [D5](AB_D5_PROGRESS.md)。老师 ZIP 明确给 `192.0.2.28:22`；本机在 21:21 授权执行的 TCP 检查 5.026 秒超时，未登录、未查询设备，见 实际记录（本地记录 `results/ab-d5-u280-network-20261108-v2/probe.json`）。当前需核实校内网/VPN条件并落实个人用户名与获配卡，不能据此判定服务器故障。以下 D2/D1 段落是历史盘点，暂停说明不是当前工作状态。

2026-11-08 更新：已授权建立独立 `Vortex-AB-Ubuntu-22.04` WSL，安装构建依赖并运行固定工具包。实测 glibc 2.35、G++ 11.4.0、CMake 3.22.1、Python 3.10.12；新环境盘点（本地记录 `results/ab-d2-newhost-20261108-v1.json`）。原生 SimX 上游整数 demo 已运行通过，证据与边界见 [D2 记录](AB_D2_PROGRESS.md)。原 Ubuntu 20.04 未升级，Docker 本轮仍不可连接；U280 访问仍 BLOCKED。本轮收尾后按用户要求暂停。

以下为 D1 历史盘点，保留原始事实和失败记录，不作为当前新 WSL 的版本表。

日期：2026-11-07（Asia/Shanghai）。本页区分本次实测、历史记录与待核实项。盘点成功只表示采集完成，不表示 SimX、RTL 或 U280 已通过。

**当前结论：A 线仍需补齐可运行的 Linux 工具链；B 线上板受访问权限阻塞。** 用户已明确目前没有 U280 访问权限，之后提供。现有课程服务器不视作 U280 入口，也没有为本轮提交新远程作业。

2026-11-07 补充：已收到老师提供的服务器/U280 资料，记载 CentOS 7、8 张 U280、Vivado/Vitis/HLS 2023.1、XRT 2.13.479 和 `xilinx_u280_gen3x16_xdma_1_202211_1`，并提供新的服务器连接线索。详见 原件与核对说明（本地记录 `docs/TEACHER_U280_REFERENCE.md`）。这些是外部资料记载，尚未登录核实；账号/分配卡、版本配套与 HOST[0] 条件仍待确认，原有实测记录与执行状态不据此改为通过。

## 本次实测

| 项目 | 本次事实 | 边界 / 证据 |
|---|---|---|
| Windows Python / Git | Python 3.13.13；Git 2.53.0.windows.2，版本命令退出 0 | Windows 原始输出与路径（本地记录 `results/ab-d1-platform-20261107/windows_inventory.json`） |
| Windows C/C++ / Make | w64devkit GCC/G++ 15.2.0；GNU Make 4.4.1，版本命令退出 0 | Windows MinGW 工具不是已验证的 Linux Vortex 构建环境 |
| Windows PATH | 未发现 cmake、ninja、Verilator、Icarus/vvp、Vivado、Vitis、v++、xbutil、xbmgmt；发现 Docker CLI | 仅检查当前 PATH，不代表磁盘上不存在安装 |
| 磁盘可见空间 | 采集时 C 盘约 70.9 GiB、D 盘约 208.1 GiB 空闲 | 动态数值以 JSON 的字节数和采集时间为准；未确认 WSL 配额与 FPGA 构建需求 |
| WSL 发行版 | 主进程本次列出 Ubuntu-20.04-D、Ubuntu-20.04、docker-desktop | 只有 Ubuntu-20.04-D 取得下列系统版本，不由名称推断另两个环境内容 |
| Ubuntu-20.04-D | 主进程实测 Ubuntu 20.04.6 LTS、glibc 2.31、G++ 9.4.0；`cmake` 未找到，组合查询退出 1 | 本次 WSL 工具返回（本地记录 `results/ab-d1-host-20261107/wsl-version-probe.log`）；不是 SimX 运行结果 |
| Linux 完整盘点 | 主进程实际运行本次脚本退出 0；16 逻辑 CPU、MemTotal 16,117,828 KiB（约 15.37 GiB）、Make 4.2.1、Python 3.8.10、Icarus 10.3、Git 2.25.1 | 完整 Linux JSON 与每项命令输出（本地记录 `results/ab-d1-host-20261107/linux_inventory.json`）；未跑编译/仿真业务 |
| Linux 缺项 | 当前 PATH 缺 cmake/ninja/Verilator/yosys/ccache；dpkg 查询只确认 build-essential 与 zlib1g-dev 已安装，其余所查开发包未安装或未找到 | 缺项见 JSON；未安装任何包 |
| Linux FPGA 安装线索 | `/opt/Xilinx` 下可见 Vitis、Vivado、Vitis_HLS 等目录，`/opt/riscv` 存在；FPGA 工具未在当前 PATH 暴露；未见 `/opt/xilinx/xrt`；未见可见 Xilinx PCI 设备 | 目录存在不能证明具体版本、许可或程序可用；WSL 未见 PCI 卡不能证明物理主机无卡 |
| Docker | CLI 29.5.2；启动现有 Desktop 超时退出 1，随后 Server 查询为 null 且 Linux daemon pipe 不存在 | 主进程实际失败记录（本地记录 `results/ab-d1-container-20261107/result.json`）；未拉镜像、未创建容器，不重复启动或修改系统 |
| 资源查询限制 | 子智能体沙箱内 WSL 与 Windows CIM 查询被拒；随后 WSL 授权请求被中止，无执行输出 | 失败/未执行记录（本地记录 `results/ab-d1-platform-20261107/probe_attempts.json`）；729.6 秒是等待审批时长，不是 WSL 启动耗时 |
| U280 | 用户确认当前无权限 | access=BLOCKED；设备/驱动查询、构建、上板、恢复=NOT_RUN |

本页的 WSL 和 Docker 新事实由主进程本轮实测提供；子智能体未执行已取消的 WSL 命令。总机器可读索引为 result.json（本地记录 `results/ab-d1-platform-20261107/result.json`）。完整 Linux JSON 与首轮失败记录并存。Linux JSON 的中文路径经显式 UTF-8 解码核查正确；个别控制台默认解码会造成显示乱码，读取时指定 UTF-8。脚本现默认输出 ASCII JSON 转义，便于跨 Windows/WSL 控制台读取。

## SimX 环境判断

候选源码的 [安装说明](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/docs/install_vortex.md) 以 Ubuntu 22.04 为 Ubuntu 路线，列出 build-essential、cmake、ccache、zlib/tinfo/ncurses/uuid/Boost serialization/PNG/hwloc 开发包。当前 Ubuntu-20.04-D 已完成只读盘点，可继续核查既有 `/opt/riscv` 工具身份；它缺多项依赖，尚不是可交付的 SimX 环境。

最佳下一环境是独立的 Ubuntu 22.04 或与选定工具包实际依赖匹配的更新 Linux，不自动升级现有 WSL。现有 Docker 是隔离环境的候选载体，但本次启动失败，不能按可用容器继续。若继续使用 Ubuntu 20.04，应先验证工具包 ELF 的 glibc/C++ 依赖与缺包情况，或评估兼容源码构建；不能把 glibc 2.31 直接认定满足 v3.0.1 预编译工具包。工具包版本号本身也不能证明所有二进制的最低 glibc 要求。

SimX 优先级：固定源码及配套工具包 → 取得可用 Linux → 补齐隔离依赖 → 原生程序编译/运行 → oracle 比较。版本查询、源码下载、CPU 答案生成均不算 SimX PASS。

## D1 历史阻塞清单（最新以 D7 接收单为准）

| 项目 | 当前状态 | 下一份证据 / 负责人 |
|---|---|---|
| 板卡访问、账号与排期 | BLOCKED：用户尚无访问权限 | 用户/资源方提供正式入口和授权范围；B 记录分配时段 |
| U280 型号、BDF、shell UUID | NOT_RUN | B 在分配节点只读查询，不使用文档示例 BDF |
| Vitis/Vivado 与许可 | NOT_RUN | B 记录真实路径、版本、许可可用性与构建配额；仅存在目录不算工具可运行 |
| XRT、驱动、platform | NOT_RUN | B 核实 runtime/driver、`platforminfo` 与实际 shell 对应关系 |
| host-memory / HOST[0] | NOT_RUN，硬件路线前置检查 | B/C 核实 platform 实际暴露 HOST[0]/host bridge、当前启用状态、主机 CMA/huge-page 条件，以及所选源版本连接文件与 buffer 分配逻辑 |
| HBM / 地址映射 | NOT_RUN | B/C 读取实际平台 bank 与链接结果；不填猜测的 HBM 地址或 pointer 位宽 |
| FPGA 构建资源 | NOT_RUN | B 取得 CPU/内存/磁盘配额及可用时间；不能把整机容量当个人配额 |
| 完成与恢复 | NOT_RUN | B/C 验证末次写入可见、重复运行、超时后隔离/恢复；未验证前不承诺安全 abort |

候选源码的 [FPGA 指南](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/docs/fpga_setup.md) 明确硬件 CP 从 host memory 取命令环和控制缓冲，未启用 host bank 时设备打开可能失败。HOST[0] 是否可用必须按实际 platform 核实。指南中的开启操作需要管理员权限并改变设备配置；本轮没有执行，也不把只读盘点脚本设计成开启它。`hw_emu` 的 host memory 模型不替代真实卡的检查。

旧赛题指定的 Vivado/Vitis 2022.2、XRT 2.13.479 不沿用为当前固定依赖；以最终选定 Vortex 与真实平台的兼容证据为准。

## 可重跑盘点入口

[platform_inventory.py](../scripts/platform_inventory.py) 使用 Python 3.6+ 标准库。默认只读，无网络、无 sudo、无安装、不加载环境脚本、不启动商业 EDA 工具、不配置或复位板卡。每条外部命令默认最多 8 秒，允许 1—30 秒；命令不存在、退出错误和超时各自记录。输出包含 OS、CPU 可见量、内存/cgroup 限制、磁盘、编译器/仿真器版本、软件包、有限目录列表、工具路径和 Xilinx PCI 可见性；不读取凭据或完整环境变量。

在已有授权的 Linux 终端，从工程根目录执行：

```bash
python3 scripts/platform_inventory.py --timeout 8 > platform-inventory.json
```

若希望脚本避免覆盖旧证据，用全新的文件名；`--output` 采用独占创建，已存在时停止：

```bash
python3 scripts/platform_inventory.py --timeout 8 --output platform-inventory-new.json
```

只有在获准访问的板卡节点才追加 `--include-device-query`，这只运行 `xrt-smi examine` 或 `xbutil examine`，不执行 configure、reset、program、validate 或管理操作。缺工具时写 BLOCKED，查询失败写 FAIL。默认设备查询为 NOT_RUN。脚本总状态 PASS 仅表示采集完成，每项结果仍需独立解读。

脚本已通过 Python 语法解析；Windows 运行按设计返回 `linux_required`（exit 2），见 guard 结果（本地记录 `results/ab-d1-platform-20261107/script_windows_guard.json`）。主进程在 Ubuntu-20.04-D 以 `--timeout 5` 实际运行退出 0，原始结果见上述 Linux JSON；这是非作者执行盘点的证据，仍不替代工具链与板卡接收。

## 远程入口与后续接收

U280 入口来自 老师资料（本地记录 `docs/TEACHER_U280_REFERENCE.md`），本项目已完成实际登录、设备查询和小型综合；完整板上程序仍 NOT_RUN。此前课程服务器与该 U280 服务器的关系未确认；旧项目的连接脚本、代理和 SSH 辅助材料未迁入，也不作为本项目依赖。

按共享规则重新检查空闲卡，以实际 BDF/UUID 准备 HOST 通路和完整 FPGA 配置；大型综合/布局布线前确认资源和作业规则。现有盘点仅证明当时环境的采集事实，不能替代工具链、仿真或 U280 接收。
