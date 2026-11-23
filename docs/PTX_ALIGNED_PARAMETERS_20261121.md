# PTX 对齐参数读取单变量实验

正式前端接入与后续回归见 [PTX 设备参数读取契约](PTX_DEVICE_PARAMETER_ACCESS.md)。

**对齐读取使 SimX 周期减少 59.64%–65.06%，处理器 RTL 周期减少 62.58%–69.05%，退休 warp 指令减少 62.77%–67.49%。** copy、vadd、affine 的两档归档输入在两个模型中共完成 48 对、96 次计数启动，完整输出与前后哨兵全部匹配原冻结答案。每对的周期差都为正，两个模型的退休数逐项一致。[机器结果与逐对差值](../results/local-ptx-align-review-20261121-v1/result.json)

## 对齐依据

1. 队列将 host 参数字节复制到设备暂存槽，再将槽基址原样拆成 `STARTUP_ARG0/1`。三个 payload 均落入 4,096 字节暂存槽路径。固定 D5 绑定查询的 VM 支持为 0，暂存槽走普通全局分配。该分配从 `0x10000` 起步，以 4,096 字节管理页，按 64 字节对齐分割块，回收时保存原地址。由此保证暂存基址至少 64 字节对齐。[队列暂存](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/sw/runtime/common/queue.cpp#L411) · [槽分配](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/sw/runtime/common/device.cpp#L181) · [内存分配](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/sw/runtime/common/device.cpp#L1061) · [分割算法](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/sw/common/mem_alloc.h#L96) · [粒度](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/sw/runtime/common/common.h#L26) · [设备基址](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/VX_types.toml#L20)
2. 两个模型都将 `STARTUP_ARG0/1` 合成 CTA 参数，交给 warp 的 `MSCRATCH`。同一设备启动代码执行 `csrr a0, MSCRATCH` 后调用 kernel。自然对齐的字段布局由前端写入 manifest，离线复核逐项检查 `offset % align == 0` 与字段范围。[SimX KMU](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/sim/simx/kmu/kmu.cpp#L64) · [RTL KMU](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/hw/rtl/VX_kmu.sv#L124) · [RTL warp 分派](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/hw/rtl/core/VX_scheduler.sv#L334) · [设备入口](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/sw/kernel/src/vx_start.S#L124) · [布局生成](../scripts/ptx_frontend_v12.py#L173)
3. 每个模型对每个算子和规模先运行一次单 CTA 的独立探针。探针使用随后计数启动的同一参数字节和缓冲区，直接回写入口 `a0` 与 `MSCRATCH`。12 次读回两值均相等，copy 与 affine 为 `0x14000`，vadd 为 `0x16000`，均满足 64 字节对齐。每个字段的实际地址均通过 4 或 8 字节检查。探针结束后重新上传原数组和哨兵，再采集计数。[SimX 样例（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-642d4d4982c1) · [RTL 样例（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-1ec6dc098901)

| 算子 | payload 字节 | u64 指针偏移 | u32 标量偏移 |
|---|---:|---|---|
| copy | 24 | 0、8 | 16 |
| vadd | 32 | 0、8、16 | 24 |
| affine | 32 | 0、8、16 | 24、28 |

## 单变量与结果

隔离目录重建逐字节控制版和对齐版，两个版本共用固定 RV64 小端工具链、`-O3`、编译规则、设备 wrapper、PTX 语义体及 launch ABI。控制版的三个 vxbin 与原归档逐字节相同。对齐版仅替换 `ptx_read32/64`，使用固定长度 `__builtin_memcpy` 读取已保证对齐的 4 或 8 字节。反汇编验证三算子不再出现 `lbu`，参数改由 `ld/lw` 读取，`split/branch/join` 和写栈计数保持原值。`kernel_main` 的静态指令从 76、104、115 条降为 25、32、34 条。[构建命令、输入身份与退出码](../results/local-ptx-align-build-20261121-v1/summary.json) · [读取函数差异示例（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-aa977e41c6c0) · [vadd 对齐版反汇编（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-5458b0755ef4)

固定 D5 模型为 1 核、8 warp、4 lane，block 32。每个模型每个算子和规模执行 4 对，次序交替。每次在完成上传后读取两次等值的空闲 MPM 快照，事件退休后立即读回计数，再做完整输出比对。下表为逐字节版 → 对齐版。周期取各路 4 次的中位数，百分比相对于逐字节版；逐对差值另存。`MINSTRET` 按完成的 warp 指令计数。[SimX 命令与退出码](../results/local-ptx-align-simx-20261121-v1/summary.json) · [RTL 命令与退出码](../results/local-ptx-align-rtlsim-20261121-v1/summary.json)

| 算子 | 元素数 | SimX 周期（降幅） | 处理器 RTL 周期（降幅） | 退休 warp 指令（降幅） |
|---|---:|---:|---:|---:|
| copy | 1,024 | 31,654 → 12,774（59.64%） | 35,311 → 13,120（62.84%） | 20,800 → 7,744（62.77%） |
| copy | 16,381 | 493,302.5 → 198,175（59.83%） | 553,859 → 207,229（62.58%） | 331,845 → 122,949（62.95%） |
| vadd | 1,024 | 42,352 → 15,833.5（62.61%） | 46,784.5 → 16,099（65.59%） | 27,968 → 9,536（65.90%） |
| vadd | 16,381 | 661,400 → 245,628（62.86%） | 750,931.5 → 254,258.5（66.14%） | 446,536 → 151,624（66.04%） |
| affine | 1,024 | 46,861 → 16,418（64.96%） | 50,167.5 → 16,868（66.38%） | 30,784 → 10,048（67.36%） |
| affine | 16,381 | 731,450.5 → 255,543.5（65.06%） | 856,301 → 265,011（69.05%） | 491,593 → 159,816（67.49%） |

1,024 元素的动态退休差额恰好为每 warp 的静态差额乘以 256。16,381 元素中，copy 和 vadd 的差额分别为 51 和 72 条乘以 4,096，affine 的实测差额比 81 条乘以 4,096 多 1 条。RTL 的大 vadd 逐对节省 472,633–544,949 周期，其中一次逐字节运行触发了驱动的 10 秒等待提示，最终完成校验。实验只覆盖通过 Vortex2 队列暂存的对齐 payload 与固定模型绑定，设备周期和收益均为本地模型结果。U280 本轮为 `NOT_RUN`，生产前端仍使用原参数读法。[SimX 原始样本（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-707bc73e228b) · [RTL 原始样本（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-8ab17afdcde5)

## 复现

前三条在项目 WSL 环境执行。离线复核可在 Windows 或 WSL 执行。使用新输出路径。

单独运行项目约定的 Python 自测，使用固定 Vortex 头文件，结果为 292 项通过、1 项 Windows 专用检查跳过、退出 0。[自测命令与日志（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-79ab51152c8b)

```sh
python3 -B experiments/ptx-aligned-parameters/build.py --output results/local-ptx-align-build-new
python3 -B experiments/ptx-aligned-parameters/run.py --build results/local-ptx-align-build-new --backend simx --output results/local-ptx-align-simx-new
python3 -B experiments/ptx-aligned-parameters/run.py --build results/local-ptx-align-build-new --backend rtlsim --output results/local-ptx-align-rtlsim-new
mkdir results/local-ptx-align-review-new
python3 -B experiments/ptx-aligned-parameters/review.py \
  --build results/local-ptx-align-build-new --simx results/local-ptx-align-simx-new \
  --rtlsim results/local-ptx-align-rtlsim-new \
  --prior results/local-ptx-perf-attribution-20261121-v2/result.json \
  --output results/local-ptx-align-review-new/result.json
```
