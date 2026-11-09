# A/B D8：U280 源接口检查与独立 FPGA 候选

日期：2026-11-09，Asia/Shanghai。本轮延续 A/B 优先方向，完成 U280 候选和实际源预处理；未启动大型综合/布局布线、未配置或加载卡。

## 结果

| 层次 | 实际结果 |
|---|---|
| 固定源身份 | WSL 中 3329 项文件哈希与根 lock 引用的清单匹配，运行后再次匹配；固定 Verilator 二进制哈希匹配 |
| 原始 U280 分支 | gen-sources 与 make -n gen-bin 退出 0；实际生成 32 个 HBM AXI 主接口，只有端口 0 有显式连接，31 个缺少显式连接；接口契约检查 FAIL，作为被检出的负例保留 |
| 独立合并接口候选 | gen-sources 退出 0；实际生成 1 个 HBM 主接口和 HOST 主接口，与固定连接命令匹配，检查 PASS |
| FPGA 源输入包 | 288 项文件、相对路径 filelist、逐文件 SHA-256；仅源输入，不是 XO/xclbin |
| 脚本与证据 | [635/635 核验](../results/ab-d8-closeout-20261109-v1/result.json) PASS、退出 0；Python 测试 79 项中 78 通过、1 跳过 |
| 远端 HOST/platform 本轮采集 | SSH 尝试（本地记录 `results/u280-host-platform-20261109-v1/transport.json`） FAIL、SSH 255；主机密钥校验通过，在密码认证阶段结束，远端探测 NOT_RUN |
| FPGA/板上 | Vivado elaboration、XO、完整综合/实现、时序、HOST 配置、原生板上 demo 均 NOT_RUN |

原始分支的发现是“RTL 端口与显式连接不一致”，尚未实际运行 v++，不能写成已复现的链接器失败，也不排除工具自动连接行为。补充静态审阅发现固定 `package_kernel.tcl` 仍查旧名 `PLATFORM_MEMORY_NUM_BANKS`，而 filelist 为 `VX_CFG_PLATFORM_MEMORY_NUM_BANKS`；本候选显式合并后把打包 bank 数固定为 1，但通用多端口打包问题未修改。没有改动 `upstream/vortex/`。

## 候选与复现

候选 [u280-hbm32-v1](../configs/candidates/u280-hbm32-v1/README.md) 从 D5 8w×4t 独立配置派生，新增合并接口；平台宏为 32 bank / 33-bit / 512-bit，SYNTHESIS/VIVADO 解析为 DSP FPU。根 lock/caps、D5 candidate、ABI 与 PTX 白名单均保留，不继承 D5 的设备验收状态。200 MHz 为待实现目标，不是实际频率。

```powershell
wsl -d Vortex-AB-Ubuntu-22.04 --cd /mnt/d/Vortex-U280 -- python3 -B scripts/run_u280_source_preflight.py --run-id NEW
wsl -d Vortex-AB-Ubuntu-22.04 --cd /mnt/d/Vortex-U280 -- python3 -B scripts/verify_ab_d8_results.py --run-id NEW-CHECK --source-run NEW
```

本次为 ab-d8-u280-source-20261109-v1（本地记录 `results/ab-d8-u280-source-20261109-v1/summary.json`），两个隔离构建目录在 `/opt/vortex-ab/builds/ab-d8-u280-source-20261109-v1-{upstream_unmerged,candidate_merged}`。原始/候选各自 configure、实际预处理、链接 dry-run、配置解析的命令、stdout/stderr、退出码完整保存。

WSL 未安装 platforminfo；固定 Makefile 立即求值的两次探测因此在 stderr 留有 `platforminfo: not found`。本次显式传入 `DEV_ARCH=virtexuplus`、`CPU_TYPE=x86` 作为离线分支选择，配置的 platform 路径来自 D6 已有盘点。这不是本地 platforminfo 成功，不验证平台文件、XSA 或 Vivado/Vitis 兼容性。服务器上的真实复核是单独步骤。

输入包及可执行分阶段包装器见 [构建方案](../environment/u280-fpga/README.md)。构建包装器默认 inspect；XO/完整 link 需显式选择，输入哈希和新目录隔离、进程 CPU 亲和性、超时及实际日志均保留。服务器旧 glibc/G++ 与固定 WSL 二进制不兼容风险通过传输预处理源绕开 FPGA 输入阶段；真实 XRT host runtime 的编译/装载仍未解决。

包装器默认 inspect 已在专用 WSL 实际退出 0，原始结果位于 `/root/vortex-u280-builds/ab-d8-wrapper-inspect-20261109-v1/result.json`，未执行 FPGA 工具。后续还须处理 runtime 时钟元数据：当前解析的 `VX_CFG_PLATFORM_CLOCK_RATE=400` 是上游默认，`VX_CAPS_CLOCK_RATE` 返回该编译值；接板前需按真实实现频率升版并重编，不能用它报告当前 200 MHz 候选的性能。

## HOST 与下一步

新增 `Invoke-U280Preflight.ps1 -ProbeKind host-platform` 只读模式，准备输入已在 `results/u280-host-platform-offline-20261109-v1/` 保存，远端 Python 3.6 语法已检查。保留原组件综合模式为默认，不改 D7 原始结果。

本轮 SSH 日志只到密码认证，最后为 `ssh_dispatch_run_fatal ... Unknown error`，不能断言密码错误或服务器网络故障；未取得远端数据，也不能把 D7 的空闲状态当成当前状态。下一次重新运行入口使用自动生成的新 run_id，并在本机终端完成认证。

已依据 [XRT 2022.1 官方文档](https://xilinx.github.io/XRT/2022.1/html/hm.html) 整理 HOST 启用前置条件、256M 起步命令、验证与有条件恢复步骤；实际参数帮助、sudo 权限及 platform/XSA 哈希/UUID 仍待远端采集。完整综合/布局布线前按用户 D7 要求确认资源/作业规则，具体拟议限制已列在构建方案中。

本轮结果均是实施者源/脚本自测，不是 E 独立验收、PTX 执行、HBM/HOST 通路或板上功能证据。
