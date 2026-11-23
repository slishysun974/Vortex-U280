# Iris 三分类实卡验证

后续扩容实验将留出预测覆盖到全部 150 条真实记录，并与本机单线程 CPU 对照测量至 65,533 行批量。[六档性能及 U280 运行监测](IRIS_U280_PERFORMANCE_20261123.md)

2026-11-23，固定 U280 完成 Iris 推理的 9 组用例。正式批次的 **135 个整数距离、45 个类别全部与启动前冻结的有理数答案一致**。按花的真实类别计，分类正确 **40/45（88.89%）**。SimX、处理器 RTL 和 NOXRT AFU 也各通过相同的 9 组。四路输出有效区、尾部和两端保护区逐字节一致。[四路复核回执](../results/iris-review-20261123-v1/summary.json) · [45 条实卡预测及原文件行号](../results/iris-review-20261123-v1/board-predictions.json)

## 数据和模型

原始文件为 R. A. Fisher 的 UCI `bezdekIris.data`。每类按原行序分出 35 个训练样本和 15 个测试样本，原文件行号从 1 开始。四个特征依次为花萼长、花萼宽、花瓣长、花瓣宽，均以整数毫米计。CPU 从训练集求每类各维之和，除以 35 即为类别中心。另以有理数计算样本到中心的平方距离，再乘以 1225 生成期望输出。冻结清单 SHA-256 为 `34d9c44e029649b5a2306235c7fef6765beea0d02a4e7b290a85917104deaeb2`。[来源与许可](../experiments/iris-u280/data/README.md) · [划分行号](../results/iris-freeze-20261123-v1/corpus/split.json) · [参考程序](../experiments/iris-u280/freeze.py) · [冻结清单](../results/iris-freeze-20261123-v1/corpus/manifest.json)

| 真实类别 | 四个训练特征和（mm） | 实卡预测 setosa | 实卡预测 versicolor | 实卡预测 virginica |
|---|---|---:|---:|---:|
| setosa | 1753，1199，511，86 | 15 | 0 | 0 |
| versicolor | 2093，988，1489，470 | 0 | 12 | 3 |
| virginica | 2302，1032，1940，712 | 0 | 2 | 13 |

原文件第 51、78、84、114、128 行是五个误分类样本。例如第 51 行真实类别为 versicolor，实卡距离依次为 1941222、169609、165957，最近中心为 virginica。这三个距离和类别编号 2 都与精确答案相符。[逐行预测与真实标签](../results/iris-freeze-20261123-v1/corpus/classifier.json) · [实卡原始输出](../results/iris-board-20261123-v1/returned/iris-board-20261123-v1/u280-xrt/test45/out.after.bin)

## 从第一朵花到实卡回读

1. 原文件第 1 行给出的四个厘米值为 5.1、3.5、1.4、0.2。主机向设备传入 `[51,35,14,2]` mm 和上表的 12 个模型参数。真实标签留在本地。[原始文件](../experiments/iris-u280/data/bezdekIris.data) · [实卡启动前输入](../results/iris-board-20261123-v1/returned/iris-board-20261123-v1/u280-xrt/test45/x.before.bin)
2. 同一份 PTX 经过默认 v1.2 前端，在 D5 与 U280 的两个隔离目录分别编译和校验。两份 vxbin 的 SHA-256 均为 `9ae0e644040d13d558b58d2e5c8dd502a71a82017202168161bf2e09267ddcdd`，各自的 manifest 绑定各自的目标锁。模块 ABI 为 32 B，三个 u64 指针在偏移 0、8、16，u32 样本数在偏移 24，末尾四字节填零。[内核源码](../ptx/samples/iris_nearest_centroid_u32.ptx) · [双目标构建与 ABI 核对](../results/iris-build-20261123-v1/summary.json) · [板用 manifest](../results/iris-build-20261123-v1/modules/board/manifest.json)
3. 实卡本批次的 `x/sums/out` 三个数据区地址为 `0x10010 / 0x10450 / 0x104d0`。一次启动 2 个块，每块 32 线程，前 45 个线程各自处理一行。第一个线程对类别 0 计算的距离为 `32² + 26² + (−21)² + (−16)² = 2397`。[实际基址](../results/iris-board-20261123-v1/returned/iris-board-20261123-v1/u280-xrt/test45/bases.json) · [32 B 参数原件](../results/iris-board-20261123-v1/returned/iris-board-20261123-v1/u280-xrt/test45/params.bin)
4. 完成事件返回后，输出分配第 16 至 31 字节为 `5d 09 00 00  6a f9 13 00  82 04 2b 00  00 00 00 00`。按小端 u32 读得三个距离 `[2397,1309034,2819202]`、类别 `0`。其余样本按 16 B 步长定位，最后 19 行保持初值。[实卡完成事件](../results/iris-board-20261123-v1/returned/iris-board-20261123-v1/u280-xrt/test45/event.json) · [实卡输出原件](../results/iris-board-20261123-v1/returned/iris-board-20261123-v1/u280-xrt/test45/out.after.bin)

## 各层证据

| 层级 | 实测结果 | 原件 |
|---|---|---|
| CPU 正式冻结 | 150 行，105/45 划分，9 组输入和答案。离线从原文件重算得到相同清单 | [冻结回执](../results/iris-freeze-20261123-v1/summary.json) |
| 源码核验及模块构建 | 固定 WSL 上游 HEAD 与根 lock 一致，跟踪文件 diff 退出 0。D5、U280 各自 prepare、build、validate 均退出 0 | [命令、日志与身份](../results/iris-build-20261123-v1/summary.json) |
| SimX | 9/9，54 份前后完整缓冲区核验通过 | [SimX 复核](../results/iris-review-20261123-v1/logs/02_review_simx.log) |
| 处理器 RTL | 9/9，54 份前后完整缓冲区核验通过 | [rtlsim 复核](../results/iris-review-20261123-v1/logs/03_review_rtlsim.log) |
| NOXRT AFU | 9/9，54 份前后完整缓冲区核验通过 | [xrtsim 复核](../results/iris-review-20261123-v1/logs/04_review_xrtsim.log) |
| 物理 U280 | 9/9，54 份前后完整缓冲区核验通过。板端、SSH、本地比对均退出 0，96 份回传文件通过哈希核验 | [板端回执](../results/iris-board-20261123-v1/result.json) · [传输回执](../results/iris-board-20261123-v1/transport.json) |
| Python 运行器自测 | 固定 WSL 共 316 项，314 通过、2 跳过，退出 0 | [命令与输出](../results/iris-selftest-20261123-v2/summary.json) |

九次启动覆盖正式 45 行、空批、单样本、31/32/33 行块边界、运行时模型换序、并列距离和数值端点。并列用例的两个赢家分别为 0 和 1，端点覆盖 49,000,000。每次均核对完成事件、实际参数、输入和模型的全区、输出有效区、尾部及保护区。每个后端各取一次正式回读副本，分别破坏距离、类别、尾部字，核验器准确报告分配内的第 16、28、736 字节并拒绝了全部 12 次改动。[九例定义](IRIS_U280_PROJECT_PLAN.md) · [实卡逐例与负对照](../results/iris-review-20261123-v1/logs/05_review_u280-xrt.log)

本次实卡为 `0000:b1:00.1`，当次 XRT index 3、HOST 256 MiB、DATA_CLK 200 MHz。门禁核对了 D10 xclbin 和 D12 主机库，并在关闭后确认卡空闲。实验证据覆盖固定镜像的完成事件和可见内存结果。逐 lane 的实卡读取、性能与故障恢复均未测量。数学参考与设备内核分别实现；本轮工程机器复核已完成，非作者复现与具名签收待办。[当次门禁与收尾快照](../results/iris-board-20261123-v1/returned/iris-board-20261123-v1/binding/sessions/iris-board-20261123-v1/gate.json) · [实卡可观测范围](PTX_U280_TAIL_OBSERVABILITY_20261122.md)

## 复现

在固定 WSL 的项目根目录使用新标识。下列首次四路收尾命令依赖本地完整传输回执和绑定原件。公开副本可直接复核[扩容实验](IRIS_U280_PERFORMANCE_20261123.md)的逐次输出与计时。使用完整本地归档时，以下命令会重新从原始数据计算答案、解码四路回读并检查板端传回文件，全程使用本地证据。

```sh
python3 -B experiments/iris-u280/closeout.py NEW \
  --freeze results/iris-freeze-20261123-v1 --compiled results/iris-build-20261123-v1 \
  --models results/iris-models-20261123-v1 --board results/iris-board-20261123-v1 \
  --selftest results/iris-selftest-20261123-v2
```

要从头执行，可用下列命令重新冻结、构建和运行三种模型，然后准备只含运行输入的板测包。把 `NEW` 换成所有目标目录均未使用的标识。

```sh
tag=NEW
app=experiments/iris-u280
f=results/iris-freeze-$tag/corpus
b=results/iris-build-$tag
m=results/iris-models-$tag
python3 -B "$app/run.py" freeze "$tag"
python3 -B "$app/run.py" build "$tag"
python3 -B "$app/run.py" models "$tag" --frozen "$f" --compiled "$b"
python3 -B "$app/run.py" selftest "$tag"
python3 -B "$app/board.py" "iris-board-$tag" --frozen "$f" --compiled "$b" --models "$m" --bdf 0000:b1:00.1
```

在可用的板卡窗口，从项目根目录的 PowerShell 运行下列命令，将运行标识换成上一步的标识。SSH 密码在终端提示处输入，门禁和回传由入口执行。随后将第一条离线复核命令的五个路径指向新产生的回执。[板测入口](../scripts/Invoke-CV03U280.ps1)

```powershell
.\scripts\Invoke-CV03U280.ps1 -RunId iris-board-NEW -Server '<SERVER_HOST>' -Account '<SERVER_USER>'
```
