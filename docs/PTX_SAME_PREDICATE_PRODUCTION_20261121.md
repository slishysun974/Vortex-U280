# 正式 PTX 前端的同谓词访存合并

固定 NOXRT AFU 的后续验证已完成，含参数暂存、完整回归和逐 lane 观测。[NOXRT AFU 结果](PTX_SAME_PREDICATE_AFU_20261121.md)

正式模块入口 `ptx_module.py prepare` 在固定 D5 对齐读取路径上接受 `--predicate-lowering same-predicate-v1`。生成器为 `ptx-vx-frontend-v1.4`。旧 v1.3 对齐生成路径仍可通过原参数选择，便于重现基线，默认逐字节模块沿用原入口。PTX 白名单及参数读取 ABI 沿用原契约。[模块入口](../scripts/ptx_module.py) · [生成规则](../scripts/ptx_frontend_v14.py) · [设备参数契约](PTX_DEVICE_PARAMETER_ACCESS.md)

生成器以已校验的 P0 IR 和原逐指令源码映射为依据。只有连续、谓词寄存器和正反极性完全相同的受支持语句才能进入一个条件块。无谓词语句、不同谓词或极性以及任何谓词写入都是片段边界。片段至少两条语句并包含全局访存。各语句按原顺序生成，`volatile` 数组 load/store 仍为各自的完整语句。每条 PTX 指令继续映射到自己的生成行。模块、前端和构建回执一致记录 lowering 版本，装载前会验证从源码重生的语义体和映射。[实现](../scripts/ptx_frontend_v14.py) · [边界与版本测试](../tests/test_ptx_module.py)

固定工具链通过正式 `prepare`、`build`、`validate` 生成三个算子和两份 V03 模块。三个算子的生成体和镜像逐字节复现实验变体。两份冻结 V03 探针生成的镜像各自与正式 v1.3 基线相同，并在两个模型重新执行。常规回归和性能计数走 `Context.load/launch/wait`。独立 DEBUG3 捕获在经核对的非 VM D6 库中回放通过正式校验的镜像字节，使用相同队列参数契约。正常装载的固定 D5 binding 范围沿用对齐读取约定。[构建、命令与镜像身份](../results/local-ptx-same-predicate-production-build-20261121-v1/summary.json)

## P0 和 V03

| 每个后端的检查 | SimX | 处理器 RTL |
|---|---:|---:|
| P0 copy、vadd、affine | 168 / 168 / 504 通过 | 168 / 168 / 504 通过 |
| P0 运行时拒绝和超时恢复 | 57 项拒绝、3 项恢复通过 | 57 项拒绝、3 项恢复通过 |
| P0 指令形式见证 | 2 次完整启动、17 项源级拒绝通过 | 2 次完整启动、17 项源级拒绝通过 |
| 冻结 V03 | 13/13，含 5 个 4 GiB 用例及别名读回 | 13/13，含 5 个 4 GiB 用例及别名读回 |

V03 复核每路回读 39 份运行前数组、39 份运行后数组和 13 份参数，同时校验固定地址及完成事件。两个模型的命令、输出和子命令退出码见回执。[SimX](../results/local-ptx-same-predicate-production-simx-20261121-v1/summary.json) · [处理器 RTL](../results/local-ptx-same-predicate-production-rtlsim-20261121-v1/summary.json)

Python 运行器自测 296 项通过、1 项跳过，12 个旧归档模块通过离线校验。主机复核入口首次启动时导入了另一实验的同名文件，修正导入路径后在新目录重跑通过。[首次启动记录](../results/local-ptx-same-predicate-production-host-20261121-v1/summary.json) · [重跑回执](../results/local-ptx-same-predicate-production-host-20261121-v2/summary.json)

## 原输入的周期和退休数

使用原冻结的 1,024 和 16,381 元素输入、答案及哨兵，block 为 32。对每个算子和规模重跑四对 v1.3 对齐基线和正式 v1.4 变体，交替执行顺序。两个模型共 48 对、96 次启动，所有读回的输入、完整输出及哨兵均匹配，48 对均减少周期。周期按四次启动取中位数，退休 warp 指令数在重复之间及模型之间一致。[配对复核](../results/local-ptx-same-predicate-production-review-20261121-v1/summary.json)

| 算子 | 元素数 | SimX 周期（降幅） | 处理器 RTL 周期（降幅） | 退休 warp 指令（降幅） |
|---|---:|---:|---:|---:|
| copy | 1,024 | 12,774 → 11,807（7.57%） | 13,116 → 11,882（9.41%） | 7,744 → 6,976（9.92%） |
| copy | 16,381 | 198,431 → 182,321（8.12%） | 205,245.5 → 184,967（9.88%） | 122,949 → 110,658（10.00%） |
| vadd | 1,024 | 15,819 → 13,064（17.42%） | 16,099 → 13,055（18.91%） | 9,536 → 8,000（16.11%） |
| vadd | 16,381 | 245,473 → 205,412.5（16.32%） | 254,594 → 208,216（18.22%） | 151,624 → 127,042（16.21%） |
| affine | 1,024 | 16,418 → 13,695.5（16.58%） | 16,865.5 → 13,759（18.42%） | 10,048 → 8,512（15.29%） |
| affine | 16,381 | 255,690 → 218,574（14.52%） | 264,907 → 219,673（17.08%） | 159,816 → 135,234（15.38%） |

## 尾部假谓词

两路 DEBUG3 各回放 12 次，逐逻辑线程核对 278,480 条数组请求的地址、读写方向和顺序。1,024 元素用例验证四个 lane 都活跃。16,381 元素用例的最后一个 warp 中，lane 0 完成预期数组访问，归一化掩码为 `1000`。lane 1–3 在三个算子和两个版本中均为零次数组读写请求。离线复核分别向 SimX load 和 RTL store 的日志副本注入一个假 lane，检查器均报告索引 16,381。请求采集点在 LSU、缓存合并之前。NOXRT AFU 和 U280 本轮为 `NOT_RUN`。[SimX 原始捕获索引](../results/local-ptx-same-predicate-production-trace-simx-20261121-v1/summary.json) · [RTL 原始捕获索引](../results/local-ptx-same-predicate-production-trace-rtlsim-20261121-v1/summary.json) · [复核记录](../results/local-ptx-same-predicate-production-review-20261121-v1/summary.json)

## 复现

在 `Vortex-AB-Ubuntu-22.04` WSL 的 `/mnt/d/Vortex-U280` 运行。每次选新的 `tag`。`--jobs` 只控制独立 DEBUG3 回放的并发数量。

```sh
tag=NEW
run=results/local-ptx-same-predicate-production
exp=experiments/ptx-same-predicate-production
python3 -B "$exp/build.py" --output "$run-build-$tag"
python3 -B "$exp/check.py" host --output "$run-host-$tag"
for backend in simx rtlsim; do
  python3 -B "$exp/model.py" --build "$run-build-$tag" --backend "$backend" --output "$run-$backend-$tag"
  python3 -B "$exp/lsu.py" --build "$run-build-$tag" --backend "$backend" --output "$run-trace-$backend-$tag"
done
python3 -B "$exp/check.py" review --build "$run-build-$tag" --host "$run-host-$tag" \
  --simx "$run-simx-$tag" --rtlsim "$run-rtlsim-$tag" \
  --trace-simx "$run-trace-simx-$tag" --trace-rtlsim "$run-trace-rtlsim-$tag" --output "$run-review-$tag"
```

单独构建一个算子时，在原对齐 `prepare` 命令的 `--device-parameter-access vortex2-queue-args-align-v1` 之后加 `--predicate-lowering same-predicate-v1`，再按同一 lock 构建和校验。[原对齐命令](PTX_DEVICE_PARAMETER_ACCESS.md#选择对齐版)
