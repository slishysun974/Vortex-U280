# PTX 同谓词访存合并单变量实验

基线使用正式 `vortex2-queue-args-align-v1` 构建入口。重建的 copy、vadd、affine 镜像与正式对齐读取版归档逐字节相同。实验版只把生成代码末尾同一谓词保护的连续语句放进一个 `if`。copy 保持读 `x`、写 `z`，vadd 和 affine 保持读 `x`、读 `y`、按原顺序计算、写 `z`。原语句、volatile 全局内存访问、PTX 源、参数布局、参数读取函数、设备 wrapper、编译选项均相同。编译器在合并后重新安排部分参数读取和地址计算。该改动只存在于隔离变体。[构建命令与源差异](../results/local-ptx-same-predicate-build-20261121-v1/summary.json)

## 性能与完整输出

固定 RV64 D5 配置为 1 核、8 warp、4 lane，block 为 32。复用两档原始输入及答案，1,024 个元素启动 32 个 CTA，16,381 个元素启动 512 个 CTA。每个常规模型使用一个 context，每个算子和规模各运行四对，交替基线和变体的顺序。两版使用相同的模型专用镜像加载和 Vortex2 队列启动调用。每次重传冻结输入与哨兵，等待队列事件完成后采集计数，然后回读所有数组。两路共 48 对、96 次启动，全部输入回读、整块输出及前后哨兵逐字节一致，48 对的周期均减少。新跑的基线退休数逐项复现正式归档，两个模型内的重复以及模型间的退休数相同。[SimX 命令和样本](../results/local-ptx-same-predicate-measure-simx-20261121-v1/summary.json) · [处理器 RTL 命令和样本](../results/local-ptx-same-predicate-measure-rtlsim-20261121-v1/summary.json)

周期和退休数均为四次启动的中位数。退休数按完成的 warp 指令计数。降幅以本轮重跑的正式对齐基线为分母。

| 算子 | 元素数 | SimX 周期（降幅） | 处理器 RTL 周期（降幅） | 退休 warp 指令（降幅） |
|---|---:|---:|---:|---:|
| copy | 1,024 | 12,774 → 11,807（7.57%） | 13,116 → 11,882（9.41%） | 7,744 → 6,976（9.92%） |
| copy | 16,381 | 198,431 → 182,321（8.12%） | 205,245.5 → 184,967（9.88%） | 122,949 → 110,658（10.00%） |
| vadd | 1,024 | 15,819 → 13,064（17.42%） | 16,099 → 13,055（18.91%） | 9,536 → 8,000（16.11%） |
| vadd | 16,381 | 245,473 → 205,412.5（16.32%） | 254,594 → 208,216（18.22%） | 151,624 → 127,042（16.21%） |
| affine | 1,024 | 16,418 → 13,695.5（16.58%） | 16,865.5 → 13,759（18.42%） | 10,048 → 8,512（15.29%） |
| affine | 16,381 | 255,690 → 218,574（14.52%） | 264,907 → 219,673（17.08%） | 159,816 → 135,234（15.38%） |

反汇编逐条与运行镜像编码核对。`kernel_main` 中 `vx_split_n`、`beqz`、`vx_join` 三类指令各从 copy 的 2 条、vadd 和 affine 的 3 条减少到 1 条。三个静态指令总数分别从 25、32、34 降为 22、26、28。1,024 元素的退休节省恰好等于每 warp 减少 3 或 6 条乘以 256 个 warp。16,381 元素分别少退休 12,291、24,582、24,582 条。[双路计数、逐对差值与反汇编复核](../results/local-ptx-same-predicate-review-20261121-v1/summary.json)

## 尾部假谓词

使用独立 D6 DEBUG3 库回放同一镜像和输入。按实际 CTA 和 warp 分派绑定逻辑线程，把每个活跃 LSU lane 的方向、地址和数据指令 PC 与预期顺序逐项匹配。两路各 12 次追踪启动、各核对 278,480 条标量数组请求。1,024 元素为全真对照。16,381 元素的最后一个 warp 只有 lane 0（索引 16,380）完成预期的数组读写，归一化掩码为 `1000`。lane 1–3（索引 16,381–16,383）在两路、三个算子和两个版本中均为 **0 条数组读写请求**。在日志的内存副本中，分别给 SimX 尾部 load、RTL 尾部 store 打开一个假 lane，检查器均报告索引 16,381。请求观察位于 LSU、缓存合并之前。DEBUG3 启动不参与性能计数。[SimX 请求](../results/local-ptx-same-predicate-trace-simx-20261121-v1/summary.json) · [RTL 请求](../results/local-ptx-same-predicate-trace-rtlsim-20261121-v3/summary.json)

RTL 首轮解析把 lane 3 到 lane 0 的地址与反向掩码错误配对。修正时同步恢复地址顺序，并按同周期的 dispatch/done 绑定被复用的物理 warp。第二轮六个小规模捕获通过，大规模 vadd 的对齐基线在 DEBUG3 模式下用完 120 秒宿主等待。第三轮把 DEBUG3 等待延长到 360 秒，以缓冲方式保留压缩原始日志。性能采集独立沿用原 120 秒等待。NOXRT AFU 和 U280 均为 `NOT_RUN`。[解析失败](../results/local-ptx-same-predicate-trace-rtlsim-20261121-v1/summary.json) · [等待超时](../results/local-ptx-same-predicate-trace-rtlsim-20261121-v2/summary.json)

项目 Python 运行器自测 294 项通过、1 项跳过、退出 0。[运行器日志（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-83680d9d2d15) · [复核记录](../results/local-ptx-same-predicate-review-20261121-v1/summary.json)

## 复现

在 `Vortex-AB-Ubuntu-22.04` WSL 的 `/mnt/d/Vortex-U280` 运行。每次选用新的 `tag`。两个模型的常规计数和 DEBUG3 捕获分别保留命令、原始输出及退出码。

```sh
tag=NEW
run=results/local-ptx-same-predicate
exp=experiments/ptx-same-predicate
python3 -B "$exp/run.py" build --output "$run-build-$tag"
for backend in simx rtlsim; do
  python3 -B "$exp/run.py" measure --build "$run-build-$tag" \
    --backend "$backend" --output "$run-measure-$backend-$tag"
  python3 -B "$exp/trace.py" trace --build "$run-build-$tag" \
    --backend "$backend" --output "$run-trace-$backend-$tag"
done
python3 -B "$exp/review.py" --build "$run-build-$tag" \
  --measure-simx "$run-measure-simx-$tag" --measure-rtlsim "$run-measure-rtlsim-$tag" \
  --trace-simx "$run-trace-simx-$tag" --trace-rtlsim "$run-trace-rtlsim-$tag" --output "$run-review-$tag"
```
