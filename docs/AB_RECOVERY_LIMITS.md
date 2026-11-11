# A/B 平台完成与恢复边界

2026-11-11 后续更新：C runtime 已新增 `sticky-device-fault-v1`，并完成三模型实际等待超时/排空与 CP 设备错误封锁实验。见 [新恢复记录与边界](RUNTIME_RECOVERY_20261111.md)。下文是原交付时点的历史说明；物理旧事务隔离和故障恢复仍未接收。

版本：`ab-recovery-notes-v1`，2026-11-11，Asia/Shanghai。适用固定 Vortex `7fe19369587c087f902c3e2bc2add612aa910a95`、D5/D6 仿真库和 D12 `gcc9-vm-allocation-v1` 的 U280 runtime。本文是源码核查及已有执行证据的交接，不是新增恢复实验，也不扩展 `ptx-vx-args-v1`。

## 已经证明的行为

同一设备、同一队列的固定 PTX 序列在 SimX、处理器 RTL、NOXRT AFU、U280 各完成 30 次合法启动。每路经过 29 次模块装载、两轮缓冲区分配，等待完成后读回完整数组及参数；提交后覆写宿主参数与 launch 描述符没有污染本次执行。每路 12 次非法 Block 提交在设备执行前同步拒绝，随后合法启动成功。原件和复现见 [连续启动记录](AB_PTX_SEQUENCE_PROGRESS.md)。

这证明了上述成功路径和提交前拒绝后的可继续性。缓冲区重新分配的 `generation` 是测试标签，并非项目 `recover()` 的 context generation；不能据此认定旧 event/句柄在故障恢复后失效。

## 固定源码说明了什么

| 机制 | 固定源码依据 | 可交给 C 的结论 |
|---|---|---|
| event 有界等待 | `sw/runtime/common/event.cpp`，`Event::wait_value` | `wait_for` 到期返回 `VX_ERR_TIMEOUT`。该分支没有停止 kernel、排空 DMA 或复位设备。调用超时和设备停止是两件不同的事。 |
| CP 轮询限时 | `sw/runtime/common/device.cpp`，`Device::cp_poll_seqnum_` | `VORTEX_CP_POLL_TIMEOUT_S` 未设置时为 0，只告警并继续轮询；设置正数后到期返回 `VX_ERR_DEVICE_LOST`。这一分支同样未完成旧事务隔离。不得把日志里的 “abort” 解读为安全硬件中止。 |
| queue 销毁 | `sw/runtime/common/queue.cpp`，`Queue::~Queue`、`worker_loop` | 销毁请求 worker 处理完已有 FIFO 后退出并 `join`；依赖等待可以使用 `VX_TIMEOUT_INFINITE`。这不是已证明有界的错误恢复/取消操作。 |
| XRT 打开时 reset | `sw/runtime/xrt/vortex.cpp`，设备初始化 | 写 `CTL_AP_RESET` 并最多读取 1000 次 `AP_IDLE`，失败会报错。这只说明打开流程中的复位实现；没有证明任意在途 DMA/故障状态下重开或复位是安全恢复。 |
| 公共调用面 | `sw/runtime/include/vortex2.h` | 有 queue/event 等待接口；项目协议中的 `recover(context, timeout_ms)`、隔离报告和句柄代际管理仍需 C/B 实现并接收。 |

以上文件逐字节身份由收尾核验对两份固定检出检查。D12 服务器补丁仅 VM 分配失败检查和构建输入处理，详见 [补丁记录](../environment/u280-fpga/PATCHES.md)，没有新增已接收的恢复语义。

## 本轮交付的限制

| 能力/试验 | 状态 | 缺少的证据与责任 |
|---|---|---|
| 合法任务完成后的数据可见性、连续启动 | PASS，固定样例范围 | 新生命周期判据仍需 E 独立接收。 |
| 非法 B=33/64 提交前拒绝后继续运行 | PASS，四路各 12 次 | 不计为 timeout/fault recovery。 |
| 有在途任务时 read/write/free/unload/close 返回项目 E_BUSY | NOT_RUN | C 实现统一 API 的资源引用及状态控制，E 冻结负例。上游队列行为不能直接等同项目 API。 |
| 在途 kernel 超时、安全中止、DMA 排空/隔离 | NOT_RUN | A/B/C 先约定能观测的停止条件、平台允许的隔离方式和有界路径，再在隔离环境验证。 |
| recover 后代际递增及旧 event/buffer/module 失效 | NOT_RUN | C 实现，A/B 提供真实停止/隔离证据，E 独立接收。 |
| 任意 kernel 越界的精确异常/内存沙箱 | 未承诺 | 当前声明范围检查只覆盖 API 可观察部分，不能代替硬件保护。 |

## 出现真实超时后的接续要求

1. 保留首次错误、运行目录、BDF、xclbin/runtime 哈希、最后进度和原始日志；把任务标为 FAIL 或仍未完成，不能补写成功输出。
2. C 将 context 标为 NEEDS_RECOVERY/UNAVAILABLE，停止新的普通提交与资源复用。仅等待超时不能授权释放底层仍可能访问的内存。
3. B 采集当次设备/进程/KDS 状态，与平台维护者确认停止或隔离方式。KDS 空闲是当前运行门禁的一项，不单独证明所有旧 DMA 已排空。
4. 在没有隔离证据前不自动 reset、重开、重新加载或复用地址。是否能够关闭 context，依 [合作协议 §6](COLLABORATION_PROTOCOL.md#6-v05v06项目-runtime-api) 的事务隔离条件判断。
5. 只有平台停止/隔离条件被实际核实且 C 完成恢复后的重新检查，才记录 `isolated=true`、递增 generation、废止旧句柄；失败则保留不可用状态。新运行使用新 run_id。

这是后续实现和接收条件，不是已经实现的自动恢复流程。本轮没有运行故障 kernel、执行额外板卡复位或改变共享设备配置。正常 device open 使用上游初始化 reset，不计作恢复试验。
