# D9 后的完整 FPGA link 准备单

2026-11-09 更新：本方案已执行完成，`u280-link-20261109-103830-671` 于 15:48:08 **PASS**，v++ 与固定 200 MHz 检查均退出 0；[最终记录](../../results/u280-link-20261109-155638-456/returned/build/result.json)、[D10 与后续工作](../../docs/AB_D10_PROGRESS.md)。下文保留当次启动方法，不需要再次提交此构建。成功 xclbin 留存远端，下一步审阅报告和准备上板条件。

授权：2026-11-09 用户回复“按此启动”，已确认本单的两个 CPU、nice +10、6 小时 v++ 超时及无 RAM 硬限方案。无需再次请求资源授权。远端实际作业状态与证据见 [D10 记录](../../docs/AB_D10_PROGRESS.md)；授权本身不代表构建已完成。

已具备：2026-11-09 10:10 完成的 XO，Vivado 2023.1、U280 part、五个 IP OOC、RTL elaboration 与原接口 gate 均实际通过。完整证据见 [D9](../../docs/AB_D9_PROGRESS.md)。XO 保留在服务器个人隔离目录；大小 312,868 字节，SHA-256 `58ff5ed950d738f232f5fa70e4c4fcf82ebd2b73bb3d247cfc00133f51e66b0d`。

执行限制：CPU affinity 两个 CPU、nice +10、综合/实现 jobs=2、实现 maxThreads=2、v++ 最长 6 小时。启动器检查当次可用 RAM 至少 64 GiB、个人工作目录所在磁盘可用空间至少 50 GiB；这是启动预算，不是已实测整机需求，运行器没有 RAM 硬限。线程限制不代表内存限制。

本机提交入口（用户在 SSH 提示处输入密码）：

```powershell
& 'D:\Vortex-U280\scripts\Invoke-U280Link.ps1'
```

入口自动生成新 run_id，核对已通过 XO、构建脚本、288 项输入和平台文件的哈希；检查下列资源后以独立后台会话启动。互斥锁防止同项目后台作业并行重复启动，已有目录不覆盖。SSH 退出后后台作业继续运行，传输 PASS 不代表构建 PASS。

查询已提交作业（每次查询生成新的本地采集目录，不会重启构建）：

```powershell
& 'D:\Vortex-U280\scripts\Invoke-U280Link.ps1' -Mode Status -BuildRun '<已提交的 run_id>'
```

自动执行的只读资源命令：

```bash
id -un
hostname
uptime
free -h
df -h /home/u280user
```

后台执行的已绑定输入/XO/补丁命令如下（实际 run_id 由提交入口生成，不能清空旧目录）：

```bash
python3 -B /home/u280user/vortex-u280-probes/u280-preflight-20261109-100406-629/build_prepared.py \
  --input /home/u280user/vortex-u280-probes/u280-preflight-20261109-100406-629/u280-rtl-input \
  --run-id u280-link-20261109-v1 --stage link --build-flow ip-ooc-v1 \
  --xo-run /home/u280user/vortex-u280-builds/u280-preflight-20261109-100406-629
```

这一步按独立候选连接 `m_axi_mem_0:HBM[0:31]`、`m_axi_host:HOST[0]`，目标 200 MHz、禁用频率缩放检查，保留 v++ 中间产物。它不要求先配置板卡，也不加载 xclbin。只有 link、固定时钟检查及产物存在性全部通过，才能记录构建阶段 PASS；之后仍须审阅完整资源/时序、xclbin 元数据和 shell UUID。

本次 XO 的时钟/依赖/未引用文件 warning 原样保留，需在完整构建中验证。接板前还要处理 HOST 权限/内存启用、当前空闲卡选择、XRT index、真实 host runtime 的服务器编译兼容性，以及 runtime 编译时钟 400 MHz 与实际实现频率的绑定。没有这些证据，不能报告板上功能或性能 PASS。
