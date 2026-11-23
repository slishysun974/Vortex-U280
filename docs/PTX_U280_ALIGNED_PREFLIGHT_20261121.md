# U280 正式 v1.4 同谓词模块的离线上板准备

本轮复核固定 D10 xclbin、D12 两库和参数暂存路径，按固定 U280 lock 重建三算子的配对候选。配对使用 v1.3 对齐基线与 v1.4 同谓词合并版，两路共用同一对齐读取和参数 ABI。离线构建与打包 `PASS`，物理对齐装载仍 `BLOCKED`，设备执行 `NOT_RUN`。[打包回执](../results/u280-aligned-predicate-preflight-20261121-v1/summary.json) · [配对包（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-01d57f652896)

## D10/D12 的确认范围

- **身份和构建。** D10 xclbin 的 SHA-256、UUID、固定 U280 lock、输入清单及返回的 RTL 原件匹配。D12 两库哈希匹配固定物理绑定，`libvortex-xrt.so` 的 ELF 依赖为物理 XRT。两条宿主构建命令均为 `TARGET=hw`，记录 `VX_CFG_VM_ENABLED=0`。D12 的 GCC9 补丁只涉及两个 VM 文件和生成脚手架，选取的队列、分配器和 XRT 平台代码与固定检出逐字节相同。[离线身份记录](../results/u280-aligned-predicate-preflight-20261121-v1/bundle/offline-audit.json) · [D12 回执](../results/u280-runtime-20261109-v4/returned/runtime/result.json)
- **暂存路径。** 非空 `vx_enqueue_launch` 参数按字节复制到设备槽，经 `dev_write` 上传。1–4,096 字节使用同一规格的 4,096 字节槽。VM 关闭时，全局分配从 `0x10000` 起，使用 4,096 字节管理页及 64 字节块对齐。队列将槽地址拆到 `STARTUP_ARG0/1`，KMU 与启动代码经 `MSCRATCH` 交给入口 `a0`，在事件退休后回收原槽地址。HOST BO 为 CP 环和传输提供宿主通路，参数读取契约约束的是设备槽地址。[队列暂存](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/sw/runtime/common/queue.cpp#L411) · [分配器与槽池](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/sw/runtime/common/device.cpp#L121) · [入口指针](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/sw/kernel/src/vx_start.S#L124)
- **VM 的设备读回要求。** D10 输入的 CP RTL 在能力寄存器的高字节返回零，D12 在打开设备时读取该寄存器的 bit 24。D12 对全 1 的读回有显式无 VM 回退，运行库也保留了相应诊断。板测时必须先记录成功且有效的原始 `CP_DEV_CAPS`，其 XRT 偏移为 `0x1008`，再核对 `VX_CAPS_VM_SUPPORT=0` 和无回退日志。此轮仅确认静态配置、译码及软件路径。实卡读回为 `NOT_RUN`。[D10 CP 译码（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-cccb144b8a7f) · [D12 回退路径](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/sw/runtime/common/device.cpp#L328) · [打包的只读诊断源](../results/u280-aligned-predicate-preflight-20261121-v1/bundle/read_cp_caps.cpp)

## 字段与候选装载

| 算子 | payload 字节 | 8 字节指针字段偏移 | 4 字节标量字段偏移 |
|---|---:|---|---|
| copy | 24 | `x=0`、`z=8` | `n=16` |
| vadd | 32 | `x=0`、`y=8`、`z=16` | `n=24` |
| affine | 32 | `x=0`、`y=8`、`z=16` | `n=24`、`alpha=28` |

六份候选用官方 v1.3/v1.4 生成体、原源码映射和同一 wrapper，在隔离目录按 U280 lock 编译。每份 `vxbin` 与此前对应的 D5 执行镜像逐字节相同。另重建逐字节板用控制模块与独立地址探针，分别复现原归档镜像。正式入口拒绝在 U280 lock 生成对齐 v1.4，也拒绝拿 D5 模块对 U280 lock 做校验，两条命令均返回 `E_TARGET_MISMATCH`。六份离线候选采用单独的准备包版本，现有运行时的物理接收条件继续生效。[构建与负例命令](../results/u280-aligned-predicate-preflight-20261121-v1/summary.json) · [包清单](../results/u280-aligned-predicate-preflight-20261121-v1/bundle/plan.json)

后续授权窗口先满足现有 `BoardGate`，包括 D10/D12、当次 BDF/index、shell、HOST 容量、空闲、加载后 UUID 与实际 200 MHz。取得上述有效 VM 读回后，用包内逐字节探针回读实际 `a0` 与 `MSCRATCH`，核对槽基址、全部字段地址与回收重用。实卡证据通过后再接收物理对齐模块格式和装载门禁，然后接通正式配对执行。CP 诊断的 XRT 编译、六组地址探针和配对计时均待该窗口实际执行。物理恢复与 `TIMING-7` 仍按原范围处理。[包内门禁细节](../results/u280-aligned-predicate-preflight-20261121-v1/bundle/README.md)

## 包内容和复现

95 个归档文件包含六份候选镜像及其源与反汇编、逐字节地址探针、VM 与 BDF 诊断源码、锁定清单、离线验证器和原六组输入及答案。1,024 与 16,381 元素使用原 block 32 和完整哨兵。每算子与规模安排 5 对预热、30 对计时并交替先后，共 **210 对、420 次计划启动**。归档解包后可直接离线核对完整数组、哨兵、模块哈希和配对顺序。本轮没有 SSH、设备查询、装载或运行。[归档（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-01d57f652896) · [离线复核](../results/u280-aligned-predicate-review-20261121-v1/summary.json)

重新解包复核退出 0。修改临时副本的一个哨兵字节后，验证器按预期退出 1。Python 项目自测 296 项通过、1 项跳过，退出 0。[解包、反向对照和自测原始日志](../results/u280-aligned-predicate-review-20261121-v1/summary.json)

从固定项目 WSL 的 `/mnt/d/Vortex-U280` 执行，使用新的结果目录。

```sh
python3 -B experiments/u280-aligned-preflight/prepare.py \
  --output results/u280-aligned-predicate-preflight-NEW
python3 -B experiments/u280-aligned-preflight/review.py \
  --bundle-run results/u280-aligned-predicate-preflight-NEW \
  --output results/u280-aligned-predicate-review-NEW
```
