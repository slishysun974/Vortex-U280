# 固定 D10/D12 U280 的尾部逐 lane 可观测性

固定 D10/D12 的离线核验退出 0，逐 lane 采集 `BLOCKED`，本轮 U280 配对执行和尾部假谓词零请求验证均为 `NOT_RUN`。大档 `copy`、`vadd`、`affine` 的最后一组 warp 里，待核对的是索引 16,381–16,383 对应的 lane 1–3。放行需要在 LSU 合并前捕获完整的请求握手、lane mask、读写方向和地址，并用 PC 或等价身份关联该逻辑 warp。没有该观测路径时按原条件停止。[离线回执](../results/u280-aligned-tail-observability-20261122-v2/summary.json)

## 已有路径的核验

- **D10 镜像与实现。** 逐字节核验固定 xclbin SHA-256 与 UUID。原始 11 项 section 表、容器末尾的 XRT mirror 和原 `xclbinutil --info` 回执一致，均无 `DEBUG_IP_LAYOUT` 和 `DEBUG_DATA`。D10 输入清单和 D8 归档逐字节匹配，实际预处理启用 `NDEBUG` 和 `SYNTHESIS`，构建及 link 无 `SCOPE`、`CHIPSCOPE` 或 XRT debug/profile 选项。实现资源表列出 shell 的 user debug hub 和 bridge。归档中无 AFU 的 LSU 逐 lane ILA 探针。[原始 section 表（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-6b58adb4b865) · [XRT 检查原件（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-26966b0045ab) · [路由调试资源（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-489b0028a27b)
- **D12 host 入口。** 两份实卡库哈希和 `TARGET=hw` 构建回执通过核对，符号表没有 `vx_scope_*`。现有 `VORTEX_CP_TRACE` 可打印提交到 CP 环的命令与参数，MPM 提供 core 级聚合计数。两者均没有逻辑线程或 lane 请求字段。HBM AXI 位于 LSU 合并及缓存之后，外部事务无法对同一缓存行内的各 lane 请求做完备归因。[D12 原始符号表（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-311e27bbb5a4) · [CP trace 记录格式](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/sw/runtime/common/device.cpp#L527) · [固定 LSU 读写和 mask（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-145f3e2a6230)

## 存量功能证据

从上一轮计数板测回传复核三个算子在 16,381 元素档的六份完整输出及 210 次启动的输出哈希，均与原冻结答案一致，覆盖前后哨兵和尾块填充。这是上一轮的功能证据。已有 DEBUG3 SimX、处理器 RTL 和隔离 NOXRT AFU 的逐 lane 记录仍按各自模型范围归档。[前次 U280 原始回执](../results/u280-aligned-mpm-20261122-v1/result.json) · [SimX 与处理器 RTL](PTX_SAME_PREDICATE_PRODUCTION_20261121.md) · [NOXRT AFU](PTX_SAME_PREDICATE_AFU_20261121.md)

首次离线解析把 section 末端当作文件末端，随后识别并核验尾随的 XRT mirror，用新 run_id 完成复核。两次回执分别保留。离线脚本只读归档，未打开 U280、替换镜像或启动新用例。[首轮回执](../results/u280-aligned-tail-observability-20261122-v1/summary.json) · [审计入口](../experiments/u280-tail-observability/audit.py)
