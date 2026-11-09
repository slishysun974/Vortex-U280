# D12：服务器 runtime 编译、HOST 复查与报告解析修正

更新：2026-11-09，Asia/Shanghai。

**19:33:31，服务器 runtime 编译及依赖检查 PASS；上板就绪仍 BLOCKED、板上功能 NOT_RUN。** v4 原始采集（本地记录 `results/u280-runtime-20261109-v4/probe.json`）与传输记录（本地记录 `results/u280-runtime-20261109-v4/transport.json`）分别记录实际结果，SSH/采集均退出 0。两个库已返回本地，所有原有失败记录保留。

## 实际编译与身份

实际入口为 `scripts/Invoke-U280Runtime.ps1 -RuntimeProfile gcc9-v1 -RunId u280-runtime-20261109-v4`。远端使用现有 GCC 9.3.1、glibc 2.17、XRT 2.13.479；先加载 `/opt/xilinx/xrt/setup.sh`，在新的个人目录 `/home/u280user/vortex-u280-runtime/u280-runtime-20261109-v4` 解包/构建。固定两个 CPU、nice +10，每条构建器命令最多 300 秒；无安装、系统升级或 FPGA 重建。

[构建 result](../results/u280-runtime-20261109-v4/returned/runtime/result.json)的六条命令均退出 0：compiler/glibc 查询、公共库编译 **10.833 秒**、真实 XRT backend 编译 **1.420 秒**、两项 ldd 各 **0.019 秒**。ldd 无 `not found`，`libxrt_coreutil.so.2` 解析到服务器 `/opt/xilinx/xrt/lib/`。这是编译/链接和依赖解析接收，尚未调用设备 runtime API、未验证设备打开或 HOST 分配。

| 产物 | 字节 | SHA-256 |
|---|---:|---|
| libvortex.so（本地记录 `results/u280-runtime-20261109-v4/returned/runtime/lib/libvortex.so`） | 307488 | `d3538d2fc7c695a4a0102106aa45e9ef7a9e939fc44c3b15c547ff97d0dffe3e` |
| libvortex-xrt.so（本地记录 `results/u280-runtime-20261109-v4/returned/runtime/lib/libvortex-xrt.so`） | 45168 | `250769482e98c1cee84bd165a9e2af1c7b3f74a5b77dcf389ac1f4ea5aa7a8c1` |

这些是 CentOS 7 服务器上的实际构建，不是 D11 Ubuntu 公共库。宿主频率常量为 200 MHz，绑定 D10 xclbin SHA-256 `bbac2ab73073b24ba857fb34eadf22bf1c11dc745527f064c4eec61b70d2c843`；编译常量仍不能视作板卡时钟实测值。

## 失败定位与独立候选

- **v1：传输 FAIL，远端 NOT_RUN。** 工具后台 SSH 等待密码，但打开的可见终端是另一个普通 PowerShell；已中止后台会话。后续明确由用户在可见终端执行脚本并在 SSH 提示下输入密码。
- **v2（本地记录 `results/u280-runtime-20261109-v2/probe.json`）：公共库编译 FAIL。** GCC 9 检出 `VMManager::map_p2v` 忽略分配失败后使用未初始化 `vpn`，`make` 退出 2。另发现 Makefile 即使收到命令行 XCONFIGS，仍立即展开缺失的 `ci/gen_config.py`；本轮 XRT backend/ldd NOT_RUN。只读平台检查 PASS。
- 独立候选 **`gcc9-vm-allocation-v1`**（CLI `gcc9-v1`）改为失败立即返回 `UINT64_MAX`，并为生成器加入“仅在 XCONFIGS 未定义时运行”的条件。保留 `-O2 -Werror`。修改仅在派生包中，详见 [补丁与后续 VM 审查项](../environment/u280-fpga/PATCHES.md)。初次本地派生包因 Windows GBK 解码失败保留；显式 UTF-8 的新 v2 包成功。
- 新 binding（本地记录 `results/u280-runtime-gcc9-prepare-20261109-v2/binding.json`）升为 `u280-runtime200-binding-v2`，记录父包、补丁前后哈希和源码清单，仍 `frozen=false`。三项代码/脚手架文件变化，FPGA defines、RTL、根 lock/caps、公开 C API 和 PTX profile 不变。U280 的 VM 仍关闭，不宣称 VM 功能或错误恢复通过。
- **v3（本地记录 `results/u280-runtime-20261109-v3/probe.json`）：两库编译 PASS，依赖检查 FAIL。** 未加载 XRT setup，ldd 报 `libxrt_coreutil.so.2 => not found`。v4 使用同一个候选输入包，仅在远端入口加载现有 XRT 环境后通过；未改服务器系统库路径。

## 当次 HOST 与平台观察

v4 在 19:33:02—19:33:29 期间采集 8 张卡：`3d/3e/40/41/b1/b2/b4/b5:00.1` 均 ready；观察时 KDS outstanding execs、contexts 为 0，interface UUID 与 D10 一致。HOST `host_mem_size` 均为 **0**，`sudo -n -l` 返回需要密码，配置权限 **UNCONFIRMED**。只读观察没有取得设备保留权，之后使用前必须重新查空闲与 BDF/index。

依据 [XRT 2022.1 HOST 文档](https://xilinx.github.io/XRT/2022.1/html/hm.html)，应在加载 xclbin 之前预留 HOST 内存；不超过 1 GiB 的需求不需要额外 Hugepage 设置。下一阶段可先核实单张空闲卡的 256 MiB HOST 方案与账号权限。当前没有运行 `configure --host-mem enable`，没有修改 Hugepages、重启服务器或加载 xclbin。

## 时钟告警与 D11 机器摘要修正

新 [v2 机器审阅](../results/u280-timing-review-20261109-v2/result.json)从哈希一致的原始报告提取：普通 DRC 共 **343** 项，无 Error/Critical Warning；methodology 共 **100** 项，其中 **9** 项 Critical Warning。逐项保留 `TIMING-1×1`、`TIMING-7×1`、`TIMING-14×1`、`TIMING-54×6`，全部 **OPEN**。内部 unconstrained endpoints=0，但仍有 7 个输入/3 个输出缺 delay；methodology 点名 `io_perst_n_00[0]`，其他端口仍需从实现 DCP 取全名单。

D11 的 `verify.py` 在第一次 `2. REPORT DETAILS` 处分割文本，误命中目录页，因此旧 result 的 `drc_rules`、`methodology_rules` 为空，`methodology_critical_count=0` 是解析缺陷，不是无告警。旧结果原样保留；D11 文档和 unresolved 字段当时正确记录的 9 项告警保持有效。新解析器拒绝空表、重复规则和汇总数不一致，并核对 summary 与 9 条 detail 相符，避免空集合让检查自动通过。

告警命名显示其涉及平台可调时钟、PCIe 和调试时钟层次；这是基于报告的归属判断，不是厂商豁免。[AMD 2023.1 时钟说明](https://docs.amd.com/r/2023.1-English/ug1393-vitis-application-acceleration/Identifying-Platform-Clocks)说明 XRT 可按 xclbin 元数据设置 scalable clock；本构建使用 `--kernel_frequency 200`，元数据 DATA_CLK 映射 `ulp_ucs/aclk_kernel_00`。该机制可以解释 5 ns 约束与模块默认 3.333 ns 的差异，但未实测，不能直接关闭 TIMING-1。[XRT 调试说明](https://xilinx.github.io/XRT/2022.1/html/debug-faq.html#incorrect-frequency-scaling)要求把板卡 clock 报告与 xclbin 元数据比较。

## 验证与下一步

本轮新测试覆盖损坏输入、越界/重复/符号链接、旧目录保护、缺失库/失败命令不能 PASS；实际抽取的 VM 方法进行分配失败/成功/缓存/随机路径验证；Makefile 保留无固定配置时的生成行为；报告解析覆盖目录页、空表、数量不符与重复规则。最终 Linux 自测 v3（本地记录 `results/ab-d12-script-checks-20261109-v3/result.json`）实际执行 `python3 -B -m unittest discover -s tests -v`：114 项中 **113 通过 / 1 跳过**、退出 0、测试报告 84.014 秒。此前 Windows 沙箱临时目录访问失败，沙箱外新增 5 项检查通过；Linux 全量覆盖随后通过，未据此归因硬件。

D12 收尾核验（本地记录 `results/ab-d12-closeout-20261109-v1/result.json`）实际执行 `python -B scripts/verify_ab_d12_results.py --run-id ab-d12-closeout-20261109-v1 --runtime-run u280-runtime-20261109-v4`：**96/96 PASS、退出 0**。核验 71 份返回文件、请求与 collector 哈希、两库与 binding、固定源码 **3329 文件零差异**、原 D11 包/FPGA 配置未变，以及完整非空规则表。上板就绪在同一结果中独立保留为 BLOCKED。本轮未重跑处理器 RTL/AFU 模型，不替代板上、PTX 或独立 E 接收。

下一步：核实 HOST 权限并准备单张空闲卡；从实现 DCP 提取缺 delay 的完整端口及平台约束来源，核实 PCIe/调试时钟告警；条件满足后受控加载，先读回 xclbin UUID 和实际 200 MHz 时钟，再执行原生 demo/边界回归。无需重做 link、下载已有 xclbin或重装工具。PTX 前后端设备集成、板上功能、性能和 E 独立接收均仍待完成。
