# E：15 条 PTX 用例独立接收

日期：2026-11-10，Asia/Shanghai。22:22 任务完成：**非作者 AI 代理 E 限定范围接收 PASS**，结论为 `ACCEPTED_WITH_FIXED_SCOPE`。[E 签发报告](../results/e-ptx-acceptance-20261110-v2/acceptance.md)、[机器结果](../results/e-ptx-acceptance-20261110-v2/result.json)。

用户要求先对现有 15 条 PTX 用例做 E 独立接收，TIMING-7 本轮跳过。此处的 E 是新建、非作者的验收 AI 代理，不代填五人团队中人类 E 的签名，不把本轮列为 AI 配对研究实验。

## 任务卡与独立性

| 字段 | 本轮约定 |
|---|---|
| task_id / parent | `/root/e_acceptance` / 当前项目推进会话 |
| 发起人 / 接收执行者 | 用户 / 独立 E 验收代理 |
| 上下文 | `fork_turns=none`，不继承实施聊天；先读规范、PTX、原始输入和用例元数据 |
| 目标接口 | V03/V04/V05/V07 中这 15 条样例的源语义、镜像复现、启动参数和可观察输出 |
| 输入版本 | `ptx-vx-p0-v0.2-draft`、`ptx-vx-args-v1`；RV64，1 Core、8 Warp/Core、4 Threads/Warp 独立候选 |
| 身份依据 | 根 `configs/target_lock.json` 及 block32/U280 候选锁；原交付清单和各镜像 SHA-256；不把根 4w 基线改写成 8w 已冻结 |
| E 可改范围 | `scripts/e_acceptance/`、`tests/test_e_ptx_acceptance.py`、新 `configs/acceptance/` 目录、新 `results/e-ptx-*` 目录 |
| 保护范围 | 生产前端/runtime、原始 PTX/inputs/expected、全部旧结果、固定上游源码、根 lock/caps |
| 统筹代理职责 | 启动已授权的 U280 门禁脚本、收集原始返回、更新状态与交接；不编写或修改 E 的冻结 oracle |
| 预算 / 模型 | 用户未指定时间、token 或费用预算；子代理继承当前会话模型，精确模型版本/成本未通过工具观测 |
| 停止条件 | 结果与独立答案不符、身份不符、环境门禁失败时保留证据并退回或标记阻塞；不修改冻结答案迎合结果 |

## 固定接收范围

| PTX | 用例 ID |
|---|---|
| copy_u32 | 0010 / 0058 / 0070 / 0082 / 0094 / 0106 |
| vadd_u32 | 0010 / 0058 / 0070 / 0106 |
| affine_u32 | 0034 / 0176 / 0210 / 0250 / 0322 |

全部 B=32。E 从三个 PTX 源文件、各 corpus 的用例元数据及 `inputs` 单独推导 u32 模运算结果、输入保持、首尾哨兵和参数 ABI。首次冻结前不读取旧 `expected`、实际输出、比较结果或实施者 oracle；冻结文件哈希和生成日志完成后，才允许读取待验结果。E 的判据不调用生产 `capture_comparison`、`pack_arguments`、`analyze_trace` 或原四路复核器。

执行采用新目录：重新生成/构建三份镜像并与交付身份对照，重新编译宿主，SimX、处理器 RTL、NOXRT AFU 各执行 15 条。U280 复用已构建的 xclbin/runtime，由原门禁入口另建 run_id；逐条检查当次卡状态、HOST、BDF、UUID、实际 200 MHz 及退出后空闲。E 直接接收这些新运行的原始字节、参数和命令状态。

验收器另注入数据、哨兵、参数、缺失输出或部分执行错误，记录实际拒绝结果。记录每层命令、原始日志、退出码、运行目录和文件哈希；单纯哈希一致或实施者 PASS 标签不作为独立正确性结论。

## 结果边界

独立答案已先行冻结：[manifest](../configs/acceptance/e-ptx15-v1/manifest.json) SHA-256 为 `f205a527c8bb6801ed7e2d416ea4a56236109e67c4b2323f851c4690d327e7d7`；[oracle 原件](../configs/acceptance/e-ptx15-v1/oracle_v1.py) SHA-256 为 `da2df04b2f38e3adda0a9839aefec6ebdf549ddc3a2fe4f378fc369bcc016507`。统筹代理读回确认两者哈希后才打开新板测窗口。[生成日志（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-3daa8aedca68)、[退出码 0（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-5babfc27d312)。

E 新目录中的三份 PTX 镜像重建与交付 vxbin 逐字节相同；SimX、处理器 RTL、NOXRT AFU 各 15 次新执行的完整输出和 ABI 均已独立接收。SimX/RTL 每路另独立核对 903 次读、580 次写，包含三条 N=0 的真实分派、参数读取与零数组请求。[新执行原件（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-47e1767d51bf)、[最终本地接收](../results/e-ptx-acceptance-20261110-v2/local.json)。

U280 首次 `e-v1` 在密码认证阶段断开，SSH 255、远端未执行，原件保留；用户确认可输入密码后另建 `e-v2`。v2 于 22:04:28—22:08:40 在 b1 完成 15 次，SSH 退出 0；E 已直接核对原始字节、参数和当次门禁，15/15 接收。[首次断连（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-819c86f373b5)、[新板测原件（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-098f528bb6d0)、[独立板端接收](../results/e-ptx-acceptance-20261110-v2/u280.json)。

总计 60 次新执行的 156 份完整数组、60 份参数均通过独立答案；2 个正控制、23 个负例均符合预期，负例覆盖错误证据及 trace，不代替 DUT 的通用错误 API 接收。根 WSL 自测实际 140 项，139 通过、1 跳过，退出 0。[故障注入（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-3dbd399cc351)、[完整自测（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-197a8d3cc11b)。

为补齐板端宿主身份，另只读取回 15 组共 135 份原件（宿主 ELF、镜像、源文件、flags、日志）。E 核对源/镜像/日志与执行包逐字节一致；宿主哈希是运行后观测，不倒填为执行时测量。[后补原件（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-29a02d7eb8f5)、[E 绑定记录（本地归档）](LOCAL_ARCHIVE_INDEX.md#archive-9308abebcea9)。首次补采的本地换行哈希失败、E 解析器/头文件身份检查迭代、临时目录权限和退出码包装问题、总接收 v1 的日志 LF→CRLF 提取失败均保留，详情见 E 报告。这些与 DUT 功能结果分开记录，冻结 oracle/预期未修改。

最终结果 SHA-256 为 `b07c286e266c2d705c0cf986b655353c30088042ac0be013c6bc58dcb3e47ee0`。本次仅接收表内 15 条 B32 用例；不扩大为完整 P0、未见合法 kernel、通用 runtime、同一 context 连续启动/故障恢复、配置性能研究或正式人类签核。根 lock/caps 继续保持草案身份。

复现调用 E 的 `scripts/e_acceptance/reproduce.py`；总接收调用 `scripts/e_acceptance/receive.py`，显式传入新的 local-run、board-run、board-artifacts 和不存在的 output。准确本次命令、退出码、接收器版本快照及哈希均在 E 签发目录中，禁止覆盖失败目录。

TIMING-7：本轮按用户要求不处理，已有技术状态保留 `OPEN`。不将跳过写成安全性通过。
