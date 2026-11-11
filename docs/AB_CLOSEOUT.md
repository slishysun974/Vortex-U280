# A/B 平台收尾与交付入口

版本：`ab-platform-delivery-v2`，2026-11-11，Asia/Shanghai。面向 C/D/E 的可复现平台交付。基础功能证据已经具备；完整 P0、通用 runtime、恢复、性能实验和正式全项验收仍分别列出。历史 lock/caps 保持原始草案，后续事实通过 run_id 和哈希绑定。

## 使用哪套版本

| 项目 | 当前交付身份 | 适用范围 |
|---|---|---|
| 固定源码 | Vortex `7fe19369587c087f902c3e2bc2add612aa910a95` | 根 lock 记录原始源码/工具身份；不以 draft 字段宣称新增能力。 |
| 工具包 | `8c64cf921d3c6c456e80f00d24482d0aa2153a82`；Clang 20.1.8、RISC-V GCC 12.2.0、Verilator 5.050 | 现有专用 WSL，隔离构建。 |
| 仿真目标 | [block32-v1](../configs/candidates/block32-v1/target_lock.json)，RV64 / 1 cluster / 1 core / 8 warps / 4 threads | D5 普通库及 D6 DEBUG3 库分别校验。根 4w×4t smoke 目标不用于 B=32 程序。 |
| FPGA 目标 | [u280-hbm32-v1](../configs/candidates/u280-hbm32-v1/target_lock.json) | 同核心规模；独立平台宏，合并 HBM 接口与 HOST[0]。仿真和 FPGA 的最终配置并非完全相同。 |
| xclbin | [D10 构建原件（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-740be5623f6b)；SHA-256 `bbac2ab73073b24ba857fb34eadf22bf1c11dc745527f064c4eec61b70d2c843` | UUID `b60ca9fb-1506-3033-c156-e03ff687f492`，历史板测实际 DATA_CLK=200 MHz。 |
| U280 runtime | [D12 两库](../results/u280-runtime-20261109-v4/returned/runtime/result.json)，[binding-v2（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-5de8582c1682) | GCC 9.3.1 / glibc 2.17 / XRT 2.13.479；`gcc9-vm-allocation-v1`、200 MHz 元数据。Ubuntu 库不能替代服务器库。 |
| PTX / ABI | `ptx-vx-p0-v0.2-draft` / `ptx-vx-args-v1` | copy/vadd/affine 的已验证整数样例；没有扩大白名单、shared/barrier/一般分支能力。 |

机器交付清单由 `scripts/verify_ab_closeout.py` 产生，绑定配置、镜像、两库和关键证据。[最终交付索引](../results/ab-delivery-20261111-v1/result.json)追加本轮真实板测、四路复核、失败记录及最终文档快照；原先板测前的核验与文档快照保留。该索引不是替代 module loader 的新 lock，也不把未接收的 draft 改成 frozen。

## 功能证据和本轮收尾

| 工作 | 实际结果 | 原件与接收边界 |
|---|---|---|
| 原生 copy/vadd/affine | D5 三路模型各 152/152；U280 152/152，608 份捕获匹配 | [D5](AB_D5_PROGRESS.md)、[板测（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-899bf14e1e4c)。作者 reference。 |
| 固定 15 条 PTX | SimX / 处理器 RTL / NOXRT AFU / U280 各 15/15，非作者 E 限定接收 | [E 报告](E_PTX15_ACCEPTANCE.md)。四路 156 数组、60 参数；无全 P0 声明。 |
| 同一 context 连续启动 | 四路各 30/30、12 次提交前拒绝后继续 | [连续启动](AB_PTX_SEQUENCE_PROGRESS.md)。新生命周期判据为作者验证，E 独立接收待做。 |
| 本轮 PTX 边界 | SimX / 处理器 RTL / NOXRT AFU / U280 各 **67/67 PASS**：copy 21、vadd 21、affine 25 | [三路模型（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-0d986f3575a4)、[真实板测（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-6686d200ee75)、[四路复核](../results/u280-boundary-review-20261111-v1/result.json)，均退出 0。三镜像新构建且同哈希，共 268 次新执行；新增 E 接收仍 NOT_RUN。 |
| 完成/恢复交接 | 已补固定源码依据、可用行为及不可承诺项 | [恢复限制](AB_RECOVERY_LIMITS.md)。提交前拒绝、等待超时、硬件隔离分别解释。 |

新边界集使用既有冻结作者语料的 repeat=0，不生成或修改旧答案。B=32 覆盖 N=0/1/7/31/32/33/63/64/65/257/1024；B=1/4/7/16/31 覆盖 N=0/65；affine 主集 alpha=0xffffffff，另补 alpha=0/1 在 N=65/1024 的控制。它扩展启动几何和输入边界，不算 E 未见合法 PTX 接收。

v6 的 275 条子命令均退出 0。每个后端核对 180 份完整数组及 67 份参数；SimX/RTL 每路 13,866 次数组读、7,884 次数组写逐 lane 通过，每路 18 条 N=0 均实际启动且无数组请求。完整 WSL 运行器自测 163 项中 162 通过、1 跳过、退出 0，见 [独立脚本检查记录（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-8e4be15afe39)。脚本检查不计为 DUT 执行。

[本地收尾核验（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-77c167fa59e5)退出 0：两份固定源码检出各 3,329 项相符，197 份 FPGA 原始报告、镜像、服务器两库和 E 冻结答案身份未变；重新核对本轮 201 次执行及既有连续启动证据。[准确板端输入包回放（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-df091cc6fae4)核对 67 条的全部 515 项输入，5 条代表宿主在 SimX/RTL 共 10 次回放通过，5 次错误 BDF 均在设备打开前拒绝。该回放的 XRT 查询为 stub，仅计本地验证。

真实 U280 于 2026-11-11 **09:11:50—09:30:15（Asia/Shanghai）**执行 67 条并全部通过；固定 `0000:b1:00.1`，每条重新通过空闲门禁，HOST 268435456 字节、UUID 与 D10 一致、实际 200 MHz，退出后 KDS 空闲。67 次宿主编译、67 次设备执行及 SSH 均退出 0，67 份执行前宿主 ELF 哈希已归档。两类持有者查询各 67 次返回 1，含义为普通账号未见持有者，保留原始退出码，不将所有采集命令概括为退出 0。四路复核退出 0，逐字节核对每路 180 份数组、67 份参数，共 720 份数组与 268 份参数；仍为作者验证，不扩大 E 接收范围。[传输记录（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-03f71d2bde34)

SimX 与处理器 RTL 检查全部有效数组 lane、PC、地址和次数，N=0 要求有真实参数读取且无数组请求。RTL 大 Grid 使用同周期 KMU/core 握手、活跃 CTA 槽位和退休记录关联逻辑 Block；SimX 按激活/停用及逻辑 warp rank 关联，并使用解码 UUID 对应 LSU。允许已退休物理 warp 复用于同 CTA 的另一个 rank，拒绝未退休复用、重复 rank、孤立访存或缺失握手；仅生成分析视图，原日志不改。AFU 只检查执行、数组和 ABI，不声称额外 LSU 观察。

最初两次边界运行在执行前失败并保留：[v1（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-927250fafb18) 误将早期 copy wrapper 与后续通用版本要求为同一文件；[v2（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-36a29f6fdeda) 发现早期 manifest 未记录 Makefile。改为从原 E 重建记录核对每个模块对应的 kernel.cpp/Makefile，再在新目录构建；没有改写旧 wrapper、旧答案或失败结果。

[v3（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-2229eef52884) 在 copy N=65/B=1 的 DEBUG3 SimX 上触发宿主 30 秒 event 等待超时，运行退出 2，原始日志保留。把原始日志先写 Linux 临时文件再整体归档后，[v4（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-48afbd57ef50) 同一程序/输入/阈值执行 0.771 秒退出 0；该次最终因检查器不支持 SimX CTA 槽位复用而 FAIL。[v5（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-fc179aa73345) 已通过 N=65 的全部 Block，N=257 执行退出 0，因检查器错误要求同一 CTA 的物理 wid 唯一而 FAIL。固定 `sim/simx/scheduler.cpp` 与 `cta_dispatcher.cpp` 说明合法身份应为逻辑 rank，补对应负例后 v6 从头运行。所有部分执行保留，不计入 v6 的新增通过数；本地仿真超时未用于声称板上故障恢复。

板测连接的 [v1（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-790a7d14dffe) 在密码认证阶段断开，SSH 退出 255，远端脚本和板卡均 NOT_RUN；日志未显示密码错误。[v2 重连（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-5f5a8f6684e6)因临时生成脚本的 Windows 换行转换导致 payload 哈希不符，在联网前被门禁拒绝，退出 1。旧输入包、错误哈希及日志均保留；修正为按原始字节写入，并在写后核对磁盘哈希，[v3（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-4b60a4014484)仅替换 run_id/nonce，515 项输入和嵌入 worker 不变，随后真实板测及四路复核通过。

## 资源、时序与性能

[D10 构建](../results/u280-archive-20261109-v5/returned/build/result.json)退出 0，完整 link 成功。以下最终 routed 资源包括 shell，来自 [原始 routed utilization（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-8178e43278e9)：

| LUT | Registers | BRAM tile | DSP | URAM |
|---:|---:|---:|---:|---:|
| 227338 | 282814 | 302.5 | 52 | 0 |

整体 WNS +0.016 ns / WHS +0.006 ns；kernel clock 00 为 +0.119 / +0.009 ns；布线错误为 0。内部未约束端点为 0，7 输入 / 3 输出缺 delay 与平台基线一致。详细原件、7 项平台保留项和实际时钟处置见 [D13](AB_D13_PROGRESS.md)。这些数值不是对全部平台告警的豁免。

**TIMING-7 继续按已有要求跳过，状态 OPEN。** 双向 CDC/端点、例外和 reset 拓扑已采集；固定 shell 的时钟关系、目标域复位释放或维护者处置依据仍缺。功能通过、相同平台告警和正余量都不能关闭此项。附件见 [既有报告包（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-2a0f4f4a4267)。

性能为 `NOT_MEASURED`：现有宿主命令耗时包含编译、装载、门禁、传输及调试；不能当作 kernel 时间，也不用于原生/PTX 加速比。可选配置研究保持 `NOT_RUN`。后续实验需同卡同配置，分开 H2D/kernel/D2H 与总时间，按既有计划 5 次预热、30 次测量报告中位数与范围。

## 接收方可执行的入口

以下从 `D:\Vortex-U280` 执行；将 `NEW` 换为未使用的 run_id。已存在的运行目录拒绝覆盖。依赖专用 WSL、现有固定源码/库和归档输入，不触发工具安装或 FPGA 重建。

```powershell
# 新目录重建三份 PTX 镜像、运行 67 条三路边界
wsl -d Vortex-AB-Ubuntu-22.04 --cd /mnt/d/Vortex-U280 -- python3 -B scripts/run_ptx_boundaries.py --run-id ptx-boundaries-NEW

# 已有连续启动用例，从头新运行三路
wsl -d Vortex-AB-Ubuntu-22.04 --cd /mnt/d/Vortex-U280 -- python3 -B scripts/run_ptx_sequence.py --run-id ptx-sequence-NEW

# 按已有门禁执行真实板上连续启动；本机输入 SSH 密码
./scripts/Invoke-U280BoardSmoke.ps1 -PtxSequenceRun ptx-sequence-NEW -RunId u280-board-ptx-sequence-NEW
python -B scripts/review_ptx_sequence.py --board-run u280-board-ptx-sequence-NEW --output u280-ptx-sequence-review-NEW

# 67 条新边界一次 SSH 批量板测：准备时先完整复核三路命令/捕获/trace
./scripts/Invoke-U280BoardSmoke.ps1 -PrepareOnly -PtxBoundaryRun ptx-boundaries-NEW -RunId u280-board-ptx-boundaries-prepare-NEW
wsl -d Vortex-AB-Ubuntu-22.04 --cd /mnt/d/Vortex-U280 -- python3 -B scripts/replay_ptx_boundary_bundle.py --prepared-run u280-board-ptx-boundaries-prepare-NEW --run-id ab-boundary-replay-NEW
./scripts/Invoke-U280BoardSmoke.ps1 -PtxBoundaryRun ptx-boundaries-NEW -RunId u280-board-ptx-boundaries-NEW
python -B scripts/review_u280_ptx_results.py --board-run u280-board-ptx-boundaries-NEW --output results/u280-boundary-review-NEW

# 运行器自测、固定源/FPGA归档/边界捕获复核和交付索引；不访问板卡
wsl -d Vortex-AB-Ubuntu-22.04 --cd /mnt/d/Vortex-U280 -- python3 -B scripts/verify_ab_closeout.py --boundary-run ptx-boundaries-NEW --run-id ab-closeout-NEW
```

最后的收尾工具复核固定历史板测，不将其计为新执行。新的板测每次仍需检查当次空闲、BDF/index、HOST 容量、UUID 和实际 200 MHz。新增批量入口每条重查门禁并保持同一卡，出错即停止、剩余用例保留 NOT_RUN；准确输入包的本地回放使用 XRT BDF 查询 stub，不能算真实板测。

## 剩余工作与责任

| 项目 | 状态 | 下一责任/接收动作 |
|---|---|---|
| 连续启动及扩展边界的独立接收 | NOT_RUN | E 另冻生命周期判据和未见合法语料；作者复跑不计 E。 |
| 通用模块/参数/buffer 校验、E_BUSY、context 状态与句柄代际 | NOT_RUN | C/D 依合作协议完成项目 API；A/B 提供本文的实际平台边界。 |
| 有界故障恢复/旧事务隔离 | NOT_RUN | A/B/C 按恢复限制准备隔离环境与测试，E 接收。 |
| TIMING-7 处置 | OPEN，当前跳过 | B 与固定平台维护者取得版本匹配的时钟/复位依据。 |
| 性能、配置和 AI 对照实验 | NOT_RUN / NOT_MEASURED | 功能接收后另建实验；不以调试日志代替测量。 |

A/B 已有平台功能成果可以按限定范围移交。上述未完项仍构成完整项目验收的缺口，不将整份 A/B 执行计划或 G0—G5 宣称全部完成。
