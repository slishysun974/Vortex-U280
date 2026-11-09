# U280 预处理输入与分阶段构建

2026-11-09 D10：**完整 FPGA link、xclbin 生成和固定 200 MHz 检查均 PASS**，15:48:08 完成，v++/clock_check 退出 0，见 [最终构建记录](../../results/u280-link-20261109-155638-456/returned/build/result.json)与 [D10](../../docs/AB_D10_PROGRESS.md)。成功产物 53,950,442 字节保存在远端构建目录；后续审阅完整资源/时序/元数据并准备 HOST/runtime/上板条件。以下 D8/D9 描述保留其历史范围；资源方案在 D10 已获用户授权且执行完毕，板上功能仍未验证。

2026-11-09 D9：HOST/platform 复查、XSA↔shell interface UUID 核对与**真实 XO 打包均已通过**，见 [D9](../../docs/AB_D9_PROGRESS.md)。首次缺 `xil_fma` stub 的失败保留；独立 [ip-ooc-v1 补丁](PATCHES.md) 显式 U280 part、五个 IP OOC DCP/stub、elaboration 和原 error gate 的实际运行退出 0、340.708 秒。补丁仅修改新目录 `flow/` Tcl，D8 输入包及固定源未改。成功流程必须显式传 `--build-flow ip-ooc-v1`，后续 link 同样传此参数；具体输入/XO 路径及资源确认方案见 [下一阶段准备单](NEXT_LINK.md)。源码包与 XO 复用绑定完整输入清单和构建流程版本。

2026-11-09。当前已完成 Linux 固定 Verilator 的源预处理、接口核对和可迁移输入包；Vivado elaboration、XO、完整综合/实现、xclbin、HOST 配置与板上运行均未在 D8 执行。

输入包为 `results/ab-d8-u280-source-20261109-v1/u280-rtl-input.tar.gz`，SHA-256 为 `6759015dd48471589c3c98ce833d8d225fd1d3e1580e970223b7d703b686d44e`。包含 288 项输入文件及 `manifest.json`：预处理 RTL、相对路径 sources.txt、固定上游 Tcl/检查脚本、候选配置/lock。不要在服务器混用 WSL 的 glibc 2.35 工具二进制；本包把预处理留在已验证 WSL，服务器使用已安装的 Vivado/Vitis 2023.1。远端 C++ runtime 的编译器/运行库兼容性仍需另行解决，服务器原盘点 G++ 为 4.8.5。

另有运行时频率元数据待办：本次解析保留上游 `VX_CFG_PLATFORM_CLOCK_RATE=400`，固定 `sw/runtime/common/device.cpp` 的 `VX_CAPS_CLOCK_RATE` 直接返回该编译值；它不能表示拟议的 200 MHz 或将来实测频率。接入板上 runtime 前，按已验证 xclbin 时钟版本化更新候选和两端构建，并重编 runtime；当前输入包不交付可用于性能报告的 runtime。

先在新的个人目录验证归档 SHA-256，再解包。将本目录 `build_prepared.py` 同时复制过去。它默认只核验输入，输出独占创建于当前账号的 `~/vortex-u280-builds/<run_id>`。每个阶段换新 run_id，失败原件不覆盖。

```bash
python3 -B build_prepared.py --input /absolute/path/u280-rtl-input --run-id NEW-inspect
python3 -B build_prepared.py --input /absolute/path/u280-rtl-input --run-id NEW-xo --stage xo
```

XO 阶段在独立副本中运行固定 `gen_xo.tcl`：生成 vendor IP、保持模块接口检查为 error、执行 RTL elaboration、再 package_xo。限制为两个 CPU、nice +10、Vivado maxThreads=2、900 秒超时。它可能失败于旧工具兼容性、vendor IP 或接口 DRC，均应保存真实日志；不能关闭 gate 来获得通过。该阶段还未在服务器运行，15 分钟只是限制，不是耗时估计。

完整构建须先按用户既有要求确认共享服务器资源/作业规则。待确认的具体方案：两个 CPU、两项综合/实现并发 run、实现 maxThreads=2、nice +10、6 小时硬超时；建议预算 64 GiB RAM、50 GiB 个人盘余量，但这是规划值，尚无整机测量。脚本**未硬限制 RAM**，应在资源确认时决定是否使用管理员提供的调度/cgroup 配额，不能只凭限制线程宣称内存受限。

```bash
python3 -B build_prepared.py --input /absolute/path/u280-rtl-input \
  --run-id NEW-link --stage link --xo-run /absolute/path/NEW-xo
```

link 阶段检查前次 XO 的状态、候选 lock 和产物哈希，使用固定 HBM/HOST 连接及 200 MHz 目标，保留全部 v++ 中间结果，之后运行固定 `xilinx_check_kernel_clock.py --no-scaling`。只有 v++、时钟检查均退出 0 且 xclbin 存在才报告该阶段 PASS。仍需单独审阅完整利用率/时序、platform interface UUID、xclbin 元数据与上板前置条件；脚本不加载卡。

HOST 只读核对入口（在 Windows 项目根目录）：

```powershell
.\scripts\Invoke-U280Preflight.ps1 -ProbeKind host-platform
```

密码只在本机 SSH 提示处输入。该模式执行 XRT help/设备报告、`sudo -n -l` 命令权限查询及已安装 XPFM/XSA 元数据读取。它不执行 sudo 配置命令。`sudo -n -l` 非零可能是需要密码或策略拒绝，不能直接判定当前账号没有 sudo 权限。

已核对 [XRT 2022.1 xbutil](https://xilinx.github.io/XRT/2022.1/html/xbutil.html) 与 [Host Memory Access](https://xilinx.github.io/XRT/2022.1/html/hm.html)：启用需 sudo，应在 xclbin 加载前执行。待实际 help/权限复核、选择当前空闲卡并确认配置授权后，可从 256M 开始；以下是准备命令，D8 未执行：

```bash
sudo /opt/xilinx/xrt/bin/xbutil configure --device 0000:b1:00.1 --host-mem enable --size 256M
/opt/xilinx/xrt/bin/xbutil examine --device 0000:b1:00.1 --report pcie-info memory
```

`b1` 是 D7 候选，不是设备预留。配置前后记录 host_mem_size、KDS、可见持有者、BDF/index、shell/interface UUID。若此前为 0、本次成功启用且确认没有其他使用者，结束后可用 `sudo ... configure --device <BDF> --host-mem disable` 恢复；如果此前已有配置，不禁用他人的内存。禁用前释放本项目 BO/进程且复查空闲，不使用 reset/刷 shell 作为默认恢复。

官方文档区分 Shared、Max Shared、Enabled Host Memory：后两项分别可能在加载带 HOST 的 xclbin、实际使用 host-only BO 后才出现，零值不能单独说明硬件不支持。现有 2 MiB hugepages 空闲数量不证明 256M 分配一定成功；先保存实际错误，不能擅自修改 grub、重启或调整整机 hugepages。
