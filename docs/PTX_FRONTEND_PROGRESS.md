# C/D：P0 前端首版与宿主语义验证

日期：2026-11-08，Asia/Shanghai。此交付是前端实施者自测，非 E 独立接收；尚未生成 Vortex image、接入项目 runtime 或执行 PTX-SimX/RTL/U280。

最终 [v3 验证](../results/ptx-frontend-host-20261108-v3/summary.json) **PASS，入口退出 0**：Linux Python 测试 69 通过/1 跳过；copy 132、vadd 132、affine 396、额外语义探针 1，共 **661/661 宿主用例通过**。正常编译与执行均退出 0，故障注入按预期退出 1；G++ 11.4.0、`-O2` 与 UBSan 实际命令保存在日志中。[174 项证据收尾](../results/ptx-frontend-closeout-20261108-v1/result.json) 全部通过、退出 0，默认 lock/caps/config 及 block32 lock 哈希保持原值。

## 实现与使用

入口为 `scripts/ptx_frontend.py`，只使用 Python 标准库（Python 3.10+）。解析完整 token 流，保留源码位置，生成 typed IR、参数布局、C++ 语义函数和哈希清单。未知指令、修饰符、directive、类型错误及不满足静态初始化条件的使用均拒绝；不按 entry 名字选择预制 kernel。

```powershell
python -B scripts/ptx_frontend.py ptx/samples/vadd_u32.ptx --output results/ptx-vadd-NEW
```

输出目录必须不存在。默认复制根 `configs/target_lock.json`，也可显式指定 `--target-lock`；要求 RV64、小端。该 lock 只是预期目标身份，不能由其已有原生仿真结果推断生成代码通过设备验证。

输出包括 `source.ptx`、`ir.json`、`kernel_body.hpp`、`source_map.json`、profile/ABI/lock 副本和 `manifest.json`。manifest 使用独立 schema `ptx-vx-frontend-artifacts-v1`，明确 `loadable=false`、`image_file=null`、`backend_execution=NOT_RUN`；不得交给上游 loader 冒充程序 image。

`kernel_body.hpp` 导出 `ptx_body(payload, PtxThread, Memory)`：线程上下文显式携带四个逻辑坐标；Memory 接收完整 u64 地址的 `load32/store32` 调用。所有算术使用无符号定宽类型；谓词指令用实际条件语句包住目的写入与访存。C 仍需实现 Vortex device wrapper、真实访存适配、后端编译、打包与装载验证。

`pack_arguments` 按源码顺序自然对齐、小端序列化，清零 padding，并拒绝参数数量、负数、溢出和布尔值混充整数。它只接受**已经由 runtime 验证的**整数值，不实现 buffer handle、生命周期、分配范围或设备地址解析，不能当作 V06 公共 runtime API。

## 版本与接收范围

机器可读文件在 `configs/ptx_frontend/v1/`。前端采用新的 `ptx-vx-p0-v0.2-draft`；父设计为 `ptx-vx-p0-v0.1-draft`。参数布局沿用文档中的 `ptx-vx-args-v1`，没有改变 u32/u64 大小、偏移算法或字节序。

v0.2 明确了首版保守语法与静态检查范围：header 按固定顺序，单 entry，寄存器声明在指令前；只加载完整标量参数，显式偏移仅接受零；不接收 predicated ld.param/ret；不含嵌套作用域；支持十进制/十六进制/八进制/二进制整数及可选 U、一元正负号，不接收常量表达式。资源上限为源 1 MiB、寄存器 4096、指令 65536。

初始化分析按“寄存器 + 谓词版本 + 极性”跟踪路径，允许同一未改写谓词保护的定义/使用以及互补分支共同初始化。谓词重定义后不能沿用旧路径事实；不做常量谓词推断或通用逻辑求解，因此可能保守拒绝语义合法但无法证明的程序。

u64 参数在本 ABI 中均为 global 设备指针。指针来源可通过 mov/cvta 和 pointer+integer 的 add 保持；整数伪造地址、两个指针相加或条件覆盖后无法证明来源的地址被拒绝。该检查不是内存沙箱；活跃路径的动态地址仍要求有效、自然对齐、在分配范围内且无数据竞争。静态地址常量偏移按 u32 的 4-byte 对齐检查。

根 target lock/caps、block32 候选和 D4/D5 原始证据不改。现有 caps 的旧 profile 名称没有被默认为新前端接收许可。C/D/E 后续接入时需明确确认 profile、ABI、wrapper、launch 限制并按协议更新接收版本；B=32 的宿主测试不提升目标 capability。

语义依据为 [NVIDIA PTX 7.0 归档](https://docs.nvidia.com/cuda/archive/11.0/parallel-thread-execution/index.html)：整数常量按使用处位宽转换；假谓词跳过指令。支持形式仍限于本项目 profile，未接受的 PTX 合法形式明确拒绝。

实现阶段表如下；`implemented` 指 parser/静态检查/C++ lowering，并不表示目标后端已接收。每一组的 SimX、RTL、U280 均为 NOT_RUN。

| 形式 | 实现状态 | 作者测试入口 |
|---|---|---|
| mov.u32/u64、ld.param.u32/u64 | implemented | 三类样例、参数布局/宽度/偏移拒绝测试、probe |
| add.u32/u64、sub.u32、mul.lo.u32、mul.wide.u32 | implemented | affine 的溢出矩阵、probe 的 u32 边界和 u64 高乘积/回绕 |
| cvta.to.global.u64、global 地址来源 | implemented，保守证明 | copy/probe、条件覆盖与伪造地址拒绝测试 |
| setp.lt/ge/eq.u32、selp.u32 | implemented | 尾线程判断、probe 的符号位为 1 的无符号比较与选择 |
| ld/st.global.u32、谓词及反谓词 | implemented | 完整逐线程 trace、N=0 未映射指针、probe 的目的保留与屏蔽访问 |
| ret、声明、特殊寄存器 | implemented | 末尾/唯一入口/类型/声明拒绝；不同 B/G 和 probe 的 nctaid |

通用性测试对 entry 和全部寄存器改名，核对生成的 C++ 完全一致；所有公开指令形式也由样例全集覆盖检查绑定。当前仅是作者自测矩阵，尚无 E 冻结验收集或 NVIDIA 同 PTX 执行对照。

## 验证与证据

完整重跑入口：

```powershell
wsl -d Vortex-AB-Ubuntu-22.04 --cd /mnt/d/Vortex-U280 -- python3 -B scripts/run_ptx_frontend_validation.py --run-id ptx-frontend-host-NEW
```

运行器独占创建 run 目录，执行 Python 自测，使用现有宿主 G++ 编译生成的 C++，启用 UndefinedBehaviorSanitizer，再执行带访问记录的 CPU harness。它不调用 SimX、Verilator、XRT 或远程服务器，不安装工具。

copy/vadd/affine 的宿主语料涵盖 N=0/1/7/31/32/33/63/64/65/257/1024，B=1/4/7/16/31/32，两组输入及 alpha=0/1/最大 u32；保存全部输入、预期、实际 x/y/z、参数字节和逐线程访问 trace。N=0 仍调用一个 block 的语义函数，参数指向未映射地址，任何实际 global 访存都会失败。其他用例检查每线程的访问顺序、地址、值、总数及完整输入/尾部哨兵。

额外 `semantics_probe.ptx` 是实施者的指令组合测试，覆盖宽乘积与 u64 回绕、无符号比较、选择、假谓词目的保留、负地址偏移与高位虚拟地址。这些地址属于宿主审计模型，不能称为设备或 HBM 高地址实测。

每次运行保存实现快照、全部命令/退出码/日志、编译器版本、生成物和输入输出哈希；run 汇总与分项 comparison 共同构成证据。Python reference 和测试均由本轮实施者编写，非冻结独立 oracle。

故障注入使用单独目录中的生成代码副本，移除首个 load 的谓词保护。在 N=0、指针未映射的输入下，预期宿主审计程序退出 1 并报告活跃访存越界。正常生成包、输入和预期不被故障注入修改；该检查仅证明宿主检测器能抓到这一类错误。

### 迭代记录

| 运行 | 结果与范围 |
|---|---|
| 首次 Windows 前端检查（本地记录 `results/ptx-frontend-initial-20261108-v1/result.json`） | FAIL，退出 1；一处作者测试的 `%r` 字符串格式化错误及沙箱临时目录拒绝。此文件为事后事实记录，原始终端输出未另存文件 |
| Windows 中间版本（本地记录 `results/ptx-frontend-windows-20261108-v1/result.json`） | 脚本/前端检查 PASS，60 通过、5 平台跳过，退出 0；不是最终 Linux 实现版本的跨平台接收 |
| Linux/宿主 v1（本地记录 `results/ptx-frontend-host-20261108-v1/summary.json`） | 整体 FAIL，退出 1；三类应用 660 用例通过，额外探针 `%r6` 条件初始化后无条件使用被正确拒绝。修复探针的显式初始化，未放宽前端规则或改写该轮结果 |
| Linux/宿主 v2（本地记录 `results/ptx-frontend-host-20261108-v2/summary.json`） | 整体 FAIL，退出 1；69 项 Python 测试通过、1 平台跳过，661 宿主用例通过；故障注入的临时代码漏分号，编译失败。修复注入脚本后另建 run |
| [Linux/宿主 v3](../results/ptx-frontend-host-20261108-v3/summary.json) | 整体 PASS，退出 0；69 Python 测试通过、1 Windows 专属负例跳过；661 宿主用例通过；提前 load 的故障注入检测 PASS（被测程序预期退出 1）；执行前后实现快照和语料未变 |
| [最终证据收尾](../results/ptx-frontend-closeout-20261108-v1/result.json) | PASS，174/174、退出 0；核对命令/日志、实现快照、生成包、访问 trace、结果汇总和原硬件配置哈希；不重复执行语义测试 |

上述探针与 reference 均为实施者新建自测，未修改 E 的冻结验收或旧 D4/D5 证据。PTX device image、SimX、处理器 RTL、AFU 与 U280 的新增执行状态始终单列为 NOT_RUN。

证据复核入口：`python -B scripts/verify_ptx_frontend_results.py --run-id ptx-frontend-host-20261108-v3 --output results/ptx-frontend-closeout-NEW`。原始 captures 的逐字节比较由主验证运行完成，收尾脚本检查其汇总与相关证据哈希；完整重执行使用上面的 `run_ptx_frontend_validation.py`。

## 下一步

1. C 接入固定 Vortex 后端，生成真正 vxbin 与设备 wrapper；用当前布局读取 payload，并校验模块/profile/lock。
2. 为 buffer handle/range/lifetime 与 launch 建立项目 runtime，保持 native wrapper 与 payload 分离；不得继承宿主模型的内存检查能力。
3. 先实际执行 PTX-SimX 三类 kernel，再按相同产物进入处理器 RTL；针对生成后的设备代码补假谓词无访存 trace。
4. E 以独立答案和未见合法组合接收。U280 另按接收单盘点环境与分配卡；登录成功不提升任何板上结果。
