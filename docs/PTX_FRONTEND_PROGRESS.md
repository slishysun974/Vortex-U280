# C/D：P0 前端首版与宿主语义验证

## 2026-11-10 22:22 E 独立接收固定 15 条

**限定范围接收 PASS，`ACCEPTED_WITH_FIXED_SCOPE`。** 非作者 E 代理使用独立上下文，先按 PTX 源和原始 inputs 冻结标准库数学 oracle、完整预期字节及 ABI，再读取实际输出；未调用生产 oracle、packer、trace analyzer 或比较器作为判据。三份镜像在新目录重新生成/编译，与交付 vxbin 完全相同。SimX、处理器 RTL、NOXRT AFU、U280 各执行 15 次并通过独立接收，156 份数组和 60 份参数准确匹配。接收范围仍为下节固定的 6 copy/4 vadd/5 affine、B=32 用例。[E 签发报告](../results/e-ptx-acceptance-20261110-v2/acceptance.md)、[总结果](../results/e-ptx-acceptance-20261110-v2/result.json)、[冻结身份与任务卡](E_PTX15_ACCEPTANCE.md)

两路 DEBUG3 独立逐 lane 核验每路 903 次数组读/580 次写、Block/逻辑线程/PC/地址/次数；三条 N=0 均真正分派并读取 N 参数，数组访问为零。NOXRT 与 U280 接收完整输出、ABI 及可观察门禁，本轮没有其逐 lane trace。U280 使用新 `e-v2` run，b1 上逐条核验 HOST/UUID/200 MHz/KDS，SSH 退出 0；另回收 135 份运行后原件，不能把补采宿主哈希称为执行时测量。

2 个正控制和 23 个负例全部达到预期；负例验证接收器拒绝能力，不宣称 DUT 通用错误 API 已实现。完整 WSL 自测 139 通过/1 跳过/退出 0。独立答案保持冻结；初次认证、检查器解析/身份验证、临时目录/退出码包装及 Windows 换行导致的失败均保留，详见报告。

本次接收不覆盖未见合法语料、全 P0、通用 runtime、同一 context 连续启动/恢复或人类 E 签名；根锁文件仍为 draft。TIMING-7 按用户要求跳过，技术状态仍 OPEN。下一步另立未见语料接收及 runtime 生命周期任务。

## 2026-11-10 21:44 A/B 的 15 条 PTX 板上回归

**U280 15/15 PASS；四路原始字节复核 PASS。** 新入口 `-PtxRegression` 在一次 SSH 中按冻结顺序运行 6 条 copy、4 条 vadd、5 条 affine。全部使用 `0000:b1:00.1`，每条重新检查空闲、HOST 至少 256 MiB、BDF/index、加载 UUID 与 DATA_CLK 200 MHz，完成后 KDS 在途任务和上下文均为 0。15 次 GCC 9 宿主编译、15 次板端执行和 SSH 均退出 0。批次实际执行时间为 21:40:22 至 21:44:28（北京时间）。[原始板测（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-35c58f764bb5)、[传输（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-011fb3699aef)

| PTX 入口 | 冻结用例 | B/G/N 与参数范围 |
|---|---|---|
| copy_u32 | 0010/0058/0070/0082/0094/0106 | B=32，G=1–3，N=0/32/33/63/64/65 |
| vadd_u32 | 0010/0058/0070/0106 | B=32，G=1–3，N=0/32/33/65 |
| affine_u32 | 0034/0176/0210/0250/0322 | B=32，G=1–3，N=0/32/33/63/65，alpha=0/1/0xffffffff |

同一用例的 **39 份完整数组及 15 份参数**在 SimX、处理器 RTL、D5 NOXRT AFU、U280 四路逐字节一致，包含全部首尾哨兵；本地复核退出 0。各 kernel 仍使用先前验证过的同一份 vxbin，冻结输入和预期未改。SimX/RTL 的逐 Block、PC、有效 lane 访存证据来自此前 15 条实际仿真，本轮没有新增处理器 RTL 或 AFU 执行，也没有取得板上 LSU trace。[四路复核（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-36ed337a21bc)、[既有 AFU 执行（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-1713d8c6b1cf)

运行器将每个结果按 `entry-case` 独立保存，第一条选卡后固定 BDF；失败、卡号变化或退出后仍非空闲时停止，余项 `NOT_RUN`。原 `-PtxSuite` 的三条 smoke 仍保留。新复核器明确拒绝参数四路不一致，检查命令/日志哈希、镜像、原始数组和板端门禁。自测实际 134 项：133 通过、1 跳过、退出 0，含顺序/换卡/部分失败与损坏参数/输出故障注入。参数注入保持自身 payload/参数/hash 一致，仍因与仿真原件不符被拒绝。[运行器自测（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-879fa9beca12)、[退出码（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-1a7740dae7bf)

离线 round-trip 核对 15 条、114 项输入文件与 Python 3.6 语法，固定源码 3329 项零差异，根 lock/caps 哈希未变，退出 0。[离线身份检查（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-bbe6f92405d8)。本轮未改配置、ABI、PTX 白名单或 FPGA/runtime，不升级草案接收状态。TIMING-7 保留 OPEN，通用 runtime 与 E 独立接收仍待完成。

```powershell
# 每次自动创建新的 run_id；加 -PrepareOnly 可只做离线准备。
& .\scripts\Invoke-U280BoardSmoke.ps1 -PtxRegression
# 使用实际生成的板测 run_id 和不存在的结果目录。
python -B scripts/review_u280_ptx_results.py --board-run u280-board-ptx-regression-NEW --output results/u280-ptx-review-NEW
```

下一步 A 向 C/D/E 提交这 15 条的配置、wrapper、LSU 与四路输出证据，并补未见合法语料的独立接收；B 跟进固定平台 TIMING-7 的时钟关系/复位释放结论。通用模块校验、buffer 生命周期、重复启动与恢复继续由 C/D 接续。此轮每条重新打开设备，不能充当同一 context 连续启动/恢复的验收。

## 2026-11-10 三条 PTX 板测与 NOXRT 回归

**U280 `-PtxSuite` 3/3 PASS。** 在同一张 `0000:b1:00.1`（XRT index 3）依次执行 copy `0106`、vadd `0106`、affine `0322`。每条 B=32/G=3/N=65，affine 的 alpha 为 `0xffffffff`。每条开卡前分别核对空闲、HOST 256 MiB 和 BDF，加载后确认 UUID `b60ca9fb-1506-3033-c156-e03ff687f492` 和 DATA_CLK 200 MHz，完成后 KDS 在途与上下文均为 0。三次 GCC 9 编译、三次设备执行和一次 SSH 均退出 0。该次结果限三条用例，E 独立接收待做。[实际板测（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-631f4d32c0b3)、[传输（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-b98285a820ae)

固定 D5 NOXRT AFU 模型以同样的 PTX vxbin 运行全部 15 条已经过双仿真 LSU 核验的用例，**15/15 PASS**（6 copy、4 vadd、5 affine），15 次编译、15 次实际运行和入口均退出 0。另对三条板测做了本地原始字节复核，8 份完整数组和 3 份参数在 SimX、处理器 RTL、NOXRT AFU、U280 四路逐字节一致，退出 0。[AFU 证据（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-1713d8c6b1cf)、[四路比对（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-d32e2624a0b3)

```powershell
& .\scripts\Invoke-U280BoardSmoke.ps1 -PtxSuite
```

批次复用一次 SSH 认证，第一条选卡后固定 BDF。后续每条重新执行开卡前和加载后门禁，上一条失败或卡状态异常时保留已完成证据，其余标记 `NOT_RUN`。准备阶段可加 `-PrepareOnly`。定向测试 5/5 及 WSL 运行器自测 125 通过、1 跳过，均退出 0。[准备记录（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-525d5c33ff00)、[定向测试（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-8fd16c8b5c8d)、[运行器自测（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-17d38f63d263)

## 2026-11-10 U280 PTX 输入包与本地回放

**三个上板输入包离线准备 PASS。** 选用已有 SimX/RTL 访存证据的 B=32、G=3、N=65，用例覆盖 8 个 warp、2 个满 Block 和末块单有效线程。准备入口核对两份目标 lock 的原 copy 绑定、命名 vxbin/入口、冻结用例、两路运行日志和实际捕获，沿用 D10 xclbin、D12 runtime 和既有 U280 开卡门禁。[上板运行器](../scripts/Invoke-U280BoardSmoke.ps1)、[参数校验](../scripts/u280_board_smoke.py)

| 入口 | 用例 | 参数字节 | 准备记录 |
|---|---|---:|---|
| `copy_u32` | `0106` | 24 | [copy（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-c0b4a44931b1) |
| `vadd_u32` | `0106` | 32 | [vadd（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-26b73ff50b8e) |
| `affine_u32` | `0322`，alpha=`0xffffffff` | 32 | [affine（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-230e0223a25b) |

解包后用原板端 `gate.cpp` 编译三个新包和原 `0026` 回归包，XRT 的 BDF 查询由本地 stub 提供，kernel 由实际 SimX、处理器 RTL 执行。每路 4/4 PASS。4 次错误 BDF 注入都在设备打开前以预期码 2 拒绝，4 次宿主编译、8 次仿真和总入口均退出 0。回放核对完整缓冲区、参数及捕获标记。真实 XRT、板上执行和 E 接收均为 `NOT_RUN`。[回放证据（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-bb7182fceba6)

例如从项目根目录离线准备 vadd，默认生成新 run_id。板上阶段去掉 `-PrepareOnly` 后由原生 SSH 提示认证，并使用当次空闲卡、HOST 容量、加载 UUID、实际 200 MHz 及 BDF 门禁。每个 run 执行一条用例。

```powershell
& .\scripts\Invoke-U280BoardSmoke.ps1 -PrepareOnly -PtxDeviceRun ptx-arithmetic-20261110-v1 -PtxEntry vadd_u32 -PtxCase 0106
```

## 2026-11-10 A/B 的 PTX vadd 与 affine 设备验证

**SimX 和处理器 RTL 各 9/9 PASS。** 用冻结语料和原前端生成体，复用 copy 的 Vortex2 wrapper、参数布局及运行入口，分别生成命名 `vadd_u32`、`affine_u32` 的 RV64 vxbin。两路用 D6 DEBUG=3 库装载各自同一份镜像。41 条子命令和总入口均退出 0。原 `copy_u32` 的 `0026` 也重新编译并通过 SimX、RTL，镜像 SHA-256 与原三路首测一致。[算术用例汇总（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-161948034953)、[copy 回归（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-22825dc5aaf2)

| 样例 | 冻结用例 | B/G/N 范围 | 每路有效数组读 / 写 |
|---|---|---|---:|
| `vadd_u32` | `0010/0058/0070/0106` | B=32，G=1–3，N=0/32/33/65 | 260 / 130 |
| `affine_u32` | `0034/0176/0210/0250/0322` | B=32，G=1–3，N=0/32/33/63/65，alpha=0/1/0xffffffff | 386 / 193 |

每个有效线程各读一次 x/y、写一次 z。两路按逻辑 Block、指令 PC 和实际 lane 地址比对，两个 N=0 用例的 32 个线程均进入参数读取阶段，数组读写为 0。x/y/z 和各缓冲区首尾哨兵逐字节匹配，32 字节参数与 packer 一致。新增用例的 AFU、U280 和 E 独立接收为 `NOT_RUN`。下一步可用这两份仿真模块作为输入，单独完成上板打包和接收。[vadd 模块（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-f22a784bea30)、[affine 模块（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-eb0ae2f6d8a2)

```powershell
wsl -d Vortex-AB-Ubuntu-22.04 --cd /mnt/d/Vortex-U280 -- python3 -B scripts/run_ptx_arithmetic.py --run-id ptx-arithmetic-NEW
```

## 2026-11-10 A/B 的 PTX copy 访存复查

**SimX 和处理器 RTL 各 6/6 PASS。** 采用冻结 copy 语料的首组输入，复用三路首测的同一份命名 vxbin（SHA-256 `78fdf5306a53d78e81420a85b26d913adc52333b9f5e580441b9c9abd0fb25c0`，入口 `0x180000034`）。两路沿用经 D6 证据哈希校验的 DEBUG=3 运行库，目标为 RV64、1 Core、8 Warp/Core、4 Threads/Warp。源提交检查、12 次宿主编译、12 次实际仿真及入口均退出 0。[汇总、命令和日志索引（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-cbb2d629184d)

| 冻结用例 | N | B | G | 两路各自观察到的数组 LSU 读 / 写 | 尾部情况 |
|---|---:|---:|---:|---:|---|
| `0010` | 0 | 32 | 1 | 0 / 0 | 32 个线程进入参数读取，全假谓词 |
| `0058` | 32 | 32 | 1 | 32 / 32 | 单个满 Block |
| `0070` | 33 | 32 | 2 | 33 / 33 | 末块 1 个有效线程 |
| `0082` | 63 | 32 | 2 | 63 / 63 | 末块 31 个有效线程 |
| `0094` | 64 | 32 | 2 | 64 / 64 | 两个满 Block |
| `0106` | 65 | 32 | 3 | 65 / 65 | 末块 1 个有效线程 |

按逻辑 Block 对照有效 lane 的地址和次数，每路恰有 257 次 u32 读与 257 次 u32 写，两路记录一致。由固定反汇编确定数组 load/store PC（`0x180000140` / `0x180000154`），因此也检查了数组指令是否访问分配范围之外的地址。另检查其它指令是否碰触 x/z 分配及哨兵。每个 Block 在参数读取 PC 都观察到 32 个活跃 lane。完整 x/z 含首尾各 8 个哨兵字均与冻结答案一致，24 字节参数与 packer 一致。计数发生在 LSU 请求侧、cache 合并之前。[N=0 RTL（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-2de06dd3dbfa)、[N=65 SimX（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-852a9309b3d1)、[N=65 RTL（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-21d0db6eccb9)

```powershell
wsl -d Vortex-AB-Ubuntu-22.04 --cd /mnt/d/Vortex-U280 -- python3 -B scripts/run_ptx_copy_trace.py --run-id ptx-copy-trace-NEW
```

新增 6 条在 NOXRT AFU、U280 和 E 独立接收均为 `NOT_RUN`。后续接收可沿用这组输入及 trace 检查，另补 vadd/affine 设备执行。平台时序另见 [TIMING-7 证据复查](AB_D13_PROGRESS.md#2026-11-10-timing-7-证据复查)。

WSL 运行 `python3 -B -m unittest discover -s tests -v`，119 通过、1 跳过、退出 0。新增检查覆盖空 trace 不得通过 N=0，以及数组 PC 的越界地址仍会被计入。原 `0026` 的两路已存捕获以共用校验函数重算，结果和原比对 JSON 一致。[运行器自测日志（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-054d85b45224)、[退出码（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-1701423df5cf)

## 2026-11-10 PTX copy 设备接续

`copy_u32` 的第一条用例在 **SimX、处理器 RTL、U280 均 PASS**，各执行一次并退出 0。选用既有宿主语料 `0026`（N=7、B=4、G=2），输入和参考输出直接取原封存文件。前端生成体 SHA-256 与 2026-11-08 宿主版本逐字节一致。Vortex wrapper 将逻辑坐标和设备 u32 访存传给 `ptx_body`，经固定 VOLT 和上游 `vxbin.py` 生成带 `copy_u32` 命名入口的 RV64 vxbin。三路装载同一份镜像，实际入口为 `0x180000034`。[设备包与布局（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-26a3c0b632c2)、[ELF 反汇编（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-cf8cf056a9b6)

宿主适配使用 Vortex2 的模块、buffer、queue、event 与读回接口。指针来自实际分配的设备地址加受检偏移，按前端生成布局写入 24 字节小端参数（x/z/n 偏移 0/8/16，padding 清零）。三路参数均与前端 packer 一致，完整 x/z 逐字节匹配，z 的 7 个目标字正确，首尾 16 个哨兵字均保留。板上 b1 的 HOST 预留为 256 MiB，XRT 与驱动均读回 200 MHz，加载 UUID 与 D10 构建产物一致。结果范围为此用例的功能输出，设备访存次数 trace、其他 P0 设备用例、通用 V06 API/恢复与独立 E 接收仍待完成。[三路逐字节比对（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-e14d0a00b6c6)、[U280 原始命令与输出（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-a6f0d9f8390a)

首轮 `ptx-copy-20261110-v1` 在设备编译阶段因生成头中的恒等自赋值触发 Clang `-Werror`。通过版本只在该生成头作用域处理自赋值与未使用寄存器诊断，前端语义体、参数 ABI 与参考沿用原件。设备交付采用 `ptx-vx-copy-device-package-v1`，范围为现有 `copy_u32` 样例。[失败原始日志（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-a4b817082572)、[SimX 与 RTL 执行记录（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-84a05a4f827c)

复现时分别使用新 run_id。第二条命令需要第一条的 SimX 和 RTL 均通过。

```powershell
wsl -d Vortex-AB-Ubuntu-22.04 --cd /mnt/d/Vortex-U280 -- python3 -B scripts/run_ptx_copy.py --run-id ptx-copy-NEW
& .\scripts\Invoke-U280BoardSmoke.ps1 -PtxCopyRun ptx-copy-NEW
```

## 2026-11-08 宿主阶段原记录

日期：2026-11-08，Asia/Shanghai。此交付是前端实施者自测，非 E 独立接收；尚未生成 Vortex image、接入项目 runtime 或执行 PTX-SimX/RTL/U280。

最终 [v3 验证](../results/ptx-frontend-host-20261108-v3/summary.json) **PASS，入口退出 0**：Linux Python 测试 69 通过/1 跳过；copy 132、vadd 132、affine 396、额外语义探针 1，共 **661/661 宿主用例通过**。正常编译与执行均退出 0，故障注入按预期退出 1；G++ 11.4.0、`-O2` 与 UBSan 实际命令保存在日志中。[174 项证据收尾](../results/ptx-frontend-closeout-20261108-v1/result.json) 全部通过、退出 0，默认 lock/caps/config 及 block32 lock 哈希保持原值。

## 实现与使用

入口为 `scripts/ptx_frontend.py`，只使用 Python 标准库（Python 3.10+）。解析完整 token 流，保留源码位置，生成 typed IR、参数布局、C++ 语义函数和哈希清单。未知指令、修饰符、directive、类型错误及不满足静态初始化条件的使用均拒绝；不按 entry 名字选择预制 kernel。

```powershell
python -B scripts/ptx_frontend.py ptx/samples/vadd_u32.ptx --output results/ptx-vadd-NEW
```

输出目录必须不存在。默认复制根 `configs/target_lock.json`，也可显式指定 `--target-lock`；要求 RV64、小端。该 lock 只是预期目标身份，不能由其已有原生仿真结果推断生成代码通过设备验证。

输出包括 `source.ptx`、`ir.json`、`kernel_body.hpp`、`source_map.json`、profile/ABI/lock 副本和 `manifest.json`。manifest 使用独立 schema `ptx-vx-frontend-artifacts-v1`，明确 `loadable=false`、`image_file=null`、`backend_execution=NOT_RUN`；不得交给上游 loader 冒充程序 image。

`kernel_body.hpp` 导出 `ptx_body(payload, PtxThread, Memory)`：线程上下文显式携带四个逻辑坐标；Memory 接收完整 u64 地址的 `load32/store32` 调用。所有算术使用无符号定宽类型；谓词指令用实际条件语句包住目的写入与访存。C 仍需实现 Vortex device wrapper、真实访存适配、后端编译、打包与装载验证。

`pack_arguments` 按源码顺序自然对齐、小端序列化，清零 padding，并拒绝参数数量、负数、溢出和布尔值混充整数。它只接受**已经由 runtime 验证的**整数值，不实现 buffer handle、生命周期、分配范围或设备地址解析，不能当作 V06 公共 runtime API。

## 版本与接收范围

机器可读文件在 `configs/ptx_frontend/v1/`。前端采用新的 `ptx-vx-p0-v0.2-draft`；父设计为 `ptx-vx-p0-v0.1-draft`。参数布局沿用文档中的 `ptx-vx-args-v1`，没有改变 u32/u64 大小、偏移算法或字节序。

v0.2 明确了首版保守语法与静态检查范围：header 按固定顺序，单 entry，寄存器声明在指令前；只加载完整标量参数，显式偏移仅接受零；不接收 predicated ld.param/ret；不含嵌套作用域；支持十进制/十六进制/八进制/二进制整数及可选 U、一元正负号，不接收常量表达式。资源上限为源 1 MiB、寄存器 4096、指令 65536。

初始化分析按“寄存器 + 谓词版本 + 极性”跟踪路径，允许同一未改写谓词保护的定义/使用以及互补分支共同初始化。谓词重定义后不能沿用旧路径事实；不做常量谓词推断或通用逻辑求解，因此可能保守拒绝语义合法但无法证明的程序。

u64 参数在本 ABI 中均为 global 设备指针。指针来源可通过 mov/cvta 和 pointer+integer 的 add 保持；整数伪造地址、两个指针相加或条件覆盖后无法证明来源的地址被拒绝。该检查不是内存沙箱；活跃路径的动态地址仍要求有效、自然对齐、在分配范围内且无数据竞争。静态地址常量偏移按 u32 的 4-byte 对齐检查。

根 target lock/caps、block32 候选和 D4/D5 原始证据不改。现有 caps 的旧 profile 名称没有被默认为新前端接收许可。C/D/E 后续接入时需明确确认 profile、ABI、wrapper、launch 限制并按协议更新接收版本；B=32 的宿主测试不提升目标 capability。

语义依据为 [NVIDIA PTX 7.0 归档](https://docs.nvidia.com/cuda/archive/11.0/parallel-thread-execution/index.html)：整数常量按使用处位宽转换；假谓词跳过指令。支持形式仍限于本项目 profile，未接受的 PTX 合法形式明确拒绝。

实现阶段表如下；`implemented` 指 parser/静态检查/C++ lowering，并不表示目标后端已接收。每一组的 SimX、RTL、U280 均为 NOT_RUN。

| 形式 | 实现状态 | 作者测试入口 |
|---|---|---|
| mov.u32/u64、ld.param.u32/u64 | implemented | 三类样例、参数布局/宽度/偏移拒绝测试、probe |
| add.u32/u64、sub.u32、mul.lo.u32、mul.wide.u32 | implemented | affine 的溢出矩阵、probe 的 u32 边界和 u64 高乘积/回绕 |
| cvta.to.global.u64、global 地址来源 | implemented，保守证明 | copy/probe、条件覆盖与伪造地址拒绝测试 |
| setp.lt/ge/eq.u32、selp.u32 | implemented | 尾线程判断、probe 的符号位为 1 的无符号比较与选择 |
| ld/st.global.u32、谓词及反谓词 | implemented | 完整逐线程 trace、N=0 未映射指针、probe 的目的保留与屏蔽访问 |
| ret、声明、特殊寄存器 | implemented | 末尾/唯一入口/类型/声明拒绝；不同 B/G 和 probe 的 nctaid |

通用性测试对 entry 和全部寄存器改名，核对生成的 C++ 完全一致；所有公开指令形式也由样例全集覆盖检查绑定。当前仅是作者自测矩阵，尚无 E 冻结验收集或 NVIDIA 同 PTX 执行对照。

## 验证与证据

完整重跑入口：

```powershell
wsl -d Vortex-AB-Ubuntu-22.04 --cd /mnt/d/Vortex-U280 -- python3 -B scripts/run_ptx_frontend_validation.py --run-id ptx-frontend-host-NEW
```

运行器独占创建 run 目录，执行 Python 自测，使用现有宿主 G++ 编译生成的 C++，启用 UndefinedBehaviorSanitizer，再执行带访问记录的 CPU harness。它不调用 SimX、Verilator、XRT 或远程服务器，不安装工具。

copy/vadd/affine 的宿主语料涵盖 N=0/1/7/31/32/33/63/64/65/257/1024，B=1/4/7/16/31/32，两组输入及 alpha=0/1/最大 u32；保存全部输入、预期、实际 x/y/z、参数字节和逐线程访问 trace。N=0 仍调用一个 block 的语义函数，参数指向未映射地址，任何实际 global 访存都会失败。其他用例检查每线程的访问顺序、地址、值、总数及完整输入/尾部哨兵。

额外 `semantics_probe.ptx` 是实施者的指令组合测试，覆盖宽乘积与 u64 回绕、无符号比较、选择、假谓词目的保留、负地址偏移与高位虚拟地址。这些地址属于宿主审计模型，不能称为设备或 HBM 高地址实测。

每次运行保存实现快照、全部命令/退出码/日志、编译器版本、生成物和输入输出哈希；run 汇总与分项 comparison 共同构成证据。Python reference 和测试均由本轮实施者编写，非冻结独立 oracle。

故障注入使用单独目录中的生成代码副本，移除首个 load 的谓词保护。在 N=0、指针未映射的输入下，预期宿主审计程序退出 1 并报告活跃访存越界。正常生成包、输入和预期不被故障注入修改；该检查仅证明宿主检测器能抓到这一类错误。

### 迭代记录

| 运行 | 结果与范围 |
|---|---|
| [首次 Windows 前端检查（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-0c2d4c19c84f) | FAIL，退出 1；一处作者测试的 `%r` 字符串格式化错误及沙箱临时目录拒绝。此文件为事后事实记录，原始终端输出未另存文件 |
| [Windows 中间版本（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-437f60f549c3) | 脚本/前端检查 PASS，60 通过、5 平台跳过，退出 0；不是最终 Linux 实现版本的跨平台接收 |
| [Linux/宿主 v1（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-4c69f3892863) | 整体 FAIL，退出 1；三类应用 660 用例通过，额外探针 `%r6` 条件初始化后无条件使用被正确拒绝。修复探针的显式初始化，未放宽前端规则或改写该轮结果 |
| [Linux/宿主 v2（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-645b25f0c655) | 整体 FAIL，退出 1；69 项 Python 测试通过、1 平台跳过，661 宿主用例通过；故障注入的临时代码漏分号，编译失败。修复注入脚本后另建 run |
| [Linux/宿主 v3](../results/ptx-frontend-host-20261108-v3/summary.json) | 整体 PASS，退出 0；69 Python 测试通过、1 Windows 专属负例跳过；661 宿主用例通过；提前 load 的故障注入检测 PASS（被测程序预期退出 1）；执行前后实现快照和语料未变 |
| [最终证据收尾](../results/ptx-frontend-closeout-20261108-v1/result.json) | PASS，174/174、退出 0；核对命令/日志、实现快照、生成包、访问 trace、结果汇总和原硬件配置哈希；不重复执行语义测试 |

上述探针与 reference 均为实施者新建自测，未修改 E 的冻结验收或旧 D4/D5 证据。PTX device image、SimX、处理器 RTL、AFU 与 U280 的新增执行状态始终单列为 NOT_RUN。

证据复核入口：`python -B scripts/verify_ptx_frontend_results.py --run-id ptx-frontend-host-20261108-v3 --output results/ptx-frontend-closeout-NEW`。原始 captures 的逐字节比较由主验证运行完成，收尾脚本检查其汇总与相关证据哈希；完整重执行使用上面的 `run_ptx_frontend_validation.py`。

## 下一步

1. C 接入固定 Vortex 后端，生成真正 vxbin 与设备 wrapper；用当前布局读取 payload，并校验模块/profile/lock。
2. 为 buffer handle/range/lifetime 与 launch 建立项目 runtime，保持 native wrapper 与 payload 分离；不得继承宿主模型的内存检查能力。
3. 先实际执行 PTX-SimX 三类 kernel，再按相同产物进入处理器 RTL；针对生成后的设备代码补假谓词无访存 trace。
4. E 以独立答案和未见合法组合接收。U280 另按接收单盘点环境与分配卡；登录成功不提升任何板上结果。
