# U280 同谓词配对的离线准备包

`python3 -B bundle/verify_bundle.py bundle` 复核包内容、六组冻结输入、完整答案与 210 对启动的顺序。`candidates/` 包含按 U280 lock 重新编译的 v1.3 对齐基线和 v1.4 同谓词合并镜像。每一对共用相同的自然对齐参数读取和 `ptx-vx-args-v1`。`candidate.json` 记录构建比对及装载状态。`probe/kernel.vxbin` 是另行构建的逐字节读取地址探针。`offline-audit.json` 给出 D10/D12 归档身份与源码证据。

## 后续授权窗口中的装载条件

1. 复用现有物理 `BoardGate`，核对固定 D10/D12 哈希、目标 lock、BDF 与当次 XRT index、shell、至少 256 MiB HOST、设备空闲和无可见持有者。加载后核对 UUID 与实际 DATA_CLK 200 MHz，再核对 1 核、8 warp、4 lane、RV64。将这些记录绑定到同一次验证窗口与同一张卡。
2. 保存 `vx_device_query(..., VX_CAPS_VM_SUPPORT, ...)` 的原生退出码和数值，预期为 0。同时保存独立有效的 CP `DEV_CAPS` 原始读回，固定 XRT 寄存器偏移为 `0x1008`。拒绝全 1、异常值和 D12 的 all-ones 回退日志。`read_cp_caps.cpp` 是只读辅助源，在 D10 已加载、D12 context 已关闭并释放 IP 后运行，先核对 BDF 与已加载 UUID。它在本包中为待用源码，设备侧 XRT 编译和读回待执行。已有 BDF 查询源码为 `query.cpp`。
3. 对每个算子和规模，用同样的设备缓冲区、原始参数布局、非空 Vortex2 `vx_enqueue_launch` payload 运行逐字节 `probe/kernel.vxbin`。probe 的网格和 block 均为 `(1,1,1)`，输出为传入 `x` 指针处的两个小端 u64，依次为 `a0` 与 `MSCRATCH`。`x` 指针仍为该分配的基址加 64 字节。保存全分配的探针前后读回和实际 payload。要求两个地址相等、非零、基址可被 64 整除、各字段地址满足 4 或 8 字节对齐，探针记录外的 `x` 字节和其他数组保持原样。补一次重复启动核对回收槽，正式计数前恢复原始输入和哨兵。
4. 用当次事实复核物理对齐装载契约并接收对应物理模块格式和 loader 门禁后，再进入配对测量。本包中的镜像是离线候选，正式 `ptx_module.py` / `Context.load` 对物理对齐版仍处于阻塞状态。配对顺序按 `pair-schedule.json`，每个组合 5 对预热、30 对计时，交替先后，共 420 次计划启动。每次上传冻结输入和哨兵并校验完整输出，分开保留装载、上传、执行等待和下载。运行脚本沿用现有物理路径的门禁与回传协议，正式接收物理对齐模块后再接通候选。本包带离线检查和探针素材。
