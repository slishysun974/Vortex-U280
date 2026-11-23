# 2026-11-21 PTX 三算子性能归因

**参数解码是三算子当前 PTX 路径的主要额外开销。** 对比归档 `kernel_main`，PTX 逐字节读取参数，再用移位和 OR 恢复字段。对全活跃 warp，参数加载和拼接解释了 **91.14%–92.73%** 的新增退休指令。处理器 RTL 的总周期为原生的 **3.06–3.98 倍**，平均每条退休指令的周期为原生的 **0.983–1.062 倍**。本地周期差主要随执行指令总量增长。[机器复核](../results/local-ptx-perf-attribution-20261121-v2/result.json)

## 同输入周期与动态指令

复用 11 月 21 日板测包内的输入和答案，以及同批归档的六个设备镜像。对比反汇编时，把每条 `kernel_main` 指令的 PC 和编码与 vxbin 内实际字节核对，模型版和板用版的镜像 SHA-256 与指令序列一致。模型使用固定 D5 绑定的 RV64、1 核 × 8 warp × 4 lane，block 为 32，两个规模分别启动 32 和 512 个 CTA。每模型、算子、规模各跑两对，第二对反转原生和 PTX 顺序。同一对共用缓冲区和参数布局，每次重传输入和输出哨兵。两模型各 24 次、共 48 次完整输出对照通过。两个采集入口与离线复核均退出 0。[SimX 命令、日志及退出码](../results/local-ptx-perf-simx-20261121-v1/summary.json) · [处理器 RTL 命令、日志及退出码](../results/local-ptx-perf-rtlsim-20261121-v1/summary.json)

表中均为**原生 / PTX**。周期是两次样本的中位数。每模型在事件前后读取 `MCYCLE` 和 `MINSTRET`，两次连续空闲快照相等，读回位于计数窗口之后。退休按完成的 warp 指令计数，两模型及两次重复的退休数逐项相同。周期的单次值、范围和额外计数保存在原始样本中。[SimX 样本（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-053378e73ece) · [RTL 样本（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-508be2f8a1c1)

| 算子 | 元素 | 退休 warp 指令 | SimX 周期 | 处理器 RTL 周期 |
|---|---:|---:|---:|---:|
| copy | 1,024 | 6,720 / 20,800 | 11,444.5 / 31,641.5 | 11,459 / 35,110 |
| copy | 16,381 | 106,562 / 331,845 | 174,044 / 493,445 | 177,763 / 553,860.5 |
| vadd | 1,024 | 7,744 / 27,968 | 12,757.5 / 42,180.5 | 12,710 / 47,099 |
| vadd | 16,381 | 122,946 / 446,536 | 199,990 / 661,400 | 206,011 / 735,229 |
| affine | 1,024 | 8,256 / 30,784 | 13,302 / 46,853 | 13,272.5 / 49,650 |
| affine | 16,381 | 131,138 / 491,593 | 211,770 / 732,329.5 | 216,548 / 862,258 |

## 指令差额来自哪里

原生路径用 `ld` / `lw` 读参数字段。PTX 生成的 `ptx_read32/64` 使用无对齐保证的 `uint8_t*`，在固定工具链的 `-O3` 下展开为 `lbu`、移位和 OR。三个 PTX 产物分别出现 20、28、32 条 `lbu`。原生的一组 `split/branch/join` 在 PTX 中分别变成 2、3、3 组。每个 PTX 产物还多一条写栈的 `sd`。这三类合计覆盖三个算子全部静态指令差额。[前端生成逻辑](../scripts/ptx_frontend_v12.py#L415) · [逐 PC 分类](../results/local-ptx-perf-attribution-20261121-v2/result.json)

| 算子 | `kernel_main` 原生 / PTX | 新增参数加载 | 新增参数拼接 | 新增谓词控制 | 新增写栈 | 参数解码占新增指令 |
|---|---:|---:|---:|---:|---:|---:|
| copy | 21 / 76 | 17 | 34 | 3 | 1 | 92.73% |
| vadd | 25 / 104 | 24 | 48 | 6 | 1 | 91.14% |
| affine | 27 / 115 | 27 | 54 | 6 | 1 | 92.05% |

- 1,024 元素全部 warp 活跃。静态差额乘以 256，正好等于两模型的动态退休差额。16,381 元素最后一个 warp 含 3 个无效 lane，按全部 4,096 个 warp 活跃估算后，与实测差额仅差 3、6、7 条。逐 PC 分类给出指令数归因，尚未测量各类指令独立造成的周期增量。
- 对两种规模，SimX 的 PTX 退休量为原生的 3.10–3.75 倍，周期为 2.76–3.52 倍。额外的 LSU 请求也符合反汇编。以 1,024 元素为例，SimX 的 load 计数分别从 4,096、6,144、7,168 增到 21,504、30,720、34,816。三算子数组访存的指令数一致，PTX 另有参数字节读和写栈。固定 RTL 库的扩展 MPM 读数均为零，本轮 RTL 比较仅采用基础周期与退休计数。[两路原始计数](../results/local-ptx-perf-attribution-20261121-v2/result.json)
- 这为先前 U280 的执行等待差提供了设备代码层面的解释。原板测的 CP 事件采用主机时钟并包含完成轮询，本轮的 SimX/RTL 核心周期与 U280 时间各有自己的测量口径。U280 的设备周期、按因素拆分的耗时和优化收益仍待测量。[既有 U280 配对结果](../results/u280-perf-three-operators-20261121-v2/result.json)

## 本地复现

前两条在项目已配置的 `Vortex-AB-Ubuntu-22.04` WSL 环境从项目根目录执行。离线复核可在 Windows 或 WSL 执行。所有输出路径需使用新的运行标识。首轮 Windows 离线复核因路径分隔符与归档清单不匹配退出 1，修正后在新目录复核同一批原始采集。[首轮失败记录（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-78a1d7dfcdf3)

最大规模的首轮 vadd PTX 在两模型中均触发驱动的 10 秒等待提示，随后完成输出校验。宿主运行器自测在 WSL 退出 0，291 项通过、2 项跳过，分别是 Windows 专用项和本次未提供 `VORTEX_SOURCE` 的原生头文件 ABI 检查。[宿主自测记录（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-a9d7ead3f29b)

```sh
python3 -B experiments/ptx-performance-attribution/measure.py --backend simx --output results/local-ptx-perf-simx-NEW
python3 -B experiments/ptx-performance-attribution/measure.py --backend rtlsim --output results/local-ptx-perf-rtlsim-NEW
mkdir results/local-ptx-perf-attribution-NEW
python3 -B experiments/ptx-performance-attribution/analyze.py \
  --simx results/local-ptx-perf-simx-NEW --rtlsim results/local-ptx-perf-rtlsim-NEW \
  --output results/local-ptx-perf-attribution-NEW/result.json
```

后续已核对设备端 payload 基址和字段对齐，并单独替换参数读取方式复测同一套输入。[对齐单变量实验](PTX_ALIGNED_PARAMETERS_20261121.md)
