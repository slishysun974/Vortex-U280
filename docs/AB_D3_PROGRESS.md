# A/B D3：原生复跑、处理器 RTL 与 AFU 模型

日期：2026-11-08，Asia/Shanghai。用户已恢复推进。沿用固定 Vortex `7fe19369587c087f902c3e2bc2add612aa910a95`、工具包 `8c64cf921d3c6c456e80f00d24482d0aa2153a82` 和 RV64 / 1 cluster / 1 core / 4 warps / 4 threads 的 smoke 配置，不改变 P0 ABI、白名单或冻结答案。

本轮 SimX 复跑、处理器 RTL 与本地 AFU 模型的上游整数 demo 均 PASS。每路使用独立构建目录，命令和原始输出已归档；按用户要求本轮收尾后暂停。U280 无访问权限，板上仍 BLOCKED，整体项目仍为 PARTIAL。

## 本轮证据

| 项目 | 当前结果 | 证据与范围 |
|---|---|---|
| SimX 新目录复跑 | PASS（仅上游整数 demo） | [运行](../results/ab-d3-simx-20261108-v1/summary.json)、根命令退出 0（本地记录 `results/ab-d3-simx-20261108-v1/root-tool-completion.json`）；同一 agent 复跑，不计作 C/E 独立接收 |
| Verilator 工具包准备 | PASS（准备范围） | 18 个分卷/单包（本地记录 `results/ab-d3-toolchain-download-20261108-v1/summary.json`）、独立提取（本地记录 `results/ab-d3-toolchain-install-20261108-v1/summary.json`）；复用已校验的 15 项，新增固定 Verilator 三卷。第二卷超时重试保留，所有 Git blob 与 SHA-256 相符 |
| 运行器自测 | PASS（脚本范围） | 共 21 项，最终 Linux 20 通过/1 跳过（本地记录 `results/ab-d3-final-linux-tests-20261108-v1/summary.json`）、Windows 16 通过/5 跳过（本地记录 `results/ab-d3-windows-tests-20261108-v1/summary.json`）；新增 profile 缺项/错版本/未知组件拒绝、AFU 模型路由防误选硬件 |
| 处理器 RTL demo | PASS（仅上游整数 demo） | [v2 隔离运行](../results/ab-d3-rtlsim-20261108-v2/summary.json)、输出（本地记录 `results/ab-d3-rtlsim-20261108-v2/logs/39_demo_run.log`）、根命令退出 0（本地记录 `results/ab-d3-rtlsim-20261108-v2/root-tool-completion.json`）；16 个整数、`PASSED!`。首轮因缺少 ccache 构建失败、demo NOT_RUN，失败保留 |
| XRT AFU RTL 模型 | PASS（仅 NOXRT 模型整数 demo） | [运行](../results/ab-d3-xrtsim-20261108-v1/summary.json)、输出（本地记录 `results/ab-d3-xrtsim-20261108-v1/logs/39_demo_run.log`）、根命令退出 0（本地记录 `results/ab-d3-xrtsim-20261108-v1/root-tool-completion.json`）；16 个整数、`PASSED!`，每条 make 强制 `TARGET=xrtsim` |
| B 线平台源码审查 | PASS（仅来源核对） | 文件哈希与来源检查（本地记录 `results/ab-d3-platform-source-20261108-v1/result.json`）；实际账号、分配 BDF、XRT/驱动、shell/platform 与 HOST[0] 均未实测 |

## 入口与范围

`scripts/prepare_toolchain.py --profile rtlsim` 在固定工具包提交中选择原四项工具和 Verilator；提取根据已校验的 cache profile 接收完整组件集，缺项或未知组件拒绝。原 D2 缓存保留、仍可读取。新工具根为 `/opt/vortex-ab/toolchains/8c64cf921d3c6c456e80f00d24482d0aa2153a82-rtlsim-d3-v1`。

`run_native_smoke.py` 结果 schema 升至 4，保存 backend 实际解析的宏定义、runtime/simulator 构建参数戳、共享库与 kernel 审阅副本。`demo_execution` 与整体构建状态分开；未执行 demo 时，不把库构建失败解释为设备执行失败。

新增 `--backend xrtsim` 是本地原生运行器的 AFU 模型标签，不是扩展项目 P0 runtime API 的 backend 或 ABI。它映射至上游 `runtime-xrt` / `run-xrt`，每一条 make 都强制 `TARGET=xrtsim`；CLI 不接受含混的 `--backend xrt`。固定源码的 `XRTSIM/NOXRT` 分支使用本地 shim，不调用真实卡路径。

处理器 RTL 和 AFU 模型都会启用源 Makefile 规定的 `SIMULATION/SV_DPI`，浮点单元使用 DPI 模型。基础硬件配置相同，不表示全部 backend 宏逐字相同；每轮 `resolved_backend.cflags` 与构建参数单独保存。本轮整数 demo 不证明浮点电路正确、P0 u32 溢出、尾线程或假谓词无访存。

首轮 `runtime_build` 退出 2，底层日志为 `ccache: No such file or directory`，此前第三方库、kernel 和 demo 编译已成功，实际 demo 尚未运行。专用 WSL 补装 `ccache 4.5.1` 与依赖 `libhiredis0.14` 后，新建 v2 构建和结果目录；安装命令/退出码（本地记录 `results/ab-d3-host-dependency-20261108-v1/summary.json`）。运行器新增 ccache 预检，宿主脚本和未构建的容器配方同步补充依赖；未修改固定 Vortex 源码。

首轮 失败 summary（本地记录 `results/ab-d3-rtlsim-20261108-v1/summary.json`） 和 原始构建日志（本地记录 `results/ab-d3-rtlsim-20261108-v1/logs/37_runtime_build.log`） 保留。成功轮次不会覆盖首轮结果，也没有修改上游源码或冻结答案。

## 元数据接收与收尾

总索引（本地记录 `results/ab-d3-closeout-20261108-v1/result.json`） 记录三路 PASS、准备/自测、保留的失败和未验收范围。三路 `kernel.vxbin` 的 SHA-256 均为 `fe1e13ecb9b98be36ccf628d5e245283e7223ffdd703a0bdd043723195af6553`；比较记录（本地记录 `results/ab-d3-closeout-20261108-v1/comparison.json`） 只证明程序相同及各 backend 的内部结果比较通过，不证明时序等价或独立 P0 u32 语义。

`target_lock` / `target_caps` 升至 **draft-v3，frozen=false**，加入固定 Verilator 归档/二进制身份和实际 RTL/AFU 观察。执行使用的 draft-v2 lock 哈希为 `c7d0b78995d02fc8529b4157b794f991a058ced237c520703bf83094d74b8824`，当前 draft-v3 为 `924b17abadbbda710ead2053ac0873fb0698161c983f8ff1feb9b96a16a19ffe`；旧快照保留在各运行目录和收尾目录的 `before_*` 文件。硬件配置、源码、XLEN、P0 ABI 与白名单没有变化。

新版元数据的 只读预检（本地记录 `results/ab-d3-metadata-preflight-20261108-v1/summary.json`） 与 最终完整性核验目录（本地记录 `results/ab-d3-final-integrity-20261108-v1`） 分开保存；预检不执行 demo，完整性核验不替代功能验收。

## 后续复跑入口

在专用 `Vortex-AB-Ubuntu-22.04` 内从 `/mnt/d/Vortex-U280` 运行，`NEW` 必须替换成未使用的名称：

```bash
python3 -B scripts/run_native_smoke.py --backend rtlsim \
  --source /opt/vortex-ab/sources/vortex-7fe19369587c-v1 \
  --tooldir /opt/vortex-ab/toolchains/8c64cf921d3c6c456e80f00d24482d0aa2153a82-rtlsim-d3-v1 \
  --ramulator-deps results/ab-d2-ramulator-deps-20261108-v1/dependencies \
  --build-dir /opt/vortex-ab/builds/rtlsim-NEW \
  --run-id rtlsim-NEW --jobs 8 --timeout 1800
```

AFU 模型改为 `--backend xrtsim`，另换 build/run 目录。加入 `--check-only` 只做预检，不执行 demo；预检和实际运行也应使用不同 run_id。

## B 线接收边界

固定平台源码的 U280 分支要求 32 个 HBM bank、33 位平台地址和 `m_axi_mem_0:HBM[0:31]`；Alveo 命令处理器还连接 `m_axi_host:HOST[0]`。真实 runtime 使用 host-only BO；AFU 模型使用对齐分配的进程内存和进程地址。即使 AFU 模型运行通过，也不能证明物理 HOST[0]、PCIe、HBM、XRT 驱动或老师资料中的版本组合可用。

本轮 smoke 继续使用原仿真内存配置，未构建 U280 32-bank 硬件配置。板卡账号与分配信息、工具/许可/配额按 [U280 接收单](U280_ACCESS_CHECKLIST.md) 提供后再核验；不使用文档示例 BDF，不登录未获准的服务器。

## 当前未完成

独立接收、PTX P0 三类 kernel/统一模块 ABI、板上构建与运行仍未完成。当前输出使用上游 signed-int demo 的内部比较；源码固定随机种子 50，没有独立归档 E 的输入/答案。本轮不修改已有失败、源配置、ABI 或答案来获得通过。
