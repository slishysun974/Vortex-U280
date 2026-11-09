# D10 对应的 200 MHz 服务器 runtime

2026-11-09 D13 后续：两库继续有效；HOST 配置已实测被服务器 sudo 策略拒绝，最小管理员操作见 [HOST_SETUP](HOST_SETUP.md)。实现/平台 DCP 审阅已完成，TIMING-7 平台跨域项仍 OPEN，实际 200 MHz 仍待受控加载读回；详见 [D13](../../docs/AB_D13_PROGRESS.md)。权限配置本身不能替代这些技术前置条件。

**2026-11-09 D12：服务器公共库、真实 XRT backend 编译及 ldd 依赖解析 PASS，板上功能 NOT_RUN。** 使用独立 `gcc9-vm-allocation-v1` 候选 / `u280-runtime200-binding-v2`，仍 draft。实际 [v4 构建与日志](../../results/u280-runtime-20261109-v4/returned/runtime/result.json)、[D12 接收范围](../../docs/AB_D12_PROGRESS.md)、[源码/脚手架补丁](PATCHES.md)。服务器 GCC 9.3.1 / glibc 2.17 / XRT 2.13.479，无安装或系统升级。

当前库在服务器：

```text
/home/u280user/vortex-u280-runtime/u280-runtime-20261109-v4/build/lib/libvortex.so
/home/u280user/vortex-u280-runtime/u280-runtime-20261109-v4/build/lib/libvortex-xrt.so
```

本地副本在 返回目录（本地记录 `results/u280-runtime-20261109-v4/returned/runtime/lib`）。SHA-256 分别为 `d3538d2fc7c695a4a0102106aa45e9ef7a9e939fc44c3b15c547ff97d0dffe3e` 和 `250769482e98c1cee84bd165a9e2af1c7b3f74a5b77dcf389ac1f4ea5aa7a8c1`。后续运行须加载 `/opt/xilinx/xrt/setup.sh` 并使用这一对库；当前只接收编译/依赖解析，尚未调用 `vx_device_open` 或加载 xclbin。

在可见 PowerShell 终端复现新构建，脚本自动产生新 run_id；用户仅在实际 SSH `password:` 提示下输入密码：

```powershell
& 'D:\Vortex-U280\scripts\Invoke-U280Runtime.ps1' -RuntimeProfile gcc9-v1
```

此入口绑定 新输入包（本地记录 `results/u280-runtime-gcc9-prepare-20261109-v2/u280-runtime200-input.tar.gz`），SHA-256 `6911b8dcbcc0c2a4ea6aa5ea6d636de470c442159e2f062e0861227f3d05ee16`。先校验输入，再在新个人目录编译、ldd 和只读检查 HOST/platform，返回所有日志和两库；不配置 HOST、不加载板卡。两个 CPU、nice +10，每条构建命令 300 秒超时。`-PrepareOnly` 只生成输入，不连服务器。`-RuntimeProfile pinned` 保留原 D11 包，用于复现 v2 已知编译失败，不是当前通过的路线。

## 保留的 D11 输入与失败背景

采用独立 `u280-runtime200-binding-v1`，仍为 draft。输入与范围见 [D11](../../docs/AB_D11_PROGRESS.md)，输入包在 `results/u280-runtime-prepare-20261109-v1/u280-runtime200-input.tar.gz`。原有 FPGA lock 与全部旧证据保留。

固定源码要求 C++17；服务器默认 GCC 4.8.5 不能充当已验证编译器。D11 Archive v5 确认 `/opt/rh/devtoolset-9/root/usr/bin/g++` 为 GCC 9.3.1，六个 XRT C++ 头文件均存在。D12 实测原包触发 GCC 9 的未初始化变量错误；因此以下为历史原包复现命令，不是已通过的候选。

在新的个人工作目录校验原输入包 SHA-256、解包并编译：

```bash
sha256sum u280-runtime200-input.tar.gz
# 必须为 9976e187005d38005c1733d0bc5e9f337450109252bb908662fc9c4839c79b84
# 在新的空目录解包，保留旧构建与失败记录。
tar -xzf u280-runtime200-input.tar.gz
python3 -B u280-runtime200-input/build_runtime.py \
  --input "$PWD/u280-runtime200-input" \
  --output "$PWD/runtime-server-<new-run-id>" \
  --cxx /opt/rh/devtoolset-9/root/usr/bin/g++
```

构建器校验全部输入清单及绑定文件，拒绝已有输出目录；显式 TARGET=hw / RV64 / 完整预解析 XCONFIGS。D12 在新包的生成 Makefile 中避免不必要的生成器展开，源码中检查分配失败；不修改固定源码或原包。

在专用 Ubuntu 上的 `--stub-only` 结果仅证明公共库能编译，不可把该库拿到 glibc 2.17 的服务器直接使用。D12 已补真实服务器编译/依赖证据；设备打开、HOST 分配与板上功能仍需要各自的实际证据。

200 MHz 由 D10 固定时钟检查提供；本输入只将 runtime 查询常量 400→200，且自动验证其他已解析定义不变。不能将编译常量当成板卡实测频率，性能接收仍需绑定实际加载的 xclbin、设备和时钟观察。
