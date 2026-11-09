# D6：原生谓词访存与 U280 环境接收

日期：2026-11-08，Asia/Shanghai。按用户要求优先推进 A/B。用户确认尚未明确分配板卡；本轮不进行设备枚举查询、加载、复位或板上运行。默认 lock/caps、D4/D5 和前端证据保持原样。

## B：已完成的实际盘点

三轮通过 WLAN 绑定 SSH 登录 `192.0.2.28:22`，身份 `u280user` / `localhost`，每轮 SSH/采集器均退出 0。用户在本机 SSH 提示处输入密码，项目不保存密码。

| 证据 | 已执行范围 | 结果 |
|---|---|---|
| 基础盘点（本地记录 `results/u280-inventory-20261108-231839-155/result.json`） | OS、编译器、资源可见量、软件包、目录与 PCI sysfs | PASS（采集范围） |
| 安装与元数据（本地记录 `results/u280-inventory-20261108-232350-747/result.json`） | 文档指定工具路径、环境脚本哈希、XRT version.json、U280 xpfm | PASS（采集范围） |
| 实际工具与 platform 解析（本地记录 `results/u280-inventory-20261108-232952-683/inventory.json`） | Vivado/Vitis/XRT 版本、platforminfo；各命令输出和退出码在 JSON | 四项均 PASS、退出 0 |

实际工具检查在 SSH 子进程中加载 `/apps/Xilinx2023/Vitis/2023.1/settings64.sh` 与 `/opt/xilinx/xrt/setup.sh`，随后逐条执行：

```bash
vivado -version
v++ --version
platforminfo -p /opt/xilinx/platforms/xilinx_u280_gen3x16_xdma_1_202211_1/xilinx_u280_gen3x16_xdma_1_202211_1.xpfm
/opt/xilinx/xrt/bin/xbutil --version
```

| 项目 | 实测事实 | 接收边界 |
|---|---|---|
| 服务器 | CentOS 7.9 / Linux 3.10.0-1160.108.1.el7 / Python 3.6.8 | 与专用 Ubuntu 22.04 WSL 分开 |
| C/C++ 与 libc | 当前 PATH GCC/G++ 4.8.5，`ldd --version` 和 `os.confstr` 均给 glibc 2.17 | Python 3.6 的 `platform.libc_ver()` 猜测为 2.3.4，原文保留，不采作真实版本；不能直接运行已验证要求 glibc≥2.35 的固定预编译组合 |
| 其他宿主工具 | CMake 3.27.9、Make 4.2、Verilator 4.034；`/opt/rh` 可见 devtoolset 7/8/9 | 没有把远端旧 Verilator 当成已锁定的 5.050；未安装、升级或改系统环境 |
| Vivado / Vitis | Vivado 2023.1，SW build 3865809；v++ 2023.1，SW build 3860322 | 版本可运行，综合/实现许可与兼容性未验证 |
| XRT / 驱动 | XRT、XOCL、XCLMGMT 2.13.479，hash `5e92a513c6950e79638b1a879ddb882da34fc683` | 版本查询不代表传输或设备运行 PASS |
| 已安装 platform | `xilinx_u280_gen3x16_xdma_1_202211_1`，version 202211.1，generated 2022.1.1，part `xcu280-fsvh2892-2L-e` | 此为磁盘上 platform 文件，不代表获配卡当前 shell 匹配 |
| 平台内存 | platforminfo 列出 HBM[0..31]、DDR[0..1]、PLRAM[0..5]、HOST[0]；HOST consumption=explicit | HOST[0] 文件级连接资源已确认；设备上 host-memory 是否启用、host-only BO 和 DMA 通路仍 NOT_RUN |
| 平台时钟 | 列出 300/500/100 MHz，默认 index 0 | 不是 Vortex 实际频率、时序或性能结果 |
| 平台仿真 | platforminfo 的 Hardware Emulation=0 | xpfm 引用了 hw_emu 文件，不能单据该引用宣称 hw_emu 可用 |
| PCI 可见性 | 8 组 Xilinx 管理/用户功能，驱动 xclmgmt/xocl | 只读 sysfs；未打开设备，也未选取任一功能作为获配卡 |
| CPU/内存/磁盘 | 64 逻辑 CPU、约 754 GiB 物理内存；磁盘见各轮时间戳和字节值 | 均为机器可见量，个人配额/时段未知，不据此提交大构建 |

可复跑入口（自动建立新 run_id，旧目录拒绝覆盖）：

```powershell
& 'D:\Vortex-U280\scripts\Collect-U280Inventory.ps1' -ToolChecks
```

默认不带 `-ToolChecks` 时只采基础/文件元数据；带参数时仅增加版本和 platform 文件检查。`-PrepareOnly` 只生成本地 payload，不连接远端。主机密钥必须匹配已有 known_hosts，WLAN 地址每次动态读取，无全局路由修改。

## A：新一轮原生 LSU 验证

采用独立 8w×4t / RV64 / 1 core 的 `block32-v1` 候选；新增 `--native-trace`，runner schema 7。DEBUG=3 只影响新的独立实验构建；不改变默认硬件/ABI/PTX 白名单。

每路实际 15 次启动：copy/vadd/affine 各覆盖全真、N=0、全假、混合谓词与尾线程。保留 D4 原生 kernel/host 源码；新增小语料与 LSU 日志分析器。SimX 观察 `LsuUnit` 发往 lmem switch 的请求；RTL 观察 `VX_lsu_slice` 的 `mem_req_fire`，均在缓存合并前。

验证完整 x/y/z 分配范围内的实际活动 lane 地址与计数，不把缓存行预取覆盖范围解释为线程访问。固定源码的 SimX `BitVector::operator<<` 与地址列表均低 lane 在前，RTL 的 mask 与地址均高 lane 在前，分别按同一显示位置配对；全真对照确保日志不是空白。输出和 audit/哨兵仍另行逐字节比较。额外向全假阶段插入一条合成读请求，以检查解析器能够拒绝错误轨迹；这是验证器故障注入，不是硬件故障注入。

| 执行证据 | 输出比较 | LSU 数组请求 | 命令退出 |
|---|---|---|---|
| SimX v2（本地记录 `results/ab-d6-trace-simx-20261108-v2/summary.json`） | 15/15 PASS | 15/15 PASS，704 个有效数组 lane 访问 | 0 |
| 处理器 RTL v1（本地记录 `results/ab-d6-trace-rtlsim-20261108-v1/summary.json`） | 15/15 PASS | 15/15 PASS，704 个有效数组 lane 访问 | 0 |

每路全假/N=0 的 6 个用例均无 x/y/z 请求；其余 9 个全真/混合/尾线程用例的地址和计数完全匹配。两路 kernel.vxbin SHA-256 相同：`19b5aeddbaf2a0d664295a7b0811b1fba9999aa73c0ee157994766db799f8505`。额外读请求均被验证器拒绝。

SimX 首轮（本地记录 `results/ab-d6-trace-simx-20261108-v1/summary.json`）为 **FAIL（日志解析器）**：构建、demo 和 15 次原生执行命令都退出 0，但解析器误把 SimX mask 当成高 bit 在前，因 masked-lane 检查报错停止。依据固定 `sw/common/bitvector.h` 和实际日志修正后，先复核原始 trace，再执行新 run_id v2。v2 使用同一已隔离的 SimX debug 构建，无完整重建；其父记录/命令日志哈希经过核对，配置、native 程序、runtime 的运行前后哈希全部一致，新语料/输出/日志独立保存。首轮结果、解析器快照和输出未改写。

新机器完整重跑仍用 `scripts/run_native_smoke.py --backend simx` 或 `--backend rtlsim`，追加 `--target-profile block32-v1 --native-trace`，并传入已有固定 source/tooldir/ramulator-deps、全新 run-id 和隔离 build-dir；精确路径与所有 argv 在两路 summary/父 summary。仅重新运行已核对的同配置 debug 产物可使用 `scripts/rerun_native_trace.py --parent PARENT_RUN --run-id NEW_RUN`，不可用于不同 backend、XLEN 或硬件配置。

[228/228 项收尾核验](../results/ab-d6-closeout-20261108-v1/result.json) PASS、退出 0：重放两路原始 trace、复核输入/预期/实际输出与所有构建/运行日志和产物哈希、父构建身份、远端盘点身份/范围、四项工具命令和默认配置未改。此核验仍由 A/B 实施者完成，不是 E 独立接收。

明确未证明：任意非法指针行为、整段程序严格恰执行一次、安全中止/恢复、PTX 生成程序、AFU 或物理 U280、E 独立接收。原生数组谓词证据不能直接提升 P0 前端/runtime 的状态。

## 脚本检查与剩余阻塞

- 修正后的 Linux 全套自测（本地记录 `results/ab-d6-linux-checks-20261108-v2/result.json`）：退出 0，73 项中 72 通过、1 跳过；修正前 v1 保留。
- Windows 重跑（本地记录 `results/ab-d6-local-checks-20261108-v2/result.json`）：退出 0，73 项中 68 通过、5 跳过；这是 mask 修正前的记录。修正后的整套检查采用上述 Linux v2，Windows 另跑了 3 项 trace 解析器测试。Windows 首轮（本地记录 `results/ab-d6-local-checks-20261108-v1/result.json`）因沙箱临时目录权限报错，原始日志保留。均只是运行器/验证器测试。
- B 还需资源方明确获配 BDF/UUID、时段、个人构建 CPU/内存/磁盘配额、工作目录和许可；之后核对该卡 shell 与 HOST[0] 启用情况，才能接收设备路径。
- FPGA 综合/实现、xclbin、时序/资源、板上传输与原生程序仍 NOT_RUN；不将版本/platforminfo PASS 写成 FPGA 或板上 PASS。
- A 后续接收 C/D 可加载 PTX 程序并交 E 独立复核；默认 4w×4t 仍未被候选取代。
