# 当前研究状态

2026-11-11 公开快照整理：当前代码、两套冻结语料、新独立四路接收与模型恢复证据纳入公开发布范围，入口见 [阶段成果](PROJECT_PROGRESS_REPORT_20261111.md)、[发布说明](PUBLICATION.md)。公开副本自测 **237 通过/32 跳过，退出 0**；四路已有 capture 离线重核各 **48/48**，冻结语料与六个生产文件共 **248 项字节一致**。这是发布验证，没有新增设备运行；完整本地自测 268/1 与公开结果分开报告。

新增 [服务器访问与目录导航](SERVER_GUIDE.md)：SSH 使用方法、XRT/Vitis/GCC/Python、D10 FPGA 成品、D12 两库、C/E 板测目录均已标明。真实账号、地址和本机 WLAN 交互登录命令仅保存在本地 `environment/server-access/SERVER_ACCESS_LOCAL.md`；公开仓库使用示例。后续仍需解决物理停止/隔离依据、恢复实验与 TIMING-7，不以发布或历史输出重核扩大接收结论。

2026-11-11 未见合法语料扩大接收完成：**独立 E 在 SimX、处理器 RTL、NOXRT AFU、物理 U280 各接收 48/48，共 192 次新执行 PASS**。独立上下文先冻结新输入与数学答案；覆盖 copy/vadd/affine 与三种合法 PTX 变体，新的 N/B/整数模式、偏移、参数副本，以及每路一个 context/queue、41 次模块装载、两组缓冲区复用。12 份模块新构建，576 份完整数组、192 组参数的 576 份字节快照通过。当前 runtime 为 `sticky-device-fault-v1`，与四路实际捕获身份一致。[E 签发](../results/e-runtime-unseen-acceptance-20261111-v1/result.json)、[范围与复现](E_RUNTIME_UNSEEN_ACCEPTANCE.md)、[交付完整性核验](../results/c-runtime-unseen-delivery-20261111-v1/result.json)。

U280 本轮 `e-u280-unseen-20261111-v1` 在 b1/index 3、HOST 256 MiB、实际 200 MHz、固定 D10/D12 与 UUID 下执行，前后门禁及 305 份原始导出字节经 E 复核，SSH、13 条远程命令与本地接收均退出 0。[板测](../results/e-u280-unseen-20261111-v1/result.json)。最终完整自测 **268 通过、1 跳过、退出 0**，旧 E 答案、根 lock/caps 和 ABI/profile 保护项保持；没有安装工具或更改系统配置。[自测/源码快照](../results/c-runtime-closeout-20261111-v1/summary.json)。接收仅限上述新合法语料，不扩大为完整 P0 或任意指令的访存 trace 证明。

故障恢复新增实证与修复：底层 finish 会清掉已报告的异步错误，旧封装重试可能误放行；现在永久锁存非 timeout 的原生故障，阻止后续 native 调用和资源复用，超时排空还必须确认原 event 成功。**三模型各两次真实等待超时→排空→句柄失效→新任务正确，以及各一次原生 CP DEVICE_LOST 后持续封锁通过**；9 个 worker、10 条命令退出 0，E 另独立复核原始日志与 9 个 canary 的完整数组。新契约为 [api_v2](../configs/c_runtime/api_v2.json)，旧 v1 原件保留。[恢复证据与限制](RUNTIME_RECOVERY_20261111.md)。**物理 U280 故障恢复仍 NOT_RUN，停止/旧 DMA 隔离依据 BLOCKED，物理 recover 继续 E_UNAVAILABLE**。故障模型进程重启不等于硬件恢复；下一步需固定平台的停止/隔离流程和维护窗口，TIMING-7 继续 OPEN。

2026-11-11 C runtime 本地合入与 U280 接续完成：**SimX、处理器 RTL、NOXRT AFU、U280 各 41/41 PASS**，当前版本四路 164 次执行、48 次拒绝；每路 261 份完整数组文件一致，164 份参数已核对。C 的模块、BufferSlice、队列/event 和连续启动入口已接入 A/B 固定工具链与 D10/D12；旧 v1 前端保留，新 v1.2 使用 `python36-integer-v1` 等价宿主补丁，参数 ABI/白名单不变。v3 六份模块新构建、三路 31 条子命令和入口退出 0；WSL 自测 **257 通过/1 跳过**。真实板测在 b1/index 3、HOST 256 MiB、实际 200 MHz 完成，三次打开/关闭门禁通过，SSH 和本地接收退出 0。[合入与复现](C_RUNTIME_MERGE.md)、[本地 v3](../results/c-runtime-merge-20261111-v3/summary.json)、[板测 v3](../results/c-u280-runtime-20261111-v3/result.json)、[交付核验](../results/c-runtime-delivery-20261111-v1/result.json)。

服务器 CPython 3.6.8 使用项目内原版 dataclasses 0.8，实际预检通过，无工具安装/系统改动。首轮集成测试失败、板测 v1 缺依赖和 v2 字符串接口失败均保留，后两次均未访问设备。固定源码、根契约、旧证据与 E 冻结答案未改；此次未推送公开仓库。下一步 E 独立接收新增 C API 组合；硬件故障隔离/有界恢复 NOT_RUN，物理 recover 返回 E_UNAVAILABLE，TIMING-7 OPEN。

2026-11-11 C/A/B 隔离联调完成：固定 C 仓库提交 `7f3575db67888c03d1c2c4dc3743051c735519dd` 的原模块/Runtime，接 A/B D5 三套库，**SimX、处理器 RTL、NOXRT AFU 各 41/41，共 123 次新执行 PASS**；三路完整输入/输出一致，36 次接口拒绝符合预期，v3 全部 15 条子命令及入口退出 0。12 项公共配置/ABI/PTX 身份一致，C 工作树前后未改。C 历史 2520 次归档复核通过；v2 C 自测 143 通过/14 跳过，A/B 自测 162 通过/1 跳过，均退出 0。[集成核对与差异](C_AB_INTEGRATION_20261111.md)、[汇总索引](../results/c-ab-integration-review-20261111-v1/result.json)、[三路新执行（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-ff9baa1e0a75)。

结论为可接入的隔离候选，**尚未正式合入、未执行 C Runtime 的 U280 板测或 E 新接收**。C v1.2 前端需与 A/B 冻结 v1 分版本，板上目标宏/物理 XRT binding 和既有门禁仍待适配；故障隔离/硬复位未验证，TIMING-7 仍 OPEN。v1 归档读取超时与 v2 AFU 绑定环境错误保留；v2 的 82 次 SimX/RTL 执行不计入 v3。下一步按核对文档合入 C 新层并接 D10/D12 物理产物，不整仓覆盖较新的 A/B 代码和证据。

2026-11-11 A/B 本轮收尾：**67 条 PTX 边界在 SimX、处理器 RTL、NOXRT AFU、U280 各 67/67 PASS**，共 268 次新执行，四路复核退出 0。copy/vadd 各 21 条、affine 25 条；覆盖 N=0/1/7/31/32/33/63/64/65/257/1024，B=1/4/7/16/31/32。三份镜像从新目录重建且与原交付同哈希，275 条仿真构建/运行子命令退出 0；每路 180 份数组、67 份参数逐字节一致，SimX/RTL 各 13,866 读/7,884 写逐 lane 通过。两路 trace 各 18 条 N=0 均实际启动且无数组请求。[模型执行（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-0d986f3575a4)、[四路复核](../results/u280-boundary-review-20261111-v1/result.json)、[A/B 统一交付入口](AB_CLOSEOUT.md)

真实 U280 于 09:30:15 完成，67 条固定 b1、HOST 256 MiB、实际 200 MHz；每条编译/执行及 SSH 退出 0，执行前宿主 ELF 哈希和退出后 KDS 空闲均已记录。[板测原件（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-6686d200ee75)。完整 WSL 运行器自测 **162 通过、1 跳过、退出 0**；两份固定源码各 3,329 项、197 份 FPGA 报告及冻结身份核验通过，515 项准确板端输入的代表回放通过。仿真 v1—v5、SSH v1 认证中断、重连 v2 本地换行/哈希门禁失败均保留，v3 重连未改变测试输入。恢复能力及固定源码依据已补[交接说明](AB_RECOVERY_LIMITS.md)。TIMING-7 继续跳过且 OPEN；新序列/边界独立 E 接收、通用 runtime、故障恢复与性能实验仍未完成，根 lock/caps 保持草案。[自测（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-8e4be15afe39)、[本地核验（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-77c167fa59e5)、[最终交付索引](../results/ab-delivery-20261111-v1/result.json)

2026-11-10 23:57 A/B 接续：**同一设备上下文的 PTX 连续启动在 SimX、处理器 RTL、NOXRT AFU、U280 各 30/30 PASS**。每路只打开一次设备、复用一个 queue，29 次模块装载、两代缓冲区，每路 12 次 B=33/64 提交前拒绝后继续合法运行通过。108 份数组/拒绝快照四路逐字节一致，每路 30 份参数通过；SimX/RTL 各 1,806 读/1,160 写逐 lane 通过。v1 的 CTA 编号关联检查失败与 v2 AFU 库名错误保留，v3 复核 v1 原始 SimX/RTL 执行并补跑 AFU，不能计成重复执行。[最终仿真（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-1128c885d06b)、[四路复核](../results/u280-ptx-sequence-review-20261110-v1/result.json)、[范围与复现](AB_PTX_SEQUENCE_PROGRESS.md)

最终 WSL 自测 149 通过、1 跳过，98 项打包文件与两份固定源码检出各 3,329 项核验通过，退出 0。准确板端输入包另在 SimX/RTL 各回放 30/30，两个错误 BDF 均在设备打开前拒绝；其中 XRT 查询使用 stub。真实 U280 在 b1、HOST 256 MiB、实际 200 MHz 完成，编译/执行/SSH 均退出 0，执行前宿主 ELF 哈希已记录，退出后 KDS 空闲。新序列的独立 E 接收、通用 runtime、超时/故障恢复仍待完成；TIMING-7 继续跳过且 `OPEN`，根 lock/caps 和冻结答案不变。[本地核验（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-3c7bc96af42e)、[板测原件（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-be720ff6ca99)

2026-11-10 22:22 **E 已独立接收固定 15 条 PTX 用例，限定范围 PASS。** 新建非作者 AI 代理先从 PTX 和原始输入冻结独立答案，再在新目录重建三份同哈希镜像、运行 SimX/处理器 RTL/NOXRT AFU/U280 各 15 条。共 60 次新执行、156 份完整数组和 60 份参数通过；SimX/RTL 每路 903 读/580 写、N=0 与尾部假谓词无数组请求独立核验通过。2 正控制、23 负例全通过，完整 WSL 自测 139 通过/1 跳过/退出 0。[E 接收结论](../results/e-ptx-acceptance-20261110-v2/acceptance.md)、[完整结果](../results/e-ptx-acceptance-20261110-v2/result.json)、[任务与复现](E_PTX15_ACCEPTANCE.md)

本轮 **TIMING-7 按用户要求跳过，技术状态保留 OPEN**。根 lock/caps 和冻结答案未改；接收仅限这 15 条，未见合法语料、通用 runtime、同一 context 连续启动/恢复、性能研究和人类 E 签名仍未完成。板端宿主二进制身份另有运行后只读补采，135 份原件与原输入/日志绑定；不声称执行时已采该哈希。失败尝试与验收器开发记录均保留并在 E 报告单列。

2026-11-10 21:44 A/B 接续完成：**B=32 的 PTX copy/vadd/affine 在 U280 15/15 PASS**（6/4/5 条，覆盖 N=0、满 Block、多 Warp、多 Block 和尾线程）。同一 b1 卡逐条核验 HOST、BDF、UUID、实际 200 MHz 和退出后空闲；15 次编译、15 次板端运行及 SSH 退出 0。39 份数组和 15 份参数与既有 SimX、处理器 RTL、NOXRT AFU 原件四路逐字节一致，复核退出 0。[板测（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-35c58f764bb5)、[四路复核（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-36ed337a21bc)、[复现与范围](PTX_FRONTEND_PROGRESS.md#2026-11-10-2144-ab-的-15-条-ptx-板上回归)

新增 `-PtxRegression`、可复用四路复核器与失败注入检查。WSL 自测 133 通过、1 跳过、退出 0；114 项打包文件和固定源码 3329 项核对通过，根 lock/caps 未变。本轮未重跑处理器 RTL/AFU。TIMING-7 仍 OPEN，通用项目 runtime、同一 context 连续启动/恢复及 E 独立验收未完成。[自测（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-879fa9beca12)、[源码与输入核对（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-bbe6f92405d8)

2026-11-10 A/B 接续。**B=32 的 PTX copy/vadd/affine 在 U280 3/3 PASS，NOXRT AFU 模型 15/15 PASS。** 三条板测均为 G=3/N=65，在同一张 `b1` 卡上依次复核 HOST、BDF、UUID 和实际 200 MHz，三次 GCC 9 编译、板端执行及一次 SSH 均退出 0。8 份完整数组与 3 份参数在 SimX、处理器 RTL、NOXRT、U280 四路逐字节一致。E 独立接收待做。[U280 结果（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-631f4d32c0b3)、[四路复核（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-d32e2624a0b3)、[AFU 结果（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-1713d8c6b1cf)

TIMING-7 仍 `OPEN`。21:02 已回传实现版与基线报告，基线 Vivado 501.875 秒、SSH、解包和本地复核均退出 0。原实现版有正常退出日志，原进程退出码未保存。双向端点和 CDC 分类与原始平台一致。正向 21 个端点计时、5 个受例外忽略，反向 9 个均受例外忽略。还需固定平台的时钟关系及复位释放安全性或维护者处置依据。[专项复核](AB_D13_PROGRESS.md#2026-11-10-2102-两套专项报告已回传)

已准备给学长核对的 TIMING-7 消息和附件。包内按基线、实现版分列 10 份原始报告，哈希和压缩包回读校验退出 0。待确认固定 shell 的既有处置和复位释放机制。[报告附件（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-2a0f4f4a4267)

2026-11-10 A/B 接续。**B=32 的 copy/vadd/affine 三个 U280 输入包离线准备 PASS**，均为 G=3、N=65。原板端 host 在本地分别用 SimX、处理器 RTL 回放，含原 copy `0026` 回归各 4/4 PASS，XRT BDF 查询使用 stub，4 次错误 BDF 注入按预期拒绝。真实板上运行与 E 接收为 `NOT_RUN`。已打开 TIMING-7 只读采集窗口，尚无远端输出或退出码，告警仍 `OPEN`。[准备入口](PTX_FRONTEND_PROGRESS.md#2026-11-10-u280-ptx-输入包与本地回放)、[回放证据（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-bb7182fceba6)、[采集传输（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-076a7b47afb0)

2026-11-10 A/B 接续。**新增 PTX vadd/affine 在 SimX 和处理器 RTL 各 9/9 PASS**，覆盖 B=32、1–3 Block、尾线程、N=0 及 affine 三种 alpha。每路核对 646 次有效数组读、323 次有效数组写，完整 x/y/z 含哨兵和参数均匹配，41 条子命令退出 0。原 copy 入口重跑两路通过且 vxbin SHA 不变。新增用例的 U280 与 E 接收为 `NOT_RUN`。B 已实现 TIMING-7 专项只读采集，准备和离线流程检查通过，服务器 Vivado 采集为 `NOT_RUN`，告警仍 `OPEN`。[仿真汇总（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-161948034953)、[B 采集入口](AB_D13_PROGRESS.md#2026-11-10-专项采集入口)

2026-11-10 A/B 接续。**PTX `copy_u32` 的 B=32 访存检查在 SimX、处理器 RTL 各 6/6 PASS**，覆盖 N=0/32/33/63/64/65、G=1–3。每路 257 次有效数组读、257 次有效数组写，按 Block、地址和次数一致。N=0 的 32 个线程进入参数读取，数组请求为零。x/z、哨兵及参数字节比对通过，入口和 25 条子命令均退出 0。新增用例的 U280 和 E 独立接收为 `NOT_RUN`。**TIMING-7 仍 OPEN**，缺双向完整端点及生效例外、时钟关系、目的域复位释放或隔离证据，平台接收还需版本匹配的维护者结论。[用例与复现](PTX_FRONTEND_PROGRESS.md#2026-11-10-ab-的-ptx-copy-访存复查)、[执行汇总（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-cbb2d629184d)、[时序复查](AB_D13_PROGRESS.md#2026-11-10-timing-7-证据复查)

2026-11-10 任务口径整理：新增[任务 1 / 任务 2 对照](TASK1_TASK2_PROGRESS_20261110.md)。任务 1 的原生 vadd 在 SimX、RTL、U280 三路运行这一功能标准已达成；配置系统研究、独立接收与 TIMING-7 关闭仍未完成。任务 2 已有 P0 线程/CTA/global 的接口约定及单条 PTX copy 设备实现，完整映射与专项接收仍待补齐；shared/local/barrier 等保持 P0 排除项。本次仅整理已有证据。下一步补 PTX 多 Warp/多 Block、vadd/affine、设备访存观察及独立复现。

2026-11-10 19:07 **PTX P0 单条 `copy_u32` 端到端 PASS**。现有前端生成体接入 Vortex 逻辑线程与设备访存 wrapper，以固定 VOLT 工具链生成 RV64 ELF、反汇编与带命名入口的 vxbin。同一份 vxbin 按 SimX、处理器 RTL、U280 顺序装载并执行 `0026`（N=7、B=4、G=2）。三路退出 0，7 个 u32 正确复制，输入和输出两端各 8 个哨兵字保留，24 字节参数与前端 packer 一致。U280 在 b1 上复查 256 MiB HOST、匹配 xclbin UUID、实际 200 MHz 后启动，退出后 KDS 在途与上下文均为 0。范围限此 copy 用例，完整 P0 设备覆盖、通用项目 runtime 和 E 独立接收待完成。[三路逐字节比对（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-e14d0a00b6c6)、[设备包清单（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-26a3c0b632c2)、[接收范围](PTX_FRONTEND_PROGRESS.md)

2026-11-10 18:53 **U280 原生板上回归 152/152 PASS**。在 `0000:b1:00.1`（XRT index 3）复查 KDS 无在途任务/上下文、普通账号未见 render 持有者、HOST 为 268435456 字节。复用 D10 xclbin 与 D12 runtime，打开后 UUID `b60ca9fb-1506-3033-c156-e03ff687f492` 匹配，XRT `DATA_CLK` 和驱动 `clock_freqs` 读回 200 MHz 后才提交用例。36 次 copy、36 次 vadd、80 次 affine 按冻结顺序完成，含 122 次 B=32。608 份输出逐字节匹配 D5 冻结参考，B=33/64 均按预期返回无效值。宿主编译、原生程序、SSH 和采集退出 0，退出后 KDS 在途任务和上下文均为 0。PTX 设备执行、E 独立接收仍未完成，TIMING-7 静态审阅仍为 OPEN。[逐项比对（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-899bf14e1e4c)、[板卡与运行原始记录（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-ec97327189b8)、[传输记录（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-d2ba573126ba)

2026-11-10 18:44 上板首测 **PASS（单条原生 u32 copy）**。选中 `0000:b1:00.1`（XRT index 3），加载前 KDS 的在途任务/上下文均为 0，普通账号未见 render 节点持有者。HOST 读回 268435456 字节（256 MiB），加载后报告 Enabled Host Memory 为 256 MB。D10 xclbin 与 D12 两库 SHA-256 核对通过，加载后 UUID 为 `b60ca9fb-1506-3033-c156-e03ff687f492`，设备 `DATA_CLK` 读回 200 MHz。单条 `010`（N=1、B=32、G=1）退出 0，四份输出逐字节匹配 D5 冻结参考，B=33/64 均返回预期的无效值错误。SSH/采集均退出 0，结束后上下文及在途任务归零。完整 152 次原生板测和 PTX 设备执行仍 NOT_RUN，TIMING-7 沿用 D13 的 OPEN 记录。[本轮原始结果（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-9fad70f8f7a6)、[传输记录（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-9a4bb2520b37)

2026-11-10 板卡协调：学长报告已配置 `b1`、`b2`、`b4`、`3d`、`3e`、`40`、`41` 的 HOST 内存。首查 `0000:b1:00.1`，备选 `b4`、`3d`、`40`、`41`。避开 `b2`、`b5`，优先选学长常用的 `3e` 以外的卡。256 MiB 容量及当前占用待服务器读回。学长建议沿用原始 DCP 的既有项，D13 已证实 TIMING-7 属于该范围，静态审阅仍为 OPEN。实际时钟、上板执行和 PTX 设备执行均待验证。[HOST 只读复核](../environment/u280-fpga/HOST_SETUP.md)、[D13 时序对照](AB_D13_PROGRESS.md)

2026-11-09 GitHub 公开发布 **PASS**。已将截至 D13 的项目代码、配置、进度和 55 份选定验证记录同步到 [Vortex-U280](https://github.com/slishysun974/Vortex-U280)。已匿名读回 main 提交和 ZIP。公开快照 Windows 运行器检查 95 通过、23 跳过、退出 0。[发布记录](../results/github-public-20261109-v1/result.json)。HOST 与 TIMING-7 仍阻塞，板上功能和 PTX 设备执行仍 NOT_RUN。

2026-11-09 文档整理：新增[项目阶段进展报告](PROJECT_PROGRESS_REPORT_20261109.md)，按开发基础、原生仿真、PTX 前端、U280 构建和当前阻塞整理截至 D13 的事实。本次仅整理文档，未新增实验或硬件验证；HOST 与 TIMING-7 仍阻塞，上板功能和 PTX 设备执行仍 NOT_RUN。下一步仍按 D13 处理 HOST/跨域问题，再受控加载并验证实际时钟与原生程序。

2026-11-09 D13 最终：**实现/平台 DCP 采集及静态审阅完成，53/53 证据检查 PASS；上板仍 BLOCKED/NOT_RUN。** 9 项关键告警中 8 项来自原始平台，1 项来自可调 kernel 时钟的 300→200 MHz 约束；7 项平台保留项已核实来源/当前影响范围，**TIMING-7 的 Partial False Path (unsafe) 仍 OPEN**，实际 200 MHz 待受控加载后读回。缺 delay 的 10 个端口与基线一致，内部未约束端点均为 0。HOST 因账号无 sudo 权限而阻塞，配置未执行；用户要求先解释结果再申请权限。[D13](AB_D13_PROGRESS.md)、[审阅结果](../results/u280-readiness-review-20261109-v2/result.json)、[管理员最小操作](../environment/u280-fpga/HOST_SETUP.md)。Linux 自测 117 通过/1 跳过，固定源码 3329 项零差异；原生 152 次输入仅离线准备。

2026-11-09 D12：**服务器 200 MHz runtime 编译/依赖解析 PASS；上板就绪 BLOCKED，板上功能 NOT_RUN。** [v4（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-6fd74a22d0c9) SSH/采集退出 0，GCC 9.3.1 / glibc 2.17 下公共库 10.833 秒、真实 XRT backend 1.420 秒，两库 ldd 均通过并已返回本地。独立 `gcc9-vm-allocation-v1` 修复分配失败后读未初始化变量及生成 Makefile 的重复配置展开，新增 binding-v2；固定源码、FPGA 配置、根 lock/caps 和旧结果保留。8 张卡当次 ready/无 KDS 在途任务，HOST 内存仍为 0、sudo 权限未确认。新报告解析纠正 D11 机器摘要的空表/零计数缺陷：methodology 100 项中的 **9 项 Critical Warning 仍全部 OPEN**；普通 DRC 343 项没有 Error/Critical Warning。最终 Python 自测 **113 通过/1 跳过**，退出 0。详见 [D12 证据与范围](AB_D12_PROGRESS.md)、[运行入口](../environment/u280-fpga/RUNTIME.md)。

2026-11-09 D11：**xclbin 与全部 197 份报告已归档，200 MHz runtime 输入准备 PASS；上板就绪仍 BLOCKED。** [v5（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-b0264f99ea10) SSH/解包退出 0，53,950,442 字节 xclbin 本地哈希与 D10 一致；197 份报告逐文件核验。最终整体 WNS +0.016 ns / WHS +0.006 ns、routing errors=0；完整 methodology 报告有 **9 项 Critical Warning**，含 5 ns 约束与 3.333 ns 时钟模块默认参数不一致，尚未关闭。已准备 [runtime200 输入包（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-17e0b6518b5b)，唯一配置差异为宿主频率常量 400→200，Ubuntu 公共库编译退出 0；服务器现有 GCC 9.3.1/XRT 头文件已确认，真实服务器 runtime/板上功能 NOT_RUN。最终脚本自测 **103 通过/1 跳过**，固定源码保留。Surfshark 局域网残留规则经用户刷新开关后 SSH 恢复，失败记录保留。详见 [D11 发现、范围与下一步](AB_D11_PROGRESS.md)。

2026-11-09 15:56:47 D10 完成复核：**完整 FPGA 构建 PASS，200 MHz 固定时钟检查 PASS**。作业 `u280-link-20261109-103830-671` 于 **15:48:08** 完成，约 5 小时 9 分；v++ 退出 0、未超时，clock_check 退出 0。检查报告 kernel clock 5.0 ns、setup WNS **+0.119 ns**、hold WHS **+0.009 ns**、289539 endpoints。服务器已生成 `out/vortex_afu.xclbin`，53,950,442 字节，SHA-256 `bbac2ab73073b24ba857fb34eadf22bf1c11dc745527f064c4eec61b70d2c843`。[最终构建记录](../results/u280-link-20261109-155638-456/returned/build/result.json)、[时钟输出](../results/u280-link-20261109-155638-456/returned/build/clock_check.stdout)、[D10](AB_D10_PROGRESS.md)。产物留存远端，尚未下载；完整利用率/元数据审阅、HOST 配置、原生上板与 PTX 设备执行仍待完成。

2026-11-09 15:27:25 D10 复查：**布线已完成，正在生成 bitstream，完整构建未完成**。[新只读采集（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-56d015287cbc)为 RUNNING，worker/v++ 存活约 4 小时 49 分；15:02:52 完成第 5/6 项 FPGA routing（耗时 43 分 56 秒），同秒开始 bitstream generation；可选布线后物理优化随后显示完成。最终 xclbin、v++ 退出码及固定 200 MHz 检查结果尚未取得。SSH/采集退出 0，原作业未重启，详见 [D10](AB_D10_PROGRESS.md)。

2026-11-09 15:01:35 D10 复查：**布线后时序分析中，完整构建未完成**。[新只读采集（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-8e0513690271)为 RUNNING，worker/v++ 存活约 4 小时 23 分；日志已从重布迭代推进至 15:00:18 的 `Phase 12 Post Router Timing`。尚未取得整个 routing 完成、最终 xclbin 或固定 200 MHz 检查 PASS。SSH/采集退出 0，原作业未重启，详见 [D10](AB_D10_PROGRESS.md)。

2026-11-09 14:31:52 D10 复查：**布局已完成，正在布线，完整构建未完成**。[新只读采集（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-deb3f34fbfb8)为 RUNNING，worker/v++ 存活约 3 小时 53 分；14:18:55 placement 完成并启动 routing，14:31:42 进入 `Rip-up And Reroute / Global Iteration 0`。布线完成、最终 xclbin 和固定时钟检查结果尚未取得。SSH/采集退出 0，原作业未重启，详见 [D10](AB_D10_PROGRESS.md)。

2026-11-09 14:14:55 D10 复查：**布局收尾清理中，完整构建未完成**。[新只读采集（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-4516a933ef40)为 RUNNING，worker/v++ 存活约 3 小时 36 分；日志已通过 Detail Placement 和 Post Placement Optimization，最新 14:10:45 为 `Phase 4.4 Final Placement Cleanup`。尚未取得布局完成、布线开始或最终 xclbin/固定时钟检查结果。SSH/采集退出 0，原作业未重启，详见 [D10](AB_D10_PROGRESS.md)。

2026-11-09 13:47:27 D10 复查：**正在全局布局，完整构建未完成**。[新只读采集（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-07ec2e373d5c)为 RUNNING，worker/v++ 存活约 3 小时 9 分；日志由布局初始化推进到 13:28:20 的 Global Placement Core，13:47:15 为 `UpdateTiming Before Physical Synthesis`。布线、最终 xclbin 和固定时钟检查尚未取得完成结果。SSH/采集退出 0，原作业未重启，详见 [D10](AB_D10_PROGRESS.md)。

2026-11-09 13:14:26 D10 复查：**正在布局（placement），完整构建未完成**。[新只读采集（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-b6b30250fccb)为 RUNNING，worker/v++ 存活约 2 小时 35 分；12:58:15 完成综合内核与平台链接，13:13:02 完成逻辑优化并启动布局，13:14:04 进入 Placer Initialization。布线、最终产物和固定时钟检查尚未取得完成结果；SSH/采集退出 0，原作业未重启。详见 [D10](AB_D10_PROGRESS.md)。

2026-11-09 12:37:02 D10 复查：**综合已完成，正在实现，完整构建仍未结束**。[新只读采集（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-0865c79bef86)为 RUNNING，worker/v++ 存活约 1 小时 58 分；12:34:27 模块级综合 156/156 完成，随后顶层综合于 12:36:11 完成，同秒进入 `impl`。尚未取得实现完成、固定时钟检查或最终 xclbin PASS。SSH/采集退出 0，原作业未重启。详见 [D10](AB_D10_PROGRESS.md)。

2026-11-09 11:27 D10 复查：**仍在综合，未完成**。[新只读采集（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-c4a368bd0c31)显示原作业 RUNNING，worker/v++ 存活约 48 分半；日志 11:26:49 为模块级综合 **49/156 完成、2 个运行**，较 10:50 的 9/156 持续推进。尚未进入布局布线或取得最终 xclbin。查询未重启作业，详见 [D10](AB_D10_PROGRESS.md)。

2026-11-09 10:50:53 D10 复查：**仍在综合，未完成**。[只读状态采集（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-43a1a33f1bc1) SSH/采集均退出 0，作业 `u280-link-20261109-103830-671` 的 worker 与 v++ 仍存活，运行约 12 分钟。最新日志 10:50:29 显示 block-level synthesis **9/156 完成、2 个运行**；尚未进入布局布线，未取得最终 xclbin 或完整构建 PASS。任务计数不代表整体进度百分比。详见 [D10](AB_D10_PROGRESS.md)。

2026-11-09 D10：**完整 FPGA link 已启动，启动快照 RUNNING**。用户已授权 [link 方案](../environment/u280-fpga/NEXT_LINK.md)；作业 `u280-link-20261109-103830-671` 于 10:38:41 启动，实际观测到 `v++ --link` 进程，10:38:44 SSH 退出 0。当次可用 RAM 约 329.7 GiB、磁盘 720.9 GiB，身份/资源检查通过，CPU affinity `[0,1]`、nice +10、6 小时 v++ 超时，无 RAM 硬限。[启动证据（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-6225f2ba7c23)、[D10](AB_D10_PROGRESS.md)。Linux 93 项 Python 自测通过、1 跳过，退出 0。综合/布局布线最终结果与 xclbin 尚未取得；HOST 配置、板上功能仍 NOT_RUN。后续使用只读 Status 入口采集新状态，不重复启动该目录。

2026-11-09 D9：**真实 U280 IP OOC、RTL elaboration、模块接口检查与 XO 打包 PASS**。[成功运行](../results/u280-preflight-20261109-100406-629/returned/build/result.json) Vivado 退出 0、340.708 秒；五个 IP 生成 DCP/stub，检查范围内 13 类/22 个模块实例通过，XO 为 312,868 字节。首次缺 stub 失败原件保留，独立 `ip-ooc-v1` 补丁只改新构建目录 Tcl。HOST/platform 复查 PASS，XSA 与 8 卡 shell UUID 匹配；HOST 内存仍为 0，sudo 权限未确认。[174/174 最终核验](../results/ab-d9-closeout-20261109-v1/result.json)通过，Linux 87 测试通过/1 跳过，固定源码 3329 文件零差异。详见 [D9](AB_D9_PROGRESS.md)。完整综合/实现、xclbin、HOST 配置与板上功能仍 NOT_RUN；[完整构建准备单](../environment/u280-fpga/NEXT_LINK.md)待确认资源规则。

2026-11-09 D8：**独立 U280 FPGA 候选与实际源预处理 PASS**。[D8 记录](AB_D8_PROGRESS.md)：原始分支生成 32 个 HBM AXI 主接口而仅端口 0 有显式连接，独立 `u280-hbm32-v1` 合并接口候选与 HBM/HOST 连接匹配；已生成可迁移 RTL 输入包。[635/635 证据核验](../results/ab-d8-closeout-20261109-v1/result.json)退出 0，Python 78 通过/1 跳过。根 lock/caps、D5 配置与固定源码未改。本轮远端 SSH 在密码认证阶段退出 255，HOST/platform 新采集 NOT_RUN；完整综合/上板仍 NOT_RUN。

2026-11-09 D7：**B 的两 CPU 小型 AFU 组件综合与实际 U280 综合许可 PASS，8 张卡的 XRT 查询 PASS**；采集时均 ready/空闲，HOST[0] 的 `host_mem_size` 均为 0。[184/184 收尾核验](../results/ab-d7-closeout-20261109-v1/result.json)退出 0，详见 [D7 记录](AB_D7_PROGRESS.md)。用户允许自行选择空闲卡和少量线程构建，无需固定分卡或书面额度；大型综合/布局布线前再确认资源与规则。当前待办是 HOST 通路、完整 FPGA 配置/构建与板上功能。

2026-11-08 D6 优先推进 A/B：**A 原生 LSU trace 在 SimX 与处理器 RTL 各 15/15 PASS**，每路 704 个有效数组 lane 访问准确匹配，全假/N=0 无数组请求；**B 实际服务器盘点、四项工具/platform 命令 PASS**。Vivado/v++ 2023.1、XRT/驱动 2.13.479；platform 文件列出 HBM[0..31]/HOST[0]。[228/228 项收尾](../results/ab-d6-closeout-20261108-v1/result.json)退出 0，SimX 首轮解析器错误和 Windows 沙箱失败记录保留。D6 当时的分卡等待条件已被上述共享卡授权替代；详见 [D6 进展与范围](AB_D6_PROGRESS.md)。

2026-11-08 D5 仿真回归：独立 8w×4t 候选在 SimX、处理器 RTL 和 NOXRT AFU 模型各 152/152 次原生启动 PASS，含每路 122 次 B=32。[84 项收尾核验](../results/ab-d5-closeout-20261108-v1/result.json)通过。4w×4t 基线及 D4 证据保留，E 独立接收待完成。

2026-11-08 P0 前端首版和宿主语义验证：[最终 v3](../results/ptx-frontend-host-20261108-v3/summary.json) 退出 0，69 项 Python 测试通过、1 项跳过，661/661 宿主用例通过，假谓词提前 load 故障被检出。[174 项收尾核验](../results/ptx-frontend-closeout-20261108-v1/result.json)通过。该轮只执行生成 C++ 的 CPU 审计，后续单条 PTX copy 的设备结果见页首。

22:19 接续：用户在终端改用另一个密码后，U280 `u280user` 登录 PASS；实际执行 `id -un && hostname` 返回 `u280user` / `localhost`，SSH 退出 0。WLAN 绑定网络与账号登录阻塞已解除，平台盘点和板卡接收仍未执行；详见 [登录记录与入口（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-998b875bd224)。22:01 认证失败及默认路径超时记录保留。

22:32 用户已完成 U280 `u280user` 密码修改，远端 `passwd` 退出 0；随后独立密码登录也 PASS，身份命令退出 0。密码未保存，首次退出 255 的 UNCONFIRMED 记录保留。见 [改密及复核证据（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-998b875bd224)。

| 项目 | 状态 | 说明 |
|---|---|---|
| 研究计划、五人分工、接口与 PTX 规范 | 已整理 | 设计文档，尚待实施接收 |
| 独立项目目录与文档入口 | 已整理 | 当前根目录为 Vortex-U280；[交接](PROJECT_HANDOFF.md)、[迁移说明](PROJECT_MIGRATION.md) |
| 老师提供的服务器 / U280 入门资料 | 已接收并核对参考链接 | 资料中的服务器入口已登录验证。后续工具盘点与板测分别见下表。[原件与使用说明（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-fdd6f83475df) |
| Vortex 源码身份 / 候选配置解析 | PASS（仅此范围） | v3.0 完整 SHA、已取两个子模块、3329 文件 SHA-256；[v2 证据](../results/ab-d1-source-20261107-v2/result.json) |
| 独立 Linux 与固定工具包 | PASS（准备范围） | Ubuntu 22.04 WSL、glibc 2.35 / G++ 11.4 / CMake 3.22.1；D3 新增同提交的 Verilator 5.050，18 个分卷/单包已核验并独立提取；[D3 证据](AB_D3_PROGRESS.md) |
| Vortex / 配套工具链组合冻结 | draft-v3，未冻结 | 新增 Verilator 5.050 身份及实际 RTL/AFU 观察，硬件/ABI/白名单未变；[lock](../configs/target_lock.json) / [caps](../configs/target_caps.json) 保持 `frozen=false`，P0 能力与独立接收未完成 |
| 原生 SimX 最小 demo | **PASS（仅上游整数 demo）** | RV64 / 1 cluster / 1 core / 4 warps / 4 threads，16 个整数；[D3 新目录复跑](../results/ab-d3-simx-20261108-v1/summary.json) 退出 0 且 `PASSED!`；同一 agent 复跑，不计作独立接收 |
| 处理器 RTL | **PASS（原生整数自测范围）** | 同 RV64 / 1c / 4w / 4t；[D4 demo 与 140 次 u32 回归（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-3c358dba008d)，退出 0；D3 首轮缺 ccache 构建失败保留 |
| XRT AFU RTL 模型 | **PASS（本地模型原生整数自测）** | [D4 NOXRT/XRTSIM 运行（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-4f796978ecd0)，demo 与 140 次 u32 回归退出 0；未测试真实 XRT、HOST[0]、PCIe/HBM、shell 或板卡 |
| 仿真运行器与准备脚本 | PASS（脚本范围） | `python -B -m unittest discover -s tests -v`。11 月 11 日 WSL 162 通过、1 跳过、退出 0；新增槽位/rank 关联、原始日志缓存及边界板测批次负例。[原始记录（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-8e4be15afe39) |
| D4 原生 u32 边界回归 | **PASS（每路 140/140）** | copy/vadd/affine，70 个参数用例各两组输入；三路 kernel/语料/捕获一致，[总核验](../results/ab-d4-closeout-20261108-v1/result.json)；同作者 reference，不计作 E 独立接收 |
| D5 B=32 原生候选 | **PASS（每路 152/152）** | 独立 8w×4t candidate-v1，每路 122 次 B=32，B=33/64 拒绝；三路输出一致，[D5 记录](AB_D5_PROGRESS.md)；根 lock/caps 未变，候选待 C/D/E 接收 |
| D6 原生假谓词/尾线程 LSU 观察 | **PASS（SimX/处理器 RTL 各 15/15）** | B=32 独立候选，copy/vadd/affine 各 5 场景；两路各 704 个有效数组 lane 地址/计数匹配，N=0/全假无数组请求；[D6](AB_D6_PROGRESS.md)，非 PTX/AFU/U280/独立 E 验收 |
| 隔离 Linux 容器启动尝试 | FAIL | 已安装 Docker Desktop 启动超时，尚无可用 daemon；[原始返回（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-97ac3a701c7c) |
| PTX 前端 / 参数布局 | **PASS（作者自测范围）** | 严格 parser、typed IR、C++ 语义代码、源码映射和小端 packer；独立 v0.2 draft，Linux 运行器/前端/证据检查合计 69 通过、1 跳过；见 [前端记录](PTX_FRONTEND_PROGRESS.md)，生成物不可装载 |
| PTX 生成 C++ 宿主语义 | **PASS（661/661）** | copy 132、vadd 132、affine 396、probe 1；输出/全局访问 trace/计数与输入/尾部哨兵通过；假谓词提前 load 注入被检出。仅宿主审计模型，非独立 E 或设备接收 |
| PTX 后端适配 / runtime / 设备执行 | **15 条 copy/vadd/affine 四路独立接收 PASS** | B=32，6 copy/4 vadd/5 affine；非作者 E 先冻结答案再复现四路共 60 次，156 份数组、60 份参数通过。新增同一设备上下文序列的作者验证见下一行；通用项目 API、故障恢复和未见语料仍待完成。[E 独立接收](../results/e-ptx-acceptance-20261110-v2/result.json) |
| PTX 同一设备上下文连续启动 | **四路各 30/30 PASS（作者验证）** | 一次设备打开/一个 queue、29 次模块装载、两代 buffer，每路 12 次提交前拒绝后继续运行；108 数组/拒绝快照四路一致，每路 30 参数通过。独立 E 接收和超时/故障恢复 NOT_RUN。[证据与边界](AB_PTX_SEQUENCE_PROGRESS.md) |
| PTX 不同 Block / 大数组边界 | **四路各 67/67 PASS（作者验证）** | B=1/4/7/16/31/32、N 最大 1024；每路 180 数组/67 参数逐字节一致，DEBUG3 两路各 13,866 读/7,884 写通过。U280 固定 b1、256 MiB HOST、实际 200 MHz；E 接收 NOT_RUN。[四路复核](../results/u280-boundary-review-20261111-v1/result.json)、[交付入口](AB_CLOSEOUT.md) |
| E 固定 15 条 PTX 接收 | **限定范围接收** | 非作者 AI 代理、独立上下文/答案、3 镜像重建、60 次新执行、30 组独立逐 lane trace、2 正控制+23 负例；非人类签名或全 P0 接收。[任务与边界](E_PTX15_ACCEPTANCE.md) |
| U280 服务器登录 | **PASS（仅登录与身份命令）** | WLAN 绑定连接 `192.0.2.28:22`，22:32 改密后独立密码认证成功，`id -un && hostname` 返回 `u280user` / `localhost`、退出 0；[最新登录结果（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-85932b77e834)，22:19 原始证据保留 |
| U280 账号密码修改 | **PASS（passwd 退出 0，随后登录 PASS）** | 用户本机输入，未保存密码或改密终端会话；[改密结果（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-68356460adf4)，首次 UNCONFIRMED 记录保留 |
| U280 服务器/工具/platform 文件盘点 | **PASS（实际命令范围）** | [最新盘点（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-7e1523062750)：Vivado/v++ 2023.1、XRT/驱动 2.13.479，HBM[0..31]/HOST[0] 文件级资源；许可与设备观察见 D7 |
| U280 小型综合/许可/设备观察 | **PASS（D7 限定范围）** | 两 CPU 的 AXI 组件综合退出 0、许可证实际签出；8/8 卡查询成功且当时空闲；[D7](AB_D7_PROGRESS.md) |
| U280 完整构建与上板 | **原生 152/152、PTX B=32 回归 15/15 PASS** | b1 HOST 256 MiB、加载 UUID、DATA_CLK 200 MHz，退出后空闲。原生 608 份捕获、PTX 39 份数组及 15 份参数匹配参考。TIMING-7 仍 OPEN。[原生回归（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-899bf14e1e4c)、[PTX 回归（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-35c58f764bb5)、[D13](AB_D13_PROGRESS.md) |
| D11 原始 runtime200 输入 | **PASS（本地准备范围）；服务器编译 FAIL** | 104 项固定源码、116 项包清单，Ubuntu 公共库编译通过；D12 服务器实测原包触发 GCC 9 未初始化变量错误，原件保留。服务器通过版本见下一行；[输入与接收范围](../environment/u280-fpga/RUNTIME.md) |
| U280 服务器 runtime200 | **PASS（编译/依赖与当前板测范围）** | [D12 v4](../results/u280-runtime-20261109-v4/returned/runtime/result.json) 两库用于原生与 PTX 板测，按哈希绑定同一 xclbin/200 MHz；已观察当前样例的装载、HOST 通路、启动/完成和读回。通用 runtime 生命周期及恢复仍未接收 |
| D8 独立 U280 FPGA 候选/输入包 | **PASS（源预处理范围）** | RV64/1c/8w/4t、合并 HBM 主接口、HOST[0]；[D8](AB_D8_PROGRESS.md)，288 项输入包；未执行 Vivado elaboration/XO/综合/实现，200 MHz 只是构建目标 |
| D8 HOST/platform 复查 | **FAIL（SSH 255），远端 NOT_RUN** | 密码认证阶段连接结束，未得到新设备/权限证据；[原始记录（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-0fe9894fe41e)，不推翻历史成功登录，也不假定 D7 空闲观察仍有效 |
| D9 HOST/platform 身份 | **PASS（只读范围）** | [09:46 采集（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-f7b7a5a59ea5)；XSA↔8 卡 interface UUID 匹配，当时 ready/无 KDS 任务，HOST 仍为 0，sudo 需要密码 |
| D9 真实 U280 XO | **PASS（OOC/elaboration/gate/打包范围）** | [10:10 完成](../results/u280-preflight-20261109-100406-629/returned/build/result.json)，Vivado 0、340.708 秒；五个 vendor IP、13 类/22 个模块实例检查；XO 留存服务器，非 xclbin/板上结果 |
| AI 对照实验 | NOT_RUN | 待冻结配对任务、预算与验收 |

## 后续验收顺序

1. **当前 C API 组合已有新合法语料的四路独立接收。** 本轮 48 条/路覆盖新输入、合法源变体和同 context 生命周期；后续如扩大 P0 指令或地址范围，应另冻语料和 trace 判据，不能继承为完整 P0 支持。[本轮 E 接收](E_RUNTIME_UNSEEN_ACCEPTANCE.md)
2. **补物理故障恢复的前置依据。** 三模型实际超时排空和设备故障封锁已验证；物理后端仍不可恢复。先取得固定平台停止/旧 DMA 隔离机制和可观察成功条件，再实现并在隔离窗口接收，包含失败重试、晚到事务和重新分配后的正确性。进程终止不作为硬件隔离。TIMING-7 保持 OPEN。[恢复记录](RUNTIME_RECOVERY_20261111.md)、[合作协议](COLLABORATION_PROTOCOL.md)
3. **单列两类研究实验。** 功能验收后，同卡同配置比较原生与 PTX，再做 Core 或 Cache 的单变量对照。AI 协作实验可先准备配对任务、同等预算与冻结验收，执行状态为 NOT_RUN。[研究计划](RESEARCH_PLAN.md)
