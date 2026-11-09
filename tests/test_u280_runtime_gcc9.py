"""Behavioral regressions for the isolated host-source/scaffold patch."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from prepare_u280_runtime_gcc9 import patch_make, patch_vm


class Gcc9RuntimePatchTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("g++"), "host g++ required")
    def test_actual_mapping_method_allocation_success_failure_and_cache(self):
        vm_source = ROOT / "upstream/vortex/sw/runtime/common/vm.cpp"
        if not vm_source.is_file():
            self.skipTest("Pinned Vortex submodule is required")
        source = vm_source.read_text(encoding="utf-8")
        patched = patch_vm(source)
        body = patched.split("uint64_t VMManager::map_p2v(", 1)[1].split("\nint VMManager::phy_to_virt_map", 1)[0]
        method = "uint64_t VMManager::map_p2v(" + body
        harness = r'''
#include <cstdint>
#include <random>
#include <unordered_map>
#include <cstdio>
#define VX_VM_PAGE_LOG2_SIZE 12
#define VX_VM_PAGE_SIZE 4096
#define VX_VM_ADDR_MODE 8
#define SV32 1
#define ALLOC_BASE_ADDR 4096
#define VX_MEM_PAGE_TABLE_BASE_ADDR 0x10000000
#define CHECK_ERR(expr, cleanup) do { auto err = (expr); if (err) { cleanup } } while (false)
struct Allocator {
  bool fail, reserve_ok;
  int allocate(uint64_t, uint64_t* out) { if (fail) return -1; *out = 0x7000; return 0; }
  int reserve(uint64_t, uint64_t) { return reserve_ok ? 0 : -1; }
};
struct VMManager {
  bool randomize_va_ = false;
  Allocator* virtual_mem_;
  std::mt19937_64 rng_{123};
  std::unordered_map<uint64_t, uint64_t> addr_mapping;
  int updates = 0, flushes = 0;
  uint64_t map_p2v(uint64_t, uint32_t);
  int update_page_table(uint64_t, uint64_t, uint32_t) { ++updates; return 0; }
  void flush() { ++flushes; }
};
uint32_t pte_flags_from_access(uint32_t flags) { return flags; }
'''
        harness += method + r'''
int main() {
  for (bool randomized : {false, true}) {
    Allocator alloc{true, false};
    VMManager vm; vm.virtual_mem_ = &alloc; vm.randomize_va_ = randomized;
    if (vm.map_p2v(17, 3) != UINT64_MAX || vm.updates || vm.flushes || !vm.addr_mapping.empty()) return 1;
    alloc.fail = false;
    if (vm.map_p2v(17, 3) != 7 || vm.updates != 1 || vm.flushes != 1) return 2;
    alloc.fail = true;
    if (vm.map_p2v(17, 3) != 7 || vm.updates != 1 || vm.flushes != 1) return 3;
  }
  Allocator alloc{true, true};
  VMManager vm; vm.virtual_mem_ = &alloc; vm.randomize_va_ = true;
  if (vm.map_p2v(18, 3) == UINT64_MAX || vm.updates != 1 || vm.flushes != 1) return 4;
  std::puts("PASS: allocation failure does not update mappings; success/cache/random reserve preserved");
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "probe.cpp").write_text(harness)
            compiled = subprocess.run(["g++", "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
                str(path / "probe.cpp"), "-o", str(path / "probe")], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            run = subprocess.run([str(path / "probe")], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    @unittest.skipUnless(shutil.which("make"), "GNU make required")
    def test_preparsed_flags_avoid_generator_but_missing_flags_still_generate(self):
        original = "XCONFIGS := $(shell printf called >> marker; printf -- -DGENERATED=1)\nall:\n\t@echo $(XCONFIGS)\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            for content, should_call in ((original, True), (patch_make(original), False)):
                (path / "Makefile").write_text(content)
                result = subprocess.run(["make", "XCONFIGS=-DFIXED=200"], cwd=tmp, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("-DFIXED=200", result.stdout)
                self.assertEqual((path / "marker").exists(), should_call)
                if (path / "marker").exists():
                    (path / "marker").unlink()
            result = subprocess.run(["make"], cwd=tmp, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("-DGENERATED=1", result.stdout)
            self.assertTrue((path / "marker").exists())


if __name__ == "__main__":
    unittest.main()
