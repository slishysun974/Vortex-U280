# D 部分收尾与 V03 交付

2026-11-21，**两个交付模块的普通地址验证和宽地址模块的 4 GiB 专项验证均通过三模型及物理 U280。** 项目负责人已限定接收 A/E 新语料的四路验收结果。[合作协议 V03](COLLABORATION_PROTOCOL.md) · [普通地址板测](../results/c-v03-u280-20261120-v1/result.json) · [4 GiB 专项板测](../results/c-v03-u280-high-board-20261121-v1/result.json) · [项目负责人签收](../results/ae-v03-signoff-20261121-v1/record.json)

## C runtime 的技术接收

C 侧固定了两份交付 manifest 的 SHA-256，并在模型启动前冻结 8 组输入、答案和 PTX 源。语料清单的 SHA-256 为 `68b6a6f21e43cc9712c4c71765b5b02930a854f86104f05d5183e96b81687bc4`，共绑定 51 个文件。答案由单独的 Python 程序按 PTX 源语义计算。新测试使用不同指针偏移、按字变化的保护值和局部块掩码。[冻结清单（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-6b8008c510b3) · [答案生成器快照（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-421ce3f11b59)

| 交付或执行项 | 接收结果 |
|---|---|
| 从冻结的 PTX 重建 | 两份模块分别在新构建目录完成 `prepare/build/validate`。每份各有 12 个文件与 D 交付包逐字节一致，包括 IR、源行映射、C++ 语义体、ABI、wrapper 和 vxbin。两次用板用 lock 校验模型包均返回预期的 `E_TARGET_MISMATCH`，命令退出 1。 |
| 逐指令探针 | 3、4、1 线程块各运行一次，对应宽乘积的活跃地址另加 1、3、5 个字。检查 42 列输出、缺席 lane 对应位置和两端保护区。全局写被屏蔽时，该字保留本轮输入的初值。 |
| 谓词与线程编号探针 | 5、17、32、7、9 线程块各运行一次，每例含多个 CTA。覆盖跨物理 warp 的逻辑线程编号、尾部屏蔽、跳过块内指定线程及全部屏蔽条件访存时的 audit 写回。 |
| SimX / 处理器 RTL / NOXRT AFU | 每路一个 C `Context`，6 次模块装载、8 次启动、8 个事件完成，并通过 `close`。每路比较 24 份完整缓冲区和 8 份启动参数，三路合计 72 份数组、24 份参数全部相符。参数期望由 native 分配地址、指针偏移和固定 ABI 单独计算。三路捕获均已从磁盘重新核对。 |

常规接收与离线回读退出 0。C 侧这组结果覆盖普通模型分配和逻辑线程的可见结果。请求级顺序与 4 GiB 实际地址观测见下方 D 的专项证据。A/E 的独立接收与人类签字另行登记。[构建与运行命令](../results/c-v03-receipt-20261120-v1/summary.json) · [SimX 回读（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-bfb68e111316) · [处理器 RTL 回读（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-3e8ebde8e377) · [NOXRT AFU 回读（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-13b9969b3e70)

本轮 WSL Python 自测共 290 项，289 项通过，1 项 Windows 专用检查跳过。该项与三个接收器自测在 Windows 上均通过。其中一项自测逐一修改三个数组和参数块的末字节，检查回读复核能否发现差异。9 项受保护文件的哈希检查通过。[WSL 自测与源码快照](../results/c-runtime-closeout-v03-receipt-20261120-v1/summary.json) · [Windows 补测](../results/c-v03-windows-tests-20261120-v1/result.json)

接收人在固定 WSL 的项目根目录可运行以下命令。第一条在新目录重新生成冻结语料，第二条校验同一清单摘要后从头构建并执行。第三条可单独用于复核这轮捕获。

```sh
tag=$(date -u +%Y%m%dT%H%M%SZ)
python3 -B scripts/freeze_c_v03_cases.py --run-id "c-v03-corpus-$tag"
python3 -B scripts/check_c_v03_receipt.py receive --corpus "results/c-v03-corpus-$tag" --run-id "c-v03-receipt-$tag"
python3 -B scripts/check_c_v03_receipt.py review --corpus "results/c-v03-corpus-$tag" --run-id "c-v03-receipt-$tag"
```

## U280 模块与地址预核验

2026-11-20 以 C 已冻结的 8 个用例复跑了三模型，每路 8/8，入口退出 0。另用 U280 候选的 `target_lock.json` 和 `fpga.json` 在隔离目录重建 `p0_form_witness`、`guarded_wide_offset`。两套板用包分别通过 `prepare/build/validate`，并通过用错目标锁的负控制。两个 `kernel.vxbin` 分别与 D 的对应模型交付逐字节一致，参数布局与逻辑启动模型一致。各包的 manifest 绑定自己的目标锁。[模型运行](../results/c-v03-receipt-20261120-resume-v1/summary.json) · [U280 构建与诊断日志索引](../results/c-v03-u280-prepare-20261120-v1/summary.json) · [普通地址板测的冻结输入和答案（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-c1e98c776136)

在固定 WSL 项目根目录重建时使用新 run_id。

```sh
python3 -B scripts/prepare_c_v03_u280.py --run-id c-v03-u280-prepare-NEW
```

D10 的 xclbin、内存拓扑、连通性和嵌入元数据均与归档哈希相符，D12 两库身份与已用物理绑定一致。归档拓扑列出 32 个 256 MiB 的 HBM bank，`m_axi_mem_0` 连通全部 32 个。高地址用例的跨界区间 `0xffffffc0` 至 `0x1000000c0`（末端不含）覆盖 `HBM[15]` 和 `HBM[16]`。低 32 位相同的 `0x01600000`、`0x101600000` 分别落在 `HBM[0]`、`HBM[16]`。嵌入元数据另有端口 `range=0xFFFFFFFF`，需要当次实卡证据确认完整通路的可达范围。离线核验退出 0，物理保留、传输与启动均为 `NOT_RUN`。[核验命令、分段和身份](../results/u280-v03-address-review-20261120-v1/result.json)

本次模型高地址复核首次选用了早期捕获，因前端源码哈希不同而退出 1。随后改用与当前源码匹配的收尾捕获，语料清单和设备镜像仍分别同哈希。复核重读 15 份捕获和其中 10 份逐 lane 日志，核对两个固定源码检出各 3329 个文件，退出 0。[首次复核记录](../results/d-high-address-review-20261120-resume-v1/summary.json) · [收尾捕获复核](../results/d-high-address-review-20261120-resume-v2/summary.json)

B/C 在当次 BDF/index、D10/D12、HOST、UUID、实际时钟和空闲门禁通过后，先跑普通地址的 8 个用例并保存所有回读、参数与原生地址。高地址单列一轮，先记录查询和保留返回值，确认低 32 位相同的两段可用不同哨兵分别写入和读回，再执行跨界读、写及 audit 探针。首次遇到设备或传输故障时保留原始证据，按现有恢复边界处理。[物理绑定与门禁](SERVER_GUIDE.md) · [恢复边界](AB_RECOVERY_LIMITS.md)

## 普通地址板测入口

**2026-11-20，物理 U280 普通地址 8/8 PASS。** `c-v03-u280-20261120-v1` 使用 `0000:b1:00.1`，当次 XRT index 为 3，HOST 为 268435456 字节，DATA_CLK 回读 200 MHz。板端 CPython 3.6.8 在一个 context 中完成 6 次装载和 8 次启动，24 份完整数组及 8 组参数通过。开关门禁通过，关闭设备后 KDS 在途和 context 均为 0。SSH、5 条板端子命令和本地验收退出 0，47 份回传文件的哈希复核通过。四路共 32 次启动，各用例完整数组逐字节相符，参数按各后端实际设备地址分别核对。[板测结果](../results/c-v03-u280-20261120-v1/result.json) · [SSH（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-79286287144a) · [四路复核](../results/c-v03-u280-closeout-20261120-v1/result.json)

`c_v03_board.py` 绑定板用 lock、两份镜像、C 的冻结输入与答案，以及 D10/D12 身份。一个 context 运行 8 例，每例回读 3 份完整数组和 1 份参数后立即校验。出现首个差异便停止后续提交并保留已捕获的原始数据。板上的 `Context` 使用现有物理开关门禁，远端回传后本地重新比较数组、参数以及门禁原件。[新三模型捕获](../results/c-v03-receipt-20261120-board-entry-v2/summary.json) · [可移植输入包（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-5d21584c1b43)

解开已校验压缩包后，执行 `python3 -B bundle/scripts/c_v03_board.py preflight --bundle bundle` 可做纯离线预检。实际板测需使用当前可用 BDF，在服务器加载既有 XRT 环境后执行 `run --bundle bundle --bdf <BDF> --output <NEW_RUN_DIR>`。Windows WLAN 通道支持一次 SSH 传输、执行和回收。先用 `scripts/c_v03_board_transport.py prepare <NEW_RUN_ID> --kit results/c-v03-board-kit-20261120-v1 --bdf <BDF>`，再以 `Invoke-CV03U280.ps1 -RunId <NEW_RUN_ID> -Server <SERVER_HOST> -Account <SERVER_USER>` 启动。运行标识使用 `c-v03-u280-*`。[WLAN 和服务器入口](SERVER_GUIDE.md)

同一套回读代码在 SimX、处理器 RTL、NOXRT AFU 各 8/8。离线从压缩包重新解出 107 个已清单化的文件，8 个用例通过预检，错用模型绑定及篡改镜像分别在设备访问前拒绝，两个负控制退出 1。随包 13 个 Python 文件通过 3.6 语法检查。项目宿主自测 290 通过、1 跳过，退出 0。[离线预检与拒绝记录](../results/c-v03-board-kit-check-20261120-v1/summary.json) · [冻结文件与自测](../results/c-runtime-closeout-v03-board-entry-20261120-v1/summary.json)

## 4 GiB 专项板测

**2026-11-21，物理 U280 定址验证通过，随后 5/5 启动通过。** 使用固定 D10/D12、`0000:b1:00.1`、XRT index 3、HOST 256 MiB、实际 DATA_CLK 200 MHz。运行时报告 8 GiB 地址窗口，VM 关闭。两个 256 字节缓冲区的实际基址是 `0x01600000` 和 `0x101600000`。先低后高、先高后低分别写入不同图样，两轮各从两个地址读回完整缓冲区，4 份结果均相符。[物理结果](../results/c-v03-u280-high-board-20261121-v1/result.json)

随后在同一 context 执行高到低、低到高、跨界读、跨界写与跨界 audit。跨界缓冲区起点为 `0xffffffc0`，主机在 4 GiB 分界将每次传输拆为 64 字节和 192 字节，再拼接回读。每例启动前先通过完整数组核对，启动后核对完整输出及带实际 64 位地址的参数。任何定址或回读差异都会停止后续提交。板端证据来自实际分配、参数和读写结果，逐 lane 请求地址见模型原始日志。[模型请求级复核](../results/d-high-address-review-20261120-resume-v2/summary.json) · [本轮三模型](../results/c-v03-u280-high-models-20261121-v1/summary.json)

SimX、处理器 RTL、NOXRT AFU 和物理 U280 各 5/5，四路逐用例的 30 份启动前后缓冲区和 5 份参数均同字节。开关门禁通过，关闭后 KDS 在途和 context 均为 0。5 条板端子命令、SSH 和离线复核退出 0，64 份回传文件与原始 SSH 帧逐字节核对。宿主自测 292 通过、1 跳过，退出 0，新增测试验证别名故障会停在启动前，并验证边界传输分段。[四路复核](../results/c-v03-u280-high-closeout-20261121-v1/result.json) · [SSH（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-df05e7137397) · [宿主自测](../results/c-runtime-closeout-v03-high-board-20261121-v1/summary.json)

重建包、运行模型并准备板测时分别使用新标识。从固定 WSL 的项目根目录执行，再沿用上节的 `Invoke-CV03U280.ps1` 启动 SSH。BDF 需通过当次空闲和硬件身份检查。

```sh
python3 -B scripts/c_v03_high_board.py prepare \
  --bundle results/c-v03-board-kit-20261120-v1 --output results/c-v03-u280-high-kit-NEW
python3 -B scripts/c_v03_high_board.py simulate \
  --bundle results/c-v03-u280-high-kit-NEW/bundle --output results/c-v03-u280-high-models-NEW
python3 -B scripts/c_v03_board_transport.py prepare c-v03-u280-high-board-NEW \
  --kit results/c-v03-u280-high-kit-NEW --models results/c-v03-u280-high-models-NEW --bdf 0000:b1:00.1
```

本轮覆盖固定构建和冻结用例中的地址区间。A/E 独立接收、物理恢复仍为 `NOT_RUN`，旧 DMA 隔离依据 `BLOCKED`，`TIMING-7` `OPEN`。

## A/E 独立验收

2026-11-21 先封存 13 组新输入与预期结果，再从冻结的 PTX 重建四份模型和板用模块。两份 PTX 源使用单独的源级解释器推导结果，输入由用例、缓冲区与字序号生成。冻结清单同时绑定完整数组、应出现的访存请求及被谓词屏蔽的候选请求。封存步骤没有启动任何设备。[冻结回执](../results/ae-v03-frozen-20261121-v1/freeze.json) · [冻结清单](../results/ae-v03-frozen-20261121-v1/manifest.json) · [重建记录](../results/ae-v03-build-20261121-v1/summary.json)

8 个普通地址用例覆盖逐指令列、未写哨兵、跨物理 warp 的 6/10/19/31 线程块以及全屏蔽。5 个定址用例使用新的 `0x03200000`、`0x103200000` 同低位地址，以及始于 `0xffffff80` 的跨界缓冲区，覆盖双向传值和跨界读、写、audit。每路先验证普通分配，再进行两轮别名对照，随后执行定址用例。SimX、处理器 RTL、NOXRT AFU、U280 各 13/13，共 52 次启动。逐路核对 39 份启动前数组、39 份启动后数组、13 组参数和 4 份别名读回。实卡为 `b1`、XRT index 3、HOST 256 MiB、实际 200 MHz，前后门禁、SSH、板端执行及本地回传校验均通过。[三模型](../results/ae-v03-models-20261121-v1/summary.json) · [实卡与参数结果](../results/c-v03-u280-ae-20261121-v1/result.json)

**机器验收 PASS。** 验收入口重新读取 137 份板端原件并与 SSH 帧逐字节比较，核对四路各例的完整数组和固定地址参数。SimX 与处理器 RTL DEBUG3 各核对 1,383 次标量访存请求。普通地址按缓冲区范围比较访问类型、地址和计数，高地址另按 CTA 和逻辑 lane 比较请求顺序。两路均观测到相邻 lane 访问 `0xfffffffc` 与 `0x100000000`，覆盖读、写及审计写回。板端证据为实际定址、参数和完整读回。首轮 DEBUG3 因旧 SimX 归档缺少当前绑定所需的原生 demo 回执而停止，补跑同一库的 demo 后用新 run_id 复核通过。宿主自测 292 通过、1 跳过，退出 0。[验收结果](../results/ae-v03-acceptance-20261121-v1/result.json) · [DEBUG3 首轮](../results/ae-v03-trace-20261121-v1/summary.json) · [最终请求证据](../results/ae-v03-trace-20261121-v2/summary.json) · [宿主自测](../results/c-runtime-closeout-ae-v03-20261121-v1/summary.json)

**项目负责人限定接收。** 2026-11-21 用户在聊天中确认“以项目负责人身份限定接收”，依据为其授权并委托执行的四路复现。签收绑定上述两份模块及 13 个冻结用例的结果。A、E 个人签名栏未登记。物理恢复、`TIMING-7` 和性能处于签收范围之外。[签收原话、范围与证据摘要](../results/ae-v03-signoff-20261121-v1/record.json)

复现每一步使用新的运行目录。先冻结源和预期，再通过两套目标锁构建、打包并执行三模型。冻结内容可从原始文件重算哈希。SSH 延用普通地址板测的启动入口，使用经授权且通过当次门禁的 BDF。

```sh
python3 -B scripts/freeze_ae_v03.py --run-id ae-v03-frozen-NEW
python3 -B scripts/build_ae_v03.py --frozen results/ae-v03-frozen-NEW --run-id ae-v03-build-NEW
python3 -B scripts/ae_v03_execute.py prepare --frozen results/ae-v03-frozen-NEW \
  --build results/ae-v03-build-NEW --output results/ae-v03-kit-NEW
python3 -B scripts/ae_v03_execute.py simulate --bundle results/ae-v03-kit-NEW/bundle \
  --build results/ae-v03-build-NEW --output results/ae-v03-models-NEW
python3 -B scripts/trace_ae_v03.py --bundle results/ae-v03-kit-NEW/bundle \
  --build results/ae-v03-build-NEW --run-id ae-v03-trace-NEW
python3 -B scripts/c_v03_board_transport.py prepare c-v03-u280-ae-NEW \
  --kit results/ae-v03-kit-NEW --models results/ae-v03-models-NEW --bdf 0000:b1:00.1
```

## 交付身份与接口

| 项目 | 本次交付 |
|---|---|
| 输入及目标 | PTX 7.0、`sm_70`、64 位地址，目标为小端 RV64、1 core × 8 warps × 4 threads。固定 Vortex commit 为 `7fe19369587c087f902c3e2bc2add612aa910a95`。 |
| 前端与契约 | `ptx-vx-frontend-v1.2`，静态检查修订 `p0-static-v2`，profile 为 `ptx-vx-p0-v0.2-draft`，ABI 为 `ptx-vx-args-v1`。联合冻结待 A/C/D 确认、E 接收。 |
| V03 输入输出 | 输入任意符合 P0 的单入口 PTX。输出含原 PTX、`ir.json`、`source_map.json`、`kernel_body.hpp` 和前端 manifest。每条指令保留源文件、行列和谓词，映射给出生成行号。 |
| V04 入口与依赖 | C 的 `ptx_module.py prepare/build/validate` 使用 V03 输出、候选 lock、硬件配置和固定工具包。模块内附 wrapper、`kernel.elf`、`kernel.vxbin`、反汇编和编译日志，native 符号为 `main`。 |
| 线程与参数 | `tid.x`、`ntid.x`、`ctaid.x`、`nctaid.x` 分别映射到逻辑线程、块宽、块编号、网格宽。新见证程序的 `x,z,bias` 位于 0、8、16 字节，参数块共 24 字节。C 传入设备指针，padding 清零。 |
| 访存与完成 | 活跃的全局 u32 访问要求有效分配、4 字节对齐且无数据竞争。假谓词保持寄存器或内存原值。逐 lane 的请求顺序由宽地址探针检查。host 等待事件并回读完整缓冲区。 |

逐指令探针的源 SHA-256 为 `bdc1bf700c20d6bdce193582bdda29315bb4166d7399407ee5272184df7f925f`，模型 image 为 `4582515cda7d105d236fd74b06116d911fb9478411cf2fa59bc9346a69cda48a`。候选 lock、硬件、全部模块文件及后端库的散列随运行保存。[运行与库身份](../results/d-p0-forms-20261120-v1/summary.json) · [前端 manifest（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-a326e0eb0773) · [构建命令与工具包（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-3bf35b20b537)

## 17 项白名单接收表

以下每行均有合法输入、边界观测和一条实际触发的定位诊断。14 条允许谓词的指令各占三列输出，分别对应无谓词、`@active` 和 `@!active`。每列含四条 lane，lane 0、1 的 active 为真，2、3 为假。第二组输入把四个 u32 边界值轮换两位，使每个值都经过两种谓词取值。两组分别在 SimX、处理器 RTL、NOXRT AFU 回读，各模型比较 **336 个输出字**以及输入、前后哨兵和参数快照。表中列号为源码注释里的零起始编号。参数装载和末尾返回通过整个程序的地址、宽乘积、输出和完成事件观测。[PTX 源](../ptx/probes/p0_form_witness.ptx) · [数学预期与检查器](../scripts/run_d_p0_closeout.py) · [逐条源行、生成行及诊断](../results/d-p0-forms-20261120-v1/summary.json)

| 指令 | 本次见证与边界 | 本次拒绝例 |
|---|---|---|
| `mov.u32` | 列 0–2，复制零、符号位两侧和全一 | 目的为 pred |
| `mov.u64` | 列 3–5，在两个地址之间选择并回读对应字 | 目的为 pred |
| `add.u32` | 列 6–8，含全一加一回绕 | 目的为 pred |
| `sub.u32` | 列 9–11，含零减一回绕 | 目的为 pred |
| `mul.lo.u32` | 列 12–14，乘三取低 32 位 | 目的为 pred |
| `mul.wide.u32` | 列 15–17，乘积至少 4 GiB，减去高位偏置后回读 | 目的为 pred |
| `add.u64` | 列 18–20，设备基址加负立即数；另有实际 4 GiB 跨界请求 | 目的为 pred |
| `cvta.to.global.u64` | 列 21–23，转换后的参数派生地址回读 | 目的为 pred；回归另查来源不确定的基址 |
| `setp.lt.u32` | 列 24–26，按无符号值与 `0x80000000` 比较 | 目的为 b32 |
| `setp.ge.u32` | 列 27–29，覆盖等于阈值 | 目的为 b32 |
| `setp.eq.u32` | 列 30–32，比较全一，假路径保留此前的相反结果 | 目的为 b32 |
| `selp.u32` | 列 33–35，真假选择值及被屏蔽时的原值可区分 | 目的为 pred |
| `ld.global.u32` | 列 36–38，假路径保留寄存器哨兵；另有请求级检查 | 目的为 pred |
| `st.global.u32` | 列 39–41，假路径保留输出哨兵；另有请求级检查 | 地址位移为 2 |
| `ld.param.u32` | 从字节 16 加显式零位移取 `0x40000000`，驱动宽乘积 | 非零参数位移 |
| `ld.param.u64` | 从字节 0、8 取两个设备指针，独立布局比对 | 非零参数位移 |
| `ret` | 无条件结束，四条 lane 完成写回且事件就绪 | 带谓词的返回 |

## 修订与既有模块兼容性

原前端会接受超出范围的地址常量，并可能把条件路径上来源不确定的 64 位值当作整数偏移。新检查把 `[base+imm]` 的位移限制在有符号 32 位且 4 字节对齐，允许的对齐端点为 `-2147483648` 与 `2147483644`。普通 `add.u64` 保留完整 64 位立即数。每条可证明的谓词路径分别跟踪整数偏移和全局指针；只有“已知指针 + 已知整数”可继续用于解引用。前端同时拒绝保留名冲突、数组展开后占用预定义寄存器及单独的 `_`，并为超长源文件提供位置诊断。[修订前失败记录](../results/d-p0-diagnostics-baseline-20261120-v1/result.json) · [定向回归](../tests/test_ptx_frontend_v12.py) · [NVIDIA PTX 7.0 语法及地址操作数](https://docs.nvidia.com/cuda/archive/11.0/parallel-thread-execution/index.html)

源 SHA-256 从 `a0516d76c9ac30a6687e12b4988d72129808986ba6769298c3f974a48f2cb0e5` 更新为 `86f82ece05707eb1eb0791b65023503b828b3ba6adfd9008b9a6bfab54d0fadd`。新前端 manifest 记录 `validation_revision`。C 可用原目标 lock 对已有模块调用 `validate`，该命令会从 PTX 重新生成并比对 IR、语义体和映射。本次对冻结的六个程序分别校验历史模型包和板包，共 **12/12 PASS**。同一宽地址 PTX 重建后 vxbin SHA-256 仍为 `1227ab66936b091f766f81e4b04b3a657467a9c27adb2bdbfdf0f1ddfa0395d2`。使用此前误接收表达式的源码需修正后重新构建；新版本的独立接收由 E 以新 run_id 绑定当前源码身份。[兼容性记录 archived_modules](../results/d-p0-forms-20261120-v1/summary.json) · [宽地址重建记录](../results/d-guarded-wide-closeout-20261120-v1/summary.json)

## 分层证据与接收责任

| 范围 | 本次结果 | 可复核材料 |
|---|---|---|
| 逐指令值、谓词与诊断 | 17/17 指令形式，17/17 拒绝；三模型各 2/2，命令均退出 0 | [全部命令与结果](../results/d-p0-forms-20261120-v1/summary.json) |
| 宽地址与谓词访存 | 三模型各 6/6。SimX 和处理器 RTL 各观察到 20 次有条件读、20 次有条件写和 36 次见证写，并核对每条 lane 的顺序和地址 | [运行](../results/d-guarded-wide-closeout-20261120-v1/summary.json) · [原始日志复核](../results/d-guarded-wide-review-closeout-20261120-v1/result.json) |
| 4 GiB 地址边界 | 三模型各 5/5。SimX 和处理器 RTL 的相邻 lane 分别访问 `0xfffffffc`、`0x100000000`；AFU 证据为整块缓冲区回读 | [运行](../results/d-high-address-closeout-20261120-v1/summary.json) · [跨界日志复核](../results/d-high-address-review-closeout-20261120-v1/summary.json) |
| 固定源码 | 项目检出和 WSL 构建检出各 3329 个文件与 lock 清单相符 | [两份清单复核结果](../results/d-guarded-wide-review-closeout-20261120-v1/result.json) |
| Python 自测与冻结文件 | WSL 共 287 项，286 通过、1 项 Windows 专用检查跳过，退出 0。该项在 Windows 单独运行通过，退出 0。9 项受保护文件与原哈希相符 | [WSL 自测与保护项](../results/c-runtime-closeout-d-p0-20261120-v1/summary.json) · [Windows 补测](../results/d-p0-windows-preflight-20261120-v1/result.json) |
| 物理 U280 | V03 普通地址 8/8，4 GiB 两侧定址回读及 5/5 专项探针通过。11 月 11 日另有独立语料的四路接收，每路 48/48 | [普通地址](../results/c-v03-u280-20261120-v1/result.json) · [4 GiB 专项](../results/c-v03-u280-high-board-20261121-v1/result.json) · [既有独立接收（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-4cf9f1621903) |
| 人类接收 | C 接收 V03，A 核对线程与访存语义，E 按独立答案复现后登记结果。新增探针如需板测，由 B/C 按实际地址窗口安排。性能 `NOT_MEASURED` | [接收模板](HANDOFF_TEMPLATE.md) |

## 从项目根目录复现

在固定的 `Vortex-AB-Ubuntu-22.04` WSL 中，从 `/mnt/d/Vortex-U280` 执行。复现者每次选新的 `tag`。高地址运行使用同一轮重建的模块，两个 review 命令分别从原始日志复核结果。

```sh
tag=$(date -u +%Y%m%dT%H%M%SZ)
python3 -B scripts/run_d_p0_closeout.py --run-id "d-p0-forms-$tag"
python3 -B scripts/run_d_guarded_wide.py --run-id "d-guarded-wide-$tag"
python3 -B scripts/verify_d_guarded_wide.py --run "results/d-guarded-wide-$tag" --run-id "d-guarded-wide-review-$tag"
python3 -B scripts/run_d_high_addresses.py run --module "results/d-guarded-wide-$tag/module" --run-id "d-high-address-$tag"
python3 -B scripts/run_d_high_addresses.py review --run "results/d-high-address-$tag" --run-id "d-high-address-review-$tag"
python3 -B scripts/check_runtime_closeout.py --run-id "c-runtime-closeout-d-p0-$tag"
```
