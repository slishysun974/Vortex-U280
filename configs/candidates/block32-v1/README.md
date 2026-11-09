# B=32 原生候选 v1：接收说明

2026-11-08。候选 `vortex-v3-rv64-1c8w4t-block32-draft-v1` 保持 RV64、1 cluster、1 core 和 4 physical lanes，将 warps/core 从 4 增为 8。目的：在固定 native runtime 的 block≤threads×warps 限制下验证 B=32；不是性能优化，也不是 32-lane warp 兼容。

此目录是独立候选，根目录 `configs/target_lock.json`、`target_caps.json` 和 `native_smoke.json` 仍描述 4w×4t 基线。不得将候选结果挂到旧 lock，不能混用旧 kernel/runtime/仿真库。执行时显式指定 `--target-profile block32-v1`，各 backend 使用新的 run/build 目录。

- 新 hardware schema：`ab-hardware-block32-candidate-v1`。
- 新 lock schema：`target-lock-block32-draft-v1`，`frozen=false`。
- 新 caps schema：`target-caps-block32-draft-v1`，初始能力保持未验收。
- 父 lock SHA-256：`924b17abadbbda710ead2053ac0873fb0698161c983f8ff1feb9b96a16a19ffe`。
- 候选 lock SHA-256：`9bf1ecd89852e54dd402e669becbfd0910752ffd16ad9e7a9f9b20e77b6c4649`。

固定源码、工具包提交、XLEN、PTX profile 与项目 ABI 均未改变；未修改上游源码。运行器分别验证此候选的固定定义、配置→lock→caps 哈希链和固定源码清单。候选配置中的 NOT_RUN 是运行前快照，后续实测通过单独的 results/summary.json 记载，避免修改执行所引用的 lock。

接收方 A/C/D/E 需要在新目录复跑、独立比较、确认逻辑线程映射与 P0 wrapper 后才能采用；当前不替代项目 P0 接收。B 在物理平台重新验收 HBM/HOST[0]、32-bank FPGA 配置、时序与板卡执行。2-bank 仿真不能作为这部分的证据。

生成命令为 `python -B scripts/prepare_block32_candidate.py`，采用独占创建；此目录已存在后不能重复生成。原始命令、退出码、配置解析输出见 `preparation.json`、`resolve.stdout` 和 `resolve.stderr`。实际推进见 [D5 记录](../../../docs/AB_D5_PROGRESS.md)。
