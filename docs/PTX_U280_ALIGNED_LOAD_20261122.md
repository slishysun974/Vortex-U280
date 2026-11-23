# U280 对齐模块的物理装载门禁与配对入口

同日的实卡执行已另行归档，包含 CP 原值、12 次探针、420 次启动及分阶段结果。[实卡证据](PTX_U280_ALIGNED_BOARD_20261122.md)

物理对齐格式为 `ptx-vx-module-u280-queue-aligned-v1-draft`，接收版本为 `u280-d10-d12-staging-v1`。当前接收范围是固定 D10 xclbin、D12 两库、U280 lock 以及 `copy`、`vadd`、`affine` 的六份已固定源码和镜像。三份使用 v1.3 对齐读取，三份使用 v1.4 同谓词合并。两路同用 `ptx-vx-args-v1`。离线校验只确认模块身份和完整性，实卡仍需同一次 context 和同一队列的观测。[格式与构建入口](../scripts/ptx_module.py) · [配对入口](../scripts/u280_aligned_pair.py)

## 放行条件

1. `BoardGate` 核对原有锁定条件，包括 xclbin、D12 两库、BDF/index、shell、HOST、当次空闲、装载 UUID、实际 200 MHz 和设备几何。正式 loader 和装载前探针复用同一个物理 context。
2. 物理捕获进程观察 D12 在 `vx_device_open` 期间调用的 `xrt::ip::read_register(0x1008)`。观测器原样返回 XRT 读值。固定源码的 CP 译码为 `0x00061001`，要求恰有一次有效的原值，且当前 context 的 `VX_CAPS_VM_SUPPORT` 调用成功并返回 0。缺失、重复、全 1 及其他值均拒绝。全 1 即使在 D12 内回退为 VM 关闭，仍会在任何探针和候选镜像装载前被拒绝。[原值观测器](../native/u280_cp_caps_observer.cpp) · [D10 CP 译码（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-cccb144b8a7f) · [CP 常量（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-d665d09e3f85)
3. 使用原 payload 和输入布局在同一队列连续跑每组两次逐字节探针，共 12 次。探针回报 `a0`、`MSCRATCH`、每个字段的设备地址和逐字节读值。核对基址非零且 64 字节对齐、字段地址为基址加 ABI 偏移、值与实际 payload 一致、完整读回中报告区域之外的字节一致。第二次启动使用不同的报告区初值并须复用第一次退休的槽地址。[设备探针](../native/u280_args_probe.cpp) · [放行校验](../scripts/ptx_u280_aligned.py)
4. 探针通过后，`Context.load` 在原生装载前验证模块身份和当次 context、设备、队列及 generation。队列更换或 context 关闭后须重新取得证据。落盘的 `alignment.json` 用于审计。任一条件失败时，候选镜像停止在原生 loader 之前。[运行时入口](../scripts/ptx_runtime.py)

## 配对执行

原离线包提供冻结输入、答案和顺序。正式执行使用 1,024 和 16,381 元素、block 32，沿用 5 对预热、30 对计时并交替先后，共 210 对、420 次计划启动。每次由正式 `Context.load/launch/wait` 执行并核对完整 `z` 和哨兵，保留逐次主机单调时钟的装载、上传、执行等待和回读时间。装载段包含模块校验，执行段包含提交和等待。通过门禁后才会创建配对样本。板端 `run` 入口需要已授权的设备窗口及明确 BDF，本轮仅运行下面的离线命令。[原始配对包](../results/u280-aligned-predicate-preflight-20261121-v1/bundle/plan.json)

```sh
python3 -B scripts/build_u280_aligned_pair.py --output results/u280-aligned-load-build-NEW
python3 -B scripts/u280_aligned_pair.py preflight \
  --bundle results/u280-aligned-predicate-preflight-20261121-v1/bundle \
  --compiled results/u280-aligned-load-build-NEW
python3 -B experiments/u280-aligned-load/verify.py \
  --bundle results/u280-aligned-predicate-preflight-20261121-v1/bundle \
  --compiled results/u280-aligned-load-build-NEW --output results/u280-aligned-load-review-NEW
```

授权后在板端项目目录可用 `scripts/u280_aligned_pair.py run`，沿用上述 `--bundle` 和 `--compiled` 参数，再提供 `--bdf` 与新的 `--output results/u280-aligned-…`。执行入口记录编译观测器、物理预检、运行和结果。板上 CP、VM、逐字节探针及全部配对执行本轮均为 `NOT_RUN`。`TIMING-7` 和物理故障恢复沿用既有限制。

## 离线证据

正式入口重建的六份镜像与前一轮离线配对镜像逐字节一致。首轮通用 WSL 的 Python 版本不支持已有前端，失败记录保留。使用固定 Vortex WSL 的新 run_id 重建成功，并构建了逐字节地址和值探针。[正式构建回执](../results/u280-aligned-load-build-20261122-v2/summary.json) · [首次构建记录](../results/u280-aligned-load-build-20261122-v1/summary.json)

最终离线回执的预检、自测和 SimX 三条命令均退出 0。项目自测 311 项通过、2 项跳过。拒绝用例覆盖全 1 回退、其他无效 CP 值、缺证据、VM 开启、基址对齐、`a0/MSCRATCH`、字段地址和值、字段覆盖及退休复用，另核对队列更换和哨兵错误。合成 transport 核对 420 次配对执行顺序。实际探针镜像在固定 SimX 上执行 12 次，各次读回 `a0 = MSCRATCH = 0x14000`，字段与复用均通过。[最终离线回执](../results/u280-aligned-load-review-20261122-v2/summary.json) · [SimX 逐字段记录](../results/u280-aligned-load-review-20261122-v2/simx-probe.json)
