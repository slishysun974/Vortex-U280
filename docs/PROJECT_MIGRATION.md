# 独立项目拆分与验证

日期：2026-11-08，Asia/Shanghai。来源：`D:\思政大课课题\vortex_project`；目标：`D:\Vortex-U280`。

## 保留与排除

整体保留当前 Vortex 项目的 docs/configs/scripts/tests/experiments/results/references/upstream，以及上游 Git 元数据、已初始化的两个子模块和未初始化子模块的原状态。老师提供的原始 ZIP 另行复制到参考资料目录。

旧 AEC `u280_gpgpu/`、FIFO `circuits/`、历史报告/备份、课程环境/服务器连接工具与 `.server-access/` 不迁入。当前 U280 服务器与课程服务器的关系未确认，旧连接入口不是当前项目依赖。仅跳过两个 Python 缓存文件；已有失败与 v1/v2 证据全部保留。

## 整理内容

- 当前项目成为根目录，移除现用文档和命令的 `vortex_project/` 前缀；WSL 路径改为 `/mnt/d/Vortex-U280`。
- 更新 README、启动清单、平台说明和状态导航，去掉对原项目的可点击文件依赖。
- 补齐根目录 AGENTS.md、交接说明与 Codex 添加步骤；保留现有研究边界与协议。
- 单元测试中的合法路径示例同步改成新根路径；测试逻辑和运行脚本未改动。
- `configs/`、上游源码、Git 对象/提交、旧 `results/`、`experiments/` 和原参考文件不改写。Git 在迁移后的检查中可能刷新三个索引缓存；对这些缓存另核对 HEAD、暂存差异和工作树，实际哈希变化写入完整性报告。日志中出现的旧路径作为原始事实保留。

## 验证记录

本次检查仅覆盖目录迁移、文件完整性、Git 身份、配置哈希、文档链接、脚本语法和已有 Python 单元测试。记录位于 迁移结果目录（本地记录 `results/project-migration-20261108`）：

- `file_manifest.json`：每个来源文件的哈希、去向和复制/更新/缓存排除分类。
- `integrity.json`：整理副本的完整性与离线检查结果。
- `runner-tests.log`：Windows Python 运行器自测，Linux 子进程组用例按平台跳过。
- `destination-integrity.json`：最终路径的首次检查，记录 Git 索引缓存刷新的差异。
- `destination-integrity-final.json`：识别索引缓存变化后，核对提交、暂存区、工作树及其余文件的最终检查。
- `runner-tests-destination.log`：最终目录的运行器测试。
- `publication.json`：逐文件比对、来源未改动确认及最终检查结论。

通过上述检查不能解释为 Vortex kernel、处理器 RTL、AFU、PTX 或 U280 验收通过；功能状态仍以 [STATUS](STATUS.md) 为准。没有执行工具安装、系统升级、远程连接或板卡配置。

## 使用与回查

后续工作只使用新目录；从新目录执行 [复跑说明](AB_D1_PROGRESS.md) 的命令。原项目保留，不删除、不搬走、不覆盖其中的源码和结果。无需原项目即可使用本次保留的当前材料；需要旧 AEC/FIFO 历史时再单独打开原项目。
