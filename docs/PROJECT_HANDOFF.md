# Vortex-U280 项目交接

2026-11-09 GitHub 公开快照收录项目源码、配置、D13 文档和选定记录。服务器及工作站标识使用示例值。标记为本地记录的文件由原工作区保管。公开快照中的证据范围见 [索引](../results/README.md)。

2026-11-09 文档交接：已新增[通俗版阶段进展报告](PROJECT_PROGRESS_REPORT_20261109.md)，用于了解项目已完成工作、验证范围与下一步。报告汇总截至 D13 的已有证据，本次未重跑实验或改变技术状态；HOST 权限与 TIMING-7 仍阻塞，实际时钟待加载后核实，板上功能及 PTX 设备执行仍 NOT_RUN。后续继续按下述 D13 结论推进。

2026-11-09 D13 最终：**DCP 采集/静态归因审阅完成，53/53 检查 PASS；HOST 与 TIMING-7 仍阻塞，上板 NOT_RUN。** v2 两份 Vivado 718.449/435.335 秒均退出 0，20:13:13 采集结束。8 项 Critical Warning 在原始平台中已有，新增 1 项为 200 MHz 可调时钟约束；TIMING-14 的 20 个 fanout 及 12 条 clock-group 命令/作用域与基线一致，7 项记录为已审阅的平台保留项。**TIMING-7 仍显示 Partial False Path (unsafe)**，不能用基线相同/正余量直接关闭；TIMING-1 仍需加载后实际 200 MHz。10 个缺 delay 端口与基线逐项一致、内部未约束端点均为 0。HOST 因 `u280user may not run sudo on localhost` 未执行配置；不要重复尝试 sudo 密码。用户要求先解释结果与最小需求，再自行申请权限。详见 [D13](AB_D13_PROGRESS.md)、[最终审阅](../results/u280-readiness-review-20261109-v2/result.json)、[管理员操作](../environment/u280-fpga/HOST_SETUP.md)。152 次原生输入离线准备 PASS，Linux 自测 117 通过/1 跳过，固定源码 3329 项零差异；旧失败原件保留，不重复 link。

2026-11-09 D12 最新：**服务器 runtime200 编译/依赖检查 PASS；上板就绪 BLOCKED，板上功能 NOT_RUN。** v4（本地记录 `results/u280-runtime-20261109-v4/probe.json`） 于 19:33:31 完成，SSH/采集退出 0；GCC 9.3.1 / glibc 2.17 / XRT 2.13.479，公共库 10.833 秒、真实 XRT backend 1.420 秒，两个库 ldd 通过并已返回本地。采用独立 `gcc9-vm-allocation-v1` / binding-v2：检查两处 VM 地址分配失败，避免未初始化变量；生成 Makefile 只在缺少固定 XCONFIGS 时运行生成器；入口先加载 XRT setup。v2 编译失败、v3 依赖失败、v1 终端接入中止原件保留。8 卡当次 ready/无 KDS 在途任务，HOST 仍为 0、sudo 权限未确认。D11 机器摘要空表/关键告警零计数是目录页截断缺陷，新 [报告审阅](../results/u280-timing-review-20261109-v2/result.json)已纠正并核对总数：methodology 100 项中的 9 项 Critical Warning 全部 OPEN，普通 DRC 343 项无 Error/Critical Warning；旧结果不改。最终自测 113 通过/1 跳过，退出 0。[D12](AB_D12_PROGRESS.md)、[服务器库位置/入口](../environment/u280-fpga/RUNTIME.md)、[补丁](../environment/u280-fpga/PATCHES.md)。下一步 HOST 权限/预留、平台约束告警与缺 delay 全端口核实、受控加载后 UUID/实际时钟，再做原生上板；无需重编 link。固定源码、根 lock/caps 和全部旧证据保留。

2026-11-09 D11 最新：**归档与 runtime200 本地准备 PASS；上板就绪 BLOCKED、板上功能 NOT_RUN。** v5（本地记录 `results/u280-archive-20261109-v5/probe.json`） 已将完整 xclbin 与 197 份原始报告取回本地并校验，见 本地 xclbin（本地记录 `results/u280-archive-20261109-v5/returned/artifacts/vortex_afu.xclbin`）。整体时序 WNS +0.016 ns / WHS +0.006 ns，kernel 00 保持 +0.119/+0.009 ns，布线错误 0；**9 项 methodology Critical Warning** 尚未关闭，特别是 5 ns 约束和时钟模块默认 3.333 ns 的差异。新 runtime200 输入包（本地记录 `results/u280-runtime-prepare-20261109-v1/result.json`） 仅将宿主编译频率 400→200，Ubuntu 公共库编译 PASS；服务器 GCC 9.3.1 与六个 XRT 头文件实际存在，但真实服务器编译仍 NOT_RUN。脚本自测 103 通过/1 跳过，退出 0。网络 WinError 10013 经只读 WFP 排查发现 Surfshark Local network visibility 残留规则；用户刷新开关后两条路径 SSH 握手恢复、v5 登录/归档成功。v1-v4 原件保留。下一步按 [D11](AB_D11_PROGRESS.md) 和 [runtime 构建说明](../environment/u280-fpga/RUNTIME.md) 编译服务器库并核实平台告警/HOST/当前空闲卡；不重复提交 link，不再下载已有产物，固定源码和根 lock/caps 未修改。

2026-11-09 15:56:47 最终复核：**D10 完整 FPGA 构建 PASS**。原作业 `u280-link-20261109-103830-671` 于 **15:48:08** 完成，v++ 18565.056 秒、退出 0、未超时，固定 200 MHz clock_check 退出 0（setup WNS +0.119 ns、hold WHS +0.009 ns，289539 endpoints）。最终采集（本地记录 `results/u280-link-20261109-155638-456/probe.json`）、[D10](AB_D10_PROGRESS.md)。服务器产物 `/home/u280user/vortex-u280-builds/u280-link-20261109-103830-671/out/vortex_afu.xclbin` 为 53,950,442 字节，SHA-256 `bbac2ab73073b24ba857fb34eadf22bf1c11dc745527f064c4eec61b70d2c843`；尚未下载到本地。worker 退出 0、作业已结束，不必重新提交构建。下一步归档完整报告/元数据，准备 HOST 通路、兼容的服务器 runtime 和实际 200 MHz 频率绑定，再进行原生上板；HOST 配置、板卡加载、板上功能均 NOT_RUN。

2026-11-09 15:27:25 最新复查：D10 原作业 `u280-link-20261109-103830-671` **RUNNING，布线完成、bitstream 生成中**。新采集（本地记录 `results/u280-link-20261109-152717-495/probe.json`）观测 worker/v++ 存活约 4 小时 49 分；15:02:52 routing 完成并开始 bitstream generation，可选布线后物理优化随后显示完成。最终 xclbin/v++ 退出码/固定时钟检查仍未取得，不能提前记录完整构建 PASS；继续查询同一 BuildRun。

2026-11-09 15:01:35 最新复查：D10 原作业 `u280-link-20261109-103830-671` **RUNNING，布线后时序分析中**。新采集（本地记录 `results/u280-link-20261109-150126-730/probe.json`）观测 worker/v++ 存活约 4 小时 23 分；日志 15:00:18 为 `Phase 12 Post Router Timing`。尚无 routing 整体完成、最终 xclbin 或固定时钟检查 PASS；后续只读查询同一 BuildRun，不将该时序分析阶段当成时序已达标。

2026-11-09 14:31:52 最新复查：D10 原作业 `u280-link-20261109-103830-671` **RUNNING，布局完成、正在布线**。新采集（本地记录 `results/u280-link-20261109-143143-780/probe.json`）观测 worker/v++ 存活约 3 小时 53 分；14:18:55 placement 完成并启动 routing，14:31:42 为 `Phase 4 Rip-up And Reroute / Phase 4.1 Global Iteration 0`。仍待布线、最终产物和固定时钟检查结果，后续查询同一 BuildRun，不重启构建。

2026-11-09 14:14:55 最新复查：D10 原作业 `u280-link-20261109-103830-671` **RUNNING，布局收尾清理中**。新采集（本地记录 `results/u280-link-20261109-141448-833/probe.json`）观测 worker/v++ 存活约 3 小时 36 分；最新日志 14:10:45 为 `Phase 4.4 Final Placement Cleanup`。较前次全局布局持续推进，但尚无布局完成或开始布线的确认，更无最终 xclbin/时钟检查 PASS；后续查询同一 BuildRun。

2026-11-09 13:47:27 最新复查：D10 原作业 `u280-link-20261109-103830-671` **RUNNING，正在全局布局**。新采集（本地记录 `results/u280-link-20261109-134719-960/probe.json`）观测 worker/v++ 存活约 3 小时 9 分；最新日志 13:47:15 为 `Phase 2.5.1 UpdateTiming Before Physical Synthesis`，较 13:14 布局初始化继续推进。布线、最终产物与固定时钟检查仍未取得完成结果，继续只读查询同一 BuildRun。

2026-11-09 13:14:26 最新复查：D10 原作业 `u280-link-20261109-103830-671` **RUNNING，正在布局**。新采集（本地记录 `results/u280-link-20261109-131419-048/probe.json`）显示 13:13:02 逻辑优化完成并启动 placement，13:14:04 处于 Placer Initialization；worker/v++ 存活约 2 小时 35 分。后续还需布线、产物生成、固定时钟检查；尚无最终 xclbin PASS。继续只读查询同一 BuildRun。

2026-11-09 12:37:02 最新复查：D10 原作业 `u280-link-20261109-103830-671` **RUNNING，已由综合进入实现**。新采集（本地记录 `results/u280-link-20261109-123654-150/probe.json`）显示 12:34:27 模块级综合 156/156 完成，12:36:11 顶层综合结束并启动 `impl`；worker/v++ 存活约 1 小时 58 分。最终实现/时钟检查/xclbin 仍未取得，继续只读查询同一 BuildRun，不重启构建。

2026-11-09 11:27 最新复查：D10 原作业 `u280-link-20261109-103830-671` **RUNNING，仍在综合**。新采集（本地记录 `results/u280-link-20261109-112701-720/probe.json`）观测 worker/v++ 存活约 48 分半；日志 11:26:49 为模块级综合 49/156 完成、2 个运行，持续推进，尚未进入布局布线。完整结果/xclbin 未取得；后续只读查询同一 BuildRun，保留旧快照。

2026-11-09 10:50:53 最新复查：D10 作业 `u280-link-20261109-103830-671` **仍在综合，RUNNING**；采集目录（本地记录 `results/u280-link-20261109-105044-191/probe.json`）为只读 Status，SSH 退出 0，没有新建远端构建。worker/v++ 运行约 12 分钟，日志 10:50:29 为 block-level synthesis 9/156 完成、2 个运行，尚未进入布局布线。后续仍查询同一 BuildRun；尚不能报告最终 xclbin、时序或板上 PASS。此前启动快照保留。

2026-11-09 D10：**完整 link 已实际启动，启动快照 RUNNING**。用户“按此启动”已授权 [方案](../environment/u280-fpga/NEXT_LINK.md)。作业 `u280-link-20261109-103830-671` 于 10:38:41 启动，10:38:44 SSH 退出 0；实际观测到 `v++ --link` PID `95311`（worker `95131`、builder `95132`），CPU affinity `[0,1]`、nice +10、6 小时 v++ 超时，无 RAM 硬限。RAM 约 329.7 GiB/磁盘 720.9 GiB 可用，输入/XO/平台身份核验通过；启动证据（本地记录 `results/u280-link-20261109-103830-671/probe.json`）、[D10](AB_D10_PROGRESS.md)。Linux 93 项 Python 自测通过、1 跳过，退出 0。远端目录分别在 `~/vortex-u280-link-jobs/<run_id>` 和 `~/vortex-u280-builds/<run_id>`；查询 `scripts/Invoke-U280Link.ps1 -Mode Status -BuildRun u280-link-20261109-103830-671`，用户仅在本机输入 SSH 密码，无需再次授权资源。此快照不是实时完成状态，完整结果/xclbin 尚未取得；不能重复启动已有目录，也不能将传输 PASS 当成构建 PASS。

2026-11-09 D9：**真实 U280 XO PASS**。成功运行 `u280-preflight-20261109-100406-629` 的 SSH/Vivado 均退出 0，Vivado 340.708 秒；五个 IP OOC DCP/stub、U280 RTL elaboration、原模块接口 gate（13 类/22 个实例）及打包通过。服务器 XO 路径 `/home/u280user/vortex-u280-builds/u280-preflight-20261109-100406-629/out/vortex_afu.xo`，312,868 字节，SHA-256 `58ff5ed950d738f232f5fa70e4c4fcf82ebd2b73bb3d247cfc00133f51e66b0d`。首次 `095402` 缺 stub 失败原件保留；独立 `ip-ooc-v1` 仅修改新目录 Tcl `flow/`，gate 保持 error，固定源/根配置/D8 输入包未改。最新 HOST/platform 采集 `u280-preflight-20261109-094621-277` PASS，XSA↔8 卡 shell UUID 匹配；HOST 内存均为 0，sudo 需要密码，权限未确认。Linux 87 测试通过/1 跳过，[174/174 最终核验](../results/ab-d9-closeout-20261109-v1/result.json)通过，固定源 3329 文件零差异。[D9](AB_D9_PROGRESS.md)、[补丁](../environment/u280-fpga/PATCHES.md)、[下一阶段具体命令与资源方案](../environment/u280-fpga/NEXT_LINK.md)。完整综合/布局布线仍须先按既有要求确认资源；xclbin/板上功能未完成。

2026-11-09 D8：**独立 U280 FPGA 候选/实际源预处理 PASS**，见 [D8](AB_D8_PROGRESS.md)。已发现原始 U280 分支的 32 个 HBM 主接口只有端口 0 有显式连接；新 `u280-hbm32-v1` 候选启用合并接口，生成 1 个 HBM 主接口和 HOST 主接口并与连接一致。已交付 288 项 RTL 输入包与 [分阶段构建入口](../environment/u280-fpga/README.md)，[635/635 收尾核验](../results/ab-d8-closeout-20261109-v1/result.json)退出 0、Python 78 通过/1 跳过。根配置、D5、固定源码未改。本轮 SSH 在密码认证阶段退出 255，远端 HOST/platform 复查 NOT_RUN。完整 FPGA 综合/上板仍待完成，200 MHz 只是候选目标。

2026-11-09 D7：**B 的两 CPU 小型 AFU 组件综合与实际 U280 综合许可 PASS，8 张卡的 XRT 查询 PASS**；采集时均 ready/空闲，HOST[0] 的 `host_mem_size` 均为 0。[184/184 收尾核验](../results/ab-d7-closeout-20261109-v1/result.json)退出 0，详见 [D7 记录](AB_D7_PROGRESS.md)。用户允许自行选择空闲卡和少量线程构建，无需固定分卡或书面额度；大型综合/布局布线前再确认资源与规则。当前待办是 HOST 通路、完整 FPGA 配置/构建与板上功能。

本轮按用户要求优先 A/B，D6 见 [进展记录](AB_D6_PROGRESS.md)。**A：SimX 与处理器 RTL 各 15/15 原生 LSU trace 用例 PASS，每路 704 个数组 lane 地址/计数匹配，N=0/全假无数组请求。B：三轮实际 SSH 盘点与四项工具/platform 命令 PASS、退出 0。** Vivado/v++ 2023.1，XRT/XOCL/XCLMGMT 2.13.479；已安装 platform 解析出 HBM[0..31]/HOST[0]。D6 当时的分卡/许可待办已由 D7 的共享授权、实际组件综合与卡观察推进；HOST 通路和上板仍未接收。[228/228 收尾核验](../results/ab-d6-closeout-20261108-v1/result.json)通过；SimX 首轮解析器错误保留，修正后 v2 使用同一隔离 debug 构建重新执行，程序/runtime/配置前后哈希一致。Linux 最终 72 测试通过/1 跳过。这些仍非 PTX 设备或 E 独立接收。

更新日期：2026-11-09，Asia/Shanghai。D5 已完成独立 8w×4t 候选的原生 B=32 回归：SimX、处理器 RTL、NOXRT AFU 模型各 152/152 次启动 PASS，含每路 122 次 B=32，B=33/64 拒绝；见 [D5 记录](AB_D5_PROGRESS.md) 与 [84 项收尾核验](../results/ab-d5-closeout-20261108-v1/result.json)。默认 4w×4t lock/caps 和 D4 证据未改。这些是 A/B 同作者 reference 自测，P0 与独立接收仍待完成。

前一轮推进 C/D 前端：新增严格 PTX parser、typed IR、参数布局/packer、C++ 语义代码和源码映射，采用独立 `ptx-vx-p0-v0.2-draft`。[最终 v3](../results/ptx-frontend-host-20261108-v3/summary.json) PASS、退出 0：69 Python 测试通过/1 跳过，661/661 宿主用例通过，假谓词提前 load 故障被检出；[174 项收尾](../results/ptx-frontend-closeout-20261108-v1/result.json) 通过，前两轮失败保留。入口、版本限制与接收说明见 [前端记录](PTX_FRONTEND_PROGRESS.md)。输出明确不可装载；Vortex wrapper、vxbin 打包、项目 runtime 与 PTX 设备执行仍未完成，不改变 D5 原生或板卡状态。

## 目标与分工

基于开源 Vortex 建立可复现的 U280 GPGPU，开发 PTX P0 子集前端和语义转换，复用配套后端/runtime，记录功能验证与 AI 协作实验。A 负责架构/RTL，B 负责平台/U280，C 负责后端/runtime，D 负责 PTX 前端，E 负责独立答案、验收与 AI 实验。首期 kernel 为 copy/vadd/affine。

## 已有事实

- Vortex v3.0 提交：`7fe19369587c087f902c3e2bc2add612aa910a95`，位于 `upstream/vortex/`。
- 配套工具包提交：`8c64cf921d3c6c456e80f00d24482d0aa2153a82`；D3 在原 SimX 四组件上增加固定 Verilator，共 18 个分卷/单包，保存 Git blob、SHA-256 和重组归档。实际 Clang 20.1.8、RISC-V GCC 12.2.0、Verilator 5.050；专用宿主补齐 ccache 4.5.1。
- softfloat 和 ramulator 子模块已取得；另三个顶层子模块尚未初始化。不能把未取子模块当成迁移丢失。
- 源码身份和候选配置解析已核验，v2 清单记录 3329 项文件哈希；现有结果见 `results/ab-d1-source-20261107-v2/`。
- 初始 smoke 候选为 RV64 / 1 cluster / 1 core / 4 warps / 4 threads。它不是 B=32 的 P0 验收配置。
- 已授权创建独立 `Vortex-AB-Ubuntu-22.04` WSL，磁盘位于本项目 `environment/wsl/`。实测 glibc 2.35、G++ 11.4、CMake 3.22.1；原 Ubuntu 20.04 未升级。
- 原生 SimX **PASS**：RV64 / 1c / 4w / 4t，上游整数 demo 的 16 个元素内部比较通过；构建/运行命令均退出 0，原始日志有 `PASSED!`。[完整证据](../results/ab-d2-simx-20261108-v2/summary.json)。这不是 E 的独立 P0 答案接收。
- D3 处理器 RTL **PASS（仅上游整数 demo）**，同 RV64 / 1c / 4w / 4t，16 个整数；[实际运行](../results/ab-d3-rtlsim-20261108-v2/summary.json)。首轮因固定 Verilator Makefile 需要 ccache 而构建失败、demo NOT_RUN；补齐依赖后换新目录通过，失败记录保留。
- 已有源码核查、平台盘点、离线依赖准备、工具包下载/提取与原生运行入口；运行器支持独立 `--source`、`--ramulator-deps`、`--build-dir`、显式 `xrtsim` 模型和 `--native-boundary`。D4 最终 Linux 自测 23 通过/1 跳过；Windows 边界版本自测 18 通过/5 跳过，最后一项状态显示修正另在 Linux 验证。
- D3 本地 AFU RTL 模型 **PASS（仅 NOXRT/XRTSIM 整数 demo）**；[实际运行](../results/ab-d3-xrtsim-20261108-v1/summary.json)。三路 `kernel.vxbin` 哈希一致，内部比较均通过，不计作独立答案接收或时序等价。
- D4 三路 **PASS（仅原生 u32 自测）**：每路 70 个参数用例、两组输入、140 次连续启动；覆盖 copy/vadd/affine、u32 溢出、N=0 与尾部、B=1/4/7/16、条件写与 buffer 偏移/复用。运行前 reference 与实际输出完整保留；三路 kernel/语料/捕获一致。B=32 在本配置被原生 runtime 拒绝，不能接收为 P0 默认 launch。
- `configs/target_lock.json` 与 `target_caps.json` 更新为 draft-v3 / frozen=false，加入固定 Verilator 与 RTL/AFU 实测观察；硬件配置、ABI 和 PTX 白名单没有变化。执行所用 draft-v2 快照完整保留，新旧哈希及接收范围见 [D3 版本接收说明](AB_D3_PROGRESS.md)。
- 参考 ZIP、两份 PDF/Markdown 和接收 manifest 已保留在 `references/teacher_u280_20261107/`。
- D5 增加 `configs/candidates/block32-v1/`，候选 lock `9bf1ecd89852e54dd402e669becbfd0910752ffd16ad9e7a9f9b20e77b6c4649`；只显式修改 warps 4→8，源码、工具包、XLEN、ABI、PTX 白名单未改。三路 152/152 原生 u32 自测通过，候选尚未升为默认或冻结。
- D5 Linux 运行器自测 25 通过/1 跳过；schema 6 支持显式 `--target-profile block32-v1`，native 语料 schema v2。全部执行代码快照在 `results/ab-d5-block32-20261108-v1/implementation/`；不把脚本自测当处理器结果。
- ZIP 原文明确入口 `192.0.2.28:22`，`yourname` 是占位符；本机 21:21 授权 TCP 检查 5.026 秒超时，未登录。B 另完成 4 份固定平台源码哈希核对，明确真实设备打开会加载 xclbin、HOST[0] 与 NOXRT 模型的差异，见接收单。

## 尚未完成与阻塞



- G0 的原生执行与锁文件可追溯已有材料；C/D/E 的能力/ABI 和独立接收仍未完成，不宣称团队全链路已验收。
- D4/D5 已验证三类原生 u32 程序的可见输出，D6 补原生 LSU 观察范围内的假谓词/尾线程无数组请求证据。项目 P0 runtime/前后端与 E 独立答案仍未接收；原生结果不能替代 PTX 转换语义、任意非法指针行为、整段程序严格恰执行一次、安全中止/恢复或浮点 RTL。
- PTX 前端已有实施者自测与宿主生成代码验证入口；`Memory` 宿主审计模型的地址检查和访问 trace 不属于真实 Vortex 能力。静态类型/初始化分析与参数序列化不能替代模块装载、buffer 生命周期、launch 或故障恢复。
- 原 WSL Ubuntu 20.04 的兼容阻塞、Docker 启动失败与 NTFS Git 检查超时保留在历史证据中；D4 未重试 Docker。实际成功路线为专用 WSL，原生 Linux 固定检出的 3329 个文件与原清单零差异。
- U280 登录、工具/platform 盘点、8 张卡只读报告与两 CPU 小型组件综合/许可均 PASS。工作目录为 `/home/u280user/vortex-u280-probes/<run_id>`；无需固定分卡或书面额度。8 张卡当时空闲，HOST 内存均为 0，下一步处理该通路及完整 FPGA 配置。D10 用户已授权两 CPU/6 小时完整 link 方案，实际启动状态见顶部与 D10 记录。真实 XRT runtime 打开会加载 xclbin，不能当只读盘点；密码仍由用户本机输入。
- D10 已有真实 xclbin 与 kernel clock 200 MHz 检查通过的结果；D11 已本地归档，D12 新解析确认 9 项 methodology 关键告警待关闭、7 输入/3 输出缺 delay。D12 服务器真实 runtime 两库编译/依赖解析已通过；HOST 通路、实际加载时钟与板上功能/性能尚未验证。整体已约束时序通过仍不等于上板接收，资源统计分清 shell 整体 placement 与 AFU 综合。

## 当前运行位置与恢复顺序

在 `Vortex-AB-Ubuntu-22.04` 中：

- 固定源码：`/opt/vortex-ab/sources/vortex-7fe19369587c-v1`；原始 `upstream/vortex/` 保留。
- 当前完整工具根：`/opt/vortex-ab/toolchains/8c64cf921d3c6c456e80f00d24482d0aa2153a82-rtlsim-d3-v1`；旧 SimX 工具根保留。
- D3 成功构建分别为 `/opt/vortex-ab/builds/ab-d3-simx-20261108-v1`、`/opt/vortex-ab/builds/ab-d3-rtlsim-20261108-v2`、`/opt/vortex-ab/builds/ab-d3-xrtsim-20261108-v1`；旧成功/失败目录均保留，新运行不得覆盖。
- D4 成功构建：`/opt/vortex-ab/builds/ab-d4-simx-20261108-v1`、`/opt/vortex-ab/builds/ab-d4-rtlsim-20261108-v1`、`/opt/vortex-ab/builds/ab-d4-xrtsim-20261108-v1`，不同 backend 完全隔离。
- D4 基线审阅日志、配置、源码清单、demo/kernel/runtime 和全部输入/参考/输出：`results/ab-d4-<backend>-20261108-v1/`；[D4 总索引](../results/ab-d4-closeout-20261108-v1/result.json)，历史 D3 目录保留。
- D5 候选成功构建：`/opt/vortex-ab/builds/ab-d5-block32-20261108-v1-simx`、`...-rtlsim`、`...-xrtsim`。对应证据在 `results/ab-d5-block32-20261108-v1-<backend>/`；[D5 总索引](../results/ab-d5-closeout-20261108-v1/result.json)。与 4w×4t 基线产物严格分开。
- D6 DEBUG=3 / 8w×4t 隔离构建：`/opt/vortex-ab/builds/ab-d6-trace-simx-20261108-v1` 和 `...-rtlsim-20261108-v1`。成功执行记录分别为 `results/ab-d6-trace-simx-20261108-v2/`、`results/ab-d6-trace-rtlsim-20261108-v1/`；SimX v1 为解析器失败父记录，v2 没有完整重建。禁止与普通性能或其他 backend 产物混用。

D5 已完成 B=32 候选自测，D6 原生 trace 已交付，C/E 独立接收仍待进行；默认为 4w×4t、原生 B≤16，独立候选为 8w×4t、已测原生 B=32。D9 XO、D10 link 和 D11 归档均已完成，D12 服务器 runtime 已配套，无需再跟进旧 link 作业或重新构建。最近设备观察为 D12 `u280-runtime-20261109-v4`，不能当成未来加载时仍空闲；可优先复查 `0000:b1:00.1`，加载前重新核对空闲、BDF/index 和 HOST 配置。D8 SSH 255 与 D9 首次 XO 失败原件保留。FPGA 成功流程为 `--build-flow ip-ooc-v1`；服务器 runtime 成功流程为 `-RuntimeProfile gcc9-v1`，与默认 pinned 原包明确分开；不要覆盖已有输出。C/D 后续接入 `ptx_body` 的 Vortex wrapper、vxbin 和项目 runtime；原生 trace/XO 不替代 PTX 设备证据。

D8 本地源运行 `ab-d8-u280-source-20261109-v1`，构建目录 `/opt/vortex-ab/builds/ab-d8-u280-source-20261109-v1-{upstream_unmerged,candidate_merged}`。`results/ab-d8-u280-source-20261109-v1/u280-rtl-input.tar.gz` 只包含预处理源和脚本，不是已综合硬件。WSL 的 platforminfo 缺失警告原样保留，显式平台选择只用于离线预处理。`prepare_u280_fpga_candidate.py` 为一次性创建工具，现有候选不要重生成。

最新候选命令见 [D5 记录](AB_D5_PROGRESS.md)，原基线命令见 [D4](AB_D4_PROGRESS.md)，宿主准备见 [宿主方案](../environment/native-sim/README.md)。日常真实状态见 [STATUS](STATUS.md)，研究边界见 [RESEARCH_PLAN](RESEARCH_PLAN.md)。`capture_target.py` 是原始 draft-v1 初始化器，会重写当前 configs；D2 后不要用它作日常只读重核，使用原生运行器的 `--check-only`。`prepare_block32_candidate.py` 也是一次性独占创建工具，现有候选不要重生成。

## 文件与上下文边界

新根目录为 `D:\Vortex-U280`，不需要原工作区才能读取当前计划、脚本、配置、源码或参考原件。旧 AEC/FIFO 和课程连接工具不在本项目中；既有日志中的旧绝对路径是当时现场，保留不改。新 Codex 聊天先读本文件和状态页；不依赖旧聊天转录才能继续工作。
