# U280 32-bank HBM 候选 v1

2026-11-09。独立 draft，未冻结，不加入现有原生运行器的 profile 列表，不替换根配置或 `block32-v1`。

继承固定 Vortex/toolchain 身份及 RV64 / 1 cluster / 1 core / 8 warps / 4 threads。新增 `PLATFORM_MERGED_MEMORY_INTERFACE`，使用固定 U280 平台分支的 32-bank、33-bit HBM、512-bit 数据口；实际预处理生成一个 `m_axi_mem_0`，连接 `HBM[0:31]`，另一个 `m_axi_host` 连接 `HOST[0]`。这不证明 HBM 实际可用容量、地址映射、HOST 功能或板上性能。

配置入口为 [fpga.json](fpga.json)，身份为 [target_lock.json](target_lock.json) 及其 SHA-256。SYNTHESIS/VIVADO 使固定配置解析为 DSP FPU，不能继承 D5 的仿真/FPU 结论。ABI、PTX 白名单、固定源码均未修改，`vortex.patches` 仍为空；合并接口是候选显式宏覆盖。

200 MHz 是首轮构建目标，未测得；`FREQ_SCALING=0` 要求后续核对真实约束和时序，不能把自动降频的产物报告为 200 MHz。两个 CPU、两项并发 run、实现 maxThreads=2 是拟议资源限制；完整综合/实现仍需按既有用户要求确认资源规则。

本轮 [源预处理（本地归档）](../../../docs/LOCAL_ARCHIVE_INDEX.md#archive-4d422751316e) PASS、退出 0；原始分支的 32 个主接口只有端口 0 有显式连接，候选的接口/连接检查通过。这是预处理与显式连接一致性检查，不是实测 v++ 链接失败/成功，也不排除平台自动连接行为。

候选 lock 中 acceptance 保留创建时的 NOT_RUN；后续结果通过独立 run 绑定配置哈希，不回写历史。接收需要 B 的实际 platform/XSA、Vivado XO/完整实现、时序、HOST/HBM 与原生板上回归，以及 C/E 对模块/运行与独立答案的接收。

准备器 `scripts/prepare_u280_fpga_candidate.py` 为一次性工具，现有目录禁止重生成。复现命令及构建交付见 [D8](../../../docs/AB_D8_PROGRESS.md) 和 [构建方案](../../../environment/u280-fpga/README.md)。
