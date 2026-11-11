# A/B：同一设备上下文的 PTX 连续启动

日期：2026-11-10，Asia/Shanghai。版本 `ptx-same-device-sequence-v1`。23:57 完成：**SimX、处理器 RTL、NOXRT AFU、真实 U280 各 30/30 连续启动 PASS，限定范围作者验证**。本轮接续固定 15 条 PTX 的 E 接收，验证 A/B 的连续启动、完成可见性及缓冲区生命周期；通用项目 runtime API、故障恢复仍另待完成。

## 验证范围

同一进程只调用一次 `vx_device_open`，创建一个 queue。将原 15 条 copy/vadd/affine 交错安排后执行两遍，第二遍轮换顺序，共 30 次合法启动。三份 vxbin 沿用 E 已复现的固定镜像，源 PTX、前端、设备 wrapper、ABI、硬件配置均不改变。

- 每个分配阶段创建三个 324 字节缓冲区，连续 15 次复用；第 16 次前等待队列完成，释放并重新分配，设备与队列保持打开。地址在日志中按分配阶段记录。
- 每次重新上传 x/y/z，逐字节检查完整数组。输入和有效数组答案来自原冻结语料及 E 的只读答案；额外容量用每次不同的哨兵字节填充，copy 未使用的 y 要求保持不变。这些扩展判据由本轮实施者编写。
- 实际装载/切换模块 29 次，覆盖同一模块再次启动及切换到其他模块；每次核对 runtime 解析的入口 PC、参数、小端 padding、Block/Grid 和捕获顺序。
- 两个分配阶段各选三类 kernel，分别提交 B=33/64：共 12 次应同步返回 `VX_ERR_INVALID_VALUE=3`、无 event。拒绝后读回 x/y/z 确认未变化，再提交合法启动。
- 合法 enqueue 返回后立即覆写宿主参数内存与 launch 描述符，验证固定 API 的提交时复制约定。等待 event、读回、queue finish 后才记录该次成功。
- SimX 与处理器 RTL 用固定 D6 DEBUG3 库观察全序列的有效 LSU lane；NOXRT 使用固定 D5 AFU 模型。模拟周期和 DEBUG 日志不用于性能结论。

## 本地执行与复核

[v3 汇总（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-1128c885d06b)：SimX、处理器 RTL、NOXRT AFU 各 30/30 合法启动和 12/12 预期拒绝通过，每路 138 份捕获（90 数组、18 拒绝后快照、30 参数）。SimX/RTL 各 1,806 次数组读取、1,160 次数组写入逐 lane 通过；每路六次 N=0 均实际分派且无数组请求。

实际 SimX/RTL 执行来自 [v1 原始命令与日志（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-5347aa7bd8eb)，两次宿主编译和运行均退出 0。v1 的最终状态为 FAIL，因为旧 trace 检查器假定 KMU 和核心 CTA ID 相同。连续运行时 KMU 的逻辑序号每次重置，核心 dispatcher 的 slot ID 则继续轮转；例如第二次启动在周期 2867 同时记录 KMU `cta_id=0` 和 core `cta_id=1`。依据固定源码 `hw/rtl/VX_kmu.sv:394` 和 `hw/rtl/core/VX_cta_dispatch.sv:834` 的同一握手，新增检查器按周期、PC 和参数地址一一关联，缺失、重复或不一致均拒绝。

v2 保留该修复后的复核结果，因 AFU 库名选择错误而 FAIL，AFU 未启动。v3 保留 v1 的原始日志/捕获和命令 provenance，重新解析两路 trace，随后新编译并实际执行 NOXRT AFU，退出 0。**v3 的 SimX/RTL 是 v1 原始执行的复核，不是新增 60 次运行。** 原始日志、失败结果和 E 冻结答案均未改写。

从头执行：

```powershell
wsl -d Vortex-AB-Ubuntu-22.04 --cd /mnt/d/Vortex-U280 -- python3 -B scripts/run_ptx_sequence.py --run-id ptx-sequence-NEW
```

仅在检查器修复、宿主/镜像/输入和库身份不变时，可显式 `--recheck-run ptx-sequence-OLD`，新目录保留执行来源，只补执行尚未运行的后端。不得把重新解析记为新的设备执行。

## U280 接续入口

新增 `Invoke-U280BoardSmoke.ps1 -PtxSequenceRun`。准备阶段重新核对三路成功命令、日志哈希、原始捕获、输入包及两份候选 lock；真实运行沿用既有空闲卡、BDF/index、HOST≥256 MiB、固定 D10/D12 哈希、加载 UUID、实际 200 MHz 门禁。只打开一次设备，在同一上下文执行完整序列；正常退出后要求 KDS 空闲。现在在执行前记录编译后宿主 ELF 的 SHA-256。

```powershell
./scripts/Invoke-U280BoardSmoke.ps1 -PrepareOnly -PtxSequenceRun ptx-sequence-20261110-v3 -RunId u280-board-ptx-sequence-prepare-NEW
./scripts/Invoke-U280BoardSmoke.ps1 -PtxSequenceRun ptx-sequence-20261110-v3 -RunId u280-board-ptx-sequence-NEW
python -B scripts/review_ptx_sequence.py --board-run u280-board-ptx-sequence-NEW --output u280-ptx-sequence-review-NEW
```

离线包：[准备记录（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-c3145855c223)。[最终本地核验（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-3c7bc96af42e)退出 0：WSL 完整自测 150 项中 149 通过、1 跳过；98 项打包文件及 Python 3.6 语法通过；Windows 项目和 WSL 固定检出各 3,329 项文件零差异，根 lock/caps 不变。准确板端宿主包在非 DEBUG 的 SimX/RTL 各回放 30/30 次，错误 BDF 两次均在设备打开前拒绝。这是额外 60 次本地回放，XRT BDF 查询使用 stub，不能当板测或新增 LSU 观察。

本轮首次 Windows 定向自测因沙箱临时目录 `WinError 5` 失败，控制台错误记录保留；随后沙箱外 10/10 定向测试通过，[日志与退出码（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-325a20149ae0)。这些运行器/检查器测试不替代 DUT 结果。

真实 [U280 结果（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-be720ff6ca99)与 [SSH 传输（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-8cb4592c92a1)均 PASS、退出 0。板端于 23:57:42—23:57:59 在 `0000:b1:00.1`（XRT index 3）执行，HOST 268435456 字节、UUID `b60ca9fb-1506-3033-c156-e03ff687f492`、DATA_CLK 200 MHz，退出后 KDS 在途、context、client PID 均空闲。宿主编译 0.850 秒、运行命令 5.160 秒均退出 0；该耗时含运行器与门禁等待，不是 kernel 性能测量。执行前宿主 ELF SHA-256 为 `845988321345ae4e62baff6692967d2687b17ca2fdaee79161de1ae44e8686e0`。

[最终四路复核](../results/u280-ptx-sequence-review-20261110-v1/result.json)退出 0：每路 30 次合法启动、12 次预期拒绝、一次设备打开、29 次模块装载、两代缓冲区和 138 份捕获通过。108 份数组/拒绝快照在四路逐字节一致；每路 30 份参数分别按实际设备地址和 ABI 核对。共 120 次主序列实际执行；复核次数不计作新增执行，额外 60 次本地打包回放单列。板卡保留既有 xclbin，无重建或复位操作。

## 接收边界与下一步

这是实施者的同一设备上下文序列验证，复用 E 已冻结的数组答案，**不是 E 对新生命周期行为的独立接收**。B=32、N≤65，仍为三个既有合法 kernel，不代表未见 PTX 语料或完整 P0。两次缓冲区分配不代表两次设备打开，也不构成 reset/recover 验证。

同步拒绝发生在提交前，不涉及设备执行故障；超时、DMA 隔离、安全中止、故障后 context generation/句柄失效均 `NOT_RUN`。TIMING-7 沿用用户先前要求跳过，技术状态仍 `OPEN`。根 lock/caps 保持草案。

下一步交 E 接收新序列；C/D 据此完成项目 API、模块/参数/buffer 校验和有界错误恢复。A/B 后续再扩未见合法语料和不同合法 Block/更大 N；性能与配置对照另建实验，不使用当前 DEBUG 运行时间。
