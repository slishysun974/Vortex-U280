# Vortex-U280 项目总览

**截至 2026-11-23，项目已把数组复制、向量加法和逐元素乘加这三类整数 PTX 程序放到 U280 上运行，并用预先冻结的答案完成四路独立核对。** 下一项应用是 Iris 三分类。已有设计和 CPU 校对值，正式数据冻结、内核构建和设备执行均待开展。[三算子独立验收](E_RUNTIME_UNSEEN_ACCEPTANCE.md) · [Iris 实施计划](IRIS_U280_PROJECT_PLAN.md)

## 从一个程序找到代码和结果

以向量加法为例，先看每个线程怎样计算数组下标，再看编译器如何生成设备模块、主机如何分配缓冲区并启动。最后打开独立验收回执，可按后端追到输入、完整数组、参数和退出码。

| 想看什么 | 从哪里开始 |
|---|---|
| PTX 源码和允许使用的指令 | [向量加法源码](../ptx/samples/vadd_u32.ptx) · [P0 兼容性规范](PTX_COMPATIBILITY_PROFILE.md) · [机器可读白名单](../configs/ptx_frontend/v1/profile.json) |
| 源码如何成为可装载的 Vortex 镜像 | [模块构建器](../scripts/ptx_module.py)提供 `prepare`、`build`、`validate` 三个入口。[编译器交付报告](D_P0_CLOSEOUT.md)给出生成的中间表示、源码映射、参数布局和镜像。 |
| 主机如何提交、等待和读回 | [运行时 Context](../scripts/ptx_runtime.py) · [U280 装载与板卡检查](../scripts/ptx_u280.py) · [运行时接口](../configs/c_runtime/api_v2.json) |
| 怎样知道输出正确 | 从[独立冻结清单](../configs/acceptance/e-runtime-unseen-20261111-v1/manifest.json)到[四路验收回执](../results/e-runtime-unseen-acceptance-20261111-v1/result.json)，可核对同一用例在三个模型和实卡上的结果。 |

## 本地文件夹和关键文件

| 根目录位置 | 内容与使用方式 |
|---|---|
| [README.md](../README.md)、[AGENTS.md](../AGENTS.md) | 首页有向量加法流程图。项目约定说明固定源码、隔离构建、证据保存和状态登记方式。根目录另有 [.gitignore](../.gitignore) 和 Ramulator 的[统计日志（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-85c0bd5cc7b3)。 |
| [configs/](../configs/) | 源码和工具包身份查[根目标锁](../configs/target_lock.json)，其状态为 `draft`、`frozen=false`。实际复现按对应的 [D5 模型锁](../configs/candidates/block32-v1/target_lock.json)或 [U280 板用锁](../configs/candidates/u280-hbm32-v1/target_lock.json)选取产物。`acceptance/` 保存部分冻结语料。 |
| [upstream/](../upstream/)、[third_party/](../third_party/) | 前者含固定 Vortex v3.0 检出，后者含项目携带的 `dataclasses-0.8` 兼容依赖及来源记录。 |
| [ptx/](../ptx/)、[native/](../native/) | `ptx/samples/` 放三个算子及语义样例，`ptx/probes/` 放指令与宽地址探针。`native/` 放原生 C++ 基线、宿主核对程序、板上探针和性能对照内核。 |
| [scripts/](../scripts/)、[tests/](../tests/) | 前者是编译、运行和验收入口，独立接收程序集中在 [e_acceptance/](../scripts/e_acceptance/)。后者有 39 个 `test_*.py` 文件，覆盖前端、运行时、目标绑定和结果复核等行为。 |
| [environment/](../environment/)、[references/（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-07a0b0962107) | 前者记录固定 WSL、模型构建环境、U280 平台及本地访问资料。后者保管老师提供的原始材料与清单。[服务器与路径导航](SERVER_GUIDE.md) · [参考资料说明（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-fdd6f83475df) |
| [experiments/](../experiments/) | 14 个专题子目录和 3 份早期实验定义。`e-v14-local/` 放独立接收程序，`ptx-*` 和 `u280-*` 放性能、装载与观测实验，`ai-paired-*` 放协作研究的协议与任务。 |
| [build/（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-44575cf5b285) | 30 个一级子目录，含隔离构建、历史公开快照和测试工作目录。复现时按目标和新 run_id 另建目录。 |
| [results/](../results/) | 423 个一级子目录，另有 2 份早期 JSON。这里同时保存冻结、准备、失败尝试、运行和接收记录。查某项成果时从下方专题或回执进入，再沿 run_id 查命令、输出和退出码。 |
| [docs/](./) | [STATUS](STATUS.md)按日期保留状态，[PROJECT_HANDOFF](PROJECT_HANDOFF.md)记录交接，[研究计划](RESEARCH_PLAN.md)给出五人分工和研究问题。[公开快照说明](PUBLICATION.md)列出本地档案与公开副本的收录范围。 |

## 已取得的成果

下表按后端列出三次不同的验收。第一列用例覆盖三算子及等价 PTX 变体。V03 是编译器与运行时的交付接口，该列覆盖两个模块的 8 个普通地址用例和 5 个 4 GiB 专项用例。v1.4 一列记录固定 D5 配置下的独立本地验收。

| 执行层级 | 三算子独立语料（11-11） | V03 地址与指令探针（11-21） | v1.4 对齐参数读取与同谓词访存合并（11-22） |
|---|---|---|---|
| SimX 指令级模拟 | 48/48 通过 | 13/13 通过 | 37/37 常规启动、5/5 逐 lane 调试回放通过 |
| 处理器 RTL 仿真 | 48/48 通过 | 13/13 通过 | 37/37 常规启动、5/5 逐 lane 调试回放通过 |
| NOXRT AFU 仿真 | 48/48 通过 | 13/13 通过 | 37/37 常规启动、5/5 逐 lane 调试回放通过 |
| 物理 U280 | 48/48 通过 | 13/13 通过 | 此次独立验收 `NOT_RUN`。六份固定镜像另有实卡配对结果，见下表。 |
| 接收依据 | [机器回执](../results/e-runtime-unseen-acceptance-20261111-v1/result.json) | [机器回执](../results/ae-v03-acceptance-20261121-v1/result.json) · [负责人限定签收](../results/ae-v03-signoff-20261121-v1/record.json) | [独立回执](../results/e-v14-review-20261122-v1/result.json) · [用例与复现命令](E_V14_LOCAL_ACCEPTANCE_20261122.md)。本版人类签收待办。 |

| 专题 | 已有结果与范围 |
|---|---|
| 源码身份 | 固定 Vortex v3.0 提交 `7fe19369587c`，源码核验记录覆盖 3,329 个文件。[源码核验](../results/ab-d1-source-20261107-v2/result.json) |
| Python 运行器 | 11-22 在固定 WSL 运行 `python -B -m unittest discover -s tests -v`，314 通过、2 跳过，退出 0。同期 Windows 为 303 通过、12 跳过、1 错误，退出 1，错误涉及库路径对盘符的解析。[WSL 命令与退出码](../results/ai-paired-runner-wsl-20261122-v2/runner.json) · [WSL 输出](../results/ai-paired-runner-wsl-20261122-v2/runner.stderr) · [Windows 输出](../results/ai-paired-freeze-20261122-v1/runner.stderr) |
| FPGA 与主机库 | D10 是已完成构建的 FPGA 镜像，D12 是与其配套的两份主机运行库。固定实卡会话实测 DATA_CLK 200 MHz、HOST 256 MiB。[D10 构建](AB_D10_PROGRESS.md) · [D12 运行库](AB_D12_PROGRESS.md) · [实卡会话](PTX_U280_ALIGNED_BOARD_20261122.md) |
| U280 性能 | 三算子、两档规模的原生/PTX 对照共 180 对正式计时，PTX 在这批样本的额外耗时主要来自执行等待。后续 v1.3/v1.4 六镜像实卡计数实验完成 420 次启动，输出与哨兵全部通过。180 对正式样本中，v1.4 有 150 对设备周期下降，180 对退休 warp 指令数下降。[原生/PTX 回执](../results/u280-perf-three-operators-20261121-v2/result.json) · [v1.3/v1.4 逐组计数](PTX_U280_ALIGNED_MPM_20261122.md) |
| V08 单、双智能体对照 | 本地单人调度了三轮。第一轮单组 5/6、双组 6/6，单组有一席因 token 计量错误提前停止。第二、三轮每轮均为单组 6/6、双组 6/6。原双人操作协议已冻结，正式试次 0/12。[首轮](V08_LOCAL_TRIAL_20261122.md) · [第二轮](V08_LOCAL_ROUND2_20261122.md) · [第三轮](V08_LOCAL_ROUND3_20261122.md) · [双人版协议](../experiments/ai-paired-v1/protocol.md) |

## 接下来怎么做

**应用主线是 Iris。** 设计阶段的 CPU 参考准确率为 40/45（88.89%）。设备验收逐项核对 45 个类别和 135 个整数距离。即使分类器判错，只要设备写回与独立数学答案相符，该样本仍可通过设备正确性检查。[设计、用例矩阵与分工](IRIS_U280_PROJECT_PLAN.md)

| 顺序 | 负责人 | 交付与完成条件 |
|---|---|---|
| M1、M2 可并行 | E 冻结数据；D 写 PTX，A 审核数值与线程语义 | E 从原始数据重算 105/45 训练测试划分，封存 9 个用例的输入与独立答案。D 为同一 PTX 分别构建 D5 模型模块和 U280 模块，用各自的锁验证。 |
| M3 本地验收 | C 执行，A/E 复核 | 三个模型各跑 9 次，核对距离、类别和缓冲区保护值，并验证检查器能检出人为改坏的结果。 |
| M4 实卡验收 | B/C 执行，E 比对 | 取得板卡窗口后核对当次配置，沿用冻结输入执行 9 次，将实卡原始回读传回独立比较。 |
| M5 演示与交接 | E 汇总，A–D 核对 | 展示一个样本从输入到设备输出的完整路径，分别报告模型准确率、各后端执行结果和复现命令。 |

其他课题可按各自的前置条件接续。

- **物理故障恢复和时序。** 三模型已验证超时排空和设备故障封锁。B/C 下一步请平台维护者确认何时旧 DMA 已不能写入待复用内存，并确认跨时钟域复位的适用条件。确认单尚待外发，隔离依据为 `BLOCKED`，物理恢复实验为 `NOT_RUN`，时序项 `TIMING-7` 为 `OPEN`。[模型恢复记录](RUNTIME_RECOVERY_20261111.md) · [平台确认单](U280_PLATFORM_QUESTIONS_20261122.md)
- **实卡尾部访存。** 固定 D10/D12 可以核对输出和聚合计数。要验证每个被屏蔽线程的读写请求为零，需能在访存合并前采集逐 lane 请求。当前镜像缺少该观测点，捕获条件为 `BLOCKED`，该项实卡验证为 `NOT_RUN`。[观测性核验](PTX_U280_TAIL_OBSERVABILITY_20261122.md)
- **研究与签收。** v1.4 本地独立验收材料可交人类接收人复核。原双人 V08 等待 E 登记两位操作者并核对计量。若推进架构比较，由团队在 Core 或 Cache 中选一个变量，沿用现有正确输出作对照。[v1.4 接收包](E_V14_LOCAL_ACCEPTANCE_20261122.md) · [V08 协议](../experiments/ai-paired-v1/protocol.md) · [研究计划](RESEARCH_PLAN.md)
