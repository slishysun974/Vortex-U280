# E：新合法语料与 C Runtime 独立接收

**限定范围 PASS：SimX、处理器 RTL、NOXRT AFU、物理 U280 各 48/48。** 共 192 次新执行、576 份全数组、192 组参数的 576 份原始字节快照通过。最终 [E 机器签发](../results/e-runtime-unseen-acceptance-20261111-v1/result.json)绑定独立冻结语料、新构建、四路执行、物理门禁、原始输运及最终源码身份；[完整复核程序](../results/e-runtime-unseen-acceptance-20261111-v1/verify.py)实际退出 0。

本轮 E 在独立代理上下文中先读取合作协议、PTX 规范、接口文档和 PTX 原件，独立构造并冻结输入与数学答案；冻结前未读取旧 expected、实际输出、实施者 oracle 或 smoke 输入生成器。旧 15 条 E 接收没有被继承为本轮通过。

冻结清单为 [manifest.json](../configs/acceptance/e-runtime-unseen-20261111-v1/manifest.json)，SHA-256：

```text
ee47fa9d641a1c94f35666610d4910924c233fb83f13b1e859c26ce3de95a654
```

冻结身份记录原始 `c-runtime-merge-20261111-v3` 生产文件哈希。执行使用其后的故障锁存修复版，`scripts/ptx_runtime.py` SHA-256 为 `17ec7272b8fd369841cd681d06cb4ddd30f03c19ceb6c70abcf7db3a53110431`；每路捕获运行前后的生产哈希和原始源文件快照。该修复未修改冻结输入、PTX、答案、根 lock 或固定上游源码。

## 冻结范围

48 条启动覆盖三种原始整数程序及三种合法等价 PTX 变体，每种 8 条。变体更换 entry 和寄存器名，将 `setp.lt`/正谓词改为 `setp.ge`/反谓词，使用 `0x4U` 地址步长，并插入等价 `sub 0`、`add 0` 或 `mul 1`；vadd/affine 还交换可交换算术的操作数。仅主张这些源级变体经过真实前端与工具链；优化后的同哈希镜像不代表新增设备指令覆盖。

N 为 0、2、5、17、47、79、193、509；B 为 3、5、6、9、13、19、23、29；G 满足完整覆盖且部分用例额外启动尾部线程。alpha 包括 0、1、`0xffffffff`、`0x80000001`、`0xfffffffe`、65537、`0x9e3779b9`、`0x40000003`。输入包含高位为 1、零、最大整数、加法与乘加回绕，以及按独立域分离 SHA-256 生成的新整数模式。

每次分配三个 600-word 缓冲区，x/y/z 指针各有独立非零自然对齐偏移。所有输入字、输出前后哨兵和未写尾部均逐字节接收。一个 context、一个 queue 连续执行 48 次，41 次装载/卸载、7 次同模块连续边界；前后两组各 24 次复用缓冲区，中间正常释放后重新分配。每次 launch 返回后修改调用方参数列表，分别捕获 plan、修改前和修改后的原始参数字节，证明副本保持原值。

独立答案只使用规范中的 `i=block_id*B+thread_id`、`i<N` 和 copy/add/affine 模 2^32 定义。参数接收器使用手写 `<QQI4x`、`<QQQI4x`、`<QQQII` 布局，不调用生产 packer；地址由 native `vx_buffer_address` 单独查询，检查 buffer base + offset、标量、padding 和完整 payload。状态检查涵盖 READY→RUNNING→READY、同 queue、单调 event、无 generation 漂移及最终 CLOSED。

## 结果与复现

[新构建记录](../results/e-runtime-unseen-build-20261111-v1/build_summary.json)：12 份模块（6 源×仿真/板上目标）均 PASS，36 条 prepare/build/validate 子命令退出 0；各 build 内的 configure、kernel 库和模块编译命令也分别保留。

[三路执行记录](../results/e-runtime-unseen-sim-20261111-v1/summary.json)完成，三路 capture/check 共 6 条子命令及外层入口退出 0。每路 144 份全数组、48 组参数的 144 份字节快照通过；共 144 次实际执行、432 份全数组、144 组参数，三路每条输出都对应同一冻结答案。

| 层级 | 结果 | 独立接收原件 |
|---|---|---|
| SimX | 48/48 PASS | [接收](../results/e-runtime-unseen-sim-20261111-v1/simx.acceptance.json) |
| 处理器 RTL | 48/48 PASS | [接收](../results/e-runtime-unseen-sim-20261111-v1/rtlsim.acceptance.json) |
| NOXRT AFU | 48/48 PASS | [接收](../results/e-runtime-unseen-sim-20261111-v1/xrtsim.acceptance.json) |
| 物理 U280 | 48/48 PASS | [E 字节接收（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-bd52c6813d6f)、[原始板测记录](../results/e-u280-unseen-20261111-v1/result.json) |

冻结输入的二次独立方程复核（直接从 input 字节重算，不导入生产代码）48/48 一致；包含 698 个 vadd 溢出元素、1440 个 affine 溢出元素和 2565 个高位为 1 的 x 元素。物理 U280 由主代理负责固定 D10/D12 门禁及 SSH 协调，E 执行器不登录远程、不配置板卡。

本次物理运行 `e-u280-unseen-20261111-v1` 在 b1/XRT index 3，HOST=268435456 bytes、实际 DATA_CLK=200 MHz、固定 xclbin UUID 下完成，真实 CPython 3.6.8 执行；一个 context 完成 48 次启动后关闭。13 条远端校验/编译/绑定/执行命令及 SSH、输运、E 接收均退出 0。三次普通账号持有者查询 `fuser` 退出 1 且输出为空，表示未见持有者，不是独占预留；其余门禁命令退出 0。加载前及关闭后 KDS 在途和 context 为 0。gate 的 `board_execution=NOT_RUN` 字段只标记门禁自身不执行 kernel，kernel 执行由独立 capture 及接收记录证明。

E 从 SSH 原始 framing 的 nonce 和 base64 重新核对全部导出字节，与返回文件和哈希一致；D10 xclbin、D12 两库、查询程序、lock 和门禁原报告的身份均核实。四路六份程序镜像逐项同哈希，每例 x/y/z 全数组四路逐字节一致。最新生产源码六项在四路执行前后及最终自测快照中一致。

```powershell
wsl -d Vortex-AB-Ubuntu-22.04 --cd /mnt/d/Vortex-U280 -- python3 -B scripts/e_acceptance/runtime_unseen_build.py --run-id e-runtime-unseen-build-NEW
wsl -d Vortex-AB-Ubuntu-22.04 --cd /mnt/d/Vortex-U280 -- python3 -B scripts/e_acceptance/runtime_unseen_simulate.py --run-id e-runtime-unseen-sim-NEW --build-run e-runtime-unseen-build-NEW
```

从新构建和三路已接收的记录准备板测，替换 `BUILD`、`SIM`、`NEW`；已有运行目录不可重试覆盖：

```powershell
python -B scripts/e_runtime_board.py prepare e-u280-unseen-NEW --modules results/BUILD/modules/board --executions results/SIM
./scripts/Invoke-EUnseenU280.ps1 -RunId e-u280-unseen-NEW
```

物理绑定已经由 B 门禁准备好后，通用执行器调用如下，使用未存在的输出目录并显式设置当前 binding 对应的 `VORTEX_DRIVER`/`LD_LIBRARY_PATH`：

```text
python3 -B scripts/e_acceptance/runtime_unseen_run.py --corpus CORPUS --modules BOARD_MODULES --binding BINDING_JSON --target-lock BOARD_LOCK --backend u280-xrt --out NEW_CAPTURE
python3 -B scripts/e_acceptance/runtime_unseen_check.py --corpus CORPUS --run NEW_CAPTURE --out NEW_ACCEPTANCE_JSON
```

宿主接收器自测为 4 个 unittest 方法，包含 3 个正控制和 16 个输出/哨兵/padding/参数副本/状态/地址/身份破坏对照，全部通过；[原始日志](../results/e-runtime-unseen-development-20261111-v1/unittest-escalated.log)。这是接收器行为验证，不是处理器或设备执行证据。[开发尝试记录](../results/e-runtime-unseen-development-20261111-v1/attempts.json)保留 WSL 沙箱 `E_ACCESSDENIED`、Windows 临时目录 `WinError 5`；两次均未成为设备结果，按权限规则在沙箱外重跑。首次 Windows 失败完整文本只在工具轨迹，磁盘记录明确标注此缺口。

最终 WSL 全套宿主自测 [记录](../results/c-runtime-closeout-20261111-v1/summary.json)为 269 项中 **268 通过、1 跳过，退出 0**；E 复核日志哈希及该记录全部源码/保护项身份。板端 CLI 的 Python 3.6 `argparse.add_subparsers(required=True)` 风险在设备访问前发现，板测适配改为直接调用生产 `validate`，没有修改生产模块或冻结源；本次实际板测首个 run 成功，没有失败板测被覆盖。

## 恢复证据的独立审阅

[审阅结果](../results/e-runtime-unseen-development-20261111-v1/recovery-review.json)核对主代理提供的 `c-runtime-recovery-20261111-v1`：10 条命令日志、9 份 worker 结果与实现快照哈希；三路各两次真实 event timeout、两次 recover(0) timeout，随后 queue drain 成功、原 event 成功，再释放资源；失效 event/buffer/module 拒绝。三路 CP poll 原生 `DEVICE_LOST=6` 后，3 次 recover 重试不再发出 native 操作、generation 保持 0、未释放不确定资源。

E 未使用该实验的 expected 文件，从原始输入按 copy PTX 独立重算恢复后的 6 个和独立新进程的 3 个 canary，共 18 份全数组通过。这是**对作者实际运行证据和生产修复的独立审阅**，不是 E 重新执行故障试验，也不是本轮预冻结 unseen 语料的一部分。

## 接收边界

本轮只覆盖上述合法整数输入、三个固定程序族、三种源级等价变体和当前单队列 API 生命周期。没有推断任意 P0 程序、高地址边界、lane trace 中假谓词完全无访存、性能或正式人类 E 签名。未见输入指 E 在不查阅开发向量的条件下独立构造完整样例，不声称每个单独整数从未出现在历史输入中。

物理故障注入、停止/隔离旧 DMA 和 U280 自动恢复仍 NOT_RUN；物理 `recover()` 保持 E_UNAVAILABLE。资源保留仅适用于仍存活的进程，进程退出或外部超时终止不构成物理 DMA 隔离证明。仿真 CP 故障的进程退出仅隔离该模拟进程，独立新进程 canary 不表示原 context 恢复。板测器用于合法任务的限时验证，不是故障守护进程，本轮没有故意制造物理故障。TIMING-7 保持 OPEN。
