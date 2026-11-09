# A/B D4：原生 u32 边界与 AFU 集成回归

日期：2026-11-08，Asia/Shanghai。用户恢复推进 A/B。固定源码、工具包、硬件配置和 draft-v3 lock/caps 不变；本轮增加上游目录之外的 native 测试程序，未实现或修改项目 PTX 前端、P0 ABI 与白名单。

本轮三路原生 u32 回归均 PASS：SimX、处理器 RTL、NOXRT AFU 模型各 140/140 次启动，实际命令均退出 0。三路程序、测试语料和全部捕获字节一致；[收尾核验](../results/ab-d4-closeout-20261108-v1/result.json) 的 51 项证据完整性检查通过。整体项目仍为 PARTIAL，物理 U280 继续 BLOCKED。

## 本轮范围

从上轮上游 signed-int demo 推进到 copy/vadd/affine 的原生 u32 回归。测试实现和 Python reference 均由同一实施者编写，因此仅作为 A/B 自测，不计作 C/E 独立接收。程序、测试定义和复跑约束见 [native/boundary](../native/boundary/README.md)。

70 个参数用例 × 两次不同输入 = 每个 backend 140 次 launch。覆盖 N=0/1/7/31/32/33/63/64/65/257/1024、u32 极值与溢出、affine alpha=0/1/最大值、非零 buffer offset、输入不变、前后哨兵、尾线程、全假与交替条件、同一 queue/module/buffer 连续复用。每个逻辑线程额外记录 block/thread/grid/block-size，N=0 仍实际启动。

完整 N/alpha 矩阵使用 B=16，另在 N=33 测 B=1/4/7。固定 `queue.cpp` 明确限制原生 block 不超过 threads×warps=16；本轮对 B=32 执行负例，期望 `VX_ERR_INVALID_VALUE`。这不是将 P0 默认 B=32 改成 B=16，也不是接收一个新的 P0 配置。后续仍须由 A/C/D 明确采用新配置或经验证的逻辑线程适配，升版后另行接收。

## 运行与证据

| 层次 | 当前结果 | 证据 |
|---|---|---|
| Linux 运行器自测 | PASS，23 通过 / 1 跳过 | 最终日志与退出码（本地记录 `results/ab-d4-final-linux-tests-20261108-v1/summary.json`）；增加边界阶段状态隔离检查，只验证脚本行为 |
| Windows 运行器自测 | PASS，18 通过 / 5 跳过 | 日志与退出码（本地记录 `results/ab-d4-windows-tests-20261108-v1/summary.json`）；先前沙箱临时目录权限错误单列 |
| SimX 原生 u32 | PASS，140/140 | 本轮 summary（本地记录 `results/ab-d4-simx-20261108-v1/summary.json`）、逐项比较（本地记录 `results/ab-d4-simx-20261108-v1/boundary/comparison.json`）；执行退出 0 |
| 处理器 RTL 原生 u32 | PASS，140/140 | 本轮 summary（本地记录 `results/ab-d4-rtlsim-20261108-v1/summary.json`）、逐项比较（本地记录 `results/ab-d4-rtlsim-20261108-v1/boundary/comparison.json`）；执行退出 0 |
| NOXRT AFU 模型原生 u32 | PASS，140/140 | 本轮 summary（本地记录 `results/ab-d4-xrtsim-20261108-v1/summary.json`）、逐项比较（本地记录 `results/ab-d4-xrtsim-20261108-v1/boundary/comparison.json`）；执行退出 0 |
| 物理 U280 | BLOCKED | 无分配账号/设备访问；FPGA 构建和板上运行 NOT_RUN |

每轮先在全新 build/run 目录跑同配置上游 demo，再编译和执行新测试。运行器 schema 升为 5，`upstream_smoke`/`demo_execution` 与 `native_boundary` 分开；前者通过不能替代后者。`--native-boundary` 是本地测试入口，不是项目 runtime API 扩展。

本轮还修正了可选边界阶段的中间状态：demo 完成后，在边界阶段结束前保持整体 RUNNING。此修改不影响构建参数或测试执行；三路已启动运行的脚本副本及交付版本哈希保存在 修订记录（本地记录 `results/ab-d4-closeout-20261108-v1/runner-revision.json`），新状态行为已在最终 Linux 自测中检查。

每轮 `boundary/inputs`、`expected`、`corpus.json` 在执行前生成并保存哈希；host/device 不读取 expected。`actual` 保存四个 buffer 的完整实际读回，`comparison.json` 逐 byte 比较并验证输入/答案没有改动。`source/` 和生成器副本保存本轮测试身份，`artifacts/` 保存编译产物和反汇编。

三路 `kernel.vxbin` SHA-256 均为 `19b5aeddbaf2a0d664295a7b0811b1fba9999aa73c0ee157994766db799f8505`，corpus SHA-256 均为 `9c099d8e97b7dee1177c4f5dfc7c59a3be51d6e35ba2870bff2fd3e18ed229e7`。本轮执行与当前 lock 均为 `924b17abadbbda710ead2053ac0873fb0698161c983f8ff1feb9b96a16a19ffe`；未修改 lock/caps 或将其冻结。三路相同结果不表示时序等价。

## 复跑

在专用 `Vortex-AB-Ubuntu-22.04`，项目根 `/mnt/d/Vortex-U280` 中执行；NEW 必须替换成从未使用的名称：

```bash
python3 -B scripts/run_native_smoke.py --backend simx --native-boundary \
  --source /opt/vortex-ab/sources/vortex-7fe19369587c-v1 \
  --tooldir /opt/vortex-ab/toolchains/8c64cf921d3c6c456e80f00d24482d0aa2153a82-rtlsim-d3-v1 \
  --ramulator-deps results/ab-d2-ramulator-deps-20261108-v1/dependencies \
  --build-dir /opt/vortex-ab/builds/ab-native-NEW \
  --run-id ab-native-NEW --jobs 4 --timeout 1800
```

处理器 RTL 改为 `--backend rtlsim`；AFU 模型改为 `--backend xrtsim`，每路另选新目录。AFU 所有 make 强制 `TARGET=xrtsim`；不使用真实 XRT、Vitis hw_emu、shell 或板卡。

## 仍待完成

输出哨兵和线程记录不能证明假条件完全没有读内存，也不能检测同一线程重复写入相同值；还需 trace/访问计数等观察与 E 独立验收。没有安全中止、恢复、高位设备 buffer 地址、shared/barrier、浮点 RTL、P0 转换或性能结论。

B 的物理平台工作继续等待账号、分配卡和操作范围，按 [接收单](U280_ACCESS_CHECKLIST.md) 盘点。无新访问授权，未远程登录或修改设备配置；本地 AFU 模型通过也不能替代 HOST[0]/HBM/PCIe 与真实 XRT 验收。

## 交给 C/D/E 的接收事项

| 接收方 | 可直接使用的材料 | 尚需接收的边界 |
|---|---|---|
| C | 固定 lock、三路运行入口、原生程序/反汇编、参数与输入输出副本 | 这是私有 native 测试结构；需实现项目参数 packer、module 校验和 runtime 生命周期契约 |
| D | u32 原生算术与条件程序、线程索引记录、B=32 原生拒绝事实 | 不能据此宣布 PTX 白名单支持；与 A/C 选择 B=32 硬件候选或逻辑线程适配方案后独立升版接收 |
| E | 运行前的输入与 reference、实际四个 buffer、逐项比较、命令/退出码 | 用独立答案在新目录复跑；补假谓词无读访问、拒绝和未初始化语义观察；本轮参数用例不能充当 30 个 PTX 语义/拒绝用例 |
