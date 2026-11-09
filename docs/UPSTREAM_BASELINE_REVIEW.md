# Vortex A/B 上游基线审查

审查日：2026-11-07。范围：版本、原生 RV64 SimX/RTL 路径、工具包规模与 U280 构建条件。已阅读本项目的 AB_EXECUTION_PLAN、COLLABORATION_PROTOCOL、PTX_COMPATIBILITY_PROFILE。**本文是来源与构建入口审查；没有下载大型工具包，没有运行 Vortex，没有验证任何候选组合。** 不替代 target_lock、target_caps 或 STATUS 中的执行证据。

## 1. 建议先固定的候选

建议使用当前 v3.0 release 所指向的完整源码 SHA，在 Ubuntu 22.04 x86_64 环境先运行原生整数 demo。工具包也固定完整 SHA；原生 SimX 成功后才把组合升级为已验证 lock。本文的选择理由是：release 已包含新版配置生成、CP/KMU 与配套 runtime；工具获取路径明确；不需要额外安装 OpenCL/HIP/Vulkan 栈即可验证原生程序。

| 项目 | 2026-11-07 核查值 | 使用边界 |
|---|---|---|
| Vortex release | `v3.0` | 标签只是便于识别；锁定下面的 SHA |
| 推荐源码 SHA | `7fe19369587c087f902c3e2bc2add612aa910a95` | 该 commit 元数据日期为 2026-10-07；不要把 release 页面最初发布日期当成源码时间 |
| 当前 master | `48fc0069d24899fab280b8a2e388955e4296d46c` | 2026-11-02，增加 RHEL9 工具包支持；不是本次首选源码 |
| 源码 VERSION 的工具标签 | `v3.0.1` | 上游多次刷新同名标签，单写标签不足以复现 |
| 工具包当前完整 SHA | `8c64cf921d3c6c456e80f00d24482d0aa2153a82` | 2026-11-06 刷新；本次候选固定这个对象，不随标签移动 |
| LLVM | LLVM 20.1.8 Vortex 分支；当前 focal 包源码标识 `1e6610b8e5ed` | 实际安装后仍需保存 `clang --version`、二进制/归档哈希 |
| Verilator | `5.050` | 使用该工具包版本，不自行替换成更新版本 |
| GNU RISC-V、libc、compiler-rt | 上述工具包 SHA 的 `riscv64-gnu-toolchain`、`libc64`、`libcrt64` | GNU 二进制实际版本尚未运行核实；不能从旧 Makefile 注释推断 |
| VOLT / PTX 后端 | 未选定 | 本次仅原生 C/C++ 路径，须由 C/D 接收并另行固定 |

来源：[release 列表](https://github.com/vortexgpgpu/vortex/releases)、[源码 commit](https://github.com/vortexgpgpu/vortex/commit/7fe19369587c087f902c3e2bc2add612aa910a95)、[VERSION](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/VERSION)、[工具包刷新记录](https://github.com/vortexgpgpu/vortex-toolchain-prebuilt/commit/8c64cf921d3c6c456e80f00d24482d0aa2153a82)、[工具包 README](https://github.com/vortexgpgpu/vortex-toolchain-prebuilt/blob/8c64cf921d3c6c456e80f00d24482d0aa2153a82/README.md)。工具包 `git ls-remote` 的 HEAD/master 与 v3.0.1 tag 在本次只读查询中均返回上述 `8c64cf...`。

新工具包 README 声明，新增 wide-load/store 由额外 `+xvortexldstwide` 特性控制，仅用 `+xvortex` 不引入新指令。这是上游兼容性声明，不是本项目测试结果。若该包在 RV64 回归中出现问题，可单独评估 2026-10-12 的 RV64 修复包 SHA `a57278b0a23d56bd2b279d5a095bb0f295d45387`，其 LLVM 标识为 `a81a5957f406`；不得静默替换依赖。[当前刷新说明](https://github.com/vortexgpgpu/vortex-toolchain-prebuilt/commit/8c64cf921d3c6c456e80f00d24482d0aa2153a82)、[较早 RV64 修复包](https://github.com/vortexgpgpu/vortex-toolchain-prebuilt/commit/a57278b0a23d56bd2b279d5a095bb0f295d45387)

**宿主系统要求容易误判。** `ubuntu/focal` 是包目录名；官方明确写其当前 LLVM/Verilator 等包需要 glibc 2.35 / GLIBCXX_3.4.30。因此已有 Ubuntu 20.04 WSL 不能只凭目录名判定可用。优先用 Ubuntu 22.04；若只有 20.04，保留环境阻塞并另建合适环境，或独立源码构建所需工具。RHEL9 需评估 master 的配套修复，不把 v3.0 的 CentOS7 映射当成已可用。[工具包系统说明](https://github.com/vortexgpgpu/vortex-toolchain-prebuilt/blob/8c64cf921d3c6c456e80f00d24482d0aa2153a82/README.md)、[RHEL9 修复](https://github.com/vortexgpgpu/vortex/commit/48fc0069d24899fab280b8a2e388955e4296d46c)

## 2. 小配置与项目 P0 配置要分开

固定源码的默认小配置是 1 cluster、1 core、4 warps/core、4 threads/warp、SIMD width 4，L1 指令/数据缓存各 16 KiB，L2/L3 关闭。RV64 默认打开 M/F/D/Zicond，TCU、DXA、图形、VM、A/C 扩展关闭。不要因为 P0 只接受整数 PTX 就随意关掉 F/D：上游 RV64 kernel ABI 使用 `rv64imafd/lp64d`，删硬件扩展还需同步库和编译选项。[配置源码](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/VX_config.toml)、[kernel 构建](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/sw/kernel/Makefile)

| 候选 ID | cluster/core/warp/thread | 用途 | 状态 |
|---|---|---|---|
| `rv64-smoke-1c4w4t` | 1 / 1 / 4 / 4 | 最早跑通上游整数 demo | NOT_RUN |
| `rv64-p0-1c4w8t` | 1 / 1 / 4 / 8 | 给项目默认逻辑 block=32 留足单 core 驻留线程；优先正式候选 | NOT_RUN |

这里的“最小”是小型排错配置，不声称资源极限最小。4w4t 只有 16 个物理线程；上游 1D 自动 occupancy helper 的 block 大小也是 threads×warps=16，不能据此承诺项目 B=32 已被支持。4w8t 的选择是基于容量的设计判断，仍须测试 CTA/尾线程、其他合法 B 和超限拒绝。[occupancy helper](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/sw/runtime/common/runtime_helpers.cpp)

RV64 默认 core memory address width 是 48，默认仿真平台是 2 bank、48 位；这不等于 U280 的实际地址能力。U280 配置另见第 5 节。`target_caps` 需区分 ISA 指针宽度、核心访存位宽、实际平台可访问范围。[配置源码](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/VX_config.toml)

相同的 core/warp/thread 参数不代表各 backend 的全部实现选择完全相同。独立运行配置生成器而不加 backend 宏时 FPU_TYPE 解析为 STD；rtlsim Makefile 自动加入 `SIMULATION/SV_DPI` 后默认选 DPI；XRT 综合默认选 DSP。因此需记录每个 backend 的实际编译宏、解析结果和报告，不能将一份通用解析 hash 冒充已构建 RTL/FPGA 的完整配置身份。[rtlsim 构建](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/sim/rtlsim/Makefile)、[配置来源](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/VX_config.toml)

## 3. 最快原生执行入口（尚未执行）

以下在新的 Linux 工作目录执行，工具目录必须隔离，因为上游安装器会替换该目录下的同名组件。优先使用 Linux 原生文件系统构建；下列路径由执行者放入获准工作区。第一段只准备源码，不安装系统包或更改设备。

```bash
set -euo pipefail
mkdir -p vortex-ab-review
cd vortex-ab-review
git init source
git -C source remote add origin https://github.com/vortexgpgpu/vortex.git
git -C source fetch --depth=1 origin 7fe19369587c087f902c3e2bc2add612aa910a95
git -C source checkout --detach FETCH_HEAD
git -C source submodule update --init --recursive
git -C source submodule status --recursive > submodules.txt
mkdir -p source/build-ab64
cd source/build-ab64
AB_TOOLDIR="$(pwd)/tools-v3-8c64cf"
../configure --xlen=64 --tooldir="$AB_TOOLDIR"
TOOLCHAIN_REV=8c64cf921d3c6c456e80f00d24482d0aa2153a82 \
  ./ci/toolchain_install.sh --riscv64 --llvm --libcrt64 --libc64
```

宿主至少需 build-essential、cmake、Python3、git、wget、bzip2、zlib/libtinfo/libncurses 开发包；完整安装指南还列 uuid、boost-serialization、png、hwloc 等依赖。先由盘点脚本确认，缺项再按实际系统安装。Ramulator 的构建可能额外取其依赖，源码与子模块下载量未计入下面工具包表。[安装说明](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/docs/install_vortex.md)、[工具安装器](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/ci/toolchain_install.sh.in)

```bash
# 仍在 source/build-ab64；先记录真实工具版本
"$AB_TOOLDIR/llvm-vortex/bin/clang" --version
"$AB_TOOLDIR/riscv64-gnu-toolchain/bin/riscv64-unknown-elf-gcc" --version
make -C ../third_party softfloat ramulator
make -C sw/kernel
make -C sw/runtime/stub

# 上游整数 demo；-n1 在此表示每个任务处理 1 个元素
./ci/blackbox.sh --driver=simx --app=demo \
  --clusters=1 --cores=1 --warps=4 --threads=4 --args="-n1"

# 进入 P0 候选配置后，SimX/RTL 都使用同一 4w8t 配置
./ci/blackbox.sh --driver=simx --app=demo \
  --clusters=1 --cores=1 --warps=4 --threads=8 --args="-n1 -x32"

TOOLCHAIN_REV=8c64cf921d3c6c456e80f00d24482d0aa2153a82 \
  ./ci/toolchain_install.sh --verilator
"$AB_TOOLDIR/verilator/bin/verilator" --version
./ci/blackbox.sh --driver=rtlsim --app=demo \
  --clusters=1 --cores=1 --warps=4 --threads=8 --args="-n1 -x32"
```

这些是逐个执行的候选命令；应由项目运行器保存完整 stdout/stderr、命令、退出码与配置 hash，不仅截取 PASSED 一行。源码将 `CONFIGS` 同时传给 runtime、kernel 和 host 的构建；调整配置后仍要核查库是否按预期重建。v3 使用构建文件中的绝对工具路径，不再需要旧的 `source ci/toolchain_env.sh`。[blackbox 源码](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/ci/blackbox.sh)、[原生测试公共构建](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/tests/regression/common.mk)、[第三方构建](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/third_party/Makefile)

demo 默认 TYPE=int，具有上游内部比较，但使用有符号 int 随机加法，不能作为本项目 u32 模 2^32 的独立 oracle。4w4t 的 `-n1` 处理 16 个元素；4w8t 的 `-n1 -x32` 处理 32 个元素。上游 vecadd 当前是浮点示例，不应记成 P0 整数验证。项目 copy/vadd/affine 及 N=0/尾线程/哨兵/假谓词无访存必须另接 E 的用例；demo 的 `-n0` 不能替代规定的 N=0 合法启动测试。[demo 类型与参数](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/tests/regression/demo/common.h)、[demo host](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/tests/regression/demo/main.cpp)、[vecadd host](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/tests/regression/vecadd/main.cpp)

原生路径不需要先安装 POCL、chipStar、Mesa、gem5、SST、FireSim、Yosys 或 VOLT。首次也不采用最新 master 文档才有的 `--profile` 或 `SIMX_FUNCTIONAL` 示例；能力与选项必须来自冻结 SHA。实际 `v3.0` configure 不提供 `--profile`。[冻结 configure](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/configure)

## 4. 下载与构建资源

以下为工具包 SHA `8c64cf...` 的 GitHub Git tree 元数据求和，**仅压缩包传输大小**，没有下载压缩包或测解压后大小。每个大包以 50 MiB 分卷；不要 clone 整个 prebuilt 仓库和其历史。

| 组件 | 文件数 | 压缩字节数 | 约 MiB |
|---|---:|---:|---:|
| riscv64-gnu-toolchain / ubuntu/focal | 10 | 497,288,955 | 474.25 |
| llvm-vortex / ubuntu/focal | 3 | 108,726,342 | 103.69 |
| libc64 | 1 | 799,142 | 0.76 |
| libcrt64 | 1 | 50,923 | 0.05 |
| SimX 所需上述合计 | 15 | 606,865,362 | 578.75 |
| Verilator / ubuntu/focal（RTL 增量） | 3 | 113,881,095 | 108.61 |
| 合计 | 18 | 720,746,457 | 687.36 |

核查接口：[固定 Git tree](https://api.github.com/repos/vortexgpgpu/vortex-toolchain-prebuilt/git/trees/8c64cf921d3c6c456e80f00d24482d0aa2153a82?recursive=1)。Git blob SHA 是 Git 对象身份，不应冒充下载内容 SHA-256；正式安装应额外保留每个分卷或重组归档的 SHA-256。安装器会删除下载归档，若要留证据应在独立下载层先缓存并校验，或为安装器增加经记录的缓存补丁。

本地空间规划建议预留 10 GiB 以上给源码、工具、重组压缩包、解压树及小规模 SimX/RTL 产物；以 4 个并行编译任务起步，宿主可用内存 16 GiB 较稳妥。这是工程预算，**不是已测占用或上游最低要求**。FPGA 构建应单独盘点更多磁盘/内存，上游给过 16 CPU、64 GiB、6 小时的调度示例，不能用它承诺 U280 1c4w8t 的实际构建时间。[FPGA 指南](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/docs/fpga_setup.md)

Verilator 版本有实际风险证据：上游将 5.052 回退到 5.050，记录前者在其最小 RTL 配置的 elaboration 占用异常增至约 204 GiB，而 5.050 约 0.54 GiB。这是上游那次测量，不是本机本配置的预测；因此本次优先沿用包内 5.050。[回退 commit](https://github.com/vortexgpgpu/vortex-toolchain-prebuilt/commit/2e57cf8ca861f6dbae33d0cfa4d6c478148967ae)

## 5. U280 构建条件与入口

源码的 XRT `platforms.mk` 有 U280 分支：32 个 HBM bank，平台地址宽度 33，`m_axi_mem_0` 连接 `HBM[0:31]`；另将 CP 的 `m_axi_host` 连接 `HOST[0]`。因此板上除了 HBM 数据通路，还必须满足 host-memory/slave-bridge 通路。该 U280 分支不像 U50/U55C 分支那样显式设置 `PLATFORM_MERGED_MEMORY_INTERFACE`；应按实际平台和生成 RTL 检查端口/连接，不能先宣称已验证。[冻结平台配置](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/hw/syn/xilinx/xrt/platforms.mk)

构建前必须收集实际 `v++ --version`、`vivado -version`、XRT 版本、`platforminfo -l` 及选定平台详情、卡 BDF/shell/驱动、许可、RAM/磁盘与排期。上游文档示例是 Vitis 2023.1，且列过多个不同日期的 U280 platform 名；这不证明任意 platform 与工具组合可互换。当前没有本项目服务器事实，因此 **Vitis/XRT/platform 版本保持待定**。[FPGA 指南](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/docs/fpga_setup.md)

当环境与工具匹配已核实，以下作为构建模板。`AB_PLATFORM` 必须填 `platforminfo` 实际返回的 U280 平台名/路径，`source` 路径也取本机事实。首轮目标频率 200 MHz 是保守工程选择，不是上游已通过参数；要保存实际频率与时序报告。

```bash
# source <actual-XRT-setup.sh>
# source <actual-Vitis-settings64.sh>
# 在 source/build-ab64 下，先将 AB_PLATFORM 设为真实平台
: "${AB_PLATFORM:?set an inventoried U280 platform first}"
make -C hw/syn/xilinx/xrt TARGET=hw PLATFORM="$AB_PLATFORM" \
  PREFIX=ab64_1c4w8t NUM_CORES=1 \
  CONFIGS="-DVX_CFG_NUM_WARPS=4 -DVX_CFG_NUM_THREADS=8" \
  KERNEL_FREQ=200 FREQ_SCALING=0 JOBS=4
```

冻结 Makefile 的默认 KERNEL_FREQ 是 300 MHz，默认允许降频；这里显式设 `FREQ_SCALING=0`，使未满足目标频率的构建不能被当成该频点成功。生成路径为 `hw/syn/xilinx/xrt/<PREFIX>_<platform-base>_hw/bin/vortex_afu.xclbin`，同时保存 routed timing、资源报告、构建日志及 SHA-256。xclbin 存在不代表板上验证通过。[XRT Makefile](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/hw/syn/xilinx/xrt/Makefile)

硬件运行前需由有权限的管理员核实并启用 host bank。冻结指南使用 `xrt-smi configure --host-mem -d <BDF> --size 1G enable`，也说明 256M 足够典型控制缓冲；实际工具命令以安装的 XRT 为准。本文没有执行管理员命令或更改板卡。硬件仿真与真实硬件分别记录，`hw_emu` 不需启用真实卡 host bank。[host-memory 要求](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/docs/fpga_setup.md)、[XRT transport 实现](https://github.com/vortexgpgpu/vortex/blob/7fe19369587c087f902c3e2bc2add612aa910a95/sw/runtime/xrt/vortex.cpp)

```bash
# FPGA_BIN_DIR 应为实际 xclbin 的 bin 目录；仍在 build-ab64
: "${FPGA_BIN_DIR:?set the reviewed bitstream bin directory first}"
FPGA_BIN_DIR="$FPGA_BIN_DIR" TARGET=hw PLATFORM="$AB_PLATFORM" \
  ./ci/blackbox.sh --driver=xrt --app=demo \
  --clusters=1 --cores=1 --warps=4 --threads=8 --args="-n1 -x32"
```

上板前还需核对生成硬件的配置与当前 host/kernel 相同。U280 地址/内存测试、copy/vadd/affine、完成可见性、重复启动、超时恢复都仍为待执行项。FireSim 的当前实现文档限制 U55C，不将其作为 U280 的替代路径。

## 6. 下一步接收条件

1. 盘点实际 Linux 发行版/动态库，决定可运行工具包的宿主；保存源码与全部递归子模块 SHA。
2. 在隔离路径安装固定 SHA 的最小工具集，记录版本与归档/二进制哈希。
3. 分别保存 4w4t smoke 与 4w8t 项目候选的原生 SimX 结果；随后同配置 RTL。失败时保留第一处错误，不换 tag 重试后覆盖日志。
4. 与 C/D 对齐 `+xvortex`、RV64/lp64d、`vortex2.h` 与参数布局。上游 demo 的参数结构不等于项目 PTX payload。
5. 将已验证事实写入 draft lock/caps 的相应字段，E 独立复现后接收。板卡条件和板上结果另列，不用仿真成功填 U280 PASS。
