# 2026-11-11 公开快照说明

公开仓库为 [slishysun974/Vortex-U280](https://github.com/slishysun974/Vortex-U280)。本次整理更新源码、接口与状态说明，收录两套冻结验收语料、新独立接收的四路输入输出及模型恢复实验，并增加 [服务器访问与目录导航](SERVER_GUIDE.md)。原本地证据和历史失败记录保持不变。

## 内容与身份

- `configs/acceptance/` 的冻结输入、答案和 manifest 原样保留；当前 runtime 的六个生产文件原样保留。
- 四路新语料的数组 `.bin` 原件保留，可以离线执行独立检查器。命令见下文；这只重核已有输出，不是新一次 RTL、AFU 或板上运行。
- 含账号、服务器地址和本机用户名的文本以脱敏副本提供。原记录内的历史 SHA-256 字段不改写，因此不应把脱敏文本重新计算的哈希解释为原件哈希。
- 公开副本中的 `publication/manifest.json` 列出原件哈希（有来源记录时）、公开文件哈希和变换类型；自身不递归计入清单。继承自旧公开提交的文件以公开哈希标识。
- 完整工具链、native 动态库、FPGA xclbin/DCP/XO、WSL 镜像、课程原件及服务器访问资料不随仓库发布。文档中缺少的归档链接会指向公开副本的 `docs/LOCAL_ARCHIVE_INDEX.md`，明确需要本地原件。

## 公开副本检查

在仓库根目录执行：

```bash
python -B -m unittest discover -s tests -v
python -B scripts/e_acceptance/runtime_unseen_check.py --corpus configs/acceptance/e-runtime-unseen-20261111-v1 --run results/e-runtime-unseen-sim-20261111-v1/simx --out simx-recheck-new.json
python -B scripts/e_acceptance/runtime_unseen_check.py --corpus configs/acceptance/e-runtime-unseen-20261111-v1 --run results/e-runtime-unseen-sim-20261111-v1/rtlsim --out rtlsim-recheck-new.json
python -B scripts/e_acceptance/runtime_unseen_check.py --corpus configs/acceptance/e-runtime-unseen-20261111-v1 --run results/e-runtime-unseen-sim-20261111-v1/xrtsim --out xrtsim-recheck-new.json
python -B scripts/e_acceptance/runtime_unseen_check.py --corpus configs/acceptance/e-runtime-unseen-20261111-v1 --run results/e-u280-unseen-20261111-v1/returned/execution/e-unseen --out u280-recheck-new.json
```

每次使用新的输出文件名，检查器拒绝覆盖。公开副本验证记录位于 `results/publication-check-20261111-v1/`。

部分历史自测依赖未发布的大型构建包、实际 D10/D12 二进制、Vivado 报告、完整上游检出或特定平台。对应检查在缺少材料时明确 SKIP，不改变已有断言，不把 SKIP 算作 PASS。本地完整工作区的 268 通过/1 跳过与本次公开副本结果分别报告。

## 使用范围

公开脚本中的 `192.0.2.28`、`u280user` 和 `C:/Users/example/` 是示例。实际连接前需配置本人获授权的服务器与工具路径；访问资料在本机独立保存。上传代码不授予共享设备权限。

当前完整 P0、物理故障恢复和性能/AI 对照研究尚未完成。物理恢复 NOT_RUN、旧 DMA 隔离依据 BLOCKED、TIMING-7 OPEN 均保留，详见 [阶段成果](PROJECT_PROGRESS_REPORT_20261111.md)。
