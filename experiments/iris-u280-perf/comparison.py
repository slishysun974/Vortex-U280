"""Offline comparison of frozen Iris measurements, CPU timings and board telemetry."""
import argparse
import json
from pathlib import Path

from analyze import analyze, check, distribution, lines, read, sha
from cpu import verify_samples


def compare(corpus, raw, cpu):
    gpu = analyze(corpus,raw)
    cpu_summary = read(cpu/"summary.json")
    cpu_times, logical = verify_samples(corpus,cpu/"samples.csv")
    check(cpu_summary["status"]=="PASS" and cpu_summary["exit_code"]==0 and cpu_times==cpu_summary["groups_ns"]
          and logical==cpu_summary["logical_cpu"] and cpu_summary["samples_sha256"]==sha(cpu/"samples.csv")
          and cpu_summary["corpus_sha256"]==sha(corpus/"freeze.json"),"CPU receipt differs")
    setup = read(raw/"capture.json")
    check(setup["backend"]=="u280-xrt" and setup["final_state"]=="CLOSED","physical capture incomplete")
    groups = {}
    for n, stats in gpu["groups"].items():
        cycles = stats["cycles"]["median"]
        device_ns = cycles*5
        total_ns = stats["total_ns"]["median"]
        cpu_ns = cpu_times[n]["median"]
        groups[n] = dict(board=stats, cpu_ns=cpu_times[n], device_busy_ns=device_ns,
            device_rows_per_s=int(n)*1e9/device_ns, board_pipeline_rows_per_s=int(n)*1e9/total_ns,
            cpu_rows_per_s=int(n)*1e9/cpu_ns, device_to_cpu_time_ratio=device_ns/cpu_ns,
            board_pipeline_to_cpu_time_ratio=total_ns/cpu_ns)
    mapping = read(raw/"sensor-map.json")
    readings = lines(raw/"sensors.jsonl")
    sensors = {}
    for key,desc in mapping.items():
        if desc["label"] not in ("FPGA TEMP","HBM TEMP","POWER") or not key.endswith("_input"):
            continue
        scale = 1e6 if desc["unit"]=="uW" else 1e3
        values = [r["values"][key]/scale for r in readings if r["values"].get(key) is not None]
        if values:
            sensors[key] = dict(label=desc["label"],unit="W" if scale==1e6 else "C",count=len(values),**distribution(values))
    endpoints = {}
    for phase in ("before","after"):
        record = read(raw/("sensors-"+phase+".json"))["devices"][0]
        endpoints[phase] = dict(bdf=record["device_id"],power_W=float(record["electrical"]["power_consumption_watts"]),
            warning=record["electrical"]["power_consumption_warning"],
            temperatures_C={s["location_id"]:float(s["temp_C"]) for s in record["thermals"] if s["is_present"]=="true"})
    return dict(status="PASS",groups=groups,folds=dict(correct=gpu["accuracy_correct"],total=gpu["accuracy_total"],
        confusion=gpu["confusion"],per_fold=gpu["fold_correct"],errors=gpu["errors"]),
        telemetry=dict(samples=len(readings),span_s=readings[-1]["monotonic_s"]-readings[0]["monotonic_s"],
                       channels=sensors,xbutil=endpoints),counter_reads=gpu["counter_reads"],
        cpu=dict(model=cpu_summary["cpu_model"],compiler=cpu_summary["compiler"],threads=1,logical_cpu=logical),
        capture_hash=sha(raw/"samples.jsonl"),mpm_hash=sha(raw/"counter-reads.jsonl"),cpu_hash=sha(cpu/"samples.csv"))


def plot(report,out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter
    sizes = sorted(map(int,report["groups"]))
    groups = [report["groups"][str(n)] for n in sizes]
    fig, (lat,rate) = plt.subplots(1,2,figsize=(10.4,4.0),layout="constrained")
    x = range(len(sizes))
    for name,ys,color,marker in (
            ("U280 host pipeline",[g["board"]["total_ns"]["median"]/1e6 for g in groups],"#B14E28","o"),
            ("Vortex device busy",[g["device_busy_ns"]/1e6 for g in groups],"#195D89","s"),
            ("Intel CPU, 1 thread",[g["cpu_ns"]["median"]/1e6 for g in groups],"#257455","^")):
        lat.plot(x,ys,label=name,color=color,marker=marker)
    lat.set(yscale="log",title="Batch latency",ylabel="Median latency (ms, log scale)")
    lat.yaxis.set_major_formatter(FuncFormatter(lambda v,_:f"{v:g}"))
    for key,name,color,marker in (("device_rows_per_s","Device busy","#195D89","s"),
                                  ("board_pipeline_rows_per_s","Host pipeline","#B14E28","o")):
        rate.plot(x,[g[key]/1e3 for g in groups],label=name,color=color,marker=marker)
    rate.set(ylim=(0,750),title="U280 throughput",ylabel="Thousand rows per second")
    for ax in (lat,rate):
        ax.set_xticks(list(x),[f"{n:,}" for n in sizes],rotation=25)
        ax.set_xlabel("Rows per batch")
        ax.grid(axis="y",alpha=.22)
        ax.spines[["right","top"]].set_visible(False)
        ax.legend(frameon=False,fontsize=8)
    fig.savefig(out,dpi=180)
    plt.close(fig)


if __name__=="__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ("corpus","board_capture","cpu"):
        p.add_argument(arg,type=Path)
    p.add_argument("--output",type=Path)
    p.add_argument("--plot",type=Path)
    a = p.parse_args()
    value = compare(a.corpus,a.board_capture,a.cpu)
    result = json.dumps(value,sort_keys=True,indent=2)
    if a.output:
        with a.output.open("x",encoding="utf-8",newline="\n") as f:
            f.write(result+"\n")
    else:
        print(result)
    if a.plot:
        check(not a.plot.exists(),"choose a new plot path")
        plot(value,a.plot)
