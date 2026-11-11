# Vortex-U280 项目交接

2026-11-11 公开快照整理：当前代码、两套冻结语料、新独立四路接收与模型恢复证据纳入公开发布范围，入口见 [阶段成果](PROJECT_PROGRESS_REPORT_20261111.md)、[发布说明](PUBLICATION.md)。公开副本自测 **237 通过/32 跳过，退出 0**；四路已有 capture 离线重核各 **48/48**，冻结语料与六个生产文件共 **248 项字节一致**。这是发布验证，没有新增设备运行；完整本地自测 268/1 与公开结果分开报告。

新增 [服务器访问与目录导航](SERVER_GUIDE.md)：SSH 使用方法、XRT/Vitis/GCC/Python、D10 FPGA 成品、D12 两库、C/E 板测目录均已标明。真实账号、地址和本机 WLAN 交互登录命令仅保存在本地 `environment/server-access/SERVER_ACCESS_LOCAL.md`；公开仓库使用示例。后续仍需解决物理停止/隔离依据、恢复实验与 TIMING-7，不以发布或历史输出重核扩大接收结论。

2026-11-11 本轮用户两项任务的接续：**扩大独立验证已完成；物理故障恢复尚未完成，三模型超时/故障路径已有新增实证和修复。** 独立 E 先冻结新合法输入与答案，再用当前 `sticky-device-fault-v1` C runtime 完成 SimX/处理器 RTL/NOXRT AFU/U280 各 48/48，合计 192 次新执行、576 份全数组和 576 份参数快照接收通过。六个 PTX 源含三种合法等价变体，12 份仿真/板上模块新构建；每路一个 context/queue、41 次装载、两代正常 buffer 分配。不是旧 E 的继承接收，也不是人类 E 签名。[E 签发](../results/e-runtime-unseen-acceptance-20261111-v1/result.json)、[任务范围与完整复现](E_RUNTIME_UNSEEN_ACCEPTANCE.md)、[交付索引](../results/c-runtime-unseen-delivery-20261111-v1/result.json)。

板测 `e-u280-unseen-20261111-v1`：b1/index 3、HOST 256 MiB、实际 200 MHz、固定 UUID/D10/D12，48 次连续启动、前后门禁、13 条远程命令及 SSH/接收退出 0，E 直接核验 305 份回传原件。入口为 `scripts/e_runtime_board.py prepare` 与 `scripts/Invoke-EUnseenU280.ps1`；必须新 run_id，准备前要求三路 E capture/acceptance 与当前生产哈希匹配。板端 Python 3.6 通过直接调用模块 validate API 预检，避开 build CLI 的较新 argparse 选项；不安装软件。[真实板测](../results/e-u280-unseen-20261111-v1/result.json)。最终自测 269 项中 **268 通过/1 跳过**、退出 0，当前源码快照与旧 E/根契约保护项核验通过。[收尾自测](../results/c-runtime-closeout-20261111-v1/summary.json)。

恢复修复 `scripts/ptx_runtime.py` SHA-256 `17ec7272b8fd369841cd681d06cb4ddd30f03c19ceb6c70abcf7db3a53110431`：永久锁存非 timeout 原生故障，阻止底层 finish 清除错误后的重复 recover 误放行；超时排空同时检查原始 event，再释放/失效旧句柄。三模型各两次真实等待超时、两次失败 drain 与两次成功 drain，另各一次原生 CP DEVICE_LOST 后 3 次恢复重试拒绝；故障模型进程终止后另起进程 canary，通过范围已分开记录并获 E 独立证据审阅。[恢复报告/复现](RUNTIME_RECOVERY_20261111.md)、[api_v2](../configs/c_runtime/api_v2.json)。物理 recover 仍 E_UNAVAILABLE，**硬件停止/旧 DMA 隔离依据 BLOCKED，物理故障恢复 NOT_RUN**；下一步需平台方提供固定 shell/D10/D12 的可靠停止或隔离条件，再安排隔离窗口实验。不要把合法板测、队列 barrier、KDS 空闲或进程退出充作该证据。TIMING-7 OPEN；根 lock/caps、旧冻结答案、固定源码及原失败记录不变。

2026-11-11 C runtime 接续完成：**本地代码合入、三路仿真及物理 U280 各 41/41 PASS**。最终源版本 `c-runtime-merge-20261111-v3` 已重新构建六份模块，31 条子命令与入口退出 0，自测 257 通过/1 跳过；板测 `c-u280-runtime-20261111-v3` 在 b1/index 3、HOST 256 MiB、实际 200 MHz 下完成 copy 13、vadd 13、affine 15，每程序一个 context 内重复启动。四路共 164 次执行、48 次拒绝，每路 261 份数组与 164 份参数复核通过。SSH、远程命令、接收与收尾核验退出 0。[合入说明/复现](C_RUNTIME_MERGE.md)、[当前交付索引](../results/c-runtime-delivery-20261111-v1/result.json)。

入口为 `scripts/ptx_runtime.py`、`scripts/ptx_u280.py` 和 `scripts/Invoke-CU280Runtime.ps1`。复现必须新 run_id，并从当前 v3 验证记录准备板测包；运行器字节不匹配时先重做本地验证。服务器 CPython 3.6.8 用输入包内原版 dataclasses 0.8，前端补丁 `python36-integer-v1` 不改变整数/PTX 语义，所有模块须按新源构建。板测 v1 缺依赖、v2 `str.removesuffix` 失败均在设备访问前停止，原件保留。旧前端、根契约、固定源码和 E 答案未改，无服务器安装/系统改动，未公开推送。下一步 E 独立接收新 C API 组合；物理恢复禁用、故障隔离 NOT_RUN，TIMING-7 OPEN。

2026-11-11 C/A/B 衔接核对：已原样检出 [C 固定提交](https://github.com/LiuZeheng123/GPGPU-runtime/tree/7f3575db67888c03d1c2c4dc3743051c735519dd) 至 `build/c-ab-integration-20261111-v1/source/`，使用其模块/Runtime 和 A/B D5 库完成 **SimX/处理器 RTL/NOXRT AFU 各 41/41 PASS**，共 123 次新执行、36 次拒绝；输入/输出三路一致，15 条子命令及入口退出 0。C 原工作树、两边 12 项契约原件保持。C 历史三路 2520 次归档复核通过；宿主自测 C 143 通过/14 跳过、A/B 162 通过/1 跳过，退出 0。[完整差异、A/B 给 C 的材料和复现](C_AB_INTEGRATION_20261111.md)、[收尾索引](../results/c-ab-integration-review-20261111-v1/result.json)。

这是隔离集成，不是主实现合入或 C 板上接收。下一步由 C/D 分版本处理 v1.2 前端与旧冻结产物，再将 C 新模块/生命周期层接到 D10/D12；物理后端、U280 平台宏、BDF/HOST/UUID/时钟门禁需显式适配。C 的恢复仅为仿真队列排空，硬件故障隔离仍 NOT_RUN；TIMING-7 保留 OPEN。v1 压缩归档检查超时、v2 AFU 绑定继承旧库目录的失败原件保留；v3 仅重新执行三路，宿主/归档检查引用 v2，不重复计数。入口为 `scripts/check_c_ab_integration.py`，默认完整检查，新运行必须换输出目录；C 原码和旧证据不覆盖。

2026-11-11 A/B 本轮收尾：**67 条 PTX 边界在 SimX、处理器 RTL、NOXRT AFU、U280 各 67/67 PASS**，三镜像新构建同哈希、268 次新执行，四路复核退出 0。B=1/4/7/16/31/32，N 覆盖既定 11 个边界至 1024；每路 180 数组/67 参数逐字节一致，DEBUG3 两路各 13,866 读/7,884 写通过。275 条仿真构建/运行子命令退出 0；旧 v1—v5 失败原件保留，日志 I/O 优化保持原始字节及 30 秒等待阈值，SimX/RTL 槽位关联只改变分析视图。完整 WSL 自测 162 通过/1 跳过/退出 0，两份固定源码各 3,329 项及 197 份 FPGA 报告核验通过。[四路复核](../results/u280-boundary-review-20261111-v1/result.json)、[A/B 交付入口](AB_CLOSEOUT.md)、[恢复限制](AB_RECOVERY_LIMITS.md)、[最终交付索引](../results/ab-delivery-20261111-v1/result.json)

新 `Invoke-U280BoardSmoke.ps1 -PtxBoundaryRun ptx-boundaries-20261111-v6` 已实际一次 SSH 执行 67 条，每条核对门禁、固定同卡，失败即停止。[真实板测 v3（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-6686d200ee75)于 09:30:15 完成：b1、HOST 256 MiB、实际 200 MHz，67 次宿主编译/设备执行及 SSH 均退出 0，执行前宿主哈希与退出后空闲状态已归档。[准确输入包回放（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-df091cc6fae4)核对 515 项输入，5 条代表用例共 10 次模型执行及 5 次错误 BDF 提交前拒绝通过；该回放的 XRT 查询为 stub。v1 SSH 认证中断、v2 临时重连脚本换行导致的本地哈希门禁失败均保留；v3 仅换 run_id/nonce，原输入和 worker 不变。后续按交付清单的新 run_id 命令复现，再由 E 独立接收新增序列和边界。TIMING-7 继续按已有要求跳过、保留 OPEN。C/D 通用 API、旧事务隔离/有界恢复及性能实验仍未完成；根 lock/caps、E 冻结答案和固定源码未改。

2026-11-10 23:57 A/B 接续新增 **PTX 同一设备上下文序列四路 PASS**。SimX、处理器 RTL、NOXRT AFU、U280 各 30/30 合法启动、12/12 非法 Block 拒绝后的后续运行通过；每路一次设备打开、一个 queue、29 次模块装载、两代复用/重分配缓冲区。108 份数组/拒绝快照四路逐字节一致，每路 30 份参数通过，DEBUG3 两路各 1,806 读/1,160 写逐 lane 核对通过。[v3 汇总（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-1128c885d06b)、[四路复核](../results/u280-ptx-sequence-review-20261110-v1/result.json)、[复现与限制](AB_PTX_SEQUENCE_PROGRESS.md)。v1 的实际 SimX/RTL 编译运行退出 0，最终因检查器不支持连续 CTA 编号而 FAIL；修复依据同周期 KMU/core 握手，v3 只复核这两路原件并新运行 AFU。v2 库名选择错误、Windows 沙箱临时目录错误均保留，不回写旧结果。

WSL 自测 149 通过/1 跳过/退出 0；98 项板测输入、Python 3.6 语法和两份固定源码检出各 3,329 项通过。准确输入包在 SimX/RTL 各回放 30/30，错误 BDF 两次在设备打开前拒绝，XRT 查询明确为 stub。[核验（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-3c7bc96af42e)。[真实板测（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-be720ff6ca99)在 b1、HOST 256 MiB、UUID/实际 200 MHz 核实后完成，编译、执行及 SSH 均退出 0，执行前宿主 ELF 哈希已采、退出后 KDS 空闲。下一步可将新序列交 E 接收、由 C/D 提炼通用 API；按新 run_id 用 `-PtxSequenceRun ptx-sequence-20261110-v3` 复现即可，无需 FPGA 重建。TIMING-7 继续跳过，根 lock/caps 不变；同步提交前拒绝不是超时/故障恢复，独立 E 序列接收及 C/D 通用 API 仍待完成。

2026-11-10 22:22 用户要求的 **E 固定 15 条 PTX 独立接收已完成，限定范围 PASS**。独立上下文的非作者代理从 PTX/原始输入先冻结 oracle 与答案；重新构建三份同哈希 vxbin，在新目录执行 SimX、处理器 RTL、NOXRT AFU、U280 各 15 次。156 份数组、60 份参数通过；两路 DEBUG3 每路 903 读/580 写以及 N=0/尾部假谓词独立核对通过。2 正控制+23 负例达到预期；根 WSL 自测 139 通过、1 跳过、退出 0。[E 签发报告](../results/e-ptx-acceptance-20261110-v2/acceptance.md)、[机器结果](../results/e-ptx-acceptance-20261110-v2/result.json)、[任务卡和复现](E_PTX15_ACCEPTANCE.md)

U280 本轮用 `u280-board-ptx-regression-e-20261110-v2`，15 次实际执行与 SSH 均退出 0；v1 认证断连留存。另取回 15 组135份板端原件补齐宿主 ELF 的运行后哈希，与原执行输入/日志绑定。补采 v1 和总接收 v1 的换行失败、E checker 开发及环境/记录失败均有原件；独立冻结答案未改。**TIMING-7 按用户要求本轮跳过，OPEN 保留**。下一步可另做未见合法语料接收与 C/D 通用 runtime；本轮不扩大为完整 P0、同一 context 连续启动/恢复或正式人类 E 签名，根 lock/caps 未冻结。

2026-11-10 21:44 A/B 接续完成。新增 `Invoke-U280BoardSmoke.ps1 -PtxRegression`，一次 SSH 在 b1 卡完成全部 15 条已通过双仿真/NOXRT 的 PTX 用例：6 copy、4 vadd、5 affine，**15/15 PASS**。每条重新核验 HOST、BDF、UUID、实际 200 MHz 和退出后空闲；15 次宿主编译、15 次板端运行与 SSH 均退出 0。39 份完整数组、15 份参数四路逐字节一致，本地复核退出 0。[板测（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-35c58f764bb5)、[四路复核（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-36ed337a21bc)、[复现说明](PTX_FRONTEND_PROGRESS.md#2026-11-10-2144-ab-的-15-条-ptx-板上回归)

WSL 运行器自测 133 通过、1 跳过，退出 0。离线核验 114 项输入文件、Python 3.6 语法与 3329 项固定源码，根 lock/caps 不变。本轮未重跑处理器 RTL/AFU，旧结果均保留。TIMING-7 仍 OPEN；下一步 A/C/D/E 独立接收这组证据及未见合法语料，C/D 补通用 runtime 与同一 context 重复启动/恢复，B 等待固定 shell 的时钟关系或复位释放处置依据。[自测（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-879fa9beca12)、[离线核验（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-bbe6f92405d8)

2026-11-10 21:02 TIMING-7 专项补采完成。基线 Vivado 501.875 秒、SSH、解包和 38 份报告/日志的本地复核退出 0。实现版报告与正常退出日志已恢复，原退出码未记录。双向 CDC 明细、min/max 端点和例外分类与平台基线一致。TIMING-7 仍 `OPEN`，后续需平台维护者说明实际时钟关系与复位释放安全性或给出固定版本的处置结论。[报告与范围](AB_D13_PROGRESS.md#2026-11-10-2102-两套专项报告已回传)

给学长确认 shell 处置的附件已备好，包含两份 DCP 的 methodology、clock interaction、双向 CDC 和复位拓扑原件及身份索引。10 份报告哈希与回读核验通过，退出 0。消息已起草，待用户转发。[附件（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-2a0f4f4a4267) · [打包记录（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-aa889d6d5f03)

2026-11-10 20:38 A/B 接续。已用 `-PtxSuite` 一次 SSH 在 `0000:b1:00.1` 完成 B=32/G=3/N=65 的 copy `0106`、vadd `0106`、affine `0322`，**3/3 PASS**。逐条读回 HOST 256 MiB、UUID 与实际 200 MHz，退出后 KDS 空闲。D5 NOXRT AFU 执行 15/15 PASS，三条板测的 8 份数组与 3 份参数四路逐字节一致。WSL 运行器自测 125 通过、1 跳过、退出 0。E 独立接收及其余 12 条 PTX 上板待做。[批次结果（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-631f4d32c0b3)、[四路复核（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-d32e2624a0b3)、[复现与 AFU 证据](PTX_FRONTEND_PROGRESS.md#2026-11-10-三条-ptx-板测与-noxrt-回归)

2026-11-10 21:01 TIMING-7 独立检查。原 SSH 已断开，原 v1 留存。实现版日志显示正常退出，16 份报告在服务器，原进程退出码未记录。基线未生成。已打开独立 v2 窗口补采基线并下载实现版原件，当前只有本地 `RUNNING` 状态。下一步收到回传后按双向 CDC、例外和 reset 扇出逐项审阅，告警仍 `OPEN`。[只读检查（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-77d966dff73f)、[v2 传输（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-a5beea4c5bf7)

2026-11-10 20:25 A/B 接续。`-PtxDeviceRun -PtxEntry -PtxCase` 可用通过双仿真的冻结 case 生成单条 U280 输入包。copy `0106`、vadd `0106`、affine `0322` 各一包，B=32/G=3/N=65。准确解包回放含原 copy `0026`，SimX 和处理器 RTL 各 4/4 PASS，4 次错误 BDF 注入均在设备打开前拒绝。回放 stub 仅覆盖 XRT BDF 查询，真实 U280 为 `NOT_RUN`。B 的 TIMING-7 窗口已启动，本地 transport `RUNNING`，截至交接未收到远端报告。下一步接收服务器报告，再按门禁分次跑三个板上包并复核字节。 [准备与回放](PTX_FRONTEND_PROGRESS.md#2026-11-10-u280-ptx-输入包与本地回放) · [TIMING-7 传输（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-076a7b47afb0)

WSL 运行器自测 122 通过、1 跳过、退出 0，新增检查覆盖 affine 的最大 u32 参数和重叠设备缓冲区拒绝。远端脚本通过 Python 3.6 语法检查。[运行器自测（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-dd8f110ff4d3)

2026-11-10 20:13 A/B 接续。vadd 和 affine 分别生成固定 RV64 vxbin，SimX 和处理器 RTL 各 9/9 PASS，逐 Block、指令 PC、有效 lane 地址核对每路 646 读/323 写。两个 N=0 均发出参数读取，数组请求为零。原 copy 重跑通过且 vxbin 与首测一致。A 下一步可交 E 独立复现并和 B/C 接续上板打包，当前新增用例 U280 为 `NOT_RUN`。B 新增 `Invoke-U280Readiness.ps1 -Timing7`，固定 D13 两份 DCP 哈希和定向报告清单，`-PrepareOnly` 与 Tcl 离线检查均退出 0。实际补采需要服务器 SSH 登录，现为 `NOT_RUN`，TIMING-7 仍 `OPEN`。[A 复现](PTX_FRONTEND_PROGRESS.md#2026-11-10-ab-的-ptx-vadd-与-affine-设备验证)、[B 入口](AB_D13_PROGRESS.md#2026-11-10-专项采集入口)

本轮 WSL 运行器自测 120 通过、1 跳过、退出 0。最终 Tcl 版本另通过 5 项定向 bundle 检查与 16 项模拟输出核对。[全套运行器日志（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-aab526265126)、[bundle 自测（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-548af42ac1aa)、[Tcl 离线检查（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-8f79ad0940ed)

2026-11-10 19:59 A/B 接续。复用首测的 `copy_u32` vxbin、冻结语料和经哈希核对的 D6 DEBUG=3 库。B=32 的 N=0/32/33/63/64/65 在 SimX 与处理器 RTL 各 6/6 PASS，逐 Block、逐地址核对各 257 读和 257 写。N=0 的 32 个逻辑线程进入参数读取，数组读写为零。参数和 x/z 含哨兵均通过；新增用例的板上执行与 E 独立接收为 `NOT_RUN`。A 后续可复用这组输入并扩展 PTX vadd/affine。B 已完成 TIMING-7 归档复查，当前 `OPEN`，先补原 DCP 的 CDC、例外覆盖和复位释放/时钟关系证据，或取得确切 shell 版本的维护者结论。[仿真命令与结果（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-cbb2d629184d)、[时序缺口](AB_D13_PROGRESS.md#2026-11-10-timing-7-证据复查)

2026-11-10 任务映射交接：新增[任务 1 / 任务 2 完成情况与语义映射审阅表](TASK1_TASK2_PROGRESS_20261110.md)。按用户验收标准，原生 vadd 的 SimX/RTL/U280 功能闭环已有证据；完整配置研究和正式独立验收尚未完成。PTX copy 仅一组 N=7/B=4/G=2 三路通过，不能替代 PTX 多 Warp、一般分支或 shared/local/barrier 接收。HOST 与实际时钟已在本轮板测中核实，TIMING-7 仍 OPEN；本次文档整理未新增实验。下一步沿现有 wrapper 扩展设备语料并完成独立复现。

2026-11-10 19:07 **PTX P0 首条 copy 在 SimX、处理器 RTL、U280 均 PASS**。以现有 `copy_u32.ptx` 生成语义体，经 `native/ptx_copy/kernel.cpp` 传入四个逻辑线程坐标与设备访存，使用固定 VOLT 和上游打包器生成命名 vxbin。三路实际装载同一 SHA-256 `78fdf5306a53d78e81420a85b26d913adc52333b9f5e580441b9c9abd0fb25c0`，runtime 解析入口 PC `0x180000034`。冻结用例 `0026` 的 x/z、24 字节参数三路逐字节一致，复制 7 个 u32，输出前后各 8 个哨兵字保留。U280 选中 b1，加载前空闲、HOST 256 MiB，核验 xclbin UUID `b60ca9fb-1506-3033-c156-e03ff687f492` 和实际 200 MHz 后才提交，完成后 KDS 无在途/上下文。设备编译、两级模拟、板端编译/执行和 SSH 均退出 0。首次 Clang 自赋值诊断失败留档，后续仅在生成头范围处理两类诊断，生成体 SHA 与原宿主版本相同。当前是单条用例与 Vortex2 runtime 接线，通用项目 API、其余 P0 用例和 E 独立接收待完成。[复现与接收范围](PTX_FRONTEND_PROGRESS.md)、[SimX/RTL 原始记录（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-84a05a4f827c)、[U280 原始记录（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-a6f0d9f8390a)、[三路比对（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-e14d0a00b6c6)

本地运行器自测使用随附 Python 3.12.14 和项目内临时目录，`python -B -m unittest discover -s tests -v` 退出 0，108 通过、10 跳过。离线复查确认远端脚本兼容 Python 3.6、原生单条/152 条输入范围正常、编译失败的 PTX run 无法进入上板准备。[自测日志（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-fe702a4e24ad)

2026-11-10 18:53 **完整 U280 原生回归 152/152 PASS**。在 `0000:b1:00.1` 当次复查 ready、shell、KDS 和普通账号可见持有者，HOST 读回 256 MiB。以 XRT index 3 打开并验证 BDF、D10 xclbin/D12 两库哈希，已加载 UUID `b60ca9fb-1506-3033-c156-e03ff687f492`。暂停在首条 kernel 前读回 XRT `DATA_CLK` 200 MHz，驱动 `icap.u.22020100/clock_freqs` 为 `200 / 500 / 450 / 0`。GCC 9 编译、原生宿主、SSH 和采集均退出 0，`CAPTURE_COMPLETE 152`，36 copy/36 vadd/80 affine，608 份 x/y/z/audit 输出在本地逐字节匹配。B=33/64 拒绝通过，退出后 KDS 上下文和在途任务均为 0，卡上保留该 xclbin。复现使用 `scripts/Invoke-U280BoardSmoke.ps1 -Regression` 和新的 run_id。结果限定原生 D5 同作者参考，PTX 设备执行和 E 独立接收仍待完成，TIMING-7 沿用 D13 OPEN。后续按合作协议接入 PTX 设备 wrapper、程序包与 runtime。[逐项比对（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-899bf14e1e4c)、[原始记录（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-ec97327189b8)、[传输记录（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-d2ba573126ba)

本地运行器自测使用随附 Python 3.12.14 和独立临时目录，`python -B -m unittest discover -s tests -v` 退出 0，108 通过、10 跳过。离线检查验证了回归输入顺序、608 份参考哈希、部分捕获分类及原 smoke 入口仍选单条 `010`。[自测日志（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-f57b9a2485fb)

2026-11-10 18:44 **U280 首条原生 smoke PASS**。本轮按用户授权在 `0000:b1:00.1` 受控加载，候选备卡未使用。加载前 shell 匹配、KDS 在途和上下文均为 0、普通账号未见持有者，HOST 为 268435456 字节。实际 XRT index 3 经 C++ API 对照 BDF 后才打开，复用 SHA-256 匹配的 D10 xclbin 与 D12 runtime。运行器在 `vx_device_open` 返回后暂停，先核实设备 UUID `b60ca9fb-1506-3033-c156-e03ff687f492`、`DATA_CLK` 200 MHz，再允许单次 `010` u32 copy。GCC 9 宿主编译退出 0，原生程序退出 0，`CAPTURE_COMPLETE 1`，四份输出逐字节匹配 D5 参考。退出后 KDS 上下文和在途任务均为 0，卡上仍加载该 xclbin。普通账号持有者检查仅覆盖可见进程，观测只对当次有效。后续完整 152 次原生板上回归和 PTX 设备执行仍 NOT_RUN，TIMING-7 静态审阅仍为 OPEN。[本轮原始结果（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-9fad70f8f7a6)、[传输记录（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-9a4bb2520b37)、[首测入口](../scripts/Invoke-U280BoardSmoke.ps1)

本地收尾：实际运行脚本已随结果留档。后续入口加严了 KDS 多行 client PID 检查，用本轮快照复核，空闲记录通过，带后续 PID 的记录被拒绝。Windows 默认 Python 首次自测受临时目录权限影响，改用随附 Python 3.12.14 和项目内临时目录运行 `python -B -m unittest discover -s tests -v`，108 通过、10 跳过、退出 0。[运行器自测日志（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-20b238b30c69)

2026-11-10 接续：学长报告已代为配置七张卡的 HOST，并允许按当次占用换卡。优先只读核查 `0000:b1:00.1`，备选 `b4`、`3d`、`40`、`41`，避开 `b2`、`b5` 和学长常用的 `3e`。256 MiB 容量、卡是否 ready/空闲及当前 BDF 与 XRT index 的映射均待现场核实。学长建议沿用原始平台 DCP 的既有项；D13 的 TIMING-7 对照符合这一描述，工具仍报 `Partial False Path (unsafe)`，按平台既有告警记录。确认选卡条件后，复用 D10 xclbin、D12 配套 runtime 和 D13 离线原生输入；加载后验证 UUID 和实际 200 MHz，再跑原生 smoke。上板及 PTX 设备执行仍 NOT_RUN。[HOST 只读复核](../environment/u280-fpga/HOST_SETUP.md)、[D13 时序对照](AB_D13_PROGRESS.md)

2026-11-09 GitHub 交接：[公开仓库](https://github.com/slishysun974/Vortex-U280)的 main 已同步 D13，提交为 `46dd01406a98ee6eab451a435c8a761b4b6a9eea`。公开副本在 `build/github-public-20261109-v1/`。上游 Vortex 以固定提交的子模块引用，公开证据按原件和脱敏副本分别列出。完整实验归档、服务器访问信息、课程资料及构建产物继续在原工作区保管。外部协作者通过 Fork 提交 Pull Request。后续发布使用该公开仓库并按相同范围审阅新增文件。[发布与自测记录](../results/github-public-20261109-v1/result.json)。

2026-11-09 文档交接：已新增[通俗版阶段进展报告](PROJECT_PROGRESS_REPORT_20261109.md)，用于了解项目已完成工作、验证范围与下一步。报告汇总截至 D13 的已有证据，本次未重跑实验或改变技术状态；HOST 权限与 TIMING-7 仍阻塞，实际时钟待加载后核实，板上功能及 PTX 设备执行仍 NOT_RUN。后续继续按下述 D13 结论推进。

2026-11-09 D13 最终：**DCP 采集/静态归因审阅完成，53/53 检查 PASS；HOST 与 TIMING-7 仍阻塞，上板 NOT_RUN。** v2 两份 Vivado 718.449/435.335 秒均退出 0，20:13:13 采集结束。8 项 Critical Warning 在原始平台中已有，新增 1 项为 200 MHz 可调时钟约束；TIMING-14 的 20 个 fanout 及 12 条 clock-group 命令/作用域与基线一致，7 项记录为已审阅的平台保留项。**TIMING-7 仍显示 Partial False Path (unsafe)**，不能用基线相同/正余量直接关闭；TIMING-1 仍需加载后实际 200 MHz。10 个缺 delay 端口与基线逐项一致、内部未约束端点均为 0。HOST 因 `u280user may not run sudo on localhost` 未执行配置；不要重复尝试 sudo 密码。用户要求先解释结果与最小需求，再自行申请权限。详见 [D13](AB_D13_PROGRESS.md)、[最终审阅](../results/u280-readiness-review-20261109-v2/result.json)、[管理员操作](../environment/u280-fpga/HOST_SETUP.md)。152 次原生输入离线准备 PASS，Linux 自测 117 通过/1 跳过，固定源码 3329 项零差异；旧失败原件保留，不重复 link。

2026-11-09 D12 最新：**服务器 runtime200 编译/依赖检查 PASS；上板就绪 BLOCKED，板上功能 NOT_RUN。** [v4（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-6fd74a22d0c9) 于 19:33:31 完成，SSH/采集退出 0；GCC 9.3.1 / glibc 2.17 / XRT 2.13.479，公共库 10.833 秒、真实 XRT backend 1.420 秒，两个库 ldd 通过并已返回本地。采用独立 `gcc9-vm-allocation-v1` / binding-v2：检查两处 VM 地址分配失败，避免未初始化变量；生成 Makefile 只在缺少固定 XCONFIGS 时运行生成器；入口先加载 XRT setup。v2 编译失败、v3 依赖失败、v1 终端接入中止原件保留。8 卡当次 ready/无 KDS 在途任务，HOST 仍为 0、sudo 权限未确认。D11 机器摘要空表/关键告警零计数是目录页截断缺陷，新 [报告审阅](../results/u280-timing-review-20261109-v2/result.json)已纠正并核对总数：methodology 100 项中的 9 项 Critical Warning 全部 OPEN，普通 DRC 343 项无 Error/Critical Warning；旧结果不改。最终自测 113 通过/1 跳过，退出 0。[D12](AB_D12_PROGRESS.md)、[服务器库位置/入口](../environment/u280-fpga/RUNTIME.md)、[补丁](../environment/u280-fpga/PATCHES.md)。下一步 HOST 权限/预留、平台约束告警与缺 delay 全端口核实、受控加载后 UUID/实际时钟，再做原生上板；无需重编 link。固定源码、根 lock/caps 和全部旧证据保留。

2026-11-09 D11 最新：**归档与 runtime200 本地准备 PASS；上板就绪 BLOCKED、板上功能 NOT_RUN。** [v5（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-b0264f99ea10) 已将完整 xclbin 与 197 份原始报告取回本地并校验，见 [本地 xclbin（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-740be5623f6b)。整体时序 WNS +0.016 ns / WHS +0.006 ns，kernel 00 保持 +0.119/+0.009 ns，布线错误 0；**9 项 methodology Critical Warning** 尚未关闭，特别是 5 ns 约束和时钟模块默认 3.333 ns 的差异。新 [runtime200 输入包（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-17e0b6518b5b) 仅将宿主编译频率 400→200，Ubuntu 公共库编译 PASS；服务器 GCC 9.3.1 与六个 XRT 头文件实际存在，但真实服务器编译仍 NOT_RUN。脚本自测 103 通过/1 跳过，退出 0。网络 WinError 10013 经只读 WFP 排查发现 Surfshark Local network visibility 残留规则；用户刷新开关后两条路径 SSH 握手恢复、v5 登录/归档成功。v1-v4 原件保留。下一步按 [D11](AB_D11_PROGRESS.md) 和 [runtime 构建说明](../environment/u280-fpga/RUNTIME.md) 编译服务器库并核实平台告警/HOST/当前空闲卡；不重复提交 link，不再下载已有产物，固定源码和根 lock/caps 未修改。

2026-11-09 15:56:47 最终复核：**D10 完整 FPGA 构建 PASS**。原作业 `u280-link-20261109-103830-671` 于 **15:48:08** 完成，v++ 18565.056 秒、退出 0、未超时，固定 200 MHz clock_check 退出 0（setup WNS +0.119 ns、hold WHS +0.009 ns，289539 endpoints）。[最终采集（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-81f7f83fc7c7)、[D10](AB_D10_PROGRESS.md)。服务器产物 `/home/course/u280user/vortex-u280-builds/u280-link-20261109-103830-671/out/vortex_afu.xclbin` 为 53,950,442 字节，SHA-256 `bbac2ab73073b24ba857fb34eadf22bf1c11dc745527f064c4eec61b70d2c843`；尚未下载到本地。worker 退出 0、作业已结束，不必重新提交构建。下一步归档完整报告/元数据，准备 HOST 通路、兼容的服务器 runtime 和实际 200 MHz 频率绑定，再进行原生上板；HOST 配置、板卡加载、板上功能均 NOT_RUN。

2026-11-09 15:27:25 最新复查：D10 原作业 `u280-link-20261109-103830-671` **RUNNING，布线完成、bitstream 生成中**。[新采集（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-56d015287cbc)观测 worker/v++ 存活约 4 小时 49 分；15:02:52 routing 完成并开始 bitstream generation，可选布线后物理优化随后显示完成。最终 xclbin/v++ 退出码/固定时钟检查仍未取得，不能提前记录完整构建 PASS；继续查询同一 BuildRun。

2026-11-09 15:01:35 最新复查：D10 原作业 `u280-link-20261109-103830-671` **RUNNING，布线后时序分析中**。[新采集（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-8e0513690271)观测 worker/v++ 存活约 4 小时 23 分；日志 15:00:18 为 `Phase 12 Post Router Timing`。尚无 routing 整体完成、最终 xclbin 或固定时钟检查 PASS；后续只读查询同一 BuildRun，不将该时序分析阶段当成时序已达标。

2026-11-09 14:31:52 最新复查：D10 原作业 `u280-link-20261109-103830-671` **RUNNING，布局完成、正在布线**。[新采集（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-deb3f34fbfb8)观测 worker/v++ 存活约 3 小时 53 分；14:18:55 placement 完成并启动 routing，14:31:42 为 `Phase 4 Rip-up And Reroute / Phase 4.1 Global Iteration 0`。仍待布线、最终产物和固定时钟检查结果，后续查询同一 BuildRun，不重启构建。

2026-11-09 14:14:55 最新复查：D10 原作业 `u280-link-20261109-103830-671` **RUNNING，布局收尾清理中**。[新采集（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-4516a933ef40)观测 worker/v++ 存活约 3 小时 36 分；最新日志 14:10:45 为 `Phase 4.4 Final Placement Cleanup`。较前次全局布局持续推进，但尚无布局完成或开始布线的确认，更无最终 xclbin/时钟检查 PASS；后续查询同一 BuildRun。

2026-11-09 13:47:27 最新复查：D10 原作业 `u280-link-20261109-103830-671` **RUNNING，正在全局布局**。[新采集（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-07ec2e373d5c)观测 worker/v++ 存活约 3 小时 9 分；最新日志 13:47:15 为 `Phase 2.5.1 UpdateTiming Before Physical Synthesis`，较 13:14 布局初始化继续推进。布线、最终产物与固定时钟检查仍未取得完成结果，继续只读查询同一 BuildRun。

2026-11-09 13:14:26 最新复查：D10 原作业 `u280-link-20261109-103830-671` **RUNNING，正在布局**。[新采集（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-b6b30250fccb)显示 13:13:02 逻辑优化完成并启动 placement，13:14:04 处于 Placer Initialization；worker/v++ 存活约 2 小时 35 分。后续还需布线、产物生成、固定时钟检查；尚无最终 xclbin PASS。继续只读查询同一 BuildRun。

2026-11-09 12:37:02 最新复查：D10 原作业 `u280-link-20261109-103830-671` **RUNNING，已由综合进入实现**。[新采集（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-0865c79bef86)显示 12:34:27 模块级综合 156/156 完成，12:36:11 顶层综合结束并启动 `impl`；worker/v++ 存活约 1 小时 58 分。最终实现/时钟检查/xclbin 仍未取得，继续只读查询同一 BuildRun，不重启构建。

2026-11-09 11:27 最新复查：D10 原作业 `u280-link-20261109-103830-671` **RUNNING，仍在综合**。[新采集（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-c4a368bd0c31)观测 worker/v++ 存活约 48 分半；日志 11:26:49 为模块级综合 49/156 完成、2 个运行，持续推进，尚未进入布局布线。完整结果/xclbin 未取得；后续只读查询同一 BuildRun，保留旧快照。

2026-11-09 10:50:53 最新复查：D10 作业 `u280-link-20261109-103830-671` **仍在综合，RUNNING**；[采集目录（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-43a1a33f1bc1)为只读 Status，SSH 退出 0，没有新建远端构建。worker/v++ 运行约 12 分钟，日志 10:50:29 为 block-level synthesis 9/156 完成、2 个运行，尚未进入布局布线。后续仍查询同一 BuildRun；尚不能报告最终 xclbin、时序或板上 PASS。此前启动快照保留。

2026-11-09 D10：**完整 link 已实际启动，启动快照 RUNNING**。用户“按此启动”已授权 [方案](../environment/u280-fpga/NEXT_LINK.md)。作业 `u280-link-20261109-103830-671` 于 10:38:41 启动，10:38:44 SSH 退出 0；实际观测到 `v++ --link` PID `95311`（worker `95131`、builder `95132`），CPU affinity `[0,1]`、nice +10、6 小时 v++ 超时，无 RAM 硬限。RAM 约 329.7 GiB/磁盘 720.9 GiB 可用，输入/XO/平台身份核验通过；[启动证据（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-6225f2ba7c23)、[D10](AB_D10_PROGRESS.md)。Linux 93 项 Python 自测通过、1 跳过，退出 0。远端目录分别在 `~/vortex-u280-link-jobs/<run_id>` 和 `~/vortex-u280-builds/<run_id>`；查询 `scripts/Invoke-U280Link.ps1 -Mode Status -BuildRun u280-link-20261109-103830-671`，用户仅在本机输入 SSH 密码，无需再次授权资源。此快照不是实时完成状态，完整结果/xclbin 尚未取得；不能重复启动已有目录，也不能将传输 PASS 当成构建 PASS。

2026-11-09 D9：**真实 U280 XO PASS**。成功运行 `u280-preflight-20261109-100406-629` 的 SSH/Vivado 均退出 0，Vivado 340.708 秒；五个 IP OOC DCP/stub、U280 RTL elaboration、原模块接口 gate（13 类/22 个实例）及打包通过。服务器 XO 路径 `/home/course/u280user/vortex-u280-builds/u280-preflight-20261109-100406-629/out/vortex_afu.xo`，312,868 字节，SHA-256 `58ff5ed950d738f232f5fa70e4c4fcf82ebd2b73bb3d247cfc00133f51e66b0d`。首次 `095402` 缺 stub 失败原件保留；独立 `ip-ooc-v1` 仅修改新目录 Tcl `flow/`，gate 保持 error，固定源/根配置/D8 输入包未改。最新 HOST/platform 采集 `u280-preflight-20261109-094621-277` PASS，XSA↔8 卡 shell UUID 匹配；HOST 内存均为 0，sudo 需要密码，权限未确认。Linux 87 测试通过/1 跳过，[174/174 最终核验](../results/ab-d9-closeout-20261109-v1/result.json)通过，固定源 3329 文件零差异。[D9](AB_D9_PROGRESS.md)、[补丁](../environment/u280-fpga/PATCHES.md)、[下一阶段具体命令与资源方案](../environment/u280-fpga/NEXT_LINK.md)。完整综合/布局布线仍须先按既有要求确认资源；xclbin/板上功能未完成。

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

22:19 最新接续：用户明确要求再试另一个密码并在终端运行 `scripts/Connect-U280Server.ps1`，[实际结果（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-f9229e20536a) PASS，SSH 退出 0。远端执行 `id -un && hostname` 返回 `u280user` / `localhost`；网络与账号登录阻塞已解除，未执行工具或设备查询。默认路径超时、21:59 无密码预检与 22:01 密码失败记录均保留。详见 [登录交接（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-998b875bd224)。

22:32 用户已完成授权的密码修改。`scripts/Set-U280Password.ps1` 通过用户本机 SSH TTY 执行当前用户 `passwd`，[改密结果（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-68356460adf4) PASS、退出 0；随后独立连接的 [登录结果（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-85932b77e834) PASS、退出 0，身份仍为 `u280user` / `localhost`。首次改密尝试退出 255、UNCONFIRMED 的原件保留。密码和改密终端会话未保存，后续仍由用户本机输入当前密码。改密原件的 `new_password_login=NOT_RUN` 不回写，复核以独立登录记录为准；此项不改变板卡接收状态。

- G0 的原生执行与锁文件可追溯已有材料；C/D/E 的能力/ABI 和独立接收仍未完成，不宣称团队全链路已验收。
- D4/D5 已验证三类原生 u32 程序的可见输出，D6 补原生 LSU 观察范围内的假谓词/尾线程无数组请求证据。项目 P0 runtime/前后端与 E 独立答案仍未接收；原生结果不能替代 PTX 转换语义、任意非法指针行为、整段程序严格恰执行一次、安全中止/恢复或浮点 RTL。
- PTX 前端已有实施者自测与宿主生成代码验证入口；`Memory` 宿主审计模型的地址检查和访问 trace 不属于真实 Vortex 能力。静态类型/初始化分析与参数序列化不能替代模块装载、buffer 生命周期、launch 或故障恢复。
- 原 WSL Ubuntu 20.04 的兼容阻塞、Docker 启动失败与 NTFS Git 检查超时保留在历史证据中；D4 未重试 Docker。实际成功路线为专用 WSL，原生 Linux 固定检出的 3329 个文件与原清单零差异。
- U280 已核实本次功能运行的 HOST 通路和实际 200 MHz。平台既有 TIMING-7 仍为 OPEN，待 A/B 核实复位释放的跨域同步机制或取得对应平台版本维护者的结论。当前尚无板上性能对照、多 Core 或 Cache/Shared Memory 配置研究结果。[最新板上证据（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-a6f0d9f8390a)、[静态审阅](AB_D13_PROGRESS.md)

## 当前运行位置与恢复顺序

在 `Vortex-AB-Ubuntu-22.04` 中：

- 固定源码：`/opt/vortex-ab/sources/vortex-7fe19369587c-v1`；原始 `upstream/vortex/` 保留。
- 当前完整工具根：`/opt/vortex-ab/toolchains/8c64cf921d3c6c456e80f00d24482d0aa2153a82-rtlsim-d3-v1`；旧 SimX 工具根保留。
- D3 成功构建分别为 `/opt/vortex-ab/builds/ab-d3-simx-20261108-v1`、`/opt/vortex-ab/builds/ab-d3-rtlsim-20261108-v2`、`/opt/vortex-ab/builds/ab-d3-xrtsim-20261108-v1`；旧成功/失败目录均保留，新运行不得覆盖。
- D4 成功构建：`/opt/vortex-ab/builds/ab-d4-simx-20261108-v1`、`/opt/vortex-ab/builds/ab-d4-rtlsim-20261108-v1`、`/opt/vortex-ab/builds/ab-d4-xrtsim-20261108-v1`，不同 backend 完全隔离。
- D4 基线审阅日志、配置、源码清单、demo/kernel/runtime 和全部输入/参考/输出：`results/ab-d4-<backend>-20261108-v1/`；[D4 总索引](../results/ab-d4-closeout-20261108-v1/result.json)，历史 D3 目录保留。
- D5 候选成功构建：`/opt/vortex-ab/builds/ab-d5-block32-20261108-v1-simx`、`...-rtlsim`、`...-xrtsim`。对应证据在 `results/ab-d5-block32-20261108-v1-<backend>/`；[D5 总索引](../results/ab-d5-closeout-20261108-v1/result.json)。与 4w×4t 基线产物严格分开。
- D6 DEBUG=3 / 8w×4t 隔离构建：`/opt/vortex-ab/builds/ab-d6-trace-simx-20261108-v1` 和 `...-rtlsim-20261108-v1`。成功执行记录分别为 `results/ab-d6-trace-simx-20261108-v2/`、`results/ab-d6-trace-rtlsim-20261108-v1/`；SimX v1 为解析器失败父记录，v2 没有完整重建。禁止与普通性能或其他 backend 产物混用。

1. **固定 15 条已接收，后续另做未见语料。** 非作者 E 完成三镜像重建与四路 60 次新运行、独立答案/ABI/两路 LSU/负例接收。E 复现和总接收入口为 `scripts/e_acceptance/reproduce.py` 与 `receive.py`；上板仍用既有 `-PtxRegression` 门禁。每次新 run_id，冻结答案不得修改。[接收报告与范围](E_PTX15_ACCEPTANCE.md)
2. **复用当前 U280 配套。** 使用 D10 xclbin（D11 本地归档）和 D12 `gcc9-v1` runtime。可优先复查 `0000:b1:00.1`，按当次采集核对空闲状态、BDF/index、shell 和 HOST 容量，加载后核实 UUID 与实际 200 MHz。FPGA 成功构建流程使用 `--build-flow ip-ooc-v1`。[板测原始记录（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-ec97327189b8)、[运行库说明](../environment/u280-fpga/RUNTIME.md)
3. **完成项目接口与接收。** C/D 将样例适配提炼为通用项目 runtime，覆盖校验、生命周期、重复启动和错误恢复。E 冻结独立参考答案与验收用例，由接收方复现原生和 PTX 两条路径。当前默认 4w×4t 与独立 8w×4t 候选按各自的锁文件、配置和结果分别管理。性能配置研究与 AI 配对实验另设验收。[后续验收顺序](STATUS.md#后续验收顺序)

D8 本地源运行 `ab-d8-u280-source-20261109-v1`，构建目录 `/opt/vortex-ab/builds/ab-d8-u280-source-20261109-v1-{upstream_unmerged,candidate_merged}`。`results/ab-d8-u280-source-20261109-v1/u280-rtl-input.tar.gz` 只包含预处理源和脚本，不是已综合硬件。WSL 的 platforminfo 缺失警告原样保留，显式平台选择只用于离线预处理。`prepare_u280_fpga_candidate.py` 为一次性创建工具，现有候选不要重生成。

最新候选命令见 [D5 记录](AB_D5_PROGRESS.md)，原基线命令见 [D4](AB_D4_PROGRESS.md)，宿主准备见 [宿主方案](../environment/native-sim/README.md)。日常真实状态见 [STATUS](STATUS.md)，研究边界见 [RESEARCH_PLAN](RESEARCH_PLAN.md)。`capture_target.py` 是原始 draft-v1 初始化器，会重写当前 configs；D2 后不要用它作日常只读重核，使用原生运行器的 `--check-only`。`prepare_block32_candidate.py` 也是一次性独占创建工具，现有候选不要重生成。

## 文件与上下文边界

新根目录为 `D:\Vortex-U280`，不需要原工作区才能读取当前计划、脚本、配置、源码或参考原件。旧 AEC/FIFO 和课程连接工具不在本项目中；既有日志中的旧绝对路径是当时现场，保留不改。新 Codex 聊天先读本文件和状态页；不依赖旧聊天转录才能继续工作。
