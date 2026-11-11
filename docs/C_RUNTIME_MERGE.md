# C Runtime 本地合入与 U280 接续

2026-11-11 后续版本：`sticky-device-fault-v1` 修复原生队列错误清除后的错误恢复放行，新增 [api_v2.json](../configs/c_runtime/api_v2.json)。三模型实际超时排空与故障封锁通过；物理 recover 继续禁用。[恢复证据](RUNTIME_RECOVERY_20261111.md)。下文 v3 为补丁前的历史交付，新板测必须匹配当前运行器与新的 E 执行记录，不能复用 v3 作为新源码执行证据。

版本：`c-runtime-integration-v1`，2026-11-11，Asia/Shanghai。来源为刘泽衡的 [GPGPU-runtime 固定提交](https://github.com/LiuZeheng123/GPGPU-runtime/tree/7f3575db67888c03d1c2c4dc3743051c735519dd)。本地目录不是 Git 工作树，本次“合入”指项目文件与调用入口已经集成，不表示已推送或合并公共仓库。

## 代码与版本

[导入记录](../results/c-runtime-import-20261111-v1/result.json)保存 15 个导入文件的来源、原始/导入 SHA-256 和保护项。C 原检出和旧 results 保留。共同协议见 [合作协议](COLLABORATION_PROTOCOL.md)；新的机器接口说明见 [api_v1.json](../configs/c_runtime/api_v1.json)。

| 入口 | 用途与版本 |
|---|---|
| `scripts/ptx_frontend.py` | 原 v1 保持原始字节，服务旧冻结构建与接收记录 |
| `scripts/ptx_frontend_v12.py` | C v1.2 加 `python36-integer-v1` 等价宿主兼容补丁；新增模块/参数层显式引用此版本 |
| `scripts/ptx_module.py` | prepare/build/validate；原仿真 schema v1 保持兼容，板上目标使用独立 `ptx-vx-module-u280-v2-draft` |
| `scripts/ptx_launch.py`、`scripts/ptx_runtime.py` | BufferSlice、模块/队列/event、E_BUSY、参数快照、完成及资源管理 |
| `scripts/bind_simx_runtime.py` | 三种仿真后端的 v3 binding；ldd 显式使用本后端库目录，避免跨后端继承 |
| `scripts/ptx_u280.py` | 独立 `u280-xrt` 后端及 `ptx-vx-u280-binding-v1`；不接受 NOXRT 模型绑定 |
| `scripts/run_c_runtime_smoke.py` | 显式模块/后端的固定整数 smoke；完整输入/输出/哨兵和参数捕获 |
| `scripts/validate_c_runtime_merge.py` | 合并自测、六个模块新构建、三路实际执行和镜像/数组对照 |
| `scripts/Invoke-CU280Runtime.ps1` | 准备、一次 SSH 执行和接收 C API 的板测；先检查准备包原始字节 |

PTX 白名单、参数布局 `ptx-vx-args-v1`、线程坐标和核心规模没有改变。前端版本变化仅为未使用变量标注和原地 mov/cvta 的等价空操作；IR 中 compiler_id 按版本区分，生成头文件哈希也区分。不能改写旧产物以迎合 v1.2。

宿主兼容补丁 `python36-integer-v1` 将 `str.removesuffix("U")` 改为相同的单后缀判断/切片，支持服务器 CPython 3.6.8。整数进制、符号、U 后缀、溢出与非法输入结果与原实现逐项比较；源码哈希随新构建记录，C 原检出与旧生成包保持。构建入口仍要求现有 WSL 环境，不宣称 Python 3.6 能运行本地构建流程。

U280 模块适配只接受当前 D10/D12 的完整 board lock SHA-256 `e55719ecaa83d1b0f637cf212819716c58667443918f822eaed9ee2eb2aa7486`，保留 `PLATFORM_MERGED_MEMORY_INTERFACE=true`，不把仿真 lock 改名使用。wrapper 和原生入口 `main` 与 C 原版一致；新 schema 标识的是板上目标适配，不改变参数 ABI。根/candidate lock、caps 与旧 profile 都不改写或宣称 frozen。

## 调用与复现

应用显式设置 `VORTEX_DRIVER`、`LD_LIBRARY_PATH`，一个进程使用一套 binding。基本调用顺序为 `Context → alloc/write → load → launch → wait → read → free/unload/close`；指针使用 `BufferSlice`，不把 host 地址塞进 payload。`launch` 返回前复制参数，可连续 launch；同一 context 同时只允许一个已装载模块和一个在途 kernel。

完整本地验证使用未使用过的 run_id：

```powershell
wsl -d Vortex-AB-Ubuntu-22.04 --cd /mnt/d/Vortex-U280 -- python3 -B scripts/validate_c_runtime_merge.py --run-id c-runtime-merge-NEW
```

从上述成功记录准备板测，`SOURCE` 替换为已经通过的 `c-runtime-merge-...`，`NEW` 为未使用的运行编号：

```powershell
./scripts/Invoke-CU280Runtime.ps1 -PrepareOnly -SourceRun SOURCE -RunId c-u280-runtime-NEW
./scripts/Invoke-CU280Runtime.ps1 -Prepared -RunId c-u280-runtime-NEW
```

默认为 b1；可用 `-Bdf` 显式选择现有允许清单中的其他卡，准备和执行必须一致。失败后使用新 run_id；已有 transport 不能重试覆盖。密码仅在本机 SSH 提示下输入，不写入脚本、结果或聊天。板测输入在准备时重新核对三路命令/日志、运行器源码、每份捕获和板上模块，板端返回原始字节后在本地再次核对。

## 物理后端的检查与边界

物理 binding 绑定 D10 xclbin、D12 两库、目标 lock、硬件配置、C++ XRT BDF 查询工具和显式卡号。每次打开前重新检查 shell、ready、HOST ≥256 MiB、KDS 和普通账号可见持有者，核对 xbutil 与 C++ XRT 的 index/BDF 映射；普通账号检查不等于独占预留。打开后读取 UUID 与实际 DATA_CLK=200 MHz，通过后才创建工作队列；关闭设备后再次检查空闲。

板端仅编译轻量 BDF 查询工具，不重建 FPGA、不安装工具、不运行 sudo 或更改 HOST。bootstrap 选用现有 Python ≥3.6：3.6 使用随输入包携带的原版 [dataclasses 0.8](https://pypi.org/project/dataclasses/0.8/)，≥3.7 使用标准库，不向系统或用户 site-packages 安装依赖。[第三方来源、文件哈希和许可证](../third_party/dataclasses-0.8/provenance.json)纳入输入清单。先在实际解释器上校验三份模块、dataclass 的身份/冻结/默认值、参数布局和在途资源拒绝，通过后才检查并打开设备。构建仍在既有 WSL Python 3.10 环境进行，板端 Python 3.6 只做校验和执行。模型库不能替代 D12 的 glibc 2.17 物理库。

仿真 `recover()` 保留 C 的有限队列排空语义。物理 `recover()` 明确返回 E_UNAVAILABLE，保留 NEEDS_RECOVERY 和资源所有权，不声称旧 DMA 已隔离或进行自动 reset。出现真实超时/故障时按 [A/B 恢复限制](AB_RECOVERY_LIMITS.md)另行处置。本次板测只运行合法整数 kernel 和提交前 API 拒绝，不故意制造硬件故障。

TIMING-7 按既有要求保持 OPEN。模型执行、板测、E 新接收、故障恢复和性能测量分别报告，旧 15 条 E 接收不会自动扩展到这个新组合。

## 运行记录

首轮 `c-runtime-merge-20261111-v1` 的 251 项自测有 1 失败、1 跳过：新增测试错误地要求两版 IR 的 compiler_id 相同。两版语义字段一致，修正为分别断言版本号后比较其余字段；这是新集成测试的修复，未修改 E 冻结测试、前端或答案。原失败日志和源码快照保留。

`c-runtime-merge-20261111-v2` 已通过：255 项自测中 254 通过、1 跳过；六份新模块构建/校验成功，copy/vadd/affine 的仿真和 U280 镜像分别同哈希；SimX、处理器 RTL、NOXRT AFU 各 41 次合法执行、12 次拒绝，全部 123 次执行与三路完整数组对照通过。31 条子命令与入口退出 0。[完整记录（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-711c113c44f6)。旧契约和实现保护项保持原始字节。

首轮板测 `c-u280-runtime-20261111-v1` SSH 退出 0，但服务器 `/usr/bin/python3` 缺少 dataclasses，故在任何设备访问前 BLOCKED，板上执行 NOT_RUN；输入包和返回原件保留。这是加入项目内固定版本兼容依赖的原因。

兼容打包检查 `c-runtime-compat-20261111-v1` 自测 256 通过/1 跳过、Python 3.10 三模块预检通过。板测 `c-u280-runtime-20261111-v2` 已加载 dataclasses，但实际 Python 3.6.8 预检暴露 `str.removesuffix` 不可用，仍在设备访问前失败。故追加上述 `python36-integer-v1` 源码补丁，并使用 `c-runtime-merge-20261111-v3` 重新构建和运行三路；不能把 v2 通过记录视为该补丁的执行证据。

当前接续完成版本为 [c-runtime-merge-20261111-v3](../results/c-runtime-merge-20261111-v3/summary.json)：258 项自测中 **257 通过、1 跳过**；六份新模块构建/校验成功，设备镜像与补丁前一致。SimX、处理器 RTL、NOXRT AFU 各 41 次执行、12 次拒绝通过，31 条子命令及入口退出 0。

[c-u280-runtime-20261111-v3](../results/c-u280-runtime-20261111-v3/result.json) 的服务器 CPython 3.6.8 预检和真实 U280 执行 **41/41 PASS**：copy 13、vadd 13、affine 15，每个程序一个 context，context 内连续启动；共 12 次 API 拒绝后继续正确运行。三次打开/关闭门禁通过；b1、XRT index 3、HOST 256 MiB、实际 200 MHz、固定 UUID/库/镜像已核对，退出后 KDS 空闲。SSH、远程预检/编译/执行命令与本地接收退出 0。

最终四路共 **164 次执行、48 次拒绝**；每路 261 份完整数组文件一致，164 份参数布局/标量与上下文内缓冲区指针一致性复核。[收尾核验与来源差异](../results/c-runtime-delivery-20261111-v1/result.json)将原始输入、命令/日志、运行器版本、板端回传绑定到同一交付。这里的结果限于三个固定整数程序及当前边界，不扩大为全部 P0、独立 E 接收、硬件恢复或性能结论。

下一步由 E 对新增 C API 组合独立冻结语料并接收；C/D 后续扩充应用时沿用上述新 run_id 入口和目标 lock，B 的 TIMING-7 与故障隔离仍分别处理。无需为本次组合重建 FPGA，也未安装服务器软件或修改系统设置。
