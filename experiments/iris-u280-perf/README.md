# Iris 扩容与性能测量

从项目根目录运行。离线复核已有数据与指标的命令见[完整报告](../../docs/IRIS_U280_PERFORMANCE_20261123.md)。下列命令在固定 WSL 生成新冻结副本、实际运行本机 CPU、准备实卡输入。需要正式 Iris 板用模块；构建方法见[首次 Iris 实验](../../docs/IRIS_U280_RESULTS_20261123.md)。输入包携带运行所需分配，准确率标签和有理数答案留在验收端。

```sh
tag=NEW
app=experiments/iris-u280-perf
f=results/iris-perf-corpus-$tag
python3 -B "$app/corpus.py" "$f"
python3 -B "$app/cpu.py" "$f" "results/iris-perf-cpu-$tag"
python3 -B "$app/prepare.py" "iris-board-perf-$tag" --corpus "$f" \
  --module results/iris-build-20261123-v1/modules/board
```

在有板卡窗口的 PowerShell 运行 `.\scripts\Invoke-CV03U280.ps1 -RunId iris-board-perf-NEW -Server '<SERVER_HOST>' -Account '<SERVER_USER>'`。终端登录后自动核对 D10/D12 身份、执行测量并回传。每轮使用新标识。CPU 和 U280 都会将完整输出与冻结答案逐次比较，公开数据可在普通主机离线复核。
