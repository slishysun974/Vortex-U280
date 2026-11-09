# PTX → Vortex 兼容性规范

版本：`ptx-vx-p0-v0.1-draft`；日期：2026-11-07。状态：设计目标，尚未实现或验收。首次执行时由 A/C/D 核对并冻结，E 接收测试；支持范围变化必须升版。

2026-11-08 实施补充：本文保留 v0.1 设计契约；新的前端采用独立 `ptx-vx-p0-v0.2-draft`，明确首版语法与保守静态检查范围，见 [版本和接收说明](PTX_FRONTEND_PROGRESS.md) 及 [机器可读 profile](../configs/ptx_frontend/v1/profile.json)。生成物是不可装载的 C++ 语义包，未接入 Vortex 后端；根 target caps 的旧 profile 不因此自动更新。

本规范描述项目接收哪些 PTX 程序、怎样保持语义以及如何拒绝超出范围的程序。它不修改 NVIDIA PTX 定义；项目只能限制输入或准确实现，不能给同名指令重新定义方便实现的行为。

## 1. 输入与目标

| 项目 | P0 设计约定 |
|---|---|
| 输入单位 | UTF-8 PTX 文本，单个 `.entry`；允许 `.visible`；不接收 cubin/fatbin/SASS |
| 起始语法版本 | 手写语料先固定 `.version 7.0`、`.target sm_70`、`.address_size 64`；这是接收的源语言标记，不表示模拟完整 sm_70 |
| 其他 PTX 版本/target | P0 拒绝；增加固定工具链生成语料时逐项评估并升版，不能仅改版本号骗过 parser |
| 目标 | 配套 Vortex/VOLT 工具链；优先 RV64、小端。具体 commit/特性/数据布局由 `target_lock` 冻结 |
| 入口和参数 | 单入口；`.param .u64` 设备指针、`.param .u32` 标量；名字、顺序、类型、对齐由 parser 产生元数据 |
| 执行维度 | `grid=(G,1,1)`、`block=(B,1,1)`，G/B 为正且满足 capability；shared_bytes=0；单队列、单个 kernel 在途 |
| 线程可见状态 | `%tid.x`、`%ntid.x`、`%ctaid.x`、`%nctaid.x`；不读物理 core/warp/lane ID |
| 控制流 | 源程序为直线指令加谓词，最后无条件 `ret`；不含源级 `bra/call`、循环或提前退出 |
| 内存 | `.param` 只读、`.global` 自然对齐标量 u32 load/store；使用有效设备分配；不同线程无数据竞争 |
| 不支持 | local/shared/const、原子、barrier、warp collective、浮点、纹理、tensor、动态并行、设备函数/外部链接 |

PTX 7.0 的语义可按 [NVIDIA 归档规范](https://docs.nvidia.com/cuda/archive/11.0/parallel-thread-execution/index.html) 核对。选择较早版本是收敛初始语法的团队决定，不意味着当前 NVCC 会输出这一版本，也不意味着需要安装 CUDA 11.0 才能手写 PTX 测试。

后续 CUDA 入口只承诺“指定 NVCC 版本、选项和语料产生的设备 PTX”。NVCC 的 PTX 输出不包含主机程序，需要项目 runtime 调用；低 compute target 也不能替代 PTX `.version` 检查。[NVCC PTX 输出说明](https://docs.nvidia.com/cuda/cuda-compiler-driver-nvcc/index.html#ptx-ptx)

## 2. P0 白名单

白名单键是完整的“opcode + 类型 + 修饰符 + 地址空间 + 操作数形式”，不是助记符。以下每一行均须有正例、边界和拒绝测试才可标为支持。未知指令/修饰符/指令性 directive 一律拒绝；注释和空白可忽略。

| 类别 | 初始接受形式 | 核心要求 |
|---|---|---|
| 声明 | `.reg .pred/.b32/.b64`；命名与 `<N>` 寄存器数组；entry 的 `.param .u32/.u64`；大括号、分号、整数常量、注释 | 数值解析、重复声明、寄存器范围和类型校验；语法细则随 parser 测试冻结 |
| 复制 | `mov.u32`、`mov.u64` | 按位宽传值；mov.u32 可读取本 profile 的四个特殊寄存器 |
| 参数 | `ld.param.u32`、`ld.param.u64` | 参数符号及已验证偏移；参数长度/对齐匹配；指针参数不能与 host 指针混淆 |
| 整数 | `add.u32`、`sub.u32`、`mul.lo.u32` | 模 2^32；不得用带有未定义有符号溢出的 C 运算代替 |
| 地址计算 | `mul.wide.u32`、`add.u64` | 前者输出完整 64 位乘积，后者保持 64 位；合法内存地址还须满足分配范围 |
| 指针空间 | `cvta.to.global.u64` | 仅限由本 ABI 传入、已知属于 global 的设备地址及可证明保持空间的派生地址；不支持任意 generic 指针 |
| 比较 | `setp.lt.u32`、`setp.ge.u32`、`setp.eq.u32` | 无符号比较、结果为 predicate；其他比较类型不自动纳入 |
| 条件选择 | `selp.u32` | 只选择值，不代表可以把有副作用的指令提前执行 |
| 全局访存 | `ld.global.u32`、`st.global.u32`；地址寄存器加整数常量偏移 | 4-byte 自然对齐；保持每线程程序顺序与完成可见性 |
| 谓词 | 上述 mov/整数/地址/比较/选择/全局访存的 `@p`、`@!p` 形式 | 假谓词不更新目的状态、不发出访存；未初始化寄存器不能被活跃路径读取 |
| 结束 | 入口末尾无条件 `ret` | 终结当前逻辑线程；kernel 完成还需全部逻辑线程和写入满足完成条件 |

P0 不支持带 `.volatile/.weak/.relaxed/.acquire/.release/.scope` 的扩展内存形式、向量访存、任意缓存修饰符、`.sat/.cc`、进位链或没有列出的算术类型。生成 kernel 如果使用 `mad.wide`、`shl`、`cvt`、`and/or/xor` 等其他合法 PTX 指令，也必须先给出 E_UNSUPPORTED；不能因为“常见”就假定已有支持。

支持表每条记录包含 `planned / implemented / simx_pass / rtl_pass / u280_pass` 与用例/证据链接；implemented 不等于其他层通过。

## 3. 语义 lowering 规则

### 3.1 虚拟寄存器和位宽

PTX 虚拟寄存器经有类型 IR 转为目标值，交由后端分配物理寄存器；不能按 PTX 寄存器号直接映射 RISC-V x 寄存器。u32 运算在 RV64 上也必须保持 32 位结果与无符号比较含义，必要时显式截断/扩展。

P0 对未定义/未初始化使用做静态诊断或保守拒绝。工具不能以“所有寄存器默认零”的测试便利改变程序语义。

### 3.2 谓词

纯值计算可在严格证明无可观察副作用时采用选择值；谓词 load/store 必须真正阻止假路径的内存访问。生成 C/LLVM 的条件分支须继续经过 Vortex 的 SIMT 分歧处理；P0 源级没有 `bra` 不代表目标代码可以省略 SIMT 正确性。

强制测试：同一物理执行组内谓词真/假混合；假路径计算出的地址指向哨兵之外或不可访问区；执行后该路径不产生 load/store，原目的值保持。采用 trace、访问计数或可用异常观测证明，不能只检查最终向量值。

### 3.3 线程映射

对于逻辑线程 `(block_id, thread_id)`：

```text
%ctaid.x  = block_id
%tid.x    = thread_id
%ntid.x   = block.x
%nctaid.x = grid.x
i         = block_id * block.x + thread_id
```

launch 限制为 `1≤B≤1024`、`1≤G≤2^31−1`，同时满足更严格的设备 capability。线程总数用 host 宽整数检查乘法溢出；本规范三个采用 u32 线性索引的样例还要求 `G×B≤2^32`，避免 kernel 内索引回绕。如果以后改用 64 位索引，索引乘加、范围比较和地址计算都必须保持相应位宽，并单独更新用例契约。

适配层必须保证每个合法逻辑线程恰执行一次；硬件 core/warp/lane 的复用方式不改变上式。P0 禁止线程间通信，所以可采用经验证的任务映射；不能将此方案直接推广到带 barrier 的 CTA。

P0 不支持 `%laneid/%warpsize`、shuffle/vote、warp 同步、隐式 warp 同步或跨线程数据竞争。只有在这些语义完全不暴露时，才允许逻辑线程调度与物理 warp 宽度不同；不能据此宣称 32-lane warp 兼容。

### 3.4 地址

host buffer handle、设备地址、HBM 物理地址、RISC-V XLEN 和 PTX `.address_size` 分别记录。host 参数用 handle+offset 表示指针，由 C 查询设备地址后按 D 的 ABI 写入 64 位字节；不能把主机虚拟地址直接作为 kernel 参数。

P0 推荐 PTX64→RV64。若平台最终采用 RV32，必须另建 profile：保留 64 位源值/运算，明确窗口与转换位置，证明或检查范围后再降低地址宽度。高位不为零、越界或加法环绕不能静默丢弃。仅在 loader 检查基址不足以证明 kernel 内所有偏移都安全。

P0 的接口参数检查不是任意 kernel 的内存沙箱：运行前可以验证 buffer、长度和声明访问范围；任意设备计算地址的检查需要额外编译插桩/硬件能力。本项目不承诺 Vortex 对全部越界都产生精确异常。

## 4. 首期三类 kernel 与参数示例

| kernel 类 | 运算 | 输出判据 |
|---|---|---|
| copy_u32 | `z[i]=x[i]`，仅 i<N | bit 相等，尾部不变 |
| vadd_u32 | `z[i]=(x[i]+y[i]) mod 2^32`，仅 i<N | bit 相等，输入不变，尾部不变 |
| affine_u32 | `z[i]=(alpha*x[i]+y[i]) mod 2^32`，仅 i<N | bit 相等；覆盖 alpha=0/1/最大值 |

vadd 的项目参数 ABI `ptx-vx-args-v1` 示例（独立于旧 AEC ABI）：

| 字节偏移 | 参数 | 大小 | 对齐 |
|---:|---|---:|---:|
| 0 | x 的设备地址 | 8 | 8 |
| 8 | y 的设备地址 | 8 | 8 |
| 16 | z 的设备地址 | 8 | 8 |
| 24 | n:u32 | 4 | 4 |
| 28 | padding，必须清零 | 4 | — |

此例 payload 为 32 byte、小端；参数布局算法为按声明顺序自然对齐，最终按最大字段对齐补齐。D 生成布局，C 的设备 wrapper 从这个 payload 读取参数；如果上游启动结构另带 grid/entry 等字段，单独封装，不能把上表直接冒充上游原生参数结构。其他 kernel 必须有自己的 manifest，不能复用 vadd 的固定偏移。

默认测试 B=32、G=max(1,ceil(N/32))，也测能力允许的其他 B，验证线程编号不是写死。N=0 仍使用有效非零分配并正常启动一个 block：所有线程执行索引和比较，所有访存谓词均为假；不能通过禁用所有硬件 lane 或跳过 launch 代替此测试。所有数组互不重叠，长度至少 `max(N,1)+guard` 元素，guard 内容固定。

## 5. 扩展顺序及前置条件

| profile | 新增目标 | 放行条件 |
|---|---|---|
| P1-CF | `bra`、结构化 if/else、可归约循环；必要整数转换/运算 | CFG 校验、分歧/收敛测试、嵌套/循环/尾线程通过；不可归约 CFG 明确拒绝 |
| P1-FP | 精选 `add.rn.f32`、`mul.rn.f32`、`fma.rn.f32` | 舍入、融合/非融合、NaN/Inf/±0/subnormal/FTZ 逐项定约并测试，不以宽容差掩盖语义差异 |
| P2 | 静态 shared、完整 CTA `bar.sync 0`、reduction/transpose | CTA 资源可驻留；参与线程一致；shared 隔离；屏障内存可见性；拒绝分歧屏障与危险提前退出 |
| P3 | 指定原子或 warp 操作、更多 NVCC 语料 | 每项独立能力、语义与拒绝测试；逻辑 warp 32 的映射被明确实现 |

P2 的 CTA 不能在没有正确挂起/恢复机制时分到互不同时驻留的批次后等待彼此。默认先限制一个 CTA 的所有参与 warp 驻留同一 core，并检查线程/shared/barrier 配额，再放开更多调度方式。

浮点功能不能只承诺统一 `1e-3` 容差：指令级语义有位级/ULP/特殊值测试，应用级误差阈值另列，验证实际承诺的 numeric mode。

## 6. 验收矩阵

| 维度 | 最低用例 |
|---|---|
| 语法/类型 | 合法声明、名称变换、寄存器数组；重复/未知/类型不匹配的拒绝 |
| 算术 | 0、最大值、溢出、乘积高低位、RV64 上 u32 符号位为 1 |
| 谓词 | 全真/全假/交替；假谓词目的不变、无访存；屏蔽尾线程 |
| 线程 | N=0/1/7/31/32/33/63/64/65/257/1024；跨多 block；其他合法 B |
| 地址/ABI | 非零 buffer offset、字段对齐、参数长度、无效 handle、高位地址检查；可用地址不够高时用适配层单测，不冒充板上高地址测试 |
| 通用性 | 改 entry/寄存器名、插入合法等价指令组合、未见输入和组合；无按名字查预制结果 |
| 拒绝 | 超版本、未知 opcode/modifier、非法维度、超资源、P0 barrier/FP/warp 等全部明确失败 |
| 证据 | 每层 backend、编译链和 target hash、实际输出、独立答案、原始日志、状态 |

首期冻结不少于 30 个有意义的语义/拒绝用例，另加三类 kernel 的参数化集成样例；计数不得把同一用例不同日志条目当成新增覆盖。未支持项的拒绝通过不计入执行支持数量。

参考依据：[PTX 规范](https://docs.nvidia.com/cuda/parallel-thread-execution/index.html)、[Vortex 工具链构建](https://github.com/vortexgpgpu/vortex/blob/master/docs/building_toolchain.md)、[Vortex intrinsics](https://github.com/vortexgpgpu/vortex/blob/master/sw/kernel/include/vx_intrinsics.h)。上游接口随版本变化，所有 native 类型、函数名和编译开关以冻结源码为准。
