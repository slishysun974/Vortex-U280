"""Bracket a retired launch with the fixed D10/D12 base MPM counters."""
import ctypes as C
import json

from ptx_module import write_json
from ptx_runtime import P, Q, U

COUNTERS = {"cycles": 0xB00, "instret": 0xB02}
COUNTER_LIMIT = 1 << 44  # D10 VX_gpu_pkg::PERF_CTR_BITS


def launch_delta(snapshots):
    idle, before, after, settled = (snapshots[key] for key in ("idle", "before", "after", "settled"))
    if idle != before or after != settled:
        raise ValueError("MPM changed while the device was idle")
    delta = {key: after[key] - before[key] for key in COUNTERS}
    if any(value <= 0 for value in delta.values()):
        raise ValueError("MPM did not advance for the retired launch")
    return delta


class CounterCapture:
    def __init__(self, ctx, output):
        self.ctx, self.output = ctx, output
        self.stream = (output / "counter-reads.jsonl").open("x", encoding="utf-8", newline="\n")
        self.record = dict(schema="u280-d10-d12-launch-mpm-v1", status="CHECKING",
                           core=0, mpm_class=0, addresses=COUNTERS, pilots=[], paired_launches=0)
        self.query = getattr(ctx.lib, "vx_device_mpm_query", None)
        if self.query is None:
            self.block("D12 does not export vx_device_mpm_query")
        else:
            self.query.argtypes, self.query.restype = [P, U, U, U, C.POINTER(Q)], C.c_int
        self.save()

    def save(self):
        write_json(self.output / "counter-status.json", self.record)

    def block(self, reason, **detail):
        self.record.update(status="BLOCKED", reason=reason, **detail)
        self.save()

    def snapshot(self, identity, phase):
        readings = {}
        for name, address in COUNTERS.items():
            value = Q(2**64 - 1)
            status = self.query(self.ctx.device, 0, address, 0, C.byref(value))
            self.stream.write(json.dumps(dict(identity, phase=phase, counter=name, address=address,
                                              exit_code=status, raw=value.value)) + "\n")
            self.stream.flush()
            if status:
                self.block("native MPM query failed", native_status=status, sample=identity, phase=phase, counter=name)
                self.ctx.check(status, "mpm_" + name)
            if value.value >= COUNTER_LIMIT:
                self.block("MPM response exceeds the D10 counter width", sample=identity, phase=phase, counter=name)
                return None
            readings[name] = value.value
        return readings

    def before(self, identity):
        if self.record["status"] == "BLOCKED":
            return None
        idle = self.snapshot(identity, "idle")
        if idle is None:
            return None
        before = self.snapshot(identity, "before")
        if before is None:
            return None
        if idle != before:
            self.block("MPM changed before launch with the device idle", sample=identity)
            return None
        return dict(idle=idle, before=before)

    def after(self, identity, snapshots):
        if snapshots is None:
            return None
        after = self.snapshot(identity, "after")
        if after is None:
            return None
        settled = self.snapshot(identity, "settled")
        if settled is None:
            return None
        try:
            delta = launch_delta(dict(snapshots, after=after, settled=settled))
        except ValueError as error:
            self.block(str(error), sample=identity)
            return None
        if identity["scope"] == "probe":
            self.record["pilots"].append(dict(identity, **delta))
            if len(self.record["pilots"]) == 2:
                if self.record["pilots"][0]["instret"] != delta["instret"]:
                    self.block("repeated bytewise probe retired different warp instruction counts", sample=identity)
                    return None
                self.record["status"] = "READABLE"
            self.save()
        else:
            self.record["paired_launches"] += 1
        return delta

    def close(self, expected):
        self.stream.close()
        if self.record["status"] == "READABLE" and self.record["paired_launches"] == expected:
            self.record["status"] = "PASS"
        elif self.record["status"] != "BLOCKED":
            self.record["status"] = "INCOMPLETE"
        self.save()
