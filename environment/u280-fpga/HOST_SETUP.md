# U280 HOST 内存配置交接

2026-11-09：用户已授权配置 HOST，但服务器账号 `u280user` 无 sudo 权限。实际 `sudo -v` 退出 1；用户看到 `Sorry, user u280user may not run sudo on localhost.`。见 v1 原始采集（本地记录 `results/u280-readiness-20261109-v1/probe.json`）。没有执行 HOST enable、加载 xclbin 或启动 kernel。

需要管理员在 `192.0.2.28` 为一张当次空闲的 U280 启用 256 MiB HOST。以下以 `0000:b1:00.1` / `/dev/dri/renderD132` 为候选；它在 v1 时 ready、无 KDS 任务、HOST 为 0，但该观察不构成预留。管理员执行前必须重新核对 BDF 与 render 节点、ready、shell、KDS 和所有用户的文件占用。

可转交的申请文字：

> 我在服务器 192.0.2.28 上进行 Vortex-U280 原生程序验证。当前账号 u280user 无 sudo 权限，runtime 需要 HOST[0] 存放命令队列与数据暂存区。请管理员为一张当次空闲、使用 xilinx_u280_gen3x16_xdma_1_202211_1 平台的 U280 配置 256 MiB HOST 内存，并提供该卡的 BDF、配置退出码及 pcie-info JSON 读回结果。管理员代为配置即可，不需要授予我通用 sudo 权限。这个容量无需配置 hugepages 或重启服务器。

```bash
# 由有权限的管理员在服务器上执行。先检查，不要直接跳到 configure。
readlink -f /sys/bus/pci/devices/0000:b1:00.1/driver
ls /sys/bus/pci/devices/0000:b1:00.1/drm/
cat /sys/bus/pci/devices/0000:b1:00.1/ready
cat /sys/bus/pci/devices/0000:b1:00.1/interface_uuids
cat /sys/bus/pci/devices/0000:b1:00.1/kdsstat
cat /sys/bus/pci/devices/0000:b1:00.1/host_mem_size
sudo fuser -v /dev/dri/renderD132
```

要求 driver 为 xocl、ready 为 `0x1`、interface UUID 为 `fb2b2c5a19ed63593fea95f51fbc8eb9`，outstanding execs/contexts 均为 0、client pid 为空，root fuser 没有持有者且没有权限/路径错误。若已配置非零 HOST，先保留现有配置并报告容量；若有使用者则改期或按资源管理规则选另一张卡。满足条件后立即配置并读回：

```bash
sudo /opt/xilinx/xrt/bin/xbutil configure --device 0000:b1:00.1 --host-mem enable --size 256M
echo "configure_exit=$?"
cat /sys/bus/pci/devices/0000:b1:00.1/host_mem_size
source /opt/xilinx/xrt/setup.sh
# 请用新的输出文件名，保留已有报告。
xbutil examine --device 0000:b1:00.1 --report platform memory pcie-info dynamic-regions --format JSON --output host-after-NEW.json
echo "examine_exit=$?"
```

交回实际 BDF、时间、两条退出码和 JSON 报告；配置退出 0 仍需由 `shared_host_mem_size_bytes` 确认已预留 256 MiB。`max_shared_host_mem_aperture_bytes` 要在加载支持 HOST 的 xclbin 后才可能更新，`enabled_host_mem_size_bytes` 要在应用实际使用 HOST 后才更新；这两个字段在本阶段为 0 不应直接判配置失败。保留 sysfs 原始值，不猜测其单位。配置后暂停设备加载，等待本项目时序审阅完成，并在后续上板前重新检查占用。

本操作只申请一张卡的 256 MiB HOST，不改变 sudoers、不配置 hugepages、不 reset/flash 卡。[XRT 2022.1 HOST 文档](https://xilinx.github.io/XRT/2022.1/html/hm.html)说明 HOST 应在 xclbin 装载前配置，1 GiB 及以下无需配置 hugepages。`HOST[0]` 出现在平台资源表中不代表 HOST 内存已经启用。

如管理员提供按命令授予的权限，需另核实该策略允许配置与必要的占用检查；当前没有获得此类授权的证据。不要重复尝试已被拒绝的 `sudo -v`。
