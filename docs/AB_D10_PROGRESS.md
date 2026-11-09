# D10：已授权完整 FPGA link

2026-11-09 D11 接续：xclbin 与 197 份完整报告已本地归档核验；报告审阅发现 9 项 methodology Critical Warning 尚未关闭，上板条件仍待完成。runtime200 输入已准备，见 [D11 最新结果与范围](AB_D11_PROGRESS.md)。下文保留 D10 当时的事实与快照。

## 最终结果：完整构建与固定时钟检查 PASS

2026-11-09 **15:48:08（Asia/Shanghai）**，作业 `u280-link-20261109-103830-671` 完成，约 5 小时 9 分。15:56:47 的 只读采集（本地记录 `results/u280-link-20261109-155638-456/probe.json`）与 SSH/解包记录（本地记录 `results/u280-link-20261109-155638-456/transport.json`）退出 0，worker 和 builder 均为 PASS、退出 0；退出后的 ps 无进程/退出 1 与已完成状态一致，不是构建失败。

[最终构建记录](../results/u280-link-20261109-155638-456/returned/build/result.json)包含三条实际命令：platforminfo 退出 0（1.575 秒）、v++ link 退出 0（18565.056 秒、未达到 21600 秒超时）、固定时钟检查退出 0（0.118 秒）。link 输出（本地记录 `results/u280-link-20261109-155638-456/returned/build/link.stdout`）确认 bitstream/xclbin 打包完成并写出产物。

[固定时钟检查输出](../results/u280-link-20261109-155638-456/returned/build/clock_check.stdout)：`clk_kernel_00_unbuffered_net`，5.0 ns / **200 MHz**，setup WNS **+0.119 ns**、hold WHS **+0.009 ns**，289539 endpoints。该结论是固定检查脚本读取实现后报告的结果，不替代完整利用率、所有时序/DRC 项和 xclbin 元数据审阅。

产物保存在服务器：

```text
/home/u280user/vortex-u280-builds/u280-link-20261109-103830-671/out/vortex_afu.xclbin
bytes: 53950442
sha256: bbac2ab73073b24ba857fb34eadf22bf1c11dc745527f064c4eec61b70d2c843
```

大小与哈希由远端 builder 在成功退出前实际计算；xclbin 本体尚未下载到本地，本次取回的是日志、状态和哈希。21 个返回文件及命令日志摘要的复核入口为 收尾核验（本地记录 `results/ab-d10-link-closeout-20261109-v1/verify.py`）。D10 启动器的既有 Python 自测为 93 通过/1 跳过，仍只证明运行器行为。

下一步：归档 xclbin 与完整报告，检查资源/时序/平台元数据；准备 HOST 启用权限、所选卡最新空闲与 BDF/index、兼容服务器的 XRT runtime，并解决 runtime 原 400 MHz 编译值与实际 200 MHz 的绑定；之后执行原生 demo 和 copy/vadd/affine 板上回归。**HOST 配置、加载、板上功能/性能和 PTX 设备执行仍 NOT_RUN**。固定源码、根 lock/caps、D5/D8 输入和全部历史快照保留，未因构建成功自动升级候选的接收状态。

## 15:27 只读复查：布线完成，bitstream 生成中

2026-11-09 15:27:25（Asia/Shanghai）完成 新状态采集（本地记录 `results/u280-link-20261109-152717-495/probe.json`），SSH/采集均退出 0（本地记录 `results/u280-link-20261109-152717-495/transport.json`）。原作业 **RUNNING，routing 已完成、bitstream generation 正在进行**；worker PID 95131 存活 04:48:44，v++ PID 95311 存活 04:48:42，没有新建或重启构建。

link 日志（本地记录 `results/u280-link-20261109-152717-495/returned/build/link.stdout`）在 15:02:52 记录 `Finished 5th of 6 tasks (FPGA routing)`，耗时 00h 43m 56s，随后同秒 `Starting bitstream generation..` 和 `Phase 13 Post-Route Event Processing`；可选布线后物理优化的开始/结束也已记录。尚未出现 bitstream/xclbin 生成完成及 v++ 最终退出结果，工具的 5/6 任务计数不等于完整构建已通过。

此次采集的 link stdout/stderr 未见 `ERROR:` 行，19 个返回文件大小/SHA-256 核验一致。最终 xclbin 和运行器固定时钟检查 PASS 仍未取得，此前快照保留。

## 15:01 只读复查：布线后时序分析

2026-11-09 15:01:35（Asia/Shanghai）完成 新状态采集（本地记录 `results/u280-link-20261109-150126-730/probe.json`），SSH/采集均退出 0（本地记录 `results/u280-link-20261109-150126-730/transport.json`）。原作业 **RUNNING，routing 推进至 Post Router Timing**；worker PID 95131 存活 04:22:54，v++ PID 95311 存活 04:22:52，没有新建或重启构建。

link 日志（本地记录 `results/u280-link-20261109-150126-730/returned/build/link.stdout`）记录：14:46—14:51 重布全局迭代 1—3；14:53:10 Delay and Skew Optimization；14:55:43 Post Hold Fix；14:58:47 Route finalize 与 Verifying routed nets；14:59:17 Depositing Routes；14:59:48 Resolve XTalk；15:00:18 `Phase 12 Post Router Timing`。这是布线流程中的时序分析阶段，尚未取得整个 routing 完成或时序达标的确认。

本次采集的 link stdout/stderr 未见 `ERROR:` 行，19 个返回文件大小/SHA-256 核验一致。最终 xclbin 和固定时钟检查 PASS 仍未取得，此前快照保留。

## 14:31 只读复查：布局完成，正在布线

2026-11-09 14:31:52（Asia/Shanghai）完成 新状态采集（本地记录 `results/u280-link-20261109-143143-780/probe.json`），SSH/采集均退出 0（本地记录 `results/u280-link-20261109-143143-780/transport.json`）。原作业 **RUNNING，placement 已完成、routing 正在执行**；worker PID 95131 存活 03:53:11，v++ PID 95311 存活 03:53:09，没有新建或重启构建。

link 日志（本地记录 `results/u280-link-20261109-143143-780/returned/build/link.stdout`）记录：14:18:55 完成第 4/6 项 FPGA logic placement，布局耗时 01h 05m 52s；同秒启动 logic routing。14:29:09 进入 Initial Routing / Global Routing，14:31:42 进入 `Phase 4 Rip-up And Reroute` 与 `Phase 4.1 Global Iteration 0`。该迭代标签本身不是失败标志，也不代表布线完成或时序达标。

此次采集的 link stdout/stderr 未见 `ERROR:` 行，19 个返回文件大小/SHA-256 核验一致。布线、最终 xclbin 和固定时钟检查仍待取得完成结果，此前快照保留。

## 14:14 只读复查：布局收尾清理

2026-11-09 14:14:55（Asia/Shanghai）完成 新状态采集（本地记录 `results/u280-link-20261109-141448-833/probe.json`），SSH/采集均退出 0（本地记录 `results/u280-link-20261109-141448-833/transport.json`）。原作业 **RUNNING，处于布局收尾清理**；worker PID 95131 存活 03:36:14，v++ PID 95311 存活 03:36:12，没有新建或重启构建。

link 日志（本地记录 `results/u280-link-20261109-141448-833/returned/build/link.stdout`）记录：13:52:22 Detail Placement，14:01:04 Post Placement Optimization and Clean-Up，14:10:14 Post Placement Cleanup，14:10:45 Placer Reporting 与 `Phase 4.4 Final Placement Cleanup`。尚未看到整个 placement 完成或 routing 开始的标志，不能把该阶段名称视为布局布线或整个构建完成。

本次采集的 link stdout/stderr 未见 `ERROR:` 行，19 个返回文件大小/SHA-256 核验一致。最终 xclbin 与固定时钟检查结果仍未取得，此前快照保留。

## 13:47 只读复查：全局布局与时序更新

2026-11-09 13:47:27（Asia/Shanghai）完成 新状态采集（本地记录 `results/u280-link-20261109-134719-960/probe.json`），SSH/采集均退出 0（本地记录 `results/u280-link-20261109-134719-960/transport.json`）。原作业 **RUNNING，正在全局布局**；worker PID 95131 存活 03:08:46，v++ PID 95311 存活 03:08:44，没有新建或重启构建。

link 日志（本地记录 `results/u280-link-20261109-134719-960/returned/build/link.stdout`）从上次布局初始化继续推进：13:22:12 Global Placement、13:28:20 Global Placement Core、13:47:15 `Phase 2.5.1 UpdateTiming Before Physical Synthesis`。最新阶段是布局内的时序更新，不能据此宣称布局完成、时序达标或已开始布线。

此次采集的 link stdout/stderr 未见 `ERROR:` 行，19 个返回文件大小/SHA-256 核验一致。最终实现、xclbin 和固定时钟检查仍待完成，此前快照保留。

## 13:14 只读复查：优化完成，正在布局

2026-11-09 13:14:26（Asia/Shanghai）完成 新状态采集（本地记录 `results/u280-link-20261109-131419-048/probe.json`），SSH/采集均退出 0（本地记录 `results/u280-link-20261109-131419-048/transport.json`）。原作业 **RUNNING，已进入 placement**；worker PID 95131 存活 02:35:45，v++ PID 95311 存活 02:35:43，未启动新构建。

link 日志（本地记录 `results/u280-link-20261109-131419-048/returned/build/link.stdout`）记录：12:58:15 完成 synthesized kernels 与平台链接（工具标记第 2/6 项）；13:13:02 完成逻辑优化（第 3/6 项）并开始 logic placement；13:14:04 为 `Phase 1 Placer Initialization` 和 `Phase 1.1 Placer Initialization Netlist Sorting`。这些任务编号不代表总耗时百分比。

本次采集的 link stdout/stderr 未见 `ERROR:` 行，19 个返回文件大小/SHA-256 核验一致。布线、最终产物及固定时钟检查尚未取得完成结果，不能报告完整构建或板上 PASS；此前快照保留。

## 12:37 只读复查：综合完成，进入实现

2026-11-09 12:37:02（Asia/Shanghai）完成 新状态采集（本地记录 `results/u280-link-20261109-123654-150/probe.json`），SSH/采集均退出 0（本地记录 `results/u280-link-20261109-123654-150/transport.json`）。原作业仍为 **RUNNING，综合阶段已完成，实现阶段已启动**；worker PID 95131 存活 01:58:20，v++ PID 95311 存活 01:58:19，未启动新构建。

link 日志（本地记录 `results/u280-link-20261109-123654-150/returned/build/link.stdout`）记录：12:34:27 模块级综合 156/156 完成；12:34:58 起执行顶层综合；12:36:11 为 `Run vpl: Step synth: Completed`，紧接 `Run vpl: Step impl: Started`。此次采集的 link stdout/stderr 未见 `ERROR:` 行，19 个返回文件的大小/SHA-256 核验一致。

该进展只证明工具已完成综合并进入实现流程，不能报告布局布线完成、200 MHz 时序通过或最终 xclbin PASS。下一步等待实现、产物生成及固定时钟检查的实际结果；此前快照与失败记录保留。

## 11:27 只读复查

2026-11-09 11:27（Asia/Shanghai）完成 新状态采集（本地记录 `results/u280-link-20261109-112701-720/probe.json`），作业仍为 **RUNNING，处于综合阶段，未完成**。worker PID 95131 存活 48:32，v++ PID 95311 存活 48:31；这次只读查询没有启动新构建。

最新 link 日志（本地记录 `results/u280-link-20261109-112701-720/returned/build/link.stdout`）在 11:26:49 显示 `Block-level synthesis in progress, 49 of 156 jobs complete, 2 jobs running.`，相比 10:50 的 9/156 已持续推进。尚未进入布局布线，未取得最终 xclbin、固定时钟检查或构建 PASS。模块级任务计数不代表全流程完成百分比，也不足以推算可靠完成时间。此前快照保留。

## 10:50 只读复查

2026-11-09 10:50:53（Asia/Shanghai）完成 新状态采集（本地记录 `results/u280-link-20261109-105044-191/probe.json`），SSH/采集退出 0（本地记录 `results/u280-link-20261109-105044-191/transport.json`），没有启动新构建。作业仍为 **RUNNING，处于综合阶段，未完成**。

worker PID 95131 的 PPID 已为 1、存活 12:12，v++ PID 95311 存活 12:10，确认先前 SSH 断开后作业继续运行。system_link、cf2sw、create_project/create_bd、generate_target 和 config_hw_runs 已完成；10:42:56 开始 synth。最新日志 10:50:29 为 `Block-level synthesis in progress, 9 of 156 jobs complete, 2 jobs running.`，详见 link.stdout（本地记录 `results/u280-link-20261109-105044-191/returned/build/link.stdout`）。该数字是模块级任务计数，不是全流程耗时或完成百分比。尚未进入布局布线，未取得最终 xclbin、固定时钟检查或构建 PASS；两个 CPU 与两并行 job 的既定限制继续使用。

## 启动记录与约束

2026-11-09 用户明确回复“按此启动”，接受 [link 方案](../environment/u280-fpga/NEXT_LINK.md)：两个 CPU、nice +10、综合/实现 jobs=2、实现 maxThreads=2、v++ 超时 6 小时，启动预算 RAM 64 GiB、磁盘 50 GiB，无 RAM 硬限。

**已实际启动，启动采集时为 RUNNING。** 作业 `u280-link-20261109-103830-671` 于 2026-11-09 10:38:41（Asia/Shanghai）启动；10:38:44 本机 SSH/解包退出均为 0。传输记录（本地记录 `results/u280-link-20261109-103830-671/transport.json`）、远端采集（本地记录 `results/u280-link-20261109-103830-671/probe.json`）、构建状态快照（本地记录 `results/u280-link-20261109-103830-671/returned/build/result.json`）。密码仅由用户在本机 SSH 提示输入，不进入聊天或证据文件。

资源检查的五条命令全部退出 0。启动时 `MemAvailable=354009686016` 字节（约 329.7 GiB）、磁盘可用 `774075731968` 字节（约 720.9 GiB），满足 64/50 GiB 启动预算；负载均值 3.38/3.02/2.74。实际 XO、构建脚本、288 项输入、flow 和 XPFM/XSA 哈希均与 D9 对应证据匹配。平台解析退出 0，用时 1.575 秒。

启动观测：worker PID `95131`、builder PID `95132`、`v++ --link` 启动进程 PID `95311`，完整 argv 已记录在 `probe.json` 的 `builder_children`。限制记录 CPU affinity `[0,1]`、nice +10、两线程、v++ 超时 21600 秒；进程 argv 包含 synth/impl jobs=2、目标 200 MHz 和既定 HBM/HOST 连接。构建结果中的 RAM 提示来自未改写的 D9 通用运行器；本次用户授权另存于 job/request.json，仍无 RAM 硬限。

此快照采集于 link 刚启动，`link.stdout/stderr` 尚为空；不能据此宣称综合、布局布线、固定时钟检查或 xclbin 已通过。后续需要新的只读采集确认进展与最终退出码，不能把本地启动快照当成实时状态。

远端作业目录：`/home/u280user/vortex-u280-link-jobs/u280-link-20261109-103830-671`。构建目录：`/home/u280user/vortex-u280-builds/u280-link-20261109-103830-671`。SSH 正常结束后独立 worker 负责继续构建并保存最终状态。查询命令（仅输入 SSH 密码，不会再提交构建）：

```powershell
& 'D:\Vortex-U280\scripts\Invoke-U280Link.ps1' -Mode Status -BuildRun u280-link-20261109-103830-671
```

新增 `scripts/Invoke-U280Link.ps1`、`prepare_u280_link.py` 和 `u280_remote_link.py`。入口使用 D9 成功 XO，核对测试过的构建脚本、输入清单、flow 补丁及 platform 文件身份，检查当次资源后启动独立后台 worker。worker 保留互斥锁至构建结束，防止第二个同项目 link 同时提交；既有运行目录拒绝覆盖。启动与只读查询各使用新的本地 run_id 保存证据。构建继续由 D9 的 `build_prepared.py` 执行，没有修改已通过的源文件或构建参数。

`transport.status=PASS` 仅表示 SSH 与结果采集成功；`build_status` 是构建状态，只有实际 builder 退出 0 且构建 `result.json` 为 PASS 才记录完成。真实板卡加载、HOST 配置和板上功能均不在本次启动范围。

离线准备记录：u280-link-prepare-20261109-v1（本地记录 `results/u280-link-prepare-20261109-v1/transport.json`），退出 0，SSH/link NOT_RUN。已在专用 WSL 执行项目规定命令 `python3 -B -m unittest discover -s tests -v`，94 项中 93 通过、1 跳过，退出 0，86.905 秒；命令/脚本哈希（本地记录 `results/ab-d10-launch-checks-20261109-v1/result.json`）、实际测试输出（本地记录 `results/ab-d10-launch-checks-20261109-v1/tests.stderr`）。新增 6 项测试覆盖资源门槛、Python 3.6 语法、旧证据保留、构建脚本被改时拒绝、后台锁存续与三种退出结果、未知作业查询拒绝。测试仅验证运行器，不作 FPGA 功能证据。

下一步读取该作业的新状态。成功后审阅完整资源/时序、固定时钟检查及 xclbin 元数据；失败则保留此目录，依据日志修正独立构建流程并使用新的 run_id。板卡 HOST 启用、加载与上板程序仍未执行，PTX 前端/runtime 接收状态未改变。
