# 正式 v1.4 同谓词模块的 NOXRT AFU 验证

## 先验证参数暂存

固定 binding 为 `results/c-runtime-merge-20261111-v3/bindings/xrtsim/binding.json`，SHA-256 为 `7f1bf3fc59419f7a45c827eb7b35298c315f65ecf7180e891ac2e98d33c5d915`。核对了目标 lock、native 回执、`-DXRTSIM`、`-DNOXRT`、实际加载的库及依赖。XRT driver 的 ELF 依赖指向 `libxrtsim.so`，设备上下文中的 VM 查询返回 0。[固定 binding（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-7302ae65aba8) · [源核验、ELF 依赖及探针命令](../results/local-ptx-same-predicate-afu-align-fixed-20261121-v2/summary.json)

非空 host payload 由 Vortex2 队列复制到设备暂存槽。1–4,096 字节走同一 4,096 字节槽池。VM 关闭时，全局分配从 `0x10000` 开始，放置粒度为 64 字节。队列将暂存地址原样拆分到两条 KMU `STARTUP_ARG` DCR，AFU 中的 Vortex 经 KMU 分派，入口从 `MSCRATCH` 取回地址。槽在 launch 退休后归还到池中，保留原设备地址。[暂存和退休](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/sw/runtime/common/queue.cpp#L411) · [槽池与分配](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/sw/runtime/common/device.cpp#L181) · [分配粒度](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/sw/runtime/common/common.h#L26) · [AFU 实例](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/hw/rtl/afu/common/VX_afu_wrap.sv#L736) · [设备入口](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/sw/kernel/src/vx_start.S#L124)

先只运行逐字节读取的原生设备探针。两个 context 共 10 次，覆盖三个算子的六份原输入、两份 V03 参数布局、4,096 字节槽边界及其后一次小载荷重用。`a0` 与 `MSCRATCH` 都回读为 `0x16000` 或 `0x11000`。两址均为 64 字节对齐，所有字段都按实际地址满足各自的 4 或 8 字节对齐。首轮六个原输入地址已回读，随后探针脚本误以字典调用位置参数打包器，在主机端停止。改为有序参数后用新 run_id 完成全部 10 次。4,096 字节捕获核查的是入口槽基址和原字段偏移。[10 次原始回读索引（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-507daa0a4ff5) · [首次失败记录](../results/local-ptx-same-predicate-afu-align-fixed-20261121-v1/summary.json)

运行时对齐 binding 接收清单升到第 2 版。加入的是上述固定 NOXRT 回执的完整 SHA-256，加载时仍查询 VM。接收范围为原 `vortex2-queue-args-align-v1` ABI 与 D5 模块格式。正式 v1.4 模块复用已校验的五份镜像、原 PTX、原冻结输入与预期。普通回归使用该 binding 的 `Context.load/launch/wait`。[装载检查](../scripts/ptx_runtime.py) · [v1.4 构建回执](../results/local-ptx-same-predicate-production-build-20261121-v1/summary.json)

## 固定 binding 的正式模块回归

| 检查 | NOXRT AFU 结果 |
|---|---|
| P0 算子回归 | copy 168、vadd 168、affine 504，全计 840/840。另有 57 项运行时拒绝和 3 次超时排空及恢复后启动通过。 |
| P0 指令见证 | 两次完整启动通过，17 项 PTX 指令形式拒绝按原诊断通过。 |
| 冻结 V03 | 13/13，含 5 个 4 GiB 边界用例及别名读回。全量复核运行前后各 39 份数组和 13 份参数。 |
| 原输入 1,024 元素 | copy、vadd、affine 均逐字节匹配完整输出及前后各 16 字哨兵，输入数组回读相同。 |
| 原输入 16,381 元素 | copy、vadd、affine 均逐字节匹配完整输出、前 16 字哨兵及尾部 19 字（含三个未激活索引），输入数组回读相同。 |

对照只改变 binding 描述字段，使整份 binding 的 SHA-256 不同。该 binding 可打开相同 AFU 库，加载对齐模块时返回 `E_TARGET_MISMATCH`，上下文保持 `READY`。固定 binding 完成六次原输入回放，三份 P0 的算术和捕获由原离线入口重核。[实际命令与回执](../results/local-ptx-same-predicate-afu-regress-20261121-v1/summary.json) · [六组输入捕获](../results/local-ptx-same-predicate-afu-regress-20261121-v1/original-inputs/summary.json) · [binding 拒绝对照](../results/local-ptx-same-predicate-afu-regress-20261121-v1/altered-binding/result.json)

## 逐 lane 观测条件

固定 binding 内的 AFU 用 `-DNDEBUG` 构建。另在隔离目录从同一固定源码和硬件配置构建 `DEBUG=2` NOXRT 模型，只启用原有 pipeline 和内存 trace。复用逐字节相同的 `libvortex.so` 与 `libvortex-xrt.so`，核对实际 Ramulator 依赖。原生 demo 先验证 AFU 输出带 PC、mask 和地址的 LSU 请求及 CTA 握手，随后这份追踪 binding 也通过 10 次参数地址探针。追踪模型回放正式校验后的 v1.4 镜像字节，逐 lane 请求观测点在缓存合并之前。[隔离构建与 demo](../results/local-ptx-same-predicate-afu-trace-build-20261121-v1/summary.json) · [追踪 binding 的对齐探针](../results/local-ptx-same-predicate-afu-align-trace-20261121-v1/summary.json)

六次追踪回放共核对 139,240 条数组请求。同一逻辑线程的读写方向、完整地址和请求顺序均匹配。16,381 元素的最后一个 warp 在三个算子中均只有 lane 0 发出预期数组读写，归一化掩码为 `1000`。lane 1–3（索引 16,381–16,383）各为 0 条数组请求。日志副本中的额外假 lane store 被检查器检出。六次追踪的完整输出和哨兵也均回读一致。[六份原始日志索引](../results/local-ptx-same-predicate-afu-trace-20261121-v1/summary.json) · [机器复核](../results/local-ptx-same-predicate-afu-review-20261121-v1/summary.json)

项目 Python 自测 296 项通过、1 项跳过、退出 0。板上 U280 为 `NOT_RUN`。[宿主自测](../results/local-ptx-same-predicate-afu-host-20261121-v1/summary.json)

## 复现

在 `Vortex-AB-Ubuntu-22.04` WSL 的 `/mnt/d/Vortex-U280` 中运行。每轮使用新的 `tag`。可用 v1.4 的正式构建入口先重建 `built` 目录中的五份模块。[正式 v1.4 构建](PTX_SAME_PREDICATE_PRODUCTION_20261121.md#复现)

```sh
tag=NEW
run=results/local-ptx-same-predicate-afu
exp=experiments/ptx-same-predicate-afu
built=results/local-ptx-same-predicate-production-build-20261121-v1
python3 -B "$exp/alignment.py" --build "$built" --output "$run-align-fixed-$tag"
python3 -B "$exp/regress.py" --build "$built" --alignment "$run-align-fixed-$tag" --output "$run-regress-$tag"
python3 -B "$exp/build_trace.py" --output "$run-trace-build-$tag"
python3 -B "$exp/alignment.py" --build "$built" --trace-build "$run-trace-build-$tag" --output "$run-align-trace-$tag"
python3 -B "$exp/trace_lsu.py" --build "$built" --fixed-alignment "$run-align-fixed-$tag" \
  --trace-build "$run-trace-build-$tag" --trace-alignment "$run-align-trace-$tag" --output "$run-trace-$tag"
python3 -B "$exp/review_afu.py" host --output "$run-host-$tag"
python3 -B "$exp/review_afu.py" review --build "$built" --host "$run-host-$tag" \
  --alignment "$run-align-fixed-$tag" --regress "$run-regress-$tag" \
  --trace "$run-trace-$tag" --trace-build "$run-trace-build-$tag" --trace-alignment "$run-align-trace-$tag" \
  --output "$run-review-$tag"
```
