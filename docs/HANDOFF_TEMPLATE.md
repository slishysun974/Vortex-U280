# Vortex 项目交接、变更与 AI 任务模板

配合 [合作接口协议](COLLABORATION_PROTOCOL.md) 使用。每位负责人填写自己交付，C 汇总集成版本，E 汇总独立验收和研究数据。未运行写 NOT_RUN，不把计划写成证据。

## 1. 模块交接

```text
交接标题 / 日期：
接口：V01—V08 中的实际编号
交付人 / 接收人：
状态：草稿 / 自测通过 / 待接收 / 接收通过 / 带限制接收 / 退回

【身份与范围】
team / profile / ABI 版本：
Vortex commit / 子模块 / 补丁哈希：
LLVM或VOLT / runtime / 编译选项：
target_lock_hash / hardware_config_hash：
源码 commit 或完整文件 SHA-256 清单：
image / manifest / bitstream 哈希（不适用写 N/A）：
backend：mock / cpu-oracle / simx / rtlsim / u280-xrt
源PTX版本 / target / address_size：
目标XLEN / device pointer / 线程映射：
支持范围、依赖、未支持项与已知限制：

【接口行为】
入口 / 参数布局 / 对齐 / 生命周期：
预期输出或响应：
拒绝、错误、完成与恢复语义：
可观察的fault信息及不能检测的行为：

【复现与证据】
工作目录、构建/运行命令：
输入文件 / 种子 / 参数字节：
独立oracle及其来源/版本：
实际输出 / 原始日志 / 退出码 / run_id：
正例、边界、拒绝、重复运行、恢复各自结果：
性能测量方法与单位（未测写 NOT_MEASURED）：

【接收人填写】
复现日期 / 环境 / 实际命令：
是否独立复现 / 接收结论：
失败证据或接受的限制：
待办负责人 / 交付日期 / 兼容矩阵条目：
```

## 2. 接口变更

```text
change_id / 接口 / 提出人：
旧版本 → 新版本：
字段或行为旧值 → 新值：
原因 / 兼容性影响：
影响的实现、样例、profile、ABI、测试、bitstream：
两端负责人 / 受影响人确认记录：
迁移方法 / 是否重编或重建：
验证命令 / 通过条件 / 生效版本：
```

## 3. 最小失败与定位

```text
问题 / 发现人 / 当前owner / 接口双方：
backend / run_id / event_id / context generation：
模块、lock、image、bitstream身份：
source_location / phase / code / native_status：
PC/core/warp/lane（只有实际可获取时填写）：
预期与首个偏差：
最小源码 / 输入 / 命令 / 原始日志：
CPU oracle / 原生Vortex / PTX-SimX / RTL / 板上各自结果：
下一定位动作 / 负责人 / 反馈日期：
修复 / 新增回归 / 接收人复测与关闭：
```

## 4. 智能体任务与研究记录

```text
task_id / parent_id / 人类owner / 人类接收人：
实验组别 / 配对任务ID / 分配方法：
模型ID与版本 / 工具与上下文资料：
任务目标 / 起始源码快照 / 依赖与接口：
可改目录 / 保护目录（含冻结oracle与验收）：
交付物 / 验收命令 / 正例与失败用例：
总时间/token或费用预算（含所有子智能体）：
任务卡与prompt路径 / 工具轨迹 / 代码差异：
首次结果 / 后续修复轮次 / 失败或超时：
人工主动分钟 / 工具分钟 / 等待分钟 / 总墙钟：
累计token / 已知费用 / 未能观测项：
人工修改与原因 / 审查结果 / 独立接收证据：
验收后发现的缺陷 / 可复现结论：
```

## 5. 兼容矩阵与首次冻结

| 组合ID | lock / profile / ABI | 编译器 | runtime | RTL配置 | bitstream | 用例版本 | backend | 状态/证据 |
|---|---|---|---|---|---|---|---|---|
| 待冻结 | 待填写 | 待填写 | 待填写 | 待填写 | N/A或实际哈希 | 待填写 | 待填写 | NOT_RUN |

| 确认项 | 参与者 | 接收记录 |
|---|---|---|
| 人员姓名、时间和30天范围 | 全体 | 待填写 |
| 配套上游/工具链/硬件配置 | A/B/C/D | 待填写 |
| PTX白名单与拒绝行为 | D，A/C/E接收 | 待填写 |
| 参数、地址、线程和模块ABI | A/C/D，B核查平台，E验收 | 待填写 |
| runtime完成与恢复 | B/C，A配合，E验收 | 待填写 |
| 独立答案、冻结测试与AI任务 | E，各owner接收 | 待填写 |
