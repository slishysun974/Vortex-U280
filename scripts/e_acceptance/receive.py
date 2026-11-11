"""One reproducible final receipt for the fixed PTX15 independent E scope."""
import argparse
import datetime
import json
from pathlib import Path
import shutil
import sys

import accept
import board
import fault_injection


def write_json(path,data):
    path.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n',encoding='utf-8')


def receive(args):
    out=args.output
    out.mkdir(parents=True,exist_ok=False)
    (out/'receiver_source').mkdir()
    for p in Path(__file__).parent.glob('*.py'):
        shutil.copyfile(p,out/'receiver_source'/p.name)
    started=datetime.datetime.now(datetime.timezone.utc).isoformat()
    result=dict(schema='e-independent-ptx15-acceptance-v1',status='FAIL',
        command=[sys.executable,'-B',str(Path(__file__)),*sys.argv[1:]],started_utc=started,
        acceptance_type='Non-author AI agent E independent acceptance; not a human E signature',
        frozen_manifest_sha256=accept.FREEZE_SHA,oracle_sha256=accept.ORACLE_SHA,
        receiver_sha256={p.name:accept.sha(p) for p in (out/'receiver_source').glob('*.py')},
        scope={'copy_u32':['0010','0058','0070','0082','0094','0106'],
               'vadd_u32':['0010','0058','0070','0106'],
               'affine_u32':['0034','0176','0210','0250','0322']},block=32,
        timing_7={'this_round':'SKIPPED_BY_USER','technical_state':'OPEN'},
        excluded={'unseen_legal_corpus':'NOT_RUN','full_P0':'NOT_RUN',
                  'generic_project_runtime':'NOT_RUN','same_context_repeated_launch_and_recovery':'NOT_RUN',
                  'performance_and_configuration_study':'NOT_RUN','AI_controlled_study':'NOT_RUN',
                  'human_E_signature':'NOT_RUN'},
        limitations=['Device runtimes and FPGA bitstream were reused after identity checks, not rebuilt.',
                     'Per-lane no-array-access proof is from SimX and processor RTL; AFU/U280 scope is execution, raw outputs, ABI and observed gates.',
                     'Remote host binary hashes were measured post-run; returned source/image/log bytes match the execution package and returned logs.',
                     'Negative cases challenge the receiver. They do not establish DUT generic invalid-argument APIs or recovery support.',
                     'Board holder checks cover KDS and processes visible to an ordinary account, without exclusive reservation.'])
    try:
        local=accept.check_local(args.local_run)
        write_json(out/'local.json',local)
        physical=board.check_board(args.board_run,out/'board_raw',args.local_run)
        write_json(out/'u280.json',physical)
        post=board.check_post_artifacts(args.board_artifacts,args.board_run,out/'board_raw',out/'post_run_artifacts')
        write_json(out/'post_run_artifacts.json',post)
        faults=fault_injection.inject(args.local_run,args.board_run,out/'fault_injection')
        accept.require(faults['status']=='PASS','receiver fault injection failed')
        unit=accept.ROOT/'results/e-ptx-root-unittest-20261110-v1'
        accept.require((unit/'exit_code.txt').read_text().strip()=='0','full runner unittest exit missing')
        test_log=(unit/'unittest.log').read_text()
        accept.require('Ran 140 tests' in test_log and 'OK (skipped=1)' in test_log,'full runner unittest scope differs')
        result.update(status='PASS',verdict='ACCEPTED_WITH_FIXED_SCOPE',
            backends={b:dict(status='PASS',cases=15) for b in ('simx','processor_rtl','noxrt_afu','u280')},
            total_new_executions=60,complete_arrays_compared=156,payloads_checked=60,
            image_reconstruction={'status':'PASS','count':3,'identical_to_delivery':True},
            trace={b:{'status':'PASS','cases':15,'array_reads':903,'array_writes':580,
                      'n_zero_cases':3,'false_predicate_array_requests':0} for b in ('simx','processor_rtl')},
            receiver_fault_injection={'status':'PASS','positive_controls':faults['positive_controls'],'negative_cases':faults['negative_cases']},
            runner_unittest={'status':'PASS','passed':139,'skipped':1,'exit_code':0,
                             'log':str(unit/'unittest.log'),'log_sha256':accept.sha(unit/'unittest.log'),
                             'scope':'Python runner/receiver self-tests; not hardware proof'},
            provenance={'local_run':str(args.local_run),'board_run':str(args.board_run),
                        'post_run_artifacts':str(args.board_artifacts),
                        'local_execution_sha256':accept.sha(args.local_run/'execution.json'),
                        'board_result_sha256':accept.sha(args.board_run/'result.json'),
                        'post_artifact_result_sha256':accept.sha(args.board_artifacts/'result.json')},
            contracts={str(p.relative_to(accept.ROOT)):accept.sha(p) for p in [
                accept.ROOT/'configs/target_lock.json',accept.ROOT/'configs/candidates/block32-v1/target_lock.json',
                accept.ROOT/'configs/candidates/u280-hbm32-v1/target_lock.json']},
            human_signoff='No additional human signoff is needed to report this AI E receipt. Formal human E acceptance, if required by the team, remains unsigned and is not implied.')
    except Exception as error:
        result['error']=repr(error)
    result['finished_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    result['exit_code']=0 if result['status']=='PASS' else 1
    write_json(out/'result.json',result)
    (out/'exit_code.txt').write_text(str(result['exit_code'])+'\n')
    if result['status']=='PASS':
        report='''# 固定 15 条 PTX：非作者 AI 代理 E 独立接收

结论：**限定范围接收 PASS**。SimX、处理器 RTL、NOXRT AFU、U280 各 15/15，共 60 次新执行；3 份隔离重建的 vxbin 与交付镜像逐字节一致。156 份完整数组和 60 份参数按独立答案通过，包含输入保持、首尾哨兵、u32 模运算和自然对齐小端 ABI。本轮不代表完整 P0 或正式人类 E 签名。

## 独立性与冻结

E 使用独立上下文，从三份 PTX、原始 inputs、选定 case 元数据和契约编写标准库数学 oracle。冻结前未读 expected/actual、输出比较或生产 oracle/packer。状态文档只用于识别交付和范围，作者的 PASS 不构成判据。

- 冻结清单：`configs/acceptance/e-ptx15-v1/manifest.json`，SHA-256 `f205a527c8bb6801ed7e2d416ea4a56236109e67c4b2323f851c4690d327e7d7`。
- oracle SHA-256：`da2df04b2f38e3adda0a9839aefec6ebdf549ddc3a2fe4f378fc369bcc016507`。
- 冻结命令：`python -B scripts/e_acceptance/oracle_v1.py --root . --freeze configs/acceptance/e-ptx15-v1`，退出 0；日志 `results/e-ptx-freeze-20261110-v1/generate.log`。
- 当前源码、根 draft lock、block32 候选 lock、U280 候选 lock 分别绑定，不将根 4 Warp 基线改写为已冻结 8 Warp 平台。

## 固定接收范围

| PTX | B32 用例 |
|---|---|
| copy_u32 | 0010 / 0058 / 0070 / 0082 / 0094 / 0106 |
| vadd_u32 | 0010 / 0058 / 0070 / 0106 |
| affine_u32 | 0034 / 0176 / 0210 / 0250 / 0322 |

| 层级 | 实际新执行 | 独立接收 |
|---|---:|---|
| SimX DEBUG3 | 15，退出 0 | 完整输出、ABI、逐 lane 访存 PASS |
| 处理器 RTL DEBUG3 | 15，退出 0 | 完整输出、ABI、逐 lane 访存 PASS |
| NOXRT AFU | 15，退出 0 | 完整输出、ABI PASS；本轮无逐 lane trace |
| U280 b1 | 15，宿主编译/执行与 SSH 退出 0 | 完整输出、ABI、当次门禁 PASS；板上无逐 lane trace |

两种 DEBUG3 后端分别检查 903 次数组读和 580 次写，逐 Block/逻辑线程/指令 PC/地址/次数核对。每层三条 N=0 用例均实际分派 8 Warp、32 线程并读取 N 参数，数组请求为零；尾部假谓词未发数组请求。参数纯读取允许合法下沉，未把“无用指针字节也必须读”当作 PTX 语义。

U280 新运行 `u280-board-ptx-regression-e-20261110-v2` 的每条记录均检查 BDF 与 XRT index、shell、HOST 256 MiB、已加载 UUID、XRT DATA_CLK 200 MHz、驱动时钟及执行后 KDS 空闲。原始 SSH JSON 与 result.json 一致。门禁宿主和执行脚本身份固定，复制的输入/镜像与独立复现一致。copy 板包头文件增加了未被相同 main.cpp 使用的 entry/buffers/scalars 声明；只允许这些精确新增项，原 ABI/launch 常量逐项不变。

后补采集保留 15 组共 135 份原件，含 smoke ELF、源文件、vxbin、flags、stdout/stderr，逐字节与执行输入及返回日志核对。宿主二进制哈希属于 **post-run** 观测，mtime 位于原运行区间；不倒填为执行当时已测哈希。逐文件哈希见 `post_run_artifacts.json`。

## 正负验收与失败记录

独立接收器实际运行 2 个正控制、23 个负例，均符合预期。错误包括数据、输入、首尾哨兵、参数指针/N/padding、缺失/多余/截断输出、非零退出、缺失完成、错误 launch、部分/重复执行、首次 dispatch 前请求、假谓词请求、漏/重复数组请求、错误板时钟和退出后忙碌。即使同时改 raw 字节、producer actual/expected SHA 和原 SSH JSON，仍因独立冻结答案拒绝。负例只证明接收器能拒绝错误证据，不代替 DUT 通用非法参数 API 或恢复测试。

开发期检查器失败与 DUT 失败分开保留：`e-ptx-local-review-20261110-v1` 的 RTL 解析遗漏 init=0 复用 Warp，后改为覆盖两种 dispatch；SimX mask 低位先打印、RTL 高位先打印均依据固定源码处理。首次参数读取检查过严，修正依据为编译器可下沉纯读取，不改冻结 oracle。`e-ptx-board-review-20261110-v1` 因 copy 头文件的额外未使用声明而拒绝，随后逐行核实并收紧为精确许可。所有 DUT 新执行均退出 0，原始证据未改。

U280 E v1 的认证断连记录留存，板上未执行；v2 是本次板上证据。后补采集 v1 的本地换行/hash 门禁失败保留，v2 才完成。Windows 定向单测 v1 为 Temp 权限错误；WSL 定向 v2 六项 OK，但外层 exit 记录错误，保留失败退出。根完整 WSL 自测最终退出 0，140 项中 139 通过、1 跳过，详见 `results/e-ptx-root-unittest-20261110-v1/`。这些是运行器行为检查，不能代替上述设备执行。

总接收 v1 在后补日志逐字节绑定时拒绝：E 在 Windows 提取 stdout/stderr 时 write_text 将 LF 转为 CRLF。改为直接写 UTF-8 原字节后，使用全新 v2 重验；原 v1 失败和源快照保留，设备原始字节未改。

## 复现与边界

本地执行入口：`wsl -d Vortex-AB-Ubuntu-22.04 --cd /mnt/d/Vortex-U280 -- python3 -B scripts/e_acceptance/reproduce.py --run-id <新的e-ptx-run-id>`。执行清单逐命令保存 argv、cwd、stdout/stderr、退出码、耗时、source/binary/runtime 哈希；runtime 使用身份核实后的 D6/D5 原库，没有重新编译仿真器或 FPGA bitstream。

总接收入口为 `scripts/e_acceptance/receive.py --local-run ... --board-run ... --board-artifacts ... --output <全新结果目录>`；确切本次命令与退出码在 `result.json` 和 `exit_code.txt`。接收源码快照位于 `receiver_source/`，每次必须使用全新输出目录，禁止覆盖失败记录。

未见合法语料、完整 P0、通用项目 runtime、同一 context 连续启动/恢复、性能与配置研究、AI 对照实验、人类 E 签名均为 NOT_RUN。物理板门禁覆盖当次可观察状态，普通账号持有者检查不等于独占预留。**TIMING-7 本轮 SKIPPED_BY_USER，既有技术状态仍 OPEN**，未调查或关闭。

本结论可称“非作者 AI 代理 E 独立接收这 15 条用例”。无需额外人类签字才能报告该技术事实；如果团队需要正式人类 E 接收签名，仍待该成员签核，不能从本报告推定。下一步由主责人更新状态和交接，仅将这 15 条标为限定接收；后续未见语料和通用 runtime 另立任务。
'''
        (out/'acceptance.md').write_text(report,encoding='utf-8')
    print(json.dumps({'status':result['status'],'exit_code':result['exit_code'],'output':str(out),
                      'error':result.get('error'),'result_sha256':accept.sha(out/'result.json')}))
    return result['exit_code']


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--local-run',type=Path,required=True)
    parser.add_argument('--board-run',type=Path,required=True)
    parser.add_argument('--board-artifacts',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    raise SystemExit(receive(parser.parse_args()))
