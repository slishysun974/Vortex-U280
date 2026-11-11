# C runtime 超时排空与设备故障封锁

2026-11-11，补丁 `sticky-device-fault-v1`，接口说明 [api_v2.json](../configs/c_runtime/api_v2.json)。v1 契约原件保留；参数 ABI、PTX 白名单、目标 lock、固定源码和 native 库没有变化。生产 `ptx_runtime.py` SHA-256 为 `17ec7272b8fd369841cd681d06cb4ddd30f03c19ceb6c70abcf7db3a53110431`。

## 发现与修复

固定源码 `sw/runtime/common/queue.cpp` 的 `Queue::finish` 先等待 FIFO barrier，随后报告并清除 `async_error_`。因此第一次返回设备错误后，再调用 finish 可能返回成功；这个成功不能证明之前失败的 CP 命令已停止访存。旧封装只看本次 finish 返回值，存在重试后误放行的路径。

现在 `Context.check()` 永久记录本 context 的首个非 timeout 原生故障 `device_fault`，独立保留原始 `first_error`。即使后续底层错误标志被清除，`recover()` 仍拒绝调用 native API，保留 buffer、module、event、参数和待传输宿主内存，generation 不变；普通操作返回 E_UNAVAILABLE，close 返回 E_BUSY。诊断查询返回副本，调用方不能修改内部故障记录。

只有没有设备故障的仿真 context 才能走超时排空：有界等待 queue finish 成功后，还要以零等待检查原始 launch event 确实成功，再释放资源、递增 generation 并废止全部旧句柄。任何步骤报错都不返回 READY。物理后端仍返回 E_UNAVAILABLE；本次没有把 native barrier、KDS 空闲或进程退出视作硬件 DMA 隔离证据。

`timeout_ms` 限定底层队列等待；native 释放 API 没有 timeout 参数，因此不能承诺整个 recover 的硬实时上界。记录包含实际耗时。`safe_abort=false`，没有增加 reset、取消或重载路径。

## 实际验证

新目录 [c-runtime-recovery-20261111-v1](../results/c-runtime-recovery-20261111-v1/summary.json) 保存脚本快照、每条命令、原始日志、退出码、原生调用返回码和耗时。

```powershell
wsl -d Vortex-AB-Ubuntu-22.04 --cd /mnt/d/Vortex-U280 -- python3 -B scripts/validate_runtime_recovery.py --run-id c-runtime-recovery-NEW
```

必须使用新的 run_id。worker 只接受 simx/rtlsim/xrtsim，不接受 u280-xrt。

| 范围 | 新证据与结论 |
|---|---|
| Python 运行器自测 | `python -B -m unittest discover -s tests -v`：260 项，259 通过、1 跳过、退出 0。覆盖原始 event 失败、设备错误锁存、重试不进入 native 和资源所有权；不计设备执行。 |
| SimX | timeout、CP fault、fresh-process canary 三个独立 worker 全部退出 0。 |
| 处理器 RTL | 同上，实际固定 D5 处理器 RTL 库；不属于物理板卡。 |
| NOXRT AFU RTL | 同上，实际固定 D5 AFU 模型库；不属于真实 XRT/PCIe/HOST。 |
| 每路超时路径 | 两次 4096 元素合法 copy，真实 `wait(event,0)` 返回原生 7；两次 `recover(0)` 仍返回原生 7并保留资源；随后 `recover(60000)` 成功，generation 分别变为 1、2。每次旧 event/buffer/module 都被拒绝，重新分配/装载后 37 元素新 copy 的完整数组及哨兵通过。 |
| 每路故障路径 | 分配和上传完成后，用上游现有 `VORTEX_CP_POLL_TIMEOUT_S=0.000000000001` 触发实际 CP 轮询超时，原生返回 `VX_ERR_DEVICE_LOST=6`。连续三次 recover、普通 alloc/read、close 均按约定拒绝，未新增 native 调用，generation 保持 0，参数仍保留。 |
| 故障后的模型处置 | 故障 worker 以 `os._exit` 结束其独立仿真进程；另起新进程运行 canary，三路均通过。仅隔离模型进程地址空间，没有在同 context 内恢复设备故障。 |
| 物理 U280 等待超时/故障恢复 | **NOT_RUN**。停止/隔离机制的依据仍 **BLOCKED**，物理 recover 禁用。合法样例的板测接收另列。 |

共 9 个实际模型 worker，6 次真实 event timeout、6 次失败的零等待 drain、6 次成功 drain、3 次原生 CP 设备错误、9 次被拒绝的故障 recover 重试；恢复后/新进程共 9 条 canary 正确。不能把故障封锁计为故障恢复成功，也不能把故意缩短 CP 轮询阈值解释为板卡发生了物理故障。故障可能发生在 kernel 的 CP 配置/启动事务阶段，未宣称其一定在 kernel 指令执行中发生。

E 对上述作者运行证据完成[独立复核](../results/e-runtime-unseen-development-20261111-v1/recovery-review.json)：检查命令/日志/原生状态、释放顺序和故障后没有新增 native 调用，并从原始输入独立重算 9 条 canary 的 18 份完整数组。该复核没有增加一次故障执行。新增 E 接收器与板测门禁后，[最终全套自测](../results/c-runtime-closeout-20261111-v1/summary.json)为 269 项，268 通过、1 跳过、退出 0；旧 E 冻结答案、根 lock/caps 与 ABI/profile 保护项哈希保持。

## 物理恢复的未完成项

下一步由平台方给出针对固定 shell、D10 xclbin/D12 runtime 的停止/隔离流程与可观察成功条件，包括旧 DMA、HOST 映射和在途写入的生命周期。取得依据后，才能增加带版本的物理恢复实现，在隔离设备窗口验证恢复失败、部分完成、旧事务晚到和重新分配后输出。现有独立合法样例板测不替代这一实验。TIMING-7 保持 OPEN。

资源保留保证只适用于仍存活的调用进程；进程退出、宿主崩溃或外部超时终止不提供硬件隔离保证。现有板测执行器是合法任务的限时验证工具，不是物理故障恢复守护进程。本轮没有用它制造物理故障或把脚本退出作为恢复成功条件。
