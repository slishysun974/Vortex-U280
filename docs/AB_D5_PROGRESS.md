# A/B D5：B=32 候选与 U280 入口复核

日期：2026-11-08，Asia/Shanghai。用户要求继续 A/B，并核实老师 ZIP 是否提供 U280 入口。

本轮完成：SimX、处理器 RTL、NOXRT AFU 模型各 **152/152 次原生启动 PASS**，每路含 122 次 B=32 启动；B=33/64 拒绝检查通过。三路命令退出 0，kernel、语料与捕获一致，[收尾 84 项核验全部通过](../results/ab-d5-closeout-20261108-v1/result.json)。这是同作者 reference 的 A/B 自测，候选仍待团队接收；物理 U280 继续 BLOCKED。

## U280 入口与本机实测

22:19 后续更新：用户在终端改用另一个密码，`u280user` 登录 PASS，WLAN 绑定连接 U280 后实际执行 `id -un && hostname`，返回 `u280user` / `localhost`、SSH 退出 0。网络与账号阻塞已解除；平台与分配卡待核实，见 登录接续（本地记录 `docs/U280_LOGIN_PROGRESS.md`）。本节 21:21 的默认路径失败记录保持原样。

老师 ZIP 中的 1_README.md（本地记录 `references/teacher_u280_20261107/md/1_README.md`） 明确给出 `192.0.2.28:22`，示例 `ssh yourname@192.0.2.28` 中的 `yourname` 必须替换为另行分配的个人用户名。资料没有提供本人的账号、密码或获配卡。

2026-11-08 21:21（Asia/Shanghai）使用本机执行一次 TCP connect，不发送 SSH 认证、不枚举板卡：

| 尝试 | 结果 | 原始证据 |
|---|---|---|
| 沙箱内首次检查 | FAIL，WinError 10013，退出 1；本地权限拒绝，不能推断远端状态 | v1（本地记录 `results/ab-d5-u280-network-20261108-v1/probe.json`） |
| 授权后沙箱外检查 | FAIL，5.026 秒连接超时，退出 1；当前本机路径未连通 | v2（本地记录 `results/ab-d5-u280-network-20261108-v2/probe.json`） |

不能由此认定服务器宕机或账号无权限。需要资源方确认校内网络/VPN或路由条件，提供个人用户名、认证方式与获配卡；登录和板卡查询仍 NOT_RUN，U280 仍 BLOCKED。历史资料接收记录不改写。

检查入口：`python -B scripts/probe_u280_endpoint.py --output results/u280-network-NEW/probe.json`；输出独占创建，连接上限 5 秒，目标固定为资料中的单个 SSH 端口。

另将真实 XRT runtime、平台连接、FPGA Makefile 与上板指南四份源码和固定清单比对并保存副本，命令退出 0、4/4 哈希匹配：源码核验（本地记录 `results/ab-d5-u280-source-20261108-v1/summary.json`）。由源码确认：真实 XRT 的设备初始化会加载 xclbin；设备选择需要把获配 BDF/UUID 映射到当次整数 index；HOST[0] 的 host-only BO 与 NOXRT 模型内存分配不同。已写入接收单。这些是源码要求，不是服务器环境或设备结果。

## B=32 候选的变更与接收

固定 `sw/runtime/common/queue.cpp` 在 launch 前查询 threads 与 warps，并拒绝 block>threads×warps。D4 的 4w×4t 因此拒绝 B=32。本轮增加 [block32-v1 候选](../configs/candidates/block32-v1/README.md)，只把 warps/core 从 4 改为 8；物理 lanes 仍为 4。当前根 lock/caps 与旧结果保留，未修改上游源码、P0 ABI 或 PTX 白名单。

候选独立版本、配置哈希、父 lock 和接收范围见候选说明。接收为项目配置仍需要 A/C/D 对齐和 E 独立复跑，本轮实施者的 reference 自测不代替接收。B=32 执行支持也不意味着 32-lane warp 语义。

固定配置生成器会随 warps 派生调整 `NUM_OPCS:1→2`、`LSU_PENDING_SIZE:8→16`、`AMO_RS_SIZE:4→8`；这些连同 `NUM_WARPS:4→8` 是与 D4 同 backend 配置比较的差异，收尾脚本逐路核对。没有手工覆盖其余派生参数。

运行器 schema 升为 6，增加显式 `--target-profile block32-v1`；原默认仍为 `smoke`。native 测试语料 schema 升为 v2，host 从同一配置编译的定义核对 runtime 所报 threads/warps/core。

候选语料含 76 个参数组合，各两组输入，共 152 次连续 launch：完整 N/alpha 矩阵使用 B=32；N=33 另测 B=1/4/7/16/31；B=32 测全假/交替条件。额外检查 B=33 和 B=64 返回 `VX_ERR_INVALID_VALUE`。输入、期望、实际 x/y/z/线程记录和源文件快照分别保存。原生私有参数结构保持 48 bytes，仍不是项目参数 ABI。

## 运行状态

总入口：`wsl -d Vortex-AB-Ubuntu-22.04 --cd /mnt/d/Vortex-U280 -- python3 -B scripts/run_block32_validation.py --run-id ab-d5-block32-20261108-v1`。

先执行 `python3 -B -m unittest discover -s tests -v`：26 项中 25 通过、1 平台跳过，退出 0；包括候选/配置不匹配时拒绝和 B=32 语料覆盖检查。这仅验证脚本行为。

三路使用全新 `/opt/vortex-ab/builds/ab-d5-block32-20261108-v1-<backend>`；源码与工具包仍来自交接记录的固定目录。[总日志](../results/ab-d5-block32-20261108-v1/summary.json) 保存脚本自测、执行前代码快照与各路完整入口，整体命令退出 0。

| 层次 | 实际结果 | 证据 |
|---|---|---|
| 运行器自测 | PASS，25 通过/1 跳过，退出 0 | [测试原始日志](../results/ab-d5-block32-20261108-v1/logs/01_runner_tests.log) |
| SimX | PASS，demo + 152/152，B=33/64 拒绝，退出 0 | summary（本地记录 `results/ab-d5-block32-20261108-v1-simx/summary.json`） |
| 处理器 RTL | PASS，demo + 152/152，B=33/64 拒绝，退出 0 | summary（本地记录 `results/ab-d5-block32-20261108-v1-rtlsim/summary.json`） |
| NOXRT AFU 模型 | PASS，demo + 152/152，B=33/64 拒绝，退出 0 | summary（本地记录 `results/ab-d5-block32-20261108-v1-xrtsim/summary.json`） |
| 证据收尾 | PASS，84/84，退出 0 | [核验结果](../results/ab-d5-closeout-20261108-v1/result.json) |
| U280 物理平台 | BLOCKED；登录、FPGA 构建与板上执行 NOT_RUN | 当前本机 TCP 超时、个人账号与分配卡待落实 |

收尾重新核对原始日志、退出码、配置快照、实际工具哈希、源码清单、全部输入/期望/实际输出和构建产物；三路实际 CAPS 均为 threads=4、warps=8、cores=1。根目录三份基线配置哈希未变。三路重新构建的 native kernel SHA-256 均为 `19b5aeddbaf2a0d664295a7b0811b1fba9999aa73c0ee157994766db799f8505`；与 D4 相同是本程序未依赖 warp 数的编译结果，不是复用旧构建产物或证明时序等价。

复核命令：`python -B scripts/verify_block32_results.py --run-id ab-d5-block32-20261108-v1 --output results/ab-d5-closeout-NEW`。重跑三路可使用 `scripts/run_block32_validation.py --run-id NEW`；它只调用已准备好的工具，不下载、安装或访问远端。单路重跑使用原 smoke 命令加 `--target-profile block32-v1 --native-boundary` 并指定新的 run/build 目录。

## 尚未证明

PTX 转换、项目 runtime/ABI、E 独立答案、假谓词完全无读访问、严格恰执行一次、安全中止/恢复、真实 XRT/HOST[0]/HBM、FPGA 时序与板卡执行仍未接收。线程记录和输出正确不能单独证明前述内存访问与执行次数语义。下一步向 C/D/E 交候选接收材料，补访问 trace，再接 PTX 产物；物理平台先解决网络和个人资源分配。
