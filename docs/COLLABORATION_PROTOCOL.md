# Vortex-U280 五人合作接口与交接协议

版本：`team-v2.0-draft`；日期：2026-11-07；新路线设计合同，尚未完成实现与接收。取代旧 `team-v0.1`，新接口使用 V01—V08，避免与历史 AEC 的 I01—I08 混淆。

人员：A 架构/RTL；B U280/平台；C 后端适配/runtime；D PTX 前端；E 验证/应用/AI 实验。研究范围见 [总计划](RESEARCH_PLAN.md)，PTX 白名单见 [兼容性规范](PTX_COMPATIBILITY_PROFILE.md)，接收记录使用 [模板](HANDOFF_TEMPLATE.md)。

**交接单位是“固定版本的实现 + 可运行样例 + 正负测试 + 原始证据”。接收方独立复现后才算交接完成。** 本协议字段是项目内部设计，不声称属于上游 Vortex 原生 API。

## 1. 所有权与协作方式

| 人员 | 唯一主责 | 必须协作的边界 | 不再承担的旧工作 |
|---|---|---|---|
| A | Vortex 核心配置、SIMT/ISA 能力、RTL 仿真与核心修复 | 和 B 交硬件配置；和 C/D 定线程、地址和后端语义 | 从零写 AEC 取指/译码/寄存器堆 |
| B | U280 shell/platform 对接、XRT 环境、构建/时序/上板、平台内存通路 | 和 A 定配置；和 C 验数据搬运/完成/恢复 | 首月自研 HBM/PCIe 控制器、FP8 MMA |
| C | 后端工具链适配、模块打包、设备 wrapper、host runtime、集成入口 | 和 D 定 IR/ABI；和 B 定平台路径；向 E 提供运行 API | 固定 aec_runtime API 与 AEC 装载协议 |
| D | PTX parser、类型与能力检查、语义 lowering、诊断和 profile | 和 A 确认语义；向 C 交代码/manifest；接 E 用例 | AEC 128-bit 编码/汇编器维护作为新主线 |
| E | 独立 oracle、系统验收集、应用需求、AI 对照实验与研究报告 | 各模块负责人提供自己的测试；E 负责独立接收和系统证据 | 首月完成全部比赛模型 |

代码目录按上述职责分配所有权；修改公共 ABI、能力表、参数布局、线程语义必须同时更新两端、样例和测试。共享文件由主责人合入，避免多个智能体同时覆盖。无需把全部文件交给 C 集中编写。

A 负责核心访存语义，B 负责平台地址/内存连接，C 负责分配和传输生命周期。程序可见 shared/cache 行为由 A 主责；B 不自行改变语义，C 不假设任意物理地址都能作为设备指针。

## 2. 首三天共同冻结的四份契约

这些文件是后续实现交付物，当前文档只规定 schema。未填真实值时保持 draft，不把占位符当成已经冻结的配置。

| 文件 | 主责 / 共同确认 | 最少字段 |
|---|---|---|
| `target_lock.json` | A，B/C/D | schema、Vortex commit、全部子模块 commit、补丁哈希、LLVM/VOLT/runtime 版本、编译选项、xlen、字节序、硬件配置哈希、仿真器、平台工具版本 |
| `target_caps.json` | A/B，C/D 接收 | device address bits、物理 threads/warp、warps/core、core 数、允许 launch 范围、shared/barrier 能力、PTX profile、numeric mode、异常/恢复能力、target_id |
| `ptx_profile.json` | D，A/C/E | 源 PTX version/target/address_size、完整指令形式白名单、声明语法、控制流/地址/线程约束、拒绝规则和测试 ID |
| `abi.json` | C/D，A/E | args ABI 版本、参数布局算法、entry/wrapper 约定、逻辑线程映射、模块格式、公共 API/错误/完成语义 |

`target_lock_hash` 是约定规范化字节（UTF-8、固定键序/换行规则）的 SHA-256；所有模块引用同一个值。板卡证据另外绑定 `platform_name`、shell/device 标识、XRT/驱动版本、xclbin SHA-256、实际实现时钟和构建报告，避免把 bitstream 自身哈希放入其源配置而形成循环。

第一阶段优先严格相同 lock 匹配；后续需要跨兼容构建运行时，再建立明确兼容列表，不能仅因为名称都叫 Vortex 就放行。首次锁定以原生 kernel 可运行的组合为依据，不预填未验证的工具版本或 HBM 地址。

## 3. 八个合作接口

| 编号 | 交付方 → 接收方 / 维护人 | 契约产物 | 接收条件 |
|---|---|---|---|
| V01 目标能力 | A/B → C/D/E / A | lock、caps、原生 kernel、配置/构建记录 | 相同配置可复现；不支持能力可查询 |
| V02 kernel 需求 | E → D/C / E | PTX 源码、数学定义、参数/布局/shape、输入、独立答案、支持/拒绝边界 | D 可编译或按 profile 诊断，C 可运行 |
| V03 前端与后端 | D → C，A 参加 / D | typed IR 或生成代码、源位置映射、参数/线程/访存语义、依赖 | C 不靠猜测生成 Vortex 程序；边界语义通过 |
| V04 模块装载 | C/D → C-runtime/E / C | 程序 image、manifest、反汇编、哈希、编译日志 | 合法包可装载，损坏/错版本/错能力包被拒绝 |
| V05 平台运行 | A/B ↔ C / B | 原生运行接口、内存映射/可见性、bitstream、完成/恢复能力 | 原生程序在目标后端正确；末次写入后才成功完成 |
| V06 应用调用 | C → E，D 参加 / C | 项目稳定 API、参数 packer、backend 选择、错误码 | 相同应用语义可切 backend；不静默 CPU fallback |
| V07 正确性与数值 | E ↔ A/B/C/D / E | oracle、冻结验收、语义/应用误差、差分与故障样例 | 各层分开出结果；通过与限制可追溯 |
| V08 智能体任务与接收 | 每位负责人 ↔ 实施/审查智能体 / E 维护模板 | 任务卡、文件范围、预算、轨迹、差异、测试与人类接收 | 非作者复现；实施者不能自行放宽冻结验收 |

## 4. V03：编译器内部边界

前端输出的最低语义信息：

```text
module: source_hash, ptx_version, source_target, address_size, profile
entry: name, ordered_params, argument_layout, logical_launch_model
instruction: opcode, type, modifiers, operands, predicate, address_space,
             source_file, line, column
value: bit_width, signedness, virtual_register, definedness
control: basic_blocks/edges（P0 可只有直线体，lowering 仍处理谓词）
requirements: features, static_shared_bytes, numeric_mode, target_lock_hash
```

D 负责 PTX 含义和严格拒绝；C 负责 target data layout、正确 Vortex 特性、SIMT 编译流程、设备 wrapper、链接与打包。普通 RISC-V 编译成功不等于 SIMT 语义正确。使用的扩展开关必须来自所选配套工具链并在反汇编/执行测试中确认，不能跨版本照抄。

若首版输出 C/C++，明确使用无符号定宽类型、显式截断/扩展、可审查的谓词访存条件和线程 accessor。D 不输出会把假谓词 load 提前执行的表达式；C 不开启会破坏承诺语义的优化。直接 LLVM IR 路线应显式保留数据布局、地址空间、函数属性和必要 intrinsics；不是现成 NVPTX 后端的反向调用。

P0 原始 PTX 不含 branch/barrier；内部谓词降低产生的分支同样要进入经验证的 Vortex SIMT 编译流程。扩展 CFG/shared/barrier 时 A/C/D 联合验收，不交给单个字符串替换 pass。

## 5. V04：模块包、参数 ABI 与校验

### 5.1 模块包

```text
module/
  source.ptx
  image.<固定版本Vortex装载格式>
  manifest.json
  program.disasm
  source_map.json
  compile.log
  target_lock.json
  sample/        参数字节、输入、独立答案、运行说明
```

正式 image 格式以固定版本工具链为准，可能来自 ELF 再打包；不把任意裸 RISC-V 字节当成可加载模块，不给上游 image 私加未经 loader 支持的头。

| manifest 字段 | 语义 |
|---|---|
| `schema_version, compiler_id, build_id` | 项目 schema 和实际生成器身份 |
| `source_sha256, source_ptx_version, source_target, source_address_bits` | 输入身份与源约束 |
| `profile, target_lock_hash, abi_version` | 输入能力、目标组合与调用布局 |
| `image_file, image_sha256, image_format, entry` | 字节对应关系、已固定 loader 格式与入口 |
| `params_size, params_align, params[]` | 每个参数 name/kind/type/offset/size/align/space；pointer 项关联 buffer 参数语义 |
| `required_features[], logical_launch_model` | 指令/SIMT 要求与逻辑线程映射版本 |
| `launch_limits, static_shared_bytes, dynamic_shared_policy` | 从目标能力与编译资源共同导出的限制 |
| `numeric_mode, memory_assumptions, known_limits` | 精确数值承诺、无数据竞争/对齐假设和限制 |

capability 的示例数值不能直接复制进 manifest。比如物理 warp 宽度、最多 block 线程、共享内存上限必须绑定目标配置与已验证调度方式。

### 5.2 参数约定

- D 生成 PTX 参数顺序/布局；C 生成或调用同一份 packer，E 使用有类型的参数列表。小端、自然对齐、padding 清零，不依赖 host C struct 隐式布局。
- 指针实参是 `buffer_handle + byte_offset + declared_access_bytes + access_mode`；C 校验存活、范围、整数溢出和对齐后查询设备地址，再按 ABI 序列化。
- 项目 payload 与上游 runtime 启动结构分开。C 的设备 wrapper 负责从 payload 取参数并建立逻辑线程上下文；grid/block 不可由各方自行塞到未约定字节中。
- vadd 的 32-byte 示例见 [PTX profile](PTX_COMPATIBILITY_PROFILE.md)；其他 kernel 参数从源码产生，不根据 kernel 名字选择固定模板。
- PTX64→RV64 为推荐起点。若另选 RV32，单独版本化受限地址策略；不得静默截断，也不能把 HBM 物理位宽等同于程序指针位宽。

### 5.3 加载与启动分别校验

加载校验 schema、哈希、image 格式/入口、lock、ABI、能力与资源。启动再次校验维度、参数数量/类型/布局、buffer 生命周期与声明范围、共享内存、并发限制；校验失败不向设备提交。

范围校验仅覆盖 API 可观察部分。任意 kernel 内部计算出的访存地址如无硬件保护/编译检查，不能保证都变成精确异常；错误地址测试须标记观察手段和检测阶段。测试程序限定为合法且无数据竞争，异常注入使用隔离的可控环境。

## 6. V05/V06：项目 runtime API

以下是拟议的逻辑 API，后续由 C 落为头文件/封装；函数名不是已存在的 Vortex API。

```text
open(backend, target_lock) -> context
query_caps(context) -> capabilities
alloc(context, bytes, alignment) -> buffer_handle
write(context, buffer, offset, host_bytes) -> status
load(context, image, manifest) -> module_handle
launch(context, module, entry, grid[3], block[3], args, shared_bytes) -> event
wait(context, event, timeout_ms) -> completion
recover(context, timeout_ms) -> {status, generation, device_state, isolated}
read(context, buffer, offset, bytes) -> host_bytes
unload(context, module)
free(context, buffer)
close(context)
```

`backend` 明确为 `simx / rtlsim / u280-xrt`；oracle 单独标 `cpu-oracle`，mock 单独标 `mock`。缺硬件返回不可用，不自动改为 CPU 计算再报告成功。

### 6.1 数据可见性与生命周期

1. 首版一个 context 一条队列、一次一个 kernel 在途；第二个 launch 在前一个完成前返回 E_BUSY。并发执行作为后续 ABI 扩展。
2. write 对仍被在途任务引用的 buffer 返回 E_BUSY；成功后数据对后续 launch 可见。launch 返回成功仅表示接收，返回前复制参数 payload，保持 module/buffer 引用直至 event 终结。
3. wait 成功表示本次逻辑线程全部完成，要求的写入已满足之后 read 可见的条件；底层需要 drain/fence/sync 时由 C/B 纳入，不因命令入队就返回执行成功。
4. read 在相关 kernel 尚未终结时返回 E_BUSY；成功时 host 数据有效。free/unload 遇到在途引用同样返回 E_BUSY，不提前释放。
5. close 在有在途工作或未隔离旧事务时返回 E_BUSY，调用方先 wait 或 recover；不隐式破坏尚在运行的资源。设备不可恢复时，B 按平台规则隔离旧事务并由 C 确认 `isolated=true` 后，才允许 close 释放该 context 及其资源。
6. 成功后可连续提交新输入，必须证明没有旧参数、旧 event 或旧输出混入。

处于 NEEDS_RECOVERY/UNAVAILABLE 时，分配、传输、装载、启动、读回和普通资源操作一律返回 E_UNAVAILABLE；仍可查询诊断、query_caps 的静态信息并调用 recover。是否可以 close 取决于上述事务隔离条件，不能因为已返回超时就释放底层仍可能访问的资源。

### 6.2 状态与失败恢复

```text
READY → RUNNING → COMPLETED → READY
                 ↘ FAILED / TIMEOUT → NEEDS_RECOVERY
NEEDS_RECOVERY → 隔离或排空旧事务 / 平台允许的恢复 → READY
              ↘ 恢复失败 → UNAVAILABLE
```

C 保存首个错误和最后进度，B 负责平台恢复机制，A 处理核心侧状态。不能假设任意 Vortex 版本都有精确 PC/lane fault 或安全的 kernel abort；能力表说明哪些可观测、哪些只能超时/重开设备。

超时后立即返回 E_TIMEOUT 及 `device_state=NEEDS_RECOVERY/UNAVAILABLE`，不承诺已经复位。调用方通过 recover 请求有界恢复；C/B 按已核实平台能力停止或隔离旧事务、恢复动态状态并重新检查设备。成功返回 READY、`isolated=true` 与递增的 context generation；旧 event 无效，旧 buffer/module 句柄全部失效，E 重新分配、装载、上传。

recover 超时或失败返回 E_TIMEOUT/E_DEVICE/E_UNAVAILABLE，保留原故障与当前 device_state，不虚构 READY；只有确认旧 DMA/写事务已停止或隔离，才允许复用设备地址。若恢复需要平台运维且未具备条件，设备保持不可用；B 完成平台隔离、C 核实后可关闭 context，即使设备尚不能重新计算也不必永远保留应用句柄。

P0 通过全量失效简化恢复语义；后续若保留资源，需要另行约定有效性并升版，不临时“猜测数据还在”。

### 6.3 统一错误对象

错误至少包含 `code, phase, message, run_id, event_id, generation, backend, source_location, native_status, evidence_path`；不适用字段为 null。可选 PC/core/warp/lane 只能填真实获取值，不能用 0 伪装未知。

| code | 情形 / 首责 |
|---|---|
| E_PTX_VERSION / E_UNSUPPORTED | 不接受的源版本、指令、修饰符、控制流或语义 / D |
| E_TYPE / E_PARAM_LAYOUT | 源类型或参数布局错误 / D；调用打包错误由 C/E 定位 |
| E_TARGET_MISMATCH / E_MODULE_CORRUPT | lock/ABI/能力不匹配或包损坏 / C/D |
| E_INVALID_BUFFER / E_ADDRESS_RANGE | handle/范围/地址宽度/对齐校验失败 / C，必要时 D |
| E_LAUNCH_LIMIT / E_BUSY | 维度、资源、并发限制 / C |
| E_DEVICE / E_TRANSPORT | 确认的设备/平台故障 / A/B/C 按首个异常位置定位 |
| E_TIMEOUT / E_UNAVAILABLE | 未按时完成、后端不可用或未恢复 / C 协调 A/B |

这些是项目错误码，不冒充 NVIDIA CUDA、AEC 或 XRT 的原生枚举；native 状态原样作为诊断附带。unsupported 不是执行成功，fallback 不是设备成功。

## 7. V07：测试与结果协议

每次运行独立保存到 `results/<run_id>/`（相对工作区根目录，运行时创建），不覆盖前一轮结果，包括失败和阻塞记录。

| 记录 | 必需内容 |
|---|---|
| 输入身份 | 源码/模块/image/lock 哈希、profile、ABI、参数字节、输入文件、种子 |
| 环境 | backend、主机工具、仿真模式；硬件运行附 bitstream/platform/时钟与设备标识 |
| 阶段状态 | compile/load/H2D/launch/wait/D2H/compare 各自状态与退出码 |
| 输出与判断 | 实际输出、独立 oracle 来源、比较方法/误差/哨兵、失败最小样例 |
| 测量 | 编译/装载/H2D/kernel/D2H/总时间，单位、时钟来源、预热/重复数 |
| 可复现证据 | 完整命令、原始日志、工具退出码、接收人复现记录 |

状态统一 `PASS / FAIL / BLOCKED / NOT_RUN`，另可对数值指标用 `NOT_MEASURED`。BLOCKED 说明外部依赖；已尝试但执行错误为 FAIL；仅生成向量为 NOT_RUN。对每项标明范围，例如 `vadd / simx / PASS`，不能只写“GPU 测试通过”。

最低接收集：三类 kernel、尾部/溢出/不同 block 数、谓词不访存、参数/模块拒绝、重复 launch、可用的恢复路径、独立原生平台基线。P1/P2 增加各自的分支/数值/同步用例。

排错依据：CPU 定义不一致先找 E；原生正确而 PTX-SimX 错误先找 D/C；SimX 正确而 RTL 错误先找 A；独立传输错误先找 B/C；原生板上正确而 PTX 板上失败由 C 组织 A/D 分析。跨模块问题先由两端共同做最小复现，不把问题全部转给集成人。

## 8. V08：智能体协作合同

每项任务由人类 owner 发出，至少包含：

```text
task_id / parent_id / owner / receiving_person
objective / input_versions / profile / ABI / target_lock_hash
allowed_files / protected_files / interface_dependencies
deliverables / acceptance_commands / expected_failure_cases
time_limit / total_token_or_cost_budget / model_id
output_directory / unresolved_questions / stop_conditions
```

实施智能体提交代码差异、说明和真实测试输出；审查智能体基于规范、冻结测试和最小复现独立核对。上下游需要变更契约时写变更记录，不在聊天里默默改变参数字段或合法范围。

E 的冻结验收与 oracle 目录不由实施智能体修改；发现测试错误需单独说明并由非作者审阅，修改前后的结果均保留。普通新增单元测试仍由模块负责人维护。

AI 研究记录除上述字段外增加：实验组别、随机分配、模型版本、完整累计预算、人工主动时间、工具/等待时间、首轮接收结果、修复次数与失败原因。多智能体组所有子智能体成本合计；实现者自报 PASS 不算接收。

## 9. 接收、版本与日常节奏

流程为 `草稿 → 自测通过 → 待接收 → 接收通过 / 带限制接收 / 退回`。接收人必须获得固定版本和输入并实际执行；退回写失败命令/证据，限制写入 profile/caps。未启用 Git 时使用完整文件 SHA-256 清单，不填写虚构 commit。

版本分别维护：`team` 管团队合同；`profile` 管 PTX 范围；`abi` 管调用布局；`target_lock` 管实际实现组合。行为不变的修复不改 ABI；兼容能力扩展升次版本；参数偏移、位宽、线程或完成语义改变升不兼容版本并更新两端。

变更记录包括旧/新值、原因、受影响人、迁移方法、需要重编/重建的产物、回归命令。参数/地址/线程变更由 A/C/D 确认，B 核查平台影响，E 接收测试；数值模式变更由 A/C/D/E 确认。团队内部确认是开发流程，不要求每次再向用户重复请求已授权的普通修改。

每天 10 分钟同步“新证据、阻塞与负责方、下一交付”；每周两次集成。D/C/E 第一周共同打通一个 kernel；A/B/C 第一周共同跑原生基线。B 汇总板卡排期，C 汇总集成版本，E 汇总验收和实验数据。

## 10. 首次冻结与仍待核实事项

- 人员姓名与可投入时间：沿用五人安排，首次组会填写，不影响文档作为工作方案使用。
- A/C：选择配套 Vortex/LLVM/runtime commit，确认 XLEN、SIMT 编译特性、仿真入口和 native image 格式。
- B：核实真实 U280 入口、platform、shell、XRT/Vitis、构建条件；所选版本需要 host-memory 支持时明确环境依赖。
- C/D：实现同一参数 packer 与设备 wrapper，验证地址、线程编号、谓词访存和完成语义。
- E：冻结三类 kernel、独立 oracle、拒绝集和 AI 配对任务；指定每个接口的接收人。

以上 V01—V08 接口尚未完成实现/接收；真实进度见 [STATUS](STATUS.md)。上游依据：[Vortex](https://github.com/vortexgpgpu/vortex)、[VOLT](https://github.com/vortexgpgpu/Volt)、[FPGA 指南](https://github.com/vortexgpgpu/vortex/blob/master/docs/fpga_setup.md)、[runtime 设计](https://github.com/vortexgpgpu/vortex/blob/master/docs/designs/vortex_runtime_api.md)、[PTX ISA](https://docs.nvidia.com/cuda/parallel-thread-execution/index.html)。具体 native 接口以冻结版本源码为准。
