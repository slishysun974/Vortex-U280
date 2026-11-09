# A/B D2：独立仿真环境与离线依赖

日期：2026-11-08，Asia/Shanghai。用户已授权新建独立 Ubuntu 22.04 WSL、安装构建依赖与固定 Vortex 工具包，并继续原生 SimX。U280 权限仍未提供，本轮没有远程或设备操作。

**本轮已收尾并按用户要求暂停。原生上游 SimX demo 已通过；后续阶段等待新的恢复指示。**

## 已新增的实际证据

| 项目 | 当前结果 | 证据与范围 |
|---|---|---|
| 原有 Linux 复查 | 仍为 Ubuntu 20.04 / glibc 2.31 | 新盘点（本地记录 `results/ab-d2-host-20261108-v1.json`）；未升级此发行版 |
| 独立 WSL 创建 | PASS | 第一次 FAIL（本地记录 `results/ab-d2-wsl-create-20261108-v1/summary.json`），下载返回 `Wsl/InstallDistro/0x80072f78`；web-download 成功（本地记录 `results/ab-d2-wsl-create-20261108-v2/summary.json`），退出 0 |
| 独立宿主依赖安装 | PASS | 安装日志与退出码（本地记录 `results/ab-d2-host-setup-20261108-v1/summary.json`）；仅作用于新发行版 |
| 新宿主盘点 | PASS（采集范围） | 完整 JSON（本地记录 `results/ab-d2-newhost-20261108-v1.json`）：glibc 2.35、G++ 11.4.0、CMake 3.22.1、Python 3.10.12 |
| 固定工具包下载 | PASS | 首轮超时 FAIL（本地记录 `results/ab-d2-toolchain-download-20261108-v1/summary.json`） 保留；第二轮 PASS（本地记录 `results/ab-d2-toolchain-download-20261108-v2/summary.json`），固定 `8c64cf...` 的 15 项全部匹配 Git blob、大小并记录 SHA-256 |
| Ramulator 三项依赖 | PASS（源码取得与完整性） | 采集证据（本地记录 `results/ab-d2-ramulator-deps-20261108-v1/summary.json`），逐文件清单（本地记录 `results/ab-d2-ramulator-deps-20261108-v1/dependencies/bundle.json`）；未放入固定上游检出 |
| 固定工具包提取 | PASS（准备范围） | NTFS 提取（本地记录 `results/ab-d2-toolchain-install-20261108-v1/summary.json`） 与 Linux 原生提取（本地记录 `results/ab-d2-toolchain-install-20261108-v2/summary.json`） 均成功；后续使用后者。切换时首轮已自然结束，恢复记录的中止 PID 列表为空，没有把成功轮改记失败 |
| softfloat/Ramulator 宿主库 | PASS（仅库构建） | 独立构建与源码不变核验（本地记录 `results/ab-d2-hostlibs-20261108-v1/summary.json`），CMake 离线配置、构建均退出 0；不是 Vortex kernel 通过 |
| Linux 原生固定源码 | PASS（身份与完整性） | 本地对象检出（本地记录 `results/ab-d2-native-source-20261108-v1/summary.json`）：同一 Vortex/子模块提交、3329 文件零差异、Git diff 与子模块命令退出 0；原始上游保留 |
| 原生 SimX demo | **PASS（仅上游整数）** | [完整结果](../results/ab-d2-simx-20261108-v2/summary.json)、原始输出（本地记录 `results/ab-d2-simx-20261108-v2/logs/35_demo_run.log`）、最外层退出码（本地记录 `results/ab-d2-simx-20261108-v2/root-tool-completion.json`）；16 个整数内部校验，`PASSED!`，全部构建/运行命令退出 0 |
| 最终运行器自测 | PASS（脚本范围） | 共 16 项：Linux 15 通过/1 跳过（本地记录 `results/ab-d2-final-tests-linux-20261108-v1/summary.json`），Windows 11 通过/5 跳过（本地记录 `results/ab-d2-final-tests-windows-20261108-v1/summary.json`）；包括进程组超时、缓存篡改拒绝、隔离复制、提取路径与目录防覆盖 |

通过范围是 RV64 / 1 cluster / 1 core / 4 warps / 4 threads 的上游 signed-int demo，`-n1` 实际处理 16 个元素，日志为 `grid_dim=4x1, block_dim=4x1`。它没有接收 E 的 copy/vadd/affine u32 独立答案，不证明 B=32、溢出、尾线程或假谓词无访存。处理器 RTL、XRT AFU、PTX 和 U280 仍未运行/接收；日志中的模型计数不当作板上性能。

原 NTFS 路线的 check-only（本地记录 `results/ab-d2-simx-preflight-20261108-v1/summary.json`） 与 构建尝试 v1（本地记录 `results/ab-d2-simx-20261108-v1/summary.json`） 为 BLOCKED，Vortex demo 均 NOT_RUN：唯一阻塞是 `git diff` 在 120 秒内未结束，文件哈希和全部编译探针相符。随后使用已核验的原生固定检出，保留原运行，不放宽身份检查或改变源码取得 PASS。

## 固定依赖与运行器变化

Ramulator 的 CMake 声明引用以下三个标签，本轮用上游 Git 查询解析成完整提交并下载固定对象：

| 依赖 | 上游标签 | 完整提交 |
|---|---|---|
| yaml-cpp | yaml-cpp-0.7.0 | `0579ae3d976091d7d664aa9d2527e0d0cff25763` |
| spdlog | v1.11.0 | `ad0e89cbfb4d0c1ce4d097e134eb7be67baebb36` |
| argparse | v2.9 | `997da9255618311d1fcb0135ce86022729d1f1cb` |

新增 `scripts/native_dependencies.py` 按固定提交准备独立缓存并生成 `bundle.json`。`run_native_smoke.py` 增加 `--ramulator-deps`；预检核验依赖身份和全部文件哈希，实际构建前再次核验并复制到本轮 `build/third_party/ramulator/ext/`。依赖树中新增、缺失、改写文件均拒绝；Git 元数据不进入构建副本。另增加 `--build-dir`，拒绝复用现有构建、污染源码/工具目录，将配置、demo、kernel/反汇编审阅副本与哈希留在 results。运行结果 schema 升为 2；未改变硬件配置、ABI 或 PTX 白名单，未修改 `upstream/vortex/`。

新增 `scripts/prepare_toolchain.py` 下载固定提交的最小 SimX 工具，保留分卷、重组归档和哈希，支持校验后复用失败运行中的完整分卷；提取只在 Linux x86_64 进行，始终使用新目录。

宿主配方、创建方式、依赖缓存命令见 [environment/native-sim](../environment/native-sim/README.md)。B 线新增 [账号与分配卡接收单](U280_ACCESS_CHECKLIST.md)，待资源方提供入口、账号、BDF、配额与操作范围后再做实测。

## 验证边界

Windows 首次自测受沙箱临时目录权限影响失败，未算作代码 PASS。沙箱外复测完成时为 11 项、10 通过/1 Linux 专属跳过，原始分段工具返回见 `results/ab-d2-validation-20261108-v1/`；之后新增三项提取测试，14 项完整版本已在新 Linux 通过。另在原 Ubuntu 20.04 执行过 11 项脚本测试，日志（本地记录 `results/ab-d2-linux-validation-20261108-v1/summary.json`） 中 10 通过/1 Windows 专属跳过。

本轮未取得独立 E 接收、PTX P0、处理器 RTL、XRT AFU 或 U280 板上证据。实际 SimX 输出与状态已在上表单列；不把依赖准备、脚本测试或新环境安装替代 kernel 正确性。

## draft-v2 元数据与接收说明

`target_lock` / `target_caps` schema 更新为 draft-v2，记录已取得的工具归档/二进制哈希、实际版本、上游 runtime/SimX 构建与 demo PASS。`frozen=false`；物理配置、XLEN、源码/工具包提交、ABI、PTX 白名单均不变，所有 P0、恢复、异常和板上 verified 字段没有提升。

实际 demo 执行引用的是原 draft-v1 lock 哈希 `81a2ddacf55ff4ed293781e7ac11e6a019f7e1f3673f2ce38ce7fa7fdd9117fa`。更新后的 draft-v2 哈希为 `c7d0b78995d02fc8529b4157b794f991a058ced237c520703bf83094d74b8824`；caps 同步绑定新哈希。新 lock 的 `observations.executed_lock_sha256` 指向真实执行快照，避免把旧运行解释为事先使用新元数据。变更前后文件和对应关系见 收尾目录（本地记录 `results/ab-d2-closeout-20261108-v1/result.json`）。

C/D/E 接收时应审核本轮范围并使用当前 hash；不把上游 demo 当成项目模块 ABI 验收。`capture_target.py` 仍是原 draft-v1 初始化器，会覆盖当前 configs，不能用于日常只读核查。更新后的锁文件已通过 最后 check-only 预检（本地记录 `results/ab-d2-final-preflight-20261108-v1/summary.json`），退出 0、零阻塞，`upstream_smoke=NOT_RUN`；此收尾步骤只核验身份、哈希链与探针，没有再次启动 kernel 或构建。

## 成功命令与暂停交接

从工程根目录执行的成功命令如下；它已经执行，不能再次使用同一 run-id 或构建目录：

```powershell
wsl -d Vortex-AB-Ubuntu-22.04 -u root --cd /mnt/d/Vortex-U280 -- python3 -B scripts/run_native_smoke.py --backend simx --source /opt/vortex-ab/sources/vortex-7fe19369587c-v1 --tooldir /opt/vortex-ab/toolchains/8c64cf921d3c6c456e80f00d24482d0aa2153a82-simx-v2 --ramulator-deps results/ab-d2-ramulator-deps-20261108-v1/dependencies --build-dir /opt/vortex-ab/builds/ab-d2-simx-run-20261108-v2 --run-id ab-d2-simx-20261108-v2 --jobs 4 --timeout 1800
```

结果保留原始命令、逐命令输出/退出码/耗时、配置快照、3329 文件清单、第三方来源清单、工具版本/哈希，以及 artifacts（本地记录 `results/ab-d2-simx-20261108-v2/artifacts`） 中的 demo、kernel.vxbin、ELF、反汇编和生成配置。成功构建保存在独立 WSL 原生目录，原始日志中的路径不改写。

本轮暂停后，不自动启动 RTL、AFU、板上或 AI 对照实验。恢复后的候选顺序：独立复跑/能力与 ABI 接收 → 同配置处理器 RTL → 单独 XRT AFU → 项目 P0 集成；U280 等待账号与卡分配。无板卡性能、时序/资源或 xclbin 可报告。
