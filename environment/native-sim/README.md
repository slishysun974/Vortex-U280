# 原生仿真宿主方案

2026-11-08 用户已授权建立独立 WSL、安装构建依赖和固定工具包并执行 SimX。独立发行版与构建依赖已完成安装；D3 继续准备固定 Verilator 并执行处理器 RTL / AFU 模型，实际结果见 [D3 记录](../../docs/AB_D3_PROGRESS.md)。已有 Ubuntu 20.04 未升级，Docker daemon 仍不可连接。

## 建议：独立 Ubuntu 22.04 WSL

已新建发行版 `Vortex-AB-Ubuntu-22.04`，磁盘目录位于本项目 `environment/wsl/`。只在新增发行版内安装构建依赖，未升级原有发行版。后续可继续使用本会话已授权的该环境与固定工具组合。

首次创建命令因下载接口返回无效响应失败；增加 `--web-download` 后成功，原始失败记录保留。以下是成功方式，已有发行版不可重复创建：

```powershell
wsl --install Ubuntu-22.04 --name Vortex-AB-Ubuntu-22.04 --location D:\Vortex-U280\environment\wsl\Vortex-AB-Ubuntu-22.04 --no-launch --version 2 --web-download
wsl -d Vortex-AB-Ubuntu-22.04 -u root --cd /mnt/d/Vortex-U280 -- bash environment/native-sim/setup-host.sh --apply
```

`setup-host.sh` 只接受 Ubuntu 22.04 x86_64；安装编译器、CMake 和开发库，不执行发行版升级。它不能识别是否为专用宿主，执行者必须选对发行版。Ubuntu 下载体积和安装后空间尚未实测；整个源码、工具、依赖与构建建议至少预留 10 GiB，以真实占用为准。

## 固定 Vortex 工具

工具包固定为 `configs/target_lock.json` 指定的提交 `8c64cf921d3c6c456e80f00d24482d0aa2153a82`。SimX 只需 `riscv64-gnu-toolchain`、`llvm-vortex`、`libc64`、`libcrt64`。D3 的 `--profile rtlsim` 增加同一提交中的 Verilator 5.050，共 720,746,457 压缩字节、18 个分卷/单包；已核验 Git blob 与 SHA-256，并独立提取到 `/opt/vortex-ab/toolchains/8c64cf921d3c6c456e80f00d24482d0aa2153a82-rtlsim-d3-v1`。

固定 Verilator 包生成的 Makefile 会调用 `ccache`。D3 首轮在此构建失败、demo 未运行；专用 WSL 补齐 `ccache 4.5.1` 后换新目录重跑。补依赖证据（本地记录 `results/ab-d3-host-dependency-20261108-v1/summary.json`）。宿主脚本与容器配方已补上此项；容器配方仍未构建验证。

下载脚本保存分卷、重组归档、固定提交的 Git tree 和哈希；离线提取拒绝越界路径和链接。下载首轮超时保留，新运行只复用校验成功的完整分卷。脚本不会删除失败记录或旧安装目录。

```powershell
python -B scripts/prepare_toolchain.py --download --run-id toolchain-download-NEW
# 下载失败后可指定旧缓存；只复用大小和 Git blob 全部匹配的分卷。
python -B scripts/prepare_toolchain.py --download --reuse-cache results/OLD --run-id toolchain-download-NEW2
# 处理器 RTL / AFU 模型使用包含 Verilator 的完整 profile。
python -B scripts/prepare_toolchain.py --download --profile rtlsim --reuse-cache results/OLD --run-id toolchain-rtl-NEW
```

```bash
python3 -B scripts/prepare_toolchain.py --extract-cache results/toolchain-download-NEW \
  --run-id toolchain-install-NEW
```

记录真实版本与二进制哈希；不要把标签、目录名或本配方当成已验收工具身份。具体来源见 [上游审查](../../docs/UPSTREAM_BASELINE_REVIEW.md)。

## 依赖源码与离线预检

Ramulator 三项依赖已有独立缓存：`results/ab-d2-ramulator-deps-20261108-v1/dependencies`。`bundle.json` 固定三个提交并保存逐文件 SHA-256。新的缓存可在授权联网的宿主通过以下命令生成，旧 run-id 拒绝覆盖：

```powershell
python -B scripts/native_dependencies.py --fetch --run-id ramulator-deps-NEW
```

本轮已完成两次隔离提取；后续使用 Linux 原生目录 `/opt/vortex-ab/toolchains/8c64cf921d3c6c456e80f00d24482d0aa2153a82-simx-v2`。另已从本地固定 Git 对象建立 `/opt/vortex-ab/sources/vortex-7fe19369587c-v1`，完整核对 3329 个文件，与锁定清单零差异；检出与核查证据（本地记录 `results/ab-d2-native-source-20261108-v1/summary.json`）。此操作不修改项目的原始上游检出。

NTFS 上的首次预检因 `git diff` 超过 120 秒而 BLOCKED；原记录保留。以下路径分别保存固定源码、工具与新构建产物，全部位于新 WSL 的原生文件系统。日志、配置快照、逐命令退出码以及生成的 demo/kernel 审阅副本仍保存在项目的 `results/<run-id>/`。

```bash
python3 -B scripts/platform_inventory.py --output results/ab-newhost-NEW.json
python3 -B scripts/run_native_smoke.py --backend simx \
  --source /opt/vortex-ab/sources/vortex-7fe19369587c-v1 \
  --tooldir /opt/vortex-ab/toolchains/8c64cf921d3c6c456e80f00d24482d0aa2153a82-simx-v2 \
  --ramulator-deps results/ab-d2-ramulator-deps-20261108-v1/dependencies \
  --build-dir /opt/vortex-ab/builds/ab-simx-NEW \
  --run-id ab-simx-preflight-NEW --check-only
```

预检满足后去掉 `--check-only`，另换 run-id；构建目录也必须为尚不存在的新目录。运行器校验缓存，复制依赖到本轮 `build/third_party/ramulator/ext/`，然后使用 CMake 离线模式。源码包完整不等于 SimX 或 RTL 已通过，实际结果见 D3 记录。

使用新 rtlsim 工具根时，`--backend rtlsim` 执行处理器 RTL；`--backend xrtsim` 强制 `TARGET=xrtsim`，执行本地 NOXRT AFU 模型。二者均使用独立的新 build/run 目录，预检需要 Verilator 启动器、底层 ELF 和 ccache。`xrtsim` 不调用真实 XRT / 卡；整数 demo 通过也不证明 P0、浮点 RTL 或 U280 平台可用。

## 可选容器配方

`Dockerfile` 提供同样的 Ubuntu 22.04 构建依赖。没有执行镜像构建；`ubuntu:22.04` 与 apt 仓库尚未解析为本项目锁定快照，不能声称镜像可复现或已可运行。Docker 引擎可用后，应保存实际镜像摘要、软件包版本和构建日志，再选择是否使用此路线；本轮没有重试启动 Desktop。

B 线服务器、卡分配、platform/XRT/HOST[0] 验收仍独立推进。本环境只服务于无板卡原生仿真。
