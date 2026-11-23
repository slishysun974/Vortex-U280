# V08 本地 AI 协作试验

**12 个席位已开题，11 份提交通过验收。** 单智能体 5/6，双智能体 6/6。五个双方均封存的题对全部双过。余下一对的单智能体席位因调度器计量错误提前停止。这次数据无法把两组通过数的差异归因于审查智能体。[本地实验汇总和逐席位结果](../results/ai-paired-local-receipt-20261122-v1/result.json)

按用户指定的本地运行方式，`V08-local-v2` 由本机调度公开卡、转交模型意见、封存源码，并在本地用 CPython 3.13.13 独立重放。推理通过当前登录的 Codex 模型服务。原 v1 规定的两名真人 P/Q 未参加，原版仍为 0/12。两版共用原清单、题卡、分组、顺序和私测。[本地试验规程](../experiments/ai-paired-local-v2/protocol.md) · [原版冻结规程](../experiments/ai-paired-v1/protocol.md)

每个席位获一次初稿、一次审查和一次定稿机会。单智能体复用同一上下文自审，双智能体由独立上下文审查初稿，原实现者定稿。两组均请求 `gpt-6.2-sol / medium / priority`，单卡材料经标准输入投递，模型调用从项目外空目录发起。审查为串行，两组均在模型内核对公开样例。全部已封存提交均在 45 分钟和 60,000 token 以内。费用及服务端部署版本无回执，人工维护时间未单独计量。[发放顺序与协议哈希（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-10b1aa46f1c6) · [中性计量探针（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-c6f1516eff35)

| 题对 | 单智能体结果 | 双智能体结果 | 单 / 双 token | 单 / 双墙钟（秒） |
|---|---|---|---:|---:|
| T1 诊断顺序 | A 未封存，FAIL | B PASS | 26,752 / 40,418 | 39.1 / 55.0 |
| T2 谓词分组 | B PASS | A PASS | 39,904 / 39,362 | 51.3 / 49.6 |
| T3 参数布局 | A PASS | B PASS | 41,943 / 40,273 | 64.9 / 57.9 |
| T4 单槽恢复 | A PASS | B PASS | 40,690 / 40,045 | 593.2 / 55.7 |
| T5 握手时序 | B PASS | A PASS | 40,406 / 39,616 | 56.5 / 52.9 |
| T6 快照比对 | B PASS | A PASS | 40,605 / 40,010 | 58.4 / 57.4 |

全部席位共计 470,024 token，其中单智能体 230,300、双智能体 239,724。11 份封存源码覆盖 89 个不同私测，两个新目录各回放一次，178 次输出全部精确匹配，22 个重放进程均退出 0。11 个公开样例也全部通过。两个组各只有 6 个席位，各题对使用相近变体。[逐席位命令、退出码、用量与判分](../results/ai-paired-local-receipt-20261122-v1)

## 计量偏差与中断

首次中性探针在沙箱启动 CLI 时被拒绝，获准后在空目录取得 token 回执。正式 T1A 的初稿与自审共消耗 26,752 token。初版调度器把续接上下文的累计值再次相加，进而以剩余预算不足为由提前关闭席位。原始 FAIL 保留，该卡没有定稿、隐藏判分或补交。验收端按会话作差，再用每一次请求的供应方 `last_token_usage` 独立复核。T1B 的最终统计也采用纠正后的逐请求用量。[首次探针错误（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-a0d67548783a) · [T1A 原始终止（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-b7f723d4c097) · [逐请求计量（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-159324f18a4b)

修正发生时 T4A 已完成初稿。原审查进程未返回任何事件，供应方日志仅有初稿一次已完成的 turn。在同一上下文续接审查和定稿，封存一次。表中的 593.2 秒包含暂停、核对和等待。其余未发席位保留原发放顺序。下次采集可用新题，先以中性多轮续接校验累计及逐轮用量。[原调度器快照（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-a69e56a99d23) · [计量更正回执（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-9fcd9ffef6ec) · [T4A 中断核对（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-18a20f0a5f6d)

重核现有封存提交时，在本机项目根目录执行以下命令并使用新的输出目录。计量复核需能读取本机这些受试会话的供应方日志。原 v1 私测和已封存源码均通过哈希绑定。[接收程序（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-37ba75f49b67)

```powershell
python -I -B experiments/ai-paired-local-v2/receive.py results/ai-paired-local-20261122-v1 results/ai-paired-local-receipt-NEW
```
