# B 线：共享卡与 FPGA 构建接收单

2026-11-09 D11：xclbin/197 份报告已本地归档并核验；32 HBM bank + HOST 元数据连接、历史 shell UUID 一致。完整报告新增发现 9 项 methodology Critical Warning 和 7 输入/3 输出缺 delay，尚需平台上下文审阅；上板就绪仍 BLOCKED。runtime200 输入和 Ubuntu 公共库编译已完成，服务器 GCC 9.3.1/XRT 头文件已实际确认，但服务器库编译、HOST 启用与板上执行仍 NOT_RUN。见 [D11](AB_D11_PROGRESS.md)、[runtime 入口](../environment/u280-fpga/RUNTIME.md)。网络已在用户刷新 Surfshark 局域网可见性开关后恢复；不需要改防火墙或重建 FPGA。

2026-11-09 D10 最新状态：**完整 link/xclbin 与固定 200 MHz 时钟检查 PASS**，作业于 15:48:08 完成，v++/clock_check 均退出 0。[最终记录](../results/u280-link-20261109-155638-456/returned/build/result.json)、[D10](AB_D10_PROGRESS.md)。此前资源方案已获用户授权并执行完毕，不必重新启动。后续是产物/报告/元数据审阅、HOST 权限与通路、服务器 runtime 兼容性及实际频率绑定，然后原生程序上板。HOST 配置、板卡加载与板上功能仍未执行。

2026-11-09 D9 新事实：09:46 只读采集（本地记录 `results/u280-preflight-20261109-094621-277/probe.json`） PASS，8 卡采集时 ready/无 KDS 在途任务，HOST 内存仍全部为 0。已安装 XSA interface UUID 与 8 卡 sysfs UUID 一致；sudo 查询返回需要密码，配置权限仍未确认。首次 XO 的缺 stub 失败保留，独立 `ip-ooc-v1` 修正后已实际通过五个 IP OOC、U280 elaboration、原 error gate 及 XO 打包（Vivado 0，340.708 秒）；见 [D9](AB_D9_PROGRESS.md)。下一步先确认[完整构建资源方案](../environment/u280-fpga/NEXT_LINK.md)，再执行 link；板上功能接收仍待完成。

2026-11-09 D8 更新：[独立 U280 候选和源输入包](AB_D8_PROGRESS.md)已完成实际预处理与接口检查；新增 [分阶段构建方案](../environment/u280-fpga/README.md)。HOST 的 sudo 配置语法与恢复步骤已有版本对应的官方依据，但本轮远端检查在 SSH 密码认证阶段退出 255，未取得新设备或权限数据。下一次使用 `Invoke-U280Preflight.ps1 -ProbeKind host-platform`，新 run_id、本机输入密码；完整综合/实现仍先确认资源规则。

更新：2026-11-09。[D7](AB_D7_PROGRESS.md) 已完成两 CPU 小型 AFU 组件综合、实际 U280 综合许可证签出、8 张卡的只读 XRT 报告；[184/184 证据核验](../results/ab-d7-closeout-20261109-v1/result.json)通过。用户明确允许自行选择空闲卡，不需要固定分配或书面配额；少量线程的小规模检查可以继续，大型综合/布局布线前再确认资源和作业规则。

## 当前事实与待办

| 项目 | 已完成 | 下一步 |
|---|---|---|
| SSH 与账号 | WLAN 绑定 `192.0.2.28:22`，`u280user` 登录与盘点 PASS | 密码在本机 SSH 提示处输入，不存入项目 |
| 共享设备 | 8/8 卡 ready；本次 KDS 无上下文/未完成任务，所有报告 CU 为 IDLE | 使用前重新检查空闲，记录 BDF/UUID 和当次 XRT index；无固定分卡等待项 |
| 个人工作目录 | 已在 `/home/u280user/vortex-u280-probes/<run_id>` 实际写入输入、日志和综合产物 | 延续隔离目录与新 run_id；大型构建前核实可用资源和作业规则 |
| 综合工具与许可 | Vivado 2023.1、U280 Synthesis 许可实际签出/释放；小型组件综合退出 0 | 完整 Vortex/IP/实现流程的兼容性及许可随下一阶段核实 |
| platform 与 shell | platform 文件列出 HBM[0..31]/HOST[0]；8 张卡均为 `xilinx_u280_gen3x16_xdma_base_1`，logic/interface UUID 已记录 | 核对完整构建所用 platform/XSA 与实际 shell 接口，不能仅凭相近名称宣称兼容 |
| HOST[0] | 实测 8/8 `host_mem_size=0`；尚未启用 | 查明 XRT 2.13 `xbutil configure --host-mem` 的参数与管理权限，准备所选卡的配置、验证和恢复步骤 |
| FPGA 源配置/输入包 | D8 源预处理、D9 XO、D10 link PASS | 独立 8w×4t 合并 HBM 主接口候选；288 项输入与成功产物绑定；核对 runtime 及仿真配置差异 |
| 完整 FPGA 构建/上板 | link/xclbin/200 MHz 检查 PASS；上板 NOT_RUN | xclbin 53,950,442 字节留存远端；归档并审阅报告/元数据，完成 HOST 与 runtime 条件后验证原生板上 demo |

下一步可优先复查 `0000:b1:00.1`：本次为空闲候选，controller 实际/预期均为 4.3.27。其余卡实际 4.3.28、预期 4.3.27，差异已记录，未升级或判为故障。没有预留任何卡。`fuser` 的 8 次原始退出 1/空输出保留，只表示未报告可见持有者，不证明其他账号没有持有者。

## 运行入口与证据边界

在项目根目录运行 `scripts/Invoke-U280Preflight.ps1`，密码在 SSH 提示处输入。该入口读取 sysfs 与 XRT 报告，并以最多两线程、两个 CPU、nice +10、300 秒超时执行固定 `VX_afu_axi_limit` 的 U280 组件综合。它不配置/复位/加载卡，不启动完整 Vortex 综合或布局布线。成功证据为 u280-preflight-20261109-001732-931（本地记录 `results/u280-preflight-20261109-001732-931/probe.json`），两个旧参数失败运行仍完整保留。仅重做基础环境盘点时使用 `scripts/Collect-U280Inventory.ps1 -ToolChecks`。

固定 XRT runtime 用 `XRT_DEVICE_INDEX` 的整数索引选择设备，运行前须从当次枚举确认与所选 BDF 的对应关系；不能假设 sysfs 排序就是 XRT index。`vx_device` 初始化会加载 `XCLBIN_PATH` 并操作 AFU，不能用它进行只读检查。HOST 控制缓冲采用 host-only BO，本地 NOXRT 模型采用进程内存，因此模型通过不证明物理主机内存桥可用。

默认 4w×4t 仿真配置与独立 8w×4t B=32 候选都不是已接收的 U280 FPGA 配置。固定 U280 平台分支使用 32-bank/33-bit HBM 及 HOST[0]；继续保持 FPGA 配置/产物隔离，不改根 lock 获得表面通过。

后续分别报告 HOST/HBM 通路、完整 AFU 构建、布局布线/时序、原生板上 demo、项目 P0 kernel。小型组件的 10 LUT/4 FF 不作为整机资源，Synthesis 许可可用也不提前承诺完整 IP/实现流程已通过。

## 历史记录

账号和网络曾经受阻，现已解除，详见 登录记录（本地记录 `docs/U280_LOGIN_PROGRESS.md`）。D6 曾按“未明确分配卡”列出待办，后由用户共享卡规则替代；[D6 原始事实](AB_D6_PROGRESS.md)及其所有结果保持不变。D5 的 固定平台源码核验（本地记录 `results/ab-d5-u280-source-20261108-v1/summary.json`）保留为来源证据。
