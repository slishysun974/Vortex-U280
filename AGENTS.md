# Vortex-U280 项目约定

本约定适用于本项目根目录及全部子目录；上游检出中的细化约定同时适用。

- 本目录是独立项目根目录。命令和文档路径以此为准，不加 `vortex_project/` 前缀。
- 范围：Vortex-U280、PTX P0 子集、可复现实验与 AI 协作研究。旧 AEC/FIFO 留在旧项目。
- 开始工作先读 `docs/PROJECT_HANDOFF.md`、`docs/STATUS.md`；涉及接口时读合作协议和 PTX 规范。
- 当前源码和工具包身份以 `configs/target_lock.json` 为准；draft 不能解释为已验收能力。
- 已有 `results/`、`experiments/` 和参考原件保留原始内容。新运行使用新的 run_id，不覆盖失败记录。
- PASS 需要实际命令、输出、退出码和范围；BLOCKED/FAIL/NOT_RUN 如实区分。
- Python 运行器自测、源码核验、处理器 RTL、XRT AFU 与 U280 板上结果分别报告。
- 当前 P0 前端/runtime 和板上功能尚未完成；不能用旧工程结果或本次迁移检查充当新功能证据。
- 不改写冻结答案或现有证据来获得通过。调整配置、ABI 或白名单时同时更新版本和接收说明。
- 修改 `upstream/vortex/` 前读取其中的 `AGENTS.md`，遵守固定版本源码；补丁需单独记录。
- 构建使用隔离目录，不污染固定源码；不同 XLEN、配置和 backend 的产物不混用。
- 本次项目整理不包含工具安装、系统升级、远程登录或设备配置；后续按具体任务授权执行。
- 当前检查命令：`python -B -m unittest discover -s tests -v`；仅验证运行器行为。
- 完成工作时更新当前状态和交接说明，明确真实结果、仍有阻塞与下一步。
