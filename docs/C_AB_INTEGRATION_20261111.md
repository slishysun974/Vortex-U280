# C 与 A/B 的集成核对

日期：2026-11-11，Asia/Shanghai。版本：`c-ab-integration-review-v1`。

## 结论与本轮范围

C 的模块/Runtime 可以作为 A/B 平台之上的项目调用层。**实际隔离联调 PASS：SimX、处理器 RTL、NOXRT AFU 各 41/41，共 123 次新执行；三路完整数组一致，36 次接口拒绝符合预期。** 两边来自同一固定 Vortex 和工具链，核心配置、PTX profile 与参数 ABI 对齐。证据入口为[汇总索引](../results/c-ab-integration-review-20261111-v1/result.json)、[新执行 v3（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-ff9baa1e0a75)和[宿主/归档检查 v2（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-14d6500f6889)。

这份记录不表示 C 已合入项目主实现，不继承 C 的 E 接收状态，也不把 A/B 已有板测归为 C Runtime 的板测。本轮没有设备重编译、FPGA 重建、远程登录或板卡操作。

## 固定输入与互补关系

- C 仓库：[LiuZeheng123/GPGPU-runtime](https://github.com/LiuZeheng123/GPGPU-runtime/tree/7f3575db67888c03d1c2c4dc3743051c735519dd)，提交 `7f3575db67888c03d1c2c4dc3743051c735519dd`（2026-11-11 09:01:44）。继承我们 11 月 9 日公开基线 `46dd01406a98ee6eab451a435c8a761b4b6a9eea`，未包含之后的 A/B 板测工作。
- 本地原样检出：`build/c-ab-integration-20261111-v1/source/`；没有初始化/修改其上游子模块，运行前后核对 Git 状态。
- 两边 Vortex 均为 `7fe19369587c087f902c3e2bc2add612aa910a95`，工具包均为 `8c64cf921d3c6c456e80f00d24482d0aa2153a82`，RV64、小端、Vortex2。
- 本次共同仿真目标为 RV64 / 1 cluster / 1 core / 8 warps / 4 threads，block32 lock SHA-256 为 `9bf1ecd89852e54dd402e669becbfd0910752ffd16ad9e7a9f9b20e77b6c4649`。

| 层次 | A/B 提供 | C 提供 | 合并后的用途 |
|---|---|---|---|
| 处理器/仿真 | 固定源、D5 运行库、D6 访存观察、线程边界证据 | 显式 SimX/RTL/NOXRT AFU 选择和运行库绑定 | 用统一 API 调用已经验证的平台 |
| PTX/模块 | 三类样例、ABI、旧设备包装及四路验证 | 通用模块构建/装载校验、设备包装、元数据校验 | 从特定实验宿主过渡到可复用模块 API |
| 生命周期 | 四路各 30 次同 context 连续启动及拒绝后继续 | buffer 范围/句柄、单模块/队列、E_BUSY、超时状态和排空恢复 | 形成应用可调用的资源管理层 |
| U280 | D10 xclbin、D12 物理 XRT 库、BDF/HOST/UUID/时钟门禁；已有原生与 PTX 板测 | 物理后端尚未启用 | 下一阶段完成 C 的板上后端接线和独立验收 |

C 自报的三路各 840 次执行及 9 次超时恢复来自其 WSL；本轮分别用它的归档核对器复查原始字节和跨后端一致性。归档复核与本轮新执行分别计数，不把作者记录转换为 E 签发。

## 本轮验证方法

[接收脚本](../scripts/check_c_ab_integration.py)完成以下工作，所有输出写到新目录：

1. 核对 C 提交、工作树、12 项公共配置/ABI/PTX 原件的双边 SHA-256；记录代码候选清单。
2. 复核 C 三类 kernel 的既有三后端归档；分别运行 C 与 A/B 的完整 Python 单测，范围仅为宿主运行器/校验组件。
3. 使用 C 原版 `bind_simx_runtime.py` 为 A/B 的 D5 三套库生成新 v3 binding；复核原生执行摘要、当前库哈希、配置和依赖。
4. 在每个后端分别运行 C 原有 copy/vadd/affine 模块，每个模块使用独立进程。copy/vadd 各 13 条，affine 15 条，每路预期 41 次。
5. 覆盖 B=32 的 N=0/1/31/32/33/63/64/65/257/1024，另测 N=65 的 B=1/7/31；affine 补 alpha=0/1/0xffffffff。使用 32-byte 非零偏移、完整输入/输出/哨兵比对；N=0 仍执行真实 launch。
6. 每个模块检查 B=33/64 拒绝、在途 free/close 返回 E_BUSY，然后正常等待并继续。跨后端比较同一镜像、完整输入和输出；payload 内设备地址分别保存，不强求不同后端分配地址相同。

本轮新增检查没有 LSU trace、故障注入、恢复实验或性能测量，不借用 A/B 旧 trace 给 C 新模块背书。使用的是 C 已归档的设备镜像，没有把复跑说成设备重建。新增 oracle 是本次集成脚本中的整数定义，不是冻结的 E oracle。

| 本轮检查 | 真实结果 | 记录范围 |
|---|---|---|
| C 历史三路归档 | 2520 次记录逐字节复核通过，三条核对命令退出 0 | v2；没有重做这 2520 次执行，也没有重做其中的恢复实验 |
| C Python 自测 | 157 项中 143 通过、14 跳过，退出 0 | v2；含固定 Vortex2 头文件的宿主 ABI 编译核验 |
| A/B Python 自测 | 163 项中 162 通过、1 跳过，退出 0 | v2；仅运行器检查 |
| 新 SimX 执行 | copy 13、vadd 13、affine 15，41/41 PASS | v3；C 原模块 + C Runtime + A/B D5 库 |
| 新处理器 RTL 执行 | 同上，41/41 PASS | v3；没有额外 LSU trace |
| 新 NOXRT AFU 执行 | 同上，41/41 PASS | v3；不是物理 XRT/U280 |
| 跨后端/所有权检查 | 数组一致、36 次拒绝符合预期、C 工作树前后干净 | v3；12 项公共配置/ABI/PTX 字节身份保持 |

v3 的全部 15 条子命令退出 0，入口退出 0。v3 使用 `--execution-only`，宿主/归档检查在该次明确为 NOT_RUN；上表引用 v2 已完成的记录，不能说成 v3 又执行了一遍。两次的 110 项代码/配置比较清单一致。

## 合入时需要解决的具体差异

| 位置 | 实际差异 | 接收办法 |
|---|---|---|
| 前端 | C 为 `ptx-vx-frontend-v1.2`，增加 `[[maybe_unused]]` 并消除原地 mov/cvta 自赋值；A/B 旧冻结产物依赖 v1 字节 | 保留 v1 和原证据，给 v1.2 建独立版本/产物入口和接收记录；不能覆盖前端后要求旧哈希继续通过 |
| 模块/入口 | C 使用 `ptx-vx-module-v1-draft`，原生入口 `main`；A/B 实验包使用各自 schema 和命名 entry | 把 C 格式作为新的调用层候选，旧实验包通过明确适配或从 PTX 新构建；不能只改 manifest 冒充兼容 |
| FPGA 配置 | C `ptx_module.target()` 要求 defines 恰为四个核心宏；A/B `fpga.json` 另含 `PLATFORM_MERGED_MEMORY_INTERFACE` | 对板上目标做显式配置适配/版本说明，保留平台约束，不能删除宏以绕过校验 |
| 物理 XRT | C `runtime_backends.BACKENDS` 仅含 simx/rtlsim/xrtsim；xrtsim 虽用 `xrt` 驱动名，严格绑定 NOXRT 模型 | 新增独立物理后端与 board binding，接 A/B 的两库、bitstream 和门禁；不能将 xrtsim 改名当板卡 |
| 恢复 | C `recover()` 是有限等待 `vx_queue_finish`，成功后释放资源、递增 generation | 可以接收限定的仿真排空语义；U280 的故障中止、旧 DMA 隔离仍需 B/C 另证，详见恢复限制 |
| 公共脚本 | C 仍基于旧公开快照；例如 `run_native_smoke.Recorder` 没有 A/B 新增的 scratch log 功能 | 保留 A/B 当前公共脚本，逐项吸收 C 新增模块/测试；不整仓覆盖较新的板测、日志及证据脚本 |
| 运行环境 | C 库来自 Ubuntu 24.04/glibc 2.39；板端已验证组合为 GCC 9.3.1/glibc 2.17/XRT 2.13.479 | 复用并核验 D12 的服务器两库；另核对 C Python 层依赖及版本，不能复制 WSL 库去服务器运行 |

代码/配置候选清单见 [file_comparison.json（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-9bc2cda7d52c)：110 项中 65 项相同、14 项只在 C 存在、31 项不同。不同项也包含公开快照脱敏及 A/B 后续修复，不能全部当作 C 新功能。

首次 [v1（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-e33407dafce7) 的 copy/vadd 归档复核退出 0；affine 在压缩文件随机读取阶段超过 240 秒，子进程退出 -9，整体 FAIL/退出 1，设备运行 NOT_RUN。v2 将原归档顺序解包到临时目录，记录输入压缩包哈希，再调用同一个未修改的 C 核对器核验全部原始字节。没有改变用例、答案或核对条件，也未改写 v1 原件。

[v2（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-14d6500f6889) 的宿主/归档检查和 SimX/RTL 各 41 次执行通过，随后 AFU 绑定前的 ldd 因继承上一后端库目录而失败，整体 FAIL/退出 1。v3 在每个 binding 创建前即设置对应库目录，全部三路从头新执行；v2 的 82 次执行保留但不计入 v3 的 123 次。此修复仅涉及接收脚本环境，C 源码、模块、库和校验条件均未变；没有重编/安装依赖。

## A/B 可交给 C 的现有材料

| C 的需求 | 当前本地交付入口 | 限制 |
|---|---|---|
| 实际配置、能力和版本 | [A/B 统一交付](AB_CLOSEOUT.md)、[最终索引](../results/ab-delivery-20261111-v1/result.json)、`configs/candidates/u280-hbm32-v1/` | 根/candidate lock 的 draft 保留；新增事实引用带哈希的实际运行记录 |
| bitstream | `results/u280-archive-20261109-v5/returned/artifacts/vortex_afu.xclbin` | SHA-256 `bbac2ab73073b24ba857fb34eadf22bf1c11dc745527f064c4eec61b70d2c843`；需将文件实际转交到 C 有权限读取的位置 |
| 匹配物理库和补丁 | [D12 结果](../results/u280-runtime-20261109-v4/returned/runtime/result.json)、[binding-v2（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-5de8582c1682)、[补丁说明](../environment/u280-fpga/PATCHES.md) | 与模型库分开，保留 GCC 9 分配检查补丁及 200 MHz 配置 |
| 实际板测与门禁 | [67 条板测（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-6686d200ee75)、[四路复核](../results/u280-boundary-review-20261111-v1/result.json)、`scripts/u280_board_smoke.py` | 当时 b1/HOST 256 MiB/UUID/200 MHz 已核实；历史空闲不等于现在预留 |
| 时序/恢复范围 | [D13](AB_D13_PROGRESS.md)、[恢复限制](AB_RECOVERY_LIMITS.md) | TIMING-7 仍 OPEN，按既有要求跳过；不能交付为已关闭或安全 abort |
| 独立测试 | [固定 15 条 E 接收](E_PTX15_ACCEPTANCE.md)及原冻结输入/答案 | 只对旧接收组合有效，C v1.2 新模块/Runtime 需要新的 E 接收 |

本轮仅在本地备好这些入口，没有向同学发送消息、上传材料或改变共享仓库。

## 下一接收顺序

1. 保留 A/B 当前工作区，将 C 的模块/Runtime 作为带来源固定提交的新层合入；先版本化处理前端差异，再运行合并后的两套宿主检查与三路回归。
2. 用当前 U280 目标建立物理 binding 和模块目标适配，复用 D10/D12 产物，加入实际 BDF、HOST、UUID、时钟与空闲门禁。当前没有证据要求重新构建 FPGA。
3. 在新 run_id 下经 C API 运行 copy/vadd/affine、重复 launch 和拒绝集，再扩展已冻结边界。由 E 接收新的组合；故障隔离/恢复和性能另列。

复现本轮隔离核对（将 NEW 换为不存在的目录）：

```powershell
wsl -d Vortex-AB-Ubuntu-22.04 --cd /mnt/d/Vortex-U280 -- python3 -B scripts/check_c_ab_integration.py --source build/c-ab-integration-20261111-v1/source --output results/c-ab-integration-NEW
```
