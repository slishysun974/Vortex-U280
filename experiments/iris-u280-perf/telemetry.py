"""Read available XRT and hwmon sensors for the selected PCI slot."""
import json
from pathlib import Path
import re
import subprocess
import threading
import time


def snapshot(bdf, root, name):
    target = root / (name+".json")
    cmd = ["xbutil","examine","--device",bdf,"--report","thermal","electrical","--format","JSON","--output",str(target)]
    try:
        result = subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=20)
        code, message = result.returncode, result.stdout.decode(errors="replace")
    except (OSError,subprocess.TimeoutExpired) as err:
        code, message = None, str(err)
    (root/(name+"-command.json")).write_text(json.dumps(dict(argv=cmd,exit_code=code,output=message)))


class Sensors:
    def __init__(self, bdf, root):
        self.root = root
        self.paths = {}
        slots = {bdf, bdf[:-1]+"0"}
        for device in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
            if not slots.intersection(device.resolve().parts):
                continue
            for p in sorted(device.iterdir()):
                if re.fullmatch(r"(?:temp\d+_input|power\d+_(?:input|average))",p.name):
                    label = p.with_name(p.name.split("_")[0]+"_label")
                    key = device.name+"/"+p.name
                    self.paths[key] = dict(path=str(p),label=label.read_text().strip() if label.is_file() else key,
                                           unit="mC" if p.name.startswith("temp") else "uW")
        (root/"sensor-map.json").write_text(json.dumps(self.paths,indent=2))
        self.done = threading.Event()
        self.thread = threading.Thread(target=self.collect)

    def collect(self):
        with (self.root/"sensors.jsonl").open("x") as stream:
            while True:
                values = {}
                for key,spec in self.paths.items():
                    try:
                        values[key] = int(Path(spec["path"]).read_text().strip())
                    except (OSError, ValueError):
                        values[key] = None
                stream.write(json.dumps(dict(monotonic_s=time.perf_counter(),values=values))+"\n")
                stream.flush()
                if self.done.wait(0.5):
                    break

    def stop(self):
        self.done.set()
        self.thread.join()
