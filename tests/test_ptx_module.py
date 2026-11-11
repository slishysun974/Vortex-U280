"""C-role host tests. Synthetic vxbin fixtures are never executed on a device."""
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ptx_module as module
from ptx_launch import BufferHandle, BufferRegistry, BufferSlice

PROJECT = module.frontend.PROJECT


def synthetic_image(*, name=b"main", pc=0x180000000, low=0x180000000, high=0x180000010):
    # Structural fixture, not a compiled image. No executable-opcode assertion.
    return (struct.pack("<QQ", low, high) + b"\0" * 16 + name
            + struct.pack("<IHHQ", 0, len(name), 0, pc) + struct.pack("<I", 1) + b"VXSYMTAB")


class ModuleFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.out = self.root / "module"
        self.lock_path = PROJECT / "configs/target_lock.json"
        self.lock = self.lock_path.read_bytes()
        self.source = (PROJECT / "ptx/samples/vadd_u32.ptx").read_text()
        self.manifest = module.prepare(self.source, self.out, self.lock_path, PROJECT / "configs/native_smoke.json")

    def reject(self, code, operation):
        with self.assertRaises(module.ModuleError) as error:
            operation()
        self.assertEqual(error.exception.code, code)

    def write_manifest(self):
        module.write_json(self.out / "manifest.json", self.manifest)

    def rehash(self, name):
        self.manifest["files"][name] = module.digest((self.out / name).read_bytes())
        self.write_manifest()


class ModuleTests(ModuleFixture):
    def test_prepare_is_not_loadable(self):
        manifest, _ = module.verify_sources(self.out, self.lock)
        self.assertEqual(manifest["status"], "SOURCE_PREPARED")
        self.assertFalse(manifest["loadable"])
        self.assertEqual(manifest["backend_execution"], "NOT_RUN")
        self.reject("E_MODULE_NOT_BUILT", lambda: module.validate(self.out, self.lock))

    def test_target_and_missing_files_rejected(self):
        self.reject("E_TARGET_MISMATCH", lambda: module.verify_sources(self.out, self.lock + b" "))
        (self.out / "kernel.cpp").unlink()
        self.reject("E_MODULE_CORRUPT", lambda: module.verify_sources(self.out, self.lock))

    def test_content_corruption_and_rehashed_semantic_change(self):
        path = self.out / "kernel_body.hpp"
        path.write_text(path.read_text().replace(" + ", " - "))
        self.reject("E_MODULE_CORRUPT", lambda: module.verify_sources(self.out, self.lock))
        self.rehash("kernel_body.hpp")
        self.reject("E_MODULE_CORRUPT", lambda: module.verify_sources(self.out, self.lock))

    def test_manifest_layout_and_launch_cap_tampering(self):
        self.manifest["params"][0]["offset"] = 4
        self.write_manifest()
        self.reject("E_MODULE_CORRUPT", lambda: module.verify_sources(self.out, self.lock))
        self.manifest["params"][0]["offset"] = 0
        self.manifest["launch_limits"]["max_block_x"] = 1024
        self.write_manifest()
        self.reject("E_MODULE_CORRUPT", lambda: module.verify_sources(self.out, self.lock))

    def test_paths_and_duplicate_json_keys_rejected(self):
        for name in ("../outside", "C:\\file", "/absolute", ".."):
            with self.subTest(name=name):
                self.manifest["files"][name] = "0" * 64
                self.write_manifest()
                self.reject("E_MODULE_CORRUPT", lambda: module.verify_sources(self.out, self.lock))
                del self.manifest["files"][name]
        (self.out / "manifest.json").write_text('{"files":{},"files":{}}')
        self.reject("E_MODULE_CORRUPT", lambda: module.verify_sources(self.out, self.lock))

    def test_changed_build_recipe_rejected_even_after_rehash(self):
        with (self.out / "Makefile").open("a") as stream:
            stream.write("\nVX_CXX := g++\n")
        self.rehash("Makefile")
        self.reject("E_MODULE_CORRUPT", lambda: module.verify_sources(self.out, self.lock))

    def test_no_overwrite(self):
        original = (self.out / "manifest.json").read_bytes()
        with self.assertRaises(FileExistsError):
            module.prepare(self.source, self.out, self.lock_path, PROJECT / "configs/native_smoke.json")
        self.assertEqual((self.out / "manifest.json").read_bytes(), original)

    def test_explicit_candidate_limit_and_names(self):
        out = self.root / "candidate"
        candidate = PROJECT / "configs/candidates/block32-v1"
        renamed = self.source.replace("vadd_u32", "unknown_entry_17")
        manifest = module.prepare(renamed, out, candidate / "target_lock.json", candidate / "native_smoke.json")
        self.assertEqual(manifest["entry"], "unknown_entry_17")
        self.assertEqual(manifest["native_entry"], "main")
        self.assertEqual(manifest["launch_limits"]["max_block_x"], 32)
        self.assertEqual((out / "kernel.cpp").read_bytes(), (self.out / "kernel.cpp").read_bytes())
        module.verify_sources(out, (candidate / "target_lock.json").read_bytes())

    def test_vxbin_extent_and_entry_validation(self):
        good = synthetic_image()
        self.assertEqual(module.inspect_vxbin(good)["entry_pc"], 0x180000000)
        for bad in (good[:15], good[:-1], synthetic_image(name=b"other"),
                    synthetic_image(pc=0), synthetic_image(pc=0x180000010),
                    synthetic_image(high=0x180000001), synthetic_image(pc=0x180000001),
                    good[:-12] + struct.pack("<I", 0xffffffff) + b"VXSYMTAB"):
            with self.subTest(image=bad.hex()):
                self.reject("E_MODULE_CORRUPT", lambda: module.inspect_vxbin(bad))

    def test_validated_image_is_an_immutable_snapshot(self):
        elf = bytearray(64)
        elf[:7] = b"\x7fELF\x02\x01\x01"
        struct.pack_into("<HH", elf, 16, 2, 243)
        fixtures = {"kernel.vxbin": synthetic_image(), "kernel.elf": bytes(elf),
                    "program.disasm": b"STRUCTURAL TEST ONLY", "compile.log": b"TEST FIXTURE",
                    "build.json": json.dumps(dict(status="PASS", exit_code=0, source_commit=module.COMMIT,
                                                  target_lock_hash=module.digest(self.lock))).encode()}
        for name, data in fixtures.items():
            (self.out / name).write_bytes(data)
            self.manifest["files"][name] = module.digest(data)
        self.manifest.update(status="BUILT", loadable=True, image_file="kernel.vxbin", image_sha256=module.digest(fixtures["kernel.vxbin"]))
        self.write_manifest()
        _, image = module.validate(self.out, self.lock)
        (self.out / "kernel.vxbin").write_bytes(b"changed")
        self.assertEqual(image, fixtures["kernel.vxbin"])
        self.reject("E_MODULE_CORRUPT", lambda: module.validate(self.out, self.lock))

    def test_build_attempt_cannot_overwrite_failed_evidence(self):
        (self.out / "compile.log").write_text("old failure")
        self.reject("E_BUILD_ENV", lambda: module.build(self.out, self.root / "source", self.root / "build",
                                                       self.root / "tools", self.lock))
        self.assertEqual((self.out / "compile.log").read_text(), "old failure")


class LaunchTests(ModuleFixture):
    def setUp(self):
        super().setUp()
        self.registry = BufferRegistry()
        self.handles = [self.registry.register_native(2**40 + i * 0x1000, 256) for i in range(3)]
        self.args = [BufferSlice(h, 4, 28, access) for h, access in zip(self.handles, ("r", "r", "w"))] + [7]

    def plan(self, **changes):
        values = dict(manifest=self.manifest, entry=self.manifest["entry"], grid=(2, 1, 1), block=(4, 1, 1), args=self.args)
        values.update(changes)
        return self.registry.prepare(**values)

    def test_high_addresses_padding_and_argument_snapshot(self):
        plan = self.plan()
        self.assertEqual(plan.payload, struct.pack("<QQQI4x", *(2**40 + i * 0x1000 + 4 for i in range(3)), 7))
        self.args[-1] = 99
        self.assertEqual(plan.payload[24:28], (7).to_bytes(4, "little"))

    def test_foreign_freed_and_forged_handles(self):
        foreign = BufferRegistry().register_native(0x1000, 32)
        for handle in (foreign, BufferHandle()):
            self.reject("E_INVALID_BUFFER", lambda: self.plan(args=[BufferSlice(handle, 0, 4, "r")] + self.args[1:]))
        self.registry.retire(self.handles[0])
        self.reject("E_INVALID_BUFFER", self.plan)

    def test_ranges_and_access(self):
        for offset, size in ((-4, 4), (2, 4), (256, 0), (252, 8), (0, -4), (0, 3), (True, 4), (2**64, 4)):
            with self.subTest(offset=offset, size=size):
                self.reject("E_ADDRESS_RANGE", lambda: self.plan(args=[BufferSlice(self.handles[0], offset, size, "r")] + self.args[1:]))
        readonly = self.registry.register_native(0x2000, 32, "r")
        self.reject("E_ADDRESS_RANGE", lambda: self.registry.pointer(BufferSlice(readonly, 0, 4, "w")))
        self.reject("E_ADDRESS_RANGE", lambda: self.registry.register_native(2**64 - 4, 8))

    def test_scalar_and_dimension_rejection(self):
        for scalar in (-1, 2**32, True, 1.0):
            self.reject("E_PARAM_LAYOUT", lambda: self.plan(args=self.args[:3] + [scalar]))
        for dims in ((0, 1, 1), (1, 2, 1), (True, 1, 1), (1,), (2**31, 1, 1)):
            self.reject("E_LAUNCH_LIMIT", lambda: self.plan(grid=dims))
        self.reject("E_LAUNCH_LIMIT", lambda: self.plan(block=(17, 1, 1)))
        self.reject("E_LAUNCH_LIMIT", lambda: self.plan(grid=(2**31-1, 1, 1), block=(16, 1, 1)))
        self.reject("E_LAUNCH_LIMIT", lambda: self.plan(shared_bytes=4))
        self.reject("E_ENTRY", lambda: self.plan(entry="missing"))

    def test_inflight_pins_and_repeat_completion(self):
        plan = self.plan()
        self.registry.pin(plan)
        self.reject("E_BUSY", self.plan)
        for handle in self.handles:
            self.reject("E_BUSY", lambda: self.registry.retire(handle))
            self.reject("E_BUSY", lambda: self.registry.require_idle(handle))
        self.registry.complete(plan)
        self.registry.retire(self.handles[0])
        self.reject("E_EVENT", lambda: self.registry.complete(plan))

    def test_revalidate_at_submission_and_recovery_isolation(self):
        plan = self.plan()
        self.registry.retire(self.handles[0])
        self.reject("E_INVALID_BUFFER", lambda: self.registry.pin(plan))
        self.reject("E_UNAVAILABLE", lambda: self.registry.invalidate_after_isolation(isolated=False))
        self.registry.invalidate_after_isolation(isolated=True)
        self.assertEqual(self.registry.generation, 1)
        self.reject("E_INVALID_BUFFER", lambda: self.registry.pin(plan))
        self.reject("E_INVALID_BUFFER", self.plan)


@unittest.skipUnless(shutil.which(os.environ.get("CXX", "g++")), "host C++ compiler unavailable; no device claim")
class WrapperHostTests(unittest.TestCase):
    def test_generated_wrapper_serial_host_mapping(self):
        """Uses a TEST-ONLY CSR header. This is NOT Vortex compilation or SIMT."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "vx_spawn2.h").write_text('''#include <stdint.h>
#define __kernel extern "C"
#define __UNIFORM__
struct Dim { uint32_t x; };
static Dim threadIdx, blockIdx, blockDim, gridDim;
''')
            for name in ("copy_u32", "vadd_u32", "affine_u32"):
                source = (PROJECT / "ptx/samples" / (name + ".ptx")).read_text().replace(name, "renamed_kernel")
                ir = module.frontend.parse(source)
                cpp, _ = module.frontend.emit_cpp(ir)
                (root / "kernel_body.hpp").write_text(cpp)
                (root / "kernel.cpp").write_text(module.wrapper())
                # The harness is independent of kernel names: argv carries the
                # ordered payload's pointer count/scalars. Python owns oracle.
                parameters = []
                pointer_index = 0
                for param in ir["params"]:
                    if param["kind"] == "pointer":
                        array = ("x", "z") [pointer_index] if name == "copy_u32" else ("x", "y", "z")[pointer_index]
                        parameters.append(f"put(payload+{param['offset']}, n ? uintptr_t({array}+1) : 0, 8);")
                        pointer_index += 1
                    else:
                        # Sample scalar order is n, then alpha.
                        scalar = "n" if param["name"] == "n" else "0xffffffffu"
                        parameters.append(f"put(payload+{param['offset']}, {scalar}, 4);")
                harness = '''#include <cstdio>
#include <cstdlib>
#include "kernel.cpp"
static void put(uint8_t* p, uint64_t v, unsigned s) { for(unsigned i=0;i<s;++i) p[i]=v>>(8*i); }
int main(int argc, char** argv) {
 if(argc!=3) return 2;
 unsigned n=std::strtoul(argv[1],nullptr,10), b=std::strtoul(argv[2],nullptr,10);
 uint32_t x[300], y[300], z[300];
 for(unsigned i=0;i<300;++i){ x[i]=0xfffffff0u+i*17u; y[i]=0x80000000u+i*19u; z[i]=0xdeadbeefu; }
 uint8_t payload[64] = {};
''' + "\n".join(parameters) + '''
 blockDim.x=b; gridDim.x=(n+b-1)/b; if(!gridDim.x) gridDim.x=1;
 for(blockIdx.x=0;blockIdx.x<gridDim.x;++blockIdx.x)
   for(threadIdx.x=0;threadIdx.x<blockDim.x;++threadIdx.x) kernel_main(payload);
 for(unsigned i=0;i<300;++i) std::printf("%u %u %u\\n",x[i],y[i],z[i]);
}
'''
                (root / "check.cpp").write_text(harness)
                build = subprocess.run([os.environ.get("CXX", "g++"), "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror", "-I", str(root), str(root / "check.cpp"), "-o", str(root / "check")], capture_output=True, text=True, timeout=60)
                self.assertEqual(build.returncode, 0, build.stderr)
                for n in (0, 1, 7, 16, 17, 33, 257):
                    for b in (1, 4, 7, 16):
                        with self.subTest(kernel=name, n=n, block=b):
                            run = subprocess.run([str(root / "check"), str(n), str(b)], capture_output=True, text=True, timeout=10)
                            self.assertEqual(run.returncode, 0, run.stderr)
                            rows = [tuple(map(int, row.split())) for row in run.stdout.splitlines()]
                            self.assertEqual(len(rows), 300)
                            for i, (x, y, z) in enumerate(rows):
                                expected_x, expected_y = (0xfffffff0+i*17) & 0xffffffff, (0x80000000+i*19) & 0xffffffff
                                self.assertEqual((x, y), (expected_x, expected_y))
                                expected_z = 0xdeadbeef
                                if 1 <= i <= n:
                                    expected_z = expected_x if name == "copy_u32" else (expected_x+expected_y if name == "vadd_u32" else 0xffffffff*expected_x+expected_y) & 0xffffffff
                                self.assertEqual(z, expected_z)


if __name__ == "__main__":
    unittest.main()
