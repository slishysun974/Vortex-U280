# A/B D13：HOST 权限与实现 DCP 审阅

2026-11-10 21:44 当前接续：HOST 与实际 200 MHz 已在后续原生 152 次和 PTX B=32 的 15 次板测中逐批验证，最新 15 条全部 PASS，退出后 KDS 空闲。[最新 PTX 板测（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-35c58f764bb5)。TIMING-7 继续 OPEN：本轮只新增功能运行与字节复核，没有新增时钟关系、目的域复位释放或平台维护者接收依据；21:02 专项报告的结论保留。以下 11 月 9 日段落为当时的历史状态。

2026-11-09，Asia/Shanghai。用户要求先处理 HOST 内存与 9 项 methodology Critical Warning，满足条件后上板；随后明确先完成时序审阅、说明现状和最小权限需求，再由用户申请权限。

**最终状态：DCP 采集与静态归因审阅完成，53/53 证据检查 PASS；HOST BLOCKED，TIMING-7 平台跨域项仍 OPEN，实际 200 MHz 待加载后核验，上板 NOT_RUN。** 这里的 PASS 只覆盖采集/对照，不表示九项告警已消除。八项在原始平台中已有，一项来自本次 200 MHz 可调时钟约束。[最终审阅](../results/u280-readiness-review-20261109-v2/result.json)保留每项处置与原始证据；v1 机器摘要仍保留。

## 已确认的结果

- [v1（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-7f14460d1290) 实际连接/返回成功，但业务 FAIL。`sudo -v` 退出 1；用户终端报告 `Sorry, user u280user may not run sudo on localhost.`，单独记录在 [权限说明（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-b6509aeadd2d)。HOST enable 未执行，8 卡当次 ready/无 KDS 在途任务、HOST 均为 0；未获得卡预留。不得重试密码来绕过策略。
- v1 的 DCP 选择器只识别 `hw_bb_locked_*`，拒绝了实际文件名。返回的 71512 字节 DCP 清单明确顶层最终路径为 `.../prj.runs/impl_1/level0_wrapper_postroute_physopt.dcp`，273620447 字节。已修正选择器，保留 v1 原件。
- [v2 传输记录（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-65a91c84c8aa) 于 20:13:13 完成。实现 DCP Vivado 718.449 秒、平台基线 435.335 秒，两者及 SSH/采集均退出 0、未超时，两个 optional_errors 文件为空。每次 Vivado 限两个 CPU、nice +10、900 秒，不综合/布局/布线，不写回 DCP，不新增 timing waiver，不加载板卡。实现 DCP SHA-256 为 `4942bb1979f74e60bbbd8d20ce9779ec1cdee675d2a3217453e505ac4cd26c19`；从已核对 XSA 提取的基线 DCP 为 `f5cee615c973ebd572f85ce6d412edbf273115b8f7b061874d286caa3408bcf3`。
- [Linux 运行器检查](../results/ab-d13-script-checks-20261109-v2/result.json) 实际运行 118 项，117 通过、1 跳过，退出 0。Windows v1 因沙箱临时目录权限失败，原日志保留；不是硬件失败。
- [原生板上输入准备](../results/u280-board-input-20261109-v1/result.json) 本地 PASS：1227 项输入身份核对，保留 D5 的 152 次 native u32 测试和已有期望值，绑定 D12 CentOS 两库/200 MHz 配置。包 778092 字节，SHA-256 `aef92fecdb42dc189afd26184ca2c8df7edfb27404d89218299d80779a4df05e`。只完成离线准备，宿主测试程序服务器编译、上板加载、板上运行全部 NOT_RUN。

## 九项告警的实际审阅结论

| 项目 | 数量 | 实际证据 | 处置 |
|---|---:|---|---|
| TIMING-1 | 1 | 仅实现 DCP 出现；kernel 约束 5 ns，MMCM 输入 100 MHz、乘 12/除 4 的初始设置为 300 MHz；D10 使用可调时钟/200 MHz 元数据 | 静态原因已定位；加载后必须核实 UUID 与实际 200 MHz，再允许执行 kernel。未实测，未添加 waiver |
| TIMING-7 | 1 | 原始平台已有；两份 DCP 的正向 10 条/反向 9 条采样路径、slack、exception 一致。正向是 PCIe debug 异步复位，反向是 XPM 同步器的既有 false path；clock interaction 两者均为 `No Common Node / Partial False Path (unsafe)`，该表列 26 个端点 | **OPEN**。归因于平台不等于安全性关闭；需继续核实该复位跨域的有效时钟关系/复位释放同步机制，或取得确切平台版本的维护者处理说明。不能仅加 false path 清除告警 |
| TIMING-14 | 1 | 原始平台已有；固定 BSCAN LUT `DONT_TOUCH=1`、状态 FIXED；20 个 fanout 边界与基线完全一致，全部位于 `level0_i/blp/` 静态管理/调试部分 | 影响范围审阅完成，作为平台保留项；未修改固定 shell，未添加 waiver |
| TIMING-54 | 6 | 原始平台已有；全部 12 条生效 clock-group 命令及 current_instance 作用域与基线相同。kernel00 的 clock-interaction 条目中没有 Asynchronous Groups | 约束来源/当前影响范围审阅完成，作为平台保留项；不是全设计 CDC 已通过或告警已消除 |

methodology 总数：实现 100、平台基线 88；Critical Warning 分别 9 和 8。工具中九项仍存在，消除数 0，七项平台保留项已完成本次范围审阅，一项平台跨域仍阻塞，一项实际时钟留待受控加载验证。现有平台 XDC 中有针对 PCIe TXOUTCLK 的其它既有 waiver，不能挪用到本次 kernel MMCM。

缺 delay 的 10 个端口逐项与基线一致：输入 `io_data_satellite_ctrl_00[0..3]`、`io_perst_n_00[0]`、`io_uart_cmc_00_rxd`、`io_uart_satellite_ctrl_00_rxd`；输出 `io_hbm_cattrip_00[0]`、`io_uart_cmc_00_txd`、`io_uart_satellite_ctrl_00_txd`。两份 DCP 的内部未约束端点均为 0。它们属于平台管理/复位/状态边界，不等于已补齐外部器件 timing budget。

本次 clock-interaction 的 kernel00 自身关系显示 Clean、5 ns、0 failing endpoints；其 289801 是该报告口径，不能替换 D10 clock_check 的 289539。原始 D10 整体 WNS +0.016 ns / WHS +0.006 ns、kernel00 +0.119/+0.009 ns 的证据保持不变。新全 timing_summary 文件因超过 8 MiB 传输上限留在服务器；本地已有 D11 归档的完整 D10 时序报告，不能声称本轮新 summary 已下载。

时钟机制依据：[AMD Vitis 2023.1 平台时钟说明](https://docs.amd.com/r/2023.1-English/ug1393-vitis-application-acceleration/Identifying-Platform-Clocks)明确可调时钟在 xclbin 加载时由 XRT 按元数据设置；[AMD scoped constraint 指南](https://docs.amd.com/r/en-US/ug903-vivado-using-constraints/Scoped-Timing-Constraints-Guidelines)说明仅有 IP 作用域不保证 clock exception 局限于 IP。上述仅支持解释和审阅方法，不充当本板卡实测。

## HOST 需求与权限边界

当前固定 XRT backend 在 `host_mem_alloc` 中使用 `xrt::bo::flags::host_only`；命令处理器通过 `m_axi_host` 访问命令队列和 DMA 暂存区。这是服务器 RAM 的一块预留区域，与板上 HBM 分开。缺少 HOST 不能以 HBM 资源表存在或 runtime 编译通过代替。

当前计划仅在一张当次空闲、shell 匹配的卡上申请 256 MiB HOST。管理员可代为执行，无需给 `u280user` 通用 sudo 权限。具体占用检查、配置命令和返回字段见 [HOST_SETUP.md](../environment/u280-fpga/HOST_SETUP.md)。[XRT 文档](https://xilinx.github.io/XRT/2022.1/html/hm.html)说明 <=1 GiB 无需 hugepages；必须先配置 HOST 再装载 xclbin。配置后的 Shared Host Memory 用于验证预留，Max/Enabled 字段在加载/实际使用前仍可能为 0。

## 验证入口

```powershell
# 仅时序审阅；自动使用新的 run_id，只需要 SSH 密码，不调用 sudo。
& 'D:\Vortex-U280\scripts\Invoke-U280Readiness.ps1' -TimingOnly
```

不带 `-TimingOnly` 的入口曾用于已授权的 HOST 配置尝试；目前已明确策略拒绝，不应再次运行该模式，除非权限状态实际改变。真实 sudo 交互继承用户可见 TTY，不管道输出、不转录；采集另用 SSH 返回经 nonce/SHA-256 校验的结果。

## 状态边界

处理器 RTL、NOXRT AFU 模型本轮未重跑；此前 D5/D6 结果仍有效但不能代替物理板卡。HOST 与 TIMING-7 仍阻塞，受控加载和原生板上功能 NOT_RUN；PTX 设备执行与 E 独立接收未完成。[3329 固定源检查](../results/ab-d13-source-checks-20261109-v1/result.json)零差异；根 lock/caps、D10 xclbin 和旧失败证据保留。[1227 项输入包 round-trip](../results/ab-d13-input-checks-20261109-v1/result.json)退出 0。

下一步先向用户解释以上结果，由用户申请管理员一次性 HOST 配置；并向平台维护者核实本版本的 TIMING-7 复位跨域保留项。两项前置条件解决后，再在当次空闲卡上受控加载，读回 UUID/实际 200 MHz/HOST 使用，先跑原生 smoke，再跑 152 次回归。权限到位本身不代表所有技术前置条件已满足。

## 2026-11-10 TIMING-7 证据复查

**OPEN。** 在固定平台 `xilinx_u280_gen3x16_xdma_1_202211_1` 的 XSA 基线和 D10 实现 DCP 中，`io_clk_pcie_00_clk_p`（100 MHz）→ `dma_ip_axi_aclk_1`（250 MHz）均列 26 个端点，`No Common Node / Partial False Path (unsafe)`。反向列 9 个端点，全部为 `Ignored / False Path`。D13 正向只取了 10 条 max 路径，采样中 `sys_reset_in_async_rst_inst/arststages_ff_reg[1]/Q` 经 LUT2 到 `debug_probes_inst` 的 `pre_ltssm_st_reg` / `ltssm_trace_cnt_reg` 异步 CLR，最小报告 recovery slack +0.185 ns。该 XPM 的 `dest_clk` 属于 PCIe 参考时钟域，采样终点的 `user_clk` 来自 GT `TXOUTCLK` 经 `BUFG_GT`。反向的 9 条采样来自 `negotiated_width`、`cur_speed` 和 `sys_rst_sbr` 的 XPM 路径。现有 XDC 可定位 XPM 输入侧约束，正向采样路径从 XPM 输出侧开始。板测的 HOST、UUID 和 200 MHz 记录见当前状态页。[时钟交互（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-b39c687ff299)、[正向（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-1ef4c6c6b318)、[反向（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-8ef62f71adf0)、[生效 XDC（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-2d440866cc19)

| 缺失证据 | 收集与判定 |
|---|---|
| 双向端点及生效例外的完整清单 | 在两份原 DCP 上按时钟对采集 `report_cdc -details -all_checks_per_endpoint -no_waiver`，逐项对照交互表中的正向 26、反向 9 个端点。补双向 min/max 路径、recovery/removal 检查和 `report_exceptions` 覆盖/忽略项。逐端点记录时钟、起终引脚、检查类型、作用域和命中的例外。CDC 结构报告和交互表的端点计数口径可能不同，应按对象归并。 |
| 运行模式下的有效时钟关系 | 核实 PCIe refclk 与 GT TXOUTCLK 在启动、复位和链路恢复时的主时钟、来源/传播及相位关系，取得平台设计依据。若存在可保证的关系，需要相应时钟约束及适用模式下的 recovery/removal 证据。 |
| 目的域复位释放或端点隔离 | 从 XPM `dest_arst` 追踪 LUT 的全部输入及 CLR 扇出，确认每个终点是否在 `dma_ip_axi_aclk_1` 域同步释放。若以 debug 逻辑在目标模式禁用或隔离为依据，提供固定 tie-off、配置或网表扇出的证据。反向逐一核对同步器级数、`ASYNC_REG`、首级例外范围，并说明多位 debug 量和 SBR 脉冲的使用条件。 |
| 若以平台已知项接收，缺版本匹配的维护者结论 | 提供适用于此 XSA/shell、PCIe IP/工具版本与同一时钟对的官方工单、发布说明或维护者签核，写明可接受的理由、适用模式及任何限制。当前记录支持告警归属平台。 |

本次在本地复查已归档报告。上述 Vivado 补采为 `NOT_RUN`。可先在原 DCP 上补报告，无需启动新一轮实现。正向 +0.185 ns 基于工具当前的时钟关系，板上功能 PASS 覆盖的是实际用例的功能执行。两项证据各自保留其原有判定范围。[原 DCP 和 XSA 身份（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-b32494352a08)、[Vivado 2023.1 CDC 命令](https://docs.amd.com/r/2023.1-English/ug835-vivado-tcl-commands/report_cdc)、[时序例外覆盖](https://docs.amd.com/r/2023.1-English/ug906-vivado-design-analysis/Reporting-the-Timing-Exceptions-Coverage)、[TIMING-7 说明](https://docs.amd.com/r/2024.1-English/ug906-vivado-design-analysis/TIMING-7-No-Common-Node-Between-Related-Clocks)

### 2026-11-10 专项采集入口

新增 `-Timing7`，沿用现有只读 SSH 和结果回传。服务端先核对 D10 xclbin、平台 XSA 和两份 D13 DCP 的 SHA-256，再用现有 Vivado 2023.1、两个 CPU、nice +10、每份 DCP 900 秒限额采集。每份 DCP 计划返回双向详细 CDC、min/max 时序及用户忽略路径、全局例外覆盖/忽略/作用域覆盖、生效 XDC，以及 debug reset LUT 输入、扇出终点时钟和相关同步器 `ASYNC_REG`。交互表提供端点计数基准，路径报告每组上限 64，收到后按引脚归并核对覆盖。[Tcl](../scripts/u280_timing7_audit.tcl)、[Vivado 2023.1 路径查询](https://docs.amd.com/r/2023.1-English/ug835-vivado-tcl-commands/report_timing)

`-Timing7 -PrepareOnly` 已实际运行并退出 0。离线核验了脚本哈希、HOST 配置禁用和 Tcl 8.6 模拟调用的 16 个输出，扇出核对覆盖 pin 和 port 两种对象。目标 DCP 在服务器，真实 Vivado 补采为 `NOT_RUN`。采集完成后的复查要确认正向 26 / 反向 9 个端点均有处置依据，再判断是否能关闭 TIMING-7。[准备记录（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-898b76d7a9df)、[Tcl 离线检查（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-8f79ad0940ed)

在项目根目录的本机 PowerShell 运行以下命令，使用自动生成的新 run_id。在 SSH 提示时于终端输入密码。

```powershell
& .\scripts\Invoke-U280Readiness.ps1 -Timing7
```

2026-11-10 20:19 已在本机打开只读采集窗口 `u280-timing7-20261110-v1`。本地 transport 已进入 `RUNNING`。截至本次交接未收到远端输出或 SSH 退出码，真实 Vivado 补采仍待确认。该窗口接收原生 SSH 密码，收到回传后再按上述端点清单审阅。[本地传输状态（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-076a7b47afb0)

2026-11-10 20:50 已经由独立 SSH 只读取证，退出 0。原 v1 连接于实现版运行后断开，原 transport 留在 `RUNNING`，其退出码未保存。服务器保留实现版 16 份专项报告，日志显示 `close_design` 后于 20:33:47 正常退出 Vivado。基线报告目录为空，未见仍匹配该作业的进程。20:54 打开 v2 基线补采窗口，固定原 DCP/XSA/Tcl 哈希，只运行基线并回传原实现版文件。21:01 本地 transport `RUNNING`，未见远端输出或退出码。TIMING-7 仍 `OPEN`。[原实现版日志尾部和文件清单（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-77d966dff73f)、[基线补采传输（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-a5beea4c5bf7)

### 2026-11-10 21:02 两套专项报告已回传

基线 Vivado 501.875 秒、SSH、解包与本地复核均退出 0。复核核对原 DCP/XSA/Tcl 身份和 38 份报告/日志的哈希，含两份 DCP 各 16 项专项输出。实现版的报告和正常退出日志已取回，原 Vivado 进程退出码仍为空。[恢复记录（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-104c56db2384)、[复核（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-d8e304b0c4d5)

两份 DCP 的双向 CDC 明细一致。正向 26 个时序端点由 21 个参与计时的 recovery/removal 端点及 5 个受既有例外忽略的端点组成，反向 9 个端点均忽略。正向最低报告余量为 recovery +0.185 ns、removal +0.415 ns。CDC 报告另有 13 项 `CDC-7` 和 2 项 `CDC-10`。`CDC-7` 中 12 项是 PCIe debug 的异步 CLR，另 1 项是链路状态寄存器的异步 CLR。网表显示 debug reset LUT 由 `sys_rst_n_sbr` 和 `dest_arst` 驱动，31 个扇出终点中有 21 个处于 DMA 用户时钟域。[正向 CDC（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-055be794c607)、[复位扇出（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-126de19d6d3e)

TIMING-7 仍 `OPEN`。端点采集缺口已补齐，后续需要平台维护者确认两域在启动、复位与链路恢复时的时钟关系，或者提供适用于固定 XSA/shell 的目的域复位释放、隔离或已知项接收依据。
