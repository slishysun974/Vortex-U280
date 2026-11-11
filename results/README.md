# 当前公开验证入口：2026-11-11

| 内容 | 入口 |
|---|---|
| 最新独立 E 四路接收 | [签发结果](e-runtime-unseen-acceptance-20261111-v1/result.json) |
| U280 新语料执行 | [执行与命令](e-u280-unseen-20261111-v1/result.json)、[原始输出目录](e-u280-unseen-20261111-v1/returned/execution/e-unseen/) |
| 三路模型新语料 | [输入输出与 capture](e-runtime-unseen-sim-20261111-v1/) |
| 超时与故障限制 | [模型恢复实验](c-runtime-recovery-20261111-v1/summary.json) |
| C runtime 集成 | [本地结果](c-runtime-merge-20261111-v3/summary.json)、[板测结果](c-u280-runtime-20261111-v3/result.json) |
| 本次公开副本验证 | [自测及离线重核](publication-check-20261111-v1/summary.json) |

公开副本自测 237 通过/32 跳过，四路历史输出各 48/48 离线复核。此验证不增加物理板测次数。冻结输入/答案与六个生产文件共 248 项保持原件字节。含账号或地址的文本做发布脱敏，原历史哈希字段不修改；逐文件来源与公开哈希见 [manifest](../publication/manifest.json)，具体规则见 [发布说明](../docs/PUBLICATION.md)。下方保留上次公开记录索引。

# 公开验证记录

本目录按原 run_id 收录选定的命令、退出码、摘要和日志。含本地路径或账号的记录以公开副本单列，示例值不参与原实验的哈希校验。完整日志、参考输入输出、工具包、运行库、XCLBIN、DCP、WSL 磁盘和课程原件在原工作区归档。公开快照用于阅读进度和协作，部分历史复核脚本需要完整本地证据树。

## 原样收录

- [ab-d1-source-20261107-v2/native_smoke.json](ab-d1-source-20261107-v2/native_smoke.json)
- [ab-d1-source-20261107-v2/result.json](ab-d1-source-20261107-v2/result.json)
- [ab-d1-source-20261107-v2/source_manifest.json](ab-d1-source-20261107-v2/source_manifest.json)
- [ab-d1-source-20261107-v2/target_caps.json](ab-d1-source-20261107-v2/target_caps.json)
- [ab-d1-source-20261107-v2/target_lock.json](ab-d1-source-20261107-v2/target_lock.json)
- [ab-d1-source-20261107-v2/target_lock.sha256](ab-d1-source-20261107-v2/target_lock.sha256)
- [ab-d1-source-20261107-v2/resolved_config.cflags](ab-d1-source-20261107-v2/resolved_config.cflags)
- [ab-d2-simx-20261108-v2/summary.json](ab-d2-simx-20261108-v2/summary.json)
- [ab-d3-simx-20261108-v1/summary.json](ab-d3-simx-20261108-v1/summary.json)
- [ab-d3-rtlsim-20261108-v2/summary.json](ab-d3-rtlsim-20261108-v2/summary.json)
- [ab-d3-xrtsim-20261108-v1/summary.json](ab-d3-xrtsim-20261108-v1/summary.json)
- [ab-d4-closeout-20261108-v1/result.json](ab-d4-closeout-20261108-v1/result.json)
- [ab-d5-block32-20261108-v1/summary.json](ab-d5-block32-20261108-v1/summary.json)
- [ab-d5-block32-20261108-v1/logs/01_runner_tests.log](ab-d5-block32-20261108-v1/logs/01_runner_tests.log)
- [ab-d5-closeout-20261108-v1/result.json](ab-d5-closeout-20261108-v1/result.json)
- [ab-d6-closeout-20261108-v1/result.json](ab-d6-closeout-20261108-v1/result.json)
- [ab-d7-closeout-20261109-v1/result.json](ab-d7-closeout-20261109-v1/result.json)
- [ab-d8-closeout-20261109-v1/result.json](ab-d8-closeout-20261109-v1/result.json)
- [ab-d10-link-closeout-20261109-v1/result.json](ab-d10-link-closeout-20261109-v1/result.json)
- [ptx-frontend-host-20261108-v3/summary.json](ptx-frontend-host-20261108-v3/summary.json)
- [ptx-frontend-host-20261108-v3/logs/01_python_tests.log](ptx-frontend-host-20261108-v3/logs/01_python_tests.log)
- [ptx-frontend-host-20261108-v3/logs/02_host_compiler.log](ptx-frontend-host-20261108-v3/logs/02_host_compiler.log)
- [ptx-frontend-host-20261108-v3/logs/03_copy_u32_frontend.log](ptx-frontend-host-20261108-v3/logs/03_copy_u32_frontend.log)
- [ptx-frontend-host-20261108-v3/logs/04_copy_u32_host_compile.log](ptx-frontend-host-20261108-v3/logs/04_copy_u32_host_compile.log)
- [ptx-frontend-host-20261108-v3/logs/05_copy_u32_host_run.log](ptx-frontend-host-20261108-v3/logs/05_copy_u32_host_run.log)
- [ptx-frontend-host-20261108-v3/logs/06_vadd_u32_frontend.log](ptx-frontend-host-20261108-v3/logs/06_vadd_u32_frontend.log)
- [ptx-frontend-host-20261108-v3/logs/07_vadd_u32_host_compile.log](ptx-frontend-host-20261108-v3/logs/07_vadd_u32_host_compile.log)
- [ptx-frontend-host-20261108-v3/logs/08_vadd_u32_host_run.log](ptx-frontend-host-20261108-v3/logs/08_vadd_u32_host_run.log)
- [ptx-frontend-host-20261108-v3/logs/09_affine_u32_frontend.log](ptx-frontend-host-20261108-v3/logs/09_affine_u32_frontend.log)
- [ptx-frontend-host-20261108-v3/logs/10_affine_u32_host_compile.log](ptx-frontend-host-20261108-v3/logs/10_affine_u32_host_compile.log)
- [ptx-frontend-host-20261108-v3/logs/11_affine_u32_host_run.log](ptx-frontend-host-20261108-v3/logs/11_affine_u32_host_run.log)
- [ptx-frontend-host-20261108-v3/logs/12_semantics_probe_frontend.log](ptx-frontend-host-20261108-v3/logs/12_semantics_probe_frontend.log)
- [ptx-frontend-host-20261108-v3/logs/13_semantics_probe_host_compile.log](ptx-frontend-host-20261108-v3/logs/13_semantics_probe_host_compile.log)
- [ptx-frontend-host-20261108-v3/logs/14_semantics_probe_host_run.log](ptx-frontend-host-20261108-v3/logs/14_semantics_probe_host_run.log)
- [ptx-frontend-host-20261108-v3/logs/15_fault_eager_load_compile.log](ptx-frontend-host-20261108-v3/logs/15_fault_eager_load_compile.log)
- [ptx-frontend-host-20261108-v3/logs/16_fault_eager_load_run.log](ptx-frontend-host-20261108-v3/logs/16_fault_eager_load_run.log)
- [u280-link-20261109-155638-456/returned/build/clock_check.stdout](u280-link-20261109-155638-456/returned/build/clock_check.stdout)
- [u280-runtime-20261109-v4/returned/runtime/ldd_libvortex-xrt.stdout](u280-runtime-20261109-v4/returned/runtime/ldd_libvortex-xrt.stdout)
- [u280-runtime-20261109-v4/returned/runtime/ldd_libvortex.stdout](u280-runtime-20261109-v4/returned/runtime/ldd_libvortex.stdout)
- [u280-runtime-20261109-v4/returned/runtime/compiler.stdout](u280-runtime-20261109-v4/returned/runtime/compiler.stdout)
- [u280-runtime-20261109-v4/returned/runtime/glibc.stdout](u280-runtime-20261109-v4/returned/runtime/glibc.stdout)
- [u280-timing-review-20261109-v2/result.json](u280-timing-review-20261109-v2/result.json)
- [u280-board-input-20261109-v1/result.json](u280-board-input-20261109-v1/result.json)
- [ab-d13-input-checks-20261109-v1/result.json](ab-d13-input-checks-20261109-v1/result.json)
- [ab-d13-script-checks-20261109-v2/result.json](ab-d13-script-checks-20261109-v2/result.json)
- [ab-d13-script-checks-20261109-v2/tests.log](ab-d13-script-checks-20261109-v2/tests.log)
- [ab-d13-source-checks-20261109-v1/result.json](ab-d13-source-checks-20261109-v1/result.json)

## 脱敏副本

- [ab-d1-source-20261107-v2/commands.json](ab-d1-source-20261107-v2/commands.json)
- [ab-d9-closeout-20261109-v1/result.json](ab-d9-closeout-20261109-v1/result.json)
- [ptx-frontend-closeout-20261108-v1/result.json](ptx-frontend-closeout-20261108-v1/result.json)
- [u280-preflight-20261109-100406-629/returned/build/result.json](u280-preflight-20261109-100406-629/returned/build/result.json)
- [u280-link-20261109-155638-456/returned/build/result.json](u280-link-20261109-155638-456/returned/build/result.json)
- [u280-archive-20261109-v5/returned/build/result.json](u280-archive-20261109-v5/returned/build/result.json)
- [u280-runtime-20261109-v4/returned/runtime/result.json](u280-runtime-20261109-v4/returned/runtime/result.json)
- [u280-readiness-review-20261109-v2/result.json](u280-readiness-review-20261109-v2/result.json)
