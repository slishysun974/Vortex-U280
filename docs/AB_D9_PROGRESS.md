# A/B D9：平台身份复核与首次真实 XO 构建

日期：2026-11-09，Asia/Shanghai。

## HOST/platform 实际结果

本次采集（本地记录 `results/u280-preflight-20261109-094621-277/probe.json`） 与 传输（本地记录 `results/u280-preflight-20261109-094621-277/transport.json`） PASS，SSH 退出 0。用户在本机输入密码；未保存密码。XRT help、platforminfo、设备列表与 8 张卡的 platform/dynamic-regions/memory/pcie-info 报告均退出 0。

- 8 张卡采集时 ready，前后 sysfs 快照一致，KDS contexts/outstanding execs 均为 0，已报告 CU 均 IDLE。fuser 退出 1、空输出只表示未发现当前账号可见的持有者，不是设备预留。
- 8 张卡的 `host_mem_size` 均为 0；未启用 HOST。权限查询 `sudo -n -l ...` 退出 1，stderr 为 `sudo: a password is required`，权限仍 UNCONFIRMED，不能解释为策略拒绝。
- XSA `ext_metadata.json` 的 interface UUID 为 `fb2b2c5a19ed63593fea95f51fbc8eb9`，与 8 张卡 sysfs interface UUID 一致。这是文件与已装 shell 接口的身份核对，不是已生成 xclbin 的兼容性接收。
- XPFM SHA-256：`33ffbb50935e524e4feafd0cb3b8c39429a7f911b0c42dff065e2f3097fe2bc6`；XSA SHA-256：`11c9e4acdfdb6e98e136df84c4af806d1d01a8d69a8e0c7b20477a6692010c91`。

`0000:b1:00.1` 仍可作为后续复查候选；本次 controller 版本实际/预期均为 4.3.27。运行前必须重新确认卡状态与 BDF/index；本轮没有配置、复位或加载卡。

## 首次 XO 失败及构建修正

原始构建结果（本地记录 `results/u280-preflight-20261109-095402-528/returned/build/result.json`）：输入包 288 项检查通过，XPFM/XSA 哈希与上述采集一致，platforminfo 退出 0。实际 Vivado 2023.1 退出 1、耗时 51.923 秒，没有达到 900 秒超时。首个错误是 `module 'xil_fma' not found`，之前 gate 已报告未找到 vendor IP stub。五个 IP 的输出生成日志存在，但没有 OOC 综合步骤。日志显示默认器件 `xc7vx485tffg1157-1`，与 U280 候选不一致。不能把其他 18 条错误都当成已修复的级联错误。

新增显式 `ip-ooc-v1` 构建流程版本，四处 Tcl 补丁只落在新工作目录的 `flow/`：传递已配置的 U280 part、串行综合五个 IP 并检查生成 stub、为 elaboration/package 工程指定相同 part。固定源码、D8 输入包、候选配置与 ABI 不改。补丁逐文件原/新哈希和 unified diff 均保存，模块接口检查器不变，error gate 不关闭。原理、官方依据与接收边界见 [构建补丁](../environment/u280-fpga/PATCHES.md)。

## 修正后实际 XO：PASS

[成功运行](../results/u280-preflight-20261109-100406-629/returned/build/result.json)：SSH 0、platforminfo 0、Vivado 0，Vivado 耗时 340.708 秒，没有超时。实际器件为 `xcu280-fsvh2892-2L-e`。五个 floating_point IP（fadd/fdiv/fma/fmul/fsqrt）的 OOC 综合完成，远端记录了每个 XCI、DCP、Verilog/VHDL stub 的路径、大小与哈希。RTL elaboration 成功；固定模块接口检查器报告 13 类模块、22 个实例的已检查前向边界无未寄存网络，并输出 PASS。这不扩展为所有未列入检查的 AFU 信号或板上时序证明。

XO 产物为 312,868 字节，SHA-256 `58ff5ed950d738f232f5fa70e4c4fcf82ebd2b73bb3d247cfc00133f51e66b0d`，保存在服务器：

```text
/home/u280user/vortex-u280-builds/u280-preflight-20261109-100406-629/out/vortex_afu.xo
```

`flow_sha256=964e4c6c23fcdd97c47376edacd88e6d210a39f3c1ac09d0c611255689ccc630`，与本地补丁审阅副本一致。原始输入 manifest/lock 与 D8 一致。XO 二进制本轮留在服务器，本地回传日志、结果、补丁和产物哈希；未声称已在 Windows 独立重算 XO 二进制哈希。

打包的 `check_integrity` 两次通过；warning 原样保留，包括 `ap_clk` 未指定 FREQ_HZ、部分未引用文件未打包、include-dir 依赖及无 CPU emulation C-model。当前目标为 hw，但 XO 内部依赖/时钟元数据仍须随下一步 link 实测检查，XO PASS 不承诺 link 一定通过。

## 运行器与复现

`build_prepared.py` 升为结果 schema v2：输入验证由“只检查清单条目”变为完整文件集合检查；重复/越界/符号链接/损坏/遗漏/额外文件拒绝。XO 复用绑定完整输入 manifest、lock、build_flow 与 flow_sha256。失败命令、stdout/stderr 哈希、退出码和独立工作目录保存。

Windows 新入口：

```powershell
& 'D:\Vortex-U280\scripts\Invoke-U280Preflight.ps1' -ProbeKind xo `
  -PlatformRun u280-preflight-20261109-094621-277 -BuildFlow ip-ooc-v1
```

只传输 D8 固定归档及构建运行器。远端先复查 XPFM/XSA 哈希，再运行 XO；不执行 link 或卡操作。仍限制两个 CPU、nice +10、Vivado maxThreads=2、Vivado 900 秒，未设置 RAM 硬限。默认 `-BuildFlow pinned` 可复现首次未修正流程。

首轮 Linux 脚本/证据检查（本地记录 `results/ab-d9-script-checks-20261109-v1/result.json`） 142/142 通过，87 个测试中 86 通过、1 跳过；这批发生在 `ip-ooc-v1` 实施前。Windows 首轮相关测试 14/14 通过，补丁相关测试 9/9 通过；沙箱临时目录拒绝、WSL 访问拒绝与 Windows 默认 GBK 解码失败的观察记录见 本地尝试（本地记录 `results/ab-d9-local-attempts-20261109-v1/observations.json`），初步控制台没有完整项目日志，不把摘要当原始日志。GBK 问题修正为显式 UTF-8/LF，失败的局部 flow 副本保留。

补丁后的 Linux 最终自测 v2（本地记录 `results/ab-d9-script-checks-20261109-v2/result.json`） 169/169 核验通过、退出 0，88 个测试中 87 通过、1 跳过；固定源码 3329 项哈希零差异，根配置、D5/D8 候选 lock 和 D8 归档哈希不变。该记录中的 `xo_packaging=FAIL` 如实指向首次未修正的真实构建；脚本/证据 PASS 不将其改写为硬件 PASS。

成功 XO 返回后的 [最终收尾](../results/ab-d9-closeout-20261109-v1/result.json) 174/174 项通过、退出 0，`xo_packaging=PASS`，按哈希复用同一实现的 Linux v2 自测结果，没有无变化重复跑测试。复现命令为：

```powershell
python -B scripts/verify_ab_d9_results.py --run-id NEW-CLOSEOUT `
  --host-run u280-preflight-20261109-094621-277 `
  --xo-run u280-preflight-20261109-100406-629 `
  --checks-run ab-d9-script-checks-20261109-v2
```

## 未完成

本轮未重新执行原生 SimX/处理器 RTL/NOXRT AFU kernel，未执行 PTX 设备 kernel。完整 Vortex 综合、布局布线、时序、xclbin、HOST 通路和板上功能仍未接收。大型构建前继续按用户已有要求确认资源与作业规则；小型 vendor IP OOC 或 XO 不替代完整 FPGA 接收。

下一步的具体远端命令与资源方案见 [link 准备单](../environment/u280-fpga/NEXT_LINK.md)，尚未执行。HOST 配置权限仍需本机交互式 sudo 确认；未配置卡。默认 runtime 编译时钟仍为 400 MHz，不能用于当前 200 MHz 构建目标的性能报告。
