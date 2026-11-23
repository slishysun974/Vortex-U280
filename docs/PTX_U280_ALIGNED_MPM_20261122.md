# 固定 D10/D12 U280 的按次设备计数

同一 D10/D12 的尾部逐 lane 可观测性已核验，当前固定镜像的相关物理验证为 `NOT_RUN`。[观测路径检查](PTX_U280_TAIL_OBSERVABILITY_20261122.md)

固定 D12 的 `libvortex.so` 导出 `vx_device_mpm_query`。该函数通过 CP/DCR 读回 core 0 的 base MPM 计数器。D10 的 `MCYCLE`（`0xB00`）在调度器 busy 时累加，`MINSTRET`（`0xB02`）按退休的 warp 指令累加。实际取样采用空闲连续两读、单次启动并等待退休、退休后连续两读。两个空闲区间各自稳定且退休后读数递增时，以本次前后差作为设备计数。所有读取位于主机执行等待计时区间之外。[D12 读回实现](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/sw/runtime/common/perf.cpp#L196) · [D10 计数器（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-254d81141dce) · [取样入口](../scripts/u280_aligned_counters.py)

实卡仍为 `0000:b1:00.1`、XRT index 3、HOST 256 MiB、DATA_CLK 200 MHz。原始 `CP_DEV_CAPS=0x00061001` 且 `VM=0`。12 次逐字节暂存探针通过，其中最先两次同时做计数可读性检查，分别得到 1,852 和 1,832 周期，退休数均为 133。198 个冻结输入与编译件均与上一轮封包逐项同哈希，覆盖正式配对镜像和诊断探针。关闭时 KDS 的在途执行与 context 均为 0。[封包清单（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-25237a21bd96) · [完整门禁（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-158830f58615) · [计数状态（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-56942f65f7c5)

三个算子、两档输入按原计划完成 210 对、420 次启动，全部通过完整 `z`、前后哨兵和尾块填充的字节核对，并取得逐次设备计数。两个探针和 420 次配对启动的 3,376 次 API 读回均返回 0。板端、SSH 和本地接收均退出 0，121 份回传原件均通过哈希复核。[本地回执与文件哈希](../results/u280-aligned-mpm-20261122-v1/result.json) · [API 原值（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-d0afea4ee499) · [逐次计数、主机耗时及输出哈希（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-b0d7608a71dc)

## 180 对计时样本

每组 30 对，排除 5 对预热。差值先在同一对内计算 `v1.4 − v1.3`，再取中位数。退休数在每组同一路的 30 次计时中一致。设备周期按实测 200 MHz 折算为每周期 5 ns。主机执行等待包括提交和等待退休。

| 算子 | 元素数 | 设备周期差 | 退休 warp 指令 v1.3 → v1.4 | 设备差折算（µs） | 主机执行等待差（µs） |
|---|---:|---:|---:|---:|---:|
| copy | 1,024 | −242.5 | 7,744 → 6,976 | −1.21 | −9.87 |
| copy | 16,381 | −6,305.5 | 122,949 → 110,658 | −31.53 | −33.83 |
| vadd | 1,024 | −1,572 | 9,536 → 8,000 | −7.86 | −8.89 |
| vadd | 16,381 | −40,188 | 151,624 → 127,042 | −200.94 | −199.33 |
| affine | 1,024 | −2,179 | 10,048 → 8,512 | −10.90 | −14.09 |
| affine | 16,381 | −56,487 | 159,816 → 135,234 | −282.44 | −278.16 |

180 对中，150 对设备周期下降、140 对主机执行等待下降，180 对退休 warp 指令下降。大档 `vadd` 和 `affine` 各 30/30 对同时节省设备周期和主机等待，两项折算后的配对中位数相差约 1.6 µs 和 4.3 µs。小档 `copy` 的设备周期差中位数仅约 1.2 µs，主机等待差的幅度更大。接收的计数范围为本轮启动差分，逐 lane 请求及长时间高位翻转为 `NOT_RUN`。

## 复现

沿用前次冻结输入和正式构建目录，在授权窗口指定新 run_id。`--counters` 只选择宿主取样。若读数无法归因，保留原始读回并标记计数阻塞。原生 DCR 读取故障会停止该会话，回传已有证据。[前次板测与登录入口](PTX_U280_ALIGNED_BOARD_20261122.md)

```powershell
python -B scripts/c_v03_board_transport.py prepare-aligned u280-aligned-mpm-NEW `
  --kit results/u280-aligned-predicate-preflight-20261121-v1 `
  --compiled results/u280-aligned-load-build-20261122-v2 --bdf 0000:b1:00.1 --counters
.\scripts\Invoke-CV03U280.ps1 -RunId u280-aligned-mpm-NEW -Server '<SERVER_HOST>' -Account '<SERVER_USER>'
```
