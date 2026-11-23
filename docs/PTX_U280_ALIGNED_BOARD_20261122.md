# 固定 U280 上的 v1.3 / v1.4 配对板测

同日的按次设备计数已在新 run_id 单独复测并归档。[设备周期、退休指令和主机等待对照](PTX_U280_ALIGNED_MPM_20261122.md)

2026-11-22，板端、SSH 和本地接收均退出 0。固定 D10 xclbin 与 D12 两库的哈希通过核对。实卡为 `0000:b1:00.1`，当次 XRT index 3、HOST 256 MiB、实际 DATA_CLK 200 MHz。关闭后 KDS 的在途执行与 context 均为 0。[板端绑定（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-24168fe977c5) · [原始门禁（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-f4d38ea99e38) · [传输回执（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-478a2a911d22)

## 装载前门禁

D12 在打开当次 context 时对 `0x1008` 恰好有一次读回，`CP_DEV_CAPS = 0x00061001`。随后 `VX_CAPS_VM_SUPPORT` 返回 0，查询退出码为 0。在同一队列对 `copy`、`vadd`、`affine` 的两档输入各启动两次逐字节探针。12/12 次均回报 `a0 == MSCRATCH == 0x14000`，设备槽满足 64 字节对齐。每个字段的地址、逐字节读取值、报告区外的完整读回，以及第二次启动的退休槽复用均通过。之后才开始装载对齐配对模块。[逐字段回执（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-9628e3683bc2) · [探针前后缓冲区（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-bb67db85ae6b)

## 输出与分阶段耗时

1,024 与 16,381 元素沿用原输入和 block 32。每组 5 对预热、30 对计时并交替先后。210 对、420 次启动全部核对完整 `z`，包括前后哨兵和尾块填充。180 对进入计时统计。逐次样本保留完整输出哈希，每组每路保留最后一次完整输出和参数原件。接收端重新核对了回传的 119 份原件。[逐次样本（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-6b27624839ed) · [完整输出与参数（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-fd4f97edb255) · [回传清单与统计](../results/u280-aligned-board-20261122-v1/result.json)

表内是每对样本先求 `v1.4 − v1.3`、再取中位数，单位为 µs。装载阶段包含模块校验，执行段为主机侧提交及等待。结果记录同时保留两路各自的阶段中位数。

| 算子 | 元素数 | 装载 | 上传 | 执行等待 | 回读 | 端到端 |
|---|---:|---:|---:|---:|---:|---:|
| copy | 1,024 | +39.6 | +0.4 | −5.6 | +2.0 | +37.6 |
| copy | 16,381 | +112.1 | +0.4 | −18.4 | +4.1 | +126.0 |
| vadd | 1,024 | +40.1 | +8.5 | −5.6 | +9.8 | +28.3 |
| vadd | 16,381 | +226.3 | 0.0 | −194.2 | −1.1 | −41.7 |
| affine | 1,024 | +43.5 | −0.6 | −9.1 | 0.0 | +31.6 |
| affine | 16,381 | +99.1 | +2.3 | −270.6 | +0.7 | −146.2 |

六组的执行等待配对中位数均下降，180 对中有 141 对下降。含装载的端到端配对中位数在 16,381 元素的 `vadd` 与 `affine` 下降，180 对中有 80 对下降。本轮保存主机单调时钟耗时，U280 设备周期、退休指令和逐 lane 请求均为 `NOT_RUN`。

## 复现入口

使用同一份冻结包和正式模块构建目录，创建新板测标识。在授权窗口通过现有 SSH 入口执行。接收器对失败也回传已生成的门禁及探针原件。[离线构建与装载契约](PTX_U280_ALIGNED_LOAD_20261122.md) · [此次输入清单（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-4455d68315a2) · [SSH 及回传入口](../scripts/Invoke-CV03U280.ps1)

```powershell
python -B scripts/c_v03_board_transport.py prepare-aligned u280-aligned-board-NEW `
  --kit results/u280-aligned-predicate-preflight-20261121-v1 `
  --compiled results/u280-aligned-load-build-20261122-v2 --bdf 0000:b1:00.1
.\scripts\Invoke-CV03U280.ps1 -RunId u280-aligned-board-NEW -Server '<SERVER_HOST>' -Account '<SERVER_USER>'
```
