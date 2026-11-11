# Vortex-U280

Vortex-U280 是一个 GPU 兼容编译的研究原型。项目让一部分用 PTX 编写的 GPU 程序在开源 Vortex GPU 上运行，并在 Alveo U280 FPGA 加速卡上验证计算结果。

PTX 是 NVIDIA 定义的 GPU 虚拟指令集，用于描述 GPU 上要执行的计算。Vortex 使用自己的指令体系，因此需要转换程序，同时保持每个线程的计算和内存访问行为。

## 从向量加法看起

向量加法把两个数组中相同位置的数相加。比如 `[1, 2, 3]` 与 `[4, 5, 6]` 相加得到 `[5, 7, 9]`。在示例程序中，每个参与计算的 GPU 线程处理一个位置。[查看 PTX 示例](ptx/samples/vadd_u32.ptx)

编译前端检查 PTX 源程序并将它转换成 C++，再用 Vortex 工具链生成设备程序。运行时负责准备设备内存、传入参数和启动程序。程序执行后，验证工具将输出与事先确定的答案逐字节比较。

## 已验证的范围

数组复制、向量加法和逐元素乘加是目前已验证的三类程序，均使用 32 位无符号整数。用例覆盖零长度输入、不同的线程分组和整数溢出。

独立验证使用同一组 48 个用例，分别在指令级模拟、处理器电路仿真、FPGA 加速单元仿真和 U280 实板上运行，四种环境均通过。[独立验证报告](docs/E_RUNTIME_UNSEEN_ACCEPTANCE.md)

当前支持范围限于项目定义的 PTX 整数子集。浮点运算、通用分支和共享内存等能力留待扩展，物理板卡故障恢复尚待验证。项目还计划开展性能评估与 AI 智能体协作的对照实验。[阶段成果](docs/PROJECT_PROGRESS_REPORT_20261111.md) · [研究计划](docs/RESEARCH_PLAN.md)

## 在本机开始

准备好 Git 和 Python 3.12 后，可下载代码并运行自测。

```bash
git clone https://github.com/slishysun974/Vortex-U280.git
cd Vortex-U280
python -B -m unittest discover -s tests -v
```

自测检查前端、运行器和验证工具的行为，无需连接 U280。部分检查依赖特定环境或历史归档，缺少相应条件时会跳过。

## 继续阅读

- 核对仓库里已有的实验输出，可按说明离线复核。[公开数据与复核方法](docs/PUBLICATION.md)
- 查看支持的 PTX 指令、数据类型与内存规则。[PTX 兼容性规范](docs/PTX_COMPATIBILITY_PROFILE.md)
- 准备实板实验时，先确认服务器访问权限、工具版本和板卡条件。[服务器访问与目录导航](docs/SERVER_GUIDE.md)
