# U280 构建流程补丁

## D12 宿主 runtime：`gcc9-vm-allocation-v1`

这是独立的宿主源码/生成脚手架补丁，与 FPGA 的 `ip-ooc-v1` 分开。触发证据为 服务器 v2（本地记录 `results/u280-runtime-20261109-v2/returned/runtime/stub.stderr`）：GCC 9.3.1 / `-O2 -Werror` 编译公共库时发现 `VMManager::map_p2v` 的 `vpn` 可能未初始化；旧代码忽略了两处分配失败，随后移位并安装页映射。未关闭警告，也未仅给变量填零。

完整 diff（本地记录 `results/u280-runtime-gcc9-prepare-20261109-v2/runtime.patch`） 修改新输入包中的三项文件：

- `source/sw/runtime/common/vm.cpp`：两处分配失败都立即返回 `UINT64_MAX`，不消费未初始化变量、不进入映射更新。
- `source/sw/runtime/common/vm.h`：记录该内部方法的失败页号。当前固定 runtime 没有此方法调用点；公开 C API 与参数 ABI 未改。
- `build/sw/runtime/common.mk`：仅当 `XCONFIGS` 未定义时展开配置生成器。原 Makefile 的立即展开赋值即使被命令行覆盖仍触发 `$(shell ...)`；新包保留 D11 的全部已解析定义，未变更 FPGA 参数。

候选 binding 升为 `u280-runtime200-binding-v2`，仍为 draft/frozen=false；记录父包/父 binding、三项前后哈希及新的源码清单。父 D11 包、根 lock/caps、原候选与 `upstream/vortex/` 均保持原样。新包 SHA-256 为 `6911b8dcbcc0c2a4ea6aa5ea6d636de470c442159e2f062e0861227f3d05ee16`。CLI 名称 `gcc9-v1` 映射此候选。

行为回归编译实际抽取的 `map_p2v` 方法，覆盖直接分配失败、随机分配回退失败、成功、缓存命中和随机 reserve 成功；失败时页表更新/flush/映射缓存均不得改变。Makefile 对照测试复现旧版仍调用生成器、新版使用固定配置时不调用，缺少固定配置时仍调用。上述为宿主单元范围；VM-disabled 的 U280 仍不能接收为 VM 功能通过。

跟踪项 **D12-VM-01**：启用 VM 前需完整设计 `map_p2v` 错误 API，并审查相邻页表分配、`update_page_table` 和 `flush` 错误传播；当前补丁不宣称解决整套 VM 恢复。服务器实际编译接收以 [D12](../../docs/AB_D12_PROGRESS.md) 最新结果为准。

## D9 FPGA 构建流程：`ip-ooc-v1`

`ip-ooc-v1` 是独立的构建流程版本，不改变 `u280-hbm32-v1` 的 RTL、参数、ABI、根 lock 或 D8 源输入包。默认 `pinned` 仍可复现未修改的上游流程。

实际接收：`u280-preflight-20261109-100406-629` 已于 2026-11-09 10:10 返回 PASS，Vivado 退出 0、340.708 秒，五个 OOC IP、elaboration、原 error gate 和 XO 打包均通过。完整 link 与板上结果仍 NOT_RUN，范围见 [D9](../../docs/AB_D9_PROGRESS.md)。

## 触发证据

`results/u280-preflight-20261109-095402-528/`：真实 Vivado 2023.1 运行退出 1，51.923 秒。五个 floating_point IP 的 `generate_target all` 已执行；随后 elaboration gate 报告没有找到 stub，首个错误为 `module 'xil_fma' not found`。其余 18 条错误含级联失败，不能断言都已定位或修复。日志还显示 `Using part: xc7vx485tffg1157-1`，因为上游没有显式设置器件。

AMD 的 [2023.1 synth_ip 文档](https://docs.amd.com/r/2023.1-English/ug835-vivado-tcl-commands/synth_ip) 说明 OOC 综合生成 DCP、stub 等产物；[synth_design 文档](https://docs.amd.com/r/2023.1-English/ug835-vivado-tcl-commands/synth_design) 也指出 RTL elaboration 使用 OOC DCP 或 stub 均须先有 OOC 综合结果。由实际缺 stub 日志与这些文档推断，固定流程缺少 OOC 生成步骤。

## 实施与范围

`build_prepared.py --build-flow ip-ooc-v1` 在每个新构建目录的 `flow/` 内复制 Tcl，再执行四处严格单匹配替换：

- `gen_xo.tcl` 向 IP 生成器传递候选的 `device_part`。
- `xilinx_ip_gen.tcl` 对五个 IP 串行执行 `synth_ip`，要求每个生成的 Verilog stub 确实存在。
- `xilinx_elab_check.tcl` 的临时工程显式选择同一 U280 part。
- `package_kernel.tcl` 的打包工程显式选择同一 part。

每次写入 `flow_patch.json`、`flow.patch`，记录原文件/新文件 SHA-256。Linux 与 Windows 输出统一 UTF-8/LF。`input/` 保持原始输入；模块接口检查器原文件保持不变，`MODULE_INTERFACE_CHECK=error`、原 `synth_design -rtl -flatten_hierarchy none` 与失败退出逻辑保留。未手写 vendor stub，未修改 FPU 参数，未设置 gate 为 warn/off。

XO 与 link 必须同时匹配原输入 manifest、候选 lock、build_flow 及 flow_sha256。补丁不是已验收硬件功能；实际 OOC、elaboration、接口 gate、XO 必须分别从远端日志接收。完整 AFU 综合/布局布线仍需按已有要求确认资源方案。

## 运行

```powershell
& 'D:\Vortex-U280\scripts\Invoke-U280Preflight.ps1' -ProbeKind xo `
  -PlatformRun u280-preflight-20261109-094621-277 -BuildFlow ip-ooc-v1
```

新 run_id 自动生成；输入包哈希与 XPFM/XSA 哈希复核后才启动工具。限制为两个 CPU、nice +10、Vivado maxThreads=2、Vivado 整阶段 900 秒；没有 RAM 硬限。补丁只增加五个小型 vendor IP 的 OOC 综合，不包含完整 Vortex 综合、link、板卡配置或装载。
