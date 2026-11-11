"""Host-side V06 launch preflight; no allocation, device calls or CPU fallback.

A native backend must register addresses from its own allocator, pin a plan
before submission and release it only after completion is visible. Recovery
may invalidate this registry ONLY after the backend has isolated old work.
"""
from dataclasses import dataclass

import ptx_frontend_v12 as frontend
from ptx_module import ModuleError


@dataclass(frozen=True, eq=False)
class BufferHandle:
    """Opaque identity; address and size are kept in the backend registry."""
    pass


@dataclass(frozen=True)
class BufferSlice:
    buffer: BufferHandle
    offset: int
    access_bytes: int
    access: str


@dataclass(frozen=True, eq=False)
class LaunchPlan:
    native_entry: str
    grid: tuple
    block: tuple
    payload: bytes
    buffers: tuple
    generation: int


class BufferRegistry:
    """Backend metadata, not a simulated allocator or an executable runtime."""
    def __init__(self):
        self.generation = 0
        self._live = {}
        self._active = None
        self._plans = set()

    def register_native(self, device_address, size, access="rw"):
        if (type(device_address) is not int or type(size) is not int
                or not 0 < device_address < 2**64 or not 0 < size <= 2**64 - device_address
                or device_address % 4 or access not in ("r", "w", "rw")):
            raise ModuleError("E_ADDRESS_RANGE", "invalid native allocation", "alloc")
        handle = BufferHandle()
        self._live[handle] = (device_address, size, access)
        return handle

    def require_idle(self, handle):
        if not isinstance(handle, BufferHandle) or handle not in self._live:
            raise ModuleError("E_INVALID_BUFFER", "foreign, retired or stale buffer", "launch")
        if self._active and handle in self._active.buffers:
            raise ModuleError("E_BUSY", "buffer is referenced by in-flight work", "launch")

    def retire(self, handle):
        self.require_idle(handle)
        del self._live[handle]

    def pointer(self, arg):
        if not isinstance(arg, BufferSlice):
            raise ModuleError("E_INVALID_BUFFER", "pointer arguments require BufferSlice", "launch")
        self.require_idle(arg.buffer)
        base, size, allowed = self._live[arg.buffer]
        if (type(arg.offset) is not int or type(arg.access_bytes) is not int
                or arg.offset < 0 or arg.access_bytes < 0 or arg.offset >= size
                or arg.access_bytes > size - arg.offset or arg.offset % 4
                or arg.access_bytes % 4 or arg.access not in ("r", "w", "rw")
                or not set(arg.access) <= set(allowed)):
            raise ModuleError("E_ADDRESS_RANGE", "invalid pointer range/alignment/access", "launch")
        return base + arg.offset

    def prepare(self, manifest, entry, grid, block, args, shared_bytes=0):
        if self._active is not None:
            raise ModuleError("E_BUSY", "only one launch may be in flight", "launch")
        # This function accepts metadata returned by ptx_module.validate or
        # verify_sources for offline planning; it cannot submit either one.
        if entry != manifest["entry"]:
            raise ModuleError("E_ENTRY", "unknown PTX entry", "launch")
        for dim in (grid, block):
            if (not isinstance(dim, (tuple, list)) or len(dim) != 3
                    or any(type(v) is not int or v <= 0 for v in dim) or tuple(dim[1:]) != (1, 1)):
                raise ModuleError("E_LAUNCH_LIMIT", "requires positive one-dimensional launch", "launch")
        limits = manifest["launch_limits"]
        if (grid[0] > limits["max_grid_x"] or block[0] > limits["max_block_x"]
                or grid[0] * block[0] > limits["max_total_threads"]
                or type(shared_bytes) is not int or shared_bytes != 0):
            raise ModuleError("E_LAUNCH_LIMIT", "launch exceeds target/profile limits", "launch")
        if len(args) != len(manifest["params"]):
            raise ModuleError("E_PARAM_LAYOUT", "argument count mismatch", "launch")
        values, handles = [], []
        for param, value in zip(manifest["params"], args):
            if param["kind"] == "pointer":
                values.append(self.pointer(value))
                if value.buffer not in handles:
                    handles.append(value.buffer)
            else:
                if type(value) is not int or not 0 <= value < 2**32:
                    raise ModuleError("E_PARAM_LAYOUT", "expected u32 scalar", "launch")
                values.append(value)
        payload = frontend.pack_arguments(manifest, values)
        plan = LaunchPlan(manifest["native_entry"], tuple(grid), tuple(block),
                          payload, tuple(handles), self.generation)
        self._plans.add(plan)
        return plan

    def pin(self, plan):
        if plan not in self._plans or plan.generation != self.generation:
            raise ModuleError("E_INVALID_BUFFER", "foreign or stale launch plan", "launch")
        if self._active:
            raise ModuleError("E_BUSY", "launch already in flight", "launch")
        for handle in plan.buffers:
            self.require_idle(handle)
        self._active = plan
        self._plans.remove(plan)

    def complete(self, plan):
        """Backend-only hook: call AFTER completion and memory visibility."""
        if plan is not self._active:
            raise ModuleError("E_EVENT", "not the active plan", "wait")
        self._active = None

    def invalidate_after_isolation(self, *, isolated):
        if isolated is not True:
            raise ModuleError("E_UNAVAILABLE", "old transactions are not isolated", "recover")
        self._active = None
        self._plans.clear()
        self._live.clear()
        self.generation += 1
