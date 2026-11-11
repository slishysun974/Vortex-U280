"""Single-queue Vortex2 adapter for explicitly verified simulation builds.

The caller starts a dedicated process with the selected driver and the binding's
library directory first in LD_LIBRARY_PATH. No CPU fallback or hardware reset.
"""
import ctypes as C
from dataclasses import dataclass
import json
import os
from pathlib import Path
from threading import RLock

from ptx_launch import BufferRegistry, BufferSlice
from ptx_module import COMMIT, ModuleError, digest, read_json, validate
from runtime_backends import BACKENDS, validate_native

P = C.c_void_p
U = C.c_uint32
Q = C.c_uint64
S = C.c_size_t


class QueueInfo(C.Structure):
    _fields_ = [("struct_size", S), ("next", P), ("priority", C.c_int), ("flags", U)]


class LaunchInfo(C.Structure):
    _fields_ = [("struct_size", S), ("next", P), ("kernel", P), ("args_host", P),
                ("args_size", S), ("ndim", U), ("grid_dim", U * 3), ("block_dim", U * 3),
                ("lmem_size", U), ("cluster_dim", U * 3)]


def api(library):
    signatures = {
        "vx_device_open": [U, C.POINTER(P)], "vx_device_release": [P],
        "vx_device_query": [P, U, C.POINTER(Q)],
        "vx_queue_create": [P, C.POINTER(QueueInfo), C.POINTER(P)],
        "vx_queue_release": [P], "vx_queue_finish": [P, Q],
        "vx_buffer_create": [P, Q, U, C.POINTER(P)],
        "vx_buffer_release": [P], "vx_buffer_address": [P, C.POINTER(Q)],
        "vx_module_load_bytes": [P, P, S, C.POINTER(P)],
        "vx_module_get_kernel": [P, C.c_char_p, C.POINTER(P)],
        "vx_module_release": [P], "vx_kernel_release": [P],
        "vx_enqueue_write": [P, P, Q, P, Q, U, P, P],
        "vx_enqueue_read": [P, P, P, Q, Q, U, P, P],
        "vx_enqueue_launch": [P, C.POINTER(LaunchInfo), U, P, C.POINTER(P)],
        "vx_event_wait_value": [P, Q, Q], "vx_event_release": [P],
    }
    for name, arguments in signatures.items():
        function = getattr(library, name)
        function.argtypes, function.restype = arguments, C.c_int
    return library


class RuntimeError(ModuleError):
    def __init__(self, code, message, context, phase, native_status=None):
        super().__init__(code, message, phase)
        self.detail = dict(backend=context.backend, generation=context.registry.generation,
                           run_id=context.run_id, event_id=context.active.id if context.active else None,
                           native_status=native_status, device_state=context.state)

    def to_dict(self):
        return dict(super().to_dict(), **self.detail)


@dataclass(eq=False)
class Module:
    manifest: dict
    native: P
    kernel: P


@dataclass(eq=False)
class Event:
    id: int
    native: P
    module: Module
    plan: object
    payload: object
    completed: bool = False


def serialized(method):
    def call(self, *args, **kwargs):
        with self.mutex:
            try:
                return method(self, *args, **kwargs)
            except RuntimeError:
                raise
            except ModuleError as error:
                raise RuntimeError(error.code, str(error), self, method.__name__) from error
    call.__name__ = method.__name__
    return call


class Context:
    def __init__(self, binding_path, target_lock, *, backend="simx", run_id=None):
        self.backend, self.run_id = backend, run_id
        self.registry, self.mutex = BufferRegistry(), RLock()
        self.state, self.active, self.first_error = "READY", None, None
        self.device_fault = None
        self.buffers, self.modules, self.events = {}, set(), set()
        self.device, self.queue, self.sequence = P(), P(), 0
        self.lock_bytes = Path(target_lock).read_bytes()
        binding_path = Path(binding_path).resolve()
        if backend == "u280-xrt":
            from ptx_u280 import open_context
            open_context(self, binding_path)
            return
        binding = read_json(binding_path.read_bytes())
        if backend not in BACKENDS or binding.get("backend") != backend:
            self.fail("E_UNAVAILABLE", "requires an explicitly bound simulation backend", "open")
        driver, backend_library, simulator_library = BACKENDS[backend]
        schema = binding.get("schema_version")
        if (schema not in ("ptx-vx-runtime-binding-v2", "ptx-vx-runtime-binding-v3")
                or (schema == "ptx-vx-runtime-binding-v2" and backend != "simx")
                or binding.get("source_commit") != COMMIT
                or binding.get("target_lock_hash") != digest(self.lock_bytes)):
            self.fail("E_TARGET_MISMATCH", "runtime build binding differs from target", "open")
        if schema == "ptx-vx-runtime-binding-v3":
            native_bytes = (binding_path.parent / "native-summary.json").read_bytes()
            if (digest(native_bytes) != binding.get("native_summary_sha256")
                    or binding.get("driver") != driver):
                self.fail("E_TARGET_MISMATCH", "native execution proof/driver differs", "open")
            try:
                native = read_json(native_bytes)
                validate_native(native, backend, digest(self.lock_bytes))
                for name in ('libvortex.so', backend_library, simulator_library):
                    if native['build_artifacts']['sw/runtime/'+name]['sha256'] != binding['libraries'][name]:
                        raise ValueError('bound library differs from native execution')
            except (ValueError, KeyError, TypeError) as error:
                self.fail("E_TARGET_MISMATCH", str(error), "open")
        hardware_bytes = (binding_path.parent / "hardware.json").read_bytes()
        if digest(hardware_bytes) != read_json(self.lock_bytes)["hardware_config_sha256"]:
            self.fail("E_TARGET_MISMATCH", "runtime hardware config differs from lock", "open")
        hardware = read_json(hardware_bytes)
        if hardware["defines"] != binding.get("hardware_defines"):
            self.fail("E_TARGET_MISMATCH", "runtime defines differ from bound config", "open")
        libdir = (binding_path.parent / binding["library_dir"]).resolve()
        if (os.environ.get("VORTEX_DRIVER") != driver
                or Path(os.environ.get("LD_LIBRARY_PATH", "").split(":")[0]).resolve() != libdir):
            self.fail("E_UNAVAILABLE", "start process with explicit backend and library search path", "open")
        for name in ("libvortex.so", backend_library, simulator_library):
            if digest((libdir / name).read_bytes()) != binding.get("libraries", {}).get(name):
                self.fail("E_TARGET_MISMATCH", "runtime library hash mismatch: " + name, "open")
        for name, expected in binding["dependencies"].items():
            if digest(Path(name).read_bytes()) != expected:
                self.fail("E_TARGET_MISMATCH", "simulator dependency hash mismatch: " + name, "open")
        self.lib = api(C.CDLL(str(libdir / "libvortex.so")))
        self.check(self.lib.vx_device_open(0, C.byref(self.device)), "open")
        try:
            self.caps = {}
            for name, key in (("threads", 1), ("warps", 2), ("cores", 3), ("isa_flags", 7), ("clusters", 10)):
                value = Q()
                self.check(self.lib.vx_device_query(self.device, key, C.byref(value)), "query_caps")
                self.caps[name] = value.value
            expected = binding["hardware_defines"]
            wanted = dict(threads=expected["VX_CFG_NUM_THREADS"], warps=expected["VX_CFG_NUM_WARPS"],
                          cores=expected["VX_CFG_NUM_CORES"] * expected["VX_CFG_NUM_CLUSTERS"],
                          clusters=expected["VX_CFG_NUM_CLUSTERS"])
            if any(self.caps[k] != v for k, v in wanted.items()) or 1 << (((self.caps["isa_flags"] >> 30) & 3) + 4) != 64:
                self.fail("E_TARGET_MISMATCH", "actual device geometry/XLEN differs", "open")
            # Verify the backend dlopen actually resolved the checked file.
            maps = Path('/proc/self/maps').read_text()
            if any(str(libdir / name) not in maps for name in (backend_library, simulator_library)):
                self.fail("E_TARGET_MISMATCH", "loaded backend does not match binding", "open")
            if any(name not in maps for name in binding["dependencies"]):
                self.fail("E_TARGET_MISMATCH", "loaded simulator dependency differs from binding", "open")
            info = QueueInfo(C.sizeof(QueueInfo), None, 1, 0)
            self.check(self.lib.vx_queue_create(self.device, C.byref(info), C.byref(self.queue)), "open")
        except Exception:
            self.lib.vx_device_release(self.device)
            raise

    def fail(self, code, message, phase, native_status=None):
        raise RuntimeError(code, message, self, phase, native_status)

    def check(self, status, phase):
        if status:
            self.state = "NEEDS_RECOVERY"
            if self.first_error is None:
                self.first_error = dict(native_status=status, phase=phase)
            # Queue::finish clears its native async_error after reporting it.
            # A later successful barrier does not prove the failed CP command
            # stopped accessing memory. Never forget a non-timeout failure.
            if status != 7 and getattr(self, "device_fault", None) is None:
                self.device_fault = dict(native_status=status, phase=phase)
            self.fail("E_TIMEOUT" if status == 7 else "E_DEVICE", "native Vortex2 operation failed", phase, status)

    def ready(self, phase, *, allow_running=False):
        if self.state == "RUNNING" and not allow_running:
            self.fail("E_BUSY", "single-queue context has in-flight work", phase)
        if self.state not in ("READY", "RUNNING"):
            self.fail("E_UNAVAILABLE", "context is " + self.state, phase)

    @staticmethod
    def timeout_ns(timeout_ms):
        if type(timeout_ms) is not int or not 0 <= timeout_ms < (2**64 - 1) // 1000000:
            raise ModuleError("E_PARAM_LAYOUT", "invalid finite timeout", "wait")
        return timeout_ms * 1000000

    @serialized
    def query_caps(self):
        return dict(self.caps, backend=self.backend, device_state=self.state,
                    generation=self.registry.generation, safe_abort=False,
                    recovery_mode="unavailable" if self.backend == "u280-xrt" else "timeout-drain-only",
                    max_modules=1,
                    device_fault=dict(self.device_fault) if getattr(self, "device_fault", None) else None,
                    first_error=dict(self.first_error) if self.first_error else None)

    @serialized
    def alloc(self, size, alignment=4):
        self.ready("alloc")
        if type(size) is not int or not 0 < size < 2**64 or alignment != 4:
            self.fail("E_ADDRESS_RANGE", "positive size and four-byte alignment required", "alloc")
        native, address = P(), Q()
        self.check(self.lib.vx_buffer_create(self.device, size, 3, C.byref(native)), "alloc")
        try:
            self.check(self.lib.vx_buffer_address(native, C.byref(address)), "alloc")
            handle = self.registry.register_native(address.value, size)
        except Exception:
            self.lib.vx_buffer_release(native)
            raise
        self.buffers[handle] = (native, size)
        return handle

    def range(self, handle, offset, size):
        self.registry.require_idle(handle)
        native, capacity = self.buffers[handle]
        if (type(offset) is not int or type(size) is not int or offset < 0 or size < 0
                or offset > capacity or size > capacity - offset):
            self.fail("E_ADDRESS_RANGE", "transfer exceeds allocation", "transfer")
        return native

    @serialized
    def write(self, handle, offset, data):
        self.ready("write")
        if not isinstance(data, (bytes, bytearray, memoryview)):
            self.fail("E_PARAM_LAYOUT", "write requires a bytes-like object", "write")
        data = bytes(data)
        native = self.range(handle, offset, len(data))
        if not data:
            return
        host = C.create_string_buffer(data)
        # Keep host storage alive if the queue fails to drain.
        self.pending_transfer = host
        self.check(self.lib.vx_enqueue_write(self.queue, native, offset, host, len(data), 0, None, None), "write")
        self.check(self.lib.vx_queue_finish(self.queue, self.timeout_ns(60000)), "write")
        self.pending_transfer = None

    @serialized
    def read(self, handle, offset, size):
        self.ready("read")
        native = self.range(handle, offset, size)
        if not size:
            return b""
        host = C.create_string_buffer(size)
        self.pending_transfer = host
        self.check(self.lib.vx_enqueue_read(self.queue, host, native, offset, size, 0, None, None), "read")
        self.check(self.lib.vx_queue_finish(self.queue, self.timeout_ns(60000)), "read")
        self.pending_transfer = None
        return host.raw

    @serialized
    def load(self, directory):
        self.ready("load")
        # Fixed images can overlap in device address space. Until relocation or
        # concurrent module ownership is supported, reject before native loading.
        if self.modules:
            self.fail("E_BUSY", "unload the current module before loading another", "load")
        manifest, image = validate(directory, self.lock_bytes)
        if manifest["launch_limits"]["max_block_x"] > self.caps["threads"] * self.caps["warps"]:
            self.fail("E_TARGET_MISMATCH", "module launch limit exceeds actual device", "load")
        native, kernel = P(), P()
        snapshot = C.create_string_buffer(image)
        self.check(self.lib.vx_module_load_bytes(self.device, snapshot, len(image), C.byref(native)), "load")
        try:
            self.check(self.lib.vx_module_get_kernel(native, manifest["native_entry"].encode(), C.byref(kernel)), "load")
        except Exception:
            self.lib.vx_module_release(native)
            raise
        result = Module(manifest, native, kernel)
        self.modules.add(result)
        return result

    @serialized
    def launch(self, module, entry, grid, block, args, shared_bytes=0):
        self.ready("launch")
        if module not in self.modules:
            self.fail("E_MODULE_CORRUPT", "foreign or unloaded module", "launch")
        plan = self.registry.prepare(module.manifest, entry, grid, block, args, shared_bytes)
        payload = C.create_string_buffer(plan.payload)
        info = LaunchInfo()
        info.struct_size, info.kernel = C.sizeof(info), module.kernel
        info.args_host, info.args_size = C.cast(payload, P), len(plan.payload)
        info.ndim, info.grid_dim, info.block_dim = 1, (U * 3)(*grid), (U * 3)(*block)
        native = P()
        self.registry.pin(plan)
        self.sequence += 1
        event = Event(self.sequence, native, module, plan, payload)
        self.events.add(event)
        self.active = event
        self.state = "RUNNING"
        self.check(self.lib.vx_enqueue_launch(self.queue, C.byref(info), 0, None, C.byref(native)), "launch")
        return event

    @serialized
    def wait(self, event, timeout_ms=60000):
        self.ready("wait", allow_running=True)
        if event not in self.events:
            self.fail("E_EVENT", "foreign or stale event", "wait")
        timeout = self.timeout_ns(timeout_ms)
        if not event.completed:
            self.check(self.lib.vx_event_wait_value(event.native, 1, timeout), "wait")
            self.check(self.lib.vx_event_release(event.native), "wait")
            event.native = P()
            self.registry.complete(event.plan)
            event.completed = True
            event.payload = None
            self.active, self.state = None, "READY"
        return dict(status="COMPLETE", event_id=event.id, generation=self.registry.generation, backend=self.backend)

    @serialized
    def free(self, handle):
        self.ready("free")
        self.registry.require_idle(handle)
        self.check(self.lib.vx_buffer_release(self.buffers[handle][0]), "free")
        self.registry.retire(handle)
        del self.buffers[handle]

    @serialized
    def unload(self, module):
        self.ready("unload")
        if module not in self.modules:
            self.fail("E_MODULE_CORRUPT", "foreign or unloaded module", "unload")
        self.check(self.lib.vx_kernel_release(module.kernel), "unload")
        module.kernel = P()
        self.check(self.lib.vx_module_release(module.native), "unload")
        self.modules.remove(module)

    def release_resources(self):
        for event in self.events:
            if event.native:
                self.check(self.lib.vx_event_release(event.native), "release")
                event.native = P()
        for module in list(self.modules):
            if module.kernel:
                self.check(self.lib.vx_kernel_release(module.kernel), "release")
                module.kernel = P()
            self.check(self.lib.vx_module_release(module.native), "release")
            self.modules.remove(module)
        for handle, (native, _) in list(self.buffers.items()):
            self.check(self.lib.vx_buffer_release(native), "release")
            del self.buffers[handle]

    @serialized
    def recover(self, timeout_ms=60000):
        if self.state != "NEEDS_RECOVERY":
            self.fail("E_UNAVAILABLE", "recovery requires a failed or timed-out context", "recover")
        if self.backend == "u280-xrt":
            self.fail("E_UNAVAILABLE", "U280 fault isolation/recovery is not accepted; retain resources", "recover")
        timeout = self.timeout_ns(timeout_ms)
        if getattr(self, "device_fault", None):
            self.fail("E_UNAVAILABLE", "native device fault requires external isolation; retain resources", "recover")
        # Drain only: no claim of safe abort or reset. On failure all resources
        # stay owned; in particular close must not release in-flight memory.
        self.check(self.lib.vx_queue_finish(self.queue, timeout), "recover")
        # Verify the original launch, not just the trailing queue barrier.
        if self.active and self.active.native:
            self.check(self.lib.vx_event_wait_value(self.active.native, 1, 0), "recover_event")
        self.release_resources()
        self.registry.invalidate_after_isolation(isolated=True)
        self.events.clear()
        self.pending_transfer = None
        self.active, self.state = None, "READY"
        return dict(status="RECOVERED", isolated=True, generation=self.registry.generation,
                    device_state=self.state, mechanism="successful-queue-and-event-drain",
                    safe_abort=False)

    @serialized
    def close(self):
        if self.state == "CLOSED":
            return
        if self.state != "READY":
            self.fail("E_BUSY", "wait or successfully drain recovery before close", "close")
        self.release_resources()
        self.check(self.lib.vx_queue_release(self.queue), "close")
        self.check(self.lib.vx_device_release(self.device), "close")
        self.registry.invalidate_after_isolation(isolated=True)
        self.events.clear()
        self.state = "CLOSED"
        if self.backend == "u280-xrt":
            self.board_gate.closed()
