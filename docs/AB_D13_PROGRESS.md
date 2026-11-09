# A/B D13：HOST 权限与实现 DCP 审阅

2026-11-09，Asia/Shanghai。用户要求先处理 HOST 内存与 9 项 methodology Critical Warning，满足条件后上板；随后明确先完成时序审阅、说明现状和最小权限需求，再由用户申请权限。

**最终状态：DCP 采集与静态归因审阅完成，53/53 证据检查 PASS；HOST BLOCKED，TIMING-7 平台跨域项仍 OPEN，实际 200 MHz 待加载后核验，上板 NOT_RUN。** 这里的 PASS 只覆盖采集/对照，不表示九项告警已消除。八项在原始平台中已有，一项来自本次 200 MHz 可调时钟约束。[最终审阅](../results/u280-readiness-review-20261109-v2/result.json)保留每项处置与原始证据；v1 机器摘要仍保留。

## 已确认的结果

- v1（本地记录 `results/u280-readiness-20261109-v1/probe.json`） 实际连接/返回成功，但业务 FAIL。`sudo -v` 退出 1；用户终端报告 `Sorry, user u280user may not run sudo on localhost.`，单独记录在 权限说明（本地记录 `results/u280-host-policy-20261109-v1/result.json`）。HOST enable 未执行，8 卡当次 ready/无 KDS 在途任务、HOST 均为 0；未获得卡预留。不得重试密码来绕过策略。
- v1 的 DCP 选择器只识别 `hw_bb_locked_*`，拒绝了实际文件名。返回的 71512 字节 DCP 清单明确顶层最终路径为 `.../prj.runs/impl_1/level0_wrapper_postroute_physopt.dcp`，273620447 字节。已修正选择器，保留 v1 原件。
- v2 传输记录（本地记录 `results/u280-readiness-20261109-v2/transport.json`） 于 20:13:13 完成。实现 DCP Vivado 718.449 秒、平台基线 435.335 秒，两者及 SSH/采集均退出 0、未超时，两个 optional_errors 文件为空。每次 Vivado 限两个 CPU、nice +10、900 秒，不综合/布局/布线，不写回 DCP，不新增 timing waiver，不加载板卡。实现 DCP SHA-256 为 `4942bb1979f74e60bbbd8d20ce9779ec1cdee675d2a3217453e505ac4cd26c19`；从已核对 XSA 提取的基线 DCP 为 `f5cee615c973ebd572f85ce6d412edbf273115b8f7b061874d286caa3408bcf3`。
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
