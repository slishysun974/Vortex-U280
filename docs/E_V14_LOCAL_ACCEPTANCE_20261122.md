# PTX 前端 v1.4 本地独立验收

**限定范围接收 PASS。** 本次接收在独立于生产实现会话的本地验收上下文完成。固定 D5 的 SimX、处理器 RTL、NOXRT AFU 各通过 24 组新输入和 13 组冻结 V03，各有 5 次额外调试回放。接收对象为 RV64、1 core、8 warp、4 thread 的对齐参数入口，以及显式选择的 `same-predicate-v1`。物理 U280 本轮 `NOT_RUN`，人类签收待办。[最终接收回执](../results/e-v14-review-20261122-v1/result.json)

## 编译和答案的来源

从固定 WSL 工具链在新目录执行正式 `prepare/build/validate`，重建 copy、vadd、affine 和两份 V03 模块。五份设备镜像的 SHA-256 与交付原件逐份一致。实际生成器为 `ptx-vx-frontend-v1.4`，源码 SHA-256 为 `3c7aa9b172473f2a0567093dfcf17e8f16b0befa968a701427d8b225b328a29f`。固定上游提交核对通过，跟踪文件差异检查退出 0。根 lock 和实际使用的 D5 lock 分别记录在回执中。[重建命令与五份镜像身份](../results/local-ptx-same-predicate-production-build-e-20261122-v1/summary.json) · [源码、lock 与模型命令](../results/e-v14-local-20261122-v1/summary.json)

验收方从三种算子的数学定义和新见证的逐线程行为计算答案。参考程序仅用 Python 标准库。在运行模型前封存四份 PTX、24 组输入、完整输出及前后哨兵。每个程序覆盖 6 种几何，block 取 1、3、7、16、31、32，活跃元素数包含 0、1、整块及不整除的尾部。输入包含无符号回绕和高位值，各数组使用不同起始偏移。[冻结回执](../results/e-v14-frozen-20261122-v1/freeze.json) · [独立参考程序](../experiments/e-v14-local/freeze.py)

新见证 `predicate_turn` 先按 `i < n` 选择从 x 读后加一，或从 y 读后减一，再把结果写入 z。随后原谓词寄存器按 CTA 内的线程号重新赋值，选中线程从 z 读回、累加并再写入。接收脚本核对三段源码映射、生成条件的极性及段内 load/store 顺序。这是本轮新编译的第六份模块。[PTX 见证](../experiments/e-v14-local/predicate_turn.ptx) · [三段生成行与运行回执](../results/e-v14-local-20261122-v1/summary.json)

## 执行层级

| 层级 | 新输入 | 已冻结 V03 | 逐 lane 调试回放 |
|---|---:|---:|---:|
| SimX | 24/24 | 13/13 | 5/5，48 条数组请求 |
| 处理器 RTL | 24/24 | 13/13 | 5/5，48 条数组请求 |
| NOXRT AFU | 24/24 | 13/13 | 5/5，48 条数组请求 |
| 物理 U280 | NOT_RUN | NOT_RUN | NOT_RUN |

正常执行走固定 binding 的 `Context.load/launch/wait`。每路离线复核 210 份运行前后完整数组、4 份高低地址别名读回、37 份原始启动参数和 37 个完成事件。13 组 V03 中有 5 个 4 GiB 专项用例。Python 运行器另行在固定 WSL 执行 316 项，314 项通过、2 项跳过，退出 0。[三路原始回执](../results/e-v14-local-20261122-v1/summary.json) · [离线复核](../results/e-v14-review-20261122-v1/result.json) · [运行器日志（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-816fae1f7676)

调试回放使用同一批已验证镜像，在单 warp/CTA 的小规模样例上，按 CTA、lane、数组、完整地址及读写顺序逐项比对缓存合并前的 LSU 记录。每路的全假 copy 为 0 条，只有一个有效元素的 copy、vadd、affine 分别为 2、3、3 条，新见证为 40 条。观测窗口覆盖各数组的完整分配，包含哨兵。固定 U280 的逐 lane 可观测性限制仍适用。[逐 lane 日志和结果](../results/e-v14-trace-20261122-v1/summary.json) · [U280 可观测性](PTX_U280_TAIL_OBSERVABILITY_20261122.md)

## 本地复现

在 `Vortex-AB-Ubuntu-22.04` 的项目根目录执行，选取新的 `tag`。验收入口会核对本轮冻结语料的完整清单。独立重算答案可以在新的输出目录另行执行 `freeze.py`。[冻结清单](../results/e-v14-frozen-20261122-v1/manifest.json)

```sh
tag=NEW
b=results/local-ptx-same-predicate-production-build-$tag
m=results/e-v14-local-$tag
t=results/e-v14-trace-$tag
python3 -B experiments/ptx-same-predicate-production/build.py --output "$b"
python3 -B experiments/e-v14-local/accept.py "$m" "$b"
python3 -B experiments/e-v14-local/trace_local.py "$t" "$m" "$b"
python3 -I -B experiments/e-v14-local/review.py "results/e-v14-review-$tag" "$b" "$m" "$t"
```

下一步若扩大物理接收范围，需要为新见证单独评审 U280 对齐模块的准入范围。当前实卡准入绑定六份既有镜像。[物理装载契约](PTX_U280_ALIGNED_LOAD_20261122.md)
