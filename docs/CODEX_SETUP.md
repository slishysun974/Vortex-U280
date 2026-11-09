# 添加为新的 Codex 本地项目

1. 在 Codex 的项目入口新建本地项目，名称使用 `Vortex-U280`。
2. 文件夹只选择 `D:\Vortex-U280`，将它作为主文件夹；无需附加原来的大工作区。
3. 在新项目中开始新的聊天。根目录的 `AGENTS.md` 提供项目约定。
4. 首条消息可以使用下文。旧项目与旧聊天保留回查，不需要迁移完整聊天记录。

```text
这是 Vortex-U280 独立项目。请先读 AGENTS.md、docs/PROJECT_HANDOFF.md、docs/STATUS.md 和 docs/AB_D1_PROGRESS.md，核对固定源码、draft 配置、当前环境阻塞和下一步。现有源码身份已核验，但原生 SimX/RTL、PTX 路径和 U280 板上验收尚未通过。请从兼容 Linux 仿真环境与原生 SimX 预检继续推进，并保留每轮真实证据。
```

新增项目是应用中的操作。当前整理任务只准备目录和文件，没有修改 Codex 的内部项目数据库，也没有创建或移动聊天。

官方说明：[Projects and chats](https://learn.chatgpt.com/docs/projects)。项目的主文件夹决定新聊天的默认工作目录，并用于 Git 和项目约定发现。
