# A/B D7：共享卡检查与小规模综合

日期：2026-11-09，Asia/Shanghai。用户已明确服务器允许自行选择空闲卡，允许少量线程的小规模构建及自行获取合法许可；无需等待固定分卡或书面配额。大型综合、布局布线之前再确认资源和作业规则。此授权替代 D6 当时的分卡等待条件。

## 执行入口与范围

Windows 入口为 `scripts/Invoke-U280Preflight.ps1`。SSH 密码仍由用户在本机提示处输入，不保存。每次创建新的本地 `results/u280-preflight-*` 与远端 `/home/u280user/vortex-u280-probes/<run_id>`，固定 known_hosts、核对账号和源文件哈希，保存命令、退出码与返回文件哈希。

实际综合对象是固定提交 `7fe19369587c087f902c3e2bc2add612aa910a95` 的 `VX_afu_axi_limit` 组件。三个 RTL/头文件逐一核对冻结源码清单，未修改上游源码。目标器件为 platforminfo 实测的 `xcu280-fsvh2892-2L-e`；两个 CPU 亲和性、Vivado `general.maxThreads=2`、nice +10、300 秒超时。只运行组件 out-of-context 综合，保存利用率和 checkpoint；完整处理器/AFU 综合、布局布线、xclbin 与板上执行分别保持 NOT_RUN。

卡状态由 sysfs 双快照及 `xbutil examine` 获取。`memstat` 的 IN-USE 表示连接信息，不能当成有人占卡；判断时结合 KDS 上下文、未完成请求和 XRT CU 状态。只读观察不建立设备租约，加载前须再次确认空闲及当次 BDF→XRT index 映射。`fuser` 若不可用，如实报告，不以此判定不存在持有者。

## 原始运行与修正

- `u280-preflight-20261109-001035-270`：SSH 退出 0，检查 FAIL/退出 1。
- `u280-preflight-20261109-001134-191`：同一旧脚本再次运行，SSH 退出 0，检查 FAIL/退出 1。
- 两轮失败是脚本命令差异：XRT 2.13.479 的 JSON 输出必须带 `--output`；Vivado 2023.1 的 `read_verilog` 不接受所用 `-include_dirs` 参数。综合没有开始，因此这两次不能解释为许可证失败。现改为独立 JSON 输出文件，以及固定上游 Tcl 已使用的 `create_project`、`add_files`、fileset `include_dirs/verilog_define` 设置。
- 两轮 sysfs 数据有效：8 张卡前后快照均为 `contexts=0`、`outstanding execs=0`、无 client pid；`host_mem_size=0`，HOST[0] 显示 UNUSED。它们是当时的空闲候选，并非保留给本项目的设备。
- 修正后的运行 u280-preflight-20261109-001732-931（本地记录 `results/u280-preflight-20261109-001732-931/probe.json`）：**PASS**，SSH 与综合均退出 0；8 张卡的 XRT 报告全部退出 0。采集在 00:17–00:18 完成。

旧运行、日志和输入快照保留，不覆盖为通过。

## 实际结果

| 检查 | 结果与证据范围 |
|---|---|
| U280 综合许可 | Vivado 日志明确记录 `Got license for feature 'Synthesis' and/or device 'xcu280'`，综合结束后释放；使用服务器现有许可，无需新购或等待书面许可证明 |
| 小型组件综合 | `VX_afu_axi_limit` 综合 PASS，0 errors、0 critical warnings；唯一 warning 是模块太小、不符合并行综合条件。整个 Vivado 命令耗时 50.879 秒，两个 CPU 亲和性、最多两线程；生成 checkpoint（本地记录 `results/u280-preflight-20261109-001732-931/returned/post_synth.dcp`） 与 利用率报告（本地记录 `results/u280-preflight-20261109-001732-931/returned/post_synth_utilization.rpt`） |
| 组件资源 | 10 CLB LUT、4 寄存器、0 BRAM、0 DSP；仅该组件的综合后数值，不是 Vortex 整机资源或布局布线结果 |
| 设备状态 | 8/8 `ready=0x1`、KDS 双快照 contexts/outstanding 均 0、XRT 所列 CU 均 IDLE；BDF 为 `0000:{3d,3e,40,41,b1,b2,b4,b5}:00.1` |
| shell | 8 张卡均为 `xilinx_u280_gen3x16_xdma_base_1`，logic UUID `283bab8f654d8674968f4da57f7fa5d7`，interface UUID `fb2b2c5a19ed63593fea95f51fbc8eb9`；尚未用本项目完整 xclbin 验证 platform/shell 兼容性 |
| 可见进程持有者 | 找到 `/usr/sbin/fuser`；8 次返回 1 且 stdout/stderr 均空。原始采集器将非零命令标为 FAIL，收尾保留该退出码，按“未报告当前账号可见的持有者”解释，不能证明所有账号都无持有者 |
| HOST[0] | 8/8 `host_mem_size=0`，尚未启用。主机可见 49,152 个空闲 2 MiB hugepages、CmaTotal=0；这是整机采集量，不是本项目额度或可分配保证 |

`0000:b1:00.1` 可作为下一步优先复查的候选：它在本次采集时空闲，satellite controller 实际/预期版本同为 4.3.27。其余七张为实际 4.3.28、预期 4.3.27，作为差异记录，未据此判为故障或执行升级。没有锁定、预留、加载或复位任何卡；运行前重新选卡。

[184/184 收尾核验](../results/ab-d7-closeout-20261109-v1/result.json)退出 0，覆盖输入/返回文件哈希、实际命令、许可日志、组件产物、双快照、配置未变及脚本测试。可重跑命令为 `python -B scripts/verify_ab_d7_results.py --run-id NEW --probe u280-preflight-20261109-001732-931`。这是同作者证据核验，不是 E 独立验收。

## 脚本验证

Linux 全套检查（本地记录 `results/ab-d7-script-checks-20261108-v1/result.json`）退出 0：76 项测试中 75 通过、1 跳过。运行命令为 `python3 -B -m unittest discover -s tests -v`，范围是运行器/前端/证据和解包行为，不是 FPGA 能力。

修正后离线输入的 Python 3.6 语法、源码与 payload 哈希通过。Windows 沙箱临时目录拒绝导致解包测试失败，原件保留在 `u280-preflight-offline-20261109-v4`；同一测试在授权环境重跑 3/3 通过（本地记录 `results/ab-d7-windows-bundle-checks-20261109-v1/result.json`）、退出 0。这些离线检查不代替实际 Vivado/XRT 命令。

## 后续

小规模综合和本次许可检查已完成，不再将固定分卡、书面额度或“未验证任何综合许可”列为当前阻塞。下一步核对 XRT 2.13 的 HOST 配置步骤与权限，准备独立 U280 FPGA 候选配置、固定工具兼容路径和受限构建计划。实际 `xbutil configure --help` 确认有 `--host-mem`，本轮没有执行配置；不能直接照抄新版本 `xrt-smi` 命令。

HOST[0] 的文件级存在已由 D6 确认，D7 的 `host_mem_size=0` 表明当前设备尚未配置该通路；固定 runtime 的命令环与控制缓冲需要 host-only BO。完整 FPGA 配置、构建、时序和原生板上 demo 仍待完成，大型综合/布局布线前按用户要求确认资源与作业规则。小组件综合不提升 A 的处理器功能或 PTX/独立 E 验收状态。
