# U280 服务器访问与目录导航

截至 2026-11-11，以下环境和目录已经由本项目的登录、构建或板测记录确认。本次整理没有重新登录或扫描服务器；目录内容、空闲卡和设备编号以使用时的检查为准。

公开仓库使用 `<SERVER_HOST>`、`<SERVER_USER>` 占位符，脚本中的 `192.0.2.28` / `u280user` 同样是示例，不能直接连接。实际账号、地址及本机命令见本地 `environment/server-access/SERVER_ACCESS_LOCAL.md`，该目录不提交 GitHub。密码只在 SSH 窗口输入。

## 如何登录

需要获授权的账号，以及能够访问服务器内网的网络。首次连接先向管理员核对 SSH 主机指纹；后续使用已确认的 known_hosts。

普通终端的交互式登录方式：

```bash
ssh -p 22 <SERVER_USER>@<SERVER_HOST>
```

在本项目 Windows 工作区，本机既有的 WLAN 绑定入口是：

```powershell
Set-Location D:\Vortex-U280
& .\scripts\Connect-U280Server.ps1
```

此脚本只执行 `id -un` 和 `hostname` 后退出，用于检查账号，并非持续交互 shell。它使用 `scripts/wlan_ssh_proxy.py`、本机 Python 和 `environment/server-access/known_hosts`，避免改变全局路由或 VPN。公开副本需先配置脚本中的服务器地址、用户名、Python 路径以及实际网卡名称；不要将示例路径当作通用安装路径。本机交互式 WLAN 登录命令见本地访问说明。

登录后先确认当前位置和环境：

```bash
id -un
hostname
printf '%s\n' "$HOME"
source /opt/xilinx/xrt/setup.sh
xbutil examine
```

`xbutil examine` 是只读查询。实际运行还需重新确认 BDF、当次 XRT index、HOST 内存、shell/xclbin UUID、实际时钟和设备空闲；不能只根据一次枚举认定卡已被预留。runtime 的设备打开会加载 xclbin，不能用于只读盘点。

## 服务器安装了什么

| 内容 | 已确认位置或版本 | 用途 |
|---|---|---|
| XRT | `/opt/xilinx/xrt/setup.sh`；2.13.479 | `xbutil`、XRT 头文件与运行库 |
| Vitis / Vivado | `/apps/Xilinx2023/Vitis/2023.1/settings64.sh`；2023.1 | FPGA 工具环境；普通板测只需 XRT |
| U280 platform | `/opt/xilinx/platforms/xilinx_u280_gen3x16_xdma_1_202211_1/xilinx_u280_gen3x16_xdma_1_202211_1.xpfm` | D10 构建使用的平台 |
| GCC 9 | `/opt/rh/devtoolset-9/root/usr/bin/g++`；9.3.1 | 服务器 runtime 和宿主查询程序编译 |
| Python | `/usr/bin/python3`；3.6.8 | 板端入口；所需 dataclasses 0.8 由项目输入包提供 |
| 系统兼容性 | glibc 2.17；系统默认 GCC 4.8.5 | 不混用本地较新 glibc 的二进制 |

工具版本来源见 [D6 环境盘点](AB_D6_PROGRESS.md)、[D12 runtime](AB_D12_PROGRESS.md)；最新板端 Python 与执行见 [E 板测记录](../results/e-u280-unseen-20261111-v1/result.json)。已有工具无需为本次文档整理重新安装。

## 项目内容在哪里

以下路径都相对于登录账号的 `$HOME`。目录保留原 run_id，后续实验创建新目录，不覆盖历史成功或失败记录。

| 目录 / 文件 | 内容与状态 |
|---|---|
| `vortex-u280-probes/<run_id>/` | 早期环境盘点、小型综合、IP/XO 检查的输入和日志 |
| `vortex-u280-link-jobs/u280-link-20261109-103830-671/` | D10 后台完整 link 作业入口及状态记录 |
| `vortex-u280-builds/u280-link-20261109-103830-671/` | D10 完整 FPGA 构建及实现报告 |
| `vortex-u280-builds/u280-link-20261109-103830-671/out/vortex_afu.xclbin` | 当前已验证的 FPGA 成品，约 54 MB |
| `vortex-u280-runtime/u280-runtime-20261109-v4/build/lib/` | D12 `libvortex.so` 与 `libvortex-xrt.so`；当前物理 backend 使用这对库 |
| `vortex-c-runtime/c-u280-runtime-20261111-v3/` | C runtime 板上集成的输入、绑定和执行证据，41/41 通过 |
| `vortex-e-runtime/e-u280-unseen-20261111-v1/` | 最新独立新语料板测输入和原件，48/48 通过 |

最新 E 目录包括 `scripts/`（执行器）、`modules/`（六份模块）、`corpus/`（冻结输入与答案）、`binding/`（物理绑定及门禁）、`execution/e-unseen/`（逐次原始输入输出、参数和 capture），以及 `query.cpp`、`xrt_bdf`、`devices.json`。完整回传原件位于本地同名 run 的 `returned/`；公开仓库提供选定证据，见 [发布范围](PUBLICATION.md)。

只读查看示例：

```bash
ls -ld "$HOME"/vortex-u280-* "$HOME"/vortex-c-runtime "$HOME"/vortex-e-runtime
ls -lh "$HOME/vortex-u280-builds/u280-link-20261109-103830-671/out/vortex_afu.xclbin"
ls -lh "$HOME/vortex-u280-runtime/u280-runtime-20261109-v4/build/lib"
ls "$HOME/vortex-e-runtime/e-u280-unseen-20261111-v1"
```

## 当前成品与设备身份

| 文件 | SHA-256 |
|---|---|
| D10 `vortex_afu.xclbin` | `bbac2ab73073b24ba857fb34eadf22bf1c11dc745527f064c4eec61b70d2c843` |
| D12 `libvortex.so` | `d3538d2fc7c695a4a0102106aa45e9ef7a9e939fc44c3b15c547ff97d0dffe3e` |
| D12 `libvortex-xrt.so` | `250769482e98c1cee84bd165a9e2af1c7b3f74a5b77dcf389ac1f4ea5aa7a8c1` |

最新板测使用 `0000:b1:00.1`，当次 XRT index 为 3、HOST 为 256 MiB、实际时钟为 200 MHz。index 不是永久编号。固定 shell interface UUID 为 `fb2b2c5a19ed63593fea95f51fbc8eb9`，D10 xclbin UUID 为 `b60ca9fb-1506-3033-c156-e03ff687f492`。板测入口会重新核验身份，不仅依靠目录名。

## 从本机继续工作

| 目的 | 入口 |
|---|---|
| 登录身份检查 | `scripts/Connect-U280Server.ps1` |
| 环境与工具盘点 | `scripts/Collect-U280Inventory.ps1 -ToolChecks` |
| C runtime 板测 | `scripts/Invoke-CU280Runtime.ps1`；按 [C 合入说明](C_RUNTIME_MERGE.md) 先准备新输入 |
| 新语料独立板测 | `scripts/e_runtime_board.py prepare` 与 `scripts/Invoke-EUnseenU280.ps1`；按 [E 接收说明](E_RUNTIME_UNSEEN_ACCEPTANCE.md) 使用新 run_id |

板测会操作共享卡，应使用既有门禁和隔离目录。物理故障恢复仍 **NOT_RUN**，旧 DMA 停止或隔离依据 **BLOCKED**，TIMING-7 **OPEN**；这些正常执行记录不能作为复位或故障恢复证明。后续恢复实验需要平台方的可靠停止/隔离条件和专用实验窗口，详见 [恢复限制](RUNTIME_RECOVERY_20261111.md)。
