**任务 1 与任务 2 完成情况对照**

**22:22 更新：** 上述固定 15 条 B=32 PTX 用例已完成非作者 AI 代理 E 的限定独立接收：先冻结答案，再重建三份镜像并在 SimX、处理器 RTL、NOXRT AFU、U280 各复现 15 次；独立输出/ABI/两路 LSU 与故障注入均通过。[E 接收范围](E_PTX15_ACCEPTANCE.md)。未见语料、通用 runtime 和正式人类签名仍不在本次结果内；TIMING-7 本轮按用户要求跳过，OPEN 保留。

**21:44 更新：** PTX copy/vadd/affine 的 15 条 B=32 用例现已在 U280 15/15 PASS，涵盖多 Warp、G=1–3、N=0 和尾线程。39 份数组及 15 份参数与既有 SimX、处理器 RTL、NOXRT AFU 逐字节一致；A 的逐 Block/有效 lane 访存观察也已完成相应用例。TIMING-7、通用 runtime 与 E 独立接收仍未完成。[最新复现与范围](PTX_FRONTEND_PROGRESS.md#2026-11-10-2144-ab-的-15-条-ptx-板上回归)。下文保留 19:07 的原始阶段对照，其中“多 Warp、vadd/affine、设备 LSU 待补”已由这组后续证据推进，shared/local/barrier 与一般分支仍保持 P0 排除。

截至 2026 年 11 月 10 日 19:07 已归档结果，北京时间。

**任务 1 的核心功能验收已经达成：不经过自研 PTX 前端，原生向量加法已在 SimX、处理器 RTL 和 U280 上运行通过。任务 2 已完成 P0 所需的部分语义约定与实现，并有单条 PTX copy 的三路执行证据；完整架构映射和专项验收尚未完成。**

与 11 月 9 日报告相比，主要新增两项成果：U280 完整原生回归 152/152 通过，以及首条 PTX copy 在 SimX、RTL 和 U280 上均通过。HOST 内存和实际运行时钟已在本轮板测中核实。平台既有 TIMING-7 告警仍为 OPEN，功能运行成功不改变其静态审阅状态。

按任务 1 列出的工作逐项对照：

| 工作 | 当前判断 | 已有成果与范围 |
|---|---|---|
| 下载、构建 Vortex | 已完成当前基线 | 固定 Vortex v3.0 提交与配套工具包，建立专用 Linux 环境和隔离构建目录 |
| SimX 运行现成测试 | 已完成，并扩展原生回归 | 上游整数 demo 通过；独立候选的 copy/vadd/affine 原生回归 152/152 通过 |
| Verilator RTL 仿真 | 已完成当前测试范围 | 处理器 RTL 原生回归 152/152 通过；另有本地 AFU 模型 152/152 通过 |
| Core、Warp、线程及存储配置研究 | 部分完成 | 已验证单 Core、每 Warp 4 线程，以及每 Core 4→8 Warp 的候选变化；尚未形成多 Core、不同线程宽度、Shared Memory 和 Cache 的系统对照 |
| 生成 U280 FPGA 配置文件 | 已完成 | 综合、实现和 xclbin 生成通过，产物与报告已归档；板上实际读回 200 MHz |
| U280 运行原生 Kernel，验证 Host 通信 | 已完成当前功能范围 | 152/152 原生启动完成，输入传入、设备执行、结果读回与参考一致 |

板上 152 次运行包括 **36 次 copy、36 次 vadd、80 次 affine**。608 份输入读回、输出和线程记录逐字节匹配保留的参考；原生执行命令 `./smoke inputs output` 退出 0，日志记录 `CAPTURE_COMPLETE 152`。SimX 与 RTL 的对应回归执行也均退出 0。[板上原始命令和输出（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-ec97327189b8)、[逐项比对（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-899bf14e1e4c)、[仿真回归](AB_D5_PROGRESS.md)

当前板测使用项目编写的原生边界测试 Kernel，由 Vortex 配套工具链编译，没有经过自研 PTX 前端。因此满足“使用原有工具链，在三类后端运行向量加法”的功能标准。参考答案仍来自实施者自测，项目协议要求的独立复现与正式接收尚未完成；也尚无配置优化或性能提升结论。

任务 2 可以整理成下面这份语义映射审阅表。这里把“接口已约定”“代码已接入”和“设备上已验证”分开描述。

| 接口 | 已明确或已实现的映射 | 验证范围与剩余工作 |
|---|---|---|
| PTX Thread ID | `%tid.x` 对应 `threadIdx.x`；设备 wrapper 也传入 block 大小、block 编号和 grid 大小 | 原生线程记录覆盖不同一维 Block/Grid；PTX copy 已验证一组 B=4、G=2 的功能输出。PTX 多 Warp 和更多尺寸仍待补测 |
| PTX Block / CTA | 复用 Vortex2 launch、KMU 和每 Core 的 CTA Dispatcher；固定版本按单 Core 容量限制一个 CTA | 原生 B=32 通过，B=33/64 拒绝；当前实测仅一个 Core，未覆盖多 Core 分配，也未接收二维、三维 PTX 启动 |
| PTX Warp | 当前配置为每 Core 8 个 Warp、每 Warp 4 个线程；P0 不暴露 Warp 专用操作 | 已明确限制。32 线程 Block 不等于 32-Lane Warp；shuffle、vote 等语义未实现或验收 |
| `.global` | 取得实际设备 buffer 地址，按 64 位小端参数传入；wrapper 用设备 u32 load/store 实现访问 | 单条 PTX copy 三路通过，含偏移和输出两端哨兵检查；通用 buffer 生命周期及更完整访存语义仍待验收 |
| `.shared` | P0 明确排除；上游提供 CTA 本地存储入口可供后续研究 | 尚未完成 PTX 块级分配、地址映射与共享可见性测试 |
| `.local` 与 Spill | PTX `.local` 属于 P0 排除项 | 尚未形成线程私有空间、栈和寄存器溢出到内存的映射与专项证据；普通程序通过不代表这些语义已验收 |
| `bar.sync` | P0 明确排除；上游有 CTA 同步接口 | 尚未完成 PTX 屏障的参与线程、计数、可见性与异常情况验证 |
| Divergence 分支分歧与重汇合 | 谓词生成条件代码，并交给配套 Vortex 编译后端 | 已有原生混合谓词/尾线程测试及 SimX、RTL 访存观察；PTX copy 有尾线程输出证据。一般 PTX 分支、循环、嵌套分歧尚未支持，设备级 PTX 访存 trace 仍待补充 |

目前最具体的 PTX 设备映射已经写进 [copy wrapper](../native/ptx_copy/kernel.cpp)：

| PTX 逻辑量 | wrapper 传入值 |
|---|---|
| `%tid.x` | `threadIdx.x` |
| `%ntid.x` | `blockDim.x` |
| `%ctaid.x` | `blockIdx.x` |
| `%nctaid.x` | `gridDim.x` |

这些 accessor 来自固定版本的 [vx_spawn2.h（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-9405dde9551f)，读取 CTA 相关状态；因此线程编号不需要从硬件 Lane 编号猜测。已有原生测试保存了四个逻辑量的逐线程记录；当前 PTX copy 样例实际使用前三项计算数组下标，不能用这一条用例宣称第四项及所有线程组合均已完成 PTX 设备验收。

首条 PTX copy 的路径已经完整运行：PTX 源码 → 现有前端语义体 → Vortex 设备 wrapper → 配套编译器和打包器 → SimX / RTL / U280。同一份 vxbin 在三路复制 7 个 u32，参数与结果一致；相关编译和执行命令退出 0。该用例为 **N=7、每 Block 4 线程、2 个 Block**，尚未验证 PTX 跨多个 Warp 的 Block。原生 B=32 的成功属于另一条证据链。[设备接续说明](PTX_FRONTEND_PROGRESS.md)、[三路比较（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-e14d0a00b6c6)

因此，任务 2 已经有可工作的最小接口实现。接下来应把本表细化为可独立接收的映射文档，为每项补齐固定源码位置、支持限制、正反例和实际测试结果。`.shared`、`.local`、`bar.sync` 等可以明确列为 P0 排除项，不需要为了完成首期映射文档而立即扩展全部功能。上游存在相关硬件或 API，不自动等于本项目已完成 PTX 支持。

近期可交付项是：补 PTX 多 Warp、多个 Block 和尾线程用例；把 PTX vadd、affine 接入同一设备流程；补生成后设备代码的谓词访存证据；由独立接收方复现。配置、缓存和共享存储的性能研究另行开展，避免与首期功能验收混为一项。

源码导航采用 `configs/target_lock.json` 的固定提交。用户所列目录可参考 [Vortex Codebase 文档](https://github.com/vortexgpgpu/vortex/blob/master/docs/codebase.md)；本项目 CTA 路径的具体依据为 [固定版本 CTA 设计（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-53fc73800a15)、[KMU（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-6e9d218408ba)、[CTA Dispatcher（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-da9c62d83eac)。首期支持边界见 [PTX 规范](PTX_COMPATIBILITY_PROFILE.md)与[合作协议](COLLABORATION_PROTOCOL.md)。

本次是已有证据的分类整理，没有重跑实验。根 lock/caps 与早期前端元数据仍保留其草案身份，最新执行范围以分次归档结果为准；单条 copy 的通过不升级为完整 P0 能力接收。
