# PTX 设备参数读取契约

`vortex2-queue-args-align-v1` 是可显式选择的设备参数读取约定。默认模块和独立前端使用逐字节读取。对齐模块使用 `ptx-vx-frontend-v1.3` 或启用同谓词合并的 `ptx-vx-frontend-v1.4`，模块格式为 `ptx-vx-module-queue-aligned-v1-draft`。`ptx-vx-args-v1` 规定参数字节布局、字段类型和填充，同一份 launch payload 可用于两种模块。[模块选项](../scripts/ptx_module.py) · [设备参数读法](../scripts/ptx_frontend_v13.py)

## 对齐模块的适用范围

| 条件 | 约定 |
|---|---|
| 构建目标 | 固定 `configs/candidates/block32-v1/target_lock.json` 和对应的 RV64 小端硬件定义。 |
| runtime | 接收清单第 2 版包含已核验的 D5 SimX、处理器 RTL 和固定 NOXRT AFU binding。校验整个 binding、实际加载的库及其依赖。加载对齐模块时要求 VM 关闭。 |
| 启动路径 | 由 `Context.launch` 把非空的 host payload 交给 `vx_enqueue_launch`，payload 大小在 1–4,096 字节内。 |
| 设备基址 | 固定 runtime 将 payload 暂存到至少 64 字节对齐的槽。槽地址通过 KMU 和 `MSCRATCH` 交给设备入口。 |
| 字段 | `.u32` 字段为 4 字节大小和对齐，`.u64` 字段为 8 字节大小和对齐。生成前检查自然对齐和字段范围。 |

在设备端，v1.3 将原来的逐字节拼接替换为读取固定长度的 `__builtin_memcpy`，并把已保证的对齐传给编译器。模块校验以 PTX 源重新生成语义体和源码映射，检查模块、前端和编译记录三处的约定一致。默认逐字节路径适用于 host 语义检查、其他目标和旧归档。未经核验的 runtime 需要加载逐字节版，提交对齐模块时会在装载前收到 `E_TARGET_MISMATCH`。[运行时检查](../scripts/ptx_runtime.py) · [暂存与设备入口依据](PTX_ALIGNED_PARAMETERS_20261121.md#对齐依据) · [固定 NOXRT AFU 接收](PTX_SAME_PREDICATE_AFU_20261121.md)

## 选择对齐版

固定 U280 的三算子配对使用独立格式 `ptx-vx-module-u280-queue-aligned-v1-draft`，准备时显式指定 `--u280-aligned`。正式装载要求当次 D10/D12 context 的原始 CP 读值、VM 查询和逐字节暂存探针通过。固定六份镜像已在 U280 通过 12 次探针与 420 次配对启动。[U280 装载门禁与配对入口](PTX_U280_ALIGNED_LOAD_20261122.md) · [实卡证据](PTX_U280_ALIGNED_BOARD_20261122.md)

在配置好的 WSL 环境，通过正式模块入口选择新约定，然后沿用 `ptx_module.py build`、`ptx_module.py validate` 和 `Context.load/launch`。从同一 PTX 准备逐字节版时，省略 `--device-parameter-access`。

```sh
python3 -B scripts/ptx_module.py prepare ptx/samples/vadd_u32.ptx \
  --output results/vadd-aligned-new \
  --target-lock configs/candidates/block32-v1/target_lock.json \
  --hardware configs/candidates/block32-v1/native_smoke.json \
  --device-parameter-access vortex2-queue-args-align-v1
```

对齐版还可显式选择 `--predicate-lowering same-predicate-v1`，由 `ptx-vx-frontend-v1.4` 生成同谓词片段。该字段进入前端清单、模块清单和构建回执，校验时从 PTX 重生语义体和逐指令源码映射。省略该选项时使用原 v1.3 对齐生成路径。适用目标及装载条件沿用本页的 D5 约定。[同谓词规则与回归](PTX_SAME_PREDICATE_PRODUCTION_20261121.md)

## 2026-11-21 本地接收结果

- **对齐版 P0 回归。** SimX、处理器 RTL 各通过 copy 168、vadd 168、affine 504 个既有用例。每路另有 57 个提交或状态拒绝检查、3 个超时排空与后续运行检查通过。两路再各通过 13 个封存 V03 用例，覆盖 8 个普通地址、5 个含 4 GiB 地址的用例及别名检查。[SimX](../results/local-ptx-aligned-production-simx-20261121-v1/summary.json) · [处理器 RTL](../results/local-ptx-aligned-production-rtlsim-20261121-v1/summary.json)
- **逐字节版及拒绝路径。** 原有 P0 指令见证在 SimX、处理器 RTL、NOXRT AFU 各 2/2，17 项指令拒绝和 12 个归档模块校验通过。显式要求在 U280 target 上准备对齐模块时，主机预检以 `E_TARGET_MISMATCH` 拒绝。Python 自测 294 项通过、1 项 Windows 专用项跳过，退出 0。[原 P0 回归](../results/d-p0-forms-queue-aligned-20261121-v1/summary.json) · [U280 target 负例（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-5808d4f1ce4b) · [宿主自测](../results/local-ptx-aligned-production-host-20261121-v1/summary.json)
- **正式入口性能复测。** 五个对齐模块均由正式工具链入口构建和校验，三个性能镜像与隔离实验的对齐镜像逐字节相同。两模型使用 `Context.load/launch/wait`，复用两个规模的归档输入，每种算子与规模各四对并交替顺序。48 对都节省周期，共 96 次完整输出和哨兵通过。两模型及两轮实验的退休数逐项一致。RTL 的部分大规模启动触发驱动等待提示，最终均退出 0。所有性能数字来自本地模型，U280 执行为 `NOT_RUN`。[构建回执](../results/local-ptx-aligned-production-build-20261121-v1/summary.json) · [配对复核](../results/local-ptx-aligned-production-review-20261121-v1/summary.json)

表中为逐字节版 → 对齐版，周期按各版本四次启动取中位数。两路 `MINSTRET` 均按完成的 warp 指令计数。

| 算子 | 元素数 | SimX 周期（降幅） | 处理器 RTL 周期（降幅） | 退休 warp 指令（降幅） |
|---|---:|---:|---:|---:|
| copy | 1,024 | 31,654 → 12,774（59.64%） | 35,311 → 13,120（62.84%） | 20,800 → 7,744（62.77%） |
| copy | 16,381 | 493,162 → 198,175（59.82%） | 553,859 → 207,229（62.58%） | 331,845 → 122,949（62.95%） |
| vadd | 1,024 | 42,183 → 15,833.5（62.46%） | 46,205 → 16,123.5（65.10%） | 27,968 → 9,536（65.90%） |
| vadd | 16,381 | 661,400 → 245,628（62.86%） | 741,939 → 254,934（65.64%） | 446,536 → 151,624（66.04%） |
| affine | 1,024 | 46,861 → 16,418（64.96%） | 50,167.5 → 16,868（66.38%） | 30,784 → 10,048（67.36%） |
| affine | 16,381 | 731,451.5 → 255,543.5（65.06%） | 856,301 → 265,226（69.03%） | 491,593 → 159,816（67.49%） |

## 回归复现

使用项目固定 WSL 和新的 run_id。验证脚本构建三个性能 kernel 和两份冻结 V03 探针，验证阶段先运行现有 P0 算子回归与冻结用例，再交替运行逐字节和对齐版本。最后一条也可在 Windows 执行。

```sh
python3 -B scripts/run_d_p0_closeout.py --run-id d-p0-forms-queue-aligned-new
python3 -B experiments/ptx-aligned-production/validate.py build --output results/local-ptx-aligned-production-build-new
python3 -B experiments/ptx-aligned-production/validate.py model --backend simx \
  --build results/local-ptx-aligned-production-build-new --output results/local-ptx-aligned-production-simx-new
python3 -B experiments/ptx-aligned-production/validate.py model --backend rtlsim \
  --build results/local-ptx-aligned-production-build-new --output results/local-ptx-aligned-production-rtlsim-new
python3 -B experiments/ptx-aligned-production/validate.py review \
  --build results/local-ptx-aligned-production-build-new \
  --simx results/local-ptx-aligned-production-simx-new --rtlsim results/local-ptx-aligned-production-rtlsim-new \
  --output results/local-ptx-aligned-production-review-new
```
