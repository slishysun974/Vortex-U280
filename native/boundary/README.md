# A/B 原生 u32 边界回归 v2

2026-11-08 D5：在 v1 基础上增加显式 `--target-profile block32-v1`，使用独立的 RV64/1c/8w/4t 配置。该候选含 76 个参数组合、152 次启动：完整 N/alpha 矩阵和谓词检查使用 B=32，其他 block 为 1/4/7/16/31；检查 B=33/64 拒绝。三路原生自测通过，见 [D5](../../docs/AB_D5_PROGRESS.md)。运行器默认仍使用 `smoke` 基线；此模式保持原 140 个输入组合，越限检查现为 B=17/32。host 按编译配置核对实际 CAPS，不接受混用不同配置的 runtime。

以下描述 v1/D4 的 4w×4t 基线覆盖。v1 的全部源程序、输入与输出快照保存在原 results 中，不受当前源码升版影响。候选是原生验证用配置，未修改项目 ABI 或 PTX 白名单，也未被 C/D/E 接收为 P0 默认配置。

使用固定上游 `vortex2` native API 与 KMU kernel，服务于 A 的处理器验证及 B 的本地 AFU 集成验证。此程序不是 PTX 前端、P0 module/runtime 实现或 E 的独立验收集。所有代码放在上游目录之外，在新的生成构建树中编译。

入口：`scripts/run_native_smoke.py --native-boundary`；其余参数与原 smoke 一致，支持 `simx / rtlsim / xrtsim`。每次先完成同配置上游 demo，再构建本程序。每个 backend 使用新 build/run_id；AFU 入口固定 `TARGET=xrtsim`，不调用物理 XRT。

固定硬件仍为 RV64 / 1 cluster / 1 core / 4 warps / 4 lanes。70 个参数用例各连续运行两次不同输入，共 140 次 launch；同一 device、queue、module 和四个 buffer 在全部 launch 之间复用：

- N=0/1/7/31/32/33/63/64/65/257/1024；每个 N 测 copy、vadd、affine(alpha=0/1/0xffffffff)，B=16。
- N=33、B=1/4/7，各测三类运算；另外在 B=16 测全假和交替条件。
- 每个输入包含固定 u32 极值及确定性随机数据。输出按 Python 大整数运算后取模 2^32，逐 byte 比较；答案不传给 host/device 程序。
- 参数指针为实际设备 buffer 地址加 32 bytes；前后至少 8 个 u32 哨兵。每次读回完整 x/y/z 和线程记录，核对输入不变、条件为假和尾部的输出不变、线程索引和 grid/block 值。
- N=0 正常启动一个非空 block；kernel 仍写每个线程的索引记录，数据数组的条件均为假。
- B=32 超出本配置的 16 个线程/core，在结束时检查原生 runtime 返回 `VX_ERR_INVALID_VALUE`。此项是拒绝测试，不算 B=32 执行支持。

`common.h` 是此 native 测试的私有参数结构：4 个 u64 设备地址和4 个 u32 标量，48 bytes；它不是 `ptx-vx-args-v1`。未修改硬件配置、P0 ABI、PTX 白名单或现有冻结答案。

每轮 `boundary/` 保存运行前生成的 inputs、expected、corpus.json、实际捕获 actual 和逐项 comparison.json，以及本轮源程序/生成器副本。corpus 与输入/答案哈希在运行后核对；输出缺失、字节不符或参考被改写均失败。expected 来自同一实施者编写的 Python reference，因此只能称 A/B 自测。

这些输出检查不证明假条件没有读内存，也不证明没有重复执行相同写入；尚需访问 trace/计数和独立接收。此 harness 为可控仿真使用，错误时结束进程，外层有进程组超时；这不证明真实设备支持安全 abort/recovery。没有性能、时序、HBM/HOST[0] 或物理板卡结论。
