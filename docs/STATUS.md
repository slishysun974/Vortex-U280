# 当前研究状态

2026-11-09 GitHub 公开快照收录项目源码、配置、D13 文档和选定记录。服务器及工作站标识使用示例值。标记为本地记录的文件由原工作区保管。公开快照中的证据范围见 [索引](../results/README.md)。

2026-11-09 文档整理：新增[项目阶段进展报告](PROJECT_PROGRESS_REPORT_20261109.md)，按开发基础、原生仿真、PTX 前端、U280 构建和当前阻塞整理截至 D13 的事实。本次仅整理文档，未新增实验或硬件验证；HOST 与 TIMING-7 仍阻塞，上板功能和 PTX 设备执行仍 NOT_RUN。下一步仍按 D13 处理 HOST/跨域问题，再受控加载并验证实际时钟与原生程序。

2026-11-09 D13 最终：**实现/平台 DCP 采集及静态审阅完成，53/53 证据检查 PASS；上板仍 BLOCKED/NOT_RUN。** 9 项关键告警中 8 项来自原始平台，1 项来自可调 kernel 时钟的 300→200 MHz 约束；7 项平台保留项已核实来源/当前影响范围，**TIMING-7 的 Partial False Path (unsafe) 仍 OPEN**，实际 200 MHz 待受控加载后读回。缺 delay 的 10 个端口与基线一致，内部未约束端点均为 0。HOST 因账号无 sudo 权限而阻塞，配置未执行；用户要求先解释结果再申请权限。[D13](AB_D13_PROGRESS.md)、[审阅结果](../results/u280-readiness-review-20261109-v2/result.json)、[管理员最小操作](../environment/u280-fpga/HOST_SETUP.md)。Linux 自测 117 通过/1 跳过，固定源码 3329 项零差异；原生 152 次输入仅离线准备。

2026-11-09 D12：**服务器 200 MHz runtime 编译/依赖解析 PASS；上板就绪 BLOCKED，板上功能 NOT_RUN。** v4（本地记录 `results/u280-runtime-20261109-v4/probe.json`） SSH/采集退出 0，GCC 9.3.1 / glibc 2.17 下公共库 10.833 秒、真实 XRT backend 1.420 秒，两库 ldd 均通过并已返回本地。独立 `gcc9-vm-allocation-v1` 修复分配失败后读未初始化变量及生成 Makefile 的重复配置展开，新增 binding-v2；固定源码、FPGA 配置、根 lock/caps 和旧结果保留。8 张卡当次 ready/无 KDS 在途任务，HOST 内存仍为 0、sudo 权限未确认。新报告解析纠正 D11 机器摘要的空表/零计数缺陷：methodology 100 项中的 **9 项 Critical Warning 仍全部 OPEN**；普通 DRC 343 项没有 Error/Critical Warning。最终 Python 自测 **113 通过/1 跳过**，退出 0。详见 [D12 证据与范围](AB_D12_PROGRESS.md)、[运行入口](../environment/u280-fpga/RUNTIME.md)。

2026-11-09 D11：**xclbin 与全部 197 份报告已归档，200 MHz runtime 输入准备 PASS；上板就绪仍 BLOCKED。** v5（本地记录 `results/u280-archive-20261109-v5/probe.json`） SSH/解包退出 0，53,950,442 字节 xclbin 本地哈希与 D10 一致；197 份报告逐文件核验。最终整体 WNS +0.016 ns / WHS +0.006 ns、routing errors=0；完整 methodology 报告有 **9 项 Critical Warning**，含 5 ns 约束与 3.333 ns 时钟模块默认参数不一致，尚未关闭。已准备 runtime200 输入包（本地记录 `results/u280-runtime-prepare-20261109-v1/result.json`），唯一配置差异为宿主频率常量 400→200，Ubuntu 公共库编译退出 0；服务器现有 GCC 9.3.1/XRT 头文件已确认，真实服务器 runtime/板上功能 NOT_RUN。最终脚本自测 **103 通过/1 跳过**，固定源码保留。Surfshark 局域网残留规则经用户刷新开关后 SSH 恢复，失败记录保留。详见 [D11 发现、范围与下一步](AB_D11_PROGRESS.md)。

2026-11-09 15:56:47 D10 完成复核：**完整 FPGA 构建 PASS，200 MHz 固定时钟检查 PASS**。作业 `u280-link-20261109-103830-671` 于 **15:48:08** 完成，约 5 小时 9 分；v++ 退出 0、未超时，clock_check 退出 0。检查报告 kernel clock 5.0 ns、setup WNS **+0.119 ns**、hold WHS **+0.009 ns**、289539 endpoints。服务器已生成 `out/vortex_afu.xclbin`，53,950,442 字节，SHA-256 `bbac2ab73073b24ba857fb34eadf22bf1c11dc745527f064c4eec61b70d2c843`。[最终构建记录](../results/u280-link-20261109-155638-456/returned/build/result.json)、[时钟输出](../results/u280-link-20261109-155638-456/returned/build/clock_check.stdout)、[D10](AB_D10_PROGRESS.md)。产物留存远端，尚未下载；完整利用率/元数据审阅、HOST 配置、原生上板与 PTX 设备执行仍待完成。

2026-11-09 15:27:25 D10 复查：**布线已完成，正在生成 bitstream，完整构建未完成**。新只读采集（本地记录 `results/u280-link-20261109-152717-495/probe.json`）为 RUNNING，worker/v++ 存活约 4 小时 49 分；15:02:52 完成第 5/6 项 FPGA routing（耗时 43 分 56 秒），同秒开始 bitstream generation；可选布线后物理优化随后显示完成。最终 xclbin、v++ 退出码及固定 200 MHz 检查结果尚未取得。SSH/采集退出 0，原作业未重启，详见 [D10](AB_D10_PROGRESS.md)。

2026-11-09 15:01:35 D10 复查：**布线后时序分析中，完整构建未完成**。新只读采集（本地记录 `results/u280-link-20261109-150126-730/probe.json`）为 RUNNING，worker/v++ 存活约 4 小时 23 分；日志已从重布迭代推进至 15:00:18 的 `Phase 12 Post Router Timing`。尚未取得整个 routing 完成、最终 xclbin 或固定 200 MHz 检查 PASS。SSH/采集退出 0，原作业未重启，详见 [D10](AB_D10_PROGRESS.md)。

2026-11-09 14:31:52 D10 复查：**布局已完成，正在布线，完整构建未完成**。新只读采集（本地记录 `results/u280-link-20261109-143143-780/probe.json`）为 RUNNING，worker/v++ 存活约 3 小时 53 分；14:18:55 placement 完成并启动 routing，14:31:42 进入 `Rip-up And Reroute / Global Iteration 0`。布线完成、最终 xclbin 和固定时钟检查结果尚未取得。SSH/采集退出 0，原作业未重启，详见 [D10](AB_D10_PROGRESS.md)。

2026-11-09 14:14:55 D10 复查：**布局收尾清理中，完整构建未完成**。新只读采集（本地记录 `results/u280-link-20261109-141448-833/probe.json`）为 RUNNING，worker/v++ 存活约 3 小时 36 分；日志已通过 Detail Placement 和 Post Placement Optimization，最新 14:10:45 为 `Phase 4.4 Final Placement Cleanup`。尚未取得布局完成、布线开始或最终 xclbin/固定时钟检查结果。SSH/采集退出 0，原作业未重启，详见 [D10](AB_D10_PROGRESS.md)。

2026-11-09 13:47:27 D10 复查：**正在全局布局，完整构建未完成**。新只读采集（本地记录 `results/u280-link-20261109-134719-960/probe.json`）为 RUNNING，worker/v++ 存活约 3 小时 9 分；日志由布局初始化推进到 13:28:20 的 Global Placement Core，13:47:15 为 `UpdateTiming Before Physical Synthesis`。布线、最终 xclbin 和固定时钟检查尚未取得完成结果。SSH/采集退出 0，原作业未重启，详见 [D10](AB_D10_PROGRESS.md)。

2026-11-09 13:14:26 D10 复查：**正在布局（placement），完整构建未完成**。新只读采集（本地记录 `results/u280-link-20261109-131419-048/probe.json`）为 RUNNING，worker/v++ 存活约 2 小时 35 分；12:58:15 完成综合内核与平台链接，13:13:02 完成逻辑优化并启动布局，13:14:04 进入 Placer Initialization。布线、最终产物和固定时钟检查尚未取得完成结果；SSH/采集退出 0，原作业未重启。详见 [D10](AB_D10_PROGRESS.md)。

2026-11-09 12:37:02 D10 复查：**综合已完成，正在实现，完整构建仍未结束**。新只读采集（本地记录 `results/u280-link-20261109-123654-150/probe.json`）为 RUNNING，worker/v++ 存活约 1 小时 58 分；12:34:27 模块级综合 156/156 完成，随后顶层综合于 12:36:11 完成，同秒进入 `impl`。尚未取得实现完成、固定时钟检查或最终 xclbin PASS。SSH/采集退出 0，原作业未重启。详见 [D10](AB_D10_PROGRESS.md)。

2026-11-09 11:27 D10 复查：**仍在综合，未完成**。新只读采集（本地记录 `results/u280-link-20261109-112701-720/probe.json`）显示原作业 RUNNING，worker/v++ 存活约 48 分半；日志 11:26:49 为模块级综合 **49/156 完成、2 个运行**，较 10:50 的 9/156 持续推进。尚未进入布局布线或取得最终 xclbin。查询未重启作业，详见 [D10](AB_D10_PROGRESS.md)。

2026-11-09 10:50:53 D10 复查：**仍在综合，未完成**。只读状态采集（本地记录 `results/u280-link-20261109-105044-191/probe.json`） SSH/采集均退出 0，作业 `u280-link-20261109-103830-671` 的 worker 与 v++ 仍存活，运行约 12 分钟。最新日志 10:50:29 显示 block-level synthesis **9/156 完成、2 个运行**；尚未进入布局布线，未取得最终 xclbin 或完整构建 PASS。任务计数不代表整体进度百分比。详见 [D10](AB_D10_PROGRESS.md)。

2026-11-09 D10：**完整 FPGA link 已启动，启动快照 RUNNING**。用户已授权 [link 方案](../environment/u280-fpga/NEXT_LINK.md)；作业 `u280-link-20261109-103830-671` 于 10:38:41 启动，实际观测到 `v++ --link` 进程，10:38:44 SSH 退出 0。当次可用 RAM 约 329.7 GiB、磁盘 720.9 GiB，身份/资源检查通过，CPU affinity `[0,1]`、nice +10、6 小时 v++ 超时，无 RAM 硬限。启动证据（本地记录 `results/u280-link-20261109-103830-671/probe.json`）、[D10](AB_D10_PROGRESS.md)。Linux 93 项 Python 自测通过、1 跳过，退出 0。综合/布局布线最终结果与 xclbin 尚未取得；HOST 配置、板上功能仍 NOT_RUN。后续使用只读 Status 入口采集新状态，不重复启动该目录。

2026-11-09 D9：**真实 U280 IP OOC、RTL elaboration、模块接口检查与 XO 打包 PASS**。[成功运行](../results/u280-preflight-20261109-100406-629/returned/build/result.json) Vivado 退出 0、340.708 秒；五个 IP 生成 DCP/stub，检查范围内 13 类/22 个模块实例通过，XO 为 312,868 字节。首次缺 stub 失败原件保留，独立 `ip-ooc-v1` 补丁只改新构建目录 Tcl。HOST/platform 复查 PASS，XSA 与 8 卡 shell UUID 匹配；HOST 内存仍为 0，sudo 权限未确认。[174/174 最终核验](../results/ab-d9-closeout-20261109-v1/result.json)通过，Linux 87 测试通过/1 跳过，固定源码 3329 文件零差异。详见 [D9](AB_D9_PROGRESS.md)。完整综合/实现、xclbin、HOST 配置与板上功能仍 NOT_RUN；[完整构建准备单](../environment/u280-fpga/NEXT_LINK.md)待确认资源规则。

2026-11-09 D8：**独立 U280 FPGA 候选与实际源预处理 PASS**。[D8 记录](AB_D8_PROGRESS.md)：原始分支生成 32 个 HBM AXI 主接口而仅端口 0 有显式连接，独立 `u280-hbm32-v1` 合并接口候选与 HBM/HOST 连接匹配；已生成可迁移 RTL 输入包。[635/635 证据核验](../results/ab-d8-closeout-20261109-v1/result.json)退出 0，Python 78 通过/1 跳过。根 lock/caps、D5 配置与固定源码未改。本轮远端 SSH 在密码认证阶段退出 255，HOST/platform 新采集 NOT_RUN；完整综合/上板仍 NOT_RUN。

2026-11-09 D7：**B 的两 CPU 小型 AFU 组件综合与实际 U280 综合许可 PASS，8 张卡的 XRT 查询 PASS**；采集时均 ready/空闲，HOST[0] 的 `host_mem_size` 均为 0。[184/184 收尾核验](../results/ab-d7-closeout-20261109-v1/result.json)退出 0，详见 [D7 记录](AB_D7_PROGRESS.md)。用户允许自行选择空闲卡和少量线程构建，无需固定分卡或书面额度；大型综合/布局布线前再确认资源与规则。当前待办是 HOST 通路、完整 FPGA 配置/构建与板上功能。

2026-11-08 D6 优先推进 A/B：**A 原生 LSU trace 在 SimX 与处理器 RTL 各 15/15 PASS**，每路 704 个有效数组 lane 访问准确匹配，全假/N=0 无数组请求；**B 实际服务器盘点、四项工具/platform 命令 PASS**。Vivado/v++ 2023.1、XRT/驱动 2.13.479；platform 文件列出 HBM[0..31]/HOST[0]。[228/228 项收尾](../results/ab-d6-closeout-20261108-v1/result.json)退出 0，SimX 首轮解析器错误和 Windows 沙箱失败记录保留。D6 当时的分卡等待条件已被上述共享卡授权替代；详见 [D6 进展与范围](AB_D6_PROGRESS.md)。

研究事实最后采集：2026-11-09，Asia/Shanghai。D5 独立 8w×4t 候选在 SimX、处理器 RTL 和 NOXRT AFU 模型各 152/152 次原生启动 PASS，含每路 122 次 B=32；[84 项收尾核验通过](../results/ab-d5-closeout-20261108-v1/result.json)。4w×4t 基线及 D4 证据保留。同作者 Python reference 自测不计作独立接收；P0 与物理平台仍未验收。

前一轮新增 P0 前端首版和宿主语义证据：[最终 v3](../results/ptx-frontend-host-20261108-v3/summary.json) 退出 0，69 项 Python 测试通过/1 跳过，661/661 宿主用例通过，假谓词提前 load 故障被检出；[174 项收尾通过](../results/ptx-frontend-closeout-20261108-v1/result.json)。这些是生成 C++ 的 CPU 审计结果，PTX-SimX/RTL/AFU/U280 仍 NOT_RUN。前两轮失败记录保留。



| 项目 | 状态 | 说明 |
|---|---|---|
| 研究计划、五人分工、接口与 PTX 规范 | 已整理 | 设计文档，尚待实施接收 |
| 独立项目目录与文档入口 | 已整理 | 当前根目录为 Vortex-U280；[交接](PROJECT_HANDOFF.md)、[迁移说明](PROJECT_MIGRATION.md) |
| 老师提供的服务器 / U280 入门资料 | 已接收并核对参考链接 | 原件与使用说明（本地记录 `docs/TEACHER_U280_REFERENCE.md`）；资料中的服务器入口已登录验证，环境与上板仍待实测 |
| Vortex 源码身份 / 候选配置解析 | PASS（仅此范围） | v3.0 完整 SHA、已取两个子模块、3329 文件 SHA-256；[v2 证据](../results/ab-d1-source-20261107-v2/result.json) |
| 独立 Linux 与固定工具包 | PASS（准备范围） | Ubuntu 22.04 WSL、glibc 2.35 / G++ 11.4 / CMake 3.22.1；D3 新增同提交的 Verilator 5.050，18 个分卷/单包已核验并独立提取；[D3 证据](AB_D3_PROGRESS.md) |
| Vortex / 配套工具链组合冻结 | draft-v3，未冻结 | 新增 Verilator 5.050 身份及实际 RTL/AFU 观察，硬件/ABI/白名单未变；[lock](../configs/target_lock.json) / [caps](../configs/target_caps.json) 保持 `frozen=false`，P0 能力与独立接收未完成 |
| 原生 SimX 最小 demo | **PASS（仅上游整数 demo）** | RV64 / 1 cluster / 1 core / 4 warps / 4 threads，16 个整数；[D3 新目录复跑](../results/ab-d3-simx-20261108-v1/summary.json) 退出 0 且 `PASSED!`；同一 agent 复跑，不计作独立接收 |
| 处理器 RTL | **PASS（原生整数自测范围）** | 同 RV64 / 1c / 4w / 4t；D4 demo 与 140 次 u32 回归（本地记录 `results/ab-d4-rtlsim-20261108-v1/summary.json`），退出 0；D3 首轮缺 ccache 构建失败保留 |
| XRT AFU RTL 模型 | **PASS（本地模型原生整数自测）** | D4 NOXRT/XRTSIM 运行（本地记录 `results/ab-d4-xrtsim-20261108-v1/summary.json`），demo 与 140 次 u32 回归退出 0；未测试真实 XRT、HOST[0]、PCIe/HBM、shell 或板卡 |
| 仿真运行器与准备脚本 | PASS（脚本范围） | D12 最终 Linux（本地记录 `results/ab-d12-script-checks-20261109-v3/result.json`） 113 通过 / 1 跳过，退出 0；不能代替 kernel 验收 |
| D4 原生 u32 边界回归 | **PASS（每路 140/140）** | copy/vadd/affine，70 个参数用例各两组输入；三路 kernel/语料/捕获一致，[总核验](../results/ab-d4-closeout-20261108-v1/result.json)；同作者 reference，不计作 E 独立接收 |
| D5 B=32 原生候选 | **PASS（每路 152/152）** | 独立 8w×4t candidate-v1，每路 122 次 B=32，B=33/64 拒绝；三路输出一致，[D5 记录](AB_D5_PROGRESS.md)；根 lock/caps 未变，候选待 C/D/E 接收 |
| D6 原生假谓词/尾线程 LSU 观察 | **PASS（SimX/处理器 RTL 各 15/15）** | B=32 独立候选，copy/vadd/affine 各 5 场景；两路各 704 个有效数组 lane 地址/计数匹配，N=0/全假无数组请求；[D6](AB_D6_PROGRESS.md)，非 PTX/AFU/U280/独立 E 验收 |
| 隔离 Linux 容器启动尝试 | FAIL | 已安装 Docker Desktop 启动超时，尚无可用 daemon；原始返回（本地记录 `results/ab-d1-container-20261107/result.json`） |
| PTX 前端 / 参数布局 | **PASS（作者自测范围）** | 严格 parser、typed IR、C++ 语义代码、源码映射和小端 packer；独立 v0.2 draft，Linux 运行器/前端/证据检查合计 69 通过、1 跳过；见 [前端记录](PTX_FRONTEND_PROGRESS.md)，生成物不可装载 |
| PTX 生成 C++ 宿主语义 | **PASS（661/661）** | copy 132、vadd 132、affine 396、probe 1；输出/全局访问 trace/计数与输入/尾部哨兵通过；假谓词提前 load 注入被检出。仅宿主审计模型，非独立 E 或设备接收 |
| 项目后端适配 / runtime / PTX 设备执行 | NOT_RUN | 尚缺 Vortex wrapper、模块打包/装载与 buffer/launch 生命周期；宿主语义测试不计作 PTX-SimX/RTL/U280 |
| U280 服务器登录 | **PASS（仅登录与身份命令）** | WLAN 绑定连接 `192.0.2.28:22`，22:32 改密后独立密码认证成功，`id -un && hostname` 返回 `u280user` / `localhost`、退出 0；最新登录结果（本地记录 `results/u280-account-20261108-223211-948/result.json`），22:19 原始证据保留 |
| U280 账号密码修改 | **PASS（passwd 退出 0，随后登录 PASS）** | 用户本机输入，未保存密码或改密终端会话；改密结果（本地记录 `results/u280-password-20261108-223102-478/result.json`），首次 UNCONFIRMED 记录保留 |
| U280 服务器/工具/platform 文件盘点 | **PASS（实际命令范围）** | 最新盘点（本地记录 `results/u280-inventory-20261108-232952-683/inventory.json`）：Vivado/v++ 2023.1、XRT/驱动 2.13.479，HBM[0..31]/HOST[0] 文件级资源；许可与设备观察见 D7 |
| U280 小型综合/许可/设备观察 | **PASS（D7 限定范围）** | 两 CPU 的 AXI 组件综合退出 0、许可证实际签出；8/8 卡查询成功且当时空闲；[D7](AB_D7_PROGRESS.md) |
| U280 完整构建与上板 | **构建/归档/静态审阅 PASS；上板就绪 BLOCKED，功能 NOT_RUN** | D13 实现/平台 DCP 对照完成：8 项平台既有告警、1 项可调时钟约束；7 项平台保留项审阅完成，TIMING-7 跨域仍 OPEN。HOST 权限与实际时钟/板上功能待完成；[D13](AB_D13_PROGRESS.md) |
| D11 原始 runtime200 输入 | **PASS（本地准备范围）；服务器编译 FAIL** | 104 项固定源码、116 项包清单，Ubuntu 公共库编译通过；D12 服务器实测原包触发 GCC 9 未初始化变量错误，原件保留。服务器通过版本见下一行；[输入与接收范围](../environment/u280-fpga/RUNTIME.md) |
| U280 服务器 runtime200 | **PASS（两库编译/依赖解析）** | [D12 v4](../results/u280-runtime-20261109-v4/returned/runtime/result.json) 六条命令退出 0；独立 GCC 9 候选绑定同一 FPGA/xclbin/200 MHz，ldd 无缺失项；设备 API、HOST 分配与板上执行 NOT_RUN |
| D8 独立 U280 FPGA 候选/输入包 | **PASS（源预处理范围）** | RV64/1c/8w/4t、合并 HBM 主接口、HOST[0]；[D8](AB_D8_PROGRESS.md)，288 项输入包；未执行 Vivado elaboration/XO/综合/实现，200 MHz 只是构建目标 |
| D8 HOST/platform 复查 | **FAIL（SSH 255），远端 NOT_RUN** | 密码认证阶段连接结束，未得到新设备/权限证据；原始记录（本地记录 `results/u280-host-platform-20261109-v1/transport.json`），不推翻历史成功登录，也不假定 D7 空闲观察仍有效 |
| D9 HOST/platform 身份 | **PASS（只读范围）** | 09:46 采集（本地记录 `results/u280-preflight-20261109-094621-277/probe.json`）；XSA↔8 卡 interface UUID 匹配，当时 ready/无 KDS 任务，HOST 仍为 0，sudo 需要密码 |
| D9 真实 U280 XO | **PASS（OOC/elaboration/gate/打包范围）** | [10:10 完成](../results/u280-preflight-20261109-100406-629/returned/build/result.json)，Vivado 0、340.708 秒；五个 vendor IP、13 类/22 个模块实例检查；XO 留存服务器，非 xclbin/板上结果 |
| AI 对照实验 | NOT_RUN | 待冻结配对任务、预算与验收 |

当前优先 A/B：D13 已完成实现/平台 DCP 审阅。下一步由用户申请一张空闲卡的 256 MiB HOST 管理员代配置，并核实平台 TIMING-7 跨域保留项；条件满足后受控加载，读回 UUID/实际 200 MHz，再执行原生上板回归，见 [D13](AB_D13_PROGRESS.md)。无需重新 link 或下载已有 xclbin。D5 [B=32 候选回归](AB_D5_PROGRESS.md)、D6 原生 trace 与 D4 证据保留，待 C/D/E 独立接收；默认 4w×4t 仍拒绝原生 B=32，候选未冻结。C/D 后续接入 Vortex wrapper、真正程序 image 与项目 runtime，再执行 PTX-SimX/RTL；原生 trace、xclbin 和宿主前端测试均不替代 PTX 设备接收。板上运行仍 NOT_RUN。
