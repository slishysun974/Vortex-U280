"""Derive an isolated GCC 9 runtime candidate from immutable D11 input."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tarfile

from u280_remote_runtime import unpack_archive

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "results/u280-runtime-prepare-20261109-v1"
PARENT_SHA = "9976e187005d38005c1733d0bc5e9f337450109252bb908662fc9c4839c79b84"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def patch_vm(text):
    old = "virtual_mem_->allocate(VX_VM_PAGE_SIZE, &vpn);"
    if text.count(old) != 2:
        raise ValueError("unexpected pinned VM allocator calls")
    # A failed allocator does not initialize vpn. Return an invalid page number
    # before shifting it or modifying the page tables/mapping cache.
    return text.replace("      " + old, "      if (virtual_mem_->allocate(VX_VM_PAGE_SIZE, &vpn) != 0) {\n        return UINT64_MAX;\n      }").replace(
        "    " + old, "    if (virtual_mem_->allocate(VX_VM_PAGE_SIZE, &vpn) != 0) {\n      return UINT64_MAX;\n    }")


def patch_make(text):
    lines = [line for line in text.splitlines() if line.startswith("XCONFIGS := $(shell ")]
    if len(lines) != 1:
        raise ValueError("unexpected generated common.mk")
    return text.replace(lines[0], "ifeq ($(origin XCONFIGS), undefined)\n" + lines[0] + "\nendif")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    import re
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", args.run_id):
        parser.error("unsafe run id")
    archive = PARENT / "u280-runtime200-input.tar.gz"
    if sha(archive) != PARENT_SHA:
        raise ValueError("D11 package changed")
    output = ROOT / "results" / args.run_id
    output.mkdir(exist_ok=False)
    package = unpack_archive(archive, output / "extracted")
    manifest = json.loads((package / "manifest.json").read_text())
    for item in manifest:
        if sha(package / item["path"]) != item["sha256"]:
            raise ValueError("D11 package member changed")
    changes = []
    diff = []
    for name, transform in (
        ("source/sw/runtime/common/vm.cpp", patch_vm),
        ("source/sw/runtime/common/vm.h", lambda t: t.replace(
            "  uint64_t map_p2v(uint64_t ppn, uint32_t flags);",
            "  // Returns UINT64_MAX if the virtual-page allocation fails.\n  uint64_t map_p2v(uint64_t ppn, uint32_t flags);")),
        ("build/sw/runtime/common.mk", patch_make),
    ):
        path = package / name
        original_sha = sha(path)
        before = path.read_text(encoding="utf-8")
        after = transform(before)
        if after == before:
            raise ValueError("patch did not apply: " + name)
        path.write_text(after, encoding="utf-8", newline="\n")
        changes.append(dict(path=name, before_sha256=original_sha, after_sha256=sha(path)))
        diff.extend(difflib.unified_diff(before.splitlines(True), after.splitlines(True), "a/" + name, "b/" + name))
    binding_path = package / "binding.json"
    binding = json.loads(binding_path.read_text())
    binding.update(schema_version="u280-runtime200-binding-v2", runtime_profile="gcc9-vm-allocation-v1",
        parent_package_sha256=PARENT_SHA, parent_binding_sha256=sha(PARENT / "binding.json"), patches=changes,
        note="Isolated host source/scaffold patch; identical FPGA/clock/defines and exported C API. VM remains disabled; not VM acceptance.",
        followup="D12-VM-01: before VM enable, review map_p2v failure API, unused callers, page-table and flush error propagation.")
    for item in binding["source_files"]:
        path = package / "source" / item["path"]
        item.update(bytes=path.stat().st_size, sha256=sha(path))
    binding_path.write_text(json.dumps(binding, indent=2) + "\n")
    manifest = [dict(path=p.relative_to(package).as_posix(), bytes=p.stat().st_size, sha256=sha(p))
                for p in sorted(package.rglob("*")) if p.is_file() and p.name != "manifest.json"]
    (package / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    target = output / "u280-runtime200-input.tar.gz"
    with tarfile.open(target, "w:gz") as tar:
        for path in sorted(package.rglob("*")):
            if path.is_file():
                tar.add(path, arcname="u280-runtime200-input/" + path.relative_to(package).as_posix(), recursive=False)
    for name in ("binding.json", "manifest.json", "resolved.cflags"):
        shutil.copy2(package / name, output / name)
    (output / "runtime.patch").write_text("".join(diff), encoding="utf-8")
    shutil.copy2(__file__, output / Path(__file__).name)
    result = dict(status="PASS", exit_code=0, argv=sys.argv, scope="derived source package only",
        runtime_profile="gcc9-vm-allocation-v1", parent_package_sha256=PARENT_SHA,
        package=dict(path=target.name, sha256=sha(target), bytes=target.stat().st_size),
        binding=binding, package_files=len(manifest), server_runtime="NOT_RUN", board_execution="NOT_RUN")
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(dict(status=result["status"], package=result["package"])))


if __name__ == "__main__":
    main()
