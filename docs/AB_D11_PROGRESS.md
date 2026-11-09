# D11：构建归档、200 MHz runtime 准备与连接恢复

更新：2026-11-09，Asia/Shanghai。

**19:01:51：归档 PASS、完整报告已审阅；上板接收条件仍未满足。** v5 采集（本地记录 `results/u280-archive-20261109-v5/probe.json`） SSH/解包均退出 0，15 条远端元数据/环境命令均退出 0。本地已保存 xclbin（本地记录 `results/u280-archive-20261109-v5/returned/artifacts/vortex_afu.xclbin`） 53,950,442 字节，SHA-256 与 D10 一致。197 份原始报告共 181,392,380 字节，经无损压缩传输后全部解包逐文件核验；总传输载荷 60,132,806 字节。v4 触发未压缩传输上限而 FAIL，未改变构建结果；原件保留。收尾核验（本地记录 `results/ab-d11-closeout-20261109-v1/result.json`）将文件一致性与板上就绪状态分开报告。

## 报告审阅结果与未关闭项

- xclbin UUID 为 `b60ca9fb-1506-3033-c156-e03ff687f492`；interface UUID `fb2b2c5a19ed63593fea95f51fbc8eb9` 与 D9 记录的 8 张卡一致。此比较只确认历史 shell 身份，不证明当前卡空闲或可加载。
- 元数据有 33 项连接：参数 4→HOST[0]（索引 40），参数 5→HBM[0..31]；32 个 HBM 区间各 256 MiB，连续覆盖 8 GiB。HOST 元数据的存在不表示实际 host memory 已启用。
- `DATA_CLK=200 MHz`，embedded metadata 将其映射到 `ulp_ucs/aclk_kernel_00`，与固定检查的 kernel clock 00 对应。元数据另列 KERNEL_CLK=500 MHz、HBM clock=450 MHz，不能将这些名称混同为 Vortex 核心频率。
- 最终 postroute-physopt 报告：整体 WNS **+0.016 ns**、WHS **+0.006 ns**，setup/hold/pulse failing endpoints 均为 0；kernel clock 00 的 WNS **+0.119 ns**、WHS **+0.009 ns**、289539 endpoints。内部 unconstrained endpoints=0；有 **7 个输入 / 3 个输出端口缺 delay**，不能声称所有外部边界均已约束。
- 布线报告：455506 个 routable nets 全部 routed，routing errors=0。
- 普通 DRC 共 343 项，汇总均为 Warning/Advisory，没有 Error/Critical Warning。Methodology 共 100 项，包含 **9 项 Critical Warning**：TIMING-1×1、TIMING-7×1、TIMING-14×1、TIMING-54×6。TIMING-1 明确指出 kernel clock 00 约束为 5 ns，而时钟模块默认参数对应 3.333 ns；需要结合平台动态时钟配置与实际编程后的时钟观察核实，不能自行豁免。其他关键项涉及 PCIe 相关时钟无公共节点、shell 时钟树 LUT 和 scoped clock constraints，也需要平台上下文审阅。

| 报告范围 | LUT | Registers | BRAM tile | DSP | URAM |
|---|---:|---:|---:|---:|---:|
| 完整设计 placement（包含 shell） | 227338 | 282814 | 302.5 | 52 | 0 |
| Vortex AFU 独立综合 | 88853 | 80147 | 66 | 48 | 0 |

这两行属于不同报告阶段和设计范围，不能相减后宣称最终核心面积。全部原始报告见 reports（本地记录 `results/u280-archive-20261109-v5/returned/reports`）。**D10 构建 PASS 保持有效；完整报告审阅发现的关键告警尚未关闭，板上就绪标为 BLOCKED，板上功能为 NOT_RUN。**

## 本地 runtime 准备

准备结果（本地记录 `results/u280-runtime-prepare-20261109-v1/result.json`） PASS、退出 0。固定 Linux 源码 3329 项 SHA-256 全部核对；选取 104 项原始源码，连同上游 configure 生成的头文件/Makefile、配置和构建器组成 116 项输入清单。

可迁移输入包（本地记录 `results/u280-runtime-prepare-20261109-v1/u280-runtime200-input.tar.gz`）为 467047 字节，SHA-256 `9976e187005d38005c1733d0bc5e9f337450109252bb908662fc9c4839c79b84`。这是源码与构建输入包，不是服务器可直接使用的二进制库。

新的 `u280-runtime200-binding-v1` 保持 draft/frozen=false；绑定文件（本地记录 `results/u280-runtime-prepare-20261109-v1/binding.json`）绑定 D8 U280 lock、D10 完整构建 result 与 xclbin 哈希。用固定上游 `gen_config.py` 从 D8 的实际 FPGA defines 重新生成全部 cflags，逐项比较确认唯一值差异是 `VX_CFG_PLATFORM_CLOCK_RATE: 400 → 200`。RV64 / 1c / 8w / 4t / 32 HBM banks / 33-bit platform address 等均保持一致。

该差异只修正宿主 runtime 的频率元数据：固定 `sw/runtime/common/device.cpp` 的 `VX_CAPS_CLOCK_RATE` 查询直接返回这个编译常量。没有改写 FPGA 输入、RTL、ABI、PTX 白名单、根 lock/caps 或原有候选，不能据此宣称板上读回时钟或性能通过。后续必须在服务器重新编译新宿主库，不能复用旧 400 MHz runtime。

Ubuntu 公共库编译（本地记录 `results/u280-runtime-prepare-20261109-v1/local-check/result.json`） PASS，四条实际命令均退出 0；G++ 11.4、glibc 2.35，两个 CPU / nice +10，编译 19.114 秒。`libvortex.so` 为 309880 字节、SHA-256 `bac645020e402ca5bcd609703fa51f041b76e7604a1fc720617612ec1db05854`，ldd 无缺失库。本项使用 `--stub-only`，只编译公共 runtime，不编译真实 XRT backend、不打开设备；该 Ubuntu 库不能移交为 CentOS 7 服务器可用库。

服务器 v5 实际命令确认默认 GCC 4.8.5、devtoolset-9 的 GCC **9.3.1**、glibc 2.17、XRT 2.13.479；固定 runtime 包含的六个 `experimental/xrt_*.h` 均存在并已记录哈希。历史 Python 为 3.6.8。真实 C++17/XRT 编译与链接仍 NOT_RUN，不能只凭版本和头文件存在宣称兼容通过。输入包预先保存固定生成器的解析结果，通过上游 Makefile 的 `XCONFIGS` 参数消费，避免在服务器 Python 3.6 上执行要求较新 Python 的 `gen_config.py`。构建器本身保持 Python 3.6 语法。

## 构建归档入口

`Invoke-U280Link.ps1` 新增 `-Mode Archive`，只接受已完成的 D10 BuildRun；核对远端构建 result 和 xclbin 的大小、SHA-256，提取 xclbin 元数据、完整 `_x/reports` 并返回 xclbin 本体。远端新建个人归档目录，保留原构建目录；不启动第二次 link，不打开板卡、不配置 HOST。元数据提取按 [XRT 官方 xclbinutil 用法](https://xilinx.github.io/XRT/2022.1/html/xclbintools.html)调用，具体 argv 和退出码进入新记录。

```powershell
& 'D:\Vortex-U280\scripts\Invoke-U280Link.ps1' -Mode Archive -BuildRun u280-link-20261109-103830-671
```

v1/v2/v3 均为本机网络失败，SSH 退出 255，尚未认证或执行远端归档；原件保留。v4 登录与 15 条检查命令成功，随后原始报告总量超过 192 MiB 传输上限，归档 FAIL；v5 使用报告无损压缩完成归档，设置独立的 2 GiB 解压总量上限，并拒绝路径越界、符号链接、重复成员、哈希错误及覆盖旧目录。

## 网络问题与恢复

与 15:56 成功记录相比，WLAN 接口 27、地址 `192.0.2.124`、Python 路径和代理 SHA-256 `6449dffee7c6e5398ccbf4a8809110fbbcf360391d8df16bfc0d27d458be11e9` 均相同。早期 `connect()` 报 WinError 10013；默认路由先超时，添加 IP 例外并重连后两条路径都被本机拒绝，系统 Python/原生 SSH 对照也未连通。

用户确认 Kill Switch / Invisible on LAN 均为关闭。普通 WFP 查询因管理员权限不足退出 1；经 UAC 的只读采集（本地记录 `results/u280-wfp-20261109-v1/result.json`）两条命令均退出 0。事件列表为空，不能伪造命中事件；实际过滤器中仍存在 Surfshark firewall 的 `Local network visibility` BLOCK：filterId 915610 / 915624，匹配 `10.0.0.0/8` 且远端端口不等于 53；同提供方也有新加的单 IP PERMIT 923568。Codex 的出站阻止规则限定另一个 SID，不能据其存在认定当前连接失败原因。

用户将 Invisible on LAN 开一次再关、重连 VPN 后，18:57:51 无密码复测（本地记录 `results/u280-network-20261109-v1/after_visibility_refresh.json`）默认路径 / WLAN 路径均取得 `SSH-2.0-OpenSSH_7.4`，分别 0.063 / 0.047 秒。这强烈支持之前的 Surfshark 局域网规则残留与故障相关，但未采集到逐连接命中事件。未手工删除 WFP/防火墙规则，未改系统路由；密码未记录。单 IP Bypasser 操作由用户在本机完成，操作依据为 [Surfshark 官方说明](https://support.surfshark.com/hc/en-us/articles/360017349293-How-to-use-Surfshark-Bypasser-on-Windows)。

## 验证与接收范围

最终 Python 自测 v2（本地记录 `results/ab-d11-script-checks-20261109-v2/result.json`）：实际 `python3 -B -m unittest discover -s tests -v`，104 项中 **103 通过 / 1 跳过**，退出 0，测试报告 84.586 秒。新增 10 项归档/频率绑定/路径及压缩报告验证测试；仍只证明脚本行为。此前 102 项 v1 记录保留。Windows 沙箱临时目录权限错误未被解释为硬件失败，沙箱外最终归档单测为 5 通过 / 1 跳过；Linux 已实际覆盖 symlink 检查。258/258 收尾核验（本地记录 `results/ab-d11-closeout-20261109-v1/result.json`）退出 0，包含全部返回文件/报告哈希、元数据、配置、测试和本地固定源码 3329 项零差异；上板就绪状态独立记录为 BLOCKED。

本轮没有重跑处理器 RTL、NOXRT AFU 或 PTX kernel；服务器 runtime、HOST 配置、实际板上程序与 E 独立接收仍 NOT_RUN。下一步在服务器用现有 GCC 9.3.1 隔离编译 runtime；继续审阅 9 项 methodology 关键告警、200 MHz 动态时钟配置以及缺 delay 的平台端口，核对 HOST 权限与当次空闲卡，再安排原生上板。无需重新 link 或再次下载已经归档的 xclbin。
